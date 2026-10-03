"""
Public status endpoints: liveness for Docker, and what the chat widget needs to know before it starts.
"""

from fastapi import APIRouter, Depends
from sqlmodel import Session, func, select

from auth import admin_token
from clock import utc_iso
from db import get_session
from llm import PROVIDERS, active_selection
from models import CrawledDocument

router = APIRouter(tags=["system"])


@router.get("/health")
async def health_check():
    return {"status": "ok", "timestamp": utc_iso()}


@router.get("/api/status")
async def status(session: Session = Depends(get_session)):
    """What the chat widget needs to know: is a provider set up (if not, it runs in demo mode), and is
    there content to search"""
    selection = active_selection()
    chunks = session.exec(select(func.count(CrawledDocument.id))).one()
    return {
        "provider_ready": selection is not None,
        "demo_mode": selection is None,
        "provider": selection and selection["provider"],
        "provider_label": selection and PROVIDERS[selection["provider"]]["label"],
        "model": selection and selection["model"],
        "indexed_chunks": chunks,
        "admin_token_required": bool(admin_token()),
    }
