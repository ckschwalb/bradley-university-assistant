"""
Suggestion pills for the chat widget: a short label to show, and the full request that
goes into the text box when someone picks it (they can edit it before sending).

The questions come from Bradley's own College Search FAQs page, read from the crawled index so
they stay current with each crawl. Each visit gets a different set, one question from each of
several topics. Until that page is indexed, a fixed list is served instead.
"""

import random
import re
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import Session, func, select

from db import get_session
from models import CrawledDocument

router = APIRouter(prefix="/api", tags=["suggestions"])

FAQ_URL = "https://www.bradley.edu/college-faq/"
PILLS_SHOWN = 3
MAX_LABEL = 20           # pills sit on one row, so labels stay short
MAX_QUESTION = 110       # longer questions wouldn't fit comfortably in the input box

# Short names for the FAQ page's topic headings; others are shortened automatically
TOPIC_LABELS = {
    "Admission and Scholarships": "Admissions",
    "Academic Programs": "Academics",
    "Residence Halls": "Residence halls",
    "Student Support Services": "Student support",
    "Student Life": "Student life",
}


class Suggestion(BaseModel):
    label: str   # fits on one row of pills, so keep it to a couple of words
    prompt: str  # a complete question that fits on about two lines of the input box


FALLBACK: List[Suggestion] = [
    Suggestion(label="Admissions",
               prompt="What are the admission requirements for first-year students, and how do I apply?"),
    Suggestion(label="Campus resources",
               prompt="What academic support and campus resources are available to students?"),
    Suggestion(label="Course offerings",
               prompt="What courses are offered in computer science, and what are their prerequisites?"),
]


def topic_label(heading: str) -> str:
    topic = re.sub(r"\s*\(.*?\)", "", heading.replace("*", "")).strip()
    if topic in TOPIC_LABELS:
        return TOPIC_LABELS[topic]
    if len(topic) <= MAX_LABEL:
        return topic
    words = topic.split()
    label = words[0]
    for word in words[1:]:
        if len(f"{label} {word}") > MAX_LABEL:
            break
        label = f"{label} {word}"
    return label.removesuffix(" and").removesuffix(" &")


def parse_faq(markdown: str) -> Dict[str, List[str]]:
    """Questions grouped by topic from a page laid out as "## Topic" with "### Question?" under it"""
    topics: Dict[str, List[str]] = {}
    topic: Optional[str] = None
    for line in markdown.splitlines():
        heading = re.match(r"^(#{2,3})\s+(.+?)\s*$", line)
        if not heading:
            continue
        level, text = len(heading.group(1)), heading.group(2).replace("*", "").strip()
        if level == 2:
            topic = topic_label(text)
        elif topic and text.endswith("?") and len(text) <= MAX_QUESTION:
            questions = topics.setdefault(topic, [])
            if text not in questions:  # chunks overlap, so a heading can appear twice
                questions.append(text)
    return topics


_cache: Dict[str, object] = {"version": None, "topics": {}}


def faq_topics(session: Session) -> Dict[str, List[str]]:
    """The FAQ page's questions by topic, re-read only when the crawler has changed the page"""
    page = CrawledDocument.url == FAQ_URL
    version = session.exec(select(func.count(CrawledDocument.id), func.max(CrawledDocument.updated_at))
                           .where(page)).one()
    if version != _cache["version"]:
        chunks = session.exec(select(CrawledDocument).where(page).order_by(CrawledDocument.chunk_index)).all()
        _cache.update(version=version, topics=parse_faq("\n\n".join(c.content for c in chunks)))
    return _cache["topics"]


def pick_suggestions(topics: Dict[str, List[str]], count: int = PILLS_SHOWN) -> List[Suggestion]:
    """One random question from each of `count` random topics, so the pills never repeat a topic"""
    chosen = random.sample(sorted(topics), min(count, len(topics)))
    return [Suggestion(label=topic, prompt=random.choice(topics[topic])) for topic in chosen]


@router.get("/suggestions", response_model=List[Suggestion])
async def get_suggestions(session: Session = Depends(get_session)):
    topics = faq_topics(session)
    return pick_suggestions(topics) if len(topics) >= PILLS_SHOWN else FALLBACK
