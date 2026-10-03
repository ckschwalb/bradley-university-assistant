#!/usr/bin/env python3
"""
Crawler service: keeps the website and course catalog index up to date.

Runs as its own process (its own container under Docker Compose). It crawls when someone
presses Start crawl in the admin dashboard, and on a schedule when auto-crawl is enabled.
Both settings live in the database, so the dashboard and this service stay in sync.

    python crawler_service.py                 # run the service
    python crawler_service.py --once [--force] # crawl once now and exit
"""

import argparse
import asyncio
import logging
from datetime import timedelta
from typing import List, Optional

from clock import parse_iso, utc_iso, utc_now
from db import init_db
from settings_store import AUTO_CRAWL, CRAWL, CRAWLER_HEARTBEAT, get_setting, set_setting, update_setting

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("crawler_service")

POLL_SECONDS = 15
TARGETS = ["site", "courses"]


def due_trigger(state: dict, auto: dict) -> Optional[str]:
    """Why a crawl should start now: 'manual', 'schedule', or None"""
    if state.get("requested_at"):
        return "manual"
    if auto.get("enabled"):
        finished = state.get("finished_at")
        if not finished:
            return "schedule"  # never crawled: build the index on first start
        interval = timedelta(hours=float(auto.get("interval_hours") or 24))
        if utc_now() - parse_iso(finished) >= interval:
            return "schedule"
    return None


async def heartbeat_forever():
    while True:
        set_setting(CRAWLER_HEARTBEAT, utc_iso())
        await asyncio.sleep(POLL_SECONDS)


async def run_crawl(trigger: str, force: bool, targets: List[str]):
    # Imported here so the embedding model only loads when a crawl actually runs
    from course_catalog_crawler import CourseCatalogCrawler
    from sitemap_crawler import SitemapCrawler

    logger.info(f"Crawl starting (trigger={trigger}, force={force}, targets={targets})")
    update_setting(CRAWL, status="running", trigger=trigger, force=force, targets=targets,
                   started_at=utc_iso(), requested_at=None, progress=None, error=None)
    results, errors = {}, []
    for target in targets:
        update_setting(CRAWL, progress=target)
        try:
            if target == "site":
                results[target] = await SitemapCrawler().crawl_all_content(force=force)
            elif target == "courses":
                results[target] = await CourseCatalogCrawler().crawl_all_courses(force=force)
            if "error" in results[target]:
                errors.append(f"{target}: {results[target]['error']}")
        except Exception as e:
            logger.exception(f"{target} crawl failed")
            errors.append(f"{target}: {e}")
    update_setting(CRAWL, status="idle", progress=None, finished_at=utc_iso(),
                   last_result=results, error="; ".join(errors) or None)
    logger.info(f"Crawl finished: {results}{' errors: ' + '; '.join(errors) if errors else ''}")


async def serve():
    init_db()
    if get_setting(CRAWL).get("status") == "running":
        # The previous process stopped mid-crawl; unfinished items are picked up next run
        update_setting(CRAWL, status="idle", progress=None, error="Previous crawl was interrupted")

    heartbeat = asyncio.create_task(heartbeat_forever())
    logger.info("Crawler service started")
    try:
        while True:
            state, auto = get_setting(CRAWL), get_setting(AUTO_CRAWL)
            trigger = due_trigger(state, auto)
            if trigger:
                force = bool(state.get("request_force")) if trigger == "manual" else False
                targets = (state.get("request_targets") or TARGETS) if trigger == "manual" else TARGETS
                update_setting(CRAWL, request_force=False, request_targets=None)
                await run_crawl(trigger, force, targets)
            await asyncio.sleep(POLL_SECONDS)
    finally:
        heartbeat.cancel()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--once", action="store_true", help="Crawl once now and exit")
    parser.add_argument("--force", action="store_true", help="With --once: re-fetch and re-embed everything")
    args = parser.parse_args()
    if args.once:
        init_db()
        asyncio.run(run_crawl("manual", args.force, TARGETS))
    else:
        asyncio.run(serve())


if __name__ == "__main__":
    main()
