"""
Demo mode: what the chat answers with before anyone adds an API key.

No AI is involved. Search runs as usual, and the answer quotes the most relevant passage from each
of the best-matching pages, linked to the page. It's free, works for anyone who clones the repo,
and never states anything the website doesn't. Adding a key (startup screen or Admin → Assistant)
switches the chat to AI-written answers.
"""

import re
from typing import Dict, List

from answering import SEARCH_RESULTS, Answer, page_title
from search import search_index

DEMO_SELECTION = {"provider": "demo", "model": "search-only"}
MAX_PAGES = 3
MAX_EXCERPT = 320  # characters quoted from each page

DEMO_NOTE = ("_Demo mode quotes Bradley's website instead of writing an answer. "
             "Add an API key from the start screen for full answers._")
EMPTY_INDEX = ("I couldn't find anything yet: Bradley's website is still being indexed. Progress is in the "
               "admin center under **Knowledge**.")

_STOPWORDS = set("""a an and are as at be bradley by can do does for from how i in is it me my of on or the
to what when where which who why will with you your university""".split())
_LINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")


def words(text: str) -> set:
    """Content words, with a plural or third-person 's' dropped so 'opens' matches 'open'"""
    found = (w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in _STOPWORDS and len(w) > 1)
    return {w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w for w in found}


def clean(markdown: str) -> str:
    """Markdown as plain text on one line: link text kept, headings, emphasis and table rules dropped"""
    text = _LINK.sub(r"\1", markdown)
    text = re.sub(r"^\s{0,3}(#{1,6}|[-*+]|\d+\.|>)\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"[*_`|]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def best_passage(content: str, title: str, question: str) -> str:
    """The paragraph that shares the most words with the question, shortened to MAX_EXCERPT"""
    content = content.removeprefix(f"# {title}\n\n")  # chunks after the first repeat the page title
    paragraphs = [clean(p) for p in re.split(r"\n\s*\n", content)]
    paragraphs = [p for p in paragraphs if len(p) >= 40 and p.lower() != title.lower()] or [clean(content)]
    wanted = words(question)
    passage = max(paragraphs, key=lambda p: len(words(p) & wanted))  # ties keep the earliest
    if len(passage) <= MAX_EXCERPT:
        return passage
    return passage[:MAX_EXCERPT].rsplit(" ", 1)[0].rstrip(",;:") + "…"


def compose(question: str, results: List[Dict]) -> tuple:
    """(answer text, sources) quoting the best-matching pages, one passage per page"""
    pages, seen = [], set()
    for r in results:
        if r["url"] and r["url"] not in seen:
            seen.add(r["url"])
            pages.append(r)
        if len(pages) == MAX_PAGES:
            break
    if not pages:
        return EMPTY_INDEX, []
    sources = [{"title": page_title(r), "url": r["url"]} for r in pages]
    quotes = [f"**[{s['title']}]({s['url']})**\n\n> {best_passage(r['content'], s['title'], question)}"
              for s, r in zip(sources, pages, strict=True)]
    return "Here's what Bradley's website says:\n\n" + "\n\n".join(quotes) + f"\n\n{DEMO_NOTE}", sources


async def demo_answer(question: str) -> Answer:
    results = await search_index.search(question, limit=SEARCH_RESULTS)  # empty only before anything is indexed
    text, sources = compose(question, results)
    return Answer(text=text, sources=sources, results=results, selection=DEMO_SELECTION)
