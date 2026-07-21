"""Test env defaults, set before nudge.config is first imported/cached."""

import os

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "123:test")
os.environ.setdefault("TELEGRAM_ALLOWED_USER_ID", "42")
os.environ.setdefault("OPENROUTER_API_KEY", "test-key")  # enables the mocked LLM path
os.environ.setdefault("DATABASE_PATH", "data/test-nudge.db")
