"""Airtable as a second inbox and a mirror. SQLite stays the source of truth.

Airtable table is expected to have these columns (created once, by hand):
    Title | Owner | Project | Week | Priority | Status | Due

Sync is a single periodic job:
  * poll-in  — new rows in the inbox view become tasks (source=airtable),
               de-duplicated by the Airtable record id we store on the task.
  * mirror-out — tasks created/changed since the last sync are upserted back.

Everything no-ops gracefully when Airtable isn't configured, so the bot runs
fine without it. pyairtable is synchronous; calls run in a worker thread.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timezone

from telegram.ext import ContextTypes

from . import store
from .config import get_settings
from .llm import iso_week_of
from .models import PRIORITIES, STATUSES

log = logging.getLogger(__name__)

# Airtable field names.
F_TITLE = "Title"
F_OWNER = "Owner"
F_PROJECT = "Project"
F_WEEK = "Week"
F_PRIORITY = "Priority"
F_STATUS = "Status"
F_DUE = "Due"

_LAST_SYNC_KEY = "airtable_last_sync"


def is_configured() -> bool:
    s = get_settings()
    return bool(s.airtable_token and s.airtable_base_id and s.airtable_table)


def _table():
    from pyairtable import Api  # imported lazily so the dep is optional at runtime

    s = get_settings()
    return Api(s.airtable_token).table(s.airtable_base_id, s.airtable_table)


# --- pure mappers (unit-tested, no network) --------------------------------

def task_to_fields(task, owner: str) -> dict:
    return {
        F_TITLE: task.title,
        F_OWNER: owner,
        F_PROJECT: task.project or "",
        F_WEEK: task.iso_week,
        F_PRIORITY: task.priority,
        F_STATUS: task.status,
        F_DUE: task.due_date.isoformat() if task.due_date else None,
    }


def record_to_task_kwargs(record: dict, today: date) -> dict:
    fields = record.get("fields", {})
    title = str(fields.get(F_TITLE) or fields.get("Name") or "(из Airtable)").strip()

    project = fields.get(F_PROJECT) or None
    project = str(project).strip() or None if project else None

    priority = str(fields.get(F_PRIORITY) or "").upper().strip()
    if priority not in PRIORITIES:
        priority = "P2"

    status = str(fields.get(F_STATUS) or "").lower().strip()
    if status not in STATUSES:
        status = "inbox"

    due = None
    raw_due = fields.get(F_DUE)
    if raw_due:
        try:
            due = date.fromisoformat(str(raw_due)[:10])
        except ValueError:
            due = None

    return {
        "title": title,
        "raw_text": title,
        "iso_week": iso_week_of(due or today),
        "project": project,
        "priority": priority,
        "status": status,
        "due_date": due,
        "source": "airtable",
        "airtable_id": record["id"],
    }


# --- sync steps (network; run in a thread) ---------------------------------

def _poll_in_sync(today: date) -> list[str]:
    table = _table()
    view = get_settings().airtable_inbox_view
    created: list[str] = []
    for record in table.all(view=view):
        if store.get_by_airtable_id(record["id"]) is not None:
            continue
        kwargs = record_to_task_kwargs(record, today)
        task = store.create_task(**kwargs)
        created.append(task.title)
    return created


def _mirror_out_sync() -> int:
    owner = get_settings().owner_name
    last_raw = store.get_setting(_LAST_SYNC_KEY)
    since = datetime.fromisoformat(last_raw) if last_raw else None
    started = datetime.now(timezone.utc)

    table = _table()
    pushed = 0
    for task in store.tasks_to_mirror(since):
        fields = task_to_fields(task, owner)
        if task.airtable_id:
            table.update(task.airtable_id, fields)
        else:
            rec = table.create(fields)
            store.set_airtable_id(task.id, rec["id"])
        pushed += 1

    store.set_setting(_LAST_SYNC_KEY, started.isoformat())
    return pushed


# --- the job ---------------------------------------------------------------

async def airtable_sync_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_configured():
        return
    settings = get_settings()
    today = datetime.now(settings.tz).date()
    try:
        created = await asyncio.to_thread(_poll_in_sync, today)
        pushed = await asyncio.to_thread(_mirror_out_sync)
    except Exception as exc:  # noqa: BLE001 — a flaky Airtable must not kill the loop
        log.warning("airtable sync failed (%s): %s", type(exc).__name__, exc)
        return

    if created:
        preview = "\n".join(f"• {t}" for t in created[:10])
        await context.bot.send_message(
            chat_id=settings.telegram_allowed_user_id,
            text=f"📥 Из Airtable добавлено ({len(created)}):\n{preview}",
        )
    log.info("airtable sync: %d imported, %d mirrored", len(created), pushed)
