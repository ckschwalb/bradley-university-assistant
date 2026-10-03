"""
The chat endpoint: answers a question from the conversation so far and the most relevant crawled content.
"""

import json
import logging
import time
from typing import AsyncIterator, List, Optional

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import BaseModel, Field
from sqlmodel import Session, select
from starlette.background import BackgroundTask

from answering import Answer, answer_stream, describe_provider_error
from db import engine
from demo import demo_answer
from evaluator import evaluate_and_store
from llm import ProviderNotConfigured, active_selection
from models import Conversation, Message
from observability import record_trace

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])

HISTORY_MESSAGES = 10  # previous messages (5 exchanges) sent with each question
MAX_MESSAGE_CHARS = 1000  # a question, not an essay; the widget's input enforces the same limit


class ChatMessage(BaseModel):
    message: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)
    conversation_id: Optional[str] = None


def load_history(session: Session, conversation_id: str) -> List:
    """The conversation's most recent messages as LangChain messages, oldest first"""
    rows = session.exec(
        select(Message).where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.desc()).limit(HISTORY_MESSAGES)
    ).all()
    return [HumanMessage(content=m.content) if m.role == "user" else AIMessage(content=m.content)
            for m in reversed(rows)]


def event(kind: str, **fields) -> bytes:
    return (json.dumps({"type": kind, **fields}) + "\n").encode()


def finished(response: str, **fields) -> bytes:
    """The last event of every reply: the final text and what the widget needs to show it"""
    defaults = {"sources": [], "conversation_id": None, "user_message_id": None, "assistant_message_id": None,
                "provider": None, "model": None, "demo": False, "error": False}
    return event("done", **{**defaults, "response": response, **fields})


def save_turn(conversation: Optional[Conversation], question: str, text: str, answer: Answer) -> dict:
    """Store the question and its answer (starting a conversation if this is the first turn) and
    return the ids the widget needs"""
    selection = answer.selection
    with Session(engine) as session:
        saved = session.get(Conversation, conversation.id) if conversation else None
        if saved is None:
            saved = Conversation()
            session.add(saved)
        user_message = Message(conversation_id=saved.id, role="user", content=question)
        assistant_message = Message(conversation_id=saved.id, role="assistant", content=text, details={
            "provider": selection["provider"], "model": selection["model"],
            # What search handed the model, and which pages the answer used,
            # so the admin can show them later
            "sources": answer.sources,
            "search_query": answer.search_query,
            "retrieved": [{"title": r["title"], "url": r["url"], "score": round(r["score"], 3)}
                          for r in answer.results],
        })
        session.add(user_message)
        session.add(assistant_message)
        session.commit()
        return {"conversation_id": saved.id, "user_message_id": user_message.id,
                "assistant_message_id": assistant_message.id}


@router.post("/chat")
async def chat(message: ChatMessage):
    """Answer a question from the conversation so far and the most relevant crawled content.

    The reply streams as newline-delimited JSON: {"type": "delta", "text"} pieces as the model writes
    them, then one {"type": "done", ...} with the final text, sources and saved message ids (or an
    error). The turn is saved only once the answer is complete, and the quality judge grades it
    after the response has been sent. With no provider set up, the chat runs in demo mode
    (demo.py): it quotes the best-matching pages instead, with `demo: true` on the final event.
    """
    with Session(engine) as session:
        conversation = session.get(Conversation, message.conversation_id) if message.conversation_id else None
        history = load_history(session, conversation.id) if conversation else []
    judged = {}  # filled in once the answer is saved, for the judge that runs after the response

    async def reply() -> AsyncIterator[bytes]:
        selection = active_selection()
        answer = None
        if selection is not None:
            trace = {"kind": "chat", "provider": selection["provider"], "model": selection["model"],
                     "conversation_id": conversation and conversation.id}
            start = time.perf_counter()
            try:
                async for item in answer_stream(message.message, history):
                    if isinstance(item, Answer):
                        answer = item
                    else:
                        yield event("delta", text=item)
            except ProviderNotConfigured:
                pass  # the key was removed while this request was starting: answer in demo mode
            except Exception as e:
                # Nothing is saved, so a failed turn doesn't end up in the conversation history
                logger.warning(f"{selection['provider']} request failed: {type(e).__name__}: {e}")
                record_trace(**trace, status="error", error=f"{type(e).__name__}: {e}"[:500],
                             total_ms=round((time.perf_counter() - start) * 1000))
                yield finished(describe_provider_error(selection["provider"], e), error=True,
                               provider=selection["provider"], model=selection["model"])
                return
        demo = answer is None
        if demo:
            answer = await demo_answer(message.message)
            yield event("delta", text=answer.text)

        selection = answer.selection
        text = answer.text if answer.text.strip() else \
            "I'm sorry, I couldn't generate a response. Please try rephrasing your question."
        ids = save_turn(conversation, message.message, text, answer)

        if not demo:  # demo answers make no provider call to trace or judge
            record_trace(**{**trace, "conversation_id": ids["conversation_id"]},
                         message_id=ids["assistant_message_id"], status="ok", **answer.metrics)
            if answer.text.strip():
                judged.update(answer=answer, message_id=ids["assistant_message_id"],
                              conversation_id=ids["conversation_id"])
        yield finished(text, sources=answer.sources, provider=selection["provider"], model=selection["model"],
                       demo=demo, **ids)

    async def judge_answer():
        if judged:
            await evaluate_and_store(judged["message_id"], judged["conversation_id"], message.message,
                                     history, judged["answer"])

    return StreamingResponse(reply(), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
                             background=BackgroundTask(judge_answer))
