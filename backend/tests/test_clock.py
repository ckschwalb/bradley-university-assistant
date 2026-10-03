from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlmodel import Session, select

import db
from clock import CENTRAL, parse_iso, utc_iso, utc_now
from models import Conversation, Message
from system_prompt import render


def test_utc_now_is_aware_and_utc_iso_round_trips():
    assert utc_now().utcoffset().total_seconds() == 0
    assert abs((utc_now() - datetime.fromisoformat(utc_iso())).total_seconds()) < 5


def test_settings_times_with_any_offset_compare_correctly():
    central = datetime.now(CENTRAL).isoformat()  # written by earlier versions
    assert abs((utc_now() - parse_iso(central)).total_seconds()) < 5
    assert parse_iso("2026-01-15T18:00:00").tzinfo is not None  # no offset: read as UTC


def test_prompt_date_uses_the_campus_calendar_not_the_server_clock():
    # 02:30 UTC on March 4 is still the evening of March 3 in Peoria
    utc_evening = datetime(2026, 3, 4, 2, 30, tzinfo=UTC)
    text_ = render("{current_date_info[current_day]} {current_date_info[current_date]} {context}", "",
                   now=utc_evening.astimezone(CENTRAL))
    assert text_ == "Tuesday March 03, 2026 "


def test_times_are_stored_in_utc_and_read_back_aware():
    with Session(db.engine) as session:
        session.add(Conversation(id="c", started_at=CENTRAL.localize(datetime(2026, 7, 15, 12, 0))))
        session.commit()
        stored = session.exec(text("SELECT started_at FROM conversations")).one()[0]
        loaded = session.exec(select(Conversation)).one().started_at
    assert stored.startswith("2026-07-15 17:00:00")  # noon CDT is 17:00 UTC
    assert loaded == datetime(2026, 7, 15, 17, 0, tzinfo=UTC)


def test_naive_times_are_refused():
    with Session(db.engine) as session:
        session.add(Conversation(id="c", started_at=datetime(2026, 1, 1)))
        with pytest.raises(Exception, match="Naive datetime"):
            session.commit()


def test_migration_moves_an_old_database_to_utc_and_the_current_columns():
    with db.engine.begin() as conn:
        for table in ("answer_evaluations", "review_marks", "feedback", "shares", "messages", "conversations",
                      "crawled_documents"):
            conn.execute(text(f"DROP TABLE IF EXISTS {table}"))
        conn.execute(text("PRAGMA user_version = 0"))
        conn.execute(text("CREATE TABLE conversations (id VARCHAR PRIMARY KEY, started_at DATETIME NOT NULL, "
                          "user_hash VARCHAR, meta JSON)"))
        conn.execute(text("CREATE TABLE messages (id VARCHAR PRIMARY KEY, conversation_id VARCHAR, role VARCHAR, "
                          "content VARCHAR, created_at DATETIME NOT NULL, tool_calls JSON)"))
        conn.execute(text("CREATE TABLE shares (id VARCHAR PRIMARY KEY, conversation_id VARCHAR, token VARCHAR, "
                          "created_at DATETIME NOT NULL, expires_at DATETIME, is_flagged BOOLEAN NOT NULL, "
                          "flag_reason VARCHAR, flagged_at DATETIME)"))
        conn.execute(text("CREATE TABLE review_marks (key VARCHAR PRIMARY KEY, reviewed_at DATETIME NOT NULL)"))
        conn.execute(text("DROP TABLE IF EXISTS system_prompts"))
        conn.execute(text("CREATE TABLE prompt_versions (id INTEGER PRIMARY KEY, content VARCHAR NOT NULL, "
                          "created_at DATETIME NOT NULL)"))
        conn.execute(text("INSERT INTO prompt_versions VALUES (1, 'old', '2026-01-15 12:00:00.000000'), "
                          "(2, 'newest', '2026-01-16 12:00:00.000000')"))
        conn.execute(text("INSERT INTO conversations VALUES ('c', '2026-01-15 12:00:00.000000', NULL, NULL)"))
        conn.execute(text("INSERT INTO messages VALUES ('m', 'c', 'assistant', 'Hi', '2026-07-15 12:00:00.000000', "
                          "'{\"model\": \"x\"}')"))
        conn.execute(text("INSERT INTO review_marks VALUES ('share:1', '2026-01-15 12:00:00.000000'), "
                          "('m:no_answer', '2026-01-15 12:00:00.000000')"))

    db.init_db()
    db.init_db()  # a second start (or the other service) must not shift the times again

    with Session(db.engine) as session:
        conversation = session.get(Conversation, "c")
        message = session.get(Message, "m")
        marks = session.exec(text("SELECT key FROM review_marks")).all()
        tables = {row[0] for row in session.exec(text("SELECT name FROM sqlite_master WHERE type = 'table'"))}
        version = session.exec(text("PRAGMA user_version")).one()[0]
    assert conversation.started_at == datetime(2026, 1, 15, 18, 0, tzinfo=UTC)  # CST is UTC-6
    assert message.created_at == datetime(2026, 7, 15, 17, 0, tzinfo=UTC)       # CDT is UTC-5
    assert message.details == {"model": "x"}
    assert [m[0] for m in marks] == ["m:no_answer"]
    assert "shares" not in tables and version == db.SCHEMA_VERSION  # share links were removed
    import system_prompt
    assert system_prompt.active_prompt() == "newest"  # prompt versions became the one saved prompt
