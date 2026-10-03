"""
Settings stored in the database, shared by the web app and the crawler service.
"""

from typing import Any

from sqlmodel import Session

from clock import utc_now
from db import engine
from models import AppSetting

LLM = "llm"            # {"provider": str, "models": {provider: model}, "api_keys": {provider: key}}
AUTO_CRAWL = "auto_crawl"  # {"enabled": bool, "interval_hours": number}
CRAWL = "crawl"        # crawl requests and status, see crawler_service.py
CRAWLER_HEARTBEAT = "crawler_heartbeat"
JUDGE = "judge"          # {"enabled": bool, "models": {provider: model}}; see evaluator.py

DEFAULTS = {
    LLM: {"provider": None, "models": {}, "api_keys": {}},
    AUTO_CRAWL: {"enabled": True, "interval_hours": 24},
    CRAWL: {},
    CRAWLER_HEARTBEAT: None,
    JUDGE: {"enabled": True, "models": {}},
}


def get_setting(key: str) -> Any:
    with Session(engine) as session:
        row = session.get(AppSetting, key)
        if row is None:
            default = DEFAULTS.get(key)
            return dict(default) if isinstance(default, dict) else default
        return row.value


def set_setting(key: str, value: Any) -> None:
    with Session(engine) as session:
        row = session.get(AppSetting, key)
        if row is None:
            row = AppSetting(key=key)
        # Assign a fresh object so SQLAlchemy registers the JSON change
        row.value = dict(value) if isinstance(value, dict) else value
        row.updated_at = utc_now()
        session.add(row)
        session.commit()


def update_setting(key: str, **changes) -> dict:
    value = get_setting(key) or {}
    value.update(changes)
    set_setting(key, value)
    return value
