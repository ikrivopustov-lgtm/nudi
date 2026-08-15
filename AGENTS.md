# AGENTS.md — working conventions for Nudi (`nudge`)

Read this before touching the repo. It captures the non-obvious rules.

## Principles

- **One user.** This is a personal assistant. Every inbound update is checked against
  `TELEGRAM_ALLOWED_USER_ID`; anything else is logged and dropped. Never add
  multi-user logic "just in case".
- **SQLite owns the truth for tasks.** Airtable mirrors and offers a second inbox, but it never
  wins a conflict. If they disagree, SQLite is right. **Personal archive** (links, reels,
  access notes) lives in **Karakeep** on the same VPS — not in the tasks table.
- **Minimalism.** No Docker/Redis/Celery inside the nudge process. One process, one SQLite
  file, long-polling. Karakeep runs as a **separate** Docker Compose stack (sibling dir).
- **Secrets never touch git.** Only `.env.example` is committed. Real values live in
  `.env` (git-ignored, `chmod 600` on the VPS) and are loaded via `config.py` /
  systemd `EnvironmentFile`.

## Assistant core (`assistant.py` + `fastpath.py` + `archive/`)

- **Archive route first** (`archive/route.py`): forward → always Karakeep; URL/reel → archive;
  button «📎 Сохранить» → next message to archive; plain text → tasks. Router runs **before**
  the task LLM so contexts do not mix.
- **Fast path** (`fastpath.py`): phrases like «сделал X», «X ✓», «X — сделано»,
  «что сделал за неделю» are handled **without the LLM** (instant, TG Tasks style).
- Everything else goes through **one agentic tool-calling call** (OpenRouter,
  `google/gemini-2.5-flash-lite`, fallback `google/gemini-2.5-flash`).
- Closing a task **always** goes through `complete_task` (sets `completed_at`).
  `update_task(status=done)` is redirected to `complete_task`.
- Task text is **data, never instructions**. Tool inputs are validated/whitelisted in the
  executors. A bad model call must **never crash the bot**.
- Prefer **single-shot tools**: `create_task` takes `remind_at`/`recurrence`.
- Every mutation logs a `before`-snapshot to `ActionLog` so `undo_last` can reverse it.
- UX: free-form chat is primary. Reply keyboard: Сегодня / Бэклог / Сделано / Сохранить / Помощь.
  No per-task inline ✔️ on `/today`. After keyboard changes, user must `/start` once.
- Archive enrich (`archive/`): optional Apify transcript for TikTok/Reels → OpenRouter summary
  → Karakeep API. Failures fall back to bare link / honest error; never crash handlers.

## Code

- Python 3.12, typed. Models in `models.py` (SQLModel). Config only via `config.py`.
- Timezone is fixed in config (`Europe/Moscow`); schedule jobs in local time.
- Keep handlers thin: parse → route → mutate DB or archive → reply. Business rules live in
  `priority.py` / `digest.py` / `airtable_sync.py` / `archive/`.

## Commands

- install `uv sync` · run `uv run python -m nudge` · test `uv run pytest`

## Git

- Atomic commits, conventional-commit prefixes (`feat(scope): …`, `chore: …`).
- Never commit `.env`, `*.db`, or backups.
