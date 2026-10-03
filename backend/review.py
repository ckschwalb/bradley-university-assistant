"""
Spotting answers an admin should look at.

These are text checks, not judgments: they catch the patterns seen in real conversations
(the assistant saying it couldn't find something, linking to a Bradley page that was never
indexed, answering in vague terms without citing anything, or leaking a code fence into the
chat) so a person can decide. The quality judge's verdicts (evaluator.py) add the "Judge:" kinds.
"""

import re
from typing import Dict, List, Optional
from urllib.parse import urlsplit

# Markdown links and bare URLs in an answer
_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)|(?<![(\[])(https?://[^\s)\]>]+)")
_APOS = "['’]"
_NO_ANSWER = re.compile(
    rf"\b(couldn{_APOS}?t|could not|can{_APOS}?t|cannot|unable to|wasn{_APOS}?t able to|didn{_APOS}?t)"
    rf" (find|locate)\b|\bdon{_APOS}?t have (any )?(specific )?information\b|\bno information (about|on)\b",
    re.IGNORECASE,
)
# Wording that describes what something "typically" does instead of what a source says
_HEDGE = re.compile(r"\b(typically|usually|generally|often|probably|likely|tends? to)\b", re.IGNORECASE)

KINDS = {
    "no_answer": "No answer found",
    "unknown_link": "Link not in index",
    "unsupported": "No sources cited",
    "formatting": "Formatting",
    "ungrounded": "Judge: unsupported claims",
    "weak_answer": "Judge: weak answer",
    "rated_down": "Rated not helpful",
}


def cited_links(text: str) -> List[Dict[str, str]]:
    """Links in an answer, in order, without repeats"""
    links, seen = [], set()
    for label, url, bare in _LINK.findall(text):
        url = (url or bare).rstrip(".,;")
        if url and url not in seen and not url.startswith("mailto:"):
            seen.add(url)
            links.append({"label": label or url, "url": url})
    return links


def normalize_url(url: str, keep_fragment: bool = False) -> str:
    """A page address in the form used to compare links: no trailing slash, and by default no #fragment"""
    base, _, fragment = url.partition("#")
    base = base.rstrip("/")
    return f"{base}#{fragment}" if keep_fragment and fragment else base


def indexed_url_set(urls) -> set:
    """Indexed page addresses in the form unindexed_links() compares against"""
    return {normalize_url(u) for u in urls}


def unindexed_links(text: str, indexed: set) -> List[str]:
    """Bradley links in an answer that aren't in the index. Sources come only from the index, so
    these are usually made up (or the page was removed since)."""
    return [link["url"] for link in cited_links(text)
            if (urlsplit(link["url"]).hostname or "").endswith("bradley.edu")
            and normalize_url(link["url"]) not in indexed]


def answer_issues(text: str, indexed: Optional[set] = None, has_sources: bool = False) -> List[Dict[str, str]]:
    """What looks wrong with one assistant answer: [{kind, label, detail}].
    Pass `indexed` (from indexed_url_set) to also check the links it cites. `has_sources` says the
    answer was recorded as drawing on pages (see answering.split_used_line), which counts as cited
    even though the answer text itself no longer lists them."""
    issues = []
    no_answer = bool(_NO_ANSWER.search(text))
    if no_answer:
        issues.append({"kind": "no_answer", "detail":
                       "The assistant said it couldn't find this. Test the question under Knowledge to see "
                       "whether the information is indexed and what search returned instead."})
    unknown = unindexed_links(text, indexed) if indexed else []
    if unknown:
        issues.append({"kind": "unknown_link", "detail":
                       f"Links to {', '.join(unknown[:2])}, which isn't in the index. The assistant may have "
                       "made the address up; open it to check."})
    hedges = sorted({m.lower() for m in _HEDGE.findall(text)})
    if not no_answer and hedges and not cited_links(text) and not has_sources:
        quoted = ", ".join(f"“{h}”" for h in hedges[:3])
        issues.append({"kind": "unsupported", "detail":
                       f"Cites no sources and uses general wording ({quoted}). The details may not come "
                       "from Bradley's pages."})
    if "```" in text:
        issues.append({"kind": "formatting", "detail":
                       "Wraps part of the answer in a code block, so the chat shows raw markup instead of "
                       "formatted text."})
    for issue in issues:
        issue["label"] = KINDS[issue["kind"]]
    return issues
