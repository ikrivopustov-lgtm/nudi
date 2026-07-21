"""Small LLM-adjacent helpers shared across modules.

The conversational core lives in assistant.py (agentic tool-calling). This module
now only holds the ISO-week helper used when computing a task's week bucket.
"""

from __future__ import annotations

from datetime import date


def iso_week_of(d: date) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"
