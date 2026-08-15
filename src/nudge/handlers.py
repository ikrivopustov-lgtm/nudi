"""Telegram handlers. Every entry point is guarded by the allowlist.

Primary UX = free-form chat (TG Tasks style). Reply keyboard is only for
quick views (/today, /done). No per-task inline «✔️» buttons — those feel slow.
"""

from __future__ import annotations

import asyncio
import functools
import logging
from collections.abc import Awaitable, Callable
from datetime import date, datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Message, ReplyKeyboardMarkup, Update
from telegram.constants import MessageEntityType
from telegram.ext import ContextTypes

from . import assistant, store
from .archive.karakeep import (
    KarakeepError,
    format_archive_ack,
    parse_tag_list,
    replace_tags,
    wait_for_tags,
)
from .archive.pipeline import store_forward_payload
from .archive.route import (
    build_telegram_post_url,
    decide_archive,
    extract_urls,
)
from .config import get_settings
from .done_history import done_week_keyboard, render_done_week, week_monday
from .fastpath import looks_like_history, try_fast_path, try_quote_action

log = logging.getLogger(__name__)

Handler = Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[None]]

_EMPTY_FORWARD_NOTE = "Пересланное сообщение"
_ARCHIVE_ACKS = "archive_acks"  # status message_id → bookmark_id


def message_payload(message: Message) -> tuple[str, list[str]]:
    """Text/caption + URLs (plain + entity links). Media-only forwards get a stub note."""
    body = (message.text or message.caption or "").strip()
    urls: list[str] = []
    seen: set[str] = set()

    def _add(url: str) -> None:
        u = (url or "").strip().rstrip(").,;]")
        if u and u not in seen:
            seen.add(u)
            urls.append(u)

    for u in extract_urls(body):
        _add(u)

    if message.text and message.entities:
        for ent in message.entities:
            if ent.type == MessageEntityType.URL:
                _add(message.parse_entity(ent))
            elif ent.type == MessageEntityType.TEXT_LINK and ent.url:
                _add(ent.url)
    if message.caption and message.caption_entities:
        for ent in message.caption_entities:
            if ent.type == MessageEntityType.URL:
                _add(message.parse_caption_entity(ent))
            elif ent.type == MessageEntityType.TEXT_LINK and ent.url:
                _add(ent.url)

    if not body and urls:
        body = urls[0]
    return body, urls


def is_forwarded(message: Message) -> bool:
    return message.forward_origin is not None or bool(
        getattr(message, "is_automatic_forward", False)
    )


def forward_telegram_post_url(message: Message) -> str | None:
    """If this is a forward of a channel/supergroup post — link to that post."""
    origin = message.forward_origin
    if origin is None:
        return None
    chat = getattr(origin, "chat", None)
    msg_id = getattr(origin, "message_id", None)
    if chat is None or msg_id is None:
        return None
    return build_telegram_post_url(
        message_id=int(msg_id),
        username=getattr(chat, "username", None),
        chat_id=getattr(chat, "id", None),
    )


# Persistent keyboard — views + archive capture.
BTN_TODAY = "☀️ Сегодня"
BTN_BACKLOG = "📋 Бэклог"
BTN_DONE = "✔️ Сделано"
BTN_SAVE = "📎 Сохранить"
BTN_HELP = "❓ Помощь"

MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [[BTN_TODAY, BTN_BACKLOG], [BTN_DONE, BTN_SAVE], [BTN_HELP]],
    resize_keyboard=True,
    is_persistent=True,
)

_SAVE_FLAG = "archive_save_next"

HELP_TEXT = (
    "<b>Nudi</b> — пиши как другу. Можно без команд: просто текст = задача.\n\n"
    "<b>Завести задачу</b> — любой из вариантов:\n"
    "• просто: <code>оплатить налоги</code>\n"
    "• <code>поставь задачу: созвон с Павлом</code>\n"
    "• <code>задача — купить молоко</code> · <code>todo: ревью PR</code>\n"
    "• <code>добавь / заведи / закинь / новая задача …</code>\n"
    "• <code>нужно / надо / не забыть …</code>\n"
    "• со сроком: <code>… до пятницы</code> · <code>… к 1 августа</code>\n"
    "• срочно: <code>… красным</code> / <code>срочно</code> → 🔴\n"
    "• проект: <code>проект ИИ-платформа: починить женю</code>\n"
    "• повтор: <code>созвон каждый понедельник</code>\n"
    "• сразу + пинг: <code>напомни про звонок сегодня в 15:00</code>\n\n"
    "<b>Архив (Karakeep)</b>\n"
    "• кнопка <b>📎 Сохранить</b> — следующее сообщение в архив\n"
    "• пересланный пост канала — в архив ссылкой на пост в Telegram (не на ссылки внутри)\n"
    "• ссылка / рилс / тикток — в архив (видео: транскрипт через Apify, если настроен)\n"
    "• после сохранения бот покажет теги; ответь на это сообщение списком через запятую — заменит теги\n"
    "• обычный текст без ссылки — задача, как раньше\n\n"
    "<b>Закрыть</b> (сразу, без кнопок)\n"
    "• <code>сделал налоги</code> · <code>налоги сделано</code> · <code>налоги ✓</code>\n"
    "• <code>готово</code> · <code>выполнил</code> · <code>закрыл отчёт</code>\n"
    "• или <b>Цитировать</b> строку из /today → <code>сделано</code>\n\n"
    "<b>Перенести на дату</b> (всплывёт в этот день)\n"
    "• <code>на завтра</code> · <code>давай на завтра</code> · <code>перенеси на завтра</code>\n"
    "• <code>на послезавтра</code> · <code>на пятницу</code> · <code>на понедельник</code>\n"
    "• <code>на следующую неделю</code> · <code>на след неделю</code> · <code>на след.нед</code>\n"
    "• <code>через неделю</code> · <code>на следующей неделе</code>\n"
    "• <code>на конец недели</code> · <code>к выходным</code>\n"
    "• <code>на 1 августа</code> · <code>на 01.08</code>\n"
    "• можно с названием: <code>налоги давай на след неделю</code>\n\n"
    "<b>Отложить в бэклог</b> (без даты → инбокс)\n"
    "• <code>отложи</code> · <code>в бэклог</code> · <code>в инбокс</code>\n"
    "• <code>убери из сегодня</code> · <code>пока отложи</code> · <code>потом</code>\n"
    "• или <b>Цитировать</b> строку из /today → <code>в бэклог</code>\n"
    "• с датой это уже перенос: <code>отложи на пятницу</code>\n\n"
    "<b>Ещё</b>\n"
    "• напоминание: <code>напомни завтра в 10</code>\n"
    "• повтор: <code>каждый день</code> · <code>по будням</code>\n"
    "• история: <code>что сделал за неделю?</code> · /done (листы по неделям ←→)\n"
    "• закрытые задачи хранятся всегда — ничего не чистится\n"
    "• план: /today · инбокс: /backlog · <code>отмени</code>\n\n"
    "Инбокс = бэклог. «Отложи» → инбокс. «На пятницу» → дата всплытия.\n"
    "После смены кнопок — один раз /start."
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


def _done_view(today: date | None = None) -> tuple[str, InlineKeyboardMarkup]:
    settings = get_settings()
    today = today or local_today()
    monday = week_monday(today)
    text = render_done_week(monday, today=today, tz=settings.tz)
    kb = done_week_keyboard(monday, today=today)
    return text, kb


@restricted
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    name = get_settings().owner_name
    await update.effective_message.reply_text(
        f"Nudi на связи, {name}. Пиши задачи и «сделал …» как думаешь.\n"
        "Кнопки: сегодня, бэклог, сделано, <b>сохранить</b> (архив), справка.\n"
        "<i>Если кнопок не видно — нажми /start ещё раз.</i>",
        parse_mode="HTML",
        reply_markup=MAIN_KEYBOARD,
    )


def _remember_archive_ack(
    context: ContextTypes.DEFAULT_TYPE, status_message_id: int, bookmark_id: str
) -> None:
    acks: dict[int, str] = context.user_data.setdefault(_ARCHIVE_ACKS, {})
    acks[status_message_id] = bookmark_id
    # Keep map small (one user) — drop oldest-ish extras.
    if len(acks) > 40:
        for mid in list(acks.keys())[:-30]:
            acks.pop(mid, None)


async def _run_archive(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    """Save to Karakeep; never crash the bot."""
    message = update.effective_message
    await context.bot.send_chat_action(chat_id=message.chat_id, action="typing")
    status = await message.reply_text("📎 сохраняю…")
    # Forward of a TG post → bookmark the post itself, not URLs inside it.
    prefer = forward_telegram_post_url(message) if message else None
    urls = [] if prefer else extract_urls(text)
    try:
        result = await asyncio.to_thread(
            store_forward_payload, text, urls=urls, prefer_url=prefer
        )
    except Exception:
        log.exception("archive pipeline crashed")
        try:
            await status.edit_text("не смог сохранить в архив (ошибка). Попробуй ещё раз.")
        except Exception:
            await message.reply_text("не смог сохранить в архив (ошибка). Попробуй ещё раз.")
        return

    if not result.ok:
        err = result.error or ""
        fail = f"{result.message}" + (f" ({err[:120]})" if err else "")
        try:
            await status.edit_text(fail)
        except Exception:
            await message.reply_text("не смог сохранить в архив.")
        return

    ack = result.message
    bookmark_id = result.bookmark_id
    if bookmark_id:
        try:
            await status.edit_text("📎 сохранил, жду теги…")
            tags = await asyncio.to_thread(wait_for_tags, bookmark_id)
            ack = format_archive_ack(result.title or result.message, tags)
        except Exception:
            log.exception("wait_for_tags failed bookmark_id=%s", bookmark_id)
            ack = format_archive_ack(result.title or "карточка", [])
        _remember_archive_ack(context, status.message_id, bookmark_id)

    try:
        await status.edit_text(ack)
    except Exception:
        await message.reply_text(ack)


async def _edit_archive_tags(
    update: Update, context: ContextTypes.DEFAULT_TYPE, bookmark_id: str, raw: str
) -> None:
    message = update.effective_message
    tags = parse_tag_list(raw)
    await context.bot.send_chat_action(chat_id=message.chat_id, action="typing")
    try:
        final = await asyncio.to_thread(replace_tags, bookmark_id, tags)
    except KarakeepError as e:
        log.warning("replace_tags failed: %s", e)
        await message.reply_text(f"не смог обновить теги ({str(e)[:120]})")
        return
    except Exception:
        log.exception("replace_tags crashed")
        await message.reply_text("не смог обновить теги (ошибка).")
        return

    if final:
        await message.reply_text("теги обновлены: " + ", ".join(final))
    else:
        await message.reply_text("теги сняты — карточка без тегов.")

    # Keep the same reply-target working for another edit.
    reply = message.reply_to_message
    if reply is not None:
        _remember_archive_ack(context, reply.message_id, bookmark_id)


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
    text = render_digest(tasks, today)
    inbox_n = len(store.list_by_status("inbox"))
    if inbox_n:
        text += f"\n\n<i>в бэклоге ещё {inbox_n}</i>"
    await update.effective_message.reply_text(text, parse_mode="HTML")


@restricted
async def cmd_done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text, kb = _done_view()
    await update.effective_message.reply_text(text, parse_mode="HTML", reply_markup=kb)


@restricted
async def cmd_backlog(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from .digest import (
        WEEKLY_TRIAGE_CAP,
        split_inbox,
        task_line_html,
        triage_keyboard,
    )

    message = update.effective_message
    inbox = store.list_by_status("inbox")

    if not inbox:
        await message.reply_text("📋 Бэклог пуст. Чисто.")
        return

    dated, undated = split_inbox(inbox)
    # Prefer showing undated for triage first (need decisions), then dated queue.
    # Cap total messages; undated first.
    budget = WEEKLY_TRIAGE_CAP
    show_undated = undated[:budget]
    budget -= len(show_undated)
    show_dated = dated[:budget] if budget > 0 else []

    header = (
        f"📋 <b>Бэклог</b>: {len(inbox)}"
        f" · без даты {len(undated)} · на дату {len(dated)}"
    )
    await message.reply_text(header, parse_mode="HTML")

    if show_undated:
        await message.reply_text(
            f"📥 <b>Без даты</b> — разложить:", parse_mode="HTML"
        )
        for t in show_undated:
            await message.reply_text(
                task_line_html(t, show_schedule=False),
                reply_markup=triage_keyboard(t.id),
                parse_mode="HTML",
            )

    if show_dated:
        await message.reply_text(
            f"📅 <b>На дату</b> — ждут своего дня:", parse_mode="HTML"
        )
        for t in show_dated:
            await message.reply_text(
                task_line_html(t, show_schedule=True),
                reply_markup=triage_keyboard(t.id),
                parse_mode="HTML",
            )

    hidden = len(inbox) - len(show_undated) - len(show_dated)
    if hidden > 0:
        await message.reply_text(f"…и ещё {hidden}.")


@restricted
async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Text, caption, or media (forwards/photos often have no `.text`)."""
    message = update.effective_message
    text, entity_urls = message_payload(message)
    forwarded = is_forwarded(message)

    # Reply to archive ACK → replace tags on that Karakeep card.
    # Must run BEFORE task-quote handling so Karakeep is never mixed with tasks.
    reply = message.reply_to_message
    if reply is not None and text:
        acks: dict[int, str] = context.user_data.get(_ARCHIVE_ACKS) or {}
        bookmark_id = acks.get(reply.message_id)
        if bookmark_id:
            await _edit_archive_tags(update, context, bookmark_id, text)
            return

        # Telegram «Цитировать»: partial quote of a bot message + bare command.
        quote = getattr(message, "quote", None)
        quote_text = (getattr(quote, "text", None) or "").strip() if quote else ""
        if quote_text:
            settings = get_settings()
            today = local_today()
            quoted = try_quote_action(
                text, quote_text, today=today, tz=settings.tz
            )
            if quoted is not None:
                store.add_turn("user", f"[quote] {quote_text}\n{text}")
                store.add_turn("assistant", quoted)
                await message.reply_text(quoted)
                return

    if text == BTN_TODAY:
        await cmd_today(update, context)
        return
    if text == BTN_BACKLOG:
        await cmd_backlog(update, context)
        return
    if text == BTN_DONE:
        await cmd_done(update, context)
        return
    if text == BTN_HELP:
        await cmd_help(update, context)
        return
    if text == BTN_SAVE:
        context.user_data[_SAVE_FLAG] = True
        await message.reply_text(
            "📎 Режим сохранения: следующее сообщение (текст, ссылка, фото/видео "
            "или пересылка) уйдёт в Karakeep, не в задачи."
        )
        return

    save_mode = bool(context.user_data.pop(_SAVE_FLAG, False))

    # Empty body: only meaningful for forward / Save / media with entity URL.
    if not text:
        if forwarded or save_mode:
            text = _EMPTY_FORWARD_NOTE
        elif entity_urls:
            text = entity_urls[0]
        else:
            return

    # Ensure entity-only links still reach the archive pipeline.
    if entity_urls and not any(u in text for u in entity_urls):
        text = f"{text}\n" + "\n".join(entity_urls)

    decision = decide_archive(text=text, is_forward=forwarded, save_mode=save_mode)
    log.info(
        "inbound msg_id=%s forward=%s save=%s decision=%s urls=%s",
        message.message_id,
        forwarded,
        save_mode,
        decision.reason,
        extract_urls(text)[:3],
    )

    if decision.kind == "archive":
        await _run_archive(update, context, text)
        return

    if decision.kind == "ask":
        context.user_data["archive_pending_text"] = text
        kb = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("📎 В архив", callback_data="arch|yes"),
                    InlineKeyboardButton("☑️ В задачи", callback_data="arch|no"),
                ]
            ]
        )
        await message.reply_text("Куда положить?", reply_markup=kb)
        return

    settings = get_settings()
    today = local_today()

    # Instant path (TG Tasks style) — no OpenRouter round-trip.
    fast = try_fast_path(text, today=today, tz=settings.tz)
    if fast is not None:
        store.add_turn("user", text)
        store.add_turn("assistant", fast)
        if looks_like_history(text):
            _, kb = _done_view(today)
            await message.reply_text(fast, parse_mode="HTML", reply_markup=kb)
        else:
            await message.reply_text(fast)
        return

    await context.bot.send_chat_action(chat_id=message.chat_id, action="typing")
    reply = await assistant.handle_message(
        text,
        today=today,
        tz=settings.tz,
        schedule_reminder=_make_reminder_scheduler(context),
    )
    await message.reply_text(reply)


def _make_reminder_scheduler(context: ContextTypes.DEFAULT_TYPE):
    from .digest import reminder_job

    def schedule(task_id: int, when_utc) -> None:
        jq = context.job_queue
        if jq is None:
            return
        for job in jq.get_jobs_by_name(f"reminder:{task_id}"):
            job.schedule_removal()
        jq.run_once(reminder_job, when=when_utc, data=task_id, name=f"reminder:{task_id}")

    return schedule


@restricted
async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    parts = (query.data or "").split("|")
    action = parts[0]

    if action == "arch" and len(parts) == 2:
        pending = context.user_data.pop("archive_pending_text", "") or ""
        if parts[1] == "yes":
            await query.edit_message_text("📎 в архив…")
            # Re-enter archive via a synthetic path
            urls = extract_urls(pending)
            try:
                result = await asyncio.to_thread(store_forward_payload, pending, urls=urls)
                await query.message.reply_text(
                    result.message if result.ok else f"{result.message}"
                )
            except Exception:
                log.exception("archive from callback failed")
                await query.message.reply_text("не смог сохранить в архив.")
            return
        # arch|no → treat as task text through assistant
        await query.edit_message_text("☑️ в задачи…")
        settings = get_settings()
        today = local_today()
        reply = await assistant.handle_message(
            pending,
            today=today,
            tz=settings.tz,
            schedule_reminder=_make_reminder_scheduler(context),
        )
        await query.message.reply_text(reply)
        return

    if action == "wk_today" and len(parts) == 2:
        store.update_task(int(parts[1]), status="today", scheduled_for=local_today())
        await query.edit_message_text("☀️ → сегодня")
        return

    if action == "wk_someday" and len(parts) == 2:
        # Legacy button: someday removed — park in backlog (inbox).
        store.update_task(int(parts[1]), status="inbox", scheduled_for=None)
        await query.edit_message_text("📋 → бэклог")
        return

    if action == "wk_del" and len(parts) == 2:
        store.delete_task(int(parts[1]))
        await query.edit_message_text("🗑 удалено")
        return

    if action == "done_week" and len(parts) == 2:
        try:
            monday = week_monday(date.fromisoformat(parts[1]))
        except ValueError:
            await query.edit_message_text("Не понял неделю.")
            return
        today = local_today()
        # Don't jump into the future past the current week.
        current = week_monday(today)
        if monday > current:
            monday = current
        settings = get_settings()
        text = render_done_week(monday, today=today, tz=settings.tz)
        kb = done_week_keyboard(monday, today=today)
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=kb)
        return
