"""
The quality judge: a second model call that grades each answer against the sources it was given.

It scores three things from 1 to 5 and lists any claims the sources don't support:
  groundedness  every fact about Bradley comes from the sources (the main hallucination check)
  relevance     the answer addresses what was asked
  completeness  the answer says everything the sources allow, and admits what they don't cover

The chat endpoint runs it in the background after each answer (see main.py), and evaluate.py runs
it over a fixed question set. Low scores put the answer on the admin's Needs review list. A judge
is a model too, so its scores are a prompt to look, not ground truth; it's more reliable when the
judge model is at least as capable as the one that wrote the answer.
"""

import logging
import time
from typing import Dict, List, Optional

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field
from sqlmodel import Session

from answering import Answer, format_context
from clock import campus_now
from db import engine
from llm import ProviderNotConfigured, get_judge_model
from models import AnswerEvaluation
from observability import record_trace

logger = logging.getLogger(__name__)

GROUNDED = 4  # a groundedness score below this puts the answer on the Needs review list
UNSUPPORTED_CAP = GROUNDED - 1  # so an answer with a listed unsupported claim always lands there
WEAK = 2      # so does a relevance or completeness score at or below this
HISTORY_MESSAGES = 4  # earlier messages shown to the judge, so it can read follow-up questions
MAX_CLAIMS = 5

JUDGE_INSTRUCTIONS = """You grade answers written by an AI assistant that answers questions about \
Bradley University. With each question the assistant receives numbered excerpts from Bradley's website \
and course catalog, and it must take every fact about Bradley from those excerpts and nothing else.

Score the answer on three scales from 1 (worst) to 5 (best).

groundedness: are the answer's factual claims supported by the sources?
  5 every claim about Bradley (names, titles, contact details, dates, costs, requirements, policies, \
locations, hours) is stated in the sources
  4 all key claims are supported; a minor detail is a reasonable paraphrase or inference
  3 one claim is not in the sources, but it isn't central to the answer
  2 a central claim is not in the sources
  1 most claims are not in the sources, or the answer contradicts them
  Saying the information couldn't be found is grounded. General guidance with no Bradley-specific facts \
(such as "contact the office") is not a claim. A claim that is true in general but not in the sources \
is still unsupported.

relevance: does the answer address what the user asked? Use the earlier conversation to resolve \
follow-up questions such as "what about their email?".
  5 directly answers the question  3 partly on topic  1 doesn't address the question

completeness: given what the sources contain, does the answer say everything they allow?
  5 nothing relevant in the sources is left out, and anything they don't cover is acknowledged
  3 leaves out a relevant detail the sources contain
  1 says it couldn't find something the sources plainly contain, or leaves out the main point
  If the sources don't answer the question and the answer says so, that is complete.

If you list any unsupported claim, groundedness can be at most 3.

List each unsupported claim, quoting or closely paraphrasing the answer (at most 5; an empty list if \
there are none), and give a one- or two-sentence rationale for the scores."""


class Verdict(BaseModel):
    groundedness: int = Field(description="1 to 5: are the answer's factual claims supported by the sources?")
    relevance: int = Field(description="1 to 5: does the answer address what the user asked?")
    completeness: int = Field(description="1 to 5: does the answer say everything the sources allow?")
    unsupported_claims: List[str] = Field(description="Claims in the answer the sources don't support; empty if none")
    rationale: str = Field(description="One or two sentences explaining the scores")


def _clamp(score) -> int:
    return min(5, max(1, int(score)))


def _transcript(history: List[BaseMessage]) -> str:
    lines = [f"{'User' if isinstance(m, HumanMessage) else 'Assistant'}: {m.content}"
             for m in history[-HISTORY_MESSAGES:]]
    return "\n\n".join(lines) or "(none: this is the first question)"


def judge_messages(question: str, history: List[BaseMessage], answer: Answer) -> List[BaseMessage]:
    used = ", ".join(str(i) for i, r in enumerate(answer.results, 1)
                     if any(s["url"] == r["url"] for s in answer.sources)) or "none"
    return [
        SystemMessage(JUDGE_INSTRUCTIONS),
        HumanMessage(
            f"Today's date: {campus_now().strftime('%B %d, %Y')}\n\n"
            f"Earlier conversation:\n{_transcript(history)}\n\n"
            f"Question: {question}\n\n"
            f"Sources the assistant was given:\n<sources>\n{format_context(answer.results) or '(none)'}\n</sources>\n\n"
            f"Answer to grade:\n<answer>\n{answer.text}\n</answer>\n\n"
            f"Sources the assistant says it used: {used}"
        ),
    ]


async def judge(question: str, history: List[BaseMessage], answer: Answer) -> tuple:
    """(Verdict, judge selection, metrics). Raises ProviderNotConfigured when the judge is off,
    and the provider's exception (or a parsing error) when grading fails."""
    llm, selection = get_judge_model()
    start = time.perf_counter()
    result = await llm.with_structured_output(Verdict, include_raw=True).ainvoke(
        judge_messages(question, history, answer))
    if result.get("parsed") is None:
        raise ValueError(f"The judge's reply couldn't be read: {result.get('parsing_error')}")
    verdict: Verdict = result["parsed"]
    claims = verdict.unsupported_claims[:MAX_CLAIMS]
    groundedness = _clamp(verdict.groundedness)
    if claims:  # the judge is lenient about its own findings, so a claim it lists caps the score
        groundedness = min(groundedness, UNSUPPORTED_CAP)
    verdict = verdict.model_copy(update={
        "groundedness": groundedness, "relevance": _clamp(verdict.relevance),
        "completeness": _clamp(verdict.completeness), "unsupported_claims": claims,
    })
    usage = getattr(result.get("raw"), "usage_metadata", None) or {}
    metrics = {"total_ms": round((time.perf_counter() - start) * 1000),
               "input_tokens": usage.get("input_tokens"), "output_tokens": usage.get("output_tokens")}
    return verdict, selection, metrics


async def evaluate_and_store(message_id: str, conversation_id: Optional[str], question: str,
                             history: List[BaseMessage], answer: Answer) -> Optional[AnswerEvaluation]:
    """Judge a saved answer and store the verdict. Never raises: a failed judgement is recorded as
    an error trace, and the chat is unaffected."""
    trace: Dict = {"kind": "judge", "conversation_id": conversation_id, "message_id": message_id}
    try:
        verdict, selection, metrics = await judge(question, history, answer)
    except ProviderNotConfigured:
        return None  # the judge is switched off
    except Exception as e:
        logger.warning(f"Judging answer {message_id} failed: {type(e).__name__}: {e}")
        record_trace(**trace, status="error", error=f"{type(e).__name__}: {e}"[:500])
        return None

    record_trace(**trace, status="ok", provider=selection["provider"], model=selection["model"], **metrics)
    evaluation = AnswerEvaluation(message_id=message_id, provider=selection["provider"], model=selection["model"],
                                  **verdict.model_dump())
    try:
        with Session(engine) as session:
            session.add(evaluation)
            session.commit()
            session.refresh(evaluation)
    except Exception as e:  # e.g. the conversation was deleted while the judge was working
        logger.warning(f"Couldn't save the evaluation of answer {message_id}: {type(e).__name__}: {e}")
        return None
    return evaluation


def evaluation_view(evaluation: Optional[AnswerEvaluation]) -> Optional[dict]:
    if evaluation is None:
        return None
    return {"groundedness": evaluation.groundedness, "relevance": evaluation.relevance,
            "completeness": evaluation.completeness, "unsupported_claims": evaluation.unsupported_claims,
            "rationale": evaluation.rationale, "model": evaluation.model, "at": evaluation.created_at}
