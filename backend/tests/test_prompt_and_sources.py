from datetime import datetime

import pytest

from answering import cited_sources, format_context, retrieved_pages, showable_prefix, split_used_line
from demo import best_passage, clean
from observability import percentile
from system_prompt import render


def test_render_fills_date_placeholders_and_context():
    now = datetime(2026, 3, 4, 15, 30)
    text = render("Today is {current_date_info[current_day]}, {current_date_info[current_date]}.\n{context}",
                  "CONTEXT", now=now)
    assert text == "Today is Wednesday, March 04, 2026.\nCONTEXT"


def test_render_appends_context_when_template_has_no_placeholder():
    assert render("Be helpful.", "CONTEXT").endswith("Use the following context to answer the question:\nCONTEXT")


def test_retrieved_pages_dedupes_urls_strips_section_suffix_and_caps_at_three():
    results = [{"title": f"Page {i} (Section 1 of 2)", "url": f"https://x.com/{i % 4}"} for i in range(10)]
    pages = retrieved_pages(results)
    assert [s["url"] for s in pages] == ["https://x.com/0", "https://x.com/1", "https://x.com/2"]
    assert pages[0]["title"] == "Page 0"


RESULTS = [
    {"title": "College Search FAQs (Section 2 of 7)", "url": "https://www.bradley.edu/college-faq/"},
    {"title": "Student Handbook", "url": "https://www.bradley.edu/handbook/"},
    {"title": "Housing", "url": "https://www.bradley.edu/housing/"},
    {"title": "CS 100 - Intro", "url": "https://catalog.bradley.edu/cs/#CS_100"},
    {"title": "CS 360 - Algorithms", "url": "https://catalog.bradley.edu/cs/#CS_360"},
]


def test_only_pages_the_answer_links_to_are_sources():
    answer = "Two years.\n\nSources: [College Search FAQs](https://www.bradley.edu/college-faq/)"
    assert cited_sources(RESULTS, answer) == [
        {"title": "College Search FAQs", "url": "https://www.bradley.edu/college-faq/"}]


def test_no_links_means_no_sources():
    assert cited_sources(RESULTS, "I couldn't find that information.") == []


def test_links_to_pages_search_did_not_return_are_not_sources():
    answer = "See [Apply](https://apply.bradley.edu/apply/) and [Made up](https://www.bradley.edu/invented/)."
    assert cited_sources(RESULTS, answer) == []


def test_sources_follow_the_order_cited_and_ignore_slash_and_repeats():
    answer = "[Housing](https://www.bradley.edu/housing) then [FAQ](https://www.bradley.edu/college-faq/) and [Housing again](https://www.bradley.edu/housing/)."
    assert [s["title"] for s in cited_sources(RESULTS, answer)] == ["Housing", "College Search FAQs"]


def test_a_fragment_link_matches_its_own_chunk_and_a_page_link_matches_the_page():
    exact = cited_sources(RESULTS, "[CS 360](https://catalog.bradley.edu/cs/#CS_360)")
    assert exact == [{"title": "CS 360 - Algorithms", "url": "https://catalog.bradley.edu/cs/#CS_360"}]
    page = cited_sources(RESULTS, "[All CS courses](https://catalog.bradley.edu/cs/)")
    assert page == [{"title": "All CS courses", "url": "https://catalog.bradley.edu/cs/"}]


def test_a_page_link_is_dropped_when_specific_parts_of_that_page_are_also_cited():
    answer = ("[CS 100](https://catalog.bradley.edu/cs/#CS_100), [CS 360](https://catalog.bradley.edu/cs/#CS_360) "
              "Sources: [Course Descriptions - CS](https://catalog.bradley.edu/cs/)")
    assert [s["url"] for s in cited_sources(RESULTS, answer)] == [
        "https://catalog.bradley.edu/cs/#CS_100", "https://catalog.bradley.edu/cs/#CS_360"]


def test_format_context_numbers_results():
    out = format_context([{"title": "A", "url": "u1", "content": "c1"}, {"title": "B", "url": "u2", "content": "c2"}])
    assert out.startswith("[1] A\nURL: u1\nc1") and "[2] B" in out


USED_RESULTS = [
    {"title": "College Search FAQs (Section 2 of 7)", "url": "https://www.bradley.edu/college-faq/"},
    {"title": "Student Handbook", "url": "https://www.bradley.edu/handbook/"},
    {"title": "College Search FAQs (Section 3 of 7)", "url": "https://www.bradley.edu/college-faq/"},
    {"title": "Housing", "url": "https://www.bradley.edu/housing/"},
]


def test_used_line_is_removed_and_mapped_to_the_pages_search_returned():
    text, sources = split_used_line("Two years.\n\nUsed: 1, 4", USED_RESULTS)
    assert text == "Two years."
    assert sources == [{"title": "College Search FAQs", "url": "https://www.bradley.edu/college-faq/"},
                       {"title": "Housing", "url": "https://www.bradley.edu/housing/"}]


@pytest.mark.parametrize("line", ["Used: 2", "**Used:** 2", "`Used: 2`", "used: [2]", "Used: 2 "])
def test_used_line_tolerates_formatting(line):
    text, sources = split_used_line(f"Answer.\n\n{line}", USED_RESULTS)
    assert text == "Answer." and [s["title"] for s in sources] == ["Student Handbook"]


def test_used_none_means_no_sources():
    assert split_used_line("I couldn't find that.\n\nUsed: none", USED_RESULTS) == ("I couldn't find that.", [])


def test_two_excerpts_from_one_page_are_one_source_and_bad_numbers_are_ignored():
    _, sources = split_used_line("Answer.\nUsed: 1, 3, 9, 0", USED_RESULTS)
    assert [s["url"] for s in sources] == ["https://www.bradley.edu/college-faq/"]


def test_no_used_line_leaves_the_answer_alone_and_reports_unknown():
    assert split_used_line("Answer with no line.", USED_RESULTS) == ("Answer with no line.", None)
    # "used" inside the answer isn't mistaken for the line
    assert split_used_line("Used: 1 is mentioned mid-answer.\nMore text.", USED_RESULTS)[1] is None


@pytest.mark.parametrize("line, pages", [
    ("Used: 1, 4", ["College Search FAQs", "Housing"]),
    ("Used: 1 and 4", ["College Search FAQs", "Housing"]),
    ("Used: 1 & 4", ["College Search FAQs", "Housing"]),
    ("Used: [2], [4]", ["Student Handbook", "Housing"]),
    ("Used: 2, and 4.", ["Student Handbook", "Housing"]),
])
def test_used_line_accepts_the_usual_separators(line, pages):
    text, sources = split_used_line(f"Answer.\n\n{line}", USED_RESULTS)
    assert text == "Answer." and [s["title"] for s in sources] == pages


@pytest.mark.parametrize("line", ["Used: and", "Used: dad", "Used: n/a", "Used:\n1\n2"])
def test_used_line_is_only_numbers_or_none(line):
    # The old pattern's character class matched the letters a, n and d, and line breaks
    raw = f"Answer.\n\n{line}"
    assert split_used_line(raw, USED_RESULTS) == (raw.strip(), None)


@pytest.mark.parametrize("raw, shown", [
    ("Two years", "Two years"),
    ("Two years.\n", "Two years.\n"),
    ("Two years.\n\nU", "Two years.\n\n"),
    ("Two years.\n\n**Use", "Two years.\n\n"),
    ("Two years.\n\nUsed: 1", "Two years.\n\n"),
    ("Two years.\n\nUsually", "Two years.\n\nUsually"),
    ("Used textbooks\nare sold at the bookstore", "Used textbooks\nare sold at the bookstore"),
])
def test_streaming_holds_back_only_a_possible_used_line(raw, shown):
    assert showable_prefix(raw) == shown


def test_percentile_uses_nearest_rank_and_ignores_missing_values():
    values = [100, None, 300, 200, 400]
    assert (percentile(values, 50), percentile(values, 95), percentile([], 50)) == (200, 400, None)


def test_demo_passages_are_plain_text_from_the_paragraph_that_matches_the_question():
    assert clean("## Hours\n- **Mon**: [Library](https://x.edu/lib) opens at *8*") == "Hours Mon : Library opens at 8"
    content = "# Library\n\nThe library has three floors and study rooms.\n\nOn Saturdays the library opens at 10 a.m. and closes at 6 p.m."
    assert best_passage(content, "Library", "When does the library open on Saturday?").startswith("On Saturdays")
    long = "Word " * 200
    passage = best_passage(long, "T", "word")
    assert passage.endswith("…") and len(passage) <= 321
