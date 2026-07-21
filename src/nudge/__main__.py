"""Entry point: start the Telegram bot (long-polling) + JobQueue."""

from __future__ import annotations

import logging
import os

from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from datetime import time as dtime

from .config import get_settings
from .db import init_db
from .digest import morning_digest, weekly_ritual
from .handlers import on_callback, on_text, start


def _configure_logging() -> None:
    logging.basicConfig(
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        level=logging.INFO,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)


def build_application() -> Application:
    settings = get_settings()
    app = Application.builder().token(settings.telegram_bot_token).build()
    app.add_handler(CommandHandler("start", start))
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
