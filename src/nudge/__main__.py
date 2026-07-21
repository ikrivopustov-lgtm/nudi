"""Entry point: start the Telegram bot (long-polling) + JobQueue."""

from __future__ import annotations

import logging
import os

from telegram.ext import Application, CommandHandler

from .config import get_settings
from .db import init_db
from .handlers import start


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
    return app


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
