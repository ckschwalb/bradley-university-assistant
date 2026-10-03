"""
The assistant's system prompt. An edit saved in the admin dashboard replaces the previous one;
with none saved (or after resetting), the repository's systemprompt.txt is used.
"""

import os
from datetime import datetime
from typing import Optional

from sqlmodel import Session, delete, select

from clock import campus_now
from db import engine
from models import SavedPrompt

_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_PATHS = [
    os.path.join(os.path.dirname(_BACKEND_DIR), "systemprompt.txt"),  # repository root (local)
    os.path.join(_BACKEND_DIR, "systemprompt.txt"),                   # next to the code (Docker image)
]

CONTEXT_PLACEHOLDER = "{context}"


def default_prompt() -> str:
    for path in _DEFAULT_PATHS:
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                return f.read()
    return "You are a helpful AI Assistant for Bradley University.\n\nAvailable data:\n{context}"


def saved_prompt() -> Optional[SavedPrompt]:
    with Session(engine) as session:
        return session.exec(select(SavedPrompt).order_by(SavedPrompt.id.desc())).first()


def active_prompt() -> str:
    saved = saved_prompt()
    return saved.content if saved else default_prompt()


def save(content: str) -> Optional[SavedPrompt]:
    """Replace the saved prompt. Saving the default's exact text goes back to using systemprompt.txt,
    so later changes to that file apply. Returns the saved row, or None for the default."""
    with Session(engine) as session:
        session.exec(delete(SavedPrompt))
        saved = None
        if content != default_prompt():
            saved = SavedPrompt(content=content)
            session.add(saved)
        session.commit()
        if saved:
            session.refresh(saved)
        return saved


def render(template: str, context: str, now: Optional[datetime] = None) -> str:
    """Fill in today's date on campus and the retrieved context. Called per request so the date is current."""
    now = now or campus_now()  # the campus calendar, not the server's clock
    values = {
        "current_day": now.strftime('%A'),
        "current_date": now.strftime('%B %d, %Y'),
        "current_time": now.strftime('%I:%M %p'),
        "current_month": now.strftime('%B'),
        "current_year": str(now.year),
    }
    text = template
    for name, value in values.items():
        text = text.replace(f"{{current_date_info[{name}]}}", value)
    if CONTEXT_PLACEHOLDER in text:
        return text.replace(CONTEXT_PLACEHOLDER, context)
    return f"{text}\n\nUse the following context to answer the question:\n{context}"
