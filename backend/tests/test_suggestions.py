
import pytest
from sqlmodel import Session

import db
from models import CrawledDocument
from routers import suggestions
from routers.suggestions import FAQ_URL, MAX_LABEL, parse_faq, topic_label

FAQ_MD = """### On this Page

- [Admission](https://www.bradley.edu/college-faq/#admission)

## ****Admission and Scholarships****

### Do I have to take the ACT or SAT to apply to Bradley University?

No. Bradley is test-free.

### Does Bradley University accept external scholarships?

Yes.

## ****Academic Programs (Majors and Minors)****

### What is the average class size at Bradley University?

Small.

## Residence Halls

### How does roommate matching work at Bradley University?

A survey.

### This heading is not a question

Ignored.

## Student Life

### What is Greek life like at Bradley University?

Active.
"""


@pytest.fixture(autouse=True)
def clear_cache():
    suggestions._cache.update(version=None, topics={})


def index_faq(markdown=FAQ_MD, chunk_size=None):
    parts = [markdown] if not chunk_size else [markdown[i:i + chunk_size] for i in range(0, len(markdown), chunk_size)]
    with Session(db.engine) as session:
        for i, part in enumerate(parts):
            session.add(CrawledDocument(url=FAQ_URL, title="College Search FAQs", content=part,
                                        content_type="page", chunk_index=i,
                                        total_chunks=len(parts)))
        session.commit()


def test_parse_faq_groups_questions_under_short_topic_labels():
    assert parse_faq(FAQ_MD) == {
        "Admissions": ["Do I have to take the ACT or SAT to apply to Bradley University?",
                       "Does Bradley University accept external scholarships?"],
        "Academics": ["What is the average class size at Bradley University?"],
        "Residence halls": ["How does roommate matching work at Bradley University?"],
        "Student life": ["What is Greek life like at Bradley University?"],
    }


def test_parse_faq_drops_repeats_from_overlapping_chunks_and_overlong_questions():
    md = "## Topic\n\n### Short question?\n\n### Short question?\n\n### " + "Long " * 30 + "question?\n"
    assert parse_faq(md) == {"Topic": ["Short question?"]}


@pytest.mark.parametrize("heading", ["Student Life", "Costs, Aid and Everything Else About Money", "Health & Wellness Services Offered"])
def test_topic_labels_fit_on_a_pill(heading):
    assert 0 < len(topic_label(heading)) <= MAX_LABEL


def test_serves_three_questions_from_different_topics(client):
    index_faq()
    for _ in range(20):
        pills = client.get("/api/suggestions").json()
        assert len(pills) == 3
        assert len({p["label"] for p in pills}) == 3
        assert all(p["prompt"].endswith("?") for p in pills)


def test_suggestions_rotate_between_visits(client):
    index_faq()
    seen = {tuple(sorted(p["prompt"] for p in client.get("/api/suggestions").json())) for _ in range(40)}
    assert len(seen) > 1


def test_reads_the_page_across_chunks(client):
    index_faq(chunk_size=150)
    # Chunk boundaries can split a heading, but several topics survive intact
    assert len(client.get("/api/suggestions").json()) == 3


def test_falls_back_to_the_fixed_list_until_the_page_is_indexed(client):
    pills = client.get("/api/suggestions").json()
    assert [p["label"] for p in pills] == [s.label for s in suggestions.FALLBACK]
    assert all(len(p["label"]) <= MAX_LABEL for p in pills)


def test_picks_up_a_changed_page_after_a_crawl(client):
    index_faq()
    client.get("/api/suggestions")
    with Session(db.engine) as session:
        from sqlmodel import delete
        session.exec(delete(CrawledDocument))
        session.commit()
    index_faq(FAQ_MD.replace("Student Life", "Campus Life").replace("What is Greek life like", "What is campus life like"))
    topics = suggestions.faq_topics(Session(db.engine))
    assert "Campus Life" in topics
