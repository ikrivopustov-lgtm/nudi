# nudge

Personal Telegram task assistant. One inbox (text to a bot), a short list (rule of 5),
external nudges as the trigger. SQLite is the single source of truth; Airtable is a second
door and a mirror; OpenRouter parses and prioritizes. Runs 24/7 on a VPS via systemd.

## What it does

- **Capture** — any text (or a forwarded message) in the bot becomes a task. An LLM parses
  it into `title / project / priority / due_date / iso_week`; you confirm/adjust with
  inline buttons.
- **Rule of 5** — the morning digest shows at most 5 things: `today` + overdue + top
  priority, sliced to 5.
- **Nudges** — morning digest, a Sunday weekly triage ritual, deadline pings — all via the
  bot's `JobQueue` (APScheduler). No Celery, no Redis.
- **Second door** — Airtable inbox view is polled every 10 min; task changes are mirrored
  back out.

## Stack

Python 3.12 · `python-telegram-bot` v21 (long-polling + JobQueue) · SQLite (WAL) via
SQLModel · OpenRouter over `httpx` · `pyairtable` · `pydantic-settings` · `uv`.

No Docker. Single process + one SQLite file. One user (allowlist by Telegram id).

## Run

```bash
uv sync                     # install
cp .env.example .env        # then fill in real values
uv run python -m nudge      # start the bot + scheduler
uv run pytest               # tests
```

## Layout

```
src/nudge/
  __main__.py     entry point: start bot + JobQueue
  config.py       pydantic-settings from .env
  db.py           engine, WAL, init, sessions
  models.py       SQLModel: Task, Setting
  llm.py          OpenRouter: parse_text / parse_edit → strict JSON
  handlers.py     text, forwards, edits, inline buttons
  priority.py     "today ≤ 5" selection + ordering
  digest.py       morning digest + weekly ritual
  airtable_sync.py  poll-in + mirror-out
scripts/          systemd unit, deploy.sh, backup_db.sh
docs/             PROJECT_KICKOFF.md, DATA_MODEL.md
```

## Deploy (VPS)

The app runs under systemd (`scripts/nudge.service`). See `scripts/deploy.sh` for the
rsync + restart flow and `scripts/backup_db.sh` for the daily SQLite backup.

Secrets live only in `.env` on the server (`chmod 600`), never in git.
