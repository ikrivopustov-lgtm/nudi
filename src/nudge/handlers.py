"""Telegram handlers. Every entry point is guarded by the allowlist.

Free-form messages go to the agentic assistant; commands and the persistent
keyboard give quick deterministic access to the digest and inbox triage.
"""

from __future__ import annotations

import functools
import logging
from collections.abc import Awaitable, Callable
from datetime import date, datetime

from telegram import ReplyKeyboardMarkup, Update
from telegram.ext import ContextTypes

from . import assistant, store
from .config import get_settings
from .models import priority_dot

log = logging.getLogger(__name__)

Handler = Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[None]]

# Persistent keyboard. These exact strings are intercepted in on_text BEFORE the
# assistant sees them, so pressing a button is a command, never a task.
BTN_TODAY = "☀️ Сегодня"
BTN_BACKLOG = "📋 Бэклог"
BTN_HELP = "❓ Помощь"

MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [[BTN_TODAY, BTN_BACKLOG], [BTN_HELP]],
    resize_keyboard=True,
    is_persistent=True,
)

HELP_TEXT = (
    "<b>Nudi</b> — ассистент задач. Пиши как думаешь, я пойму.\n\n"
    "<b>Просто говори</b>\n"
    "• «оплатить налоги до 25 июля, красным» → заведу со сроком и 🔴\n"
    "• «сделал налоги» → закрою\n"
    "• «давай на завтра эту задачу» → перенесу\n"
    "• «напомни про звонок сегодня в 15:00» → пну в это время\n"
    "• «созвон каждый понедельник» → повторяющаяся\n"
    "• «отмени» → откачу последнее действие\n"
    "• «что горит на этой неделе?» → просто отвечу, без задачи\n\n"
    "<b>Приоритеты — цветом</b>\n"
    "🔴 срочно · 🟠 обычный · 🟡 потом. «сделай жёлтой» — сменю.\n\n"
    "<b>Команды и кнопки</b>\n"
    "/today — список на сегодня (максимум 5)\n"
    "/backlog — разобрать инбокс кнопками\n"
    "/help — эта справка\n\n"
    "<b>Сам напомню</b>\n"
    "Утром в 08:30 — план на день, в воскресенье в 19:00 — разбор инбокса."
)


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


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# --- commands --------------------------------------------------------------

@restricted
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    name = get_settings().owner_name
    await update.effective_message.reply_text(
        f"Nudi на связи, {name}. Пиши задачи и правки как думаешь — я разберусь.\n"
        "Кнопки снизу: план на сегодня, разбор инбокса, справка.",
        reply_markup=MAIN_KEYBOARD,
    )


@restricted
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(
        HELP_TEXT, parse_mode="HTML", reply_markup=MAIN_KEYBOARD
    )


@restricted
async def cmd_today(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from .digest import render_digest
    from .priority import select_today

    today = local_today()
    tasks = select_today(today)
    active = len(store.list_active())
    text = render_digest(tasks, today)
    if active > len(tasks):
        text += f"\n\n<i>ещё {active - len(tasks)} в очереди — покажу, когда разгрузишь</i>"
    await update.effective_message.reply_text(text, parse_mode="HTML")


@restricted
async def cmd_backlog(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from .digest import WEEKLY_TRIAGE_CAP, triage_keyboard

    message = update.effective_message
    inbox = store.list_by_status("inbox")
    someday = store.count_by_status("someday")

    if not inbox:
        tail = f"\nВ «когда-нибудь» лежит: {someday}." if someday else ""
        await message.reply_text(f"📋 Инбокс пуст. Чисто.{tail}")
        return

    tail = f" · в «когда-нибудь»: {someday}" if someday else ""
    await message.reply_text(
        f"📋 <b>Инбокс</b>: {len(inbox)}{tail}. Разложим:", parse_mode="HTML"
    )
    for t in inbox[:WEEKLY_TRIAGE_CAP]:
        proj = f" · {_esc(t.project)}" if t.project else ""
        await message.reply_text(
            f"{priority_dot(t.priority)} {_esc(t.title)}{proj}",
            reply_markup=triage_keyboard(t.id),
            parse_mode="HTML",
        )
    if len(inbox) > WEEKLY_TRIAGE_CAP:
        await message.reply_text(f"…и ещё {len(inbox) - WEEKLY_TRIAGE_CAP}.")


# --- free-form messages -> assistant ---------------------------------------

@restricted
async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    text = (message.text or "").strip()
    if not text:
        return

    # Keyboard presses are commands, not tasks — intercept before the assistant.
    if text == BTN_TODAY:
        await cmd_today(update, context)
        return
    if text == BTN_BACKLOG:
        await cmd_backlog(update, context)
        return
    if text == BTN_HELP:
        await cmd_help(update, context)
        return

    if message.forward_origin is not None:
        text = f"[Пересланное сообщение, заведи как задачу]\n{text}"

    settings = get_settings()
    await context.bot.send_chat_action(chat_id=message.chat_id, action="typing")
    reply = await assistant.handle_message(
        text,
        today=local_today(),
        tz=settings.tz,
        schedule_reminder=_make_reminder_scheduler(context),
    )
    await message.reply_text(reply)


def _make_reminder_scheduler(context: ContextTypes.DEFAULT_TYPE):
    """Give the assistant a way to arm a one-off reminder job."""
    from .digest import reminder_job

    def schedule(task_id: int, when_utc) -> None:
        jq = context.job_queue
        if jq is None:
            return
        for job in jq.get_jobs_by_name(f"reminder:{task_id}"):
            job.schedule_removal()
        jq.run_once(reminder_job, when=when_utc, data=task_id, name=f"reminder:{task_id}")

    return schedule


# --- inline triage buttons (weekly ritual + /backlog) ----------------------

@restricted
async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    parts = (query.data or "").split("|")
    action = parts[0]

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
