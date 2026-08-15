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
| `status`        | str        | **inbox \| today \| done** (default inbox). Legacy `someday` migrates to inbox. |
| `due_date`      | date \| null | hard deadline                                     |
| `scheduled_for` | date \| null | day the task is meant to land in "today"          |
| `remind_at`     | datetime \| null | one-off reminder ping, stored naive-UTC       |
| `recurrence`    | str \| null | `daily` \| `weekly:mon,thu` \| `monthly:15`        |
| `completed_at`  | datetime \| null | set when status → done; **never purged** — history is permanent |
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

## `ConvTurn` / `ActionLog`

- **`ConvTurn`** — rolling conversation memory (`role`, `content`, `created_at`), pruned to
  the last ~24 turns, fed to the assistant so it keeps context across messages and restarts.
- **`ActionLog`** — reversible action journal (`kind`, `task_id`, `before` JSON snapshot,
  `summary`, `undone`) powering `отмени`/undo.

New Task columns added after the first release (`remind_at`, `recurrence`, `completed_at`)
are applied to a pre-existing SQLite table by `db._migrate` (idempotent `ALTER TABLE`).

## Priority rule — "today ≤ 5"

The morning digest / `/today` selects at most **5** commitments:

1. all tasks with `status = today`, **plus**
2. all with `scheduled_for = today`, **plus**
3. all overdue tasks (`due_date < today` and not `done`).

There is **no silent top-up** from undated inbox. New captures stay in backlog until
the user says «на сегодня», presses triage «☀️ Сегодня», or the scheduled day arrives.

On read, `materialize_today` promotes inbox items that are already in the selection
(`scheduled_for = today` or overdue) to `status = today`, so they leave the backlog
(one place at a time).

Tasks with `scheduled_for > today` stay in the backlog until that day.

## Storage

- WAL journal mode (`PRAGMA journal_mode=WAL`), `synchronous=NORMAL`, `foreign_keys=ON`.
- DB file at `DATABASE_PATH` (default `data/nudge.db`), git-ignored along with its
  `-wal` / `-shm` sidecars.
- Daily file-copy backup via `scripts/backup_db.sh`, rotated, kept outside the repo.
