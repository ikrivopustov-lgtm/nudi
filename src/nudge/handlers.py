"""Telegram handlers. Every entry point is guarded by the allowlist."""

from __future__ import annotations

import functools
import logging
from collections.abc import Awaitable, Callable
from datetime import date, datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from . import store
from .config import get_settings
from .llm import parse_text
from .models import Task

log = logging.getLogger(__name__)

Handler = Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[None]]

_PENDING_PROJECT = "await_project_for"  # user_data key: task id awaiting a project name


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


def local_today() -> date:
    return datetime.now(get_settings().tz).date()


# --- confirmation rendering ------------------------------------------------

def _confirm_text(task: Task) -> str:
    lines = [f"✅ Задача #{task.id}: <b>{_esc(task.title)}</b>"]
    lines.append(f"Приоритет: {task.priority} · Статус: {task.status}")
    if task.project:
        lines.append(f"Проект: {_esc(task.project)}")
    if task.due_date:
        lines.append(f"Дедлайн: {task.due_date.isoformat()}")
    lines.append(f"Неделя: {task.iso_week}")
    return "\n".join(lines)


def _confirm_keyboard(task_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("☀️ В сегодня", callback_data=f"today|{task_id}")],
            [
                InlineKeyboardButton("P1", callback_data=f"prio|{task_id}|P1"),
                InlineKeyboardButton("P2", callback_data=f"prio|{task_id}|P2"),
                InlineKeyboardButton("P3", callback_data=f"prio|{task_id}|P3"),
            ],
            [InlineKeyboardButton("🗂 Проект…", callback_data=f"proj|{task_id}")],
        ]
    )


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


async def _send_confirmation(update: Update, task: Task) -> None:
    await update.effective_message.reply_text(
        _confirm_text(task),
        reply_markup=_confirm_keyboard(task.id),
        parse_mode="HTML",
    )


# --- handlers --------------------------------------------------------------

@restricted
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    name = get_settings().owner_name
    await update.effective_message.reply_text(
        f"nudge на связи, {name}. Кидай задачу текстом — разберу и добавлю. "
        "Пересланные сообщения тоже ловлю."
    )


@restricted
async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    text = (message.text or "").strip()
    if not text:
        return

    # If we asked for a project name for an existing task, consume this reply as that.
    pending_id = context.user_data.pop(_PENDING_PROJECT, None) if context.user_data else None
    if pending_id is not None:
        task = store.update_task(pending_id, project=text)
        if task:
            await message.reply_text(f"Проект задачи #{task.id}: {task.project}")
        return

    parsed = await parse_text(text, today=local_today())
    task = store.create_task(
        title=parsed["title"],
        raw_text=text,
        iso_week=parsed["iso_week"],
        project=parsed["project"],
        priority=parsed["priority"],
        due_date=parsed["due_date"],
        source="tg",
    )
    await _send_confirmation(update, task)


@restricted
async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    parts = (query.data or "").split("|")
    action = parts[0]

    if action == "today" and len(parts) == 2:
        task = store.update_task(int(parts[1]), status="today", scheduled_for=local_today())
        if task:
            await query.edit_message_text(_confirm_text(task), reply_markup=_confirm_keyboard(task.id), parse_mode="HTML")
        return

    if action == "prio" and len(parts) == 3 and parts[2] in {"P1", "P2", "P3"}:
        task = store.update_task(int(parts[1]), priority=parts[2])
        if task:
            await query.edit_message_text(_confirm_text(task), reply_markup=_confirm_keyboard(task.id), parse_mode="HTML")
        return

    if action == "proj" and len(parts) == 2:
        if context.user_data is not None:
            context.user_data[_PENDING_PROJECT] = int(parts[1])
        await query.message.reply_text("Напиши название проекта одним сообщением.")
        return

    # --- weekly-ritual triage ---
    if action == "wk_today" and len(parts) == 2:
        store.update_task(int(parts[1]), status="today", scheduled_for=local_today())
        await query.edit_message_text("☀️ → сегодня")
        return

    if action == "wk_someday" and len(parts) == 2:
        store.update_task(int(parts[1]), status="someday")
        await query.edit_message_text("💤 → someday")
        return

    if action == "wk_del" and len(parts) == 2:
        store.delete_task(int(parts[1]))
        await query.edit_message_text("🗑 удалено")
        return
