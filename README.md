<p align="center">
  <img src="docs/assets/logo.png" width="168" alt="Nudi" />
</p>

<h1 align="center">Nudi</h1>

<p align="center">
  Личный ассистент в Telegram.<br />
  Пишешь как другу. Сегодня — не больше пяти дел. Ссылки не попадают в список задач.
</p>

<p align="center">
  <img alt="Python 3.12" src="https://img.shields.io/badge/python-3.12-07133d?style=flat-square" />
  <img alt="License MIT" src="https://img.shields.io/badge/license-MIT-c7ff62?style=flat-square&labelColor=07133d" />
  <img alt="Один пользователь" src="https://img.shields.io/badge/пользователей-1-0a2bff?style=flat-square&labelColor=07133d" />
</p>

<p align="center">
  <img src="docs/assets/banner.png" alt="Пиши как другу. Задачи в чате, ссылки в архиве, сегодня не больше пяти." />
</p>

Ставишь себе на сервер. Один человек в Telegram. Один файл SQLite. Внутри бота нет Docker.

Пакет в коде по-прежнему `nudge` (`uv run python -m nudge`). **Nudi** — имя, которое видишь в чате.

## Как это работает

Пишешь в Telegram так, как думаешь. Nudi кладёт сообщение в **одну из двух коробок**:

| Что прислал | Куда попадает |
| --- | --- |
| Обычный текст (`оплатить налоги`) | Задачи (SQLite) |
| «сделал налоги», `налоги ✓` | Закрывает задачу сразу, без ожидания модели |
| Пересланный пост, ссылка, рилс, TikTok | Архив ([Karakeep](https://github.com/karakeep-app/karakeep)) |
| Кнопка **📎 Сохранить**, затем следующее сообщение | Архив |

**Сегодня** — короткий список: максимум пять дел. Бэклог ждёт. Сам оттуда ничего не подмешивается.

<p align="center">
  <img src="docs/assets/how-it-works.png" alt="Один чат. Две коробки — задачи и архив." />
</p>

<p align="center">
  <img src="docs/assets/chats.png" alt="Четыре экрана: завести задачу, сегодня из пяти, закрыть галочкой, сохранить рилс в архив." />
</p>

Клавиатура: **Сегодня** · **Бэклог** · **Сделано** · **Сохранить** · **Помощь**. После смены кнопок один раз напиши `/start`.

## Что можно писать

- **Завести** — `оплатить налоги до пятницы`, `напомни про звонок сегодня в 15:00`
- **Закрыть** — `сделал налоги`, `налоги ✓`, `готово` (или цитата строки из /today → `сделано`)
- **Перенести** — `на пятницу`, `на след неделю`, `отложи` (без даты → в бэклог)
- **История** — `что сделал за неделю?` или `/done` (листы ← →). Закрытые задачи не удаляются.
- **Отмена** — `отмени` откатывает последний заход.

Сложные фразы идут в одну модель через OpenRouter (`gemini-2.5-flash-lite`, запасной вариант — `flash`). «сделал X» модель не ждёт.

## Из чего состоит

Python 3.12 · `python-telegram-bot` v21 · SQLite · OpenRouter · по желанию [Karakeep](https://github.com/karakeep-app/karakeep) · по желанию Apify (расшифровка TikTok/рилсов) · по желанию зеркало в Airtable.

Правда всегда в SQLite. Airtable — второй вход, но не хозяин данных.

```
Telegram
   │
   ├─ архив     →  Karakeep     (ссылки, пересылки, рилсы)
   ├─ быстро    →  закрыть / история / бэклог   (без модели)
   └─ ассистент →  OpenRouter → SQLite
```

## Запуск

```bash
uv sync
cp .env.example .env   # токен бота, свой Telegram id, ключ OpenRouter
uv run python -m nudge
uv run pytest
```

Нужно: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_USER_ID`, `OPENROUTER_API_KEY`.  
По желанию: `KARAKEEP_API_URL` + `KARAKEEP_API_KEY`, `APIFY_TOKEN`, Airtable.

Это бот **для одного человека**. Сообщение от кого-то другого записывается в лог и отбрасывается.

Деплой — один systemd-юнит (`scripts/nudge.service`) и `scripts/deploy.sh`. Пути в файлах — пример, их надо поправить под свой сервер.

## Где что лежит

```
src/nudge/
  assistant.py    модель и инструменты
  fastpath.py     мгновенное закрытие / история / бэклог
  archive/        Karakeep + Apify + маршрутизация
  handlers.py     команды Telegram и клавиатура
  store.py        задачи, отмена, история
  priority.py     сегодня ≤ 5
  digest.py       утренний список и воскресный бэклог
```

## Лицензия

[MIT](LICENSE) © 2026 Ilya Krivopustov
