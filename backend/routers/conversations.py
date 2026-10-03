"""
Admin API for reading what people asked and how the assistant answered: the overview,
conversation transcripts, the Needs review list, search testing and prompt previews.

The text checks behind Needs review run over every stored message on each request. That's
milliseconds at the size of a local install; add a column for the results if it ever isn't.
The quality judge's verdicts (evaluator.py) are stored, and low scores join the list too.
"""

import asyncio
import time
from collections import defaultdict
from datetime import timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import delete, or_
from sqlmodel import Session, func, select

from answering import SEARCH_RESULTS, describe_provider_error, generate, retrieved_pages
from auth import require_admin
from clock import utc_now
from db import get_session
from evaluator import GROUNDED, WEAK, evaluation_view
from llm import ProviderNotConfigured, active_selection
from models import AnswerEvaluation, Conversation, CrawledDocument, Feedback, Message, ReviewMark
from observability import record_trace
from review import KINDS, answer_issues, cited_links, indexed_url_set
from search import search_index

LIST_LIMIT = 200
FILTERS = ("all", "review", "rated")

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])


class ReviewResolve(BaseModel):
    key: str


class SearchTest(BaseModel):
    query: str


class PromptPreview(BaseModel):
    content: str
    question: str


# ---- Building blocks -----------------------------------------------------

def indexed_urls(session: Session) -> set:
    return indexed_url_set(session.exec(select(CrawledDocument.url).distinct()).all())


def reviewed_keys(session: Session) -> set:
    return set(session.exec(select(ReviewMark.key)).all())


def turns_of(messages: List[Message]) -> List[dict]:
    """Pair each question with the answer that followed it"""
    turns = []
    for m in messages:
        if m.role == "user" or not turns or turns[-1]["answer"] is not None:
            turns.append({"question": None, "answer": None})
        turns[-1]["question" if m.role == "user" else "answer"] = m
    return turns


def judge_issues(evaluation: Optional[AnswerEvaluation]) -> List[dict]:
    """Needs review items from the quality judge's verdict on one answer"""
    if evaluation is None:
        return []
    issues = []
    if evaluation.groundedness < GROUNDED:
        claims = "; ".join(f"“{c}”" for c in evaluation.unsupported_claims[:2])
        issues.append({"kind": "ungrounded", "detail": f"The quality judge scored groundedness "
                       f"{evaluation.groundedness}/5. " + (f"Not in the sources: {claims}" if claims else evaluation.rationale)})
    if min(evaluation.relevance, evaluation.completeness) <= WEAK:
        issues.append({"kind": "weak_answer", "detail": f"The quality judge scored relevance {evaluation.relevance}/5 "
                       f"and completeness {evaluation.completeness}/5. {evaluation.rationale}"})
    for issue in issues:
        issue["label"] = KINDS[issue["kind"]]
    return issues


def review_items(messages: List[Message], feedback: List[Feedback], evaluations: dict, done: set,
                 indexed: set) -> List[dict]:
    """Open Needs review items for one conversation, oldest first"""
    items = []
    question_for = {}
    for turn in turns_of(messages):
        answer = turn["answer"]
        if answer is None:
            continue
        question = turn["question"].content if turn["question"] else None
        question_for[answer.id] = question
        issues = answer_issues(answer.content, indexed, has_sources=bool(used_pages(answer)))
        for issue in issues + judge_issues(evaluations.get(answer.id)):
            items.append({**issue, "key": f"{answer.id}:{issue['kind']}", "message_id": answer.id,
                          "question": question, "at": answer.created_at})
    for fb in feedback:
        if fb.rating == -1:
            items.append({"kind": "rated_down", "label": KINDS["rated_down"], "key": f"feedback:{fb.id}",
                          "detail": f"Comment: “{fb.comment}”" if fb.comment else "No comment left.",
                          "message_id": fb.message_id, "question": question_for.get(fb.message_id),
                          "at": fb.created_at})
    for item in items:
        item["conversation_id"] = messages[0].conversation_id if messages else None
    return [i for i in items if i["key"] not in done]


def load_related(session: Session, conversation_ids: List[str]) -> tuple:
    """Messages and feedback for these conversations, grouped by conversation id, and the
    judge's evaluations of their answers by message id (the latest one, if an answer has several)"""
    messages, feedback, evaluations = defaultdict(list), defaultdict(list), {}
    if not conversation_ids:
        return messages, feedback, evaluations
    for m in session.exec(select(Message).where(Message.conversation_id.in_(conversation_ids))
                          .order_by(Message.created_at)).all():
        messages[m.conversation_id].append(m)
    for fb in session.exec(select(Feedback).where(Feedback.conversation_id.in_(conversation_ids))).all():
        feedback[fb.conversation_id].append(fb)
    answer_ids = select(Message.id).where(Message.conversation_id.in_(conversation_ids))
    for e in session.exec(select(AnswerEvaluation).where(AnswerEvaluation.message_id.in_(answer_ids))
                          .order_by(AnswerEvaluation.id)).all():
        evaluations[e.message_id] = e
    return messages, feedback, evaluations

def model_of(message: Message) -> Optional[str]:
    return (message.details or {}).get("model")


def used_pages(message: Message) -> Optional[List[dict]]:
    """The pages recorded as used for an answer, or None for answers saved before that was recorded"""
    return (message.details or {}).get("sources")


# ---- Overview ------------------------------------------------------------

@router.get("/overview")
async def overview(session: Session = Depends(get_session)):
    conversations = session.exec(select(Conversation)).all()
    ids = [c.id for c in conversations]
    messages, feedback, evaluations = load_related(session, ids)
    done, indexed = reviewed_keys(session), indexed_urls(session)

    review = []
    for cid in ids:
        review.extend(review_items(messages[cid], feedback[cid], evaluations, done, indexed))
    review.sort(key=lambda i: i["at"], reverse=True)

    questions = session.exec(select(Message).where(Message.role == "user")
                             .order_by(Message.created_at.desc()).limit(10)).all()
    week_ago = utc_now() - timedelta(days=7)
    all_feedback = [fb for fbs in feedback.values() for fb in fbs]
    judged_this_week = [e for e in evaluations.values() if e.created_at >= week_ago]
    return {
        "conversations": len(conversations),
        "conversations_this_week": sum(1 for c in conversations if c.started_at >= week_ago),
        "first_conversation_at": min((c.started_at for c in conversations), default=None),
        "questions": session.exec(select(func.count(Message.id)).where(Message.role == "user")).one(),
        "follow_up_conversations": sum(1 for cid in ids if sum(m.role == "user" for m in messages[cid]) > 1),
        "ratings_up": sum(fb.rating == 1 for fb in all_feedback),
        "ratings_down": sum(fb.rating == -1 for fb in all_feedback),
        "judged_this_week": len(judged_this_week),
        "grounded_this_week": sum(e.groundedness >= GROUNDED for e in judged_this_week),
        "review": review[:20],
        "review_total": len(review),
        "recent_questions": [{"text": m.content, "at": m.created_at, "conversation_id": m.conversation_id}
                             for m in questions],
    }


# ---- Conversations -------------------------------------------------------

def summarize(conversation: Conversation, messages: List[Message], feedback: List[Feedback],
              evaluations: dict, done: set, indexed: set) -> dict:
    questions = [m for m in messages if m.role == "user"]
    open_items = review_items(messages, feedback, evaluations, done, indexed)
    kinds = list(dict.fromkeys(i["kind"] for i in open_items))
    return {
        "id": conversation.id,
        "started_at": conversation.started_at,
        "last_at": messages[-1].created_at if messages else conversation.started_at,
        "title": questions[0].content if questions else "(no questions)",
        "questions": len(questions),
        "models": list(dict.fromkeys(filter(None, (model_of(m) for m in messages)))),
        "tags": [{"kind": k, "label": KINDS[k]} for k in kinds],
        "ratings_up": sum(fb.rating == 1 for fb in feedback),
        "ratings_down": sum(fb.rating == -1 for fb in feedback),
    }


def matches(summary: dict, filter_name: str) -> bool:
    return {
        "all": True,
        "review": bool(summary["tags"]),
        "rated": summary["ratings_up"] + summary["ratings_down"] > 0,
    }[filter_name]


@router.get("/conversations")
async def list_conversations(
    filter: str = Query("all", pattern=f"^({'|'.join(FILTERS)})$"),
    q: Optional[str] = None,
    session: Session = Depends(get_session),
):
    """Conversations, most recently active first, with counts for each filter"""
    stmt = select(Conversation)
    if q and q.strip():
        hits = select(Message.conversation_id).where(Message.content.ilike(f"%{q.strip()}%"))
        stmt = stmt.where(Conversation.id.in_(hits))
    conversations = session.exec(stmt).all()
    messages, feedback, evaluations = load_related(session, [c.id for c in conversations])
    done, indexed = reviewed_keys(session), indexed_urls(session)
    summaries = [summarize(c, messages[c.id], feedback[c.id], evaluations, done, indexed)
                 for c in conversations]
    summaries.sort(key=lambda s: s["last_at"], reverse=True)
    return {
        "counts": {f: sum(matches(s, f) for s in summaries) for f in FILTERS},
        "conversations": [s for s in summaries if matches(s, filter)][:LIST_LIMIT],
    }


@router.get("/conversations/{conversation_id}")
async def get_conversation(conversation_id: str, session: Session = Depends(get_session)):
    """The full transcript, with sources, ratings, the judge's scores and open review items on each answer"""
    conversation = session.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    grouped_messages, grouped_feedback, evaluations = load_related(session, [conversation_id])
    messages, feedback = grouped_messages[conversation_id], grouped_feedback[conversation_id]
    done, indexed = reviewed_keys(session), indexed_urls(session)
    items = review_items(messages, feedback, evaluations, done, indexed)
    items_by_message = defaultdict(list)
    for item in items:
        items_by_message[item["message_id"]].append(item)
    feedback_by_message = defaultdict(list)
    for fb in feedback:
        feedback_by_message[fb.message_id].append({"rating": fb.rating, "comment": fb.comment, "at": fb.created_at})

    turns = []
    for turn in turns_of(messages):
        q, a = turn["question"], turn["answer"]
        turns.append({
            "question": q and {"id": q.id, "text": q.content, "at": q.created_at},
            "answer": a and {
                "id": a.id, "text": a.content, "at": a.created_at,
                "provider": (a.details or {}).get("provider"), "model": model_of(a),
                "cited": ([{"label": s["title"], "url": s["url"]} for s in used_pages(a)]
                          if used_pages(a) is not None else cited_links(a.content)),
                "retrieved": (a.details or {}).get("retrieved"),  # answers saved before this was recorded have none
                "search_query": (a.details or {}).get("search_query"),  # set when a follow-up was restated for search
                "evaluation": evaluation_view(evaluations.get(a.id)),
                "review": items_by_message.get(a.id, []),
                "feedback": feedback_by_message.get(a.id, []),
            },
        })

    return {**summarize(conversation, messages, feedback, evaluations, done, indexed), "turns": turns}


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str, session: Session = Depends(get_session)):
    if session.get(Conversation, conversation_id) is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    # Review marks are keyed by message and feedback ids (see review_items)
    message_ids = list(session.exec(select(Message.id).where(Message.conversation_id == conversation_id)))
    prefixes = [f"{i}:" for i in message_ids]
    prefixes += [f"feedback:{i}" for i in session.exec(select(Feedback.id).where(Feedback.conversation_id == conversation_id))]
    if prefixes:
        session.exec(delete(ReviewMark).where(or_(*(ReviewMark.key.startswith(p) for p in prefixes))))
    if message_ids:
        session.exec(delete(AnswerEvaluation).where(AnswerEvaluation.message_id.in_(message_ids)))
    for model in (Feedback, Message):  # children before the conversation
        session.exec(delete(model).where(model.conversation_id == conversation_id))
    session.exec(delete(Conversation).where(Conversation.id == conversation_id))
    session.commit()
    return {"deleted": True}


@router.post("/review/resolve")
async def resolve_review_item(body: ReviewResolve, session: Session = Depends(get_session)):
    """Take an item off the Needs review list"""
    if session.get(ReviewMark, body.key) is None:
        session.add(ReviewMark(key=body.key))
        session.commit()
    return {"key": body.key}


# ---- Knowledge and prompt testing ----------------------------------------

@router.post("/search-test")
async def search_test(body: SearchTest, session: Session = Depends(get_session)):
    """Exactly what search would hand the assistant for this question, without calling the AI"""
    results = await search_index.search(body.query, limit=SEARCH_RESULTS)
    urls = list({r["url"] for r in results})
    first_chunks = dict(session.exec(
        select(CrawledDocument.url, CrawledDocument.id)
        .where(CrawledDocument.url.in_(urls)).where(CrawledDocument.chunk_index == 0)
    ).all()) if urls else {}
    return [{"title": r["title"], "url": r["url"], "type": r["content_type"], "score": round(r["score"], 3),
             "doc_id": first_chunks.get(r["url"])} for r in results]


@router.post("/system-prompt/preview")
async def preview_prompt(body: PromptPreview):
    """Answer one question with a draft prompt and with the active one, side by side. Nothing is saved."""
    if not body.content.strip() or not body.question.strip():
        raise HTTPException(status_code=400, detail="Enter a question and a prompt to preview")
    selection = active_selection()
    if selection is None:
        raise HTTPException(status_code=400, detail="Set up an AI provider first")
    results = await search_index.search(body.question, limit=SEARCH_RESULTS)
    trace = {"kind": "preview", "provider": selection["provider"], "model": selection["model"]}
    start = time.perf_counter()
    try:
        draft, active = await asyncio.gather(
            generate(body.question, [], template=body.content, results=results),
            generate(body.question, [], results=results),
        )
    except ProviderNotConfigured:
        raise HTTPException(status_code=400, detail="Set up an AI provider first") from None
    except Exception as e:
        record_trace(**trace, status="error", error=f"{type(e).__name__}: {e}"[:500],
                     total_ms=round((time.perf_counter() - start) * 1000))
        raise HTTPException(status_code=502, detail=describe_provider_error(selection["provider"], e)) from e
    for answer in (draft, active):
        record_trace(**trace, status="ok", **answer.metrics)
    return {"draft": draft.text, "active": active.text, "model": draft.selection["model"],
            "sources": retrieved_pages(results)}
