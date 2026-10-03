"""
Turning a question into an answer: search the index, build the prompt, call the chat model.

Shared by the chat endpoint (main.py), the admin prompt preview (routers/conversations.py) and
the answer-quality evaluation (evaluate.py).
"""

import logging
import re
import time
from dataclasses import dataclass, field
from typing import AsyncIterator, Dict, List, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

import system_prompt
from llm import PROVIDERS, get_chat_model
from review import cited_links, normalize_url
from search import search_index

logger = logging.getLogger(__name__)

SEARCH_RESULTS = 5
REWRITE_HISTORY_MESSAGES = 4  # recent messages the query rewriter sees (2 exchanges)
MAX_QUERY_CHARS = 200
REWRITE_MESSAGE_CHARS = 300  # each earlier message is cut to this, enough to name its subject
MAX_PREVIEW_SOURCES = 3

CHAT_PROMPT = ChatPromptTemplate.from_messages([
    ("system", "{system}"),
    MessagesPlaceholder("history"),
    ("human", "{question}"),
])


REWRITE_INSTRUCTIONS = """You turn the latest message of a conversation with a Bradley University assistant \
into a short standalone search query for Bradley's website and course catalog.

Only resolve references to the earlier conversation ("she", "that program", "what about the cost?") by \
naming the person, program, office or topic they refer to. Take nothing else from the earlier conversation: \
don't copy details, lists, course names, numbers or contact information from the assistant's earlier \
answers into the query. Keep every specific detail from the latest message itself (course codes, names, \
years). If the latest message already makes sense on its own, return it unchanged.

Aim for a few words: the subject plus what is being asked, such as "Angelica Perdue courses taught". \
Reply with the query only: one line, no quotes, no explanation, and do not answer the question."""


def _text(message) -> str:
    return message.text if isinstance(message.text, str) else ""


def _shortened(text: str) -> str:
    return text if len(text) <= REWRITE_MESSAGE_CHARS else text[:REWRITE_MESSAGE_CHARS].rstrip() + "…"


async def rewrite_query(llm, question: str, history: List) -> tuple:
    """(standalone search query, token usage). Follow-ups like "what about their email?" mean nothing
    to a search index, so with earlier messages the model restates the question on its own terms.
    Falls back to the question as asked if the rewrite fails or comes back empty."""
    usage = {"input_tokens": 0, "output_tokens": 0}
    if not history:
        return question, usage
    transcript = "\n\n".join(
        f"{'User' if isinstance(m, HumanMessage) else 'Assistant'}: {_shortened(m.content)}"
        for m in history[-REWRITE_HISTORY_MESSAGES:])
    try:
        reply = await llm.ainvoke([
            SystemMessage(REWRITE_INSTRUCTIONS),
            HumanMessage(f"Earlier conversation:\n{transcript}\n\nLatest message: {question}"),
        ])
    except Exception as e:  # the answer can still be written from the question as asked
        logger.warning(f"Rewriting the search query failed: {type(e).__name__}: {e}")
        return question, usage
    for key in usage:
        usage[key] = (getattr(reply, "usage_metadata", None) or {}).get(key) or 0
    lines = [line.strip().strip('"') for line in _text(reply).splitlines() if line.strip()]
    query = lines[0][:MAX_QUERY_CHARS] if lines else ""
    return query or question, usage


def format_context(results: List[Dict]) -> str:
    return "\n\n".join(f"[{i}] {r['title']}\nURL: {r['url']}\n{r['content']}" for i, r in enumerate(results, 1))


def page_title(result: Dict) -> str:
    return result["title"].split(" (Section ")[0]


def retrieved_pages(results: List[Dict]) -> List[Dict[str, str]]:
    """The pages search handed the model, whether or not it used them (for the prompt preview)"""
    sources, seen = [], set()
    for r in results:
        if r["url"] and r["url"] not in seen:
            seen.add(r["url"])
            sources.append({"title": page_title(r), "url": r["url"]})
        if len(sources) == MAX_PREVIEW_SOURCES:
            break
    return sources


def cited_sources(results: List[Dict], answer: str) -> List[Dict[str, str]]:
    """The retrieved pages the answer links to, in the order it links them: the pages it actually used.
    Links to anything search didn't return (an address the model made up, or one that was only
    mentioned inside a page) aren't sources. A link without a #fragment stands for its whole page,
    and is dropped when the answer also links specific parts of that page."""
    sources, seen = [], set()
    page_level = []  # (index into sources, page address) for links that stand for a whole page
    for link in cited_links(answer):
        url = link["url"]
        exact = next((r for r in results if r["url"]
                      and normalize_url(r["url"], keep_fragment=True) == normalize_url(url, keep_fragment=True)), None)
        if exact is not None:
            source = {"title": page_title(exact), "url": exact["url"]}
        elif "#" not in url and any(r["url"] and normalize_url(r["url"]) == normalize_url(url) for r in results):
            source = {"title": link["label"], "url": url}  # no single excerpt names the whole page
            page_level.append((len(sources), normalize_url(url)))
        else:
            continue
        if source["url"] not in seen:
            seen.add(source["url"])
            sources.append(source)
    specific_pages = {normalize_url(s["url"]) for s in sources if "#" in s["url"]}
    drop = {i for i, page in page_level if page in specific_pages}
    return [s for i, s in enumerate(sources) if i not in drop]


def describe_provider_error(provider: str, error: Exception) -> str:
    label = PROVIDERS.get(provider, {}).get("label", provider)
    status = getattr(error, "status_code", None) or getattr(error, "code", None)
    if status in (401, 403):
        problem = "rejected the API key"
    elif status == 404:
        problem = "doesn't recognize the selected model"
    elif status == 429:
        problem = "is rate limiting requests or the account is out of credit"
    else:
        problem = f"returned an error ({type(error).__name__})"
    return (f"{label} {problem}. Open the admin dashboard (/admin → Assistant) to check the key "
            f"and model, then try again.")


# The closing "Used: 1, 3" line the system prompt asks for (see systemprompt.txt, rule 7): "none", or
# source numbers (optionally [bracketed]) separated by commas, "and" or "&", with optional markdown emphasis
_NUMBER = r"\[?\d+\]?"
_SEPARATOR = r"[ \t]*,?[ \t]*(?:(?:and|&)[ \t]*)?"
_USED_LINE = re.compile(
    rf"(?:\n|^)[ \t]*[`*]*Used:?[`*]*[ \t]*(none|{_NUMBER}(?:{_SEPARATOR}{_NUMBER})*)[ \t]*[`*]*[ \t.]*\Z",
    re.IGNORECASE,
)


def split_used_line(raw: str, results: List[Dict]) -> tuple:
    """(answer without its closing Used line, the pages that line names).

    The numbers refer to the sources the model was shown, so they map straight back to the pages
    search returned. Returns None for the pages when there's no such line (an older or edited prompt
    may not ask for one); the caller then falls back to the links in the answer.
    """
    match = _USED_LINE.search(raw)
    if match is None:
        return raw.strip(), None
    sources, seen = [], set()
    for number in re.findall(r"\d+", match.group(1)):
        index = int(number) - 1
        if 0 <= index < len(results) and results[index]["url"] and results[index]["url"] not in seen:
            seen.add(results[index]["url"])
            sources.append({"title": page_title(results[index]), "url": results[index]["url"]})
    return raw[:match.start()].strip(), sources


def showable_prefix(raw: str) -> str:
    """The part of a reply still being written that's safe to show: everything except a last line
    that is, or may become, the closing Used line, so the line never flashes up while streaming."""
    line_start = raw.rfind("\n") + 1
    last_line = raw[line_start:].lstrip(" \t`*").lower()
    if last_line.startswith("used") or "used".startswith(last_line):
        return raw[:line_start]
    return raw


@dataclass
class Answer:
    text: str                      # as the user sees it
    sources: List[Dict[str, str]]  # the pages it used, linking to bradley.edu
    results: List[Dict]            # everything search returned
    selection: Dict[str, str]
    search_query: Optional[str] = None  # what was searched, when it differs from the question (follow-ups)
    metrics: Dict[str, Optional[float]] = field(default_factory=dict)  # see Trace in models.py


def _elapsed_ms(start: float) -> int:
    return round((time.perf_counter() - start) * 1000)


async def answer_stream(question: str, history: List, template: Optional[str] = None,
                        results: Optional[List[Dict]] = None) -> AsyncIterator[str | Answer]:
    """Answer one question, yielding text as the model writes it and then the finished Answer.

    The streamed pieces are for display; the Answer's text is the final version (closing Used
    line removed). Raises ProviderNotConfigured when no provider is set up, and the provider's own
    exception when the request fails. `template` defaults to the active system prompt.
    """
    start = time.perf_counter()
    llm, selection = get_chat_model()
    usage = {"input_tokens": 0, "output_tokens": 0}
    search_query = question
    if results is None:
        search_query, rewrite_usage = await rewrite_query(llm, question, history)
        for key in usage:
            usage[key] += rewrite_usage[key]
        results = await search_index.search(search_query, limit=SEARCH_RESULTS)
    search_ms = _elapsed_ms(start)
    prompt = CHAT_PROMPT.invoke({
        "system": system_prompt.render(template or system_prompt.active_prompt(), format_context(results)),
        "history": history,
        "question": question,
    })

    raw, shown, first_token_ms = "", 0, None
    async for chunk in llm.astream(prompt):
        for key in usage:  # providers report usage on one or more chunks; the totals are the sum
            usage[key] += (getattr(chunk, "usage_metadata", None) or {}).get(key) or 0
        piece = chunk.text if isinstance(chunk.text, str) else ""
        if not piece:
            continue
        if first_token_ms is None:
            first_token_ms = _elapsed_ms(start)
        raw += piece
        visible = showable_prefix(raw)
        if len(visible) > shown:
            yield visible[shown:]
            shown = len(visible)

    text, sources = split_used_line(raw, results)
    if sources is None:
        sources = cited_sources(results, text)
    yield Answer(text=text, sources=sources, results=results, selection=selection,
                 search_query=search_query if search_query != question else None, metrics={
        "search_ms": search_ms, "first_token_ms": first_token_ms, "total_ms": _elapsed_ms(start),
        "input_tokens": usage["input_tokens"] or None, "output_tokens": usage["output_tokens"] or None,
        "top_score": round(results[0]["score"], 3) if results else None,
    })


async def generate(question: str, history: List, template: Optional[str] = None,
                   results: Optional[List[Dict]] = None) -> Answer:
    """Answer one question without streaming (prompt previews and evaluate.py)"""
    async for item in answer_stream(question, history, template=template, results=results):
        if isinstance(item, Answer):
            return item
    raise RuntimeError("The answer stream ended without an answer")
