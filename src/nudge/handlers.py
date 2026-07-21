"""Telegram handlers. Every entry point is guarded by the allowlist."""

from __future__ import annotations

import functools
import logging
from collections.abc import Awaitable, Callable

from telegram import Update
from telegram.ext import ContextTypes

from .config import get_settings

log = logging.getLogger(__name__)

Handler = Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[None]]


def restricted(func: Handler) -> Handler:
    """Drop (and log) any update whose sender is not the single allowed user."""

    @functools.wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        allowed = get_settings().telegram_allowed_user_id
        user = update.effective_user
        if user is None or user.id != allowed:
            log.warning(
                "dropped update from unauthorized user id=%s username=%s",
                getattr(user, "id", None),
                getattr(user, "username", None),
            )
            return
        await func(update, context)

    return wrapper


@restricted
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    name = get_settings().owner_name
    await update.effective_message.reply_text(
        f"nudge на связи, {name}. Кидай задачу текстом — разберу и добавлю. "
        "Пересланные сообщения тоже ловлю."
    )
