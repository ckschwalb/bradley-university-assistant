"""
Traces of every call to the AI provider (chat answers, quality judgements, prompt previews), and
the summaries the admin's Observability page builds from them.
"""

import logging
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Dict, Iterable, List, Optional

from sqlmodel import Session

from db import engine
from models import Trace

logger = logging.getLogger(__name__)


def record_trace(**fields) -> None:
    """Save one Trace. Never raises: losing a trace must not break the chat."""
    try:
        with Session(engine) as session:
            session.add(Trace(**fields))
            session.commit()
    except Exception as e:
        logger.warning(f"Couldn't record a {fields.get('kind')} trace: {type(e).__name__}: {e}")


def percentile(values: Iterable[Optional[float]], p: float) -> Optional[float]:
    """Nearest-rank percentile of the values that are present, or None if there are none"""
    present = sorted(v for v in values if v is not None)
    if not present:
        return None
    rank = max(1, -(-len(present) * p // 100))  # ceil(n * p / 100)
    return present[int(rank) - 1]


def mean(values: Iterable[Optional[float]]) -> Optional[float]:
    present = [v for v in values if v is not None]
    return round(sum(present) / len(present), 2) if present else None


def call_stats(traces: List[Trace]) -> Dict:
    """Volume, errors, latency and tokens for a group of calls"""
    ok = [t for t in traces if t.status == "ok"]
    errors = len(traces) - len(ok)
    return {
        "calls": len(traces),
        "errors": errors,
        "error_rate": round(errors / len(traces), 4) if traces else None,
        "p50_ms": percentile((t.total_ms for t in ok), 50),
        "p95_ms": percentile((t.total_ms for t in ok), 95),
        "p50_first_token_ms": percentile((t.first_token_ms for t in ok), 50),
        "p95_first_token_ms": percentile((t.first_token_ms for t in ok), 95),
        "p50_search_ms": percentile((t.search_ms for t in ok), 50),
        "input_tokens": sum(t.input_tokens or 0 for t in ok),
        "output_tokens": sum(t.output_tokens or 0 for t in ok),
        "avg_input_tokens": mean(t.input_tokens for t in ok),
        "avg_output_tokens": mean(t.output_tokens for t in ok),
        "median_top_score": percentile((t.top_score for t in ok), 50),
    }


def bucket_starts(since: datetime, until: datetime, hourly: bool, zone) -> List[datetime]:
    """The start of every hour (UTC) or calendar day (in `zone`) from `since` to `until`"""
    if hourly:
        start = since.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
        count = int((until - start) // timedelta(hours=1)) + 1
        return [start + timedelta(hours=i) for i in range(count)]
    first, last = since.astimezone(zone).date(), until.astimezone(zone).date()
    return [zone.localize(datetime.combine(first + timedelta(days=i), datetime.min.time()))
            for i in range((last - first).days + 1)]


def bucket_of(moment: datetime, hourly: bool, zone) -> datetime:
    if hourly:
        return moment.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
    return zone.localize(datetime.combine(moment.astimezone(zone).date(), datetime.min.time()))


def timeline(traces: List[Trace], groundedness: Dict[str, int], since: datetime, until: datetime,
             hourly: bool, zone) -> List[Dict]:
    """Chat answers per hour or day: how many, how many failed, how slow, and how grounded"""
    grouped = defaultdict(list)
    for t in traces:
        grouped[bucket_of(t.created_at, hourly, zone)].append(t)
    points = []
    for start in bucket_starts(since, until, hourly, zone):
        group = grouped.get(start, [])
        ok = [t for t in group if t.status == "ok"]
        points.append({
            "start": start.isoformat(),
            "answers": len(ok),
            "errors": len(group) - len(ok),
            "p95_ms": percentile((t.total_ms for t in ok), 95),
            "groundedness": mean(groundedness.get(t.message_id) for t in ok),
        })
    return points
