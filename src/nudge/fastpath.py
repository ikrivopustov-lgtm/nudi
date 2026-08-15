"""Deterministic free-form shortcuts — no LLM, instant reply.

Inspired by TG Tasks: "called the supplier ✓", "done with X", "сделал налоги".
Common complete / history phrases are matched against the live task list locally
so closing a task feels instant instead of waiting on OpenRouter.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import store
from .models import Task, priority_dot

# Markers that mean "close this" (TG Tasks style: done / ✓ / готово).
_DONE_MARKERS = (
    "сделал", "сделала", "сделано", "сделали",
    "выполнил", "выполнила", "выполнено",
    "закрыл", "закрыла", "закрыто",
    "готово", "готов", "готова",
    "done", "completed", "finish", "finished",
)

# Strip trailing/leading punctuation and checkmarks.
_PUNCT = re.compile(r"^[\s\-–—:·.•]+|[\s\-–—:·.•]+$")
_CHECK = re.compile(r"[✓✔✅☑➕＋+]+")


def _norm(text: str) -> str:
    t = unicodedata.normalize("NFKC", text or "").lower().strip()
    t = _CHECK.sub(" ", t)
    t = re.sub(r"\s+", " ", t)
    return t.strip()


def _strip_markers(text: str) -> str:
    """Remove done-markers and punctuation; leftover is the task hint."""
    t = _norm(text)
    # "X - сделано" / "X сделано" / "сделал X" / "done: X"
    for m in _DONE_MARKERS:
        # marker at start: "сделал налоги", "done taxes"
        t = re.sub(rf"^{re.escape(m)}\b[\s:]*", "", t)
        # marker at end: "налоги сделано", "taxes done"
        t = re.sub(rf"[\s:]*\b{re.escape(m)}$", "", t)
        # marker after dash: "налоги - сделано"
        t = re.sub(rf"\s*[-–—:]\s*{re.escape(m)}$", "", t)
    return _PUNCT.sub("", t).strip()


def looks_like_complete(text: str) -> bool:
    """True if the message clearly claims a completion (has a done-marker or ✓)."""
    raw = text or ""
    if _CHECK.search(raw):
        return True
    n = _norm(raw)
    return any(re.search(rf"\b{re.escape(m)}\b", n) for m in _DONE_MARKERS)


def looks_like_history(text: str) -> bool:
    n = _norm(text)
    patterns = (
        r"что сделал",
        r"что сделала",
        r"что закрыл",
        r"что выполнил",
        r"сделанн\w* за",
        r"закрыт\w* за",
        r"история",
        r"за неделю",
        r"за последн",
        r"^/done$",
        r"list done",
        r"what did i (do|finish|complete)",
    )
    return any(re.search(p, n) for p in patterns)


def score_match(hint: str, task: Task) -> float:
    """0..1 how well `hint` matches the task title/project."""
    if not hint:
        return 0.0
    h = _norm(hint)
    title = _norm(task.title)
    project = _norm(task.project or "")
    if not h:
        return 0.0
    if h == title:
        return 1.0
    if h in title or title in h:
        # prefer longer overlap
        return 0.85 + 0.1 * min(len(h), len(title)) / max(len(title), 1)
    # all significant tokens of hint appear in title
    tokens = [tok for tok in re.split(r"\W+", h) if len(tok) >= 3]
    if tokens and all(tok in title or tok in project for tok in tokens):
        return 0.7
    if project and (h in project or project in h):
        return 0.55
    return 0.0


def find_complete_candidates(text: str) -> list[tuple[Task, float]]:
    if not looks_like_complete(text):
        return []
    hint = _strip_markers(text)
    # Bare "готово" / "done" / "✓" with no hint → most recently touched active task
    active = store.list_active()
    if not hint:
        last = store.last_touched_active()
        return [(last, 0.6)] if last else []
    scored = [(t, score_match(hint, t)) for t in active]
    scored = [(t, s) for t, s in scored if s >= 0.55]
    scored.sort(key=lambda x: (-x[1], -(x[0].updated_at.timestamp() if x[0].updated_at else 0)))
    return scored


def try_fast_complete(text: str, *, today: date, tz: ZoneInfo) -> str | None:
    """If message is a clear completion, close the task without LLM. Else None."""
    from .assistant import _Executor

    cands = find_complete_candidates(text)
    if not cands:
        return None
    best_score = cands[0][1]
    top = [c for c in cands if c[1] >= best_score - 0.05 and c[1] >= 0.55]

    # Same title repeated (stale twins) → close the most recently touched one.
    titles = {_norm(t.title) for t, _ in top}
    if len(top) > 1 and len(titles) == 1:
        top = [top[0]]

    if len(top) > 1 and top[0][1] < 0.95:
        lines = ["Несколько похожих — уточни, какую закрыть:"]
        for t, _ in top[:5]:
            lines.append(f"• #{t.id} {priority_dot(t.priority)} {t.title}")
        return "\n".join(lines)

    task = top[0][0]
    out = _Executor(today, tz, None).run("complete_task", {"task_id": task.id})
    if out.startswith("error"):
        return None
    from .priority import select_today

    left = len(select_today(today))
    closed = store.get_task(task.id)
    title = closed.title if closed else task.title
    return f"✔️ Закрыл: {title}\n\nосталось сегодня: {left}"


def try_fast_history(text: str, *, today: date, tz: ZoneInfo) -> str | None:
    """Current calendar week of completions (same text as /done)."""
    if not looks_like_history(text):
        return None
    from .done_history import render_done_week, week_monday

    return render_done_week(week_monday(today), today=today, tz=tz)


def looks_like_inbox(text: str) -> bool:
    n = _norm(text)
    patterns = (
        r"^бэклог$",
        r"^беклог$",
        r"^инбокс$",
        r"^inbox$",
        r"разбер(и|ём|ем)\s+инбокс",
        r"покажи\s+инбокс",
        r"что\s+в\s+инбоксе",
        r"^backlog$",
    )
    return any(re.search(p, n) for p in patterns)


def try_fast_inbox(text: str) -> str | None:
    """List backlog in plain text, split dated / undated (TG Tasks Inbox+Queue style)."""
    if not looks_like_inbox(text):
        return None
    from .digest import format_scheduled, split_inbox

    inbox = store.list_by_status("inbox")
    if not inbox:
        return "📋 Бэклог пуст. Чисто.\n\nРазбор кнопками: /backlog"
    dated, undated = split_inbox(inbox)
    lines = [
        f"📋 Бэклог ({len(inbox)}) · без даты {len(undated)} · на дату {len(dated)}"
    ]
    if undated:
        lines.append("\n📥 Без даты:")
        for t in undated[:15]:
            proj = f" · {t.project}" if t.project else ""
            lines.append(f"• #{t.id} {priority_dot(t.priority)} {t.title}{proj}")
    if dated:
        lines.append("\n📅 На дату:")
        for t in dated[:15]:
            proj = f" · {t.project}" if t.project else ""
            when = format_scheduled(t.scheduled_for) if t.scheduled_for else "?"
            lines.append(f"• #{t.id} {priority_dot(t.priority)} {t.title}{proj} · {when}")
    lines.append("\nРазложить кнопками: /backlog")
    return "\n".join(lines)


# Explicit "create this" prefixes — strip them from the title.
_CREATE_PREFIX = re.compile(
    r"^(?:"
    r"поставь\s+задачу|"
    r"сделай\s+задачу|"
    r"новая\s+задача|"
    r"задача|"
    r"todo|"
    r"добавь(?:\s+задачу)?|"
    r"заведи(?:\s+задачу)?|"
    r"закинь(?:\s+задачу)?|"
    r"запиши(?:\s+задачу)?|"
    r"в\s+задачи|"
    r"нужно|"
    r"надо|"
    r"не\s+забыть"
    r")\s*[:—\-·.]?\s+",
    re.IGNORECASE,
)
# "поставь X" but NOT "поставь на пятницу" (that's reschedule).
_CREATE_POSTAV = re.compile(r"^поставь\s+(?!на\b)(.+)$", re.IGNORECASE | re.DOTALL)

# Messages that must go to the LLM (edit / ask / confirm), not bare-create.
_MUTATE_OR_ASK = re.compile(
    r"(?:"
    r"\?|"
    r"^(да|нет|ок|окей|ага|угу|ладно|хорошо|давай)$|"
    r"^/"
    r"|перенес|перенести|отлож|напомни|удали|убери\s+из|убери\s+с|"
    r"отмени|undo|приоритет|"
    r"давай\s+на|кинь\s+на|подвинь|сдвинь|поставь\s+на|"
    r"сделай\s+(красн|жёлт|желт|оранж)|"
    r"^на\s+(сегодня|завтра|послезавтра|понедельник|вторник|среду|"
    r"четверг|пятницу|субботу|воскресенье|след|"
    r"конец|выходн|\d)"
    r"|что\s+(горит|сегодня|сделал|закрыл|в\s+инбоксе|в\s+бэклоге)"
    r"|сколько\s+|какие\s+|где\s+"
    r"|найди|покажи|скажи|расскажи|объясни"
    r")",
    re.IGNORECASE,
)

_CHITCHAT = re.compile(
    r"^(привет|здравствуй\w*|хай|hello|hi|hey|спасибо|благодар\w*|"
    r"пока|доброе\s+утро|добрый\s+(день|вечер)|помощь|help)$",
    re.IGNORECASE,
)


def extract_create_title(text: str) -> str | None:
    """If message is clearly 'create a task', return the title. Else None."""
    raw = (text or "").strip()
    if not raw or len(raw) > 400:
        return None
    n = _norm(raw)
    if looks_like_complete(raw) or looks_like_history(raw) or looks_like_inbox(raw):
        return None
    if _CHITCHAT.match(n) or _MUTATE_OR_ASK.search(n):
        return None

    m = _CREATE_PREFIX.match(raw)
    if m:
        title = raw[m.end():].strip()
        title = _PUNCT.sub("", title).strip()
        return title if len(title) >= 2 else None

    m = _CREATE_POSTAV.match(raw)
    if m:
        title = m.group(1).strip()
        title = _PUNCT.sub("", title).strip()
        return title if len(title) >= 2 else None

    # Bare title: short free text without edit/ask markers → new task (TG Tasks style).
    if len(n) < 2:
        return None
    # Skip pure emoji / punctuation.
    if not re.search(r"[\wа-яёА-ЯЁ]", raw, re.IGNORECASE):
        return None
    return raw.strip()


def try_fast_create(text: str, *, today: date, tz: ZoneInfo) -> str | None:
    """Create a task without LLM when intent is clearly 'new task'."""
    title = extract_create_title(text)
    if not title:
        return None
    from .assistant import _Executor

    out = _Executor(today, tz, None).run("create_task", {"title": title})
    if out.startswith("error"):
        return None
    return f"✅ В бэклог: {title}"


# Explicit reschedule / move-to-date signals (not bare "X на фронт" create titles).
_RESCHEDULE_SIGNAL = re.compile(
    r"(?:"
    r"\bперенес\w*\b|"
    r"\bподвинь\w*\b|"
    r"\bсдвинь\w*\b|"
    r"давай\s+на\b|"
    r"давай\s+поставим\s+на\b|"
    r"давай\s+сдвинем\s+на\b|"
    r"кинь\s+на\b|"
    r"поставь\s+на\b|"
    r"отлож\w*\s+на\b"
    r")",
    re.IGNORECASE,
)

# Date phrase — usually at the end: «на вторник», «на след неделю», «завтра».
_DATE_PHRASE = re.compile(
    r"(?P<full>"
    r"(?:\s+(?:давай|поставь|сдвинь|кинь|подвинь))?\s+на\s+"
    r"(?P<body>"
    r"сегодня|завтра|послезавтра|"
    r"понедельник|вторник|среду|среда|четверг|пятницу|пятница|субботу|суббота|воскресенье|"
    r"след(?:ующ(?:ую|ей|ий)?)?\.?\s*недел[еиюя]?|"
    r"конец\s+недели|выходн\w*|"
    r"\d{1,2}[./]\d{1,2}(?:[./]\d{2,4})?"
    r")"
    r"|"
    r"\s+через\s+неделю"
    r"|"
    r"\s+(?:на\s+)?(?P<body2>сегодня|завтра|послезавтра)"
    r")\s*$",
    re.IGNORECASE,
)

_WEEKDAY_RU = {
    "понедельник": 0,
    "вторник": 1,
    "среду": 2,
    "среда": 2,
    "четверг": 3,
    "пятницу": 4,
    "пятница": 4,
    "субботу": 5,
    "суббота": 5,
    "воскресенье": 6,
}

_ACTION_STRIP = re.compile(
    r"^(?:"
    r"перенес\w*|подвинь\w*|сдвинь\w*|кинь|поставь|отлож\w*|давай|"
    r"давай\s+поставим|давай\s+сдвинем"
    r")\s+",
    re.IGNORECASE,
)

_TITLE_VERB_STRIP = re.compile(
    r"^(?:перенести|перенес|сделать|проверить|добавить)\s+",
    re.IGNORECASE,
)


def looks_like_reschedule(text: str) -> bool:
    n = _norm(text)
    return bool(_RESCHEDULE_SIGNAL.search(n))


def resolve_relative_date(body: str, *, today: date) -> date | None:
    """Map a Russian date fragment to a concrete date, or None."""
    b = _norm(body)
    if not b:
        return None
    if b == "сегодня":
        return today
    if b == "завтра":
        return today + timedelta(days=1)
    if b == "послезавтра":
        return today + timedelta(days=2)
    if b == "через неделю" or "через неделю" in b:
        return today + timedelta(days=7)
    if "конец недели" in b or b.startswith("выходн"):
        # nearest Friday (or today if Friday/Sat/Sun → Friday this week already passed → next Fri)
        days = (4 - today.weekday()) % 7
        return today + timedelta(days=days)
    if "недел" in b:  # след. неделя / следующую неделю / ...
        # Monday of next ISO week
        days = (7 - today.weekday()) % 7
        if days == 0:
            days = 7
        return today + timedelta(days=days)
    for name, wd in _WEEKDAY_RU.items():
        if name in b:
            delta = (wd - today.weekday()) % 7
            return today + timedelta(days=delta)
    m = re.match(r"^(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?$", b)
    if m:
        d, mo = int(m.group(1)), int(m.group(2))
        if m.group(3):
            y = int(m.group(3))
            if y < 100:
                y += 2000
        else:
            y = today.year
            candidate = date(y, mo, d)
            if candidate < today:
                y += 1
        try:
            return date(y, mo, d)
        except ValueError:
            return None
    return None


def extract_reschedule(text: str, *, today: date) -> tuple[str, date] | None:
    """If message is a reschedule, return (task_hint, target_date). Else None."""
    raw = (text or "").strip()
    if not raw or not looks_like_reschedule(raw):
        return None
    m = _DATE_PHRASE.search(raw)
    if not m:
        return None
    body = m.group("body") or m.group("body2")
    if body is None and "через неделю" in _norm(m.group("full")):
        body = "через неделю"
    target = resolve_relative_date(body or "", today=today)
    if target is None:
        return None
    head = raw[: m.start()].strip()
    head = _PUNCT.sub("", head).strip()
    # Strip leading action verbs → leftover is the task hint.
    hint = head
    for _ in range(3):
        nxt = _ACTION_STRIP.sub("", hint).strip()
        if nxt == hint:
            break
        hint = nxt
    hint = _PUNCT.sub("", hint).strip()
    # Pronouns / empty → last touched
    if _norm(hint) in {"", "это", "эту", "её", "ее", "её", "последнюю", "последнее", "её"}:
        hint = ""
    return hint, target


def score_match_reschedule(hint: str, task: Task) -> float:
    """Like score_match, but also compares against title without a leading verb."""
    base = score_match(hint, task)
    if not hint:
        return base
    h = _norm(hint)
    title_core = _TITLE_VERB_STRIP.sub("", _norm(task.title)).strip()
    if title_core and (h == title_core or h in title_core or title_core in h):
        base = max(base, 0.9 + 0.05 * min(len(h), len(title_core)) / max(len(title_core), 1))
    # Full title as typed (user repeats task name including «Перенести …»)
    if h == _norm(task.title):
        base = 1.0
    return min(base, 1.0)


def find_reschedule_candidates(hint: str) -> list[tuple[Task, float]]:
    active = store.list_active()
    if not hint:
        last = store.last_touched_active()
        return [(last, 0.6)] if last else []
    # Score with stripped hint and with raw hint (user may paste full title).
    scored: list[tuple[Task, float]] = []
    for t in active:
        s = max(score_match_reschedule(hint, t), score_match(hint, t))
        if s >= 0.55:
            scored.append((t, s))
    scored.sort(key=lambda x: (-x[1], -(x[0].updated_at.timestamp() if x[0].updated_at else 0)))
    return scored


def try_fast_reschedule(text: str, *, today: date, tz: ZoneInfo) -> str | None:
    """Move a task to a date without LLM when phrasing is clear."""
    parsed = extract_reschedule(text, today=today)
    if parsed is None:
        return None
    hint, target = parsed
    from .assistant import _Executor
    from .digest import format_scheduled

    cands = find_reschedule_candidates(hint)
    if not cands:
        # User often pastes the full title including «Перенести …»
        m = _DATE_PHRASE.search((text or "").strip())
        if m:
            head = (text or "").strip()[: m.start()].strip()
            if head and _norm(head) != _norm(hint):
                cands = find_reschedule_candidates(head)
    if not cands:
        return None  # let LLM try / clarify
    best = cands[0][1]
    top = [c for c in cands if c[1] >= best - 0.05 and c[1] >= 0.55]
    titles = {_norm(t.title) for t, _ in top}
    if len(top) > 1 and len(titles) == 1:
        top = [top[0]]
    if len(top) > 1 and top[0][1] < 0.95:
        lines = ["Несколько похожих — уточни, какую перенести:"]
        for t, _ in top[:5]:
            lines.append(f"• #{t.id} {priority_dot(t.priority)} {t.title}")
        return "\n".join(lines)

    task = top[0][0]
    out = _Executor(today, tz, None).run(
        "update_task",
        {"task_id": task.id, "scheduled_for": target.isoformat()},
    )
    if out.startswith("error"):
        return None
    updated = store.get_task(task.id)
    title = updated.title if updated else task.title
    when = format_scheduled(target)
    return f"✏️ Перенёс: {title} → 📅 {when}"


# --- Telegram native quote (Цитировать) → complete / backlog ---------------

# Bare commands only — title comes from quote.text, not from the reply body.
_QUOTE_COMPLETE = re.compile(
    r"^(?:"
    r"сделал[аио]?|сделано|"
    r"выполнил[аио]?|выполнено|"
    r"закрыл[аио]?|закрыто|"
    r"готово|готов[ао]?|"
    r"done|completed|finish(?:ed)?"
    r")$",
    re.IGNORECASE,
)
_QUOTE_BACKLOG = re.compile(
    r"^(?:"
    r"в\s+б[еэ]клог|в\s+инбокс|"
    r"отлож\w*|пока\s+отлож\w*|потом|не\s+сегодня|"
    r"убери\s+(?:из|с)\s+сегодня|из\s+сегодня\s+убери|"
    r"backlog|inbox"
    r")$",
    re.IGNORECASE,
)
# Digest line chrome: «1. 🟠 title» or «🟠 title»
_DIGEST_LINE_PREFIX = re.compile(
    r"^(?:\d+[.)]\s*)?(?:[🔴🟠🟡]\s*)?",
)
_TRAILING_ELLIPSIS = re.compile(r"[…\.]+$")


def parse_quote_command(text: str) -> str | None:
    """Return 'complete' | 'backlog' if reply body is a bare quote-command."""
    raw = (text or "").strip()
    if not raw or len(raw) > 80:
        return None
    # Pure checkmarks → complete
    if _CHECK.fullmatch(raw.strip()):
        return "complete"
    n = _norm(raw)
    n = _PUNCT.sub("", n).strip()
    if not n:
        return None
    if _QUOTE_COMPLETE.match(n):
        return "complete"
    if _QUOTE_BACKLOG.match(n):
        return "backlog"
    return None


def clean_quote_hint(quote_text: str) -> str:
    """Strip digest numbering / priority dots from a Telegram partial quote."""
    raw = (quote_text or "").strip()
    if not raw:
        return ""
    # Drop HTML leftovers if any (digest uses parse_mode=HTML).
    raw = raw.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    t = _DIGEST_LINE_PREFIX.sub("", raw).strip()
    t = _TRAILING_ELLIPSIS.sub("", t).strip()
    t = _PUNCT.sub("", t).strip()
    return t


def find_quote_candidates(hint: str) -> list[tuple[Task, float]]:
    """Match quote substring against active tasks (today + inbox)."""
    cleaned = clean_quote_hint(hint)
    if len(_norm(cleaned)) < 3:
        return []
    active = store.list_active()
    scored: list[tuple[Task, float]] = []
    for t in active:
        s = max(score_match(cleaned, t), score_match(hint, t))
        # Truncated quote: user selected prefix of the title (common in long lines).
        title = _norm(t.title)
        h = _norm(cleaned)
        if h and title.startswith(h):
            s = max(s, 0.92)
        if s >= 0.55:
            scored.append((t, s))
    scored.sort(
        key=lambda x: (
            -x[1],
            -(x[0].updated_at.timestamp() if x[0].updated_at else 0),
        )
    )
    return scored


def try_quote_action(
    text: str,
    quote_text: str,
    *,
    today: date,
    tz: ZoneInfo,
) -> str | None:
    """Handle Telegram «Цитировать» + bare command. None → not a quote command."""
    action = parse_quote_command(text)
    if action is None:
        return None

    hint = clean_quote_hint(quote_text)
    if len(_norm(hint)) < 3:
        return "Не понял цитату — выдели название задачи."

    cands = find_quote_candidates(hint)
    if not cands:
        short = hint if len(hint) <= 80 else hint[:77] + "…"
        return f"Не нашёл задачу по цитате: «{short}»"

    best = cands[0][1]
    top = [c for c in cands if c[1] >= best - 0.05 and c[1] >= 0.55]
    titles = {_norm(t.title) for t, _ in top}
    if len(top) > 1 and len(titles) == 1:
        top = [top[0]]
    if len(top) > 1 and top[0][1] < 0.95:
        verb = "закрыть" if action == "complete" else "отложить"
        lines = [f"Несколько похожих — уточни, какую {verb}:"]
        for t, _ in top[:5]:
            lines.append(f"• #{t.id} {priority_dot(t.priority)} {t.title}")
        return "\n".join(lines)

    task = top[0][0]
    from .assistant import _Executor

    if action == "complete":
        out = _Executor(today, tz, None).run("complete_task", {"task_id": task.id})
        if out.startswith("error"):
            return None
        from .priority import select_today

        left = len(select_today(today))
        closed = store.get_task(task.id)
        title = closed.title if closed else task.title
        return f"✔️ Закрыл: {title}\n\nосталось сегодня: {left}"

    # backlog
    out = _Executor(today, tz, None).run(
        "update_task",
        {"task_id": task.id, "status": "inbox"},
    )
    if out.startswith("error"):
        return None
    updated = store.get_task(task.id)
    title = updated.title if updated else task.title
    return f"📋 В бэклог: {title}"


def try_fast_path(text: str, *, today: date, tz: ZoneInfo) -> str | None:
    """Run cheap deterministic handlers before the LLM. Returns reply or None."""
    inbox = try_fast_inbox(text)
    if inbox is not None:
        return inbox
    # Complete first: "сделал X за неделю" is still a completion, not history.
    if looks_like_complete(text) and not looks_like_history(text):
        return try_fast_complete(text, today=today, tz=tz)
    if looks_like_complete(text):
        # Ambiguous: has both done-marker and history words → prefer complete
        # only when there's a concrete task hint after stripping markers.
        hint = _strip_markers(text)
        if hint and hint not in {"за неделю", "за последние дни", "история"}:
            return try_fast_complete(text, today=today, tz=tz)
    hist = try_fast_history(text, today=today, tz=tz)
    if hist is not None:
        return hist
    if looks_like_complete(text):
        return try_fast_complete(text, today=today, tz=tz)
    # Reschedule before create — «перенести X на вторник» must not become a new task.
    moved = try_fast_reschedule(text, today=today, tz=tz)
    if moved is not None:
        return moved
    created = try_fast_create(text, today=today, tz=tz)
    if created is not None:
        return created
    return None
