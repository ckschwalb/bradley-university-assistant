"""
Admin API for the Observability page: how the AI calls behind the chat are performing (volume,
errors, latency, tokens) and how good the answers are according to the quality judge.
"""

from collections import defaultdict
from datetime import timedelta
from typing import Optional

import pytz
from fastapi import APIRouter, Depends, Query
from sqlmodel import Session, select

from auth import require_admin
from clock import utc_now
from db import get_session
from evaluator import GROUNDED, WEAK
from models import AnswerEvaluation, Conversation, Trace
from observability import call_stats, mean, timeline

router = APIRouter(prefix="/api/admin", tags=["observability"], dependencies=[Depends(require_admin)])

RECENT_LIMIT = 50


def time_zone(name: Optional[str]):
    try:
        return pytz.timezone(name) if name else pytz.utc
    except pytz.UnknownTimeZoneError:
        return pytz.utc


@router.get("/observability")
async def observability(
    hours: int = Query(24 * 7, ge=1, le=24 * 90),
    tz: Optional[str] = Query(None, description="The viewer's IANA time zone, for grouping by day"),
    session: Session = Depends(get_session),
):
    until = utc_now()
    since = until - timedelta(hours=hours)
    traces = session.exec(select(Trace).where(Trace.created_at >= since).order_by(Trace.created_at.desc())).all()
    evaluations = session.exec(select(AnswerEvaluation).where(AnswerEvaluation.created_at >= since)).all()
    by_message = {e.message_id: e for e in evaluations}
    groundedness = {e.message_id: e.groundedness for e in evaluations}
    chat = [t for t in traces if t.kind == "chat"]

    models = defaultdict(list)
    for t in chat:
        models[(t.provider, t.model)].append(t)

    live_conversations = set(session.exec(
        select(Conversation.id).where(Conversation.id.in_({t.conversation_id for t in traces[:RECENT_LIMIT]
                                                           if t.conversation_id}))).all())

    return {
        "since": since,
        "until": until,
        "chat": call_stats(chat),
        "judge": call_stats([t for t in traces if t.kind == "judge"]),
        "preview": call_stats([t for t in traces if t.kind == "preview"]),
        "quality": {
            "judged": len(evaluations),
            "groundedness": mean(e.groundedness for e in evaluations),
            "relevance": mean(e.relevance for e in evaluations),
            "completeness": mean(e.completeness for e in evaluations),
            "grounded_share": (round(sum(e.groundedness >= GROUNDED for e in evaluations) / len(evaluations), 4)
                               if evaluations else None),
            "flagged": sum(e.groundedness < GROUNDED or min(e.relevance, e.completeness) <= WEAK for e in evaluations),
            "threshold": GROUNDED,
        },
        "timeline": timeline(chat, groundedness, since, until, hourly=hours <= 48, zone=time_zone(tz)),
        "hourly": hours <= 48,
        "models": sorted(
            ({"provider": provider, "model": model, **call_stats(group),
              "groundedness": mean(groundedness.get(t.message_id) for t in group)}
             for (provider, model), group in models.items()),
            key=lambda m: m["calls"], reverse=True,
        ),
        "recent": [
            {
                "id": t.id, "at": t.created_at, "kind": t.kind, "status": t.status, "provider": t.provider,
                "model": t.model, "error": t.error, "search_ms": t.search_ms, "first_token_ms": t.first_token_ms,
                "total_ms": t.total_ms, "input_tokens": t.input_tokens, "output_tokens": t.output_tokens,
                "top_score": t.top_score, "message_id": t.message_id,
                "conversation_id": t.conversation_id if t.conversation_id in live_conversations else None,
                "groundedness": by_message[t.message_id].groundedness if t.message_id in by_message else None,
            }
            for t in traces[:RECENT_LIMIT]
        ],
    }
