# Nudi — product notes

Personal Telegram assistant: one inbox, a short today list (rule of 5), and a
separate archive for links and reels. The Python package / service name is
`nudge`; the name in chat is **Nudi**.

## Assumptions that still hold

- **One user.** Allowlist is `TELEGRAM_ALLOWED_USER_ID`. No multi-user mode.
- Tiny load: tens of tasks a day. No Redis / Celery inside the bot process.
- Channel is Telegram only (long-polling, no webhook).
- SQLite is the source of truth for tasks. Airtable may mirror; it never wins.
- Personal materials (forwards, URLs, Reels) live in **Karakeep**, not in `Task`.
- Timezone is fixed in config (default `Europe/Moscow`).

## Stack

Python 3.12 · `python-telegram-bot` v21 · SQLite / SQLModel (WAL) · OpenRouter
via `httpx` · optional Karakeep, Apify, Airtable · `uv` · systemd on a VPS.

See [DATA_MODEL.md](DATA_MODEL.md) for tables and the today ≤ 5 rule.
See the root [README](../README.md) for how a message is routed.
