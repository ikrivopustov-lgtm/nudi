# nudge — Project Kickoff

Персональный Telegram-ассистент задач. Один вход (текст в бота), короткий список
(правило 5), пинги как внешний триггер. Свой SQLite-мозг, Airtable как вторая дверь,
OpenRouter для разбора и приоритета. Собирается с Claude Code, крутится 24/7 на VPS.

## 0. Прогресс

**Сделано:**

- LLM-провайдер выбран: OpenRouter (kie.ai отклонён — он про генеративную медиа, не про
  дешёвый текст; OpenRouter уже в стеке и надёжнее для LLM).
- Хостинг заказан: Beget VPS, минимальная конфигурация (1 vCPU / 1 ГБ RAM / SSD 15–30 ГБ),
  Ubuntu, публичный IPv4 (нужен для исходящих запросов к Telegram/OpenRouter/Airtable).
- Доступ: SSH по ключу (ed25519 с Мака), вход под root работает. Сервер поднят.

**Осталось до кода:**

- `ufw default deny incoming` + разрешить только SSH; отключить вход по паролю в `sshd`.
- Поставить `git`, `uv`, Python 3.12 на сервер; `git init` в `~/code/personal/nudge`.
- Прогнать промпты P1→P8.

## 1. Assumptions

- Один пользователь (ты). Мультипользовательность не нужна — allowlist по Telegram user_id.
- Нагрузка мизерная: десятки задач в день. Никакого Redis/Celery/очередей на MVP.
- Канал = Telegram. Захват и пинги — только там.
- LLM = OpenRouter, дешёвая модель для парсинга (`google/gemini-2.5-flash` или
  `deepseek-chat`).
- Telegram через long-polling, не webhook → домен/TLS/порты не нужны. Публичный IPv4 —
  только для исходящих запросов.
- Airtable — вторичная входная точка и зеркало, синк через периодический poll.
- SQLite — единственный источник правды. Airtable отражает, но не владеет данными.
- Хостинг = Beget VPS, публичный IPv4, Ubuntu, запуск через systemd. Без Docker.
- Часовой пояс фиксированный (Europe/Moscow), хранится в конфиге.

## 2. Stack

- Язык: Python 3.12
- Бот + планировщик: `python-telegram-bot` v21 (встроенный JobQueue на APScheduler).
- БД: SQLite через `SQLModel`, режим WAL.
- LLM: OpenRouter через `httpx`, строгий JSON-ответ.
- Airtable: `pyairtable`.
- Конфиг: `pydantic-settings`, `.env` локально, `.env.example` в репе.
- Менеджер зависимостей: `uv`.
- Прод: Beget VPS (Ubuntu, публичный IPv4, root по SSH-ключу) + systemd.

## 6. Data model

```
Task
  id            int  pk
  title         str
  raw_text      str
  project       str?
  iso_week      str            # "2026-W30"
  priority      str            # P1 | P2 | P3
  status        str            # inbox | today | done | someday
  due_date      date?
  scheduled_for date?          # день, в который попадает в «сегодня»
  source        str            # tg | forward | airtable
  airtable_id   str?           # для зеркалирования
  created_at    datetime
  updated_at    datetime

Setting          # kv для времени пингов и tz
  key   str  pk
  value str
```

Правило «сегодня ≤5»: `status=today` + просроченные (`due_date < today`) + добор по
приоритету P1→P3, срез до 5.

## 8. Milestones

- **Day 0** — вертикальный срез: бот стартует (polling) с allowlist; текст → parse →
  задача в SQLite → подтверждение.
- **Day 1** — утренний дайджест ≤5; правки текстом; задача из пересланного сообщения.
- **Day 2** — Airtable poll-in + mirror-out; еженедельный ритуал; бэкап БД; деплой
  через systemd; ретраи и обработка ошибок.

## 10. Prompt pack (P1→P8)

- **P1** Scaffold — репо-скелет, `uv sync`, `python -m nudge` печатает «nudge up».
- **P2** Data model + DB — SQLModel `Task`/`Setting`, SQLite WAL, init.
- **P3** Bot skeleton + allowlist — PTB long-polling, `/start`, фильтр по user_id.
- **P4** Capture — text → `parse_text` → Task → confirm с inline-кнопками.
- **P5** Priority + morning digest — отбор ≤5 + `run_daily`.
- **P6** Weekly ritual — воскресный триаж инбокса кнопками.
- **P7** NL edits + forwarded capture — `parse_edit` (done/reschedule/priority) + forwards.
- **P8** Airtable sync + deploy — poll-in, mirror-out, systemd, deploy/backup скрипты.
