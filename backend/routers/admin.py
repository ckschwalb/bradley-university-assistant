"""
Admin API for the Bradley AI Assistant dashboard.

By default there is no password: the app only listens on this machine (see docker-compose.yml), and
main.py refuses state-changing requests that come from other websites. Set ADMIN_TOKEN to require
a bearer token (auth.py).
"""

import os
from datetime import timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import delete, or_
from sqlmodel import Session, func, select

import system_prompt
from auth import require_admin
from clock import parse_iso, utc_iso, utc_now
from db import get_session
from models import AnswerEvaluation, Conversation, CrawledDocument, Feedback, Message, ReviewMark, SavedPrompt
from settings_store import AUTO_CRAWL, CRAWL, CRAWLER_HEARTBEAT, get_setting, set_setting, update_setting

PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")
CRAWLER_OFFLINE_AFTER = timedelta(seconds=60)  # the service writes a heartbeat every 15 seconds

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])


class SystemPromptUpdate(BaseModel):
    content: str


class CrawlRequest(BaseModel):
    force: bool = False
    targets: Optional[List[str]] = None  # "site", "courses"; default both


class AutoCrawlUpdate(BaseModel):
    enabled: bool
    interval_hours: float = 24


# ---- System prompt -------------------------------------------------------

def prompt_view(saved: Optional[SavedPrompt]) -> dict:
    """The prompt in use, and the default (systemprompt.txt) so the editor can offer to go back to it"""
    default = system_prompt.default_prompt()
    return {"content": saved.content if saved else default, "is_default": saved is None,
            "saved_at": saved and saved.created_at, "default_content": default}


@router.get("/system-prompt")
async def get_current_system_prompt():
    return prompt_view(system_prompt.saved_prompt())


@router.post("/system-prompt")
async def update_system_prompt(update: SystemPromptUpdate):
    """Replace the prompt. It applies to the next chat message, no restart needed."""
    if not update.content.strip():
        raise HTTPException(status_code=400, detail="The system prompt can't be empty")
    return prompt_view(system_prompt.save(update.content))


# ---- Crawling ------------------------------------------------------------

def crawler_online() -> bool:
    heartbeat = get_setting(CRAWLER_HEARTBEAT)
    return bool(heartbeat) and utc_now() - parse_iso(heartbeat) < CRAWLER_OFFLINE_AFTER


@router.get("/crawl/status")
async def get_crawl_status(session: Session = Depends(get_session)):
    web = CrawledDocument.content_type != "course"
    return {
        **get_setting(CRAWL),
        "auto_crawl": get_setting(AUTO_CRAWL),
        "crawler_online": crawler_online(),
        "document_count": session.exec(select(func.count(func.distinct(CrawledDocument.url))).where(web)).one(),
        "total_chunks": session.exec(select(func.count(CrawledDocument.id))).one(),
        "course_count": session.exec(
            select(func.count(CrawledDocument.id)).where(CrawledDocument.content_type == "course")).one(),
        # Pages and courses (not chunks) of each kind, largest first
        "type_counts": dict(session.exec(
            select(CrawledDocument.content_type, func.count(func.distinct(CrawledDocument.url)))
            .group_by(CrawledDocument.content_type)
            .order_by(func.count(func.distinct(CrawledDocument.url)).desc())).all()),
    }


@router.post("/crawl/start")
async def start_crawl(request: CrawlRequest):
    """Ask the crawler service to crawl; it picks the request up within about 15 seconds"""
    state = get_setting(CRAWL)
    if state.get("status") == "running":
        raise HTTPException(status_code=409, detail="A crawl is already running")
    targets = [t for t in (request.targets or ["site", "courses"]) if t in ("site", "courses")]
    update_setting(CRAWL, requested_at=utc_iso(),
                   request_force=request.force, request_targets=targets or ["site", "courses"])
    return {"requested": True, "crawler_online": crawler_online()}


@router.put("/crawl/auto")
async def update_auto_crawl(update: AutoCrawlUpdate):
    if update.interval_hours < 1:
        raise HTTPException(status_code=400, detail="The interval must be at least 1 hour")
    set_setting(AUTO_CRAWL, {"enabled": update.enabled, "interval_hours": update.interval_hours})
    return get_setting(AUTO_CRAWL)


# ---- Data sources --------------------------------------------------------

@router.get("/data-sources")
async def get_data_sources(
    query: Optional[str] = None,
    source_type: Optional[str] = None,
    sort_by: str = Query("title", pattern="^(title|url|last_updated)$"),
    sort_order: str = Query("asc", pattern="^(asc|desc)$"),
    limit: int = Query(50, le=500),
    offset: int = 0,
    session: Session = Depends(get_session),
):
    """One entry per crawled page or course (its first chunk), searchable and sortable"""
    stmt = select(CrawledDocument).where(CrawledDocument.chunk_index == 0)
    if query:
        pattern = f"%{query}%"
        stmt = stmt.where(or_(CrawledDocument.title.ilike(pattern), CrawledDocument.content.ilike(pattern)))
    if source_type:
        stmt = stmt.where(CrawledDocument.content_type == source_type)
    column = {"title": CrawledDocument.title, "url": CrawledDocument.url, "last_updated": CrawledDocument.updated_at}[sort_by]
    stmt = stmt.order_by(column.desc() if sort_order == "desc" else column.asc()).offset(offset).limit(limit)
    return [
        {
            "id": doc.id,
            "title": doc.title,
            "url": doc.url,
            "content_preview": doc.content[:200] + ("..." if len(doc.content) > 200 else ""),
            "last_updated": doc.updated_at,
            "source_type": doc.content_type,
        }
        for doc in session.exec(stmt).all()
    ]


@router.get("/data-sources/{doc_id}")
async def get_data_source(doc_id: str, session: Session = Depends(get_session)):
    """A page's full stored text, reassembled from its chunks"""
    first = session.get(CrawledDocument, doc_id)
    if first is None:
        raise HTTPException(status_code=404, detail="Not found")
    chunks = session.exec(
        select(CrawledDocument).where(CrawledDocument.url == first.url).order_by(CrawledDocument.chunk_index)
    ).all()
    header = f"# {first.title}\n\n"
    parts = [c.content if c.chunk_index == 0 else c.content.removeprefix(header) for c in chunks]
    return {
        "id": first.id, "title": first.title, "url": first.url, "source_type": first.content_type,
        "last_updated": first.updated_at, "chunks": len(chunks),
        # Chunks overlap slightly, so a few sentences can repeat at the joins
        "full_content": "\n\n".join(parts),
    }


# ---- Conversations -------------------------------------------------------

@router.post("/clear-conversation-history")
async def clear_conversation_history(session: Session = Depends(get_session)):
    """Delete all conversations with their messages, feedback, evaluations and review marks.
    Traces stay: they hold timings and token counts, not what anyone asked."""
    for model in (ReviewMark, AnswerEvaluation, Feedback, Message, Conversation):  # children before parents
        session.exec(delete(model))
    session.commit()
    return {"message": "Conversation history cleared"}
