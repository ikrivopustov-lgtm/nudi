# Data model & priority rules

SQLite (WAL) is the single source of truth. Airtable mirrors it and offers a second
inbox, but never wins a conflict.

## `Task`

| field           | type       | notes                                             |
| --------------- | ---------- | ------------------------------------------------- |
| `id`            | int PK     | autoincrement                                     |
| `title`         | str        | short parsed title                                |
| `raw_text`      | str        | original captured text (kept verbatim)            |
| `project`       | str \| null | parsed project, nullable                          |
| `iso_week`      | str        | ISO week the task belongs to, e.g. `2026-W30`     |
| `priority`      | str        | **P1 \| P2 \| P3** (default P2)                    |
| `status`        | str        | **inbox \| today \| done \| someday** (default inbox) |
| `due_date`      | date \| null | hard deadline                                     |
| `scheduled_for` | date \| null | day the task is meant to land in "today"          |
| `source`        | str        | **tg \| forward \| airtable**                     |
| `airtable_id`   | str \| null | record id for mirroring                           |
| `created_at`    | datetime   | UTC                                               |
| `updated_at`    | datetime   | UTC, bumped on every mutation                     |

Whitelists (`priority`, `status`, `source`) are defined in `models.py` and are the same
values used to validate LLM output — anything outside them is rejected and replaced with a
safe default (`priority=P2`, `status=inbox`).

## `Setting`

Simple key/value store (`key` PK, `value`) for runtime-tunable settings such as ping times
or a timezone override, if we ever want to change them without a redeploy.

## Priority rule — "today ≤ 5"

The morning digest selects at most **5** tasks:

1. all tasks with `status = today`, **plus**
2. all overdue tasks (`due_date < today` and not `done`), **plus**
3. top-up by priority **P1 → P2 → P3** until we reach 5.

Ordering within the set: overdue first, then by priority, then by `due_date` (nulls last),
then by `created_at`. The list is hard-capped at 5 — anything beyond stays hidden until the
list frees up. That cap *is* the product.

## Storage

- WAL journal mode (`PRAGMA journal_mode=WAL`), `synchronous=NORMAL`, `foreign_keys=ON`.
- DB file at `DATABASE_PATH` (default `data/nudge.db`), git-ignored along with its
  `-wal` / `-shm` sidecars.
- Daily file-copy backup via `scripts/backup_db.sh`, rotated, kept outside the repo.
