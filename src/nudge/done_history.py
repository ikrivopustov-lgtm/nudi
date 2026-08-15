"""Completed-task history by calendar week (Mon–Sun, owner timezone).

Done tasks are never purged from SQLite — this module only *reads* them.
Week paging edits one Telegram message via inline ← / → buttons.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from . import store
from .models import priority_dot

_WEEKDAYS_RU = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")
_MAX_LINES = 40


def week_monday(d: date) -> date:
    """Monday of the ISO week that contains `d`."""
    return d - timedelta(days=d.weekday())


def week_sunday(monday: date) -> date:
    return monday + timedelta(days=6)


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _local_bounds_utc(monday: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    """[local Mon 00:00, next Mon 00:00) as naive UTC for completed_at queries."""
    start_local = datetime(monday.year, monday.month, monday.day, tzinfo=tz)
    end_local = start_local + timedelta(days=7)
    since = start_local.astimezone(timezone.utc).replace(tzinfo=None)
    until = end_local.astimezone(timezone.utc).replace(tzinfo=None)
    return since, until


def format_week_range(monday: date) -> str:
    sun = week_sunday(monday)
    return (
        f"{_WEEKDAYS_RU[0]} {monday.strftime('%d.%m')}"
        f" – {_WEEKDAYS_RU[6]} {sun.strftime('%d.%m')}"
    )


def render_done_week(monday: date, *, today: date, tz: ZoneInfo) -> str:
    """HTML body for one calendar week of completions (kept forever in DB)."""
    monday = week_monday(monday)
    since, until = _local_bounds_utc(monday, tz)
    found = store.list_completed_between(since, until)
    label = format_week_range(monday)
    current = week_monday(today)
    tag = " · эта неделя" if monday == current else ""

    if not found:
        return f"✔️ <b>Сделано</b> · {label}{tag}\n\nЗакрытых задач нет."

    lines = [f"✔️ <b>Сделано</b> · {label}{tag} ({len(found)}):"]
    for t in found[:_MAX_LINES]:
        if t.completed_at:
            # Show local calendar day
            when = (
                t.completed_at.replace(tzinfo=timezone.utc)
                .astimezone(tz)
                .strftime("%d.%m")
            )
        else:
            when = "?"
        proj = f" · {_esc(t.project)}" if t.project else ""
        lines.append(f"• {when} — {priority_dot(t.priority)} {_esc(t.title)}{proj}")
    if len(found) > _MAX_LINES:
        lines.append(f"…и ещё {len(found) - _MAX_LINES}.")
    lines.append("\n<i>История хранится всегда — листай недели кнопками.</i>")
    return "\n".join(lines)


def done_week_keyboard(monday: date, *, today: date) -> InlineKeyboardMarkup:
    monday = week_monday(monday)
    current = week_monday(today)
    prev_m = monday - timedelta(days=7)
    next_m = monday + timedelta(days=7)
    row: list[InlineKeyboardButton] = [
        InlineKeyboardButton(
            "← пред. неделя",
            callback_data=f"done_week|{prev_m.isoformat()}",
        )
    ]
    if next_m <= current:
        row.append(
            InlineKeyboardButton(
                "след. неделя →",
                callback_data=f"done_week|{next_m.isoformat()}",
            )
        )
    return InlineKeyboardMarkup([row])
