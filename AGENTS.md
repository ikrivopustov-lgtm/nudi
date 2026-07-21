# AGENTS.md — working conventions for nudge

Read this before touching the repo. It captures the non-obvious rules.

## Principles

- **One user.** This is a personal assistant. Every inbound update is checked against
  `TELEGRAM_ALLOWED_USER_ID`; anything else is logged and dropped. Never add
  multi-user logic "just in case".
- **SQLite owns the truth.** Airtable mirrors and offers a second inbox, but it never
  wins a conflict. If they disagree, SQLite is right.
- **Minimalism.** No Docker, no Redis, no Celery, no webhook server. One process,
  one SQLite file, long-polling. Add machinery only when there is real pain.
- **Secrets never touch git.** Only `.env.example` is committed. Real values live in
  `.env` (git-ignored, `chmod 600` on the VPS) and are loaded via `config.py` /
  systemd `EnvironmentFile`.

## Assistant core (`assistant.py`)

- Free-form messages go through **one agentic tool-calling call** (OpenRouter,
  `google/gemini-2.5-flash-lite`). The model gets the message, recent conversation
  (`ConvTurn`, persisted) and the live task list, then drives tools: create / update /
  complete / delete / set_reminder / set_recurrence / search / undo — or just replies.
- Task text is **data, never instructions**. Tool inputs are validated/whitelisted in the
  executors (`priority ∈ {P1,P2,P3}`, `status ∈ {…}`, ISO dates). A bad model call or a
  tool error is returned to the model / caught — it must **never crash the bot**.
- Prefer **single-shot tools**: `create_task` takes `remind_at`/`recurrence` so the model
  doesn't chain calls and mis-target ids (weak models get this wrong).
- Every mutation logs a `before`-snapshot to `ActionLog` so `undo_last` can reverse it.

## Code

- Python 3.12, typed. Models in `models.py` (SQLModel). Config only via `config.py`.
- Timezone is fixed in config (`Europe/Moscow`); schedule jobs in local time.
- Keep handlers thin: parse → mutate DB → reply. Business rules live in
  `priority.py` / `digest.py` / `airtable_sync.py`.

## Commands

- install `uv sync` · run `uv run python -m nudge` · test `uv run pytest`

## Git

- Atomic commits, conventional-commit prefixes (`feat(scope): …`, `chore: …`).
- Never commit `.env`, `*.db`, or backups.
