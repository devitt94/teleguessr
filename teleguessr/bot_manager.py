from pathlib import Path
import traceback

from telegram import Update
from telegram.ext import Application as TelegramApp

from teleguessr.awards import get_ranked_guesses
from teleguessr.formatters import (
    format_leaderboard_html,
    format_round_result_html,
    format_time,
)
from teleguessr.geoguessr_scraper import GeoguessrClient
from teleguessr.league import LeagueState
from teleguessr.settings import LeagueSettings
from loguru import logger

from teleguessr.handicaps import (
    calculate_new_handicaps,
    get_latest_handicaps,
    update_handicaps,
)
from teleguessr.ranks import get_ranks_from_scores

from telegram.ext import ContextTypes


class BotManager:
    def __init__(
        self,
        admin_id: int,
        data_dir: Path,
        league_settings: LeagueSettings,
        geoguessr_client: GeoguessrClient,
    ):
        self.admin_id = admin_id
        self.data_dir = data_dir
        self.league_settings = league_settings
        self.league_state = None
        self.__initialised = False
        self.geoguessr_client = geoguessr_client

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

        self.__initialised = True

    async def resume_league_tasks(self, app: TelegramApp):
        if not self.__initialised:
            raise RuntimeError("BotManager not initialised!")

        if self.league_state is not None and not self.league_state.is_finished:
            if self.league_state.round_in_progress:
                round_end_in_seconds = self.league_state.get_time_left_seconds()
                logger.info(
                    f"Resuming scheduled tasks for round {self.league_state.current_round_num}, "
                    f"which ends in {round_end_in_seconds} seconds."
                )

                total_round_time_seconds = (
                    self.league_settings.time_per_round_hours * 3600
                )
                reminder_time_in_seconds = total_round_time_seconds * 1 / 12
                if round_end_in_seconds < reminder_time_in_seconds:
                    logger.info(
                        "Round end is within reminder period; skipping reminder scheduling."
                    )
                else:
                    logger.info("Scheduling round reminder job.")

                    app.job_queue.run_once(
                        self.remind_scheduled,
                        when=round_end_in_seconds - reminder_time_in_seconds,
                        chat_id=self.league_state.chat_id,
                        name="round_reminder_job",
                    )

                app.job_queue.run_once(
                    self.end_round_scheduled,
                    when=round_end_in_seconds,
                    chat_id=self.league_state.chat_id,
                    name="end_round_job",
                )
            else:
                chat_id = self.league_state.chat_id
                self.start_round(app.context_types.DEFAULT_TYPE, chat_id=chat_id)

    async def get_new_league_id(self) -> int:
        finished_leagues = list(self.finished_league_dir.iterdir())
        return len(finished_leagues) + 1

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

        league_id = await self.get_new_league_id()
        league_filepath = self.active_league_dir / f"league_{league_id}.json"
        self.league_state = LeagueState(
            filepath=league_filepath,
            num_rounds=self.league_settings.number_of_rounds,
        )

        logger.info(
            f"Starting new league with ID {league_id} at {league_filepath.absolute()}"
        )

        await update.message.reply_text("New league starting...")

        self.league_state.chat_id = update.effective_chat.id
        self.league_state.save()

        await self.start_round(context, chat_id=update.effective_chat.id)

    async def start_round(self, context: ContextTypes.DEFAULT_TYPE, chat_id: int):
        challenge_url = await self.geoguessr_client.create_challenge(
            map_id=self.league_settings.map_id,
            time_limit_seconds=self.league_settings.time_per_guess_seconds,
        )
        self.league_state.start_round(
            url=challenge_url,
            hours=self.league_settings.time_per_round_hours,
        )

        round_ends_in_seconds = self.league_settings.time_per_round_hours * 3600
        logger.info(
            f"Started round {self.league_state.current_round_num} with challenge URL: {challenge_url}. "
            f"Round ends in {round_ends_in_seconds} seconds."
        )

        context.job_queue.run_once(
            self.remind_scheduled,
            when=(round_ends_in_seconds * 11 / 12),
            chat_id=chat_id,
        )
        context.job_queue.run_once(
            self.end_round_scheduled,
            when=round_ends_in_seconds,
            chat_id=chat_id,
        )

        self.league_state.save()

        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                f"🏁 Round {self.league_state.current_round_num} has started!\n\n"
                f"Challenge URL: {challenge_url}\n"
                f"This round will end in {format_time(round_ends_in_seconds)}."
            ),
        )

    async def status_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.__initialised:
            raise RuntimeError("BotManager not initialised!")

        if self.league_state is None or self.league_state.is_finished:
            status_message = "No active league. Start a new league with /startleague."
        else:
            status_message = f"League Status:\n- Rounds completed: {self.league_state.last_round_finished_num}/{self.league_state.num_rounds}\n"
            if self.league_state.round_in_progress:
                players_played = await self.player_round_status()
                time_left = self.league_state.get_time_left_seconds()
                status_message += (
                    f"- Current round in progress (ends in {format_time(time_left)})\n"
                )
                status_message += "- Players who have played this round:\n"
                for player, finished in players_played.items():
                    status_message += f"  - {player}: {'✅' if finished else '❌'}\n"

            else:
                status_message += "- No round currently in progress.\n"

        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=status_message,
        )

    async def remind_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.__initialised:
            raise RuntimeError("BotManager not initialised!")

        if self.league_state is None or self.league_state.is_finished:
            await update.message.reply_text("No active league.")
            return

        await self.reminder(context, update.effective_chat.id)

    async def remind_scheduled(self, context: ContextTypes.DEFAULT_TYPE):
        if not self.__initialised:
            raise RuntimeError("BotManager not initialised!")

        if self.league_state is None or self.league_state.is_finished:
            return

        await self.reminder(context, context.job.chat_id)

    async def reminder(self, context: ContextTypes.DEFAULT_TYPE, chat_id: int):
        if chat_id is None:
            raise ValueError("chat_id must be provided to reminder")

        players_finished = await self.player_round_status()

        time_left = self.league_state.get_time_left_seconds()
        time_left_str = format_time(time_left)

        players_pending = {
            player for player, finished in players_finished.items() if not finished
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
            f"The following players have not played yet:\n{pending_list}\n\n"
            f"Round URL: {self.league_state.current_round.challenge_url}"
        )

        await context.bot.send_message(
            chat_id,
            message,
        )

    async def end_round_scheduled(self, context: ContextTypes.DEFAULT_TYPE):
        if not self.__initialised:
            raise RuntimeError("BotManager not initialised!")

        if self.league_state is None or self.league_state.is_finished:
            return

        await self.end_round(context, context.job.chat_id)

    async def end_round_handler(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        if not self.__initialised:
            raise RuntimeError("BotManager not initialised!")

        if self.league_state is None or self.league_state.is_finished:
            await update.message.reply_text("No active league.")
            return

        if not self.league_state.round_in_progress:
            await update.message.reply_text("No round in progress.")
            return

        await self.end_round(context, update.effective_chat.id)

        # Clear the job queue to avoid duplicate end round calls
        current_jobs = context.job_queue.get_jobs_by_name("end_round_job")
        for job in current_jobs:
            job.schedule_removal()

        current_jobs = context.job_queue.get_jobs_by_name("round_reminder_job")
        for job in current_jobs:
            job.schedule_removal()

    async def end_round(self, context: ContextTypes.DEFAULT_TYPE, chat_id: int):
        if chat_id is None:
            raise ValueError("chat_id must be provided to end_round")

        challenge_url = self.league_state.current_round.challenge_url
        round_result = await self.geoguessr_client.get_challenge_scores(
            challenge_url,
            handicaps=self.handicaps,
            default_handicap=self.league_settings.default_handicap_multiplier,
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
                new_handicaps, self.league_state.league_id, self.league_settings
            )

            logger.info(f"Updated handicaps: {new_handicaps}")
            await self.show_handicap_updates(
                context,
                chat_id,
                prev_handicaps=self.handicaps,
                new_handicaps=new_handicaps,
            )
            self.handicaps = new_handicaps
            await self.end_league()

        else:
            await self.start_round(context, chat_id=chat_id)

    async def show_leaderboard_handler(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        if not self.__initialised:
            raise RuntimeError("BotManager not initialised!")

        if self.league_state is None or self.league_state.is_finished:
            await update.message.reply_text("No active league.")
            return

        await self.show_leaderboard(context, update.effective_chat.id)

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
        tb_list = traceback.format_exception(
            None, context.error, context.error.__traceback__
        )
        tb_text = "".join(tb_list)

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

    async def player_round_status(self) -> dict[str, bool]:
        if (
            self.league_state is None
            or self.league_state.is_finished
            or not self.league_state.round_in_progress
        ):
            raise RuntimeError("No active round.")

        challenge_url = self.league_state.current_round.challenge_url
        current_result = await self.geoguessr_client.get_challenge_scores(
            challenge_url,
            handicaps=self.handicaps,
            default_handicap=self.league_settings.default_handicap_multiplier,
        )
        players_finished = current_result.players_finished

        result = {player: False for player in self.handicaps.keys()}
        for player in players_finished:
            result[player] = True
        return result

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

    async def show_current_round_scores_handler(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        if self.league_state is None or self.league_state.is_finished:
            context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="No active league.",
            )
            return
        if not self.league_state.round_in_progress:
            context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="No round in progress.",
            )
            return

        message = await self.current_round_scores_message()

        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=message,
            parse_mode="HTML",
        )

    async def current_round_scores_message(self) -> str:
        challenge_url = self.league_state.current_round.challenge_url
        round_result = await self.geoguessr_client.get_challenge_scores(
            challenge_url,
            handicaps=self.handicaps,
            default_handicap=self.league_settings.default_handicap_multiplier,
        )

        net_scores = sorted(
            [(score.player.name, score.net_score) for score in round_result.scores],
            key=lambda x: x[1],
            reverse=True,
        )

        round_text = "🏁 Current Round Scores:\n\n"
        for name, score in net_scores:
            round_text += f"- {name}: {score} pts\n"

        return round_text

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
