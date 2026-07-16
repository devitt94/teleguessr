from datetime import datetime, timedelta
from pathlib import Path
import traceback

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application as TelegramApp, ConversationHandler
from telegram.error import NetworkError

from teleguessr.awards import get_ranked_guesses
from teleguessr.bets import BetManager
from teleguessr.challenge_settings_generators import (
    CHALLENGE_SETTINGS,
    ChallengeSettingsGenerator,
)
from teleguessr.formatters import (
    format_awards_html,
    format_challenge_settings,
    format_leaderboard_html,
    format_round_result_html,
    format_time,
)
from teleguessr.odds import FractionalOdds
from teleguessr.predictions import generate_outright_odds_predictions
from teleguessr.replay import replay_league
from teleguessr.record_manager import RecordManager
from teleguessr.geoguessr_scraper import GeoguessrClient
from teleguessr.league import (
    LeagueState,
    skewed_ranking_score_manager,
)
from teleguessr.models import AbbreviatedRoundScore, ChallengeResult, RankedGuess
from teleguessr.settings import (
    LeagueSettings,
    TELEGRAM_ID_TO_PLAYER_NAME,
    PLAYER_NAME_TO_TELEGRAM_ID,
    ModelSettings,
)
from loguru import logger

from teleguessr.handicaps import (
    calculate_new_handicaps,
    get_latest_handicaps,
    update_handicaps,
)
from teleguessr.ranks import get_ranks_from_scores

from telegram.ext import ContextTypes


BET_SELECT_PLAYER, BET_SELECT_AMOUNT = range(2)

NUMBER_EMOJI_MAP = {
    1: "1️⃣",
    2: "2️⃣",
    3: "3️⃣",
    4: "4️⃣",
    5: "5️⃣",
    6: "6️⃣",
    7: "7️⃣",
    8: "8️⃣",
    9: "9️⃣",
    10: "🔟",
}


class BotManager:
    def __init__(
        self,
        admin_id: int,
        players_lounge_group_id: int | None,
        data_dir: Path,
        polling_interval_seconds: int,
        league_settings: LeagueSettings,
        model_settings: ModelSettings,
        geoguessr_client: GeoguessrClient,
    ):
        self.admin_id = admin_id
        self.players_lounge_group_id = players_lounge_group_id
        self.data_dir = data_dir
        self.polling_interval_seconds = polling_interval_seconds
        self.league_settings = league_settings
        self.model_settings = model_settings
        self.league_state = None
        self.bet_manager = None
        self.__initialised = False
        self.geoguessr_client = geoguessr_client

        self.challenge_settings_generator: ChallengeSettingsGenerator = (
            CHALLENGE_SETTINGS[league_settings.challenge_settings_name]
        )

    @property
    def active_league_dir(self) -> Path:
        return self.data_dir / "leagues" / "active"

    @property
    def finished_league_dir(self) -> Path:
        return self.data_dir / "leagues" / "finished"

    async def initialise(self):
        self.active_league_dir.mkdir(parents=True, exist_ok=True)
        self.finished_league_dir.mkdir(parents=True, exist_ok=True)

        active_leagues = list(self.active_league_dir.glob("*.json"))

        if len(active_leagues) > 1:
            raise RuntimeError("Multiple active leagues not supported!")

        if active_leagues:
            state_file = active_leagues[0]
            logger.info(f"Loading league state from {state_file}")
            self.league_state = LeagueState(
                filepath=state_file, num_rounds=self.league_settings.number_of_rounds
            )
            self.league_state.load_from_file()

        else:
            logger.info("No active league found.")

        self.handicaps = get_latest_handicaps(self.league_settings)

        if self.league_state is not None:
            self.bet_manager = BetManager(
                model_settings=self.model_settings,
                data_dir=self.data_dir,
                league_date=self.league_state.start_date,
            )
            self.record_manager = RecordManager(data_dir=self.data_dir)

        self.__initialised = True

    async def resume_league_tasks(self, app: TelegramApp):
        if not self.__initialised:
            raise RuntimeError("BotManager not initialised!")

        if self.league_state is None or self.league_state.is_finished:
            logger.info("No active league to resume tasks for.")
            return

        if not self.league_state.round_in_progress:
            logger.info("No round in progress to resume tasks for. Starting new round.")
            chat_id = self.league_state.chat_id
            await self.start_round(app, chat_id=chat_id)
            return

        logger.info("Resuming round update polling for active round.")
        app.job_queue.run_repeating(
            self.poll_for_round_updates,
            interval=self.polling_interval_seconds,
            first=0,
        )

    async def help_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        help_message = (
            "🤖 <b>Teleguessr Bot Commands</b> 🤖\n\n"
            "/startleague - Start a new league (admin only)\n"
            "/endround - End the current round (admin only)\n"
            "/status - Get the current status of the league and your round\n"
            "/handicaps - Show current handicaps\n"
            "/lounge - Get an invite to the Players' Lounge group chat (after playing your round)\n"
            "/bet - Place a bet on the league winner\n"
            "/position - Show your current betting position\n"
            "/guesses - Show current round guesses and rankings\n"
            "/records - Show all-time records\n"
            "/help - Show this help message\n\n"
        )

        await update.message.reply_text(
            help_message,
            parse_mode="HTML",
        )

    async def odds_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.__initialised:
            raise RuntimeError("BotManager not initialised!")

        if self.league_state is None or self.league_state.is_finished:
            await update.message.reply_text(
                "No active league. Start a new league with /startleague."
            )
            return

        await self.display_odds(context, chat_id=update.effective_chat.id)

    async def position_handler(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        if not self.__initialised:
            raise RuntimeError("BotManager not initialised!")

        if self.league_state is None or self.league_state.is_finished:
            await update.message.reply_text(
                "No active league. Start a new league with /startleague."
            )
            return

        player_id = update.effective_user.id
        all_runners = list(self.handicaps.keys())

        if player_id == self.admin_id:
            positions = self.bet_manager.compute_bookmaker_exposure(all_runners)
        else:
            player_name = TELEGRAM_ID_TO_PLAYER_NAME.get(player_id)
            if player_name is None:
                await update.message.reply_text(
                    "Your Telegram ID is not linked to a player name. Please contact the admin."
                )
                return

            positions = self.bet_manager.compute_position(
                bettor=player_name, runners=all_runners
            )

        position_message = "📈 Your current betting position:\n\n"

        all_positions = {runner: positions.get(runner, 0.0) for runner in all_runners}

        total_equity = 0.0
        for runner, position in sorted(
            all_positions.items(), key=lambda x: x[1], reverse=True
        ):
            runner_odds = self.bet_manager.get_latest_odds(
                self.league_state.current_round_num
            ).get(runner)

            total_equity += self.bet_manager.compute_equity(
                runner, position, runner_odds
            )

            position_message += (
                f"- {runner}: {self.bet_manager.compute_signed_amount(position)}\n"
            )

        position_message += f"\nEstimated cash out (adjusted for odds): {self.bet_manager.compute_signed_amount(total_equity)}"
        await update.message.reply_text(
            position_message,
            parse_mode="HTML",
        )

    def records_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.__initialised:
            raise RuntimeError("BotManager not initialised!")

        records = self.record_manager.get_records()

        records_message = "🏆 All-Time Records:\n\n"
        for player, record in records.items():
            records_message += f"- {player}:\n"
            records_message += f"  - Net Wins: {record.net_wins}\n"
            records_message += f"  - Gross Wins: {record.gross_wins}\n"
            if record.most_recent_net_win:
                records_message += f"  - Most Recent Net Win: {record.most_recent_net_win.strftime('%Y-%m-%d')}\n"
            else:
                records_message += "  - Most Recent Net Win: N/A\n"
            if record.most_recent_gross_win:
                records_message += f"  - Most Recent Gross Win: {record.most_recent_gross_win.strftime('%Y-%m-%d')}\n"
            else:
                records_message += "  - Most Recent Gross Win: N/A\n"

        update.message.reply_text(
            records_message,
            parse_mode="HTML",
        )

    async def start_league_handler(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        if not self.__initialised:
            raise RuntimeError("BotManager not initialised!")

        if update.effective_user.id != self.admin_id:
            await update.message.reply_text(
                "You are not authorized to use this command."
            )
            return

        if self.league_state is not None and not self.league_state.is_finished:
            err_msg = "League already active, cannot start a new one."
            logger.warning(err_msg)
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=err_msg,
            )
            return

        league_start_date = datetime.now().strftime("%Y%m%d")
        league_filepath = self.active_league_dir / f"league_{league_start_date}.json"
        self.league_state = LeagueState(
            filepath=league_filepath,
            num_rounds=self.league_settings.number_of_rounds,
        )

        self.bet_manager = BetManager(
            model_settings=self.model_settings,
            data_dir=self.data_dir,
            league_date=self.league_state.start_date,
        )

        logger.info(f"Starting new league at {league_filepath.absolute()}")

        await update.message.reply_text("New league starting...")

        sorted_handicaps = sorted(self.handicaps.items(), key=lambda item: item[1])

        handicap_message = "📉 Handicaps:\n\n"
        for player, handicap in sorted_handicaps:
            handicap_message += f"- {player}: {handicap:.0%}\n"
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=handicap_message,
        )

        self.league_state.chat_id = update.effective_chat.id
        self.league_state.save()

        await self.start_round(context, chat_id=update.effective_chat.id)

    async def poll_for_round_updates(self, context: ContextTypes.DEFAULT_TYPE):
        if not self.__initialised:
            raise RuntimeError("BotManager not initialised!")

        if (
            self.league_state is None
            or self.league_state.is_finished
            or not self.league_state.round_in_progress
        ):
            return

        logger.info("Polling for round updates.")

        round_result = await self.geoguessr_client.get_challenge_scores(
            self.league_state.current_round.challenge_url,
            handicaps=self.handicaps,
            default_handicap=self.league_settings.default_handicap_multiplier,
            challenge_settings=self.league_state.current_round.challenge_settings,
        )

        players_finished_before = self.league_state.get_players_finished_round()
        current_round_played_status = await self.player_round_status(round_result)
        finished_players, still_pending_players = set(), set()
        for player, abbreviated_score in current_round_played_status.items():
            if abbreviated_score is not None and abbreviated_score.is_finished:
                finished_players.add(player)
            else:
                still_pending_players.add(player)

        new_finished_players = finished_players - players_finished_before

        if new_finished_players:
            logger.info(f"New players finished this round: {new_finished_players}")
            for player in new_finished_players:
                self.league_state.add_player_finished(player)

                if self.players_lounge_group_id is None or not still_pending_players:
                    continue

                try:
                    await self.invite_player_to_lounge(
                        context,
                        player_name=player,
                    )
                except Exception as e:
                    logger.exception(
                        f"Failed to invite player {player} to lounge chat: {e}"
                    )
                    await context.bot.send_message(
                        chat_id=self.admin_id,
                        text=(
                            f"⚠️ Failed to invite player {player} to lounge chat: {e}"
                        ),
                    )
                await context.bot.send_message(
                    chat_id=self.players_lounge_group_id,
                    text=f"✅ {player} has finished their round!",
                )

            self.league_state.save()

            if self.players_lounge_group_id is not None:
                await self.status_update(
                    context,
                    chat_id=self.players_lounge_group_id,
                    round_result=round_result,
                    from_perspective_of_player_id=None,
                )

        should_end_round = not still_pending_players or (
            self.league_state.round_in_progress
            and self.league_state.current_round.end_time <= datetime.now()
        )

        if should_end_round:
            logger.info("Ending round.")
            await self.end_round(context, chat_id=self.league_state.chat_id)
            return

        round_reminder_time = self.league_state.current_round.end_time - timedelta(
            hours=2
        )
        should_send_reminder = (
            not self.league_state.current_round.reminder_sent
            and self.league_settings.round_end_time_hour_utc >= 0
            and datetime.now() >= round_reminder_time
        )

        if should_send_reminder:
            logger.info("Sending round reminder.")
            await self.reminder(context, chat_id=self.league_state.chat_id)
            self.league_state.current_round.reminder_sent = True
            self.league_state.save()

    async def start_round(self, context: ContextTypes.DEFAULT_TYPE, chat_id: int):
        challenge_settings = self.challenge_settings_generator(
            self.league_state.current_round_num
        )
        challenge_url = await self.geoguessr_client.create_challenge(
            challenge_settings=challenge_settings
        )
        self.league_state.start_round(
            url=challenge_url,
            end_time_hours=self.league_settings.round_end_time_hour_utc,
            challenge_settings=challenge_settings,
        )

        round_ends_in_seconds = self.league_state.get_time_left_seconds()
        logger.info(
            f"Started round {self.league_state.current_round_num} with challenge URL: {challenge_url}. "
            f"Round ends in {round_ends_in_seconds} seconds."
        )

        self.league_state.save()

        round_start_message = await context.bot.send_message(
            chat_id=chat_id,
            text=(
                f"🏁 Round {self.league_state.current_round_num} has started!\n\n"
                f"Challenge URL: {challenge_url}\n"
                f"This round will end in {format_time(round_ends_in_seconds)}.\n\n"
                f"Format:\n{format_challenge_settings(challenge_settings)}"
            ),
            parse_mode="HTML",
        )

        await context.bot.pin_chat_message(
            chat_id=chat_id,
            message_id=round_start_message.message_id,
            disable_notification=True,
        )

        await context.bot.send_message(
            chat_id=chat_id,
            text="⏳ Calculating latest odds...",
        )

        logger.info(
            f"Writing empty odds file for round {self.league_state.current_round_num}"
        )
        self.bet_manager.update_odds(
            round_num=self.league_state.current_round_num, odds={}
        )

        context.job_queue.run_once(
            self.generate_and_send_odds_update,
            when=1,
            data={"chat_id": chat_id},
        )

        context.job_queue.run_repeating(
            self.poll_for_round_updates,
            interval=self.polling_interval_seconds,
            first=self.polling_interval_seconds,
        )

    async def generate_and_send_odds_update(self, context: ContextTypes.DEFAULT_TYPE):
        chat_id = context.job.data["chat_id"]
        logger.info(f"Generating and sending odds update to chat {chat_id}.")
        odds_df = await generate_outright_odds_predictions(
            n_sims=self.model_settings.n_sims,
        )
        odds_dict = dict(
            odds_df.select("player", "back_win_odds")
            .drop_nulls("back_win_odds")
            .iter_rows()
        )
        odds_dict = {
            player: FractionalOdds.from_str(odds) for player, odds in odds_dict.items()
        }

        overround = sum(odds.implied_probability for odds in odds_dict.values()) - 1
        logger.info(
            f"Odds predictions generated\n\n{odds_df}\\n\nOverround: {overround:.2%}"
        )

        self.bet_manager.update_odds(
            round_num=self.league_state.current_round_num, odds=odds_dict
        )
        odds_message = await self.create_odds_message(odds_dict=odds_dict)

        await context.bot.send_message(
            chat_id=chat_id,
            text=odds_message,
        )

    async def create_odds_message(self, odds_dict: dict[str, FractionalOdds]) -> str:
        if not odds_dict:
            return "Odds are not available."
        odds_message = "📊 Current Odds:\n\n"
        for player, odds in odds_dict.items():
            odds_message += f"- {player}: {odds.formatted}\n"

        odds_message += "\n DM me with /bet to place your bets!"
        odds_message += "\n Use /position to check your current betting position."

        return odds_message

    async def display_odds(self, context: ContextTypes.DEFAULT_TYPE, chat_id: int):
        latest_odds = self.bet_manager.get_latest_odds(
            league_round=self.league_state.current_round_num
        )
        if not latest_odds:
            await context.bot.send_message(
                chat_id=chat_id,
                text="Odds have not been generated yet for this round. Please check back soon!",
            )
            return
        odds_message = await self.create_odds_message(odds_dict=latest_odds)
        await context.bot.send_message(
            chat_id=chat_id,
            text=odds_message,
        )

    async def get_ranked_guesses(self) -> list[RankedGuess]:
        if not self.__initialised:
            raise RuntimeError("BotManager not initialised!")

        if (
            self.league_state is None
            or self.league_state.is_finished
            or not self.league_state.round_in_progress
        ):
            raise RuntimeError("No active round.")

        challenge_url = self.league_state.current_round.challenge_url
        round_result = await self.geoguessr_client.get_challenge_scores(
            challenge_url,
            handicaps=self.handicaps,
            default_handicap=self.league_settings.default_handicap_multiplier,
            challenge_settings=self.league_state.current_round.challenge_settings,
        )

        ranked_guesses = get_ranked_guesses(round_result)
        return ranked_guesses

    async def get_round_leaderboard_message(
        self,
        scores_hidden: bool,
        players_played: dict[str, AbbreviatedRoundScore | None],
    ) -> str:
        leaderboard_message = ""
        if not scores_hidden:
            leaderboard_message += "<b>Current rankings for this round:</b>\n"
            for player, abbreviated_score in players_played.items():
                if abbreviated_score is None:
                    rank_emoji = "❓"
                    net_score_str = ""
                elif not abbreviated_score.is_finished:
                    rank_emoji = "⏳"
                    net_score_str = f" ({abbreviated_score.net_score} pts, {abbreviated_score.rounds_played}/{abbreviated_score.total_rounds} played)"
                else:
                    rank_emoji = NUMBER_EMOJI_MAP.get(abbreviated_score.rank, "❓")
                    net_score_str = f" ({abbreviated_score.net_score} pts)"

                leaderboard_message += f"  {rank_emoji}: {player} {net_score_str}\n"

        else:
            leaderboard_message += "- Players who have played this round\n"

            # Sort players by alphabetical order for consistent display
            sorted_players = sorted(players_played.items())

            for player, abbreviated_score in sorted_players:
                if abbreviated_score is None:
                    emoji = "❌"
                elif not abbreviated_score.is_finished:
                    emoji = "⏳"
                else:
                    emoji = "✅"
                leaderboard_message += f"  - {emoji} {player}\n"

        return leaderboard_message

    async def get_league_projections_for_round(
        self,
        round_result: ChallengeResult,
        best_guess_player: str,
        worst_guess_player: str,
    ) -> str:
        if not self.__initialised:
            raise RuntimeError("BotManager not initialised!")

        if (
            self.league_state is None
            or self.league_state.is_finished
            or not self.league_state.round_in_progress
        ):
            raise RuntimeError("No active round.")

        current_leaderboard = self.league_state.get_leaderboard_data()["scores"]
        projected_scores = current_leaderboard.copy()
        points_for_round = skewed_ranking_score_manager(round_result)
        players_played = set()
        for score in round_result.scores:
            if score.is_finished:
                projected_scores[score.player.name] = (
                    projected_scores.get(score.player.name, 0)
                    + points_for_round[score.player.name]
                )
                players_played.add(score.player.name)
            else:
                projected_scores[score.player.name] = projected_scores.get(
                    score.player.name, 0
                )

        projected_scores[best_guess_player] += 1
        projected_scores[worst_guess_player] -= 1

        projected_ranks = get_ranks_from_scores(projected_scores)
        sorted_projected = sorted(projected_ranks.items(), key=lambda x: x[1])
        projection_message_lines = [
            "<b>Projected league standings after this round:</b>"
        ]
        for player, rank in sorted_projected:
            rank_emoji = NUMBER_EMOJI_MAP.get(rank, "❓")
            if player not in players_played:
                line = f"  <i>{rank_emoji}: {player} ({projected_scores[player]})*</i>"
            else:
                line = f"  <b>{rank_emoji}: {player} ({projected_scores[player]})</b>"

            projection_message_lines.append(line)

        projection_message_lines.append(
            "\n*Players who have not played this round yet."
        )
        return "\n".join(projection_message_lines)

    async def status_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.__initialised:
            raise RuntimeError("BotManager not initialised!")

        if self.league_state is None or self.league_state.is_finished:
            await update.message.reply_text(
                "No active league. Start a new league with /startleague."
            )
            return

        player_id = update.effective_user.id
        chat_id = update.effective_chat.id

        player_name = TELEGRAM_ID_TO_PLAYER_NAME.get(player_id)

        logger.info(
            f"Sending status update to chat {chat_id} for player {player_name} (ID: {player_id})"
        )

        round_result = await self.geoguessr_client.get_challenge_scores(
            self.league_state.current_round.challenge_url,
            handicaps=self.handicaps,
            default_handicap=self.league_settings.default_handicap_multiplier,
            challenge_settings=self.league_state.current_round.challenge_settings,
        )

        await self.status_update(context, chat_id, round_result, player_id)

    async def status_update(
        self,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        round_result: ChallengeResult,
        from_perspective_of_player_id: int | None = None,
    ) -> str:
        status_message = f"League Status:\n- Rounds completed: {self.league_state.last_round_finished_num}/{self.league_state.num_rounds}\n"
        if not self.league_state.round_in_progress:
            status_message += "- No round currently in progress.\n"
        else:
            players_scores = await self.player_round_status(round_result)
            players_played = set(
                player
                for player, score in players_scores.items()
                if score is not None and score.is_finished
            )

            time_left = self.league_state.get_time_left_seconds()

            if from_perspective_of_player_id is not None:
                player_name = TELEGRAM_ID_TO_PLAYER_NAME.get(
                    from_perspective_of_player_id
                )
                player_has_played = player_name in players_played
            else:
                player_has_played = True

            status_message += (
                f"- Current round in progress (ends in {format_time(time_left)})\n\n"
            )
            status_message += await self.get_round_leaderboard_message(
                scores_hidden=not player_has_played,
                players_played=players_scores,
            )

            if player_has_played:
                # Reply in private chat if the player has played
                ranked_guesses = await self.get_ranked_guesses()
                status_message += (
                    f"\n<b>Projected Awards:</b>\n{format_awards_html(ranked_guesses)}"
                )
                if self.league_state.chat_id == chat_id:
                    chat_id = from_perspective_of_player_id

                best_guess_player = ranked_guesses[0].player.name
                worst_guess_player = ranked_guesses[-1].player.name
                projected_leaderboard_message = (
                    await self.get_league_projections_for_round(
                        round_result=round_result,
                        best_guess_player=best_guess_player,
                        worst_guess_player=worst_guess_player,
                    )
                )
                status_message += f"\n\n{projected_leaderboard_message}"

        await context.bot.send_message(
            chat_id=chat_id,
            text=status_message,
            parse_mode="HTML",
        )

    async def reminder(self, context: ContextTypes.DEFAULT_TYPE, chat_id: int):
        if chat_id is None:
            raise ValueError("chat_id must be provided to reminder")

        round_result = await self.geoguessr_client.get_challenge_scores(
            self.league_state.current_round.challenge_url,
            handicaps=self.handicaps,
            default_handicap=self.league_settings.default_handicap_multiplier,
            challenge_settings=self.league_state.current_round.challenge_settings,
        )

        players_finished = await self.player_round_status(round_result)

        time_left = self.league_state.get_time_left_seconds()
        time_left_str = format_time(time_left)

        players_pending = {
            player
            for player, abbreviated_score in players_finished.items()
            if abbreviated_score is None or not abbreviated_score.is_finished
        }
        if not players_pending:
            logger.info("All players have finished the round; no reminder sent.")
            return

        pending_list = "\n".join(f"- {player}" for player in players_pending)

        logger.info(
            f"Sending reminder to chat {chat_id} for players: {players_pending}"
        )

        message = (
            f"⏰ Reminder: Round {self.league_state.current_round_num} will end in {time_left_str}.\n"
            f"The following players have not completed this round yet:\n{pending_list}\n\n"
            f"Round URL: {self.league_state.current_round.challenge_url}"
        )

        await context.bot.send_message(
            chat_id,
            message,
        )

    async def end_round_handler(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        if not self.__initialised:
            raise RuntimeError("BotManager not initialised!")

        if update.effective_user.id != self.admin_id:
            await update.message.reply_text(
                "You are not authorized to use this command."
            )
            return

        if self.league_state is None or self.league_state.is_finished:
            await update.message.reply_text("No active league.")
            return

        if not self.league_state.round_in_progress:
            await update.message.reply_text("No round in progress.")
            return

        await self.end_round(context, update.effective_chat.id)

    async def guesses_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.__initialised:
            raise RuntimeError("BotManager not initialised!")

        if self.league_state is None or self.league_state.is_finished:
            await update.message.reply_text(
                "No active league. Start a new league with /startleague."
            )
            return

        if update.effective_chat.id == self.league_state.chat_id:
            await update.message.reply_text(
                "Guesses are only visible in private chat or Players' Lounge. Please DM me with /guesses to see the current round guesses and rankings.",
            )
            return

        ranked_guesses = await self.get_ranked_guesses()

        top_5_guesses = []
        locations_seen_top_5 = set()
        for ranked_guess in ranked_guesses:
            if ranked_guess.location_index not in locations_seen_top_5:
                top_5_guesses.append(ranked_guess)
                locations_seen_top_5.add(ranked_guess.location_index)
            if len(top_5_guesses) >= 5:
                break

        bottom_5_guesses = []
        locations_seen_bottom_5 = set()
        for ranked_guess in reversed(ranked_guesses):
            if ranked_guess.location_index not in locations_seen_bottom_5:
                bottom_5_guesses.append(ranked_guess)
                locations_seen_bottom_5.add(ranked_guess.location_index)
            if len(bottom_5_guesses) >= 5:
                break

        guesses_message = "📊 Current Round Guesses:\n\n"

        def format_guess(ranked_guess: RankedGuess) -> str:
            return f"- {ranked_guess.player.name} - R{ranked_guess.location_index} (guess rating: {ranked_guess.adjusted_score})"

        guesses_message += "Top 5 guesses:\n"
        for ranked_guess in top_5_guesses:
            guesses_message += f"{format_guess(ranked_guess)}\n"

        guesses_message += "\nBottom 5 guesses:\n"
        for ranked_guess in bottom_5_guesses:
            guesses_message += f"{format_guess(ranked_guess)}\n"

        logger.info(
            f"Sending guesses update to chat {update.effective_chat.id}\n\n{guesses_message}"
        )
        await update.message.reply_text(
            guesses_message,
            parse_mode="HTML",
        )

    async def end_round(self, context: ContextTypes.DEFAULT_TYPE, chat_id: int):
        if chat_id is None:
            raise ValueError("chat_id must be provided to end_round")

        challenge_url = self.league_state.current_round.challenge_url
        challenge_settings = self.league_state.current_round.challenge_settings
        round_result = await self.geoguessr_client.get_challenge_scores(
            challenge_url,
            handicaps=self.handicaps,
            default_handicap=self.league_settings.default_handicap_multiplier,
            challenge_settings=challenge_settings,
        )

        ranked_guesses = get_ranked_guesses(round_result)

        self.league_state.add_round_result(round_result)
        self.league_state.add_awards(ranked_guesses[0], ranked_guesses[-1])
        self.league_state.save()

        round_text = format_round_result_html(round_result, ranked_guesses)

        await context.bot.send_message(
            chat_id=chat_id,
            text=f"🏁 Round {self.league_state.last_round_finished_num} has ended!\n\n{round_text}",
            parse_mode="HTML",
        )

        await self.clear_players_from_lounge_chat(context)

        await self.show_leaderboard(context, chat_id)

        if self.league_state.is_finished:
            winner = self.league_state.get_winner()
            await context.bot.send_message(
                chat_id, f"🏆 League finished. Winner: {winner}"
            )
            # Calculate and update handicaps
            player_ranks = get_ranks_from_scores(
                self.league_state.get_leaderboard_data()["scores"]
            )
            new_handicaps = calculate_new_handicaps(player_ranks, self.league_settings)

            update_handicaps(
                new_handicaps, self.league_state.league_start_date, self.league_settings
            )

            logger.info(f"Updated handicaps: {new_handicaps}")
            await self.show_handicap_updates(
                context,
                chat_id,
                prev_handicaps=self.handicaps,
                new_handicaps=new_handicaps,
            )
            self.handicaps = new_handicaps
            logger.info("Starting replay without handicaps.")

            gross_replay_league_state = await replay_league(
                league_path=self.league_state.filepath,
                handicaps={},
                league_settings=self.league_settings,
            )

            replayed_leaderboard_text = format_leaderboard_html(
                **gross_replay_league_state.get_leaderboard_data()
            )
            await context.bot.send_message(
                chat_id,
                f"📊 Gross Results:\n\n{replayed_leaderboard_text}",
                parse_mode="HTML",
            )

            gross_replay_league_state.filepath.unlink(missing_ok=True)

            # Comupute bet P&L and send final bet results
            bet_pnls = self.bet_manager.compute_bet_pnls(
                winner=winner,
            )

            if bet_pnls:
                bet_results_message = "💰 Bet Results:\n\n"
                for player, pnl in bet_pnls.items():
                    bet_results_message += (
                        f"- {player}: {self.bet_manager.compute_signed_amount(pnl)}\n"
                    )

                bookmaker_pnl = -sum(bet_pnls.values())
                bet_results_message += f"\nBookmaker P&L: {self.bet_manager.compute_signed_amount(bookmaker_pnl)}"

                await context.bot.send_message(
                    chat_id,
                    bet_results_message,
                )
            else:
                logger.info("No bets placed, skipping bet results message.")

            logger.info(
                "Leageue finished, ending league and moving file to finished directory."
            )

            await self.end_league()

        else:
            await self.start_round(
                context,
                chat_id=chat_id,
            )

    async def outcomes_handler(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        if not self.__initialised:
            raise RuntimeError("BotManager not initialised!")

        if self.league_state is None or self.league_state.is_finished:
            await update.message.reply_text(
                "No active league. Start a new league with /startleague."
            )
            return

        odds = self.bet_manager.get_latest_odds(
            league_round=self.league_state.current_round_num
        )
        if not odds:
            await update.message.reply_text(
                "Odds have not been generated yet for this round. Please check back soon!",
            )
            return

        bet_outcomes_message = "📊 Bet Outcomes:\n\n"
        for player, odds in odds.items():
            bet_outcomes_message += f"{player}: (current odds: {odds.formatted})\n"

            for bettor, pnl in self.bet_manager.compute_bet_pnls(winner=player).items():
                bet_outcomes_message += (
                    f"    - {bettor}: {self.bet_manager.compute_signed_amount(pnl)}\n"
                )

            bet_outcomes_message += "\n"

        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=bet_outcomes_message,
            parse_mode="HTML",
        )

    async def show_leaderboard(self, context: ContextTypes.DEFAULT_TYPE, chat_id: int):
        leaderboard = self.league_state.get_leaderboard_data()
        leaderboard_text = format_leaderboard_html(**leaderboard)

        await context.bot.send_message(
            chat_id,
            f"📊 Standings after round {self.league_state.last_round_finished_num}:\n\n{leaderboard_text}",
            parse_mode="HTML",
        )

    async def error_handler(
        self, update: object, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Error handler that sends the traceback to the admin."""
        # Build a clean traceback message
        if isinstance(context.error, NetworkError):
            logger.info(f"Network error occurred: {context.error}")
            return

        tb_list = traceback.format_exception(
            None, context.error, context.error.__traceback__
        )
        tb_text = "".join(tb_list)
        tb_text = tb_text[-4000:]

        message = (
            "⚠️ <b>Bot Handler Error</b>\n"
            f"<b>Exception:</b> {context.error}\n\n"
            f"<b>Traceback:</b>\n<pre>{tb_text}</pre>"
        )

        try:
            await context.bot.send_message(
                chat_id=self.admin_id, text=message, parse_mode="HTML"
            )
        except Exception as e:
            logger.exception(f"Failed to send admin alert: {e}")

        # Still print to logs
        logger.info(f"Exception while handling update {update}: {context.error}")

    async def player_round_status(
        self, round_result: ChallengeResult
    ) -> dict[str, AbbreviatedRoundScore | None]:
        net_scores = {}
        rounds_played_by_player = {}
        for score in round_result.scores:
            net_score = score.compute_net_score()
            net_scores[score.player.name] = net_score
            rounds_played_by_player[score.player.name] = len(score.guesses)

        ranks = get_ranks_from_scores(net_scores)

        result = {player: None for player in self.handicaps.keys()}

        for player, rank in ranks.items():
            result[player] = AbbreviatedRoundScore(
                rank=rank,
                net_score=net_scores[player],
                rounds_played=rounds_played_by_player[player],
                total_rounds=round_result.num_rounds,
            )

        # Sort the result dict by rank (None values at the end)
        return dict(
            sorted(
                result.items(),
                key=lambda item: (
                    item[1].rank if item[1] is not None else float("inf")
                ),
            )
        )

    async def end_league(self):
        if self.league_state is None:
            raise RuntimeError("No active league to end.")

        finished_league_path = (
            self.finished_league_dir / self.league_state.filepath.name
        )
        self.league_state.filepath.rename(finished_league_path)
        logger.info(
            f"League ended. Moved league file to {finished_league_path.absolute()}"
        )
        self.league_state = None

    async def show_handicap_updates(
        self,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        prev_handicaps: dict[str, float],
        new_handicaps: dict[str, float],
    ):
        message = "📉 Handicap Updates:\n\n"
        for player, new_hcap in new_handicaps.items():
            prev_hcap = prev_handicaps.get(
                player, self.league_settings.default_handicap_multiplier
            )
            change = new_hcap - prev_hcap
            change_str = f"+{change:.0%}" if change > 0 else f"{change:.0%}"
            message += f"- {player}: {prev_hcap:.0%} -> {new_hcap:.0%} ({change_str})\n"

        await context.bot.send_message(
            chat_id=chat_id,
            text=message,
        )

    async def invite_player_to_lounge(
        self,
        context: ContextTypes.DEFAULT_TYPE,
        player_name: str,
    ):
        if not self.__initialised:
            raise RuntimeError("BotManager not initialised!")

        if self.players_lounge_group_id is None:
            raise ValueError("players_lounge_group_id is not set.")

        player_telegram_id = PLAYER_NAME_TO_TELEGRAM_ID.get(player_name)
        if player_telegram_id is None:
            logger.warning(f"No Telegram ID found for player {player_name}.")
            return

        invite_link = await context.bot.create_chat_invite_link(
            chat_id=self.players_lounge_group_id,
            member_limit=1,  # single-use
            expire_date=datetime.utcnow() + timedelta(minutes=15),
        )

        await context.bot.send_message(
            chat_id=player_telegram_id,
            text=(
                f"Hello {player_name}!\n\n"
                f"You have been invited to join the Teleguessr Players' Lounge group chat.\n"
                f"Click the link below to join:\n{invite_link.invite_link}\n\n"
                f"This link will expire in 15 minutes - but you can request a new one by using the /lounge command."
            ),
        )

    async def clear_players_from_lounge_chat(self, context: ContextTypes.DEFAULT_TYPE):
        if not self.__initialised:
            raise RuntimeError("BotManager not initialised!")

        if self.players_lounge_group_id is None:
            logger.info(
                "No players lounge group ID set, skipping clearing lounge chat."
            )
            return

        players_to_remove = []

        for player_name in self.handicaps.keys():
            player_telegram_id = PLAYER_NAME_TO_TELEGRAM_ID.get(player_name)
            if player_telegram_id is None:
                logger.warning(f"No Telegram ID found for player {player_name}.")
                continue

            try:
                member = await context.bot.get_chat_member(
                    self.players_lounge_group_id, player_telegram_id
                )
                if member.status not in ("creator", "administrator"):
                    players_to_remove.append((player_name, player_telegram_id))
            except Exception:
                logger.exception(
                    f"Failed to get chat member info for player {player_name}"
                )

        for player_name, player_telegram_id in players_to_remove:
            logger.info(f"Removing player {player_name} from lounge chat.")
            try:
                await context.bot.ban_chat_member(
                    chat_id=self.players_lounge_group_id,
                    user_id=player_telegram_id,
                    until_date=datetime.now() + timedelta(seconds=60),
                )
                await context.bot.unban_chat_member(
                    chat_id=self.players_lounge_group_id,
                    user_id=player_telegram_id,
                )
            except Exception as e:
                logger.exception(
                    f"Failed to remove player {player_name} from lounge chat: {e}"
                )
                await context.bot.send_message(
                    chat_id=self.admin_id,
                    text=f"⚠️ Failed to remove player {player_name} from lounge chat: {e}",
                )

    async def lounge_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.__initialised:
            raise RuntimeError("BotManager not initialised!")

        if self.league_state is None or self.league_state.is_finished:
            await update.message.reply_text(
                "No active league. Start a new league with /startleague."
            )
            return

        user_id = update.effective_user.id

        player_name = TELEGRAM_ID_TO_PLAYER_NAME.get(user_id)

        if player_name is None:
            await update.message.reply_text(
                "You are not registered as a player in this league."
            )
            return

        round_result = await self.geoguessr_client.get_challenge_scores(
            self.league_state.current_round.challenge_url,
            handicaps=self.handicaps,
            default_handicap=self.league_settings.default_handicap_multiplier,
            challenge_settings=self.league_state.current_round.challenge_settings,
        )

        round_status = await self.player_round_status(round_result)
        player_score = round_status.get(player_name)

        if player_score is None or not player_score.is_finished:
            await update.message.reply_text(
                "You have not completed this round yet. Please complete your round to join the lounge."
            )
            return

        await self.invite_player_to_lounge(
            context,
            player_name=player_name,
        )

    async def handicaps_handler(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        if not self.__initialised:
            raise RuntimeError("BotManager not initialised!")

        sorted_handicaps = sorted(self.handicaps.items(), key=lambda item: item[1])

        message = "📉 Current Handicaps:\n\n"
        for player, handicap in sorted_handicaps:
            message += f"- {player}: {handicap:.0%}\n"

        await update.message.reply_text(message)

    async def start_bet(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.__initialised:
            raise RuntimeError("BotManager not initialised!")

        if self.league_state is None or self.league_state.is_finished:
            await update.message.reply_text(
                "No active league. Start a new league with /startleague."
            )
            return

        player_id = update.effective_user.id

        chat_id = update.effective_chat.id
        if chat_id != player_id:
            await update.message.reply_text(
                "Please place bets in a private chat with the bot to avoid interference."
            )
            return

        player_name = TELEGRAM_ID_TO_PLAYER_NAME.get(player_id)

        if player_name is None:
            await update.message.reply_text(
                "You are not registered as a player in this league."
            )
            return

        round_result = await self.geoguessr_client.get_challenge_scores(
            self.league_state.current_round.challenge_url,
            handicaps=self.handicaps,
            default_handicap=self.league_settings.default_handicap_multiplier,
            challenge_settings=self.league_state.current_round.challenge_settings,
        )

        players_played = await self.player_round_status(round_result)
        if players_played.get(player_name) is not None:
            await update.message.reply_text(
                "You have already started this round, so you cannot place bets. Please wait for the next round to start."
            )
            return

        odds = self.bet_manager.get_latest_odds(self.league_state.current_round_num)
        if not odds:
            await update.message.reply_text(
                "Betting is not currently available for this round. Please try again later."
            )
            return

        keyboard = [
            [InlineKeyboardButton(f"{player} ({odd.formatted})", callback_data=player)]
            for player, odd in odds.items()
        ]
        keyboard.append([InlineKeyboardButton("Cancel", callback_data="cancel")])
        await update.message.reply_text(
            "Who would you like to bet on?", reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return BET_SELECT_PLAYER

    async def handle_player_selection(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> int:
        query = update.callback_query
        await query.answer()

        context.user_data["bet_player"] = query.data
        odds = self.bet_manager.get_latest_odds(self.league_state.current_round_num)
        if query.data == "cancel":
            await query.edit_message_text("Bet cancelled.")
            return ConversationHandler.END

        runner_odds = odds.get(query.data)
        if runner_odds is None:
            await query.edit_message_text(
                f"Sorry, odds for {query.data} are not available. Please try again later."
            )
            return ConversationHandler.END

        context.user_data["bet_odds"] = runner_odds
        valid_bet_amounts = self.bet_manager.calculate_bet_amounts(
            bettor=TELEGRAM_ID_TO_PLAYER_NAME.get(update.effective_user.id),
            runner=query.data,
            odds=runner_odds,
        )

        if not valid_bet_amounts:
            await query.edit_message_text(
                f"Sorry, you cannot place a bet on {query.data} at the moment. Please try again later."
            )
            return ConversationHandler.END

        keyboard = [
            [InlineKeyboardButton(f"€{amount}", callback_data=str(amount))]
            for amount in valid_bet_amounts
        ]
        keyboard.append([InlineKeyboardButton("Cancel", callback_data="cancel")])
        await query.edit_message_text(
            f"Selected: *{query.data}*\nHow much would you like to bet?",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown",
        )
        return BET_SELECT_AMOUNT  # ← move to next state

    async def handle_amount_selection(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> int:
        query = update.callback_query
        await query.answer()

        if query.data == "cancel":
            await query.edit_message_text("Bet cancelled.")
            return ConversationHandler.END

        player = context.user_data["bet_player"]
        bet_odds: FractionalOdds = context.user_data["bet_odds"]
        amount = float(query.data)

        bet = self.bet_manager.place_bet(
            bettor=TELEGRAM_ID_TO_PLAYER_NAME[update.effective_user.id],
            runner=player,
            amount=amount,
            odds=bet_odds,
        )

        message = f"✅ Bet placed\n\n{bet}"

        await query.edit_message_text(
            message,
            parse_mode="Markdown",
        )

        await context.bot.send_message(
            chat_id=self.league_state.chat_id,
            text=message,
            parse_mode="Markdown",
        )

        return ConversationHandler.END  # ← end the conversation

    async def cancel_bet(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> int:
        await update.message.reply_text("Bet cancelled.")
        return ConversationHandler.END
