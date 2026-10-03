#!/usr/bin/env python3
"""
Database maintenance: export conversation history to JSON, and reset the database.

Uses the same database as the app (DATABASE_URL, default backend/local.db).
Under Docker: docker compose exec app python manage_db.py export

    python manage_db.py export              # write conversations/messages/feedback to backups/
    python manage_db.py reset --yes         # export, then drop and recreate every table (empty database)
    python manage_db.py reset --yes --skip-export
"""

import argparse
import json
import os
import sys

from sqlalchemy import MetaData, inspect, select, text
from sqlmodel import SQLModel

import models  # noqa: F401  (registers the tables on SQLModel.metadata)
from clock import utc_iso, utc_now
from db import engine

# Docker sets BACKUP_DIR to a folder on the data volume; locally exports go to <repo>/backups
BACKUP_DIR = os.getenv("BACKUP_DIR") or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backups")
CONVERSATION_TABLES = ["conversations", "messages", "feedback"]
# Tables left over from earlier versions of the app that a reset should also remove
LEGACY_TABLES = ["alembic_version", "shares"]


def describe_target() -> str:
    """Database location without credentials, for logs and file names."""
    url = engine.url
    if url.drivername.startswith("sqlite"):
        return f"sqlite:{url.database}"
    host = f"{url.host}:{url.port}" if url.port else (url.host or "localhost")
    return f"{url.drivername}://{host}/{url.database}"


def read_table_rows(conn, table_name: str) -> list:
    """Read every row of a table using its actual columns, so older schemas export too."""
    existing = inspect(conn).get_table_names()
    if table_name not in existing:
        return []
    table = MetaData()
    table.reflect(bind=conn, only=[table_name])
    return [dict(row._mapping) for row in conn.execute(select(table.tables[table_name]))]


def export_conversations() -> tuple:
    """Write all conversation data, nested per conversation, to a timestamped JSON file."""
    with engine.connect() as conn:
        rows = {name: read_table_rows(conn, name) for name in CONVERSATION_TABLES}

    by_conversation = {name: {} for name in ("messages", "feedback")}
    for name, grouped in by_conversation.items():
        for row in rows[name]:
            grouped.setdefault(row["conversation_id"], []).append(row)

    conversations = []
    known_ids = {conv["id"] for conv in rows["conversations"]}
    for conv in sorted(rows["conversations"], key=lambda c: str(c["started_at"])):
        conversations.append({
            **conv,
            "messages": sorted(by_conversation["messages"].get(conv["id"], []), key=lambda m: str(m["created_at"])),
            "feedback": by_conversation["feedback"].get(conv["id"], []),
        })

    # SQLite doesn't enforce foreign keys, so keep rows whose conversation no longer exists
    orphaned = {
        name: [row for conv_id, group in grouped.items() if conv_id not in known_ids for row in group]
        for name, grouped in by_conversation.items()
    }

    counts = {name: len(rows[name]) for name in CONVERSATION_TABLES}
    export = {
        "exported_at": utc_iso(),
        "source": describe_target(),
        "counts": counts,
        "conversations": conversations,
        "orphaned": orphaned,
    }

    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = utc_now().strftime("%Y%m%d-%H%M%S-%fZ")
    if engine.url.drivername.startswith("sqlite"):
        source_label = os.path.splitext(os.path.basename(engine.url.database))[0]
    else:
        source_label = engine.url.host or "db"
    path = os.path.join(BACKUP_DIR, f"conversations-{source_label}-{stamp}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(export, f, indent=2, default=str, ensure_ascii=False)

    # Read the file back so a reset never proceeds on a partial or unreadable export
    with open(path, encoding="utf-8") as f:
        written = json.load(f)
    for name in ("messages", "feedback"):
        exported = sum(len(c[name]) for c in written["conversations"]) + len(written["orphaned"][name])
        if exported != counts[name]:
            raise RuntimeError(f"Export verification failed for {path}: {name} {exported} != {counts[name]}")
    if len(written["conversations"]) != counts["conversations"]:
        raise RuntimeError(f"Export verification failed for {path}: conversations")

    return path, counts


def reset_database():
    """Drop every app table (plus legacy tables) and recreate the current schema empty."""
    SQLModel.metadata.drop_all(engine)
    with engine.begin() as conn:
        for name in LEGACY_TABLES:
            conn.execute(text(f"DROP TABLE IF EXISTS {name}"))
    SQLModel.metadata.create_all(engine)

    with engine.connect() as conn:
        tables = sorted(inspect(conn).get_table_names())
        counts = {name: conn.execute(text(f"SELECT COUNT(*) FROM {name}")).scalar() for name in tables}
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("export", help="Export conversation history to backups/*.json")
    reset = sub.add_parser("reset", help="Export, then drop and recreate all tables")
    reset.add_argument("--yes", action="store_true", help="Confirm deleting all data in the target database")
    reset.add_argument("--skip-export", action="store_true", help="Don't export conversations first")
    args = parser.parse_args()

    print(f"Target database: {describe_target()}")

    if args.command == "reset" and not args.yes:
        sys.exit("Refusing to reset without --yes. This deletes all conversations, feedback and crawled content.")

    if args.command == "export" or not args.skip_export:
        path, counts = export_conversations()
        print(f"Exported {counts} -> {path}")

    if args.command == "reset":
        counts = reset_database()
        print(f"Database reset. Tables now: {counts}")


if __name__ == "__main__":
    main()
