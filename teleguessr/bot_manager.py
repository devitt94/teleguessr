from collections.abc import Callable
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path
import traceback
from typing import Awaitable

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application as TelegramApp, ConversationHandler
from telegram.error import NetworkError

from teleguessr.active_players import PlayerManager
from teleguessr.analysis import all_gross_scores_needed
from teleguessr.awards import get_ranked_guesses
from teleguessr.bets import BetManager, BettingSuspendedError
from teleguessr.challenge_settings_generators import (
    CHALLENGE_SETTINGS,
    ChallengeSettingsGenerator,
)
from teleguessr import formatters
from teleguessr.odds import FractionalOdds
from teleguessr.predictions import generate_outright_odds_predictions
from teleguessr.replay import replay_league
from teleguessr.record_manager import RecordManager
from teleguessr.geoguessr_scraper import GeoguessrClient
from teleguessr.league import (
    LeagueState,
    get_rank_scores_list,
    skewed_ranking_score_manager,
)
from teleguessr.models import (
    AbbreviatedRoundScore,
    BetType,
    ChallengeResult,
    MarketType,
    RankedGuess,
)
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


BET_SELECT_PLAYER, BET_SELECT_BET_TYPE, BET_SELECT_AMOUNT = range(3)

OPT_IN_CALLBACK = "optin_next_league"

HandlerFunc = Callable[
    ["BotManager", Update, ContextTypes.DEFAULT_TYPE], Awaitable[None]
]


def command_handler(
    initialised: bool = True,
    admin: bool = False,
    league_in_progress: bool | None = None,
    round_in_progress: bool = False,
) -> Callable[[HandlerFunc], HandlerFunc]:
    """A decorator for command handlers to validate the application state before executing the command."""

    def decorator(func: HandlerFunc) -> HandlerFunc:
        @wraps(func)
        async def wrapper(
            self: "BotManager", update: Update, context: ContextTypes.DEFAULT_TYPE
        ) -> None:
            if initialised and not self._initialised:
                raise RuntimeError("BotManager not initialised!")

            if admin and update.effective_user.id != self.admin_id:
                await update.message.reply_text(
                    "You are not authorized to use this command."
                )
                return

            league_currently_in_progress = (
                self.league_state is not None and not self.league_state.is_finished
            )
            if league_in_progress is not None:
                if league_in_progress and not league_currently_in_progress:
                    await update.message.reply_text(
                        "No active league. Start a new league with /startleague."
                    )
                    return
                elif not league_in_progress and league_currently_in_progress:
                    await update.message.reply_text(
                        "A league is currently in progress. This command cannot be used during an active league."
                    )
                    return

            if round_in_progress and not (
                league_currently_in_progress and self.league_state.round_in_progress
            ):
                await update.message.reply_text("No round currently in progress.")
                return

            return await func(self, update, context)

        return wrapper

    return decorator


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
        player_manager: PlayerManager,
    ):
        self.admin_id = admin_id
        self.players_lounge_group_id = players_lounge_group_id
        self.data_dir = data_dir
        self.polling_interval_seconds = polling_interval_seconds
        self.league_settings = league_settings
        self.model_settings = model_settings
        self.league_state = None
        self.bet_manager = None
        self._initialised = False
        self.geoguessr_client = geoguessr_client
        self.player_manager = player_manager

        self.challenge_settings_generator: ChallengeSettingsGenerator = (
            CHALLENGE_SETTINGS[league_settings.challenge_settings_name]
        )

    @property
    def active_league_dir(self) -> Path:
        return self.data_dir / "leagues" / "active"

    @property
    def finished_league_dir(self) -> Path:
        return self.data_dir / "leagues" / "finished"

    @property
    def active_handicaps(self) -> dict[str, float]:
        return {
            player: handicap
            for player, handicap in self.handicaps.items()
            if player in self.player_manager.get_active_players()
        }

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
        self.record_manager = RecordManager(data_dir=self.data_dir)

        if self.league_state is not None:
            self.bet_manager = BetManager(
                model_settings=self.model_settings,
                data_dir=self.data_dir,
                league_date=self.league_state.start_date,
                all_runners=list(self.player_manager.get_active_players()),
            )

        self._initialised = True

    async def resume_league_tasks(self, app: TelegramApp):
        if self.league_state is None or self.league_state.is_finished:
            logger.info("No active league to resume tasks for.")
            return

        if not self.league_state.round_in_progress:
            logger.info("No round in progress to resume tasks for. Starting new round.")
            chat_id = self.league_state.chat_id
            await self.__start_round(app, chat_id=chat_id)
            return

        logger.info("Resuming round update polling for active round.")
        app.job_queue.run_repeating(
            self.__poll_for_round_updates,
            interval=self.polling_interval_seconds,
            first=0,
        )

    def __construct_position_message(
        self, player_name: str, is_bookmaker: bool = False
    ) -> str:
        if is_bookmaker:
            position = self.bet_manager.compute_bookmaker_exposure()
            position_message = "📈 Bookmaker's exposure:\n\n"
        else:
            position_message = "📈 Your current betting position:\n\n"
            position = self.bet_manager.compute_position(bettor=player_name)

        total_equity = 0.0

        for runner, position in sorted(
            position.items(), key=lambda x: x[1], reverse=True
        ):
            runner_odds = self.bet_manager.get_latest_odds(
                self.league_state.current_round_num
            ).get(runner)

            total_equity += self.bet_manager.compute_equity(
                runner, position, runner_odds
            )

            position_message += (
                f"- {runner}: {formatters.format_signed_amount(position)}\n"
            )

        position_message += f"\nEstimated cash out (adjusted for odds): {formatters.format_signed_amount(total_equity)}"
        return position_message

    async def __poll_for_round_updates(self, context: ContextTypes.DEFAULT_TYPE):
        if (
            self.league_state is None
            or self.league_state.is_finished
            or not self.league_state.round_in_progress
        ):
            return

        logger.info("Polling for round updates.")

        round_result = await self.geoguessr_client.get_challenge_scores(
            self.league_state.current_round.challenge_url,
            handicaps=self.active_handicaps,
            challenge_settings=self.league_state.current_round.challenge_settings,
        )

        players_finished_before = self.league_state.get_players_finished_round()
        current_round_played_status = self.__player_round_status(round_result)
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
                    await self.__invite_player_to_lounge(
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
                await self.__status_update(
                    context,
                    chat_id=self.players_lounge_group_id,
                    round_result=round_result,
                )

        should_end_round = not still_pending_players or (
            self.league_state.round_in_progress
            and self.league_state.current_round.end_time <= datetime.now()
        )

        if should_end_round:
            logger.info("Ending round.")
            await self.__end_round(context, chat_id=self.league_state.chat_id)
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
            await self.__reminder(context, chat_id=self.league_state.chat_id)
            self.league_state.current_round.reminder_sent = True
            self.league_state.save()

    async def __start_round(self, context: ContextTypes.DEFAULT_TYPE, chat_id: int):
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

        streamer = self.league_state.get_streamer_for_round()

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
                f"This round will end in {formatters.format_time(round_ends_in_seconds)}.\n\n"
                f"Format:\n{formatters.format_challenge_settings(challenge_settings)}"
            ),
            parse_mode="HTML",
        )

        if streamer is not None:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"🎥 Streamer for this round: {streamer}",
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
            round_num=self.league_state.current_round_num, back_odds={}, lay_odds={}
        )

        context.job_queue.run_once(
            self.__generate_and_send_odds_update,
            when=1,
            data={"chat_id": chat_id},
        )

        context.job_queue.run_repeating(
            self.__poll_for_round_updates,
            interval=self.polling_interval_seconds,
            first=self.polling_interval_seconds,
        )

    async def __generate_and_send_odds_update(self, context: ContextTypes.DEFAULT_TYPE):
        chat_id = context.job.data["chat_id"]
        logger.info(f"Generating and sending odds update to chat {chat_id}.")
        odds_df = await generate_outright_odds_predictions(
            n_sims=self.model_settings.n_sims,
            runners=self.player_manager.get_active_players(),
        )

        back_win_odds_dict = {
            player: FractionalOdds.from_str(odds)
            for player, odds in odds_df.select("player", "back_win_odds")
            .drop_nulls("back_win_odds")
            .iter_rows()
        }

        lay_win_odds_dict = {
            player: FractionalOdds.from_str(odds)
            for player, odds in odds_df.select("player", "lay_win_odds")
            .drop_nulls("lay_win_odds")
            .iter_rows()
        }

        back_overround = (
            sum(odds.implied_probability for odds in back_win_odds_dict.values()) - 1
        )
        lay_overround = (
            sum(odds.implied_probability for odds in lay_win_odds_dict.values()) - 1
        )
        logger.info(
            f"Odds predictions generated\n\n{odds_df}\\n\nOverrounds: Back - {back_overround:.2%}, Lay - {lay_overround:.2%}"
        )

        self.bet_manager.update_odds(
            round_num=self.league_state.current_round_num,
            back_odds=back_win_odds_dict,
            lay_odds=lay_win_odds_dict,
        )
        self.bet_manager.suspend_betting()
        odds_message = formatters.format_odds_message(
            back_win_odds_dict, lay_win_odds_dict
        )

        await context.bot.send_message(
            chat_id=chat_id,
            text=odds_message,
        )

    async def __announce_league_end(
        self, context: ContextTypes.DEFAULT_TYPE, chat_id: int
    ):
        """Call this when the current league finishes."""
        self.player_manager.clear_active_players()

        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "✅ I'm in for next week", callback_data=OPT_IN_CALLBACK
                    )
                ]
            ]
        )

        text = (
            "Next week's league will begin on Sunday at 12pm UK time.\n"
            "Tap below to opt in:"
        )

        join_league_message = await context.bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=keyboard,
        )
        await join_league_message.pin()

    async def handle_opt_in(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        user = query.from_user

        if query.data != OPT_IN_CALLBACK:
            return

        player_name = TELEGRAM_ID_TO_PLAYER_NAME.get(user.id)

        newly_added = self.player_manager.add_active_player(player_name)

        if not newly_added:
            await query.answer("You're already signed up!")
            return

        await query.answer("You're in! 🎉")

        # Update the message to show current sign-ups
        count = len(self.player_manager.get_active_players())
        await query.edit_message_reply_markup(
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            f"✅ I'm in ({count} joined)", callback_data=OPT_IN_CALLBACK
                        )
                    ]
                ]
            )
        )

    async def __get_ranked_guesses(self) -> list[RankedGuess]:
        if (
            self.league_state is None
            or self.league_state.is_finished
            or not self.league_state.round_in_progress
        ):
            raise RuntimeError("No active round.")

        challenge_url = self.league_state.current_round.challenge_url
        round_result = await self.geoguessr_client.get_challenge_scores(
            challenge_url,
            handicaps=self.active_handicaps,
            challenge_settings=self.league_state.current_round.challenge_settings,
        )

        ranked_guesses = get_ranked_guesses(round_result)
        return ranked_guesses

    def __get_league_projections_for_round(
        self,
        round_result: ChallengeResult,
        best_guess_player: str,
        worst_guess_player: str,
    ) -> str:
        current_leaderboard = self.league_state.get_leaderboard_data()["scores"]
        projected_scores = current_leaderboard.copy()
        points_for_round = skewed_ranking_score_manager(
            round_result, num_players=len(self.active_handicaps)
        )
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
        return formatters.format_projected_leaderboard_message(
            projected_ranks=projected_ranks,
            projected_scores=projected_scores,
            players_played=players_played,
        )

    async def __status_update(
        self,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        round_result: ChallengeResult,
    ) -> str:
        status_message = f"League Status:\n- Rounds completed: {self.league_state.last_round_finished_num}/{self.league_state.num_rounds}\n"

        players_scores = self.__player_round_status(round_result)
        players_played = set(
            player
            for player, score in players_scores.items()
            if score is not None and score.is_finished
        )

        time_left = self.league_state.get_time_left_seconds()

        hide_scores: bool
        if chat_id == self.players_lounge_group_id:
            hide_scores = False
        elif chat_id == self.league_state.chat_id:
            hide_scores = True
        else:
            player_id = chat_id
            player_name = TELEGRAM_ID_TO_PLAYER_NAME.get(player_id)
            hide_scores = player_name not in players_played

        status_message += f"- Current round in progress (ends in {formatters.format_time(time_left)})\n\n"
        status_message += formatters.format_round_leaderboard_message(
            scores_hidden=hide_scores,
            players_played=players_scores,
        )

        if not hide_scores:
            ranked_guesses = await self.__get_ranked_guesses()
            status_message += f"\n<b>Projected Awards:</b>\n{formatters.format_awards_html(ranked_guesses)}"
            best_guess_player = ranked_guesses[0].player.name
            worst_guess_player = ranked_guesses[-1].player.name
            projected_leaderboard_message = self.__get_league_projections_for_round(
                round_result=round_result,
                best_guess_player=best_guess_player,
                worst_guess_player=worst_guess_player,
            )
            status_message += f"\n{projected_leaderboard_message}"

        await context.bot.send_message(
            chat_id=chat_id,
            text=status_message,
            parse_mode="HTML",
        )

    async def __reminder(self, context: ContextTypes.DEFAULT_TYPE, chat_id: int):
        round_result = await self.geoguessr_client.get_challenge_scores(
            self.league_state.current_round.challenge_url,
            handicaps=self.active_handicaps,
            challenge_settings=self.league_state.current_round.challenge_settings,
        )

        players_finished = self.__player_round_status(round_result)

        time_left = self.league_state.get_time_left_seconds()
        time_left_str = formatters.format_time(time_left)

        players_pending = {
            player
            for player, abbreviated_score in players_finished.items()
            if abbreviated_score is None or not abbreviated_score.is_finished
        }
        if not players_pending:
            logger.info("All players have finished the round; no reminder sent.")
            return

        players_with_telegram_ids = [
            (player, PLAYER_NAME_TO_TELEGRAM_ID.get(player))
            for player in players_pending
        ]

        pending_list = "\n".join(
            f"\- [{player}](tg://user?id={telegram_id})"
            for player, telegram_id in players_with_telegram_ids
        )

        logger.info(
            f"Sending reminder to chat {chat_id} for players: {players_pending}"
        )

        message = (
            f"⏰ Reminder: Round {self.league_state.current_round_num} will end in {time_left_str}\.\n"
            f"The following players have not completed this round yet:\n{pending_list}\n\n"
        )

        await context.bot.send_message(chat_id, message, parse_mode="MarkdownV2")

    async def __end_league(self):
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

    async def __show_handicap_updates(
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

    async def __invite_player_to_lounge(
        self,
        context: ContextTypes.DEFAULT_TYPE,
        player_name: str,
    ):
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

    async def __clear_players_from_lounge_chat(
        self, context: ContextTypes.DEFAULT_TYPE
    ):
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

    async def __show_leaderboard(
        self, context: ContextTypes.DEFAULT_TYPE, chat_id: int
    ):
        leaderboard = self.league_state.get_leaderboard_data()
        leaderboard_text = formatters.format_leaderboard_html(**leaderboard)

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

    def __player_round_status(
        self, round_result: ChallengeResult
    ) -> dict[str, AbbreviatedRoundScore | None]:
        net_scores = {}
        rounds_played_by_player = {}
        for score in round_result.scores:
            net_score = score.compute_net_score()
            net_scores[score.player.name] = net_score
            rounds_played_by_player[score.player.name] = len(score.guesses)

        ranks = get_ranks_from_scores(net_scores)

        result = {player: None for player in self.active_handicaps.keys()}

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

    async def __end_round(self, context: ContextTypes.DEFAULT_TYPE, chat_id: int):
        if chat_id is None:
            raise ValueError("chat_id must be provided to end_round")

        challenge_url = self.league_state.current_round.challenge_url
        challenge_settings = self.league_state.current_round.challenge_settings
        round_result = await self.geoguessr_client.get_challenge_scores(
            challenge_url,
            handicaps=self.active_handicaps,
            challenge_settings=challenge_settings,
        )

        ranked_guesses = get_ranked_guesses(round_result)

        self.league_state.add_round_result(
            round_result, num_players=len(self.active_handicaps)
        )
        self.league_state.add_awards(ranked_guesses[0], ranked_guesses[-1])
        self.league_state.save()

        round_text = formatters.format_round_result_html(
            round_result, ranked_guesses, num_players=len(self.active_handicaps)
        )

        await context.bot.send_message(
            chat_id=chat_id,
            text=f"🏁 Round {self.league_state.last_round_finished_num} has ended!\n\n{round_text}",
            parse_mode="HTML",
        )

        await self.__clear_players_from_lounge_chat(context)

        await self.__show_leaderboard(context, chat_id)

        if self.league_state.is_finished:
            winner, second, third, *_, last = (
                self.league_state.get_final_sorted_leaderboard()
            )
            await context.bot.send_message(
                chat_id,
                f"🏆 League finished.\n\n🥇: {winner}\n🥈: {second}\n🥉: {third}\n🥄: {last}",
            )
            # Calculate and update handicaps
            final_leaderboard = self.league_state.get_leaderboard_data()
            player_ranks = get_ranks_from_scores(final_leaderboard["scores"])
            new_handicaps = calculate_new_handicaps(player_ranks, self.league_settings)

            update_handicaps(
                new_handicaps, self.league_state.league_start_date, self.league_settings
            )

            logger.info(f"Updated handicaps: {new_handicaps}")
            await self.__show_handicap_updates(
                context,
                chat_id,
                prev_handicaps=self.handicaps,
                new_handicaps=new_handicaps,
            )
            self.handicaps = new_handicaps
            logger.info("Starting replay without handicaps.")

            gross_replay_league_state = await replay_league(
                league_path=self.league_state.filepath,
                handicaps={player: 0.0 for player in self.active_handicaps},
                league_settings=self.league_settings,
            )

            gross_winner = gross_replay_league_state.get_winner()
            self.record_manager.update_records(
                gross_winner=gross_winner,
                net_winner=winner,
                second_place=second,
                third_place=third,
                last_place=last,
                best_guesses=final_leaderboard["best_guesses"],
                worst_guesses=final_leaderboard["worst_guesses"],
                handicaps=self.handicaps,
            )

            replayed_leaderboard_text = formatters.format_leaderboard_html(
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
                        f"- {player}: {formatters.format_signed_amount(pnl)}\n"
                    )

                bookmaker_pnl = -sum(bet_pnls.values())
                bet_results_message += (
                    f"\nBookmaker P&L: {formatters.format_signed_amount(bookmaker_pnl)}"
                )

                await context.bot.send_message(
                    chat_id,
                    bet_results_message,
                )
            else:
                logger.info("No bets placed, skipping bet results message.")

            logger.info(
                "Leageue finished, ending league and moving file to finished directory."
            )

            await self.__end_league()

            await self.__announce_league_end(
                context,
                chat_id=chat_id,
            )

        else:
            await self.__start_round(
                context,
                chat_id=chat_id,
            )

    @command_handler()
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
            "/exposure - Show the bookmaker's position"
            "/scoresneeded - Show the gross scores needed by each remaining player in the round\n"
            "/outcomes - Show all betting outcomes"
            "/records - Show all-time records\n"
            "/help - Show this help message\n\n"
        )

        await update.message.reply_text(
            help_message,
            parse_mode="HTML",
        )

    @command_handler()
    async def records_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        records = self.record_manager.get_records()

        records_message = "🏆 All-Time Records:\n"
        records_message += (
            "Net = 🏆; "
            "Gross = 👑; "
            "Best Guess = 🐐; "
            "Worst Guess = 🎣; "
            "Min Handicap = 📉; "
            "Max Handicap = 📈; "
            "Podium finishes = 🏅; "
            "Wooden Spoon = 🥄\n\n"
        )
        for player, record in records.items():
            records_message += f"- {player}:\n"
            if record.net_wins > 0:
                net_win_str = f"{record.net_wins} (most recent: {formatters.format_datetime_to_time_ago(record.most_recent_net_win)}) \n"
            else:
                net_win_str = "0\n"
            records_message += f"    - 🏆x{net_win_str}"

            if record.gross_wins > 0:
                gross_win_str = f"{record.gross_wins} (most recent: {formatters.format_datetime_to_time_ago(record.most_recent_gross_win)}) \n"
            else:
                gross_win_str = "0\n"
            records_message += f"    - 👑x{gross_win_str}"

            records_message += f"    - 🐐x{record.best_guesses}\n"
            records_message += f"    - 🎣x{record.worst_guesses}\n"
            records_message += (
                f"    - 📉: {record.min_handicap:.0%}\n"
                if record.min_handicap is not None
                else ""
            )
            records_message += (
                f"    - 📈: {record.max_handicap:.0%}\n"
                if record.max_handicap is not None
                else ""
            )

            records_message += f"    - 🏅x{record.podium_finishes}\n"
            records_message += f"    - 🥄x{record.wooden_spoon_finishes}\n"

        await update.message.reply_text(
            records_message,
            parse_mode="HTML",
        )

    @command_handler(league_in_progress=True, round_in_progress=True)
    async def status_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        player_id = update.effective_user.id
        chat_id = update.effective_chat.id

        player_name = TELEGRAM_ID_TO_PLAYER_NAME.get(player_id)

        logger.info(f"Sending status update to chat {chat_id} for player {player_name}")

        round_result = await self.geoguessr_client.get_challenge_scores(
            self.league_state.current_round.challenge_url,
            handicaps=self.active_handicaps,
            challenge_settings=self.league_state.current_round.challenge_settings,
        )

        await self.__status_update(context, chat_id, round_result)

    @command_handler(admin=True, league_in_progress=False)
    async def start_league_handler(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        league_start_date = datetime.now().strftime("%Y%m%d")
        league_filepath = self.active_league_dir / f"league_{league_start_date}.json"
        self.league_state = LeagueState(
            filepath=league_filepath,
            num_rounds=self.league_settings.number_of_rounds,
            players=self.player_manager.get_active_players(),
        )

        self.bet_manager = BetManager(
            model_settings=self.model_settings,
            data_dir=self.data_dir,
            league_date=self.league_state.start_date,
            all_runners=list(self.player_manager.get_active_players()),
        )

        logger.info(f"Starting new league at {league_filepath.absolute()}")

        await update.message.reply_text("New league starting...")

        sorted_handicaps = sorted(
            self.active_handicaps.items(), key=lambda item: item[1]
        )

        handicap_message = "📉 Handicaps:\n\n"
        for player, handicap in sorted_handicaps:
            handicap_message += f"- {player}: {handicap:.0%}\n"
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=handicap_message,
        )

        self.league_state.chat_id = update.effective_chat.id
        self.league_state.save()

        await self.__start_round(context, chat_id=update.effective_chat.id)

    @command_handler(league_in_progress=True)
    async def leaderboard_handler(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        await self.__show_leaderboard(context, chat_id=update.effective_chat.id)

    @command_handler(admin=True, league_in_progress=True, round_in_progress=True)
    async def end_round_handler(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        await self.__end_round(context, update.effective_chat.id)

    @command_handler(league_in_progress=True, round_in_progress=True)
    async def guesses_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_chat.id == self.league_state.chat_id:
            await update.message.reply_text(
                "Guesses are only visible in private chat or Players' Lounge. Please DM me with /guesses to see the current round guesses and rankings.",
            )
            return

        ranked_guesses = await self.__get_ranked_guesses()

        guesses_message = formatters.format_ranked_guesses(ranked_guesses)
        logger.info(
            f"Sending guesses update to chat {update.effective_chat.id}\n\n{guesses_message}"
        )
        await update.message.reply_text(
            guesses_message,
            parse_mode="HTML",
        )

    @command_handler(league_in_progress=True)
    async def outcomes_handler(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        odds = self.bet_manager.get_latest_odds(
            league_round=self.league_state.current_round_num
        )
        if not odds:
            await update.message.reply_text(
                "Odds have not been generated yet for this round. Please check back soon!",
            )
            return

        outcomes = {
            player: self.bet_manager.compute_bet_pnls(winner=player) for player in odds
        }

        bet_outcomes_message = formatters.format_outcomes_message(odds, outcomes)
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=bet_outcomes_message,
            parse_mode="HTML",
        )

    @command_handler(league_in_progress=True)
    async def odds_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        latest_back_odds = self.bet_manager.get_latest_odds(
            league_round=self.league_state.current_round_num
        )
        if not latest_back_odds:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="Odds have not been generated yet for this round. Please check back soon!",
            )
            return

        latest_lay_odds = self.bet_manager.get_latest_odds(
            league_round=self.league_state.current_round_num, bet_type=BetType.LAY
        )
        odds_message = formatters.format_odds_message(latest_back_odds, latest_lay_odds)
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=odds_message,
        )

    @command_handler(league_in_progress=True)
    async def exposure_handler(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        exposure_message = self.__construct_position_message(
            player_name=None, is_bookmaker=True
        )

        await update.message.reply_text(
            exposure_message,
            parse_mode="HTML",
        )

    @command_handler(league_in_progress=True)
    async def position_handler(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        player_id = update.effective_user.id
        player_name = TELEGRAM_ID_TO_PLAYER_NAME.get(player_id)
        if player_name is None:
            await update.message.reply_text(
                "Your Telegram ID is not linked to a player name. Please contact the admin."
            )
            return

        position_message = self.__construct_position_message(player_name=player_name)
        await update.message.reply_text(
            position_message,
            parse_mode="HTML",
        )

    @command_handler(league_in_progress=True, round_in_progress=True)
    async def lounge_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id

        player_name = TELEGRAM_ID_TO_PLAYER_NAME.get(user_id)

        if player_name is None:
            await update.message.reply_text(
                "You are not registered as a player in this league."
            )
            return

        if player_name in self.active_handicaps:
            round_result = await self.geoguessr_client.get_challenge_scores(
                self.league_state.current_round.challenge_url,
                handicaps=self.active_handicaps,
                challenge_settings=self.league_state.current_round.challenge_settings,
            )

            round_status = self.__player_round_status(round_result)
            player_score = round_status.get(player_name)

            if player_score is None or not player_score.is_finished:
                await update.message.reply_text(
                    "You have not completed this round yet. Please complete your round to join the lounge."
                )
                return

        await self.__invite_player_to_lounge(
            context,
            player_name=player_name,
        )

    @command_handler()
    async def handicaps_handler(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        sorted_handicaps = sorted(
            self.active_handicaps.items(), key=lambda item: item[1]
        )

        message = "📉 Current Handicaps:\n\n"
        for player, handicap in sorted_handicaps:
            message += f"- {player}: {handicap:.0%}\n"

        await update.message.reply_text(message)

    @command_handler(league_in_progress=True, round_in_progress=True)
    async def gross_scores_needed_handler(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        player_id = update.effective_user.id
        player_name = TELEGRAM_ID_TO_PLAYER_NAME.get(player_id)

        if player_name is None:
            await update.message.reply_text(
                "You are not registered as a player in this league."
            )
            return

        round_result = await self.geoguessr_client.get_challenge_scores(
            self.league_state.current_round.challenge_url,
            handicaps=self.active_handicaps,
            challenge_settings=self.league_state.current_round.challenge_settings,
        )

        player_status_map = self.__player_round_status(round_result)
        if player_status_map.get(player_name) is None:
            await update.message.reply_text(
                "You have not completed this round yet. Please complete your round to see the gross score needed."
            )
            return

        if update.effective_chat.id == self.league_state.chat_id:
            reply_chat = player_id
        else:
            reply_chat = update.effective_chat.id

        net_scores = []
        players_played_names = set()
        for player, status in player_status_map.items():
            if status is not None and status.is_finished:
                net_scores.append(status.net_score)
                players_played_names.add(player)

        gross_scores_needed = all_gross_scores_needed(
            self.active_handicaps,
            sorted(net_scores, reverse=True),
            players_played=players_played_names,
        )
        message = formatters.format_gross_scores_needed_message(gross_scores_needed)
        await context.bot.send_message(
            chat_id=reply_chat,
            text=message,
            parse_mode="HTML",
        )

    @command_handler(league_in_progress=True, round_in_progress=True)
    async def start_bet(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
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
            challenge_settings=self.league_state.current_round.challenge_settings,
        )

        players_played = self.__player_round_status(round_result)
        if player_id != self.admin_id and players_played.get(player_name) is not None:
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

        if query.data == "cancel":
            await query.edit_message_text("Bet cancelled.")
            return ConversationHandler.END

        context.user_data["bet_player"] = query.data

        runner_back_odds = self.bet_manager.get_latest_odds(
            self.league_state.current_round_num, bet_type=BetType.BACK
        ).get(query.data)
        runner_lay_odds = self.bet_manager.get_latest_odds(
            self.league_state.current_round_num, bet_type=BetType.LAY
        ).get(query.data)

        if not (runner_back_odds or runner_lay_odds):
            await query.edit_message_text(
                f"Sorry, odds for {query.data} are not available. Please try again later."
            )
            return ConversationHandler.END

        context.user_data["back_odds"] = runner_back_odds
        context.user_data["lay_odds"] = runner_lay_odds

        keyboard = [
            [
                InlineKeyboardButton(
                    f"Back ({runner_back_odds.formatted})",
                    callback_data=BetType.BACK.value,
                )
            ]
            if runner_back_odds
            else [],
            [
                InlineKeyboardButton(
                    f"Lay ({runner_lay_odds.formatted})",
                    callback_data=BetType.LAY.value,
                )
            ]
            if runner_lay_odds
            else [],
            [InlineKeyboardButton("Cancel", callback_data="cancel")],
        ]

        await query.edit_message_text(
            f"Runner: *{query.data}*\nWould you like to place a Back or Lay bet?",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown",
        )

        return BET_SELECT_BET_TYPE

    async def handle_bet_type_selection(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> int:
        query = update.callback_query
        await query.answer()

        if query.data == "cancel":
            await query.edit_message_text("Bet cancelled.")
            return ConversationHandler.END

        context.user_data["bet_type"] = BetType(query.data)
        bettor = TELEGRAM_ID_TO_PLAYER_NAME.get(update.effective_user.id)
        bettor_is_active = bettor in self.active_handicaps

        valid_bet_amounts = self.bet_manager.calculate_bet_amounts(
            bettor=bettor,
            runner=context.user_data["bet_player"],
            odds=context.user_data["back_odds"]
            if context.user_data["bet_type"] == BetType.BACK
            else context.user_data["lay_odds"],
            market_type=MarketType.WINNER,
            bet_type=context.user_data["bet_type"],
            bettor_is_active=bettor_is_active,
        )

        if not valid_bet_amounts:
            await query.edit_message_text(
                "Sorry, this bet is not available at the moment."
            )
            return ConversationHandler.END

        keyboard = [
            [InlineKeyboardButton(f"€{amount}", callback_data=str(amount))]
            for amount in valid_bet_amounts
        ]
        keyboard.append([InlineKeyboardButton("Cancel", callback_data="cancel")])
        await query.edit_message_text(
            f"Runner: *{context.user_data['bet_player']}*\nBet Type: *{query.data}*\nHow much would you like to bet?",
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
        bet_odds: FractionalOdds = (
            context.user_data["back_odds"]
            if context.user_data["bet_type"] == BetType.BACK
            else context.user_data["lay_odds"]
        )
        amount = float(query.data)

        bettor = TELEGRAM_ID_TO_PLAYER_NAME[update.effective_user.id]
        if bettor in self.league_state.get_players_finished_round():
            await query.edit_message_text(
                "You have already started this round, so you cannot place bets. Please wait for the next round to start."
            )
            return ConversationHandler.END

        try:
            bet = self.bet_manager.place_bet(
                bettor=bettor,
                runner=player,
                amount=amount,
                odds=bet_odds,
                market_type=MarketType.WINNER,
                bet_type=context.user_data["bet_type"],
            )
        except BettingSuspendedError:
            await query.edit_message_text(
                "⚠️ Betting is currently suspended for this round. Please try again later."
            )
            return ConversationHandler.END

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

    @command_handler(admin=True, league_in_progress=True)
    async def suspend_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        is_newly_suspended = self.bet_manager.suspend_betting()

        if is_newly_suspended:
            await update.message.reply_text(
                "⚠️ Betting has been suspended for this round."
            )
        else:
            await update.message.reply_text(
                "⚠️ Betting was already suspended for this round."
            )

    @command_handler(admin=True, league_in_progress=True)
    async def unsuspend_handler(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        is_newly_resumed = self.bet_manager.resume_betting()

        if is_newly_resumed:
            await update.message.reply_text(
                "✅ Betting has been resumed for this round."
            )
        else:
            await update.message.reply_text(
                "✅ Betting was already active for this round."
            )

    @command_handler(league_in_progress=True)
    async def rank_scores_handler(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        rank_scores = get_rank_scores_list(len(self.active_handicaps))
        msg = formatters.format_rank_scores(rank_scores)
        await update.message.reply_text(msg, parse_mode="HTML")
