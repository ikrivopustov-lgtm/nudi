"""Typed configuration loaded from .env via pydantic-settings."""

from __future__ import annotations

from datetime import time
from functools import lru_cache
from zoneinfo import ZoneInfo

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Telegram
    telegram_bot_token: str
    telegram_allowed_user_id: int

    # OpenRouter
    openrouter_api_key: str = ""
    openrouter_model: str = "google/gemini-2.5-flash"

    # Airtable
    airtable_token: str = ""
    airtable_base_id: str = ""
    airtable_table: str = "Tasks"
    airtable_inbox_view: str = "Inbox"

    # Owner / scheduling
    owner_name: str = "Owner"
    timezone: str = "Europe/Moscow"
    morning_time: str = "08:30"   # HH:MM local
    weekly_time: str = "19:00"    # HH:MM local

    # Storage
    database_path: str = "data/nudge.db"

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    @property
    def morning_at(self) -> time:
        return _parse_hhmm(self.morning_time)

    @property
    def weekly_at(self) -> time:
        return _parse_hhmm(self.weekly_time)


def _parse_hhmm(value: str) -> time:
    hh, mm = value.strip().split(":")
    return time(hour=int(hh), minute=int(mm))


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
