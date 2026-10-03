"""
SQLModel models for conversations, messages, feedback, the crawled index, and the
traces and quality evaluations behind the admin's Observability page
"""

import uuid
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import DateTime, LargeBinary
from sqlalchemy.types import TypeDecorator
from sqlmodel import JSON, Field, Relationship, SQLModel

from clock import utc_now


class UTCDateTime(TypeDecorator):
    """Stores times as UTC and reads them back with the UTC offset attached.

    SQLite has no time zone type, so the column holds UTC wall-clock time. Refusing naive values
    keeps a local time from ever being written as if it were UTC.
    """
    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: Optional[datetime], dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("Naive datetime; use an aware time such as clock.utc_now()")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: Optional[datetime], dialect):
        return value.replace(tzinfo=UTC) if value is not None else None


def utc_field(**kwargs) -> Any:
    return Field(default_factory=utc_now, sa_type=UTCDateTime, **kwargs)


class Conversation(SQLModel, table=True):
    __tablename__ = "conversations"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    started_at: datetime = utc_field()

    messages: list["Message"] = Relationship(back_populates="conversation")
    feedback: list["Feedback"] = Relationship(back_populates="conversation")


class Message(SQLModel, table=True):
    __tablename__ = "messages"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    conversation_id: str = Field(foreign_key="conversations.id")
    role: str  # 'user' or 'assistant'
    content: str
    created_at: datetime = utc_field()
    # Assistant messages: {provider, model, sources (pages the answer used), retrieved (what search returned)}
    details: Optional[Dict[str, Any]] = Field(default=None, sa_type=JSON)

    conversation: Conversation = Relationship(back_populates="messages")
    feedback: list["Feedback"] = Relationship(back_populates="message")


class Feedback(SQLModel, table=True):
    __tablename__ = "feedback"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    conversation_id: str = Field(foreign_key="conversations.id")
    message_id: Optional[str] = Field(default=None, foreign_key="messages.id")
    rating: int = Field(ge=-1, le=1)  # 1 for thumbs up, -1 for thumbs down
    comment: Optional[str] = None
    created_at: datetime = utc_field()

    conversation: Conversation = Relationship(back_populates="feedback")
    message: Optional[Message] = Relationship(back_populates="feedback")


class CrawledDocument(SQLModel, table=True):
    """One chunk of a crawled page or course, with its embedding"""
    __tablename__ = "crawled_documents"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    url: str = Field(index=True)  # shared by every chunk of a page
    title: str
    content: str
    content_type: str  # 'page', 'faculty-staff', 'program', 'course', ...
    created_at: datetime = utc_field()
    updated_at: datetime = utc_field()
    embedding: Optional[bytes] = Field(default=None, sa_type=LargeBinary)  # normalized float32 vector
    doc_metadata: Optional[Dict[str, Any]] = Field(default=None, sa_type=JSON)  # modified time and content hash
    chunk_index: Optional[int] = None  # position of this chunk within the page (0, 1, 2, ...)
    total_chunks: Optional[int] = None


class AppSetting(SQLModel, table=True):
    """Key/value settings shared by the web app and the crawler service"""
    __tablename__ = "app_settings"

    key: str = Field(primary_key=True)
    value: Optional[Any] = Field(default=None, sa_type=JSON)
    updated_at: datetime = utc_field()


class SavedPrompt(SQLModel, table=True):
    """The system prompt as edited in the admin dashboard: at most one row. With none,
    the repository's systemprompt.txt is used (see system_prompt.py)."""
    __tablename__ = "system_prompts"

    id: Optional[int] = Field(default=None, primary_key=True)
    content: str
    created_at: datetime = utc_field()


class ReviewMark(SQLModel, table=True):
    """An item in the admin's Needs review list that someone marked as reviewed"""
    __tablename__ = "review_marks"

    key: str = Field(primary_key=True)  # see review_items in routers/conversations.py
    reviewed_at: datetime = utc_field()


class Trace(SQLModel, table=True):
    """One call to the AI provider: a chat answer, a quality judgement or a prompt preview.

    Holds timings, token counts and the outcome, not the text, so it can outlive the conversation.
    """
    __tablename__ = "traces"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    created_at: datetime = utc_field(index=True)
    kind: str  # 'chat', 'judge', 'preview'
    status: str  # 'ok' or 'error'
    provider: Optional[str] = None
    model: Optional[str] = None
    conversation_id: Optional[str] = None
    message_id: Optional[str] = None  # the answer this call wrote or judged
    error: Optional[str] = None
    search_ms: Optional[int] = None
    first_token_ms: Optional[int] = None
    total_ms: Optional[int] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    top_score: Optional[float] = None  # best search similarity, a rough measure of how well the index covers the question


class AnswerEvaluation(SQLModel, table=True):
    """The quality judge's verdict on one answer (see evaluator.py); scores run 1 to 5"""
    __tablename__ = "answer_evaluations"

    id: Optional[int] = Field(default=None, primary_key=True)
    message_id: str = Field(foreign_key="messages.id", index=True)
    created_at: datetime = utc_field()
    provider: str
    model: str
    groundedness: int
    relevance: int
    completeness: int
    unsupported_claims: List[str] = Field(default_factory=list, sa_type=JSON)
    rationale: str = ""
