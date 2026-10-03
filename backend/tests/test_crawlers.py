from datetime import UTC, datetime, timedelta

from course_catalog_crawler import CourseCatalogCrawler
from crawler_service import due_trigger
from sitemap_crawler import html_to_markdown


def test_html_to_markdown_drops_noise_and_keeps_structure():
    md = html_to_markdown("<nav>Menu</nav><h2>Admissions</h2><script>x()</script>"
                          "<ul><li>Apply</li></ul><img src='a.png' alt='Campus'>")
    assert "Menu" not in md and "x()" not in md
    assert "## Admissions" in md and "- Apply" in md and "Campus" in md


def test_html_to_markdown_handles_empty_input():
    assert html_to_markdown("") == ""


def test_prerequisite_course_codes_are_extracted():
    crawler = CourseCatalogCrawler()
    assert crawler.extract_prerequisite_courses("CS 101 and MTH 109, or permission") == ["CS 101", "MTH 109"]
    assert crawler.extract_prerequisite_courses("") == []


def test_due_trigger_manual_request_wins():
    assert due_trigger({"requested_at": "now"}, {"enabled": False}) == "manual"


def test_due_trigger_schedule():
    auto = {"enabled": True, "interval_hours": 24}
    assert due_trigger({}, auto) == "schedule"  # never crawled
    recent = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    old = (datetime.now(UTC) - timedelta(hours=25)).isoformat()
    assert due_trigger({"finished_at": recent}, auto) is None
    assert due_trigger({"finished_at": old}, auto) == "schedule"
    assert due_trigger({"finished_at": old}, {"enabled": False}) is None
