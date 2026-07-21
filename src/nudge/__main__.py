"""Entry point: start the Telegram bot (long-polling) + JobQueue."""

from __future__ import annotations

import logging
import os

from telegram import BotCommand
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from datetime import time as dtime

from . import store
from .airtable_sync import airtable_sync_job, is_configured
from .config import get_settings
from .db import init_db
from .digest import morning_digest, weekly_ritual
from .handlers import cmd_backlog, cmd_help, cmd_today, on_callback, on_text, start


def _configure_logging() -> None:
    logging.basicConfig(
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        level=logging.INFO,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)


async def _post_init(app: Application) -> None:
    """Publish the '/' menu and re-arm reminders that outlived a restart."""
    await app.bot.set_my_commands(
        [
            BotCommand("today", "Что делать сегодня (максимум 5)"),
            BotCommand("backlog", "Разобрать инбокс"),
            BotCommand("help", "Что я умею"),
            BotCommand("start", "Показать кнопки"),
        ]
    )
    from datetime import datetime, timezone

    from .digest import reminder_job

    now = datetime.now(timezone.utc)
    for task in store.tasks_with_future_reminders(now):
        when = task.remind_at
        if when.tzinfo is None:  # SQLite returns naive; the stored value is UTC
            when = when.replace(tzinfo=timezone.utc)
        app.job_queue.run_once(
            reminder_job, when=when, data=task.id, name=f"reminder:{task.id}"
        )


def build_application() -> Application:
    settings = get_settings()
    app = (
        Application.builder()
        .token(settings.telegram_bot_token)
        .post_init(_post_init)
        .build()
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("today", cmd_today))
    app.add_handler(CommandHandler("backlog", cmd_backlog))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    register_jobs(app)
    return app


def register_jobs(app: Application) -> None:
    settings = get_settings()
    tz = settings.tz
    morning = dtime(settings.morning_at.hour, settings.morning_at.minute, tzinfo=tz)
    app.job_queue.run_daily(morning_digest, time=morning, name="morning_digest")

    # PTB v21: days 0-6 = Sunday-Saturday, so Sunday = 0.
    weekly = dtime(settings.weekly_at.hour, settings.weekly_at.minute, tzinfo=tz)
    app.job_queue.run_daily(weekly_ritual, time=weekly, days=(0,), name="weekly_ritual")

    if is_configured():
        app.job_queue.run_repeating(
            airtable_sync_job, interval=600, first=30, name="airtable_sync"
        )
    else:
        logging.getLogger("nudge").info("Airtable not configured — sync job skipped")


def main() -> None:
    _configure_logging()
    settings = get_settings()
    # Keep db.py and config in sync on the storage path.
    os.environ.setdefault("DATABASE_PATH", settings.database_path)
    init_db()

    app = build_application()
    logging.getLogger("nudge").info("nudge up — polling as allowed user %s", settings.telegram_allowed_user_id)
    app.run_polling(allowed_updates=["message", "edited_message", "callback_query"])


if __name__ == "__main__":
    main()
