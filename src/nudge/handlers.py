"""Telegram handlers. Every entry point is guarded by the allowlist."""

from __future__ import annotations

import functools
import logging
import re
from collections.abc import Awaitable, Callable
from datetime import date, datetime

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    Update,
)
from telegram.ext import ContextTypes

from . import store
from .config import get_settings
from .llm import iso_week_of, parse_edit, parse_text
from .models import Task

log = logging.getLogger(__name__)

Handler = Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[None]]

_PENDING_PROJECT = "await_project_for"  # user_data key: task id awaiting a project name
_LAST_TASK = "last_task_id"             # user_data key: task the user last touched

# Persistent keyboard. These exact strings are intercepted in on_text BEFORE
# capture, so pressing a button never creates a task.
BTN_TODAY = "☀️ Сегодня"
BTN_BACKLOG = "📋 Бэклог"
BTN_HELP = "❓ Помощь"

MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [[BTN_TODAY, BTN_BACKLOG], [BTN_HELP]],
    resize_keyboard=True,
    is_persistent=True,
)

HELP_TEXT = (
    "<b>Nudi</b> — ловлю задачи и не даю списку разрастись.\n\n"
    "<b>Как добавить</b>\n"
    "Просто напиши текстом: «оплатить налоги до 25 июля». Разберу на заголовок, "
    "проект, приоритет и дедлайн. Пересланное сообщение тоже станет задачей.\n\n"
    "<b>Как править — тоже текстом</b>\n"
    "• «сделал налоги» → закрою\n"
    "• «сдвинь звонок на пятницу» → перенесу (когда всплывёт)\n"
    "• «поставь дедлайн на 30 июля» → жёсткий срок\n"
    "• «давай эту задачу на неделю» → перенесу на +7 дней\n"
    "• «подними приоритет по стоматологу» → сменю приоритет\n\n"
    "<b>Про «эту задачу»</b>\n"
    "Можно не называть задачу — скажи «давай на завтра эту задачу», и я возьму "
    "последнюю, с которой мы работали. Надёжнее всего — <b>ответить реплаем</b> на "
    "карточку задачи, тогда я точно не промахнусь.\n\n"
    "<b>Команды</b>\n"
    "/today — что делать сегодня (максимум 5)\n"
    "/backlog — разобрать инбокс кнопками\n"
    "/help — это сообщение\n\n"
    "<b>Сам напомню</b>\n"
    "Утром в 08:30 пришлю список на день, в воскресенье в 19:00 — разбор инбокса.\n\n"
    "⚠️ Учти: я считаю задачей <i>любой</i> текст. Вопросы задавай кнопками и "
    "командами, иначе вопрос осядет задачей."
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


_STEM_LEN = 5  # crude stemming: enough to survive Russian/English inflection
                # ("оплатил"->"оплат" matches "оплатить", "звонок"->"звон" matches "позвонить")


def _match_score(hint: str, task: Task) -> float:
    """Token-overlap score of a hint against a task's title+project+original text."""
    hay = f"{task.title} {task.project or ''} {task.raw_text}".lower()
    tokens = [w for w in hint.lower().split() if len(w) > 2]
    if not tokens:
        return 0.0
    hits = sum(1 for w in tokens if w[:_STEM_LEN] in hay)
    return hits / len(tokens)


# Deictic references — they point at a task without naming it.
_DEICTIC = {
    "эту", "это", "эта", "этой", "этот", "её", "ее", "его", "их", "тут",
    "задачу", "задача", "задачи", "последнюю", "последняя", "предыдущую",
    "this", "that", "it", "task", "last", "one",
}

_TASK_ID_RE = re.compile(r"Задача #(\d+)")


def _is_deictic(hint: str | None) -> bool:
    """True when the hint names no task, just points ('эту задачу', 'её')."""
    if not hint:
        return True
    words = [w.strip(".,!?:;«»\"'") for w in hint.lower().split()]
    words = [w for w in words if w]
    return bool(words) and all(w in _DEICTIC for w in words)


def target_from_reply(message) -> Task | None:
    """If the user replied to a task card ('✅ Задача #12: …'), that's the target."""
    reply = getattr(message, "reply_to_message", None)
    if reply is None:
        return None
    match = _TASK_ID_RE.search(reply.text or reply.caption or "")
    if not match:
        return None
    return store.get_task(int(match.group(1)))


def resolve_target(hint: str | None) -> Task | None:
    """Best active task matching the hint (score >= 0.5), newest wins on ties."""
    if not hint:
        return None
    scored = [(_match_score(hint, t), t) for t in store.list_active()]
    scored = [(sc, t) for sc, t in scored if sc >= 0.5]
    if not scored:
        return None
    scored.sort(key=lambda st: (st[0], st[1].id), reverse=True)
    return scored[0][1]


def _pick_target(update: Update, context: ContextTypes.DEFAULT_TYPE, hint: str | None) -> Task | None:
    """Reply-to beats a pronoun, a pronoun beats fuzzy matching."""
    # 1. Explicit: user replied to a task card.
    by_reply = target_from_reply(update.effective_message)
    if by_reply is not None:
        return by_reply

    # 2. Deictic ('эту задачу', 'её') -> the task we last touched.
    if _is_deictic(hint):
        last_id = (context.user_data or {}).get(_LAST_TASK)
        if last_id is not None:
            task = store.get_task(last_id)
            if task is not None and task.status != "done":
                return task
        return store.last_touched_active()

    # 3. Named: fuzzy match on title/project/raw text.
    return resolve_target(hint)


async def _apply_edit(update: Update, context: ContextTypes.DEFAULT_TYPE, edit: dict) -> bool:
    """Apply a parsed edit. Returns True if handled (found + applied or reported)."""
    action = edit["action"]
    message = update.effective_message
    target = _pick_target(update, context, edit["target_hint"])

    if target is None:
        hint = edit["target_hint"]
        if _is_deictic(hint):
            await message.reply_text("Не понял, о какой задаче речь — назови её или ответь на карточку.")
        else:
            await message.reply_text(f"Не нашёл задачу по «{hint}». Уточни или пришли как новую.")
        return True

    if action == "done":
        store.update_task(target.id, status="done")
        await message.reply_text(f"✔️ Готово: {target.title}")
    elif action == "priority":
        store.update_task(target.id, priority=edit["value"])
        await message.reply_text(f"Приоритет {edit['value']}: {target.title}")
    elif action == "reschedule":
        new_date = edit["value"]
        fields = {"scheduled_for": new_date, "iso_week": iso_week_of(target.due_date or new_date)}
        # Moving it to today puts it on today's list; moving it away takes it off.
        if new_date == local_today():
            fields["status"] = "today"
        elif target.status == "today":
            fields["status"] = "inbox"
        store.update_task(target.id, **fields)
        await message.reply_text(
            f"↪️ Перенёс на {_human_date(new_date)}: {target.title}"
        )
    elif action == "deadline":
        due = edit["value"]
        store.update_task(target.id, due_date=due, iso_week=iso_week_of(due))
        await message.reply_text(f"⏳ Дедлайн {_human_date(due)}: {target.title}")

    _remember(context, target.id)
    return True


def _human_date(d: date) -> str:
    delta = (d - local_today()).days
    if delta == 0:
        return "сегодня"
    if delta == 1:
        return "завтра"
    return d.isoformat()


def _remember(context: ContextTypes.DEFAULT_TYPE, task_id: int) -> None:
    if context.user_data is not None:
        context.user_data[_LAST_TASK] = task_id


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
        f"Nudi на связи, {name}. Кидай задачу текстом — разберу и добавлю.\n"
        "Кнопки снизу: список на сегодня, разбор инбокса, справка.",
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
            f"[{t.priority}] {_esc(t.title)}{proj}",
            reply_markup=triage_keyboard(t.id),
            parse_mode="HTML",
        )
    if len(inbox) > WEEKLY_TRIAGE_CAP:
        await message.reply_text(f"…и ещё {len(inbox) - WEEKLY_TRIAGE_CAP}.")


@restricted
async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    text = (message.text or "").strip()
    if not text:
        return

    # Keyboard presses are commands, not tasks — intercept before capture.
    if text == BTN_TODAY:
        await cmd_today(update, context)
        return
    if text == BTN_BACKLOG:
        await cmd_backlog(update, context)
        return
    if text == BTN_HELP:
        await cmd_help(update, context)
        return

    # If we asked for a project name for an existing task, consume this reply as that.
    pending_id = context.user_data.pop(_PENDING_PROJECT, None) if context.user_data else None
    if pending_id is not None:
        task = store.update_task(pending_id, project=text)
        if task:
            await message.reply_text(f"Проект задачи #{task.id}: {task.project}")
        return

    is_forward = message.forward_origin is not None

    # Forwards are always new captures. Plain text may be an edit instruction.
    if not is_forward:
        edit = await parse_edit(text, today=local_today())
        if edit["action"] is not None:
            await _apply_edit(update, context, edit)
            return

    parsed = await parse_text(text, today=local_today())
    task = store.create_task(
        title=parsed["title"],
        raw_text=text,
        iso_week=parsed["iso_week"],
        project=parsed["project"],
        priority=parsed["priority"],
        due_date=parsed["due_date"],
        source="forward" if is_forward else "tg",
    )
    _remember(context, task.id)
    await _send_confirmation(update, task)


@restricted
async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    parts = (query.data or "").split("|")
    action = parts[0]
    # Any button press makes that task the referent for a following 'эту задачу'.
    if len(parts) >= 2 and parts[1].isdigit():
        _remember(context, int(parts[1]))

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
