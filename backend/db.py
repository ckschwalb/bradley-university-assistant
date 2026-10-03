"""
Database connection and session management
"""

import os
from datetime import UTC

from dotenv import load_dotenv
from sqlalchemy import event
from sqlalchemy.engine import make_url
from sqlmodel import Session, create_engine

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))

# Load environment variables from backend folder
load_dotenv(os.path.join(BACKEND_DIR, '.env'))

# One SQLite file holds everything: conversations, settings, and the crawled index.
# Docker sets DATABASE_URL to a file on the data volume; locally it defaults to backend/local.db.
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./local.db")

# Resolve a relative SQLite path against backend/ so the server, crawlers and scripts
# all use the same file no matter which directory they're started from
url = make_url(DATABASE_URL)
if url.drivername.startswith("sqlite") and url.database and url.database != ":memory:" \
        and not os.path.isabs(url.database):
    url = url.set(database=os.path.join(BACKEND_DIR, url.database))

# Create engine
engine = create_engine(url, echo=False)

if url.drivername.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _record):
        # WAL lets the web app read while the crawler service writes; busy_timeout waits for
        # the other process's write lock instead of failing; SQLite leaves foreign keys off by default
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

def get_session():
    """Get database session"""
    with Session(engine) as session:
        yield session

def init_db():
    """Bring an existing database up to date, then create any missing tables.
    The web app and crawler service both call this at startup."""
    from sqlalchemy.exc import OperationalError
    from sqlmodel import SQLModel

    import models  # noqa: F401  (registers the tables)
    if url.drivername.startswith("sqlite"):
        migrate_sqlite()
    try:
        SQLModel.metadata.create_all(engine)
    except OperationalError as e:
        # The other process created the same table between the existence check and CREATE
        if "already exists" not in str(e):
            raise
        SQLModel.metadata.create_all(engine)


# ---- Migrations -------------------------------------------------------------
# PRAGMA user_version records which of these a database has had. A new database starts at the
# latest version, since create_all builds the current schema.

SCHEMA_VERSION = 3

# Version 1 stores times in UTC; earlier versions stored naive Central (America/Chicago) times
_TIME_COLUMNS = {
    "conversations": ["started_at"],
    "messages": ["created_at"],
    "feedback": ["created_at"],
    "shares": ["created_at", "expires_at"],
    "crawled_documents": ["created_at", "updated_at"],
    "app_settings": ["updated_at"],
    "prompt_versions": ["created_at"],
    "review_marks": ["reviewed_at"],
}
# Columns no code reads or writes any more. Some are NOT NULL, so they must go before new rows can be added.
_DROPPED_COLUMNS = {
    "conversations": ["user_hash", "meta"],
    "feedback": ["client_meta"],
    "shares": ["is_flagged", "flag_reason", "flagged_at"],
    "crawled_documents": ["source", "chunk_id", "chunk_metadata"],
}
_SQLITE_TIME_FORMAT = "%Y-%m-%d %H:%M:%S.%f"  # how SQLAlchemy writes DateTime to SQLite


def _columns(cursor, table: str) -> set:
    return {row[1] for row in cursor.execute(f"PRAGMA table_info({table})")}


def _migrate_to_v1(cursor):
    from datetime import datetime

    from clock import CENTRAL

    tables = {row[0] for row in cursor.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    for table, columns in _TIME_COLUMNS.items():
        if table not in tables:
            continue
        present = _columns(cursor, table)
        for column in (c for c in columns if c in present):
            rows = cursor.execute(f"SELECT rowid, {column} FROM {table} WHERE {column} IS NOT NULL").fetchall()
            converted = []
            for rowid, value in rows:
                local = CENTRAL.localize(datetime.fromisoformat(value))
                converted.append((local.astimezone(UTC).strftime(_SQLITE_TIME_FORMAT), rowid))
            cursor.executemany(f"UPDATE {table} SET {column} = ? WHERE rowid = ?", converted)
    if "messages" in tables and "tool_calls" in _columns(cursor, "messages"):
        cursor.execute("ALTER TABLE messages RENAME COLUMN tool_calls TO details")
    for table, columns in _DROPPED_COLUMNS.items():
        if table in tables:
            for column in columns:
                if column in _columns(cursor, table):
                    cursor.execute(f"ALTER TABLE {table} DROP COLUMN {column}")
    if "review_marks" in tables:
        cursor.execute("DELETE FROM review_marks WHERE key LIKE 'share:%'")  # marks on user flags, now removed


def _migrate_to_v2(cursor):
    """Version 2 keeps one saved system prompt instead of a history of versions: the newest stays"""
    if cursor.execute("SELECT 1 FROM sqlite_master WHERE name = 'prompt_versions'").fetchone():
        cursor.execute("DELETE FROM prompt_versions WHERE id < (SELECT MAX(id) FROM prompt_versions)")
        cursor.execute("ALTER TABLE prompt_versions RENAME TO system_prompts")


def _migrate_to_v3(cursor):
    """Version 3 drops the shares table: conversations are no longer shared by link"""
    cursor.execute("DROP TABLE IF EXISTS shares")


_MIGRATIONS = {1: _migrate_to_v1, 2: _migrate_to_v2, 3: _migrate_to_v3}


def migrate_sqlite():
    """Apply the migrations this database hasn't had, inside one write transaction. BEGIN IMMEDIATE
    makes the app and crawler service take turns, so only one of them runs each migration."""
    raw = engine.raw_connection()
    connection = raw.driver_connection
    previous_isolation = connection.isolation_level
    connection.isolation_level = None  # manage the transaction here instead of in the driver
    cursor = connection.cursor()
    try:
        cursor.execute("BEGIN IMMEDIATE")
        try:
            version = cursor.execute("PRAGMA user_version").fetchone()[0]
            existing = cursor.execute("SELECT 1 FROM sqlite_master WHERE name = 'messages'").fetchone()
            if version < SCHEMA_VERSION:
                if existing:
                    for target in range(version + 1, SCHEMA_VERSION + 1):
                        _MIGRATIONS[target](cursor)
                cursor.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            cursor.execute("COMMIT")
        except Exception:
            cursor.execute("ROLLBACK")
            raise
    finally:
        cursor.close()
        connection.isolation_level = previous_isolation
        raw.close()
