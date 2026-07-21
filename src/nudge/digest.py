"""Scheduled nudges: morning digest (rule of 5) and the weekly ritual (P6)."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from . import store
from .config import get_settings
from .models import Task, priority_dot
from .priority import select_today

WEEKLY_TRIAGE_CAP = 12  # don't spam more than this many inbox items at once

log = logging.getLogger(__name__)


def _local_today() -> date:
    return datetime.now(get_settings().tz).date()


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render_digest(tasks: list[Task], today: date) -> str:
    if not tasks:
        return "☀️ Доброе утро. На сегодня пусто — можно выдохнуть или закинуть задачу."
    lines = ["☀️ <b>Сегодня</b> (правило 5):"]
    for i, t in enumerate(tasks, 1):
        mark = ""
        if t.due_date and t.due_date < today:
            mark = " ⏰просрочено"
        elif t.due_date:
            mark = f" (до {t.due_date.isoformat()})"
        proj = f" · {_esc(t.project)}" if t.project else ""
        lines.append(f"{i}. {priority_dot(t.priority)} {_esc(t.title)}{proj}{mark}")
    return "\n".join(lines)


async def morning_digest(context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = get_settings()
    today = _local_today()
    tasks = select_today(today)
    text = render_digest(tasks, today)
    await context.bot.send_message(
        chat_id=settings.telegram_allowed_user_id,
        text=text,
        parse_mode="HTML",
    )
    log.info("morning digest sent (%d tasks)", len(tasks))


def triage_keyboard(task_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("☀️ Сегодня", callback_data=f"wk_today|{task_id}"),
                InlineKeyboardButton("💤 Someday", callback_data=f"wk_someday|{task_id}"),
                InlineKeyboardButton("🗑", callback_data=f"wk_del|{task_id}"),
            ]
        ]
    )


def weekly_stats_line() -> str:
    """One-line 'closed X / hanging Y' summary for the ritual header."""
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    done = len(store.completed_since(week_ago))
    active = len(store.list_active())
    return f"📊 За неделю закрыл: {done} · сейчас висит: {active}"


async def reminder_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """One-off reminder ping armed by the assistant's set_reminder tool."""
    task_id = context.job.data
    task = store.get_task(task_id)
    if task is None or task.status == "done":
        return
    settings = get_settings()
    proj = f" · {_esc(task.project)}" if task.project else ""
    await context.bot.send_message(
        chat_id=settings.telegram_allowed_user_id,
        text=f"⏰ Напоминание: {priority_dot(task.priority)} {_esc(task.title)}{proj}",
        parse_mode="HTML",
    )
    store.update_task(task.id, remind_at=None)  # fired once
    log.info("reminder fired for task %s", task_id)


async def weekly_ritual(context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = get_settings()
    chat_id = settings.telegram_allowed_user_id
    inbox = store.list_by_status("inbox")
    stats = weekly_stats_line()

    if not inbox:
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"🧹 Еженедельный разбор: инбокс пуст. Чисто.\n{stats}",
        )
        return

    await context.bot.send_message(
        chat_id=chat_id,
        text=f"🧹 <b>Еженедельный разбор</b>\n{stats}\nВ инбоксе задач: {len(inbox)}. Разложим:",
        parse_mode="HTML",
    )
    for t in inbox[:WEEKLY_TRIAGE_CAP]:
        proj = f" · {_esc(t.project)}" if t.project else ""
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"{priority_dot(t.priority)} {_esc(t.title)}{proj}",
            reply_markup=triage_keyboard(t.id),
            parse_mode="HTML",
        )
    if len(inbox) > WEEKLY_TRIAGE_CAP:
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"…и ещё {len(inbox) - WEEKLY_TRIAGE_CAP}. Разберём в следующий раз.",
        )
    log.info("weekly ritual sent (%d inbox tasks)", len(inbox))
