#!/usr/bin/env python3
"""
Initialize SQLite database schema and seed data for the database container.

Requirements implemented:
- Read SQLite database file path from db_connection.txt (single source of truth).
- Create a `users` table (id, name, email, created_at).
- Idempotent: safe to re-run (CREATE TABLE IF NOT EXISTS + seed only if empty).
- Simple CLI entry: `python init_db.py` with status messages.
"""

from __future__ import annotations

import os
import re
import sqlite3
import sys
from typing import Optional, Sequence, Tuple


def _extract_db_path_from_db_connection_file(contents: str) -> Optional[str]:
    """
    Parse db_connection.txt contents and return the SQLite file path if found.

    Expected to find a line like:
      # File path: /abs/path/to/myapp.db
    Or alternatively a connection string like:
      # Connection string: sqlite:////abs/path/to/myapp.db
    """
    # Prefer explicit file path line.
    m = re.search(r"^\s*#\s*File path:\s*(.+?)\s*$", contents, flags=re.MULTILINE)
    if m:
        return m.group(1).strip()

    # Fallback: parse sqlite URI line.
    m = re.search(r"^\s*#\s*Connection string:\s*(sqlite:/{2,}.+?)\s*$", contents, flags=re.MULTILINE)
    if m:
        uri = m.group(1).strip()
        # Common form used in the repo: sqlite:////abs/path/to/file.db
        # Strip scheme and leading slashes carefully.
        # sqlite:////abs/path -> path is /abs/path
        if uri.startswith("sqlite:////"):
            return "/" + uri[len("sqlite:////") :].lstrip("/")
        if uri.startswith("sqlite:///"):
            return uri[len("sqlite:///") :]
        return uri

    return None


# PUBLIC_INTERFACE
def get_db_path(db_connection_file: str = "db_connection.txt") -> str:
    """Read db_connection.txt and return the absolute path to the SQLite database file."""
    if not os.path.exists(db_connection_file):
        raise FileNotFoundError(
            f"Required file '{db_connection_file}' not found. "
            "This file must contain the authoritative SQLite DB path."
        )

    with open(db_connection_file, "r", encoding="utf-8") as f:
        contents = f.read()

    db_path = _extract_db_path_from_db_connection_file(contents)
    if not db_path:
        raise ValueError(
            f"Could not determine SQLite DB path from '{db_connection_file}'. "
            "Expected a line like '# File path: /abs/path/to/myapp.db'."
        )

    # Keep db_connection.txt as source of truth; we normalize only for usage.
    db_path = os.path.expanduser(db_path)
    db_path = os.path.abspath(db_path)
    return db_path


def _ensure_parent_dir(db_path: str) -> None:
    """Ensure the database directory exists (SQLite will create the file, but not the directory)."""
    parent = os.path.dirname(db_path)
    if parent and not os.path.exists(parent):
        os.makedirs(parent, exist_ok=True)


def _create_schema(conn: sqlite3.Connection) -> None:
    """Create required tables (idempotent)."""
    cur = conn.cursor()

    # Keep minimal, focused schema per request.
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    # Helpful index for lookup by email (unique already implies index in SQLite,
    # but we leave schema minimal and rely on UNIQUE constraint).
    conn.commit()


def _table_row_count(conn: sqlite3.Connection, table: str) -> int:
    cur = conn.cursor()
    cur.execute(f"SELECT COUNT(*) FROM {table}")
    return int(cur.fetchone()[0])


def _seed_users_if_empty(conn: sqlite3.Connection) -> int:
    """Seed a few sample users only if the users table is empty. Returns number inserted."""
    existing = _table_row_count(conn, "users")
    if existing > 0:
        return 0

    seed_rows: Sequence[Tuple[str, str]] = [
        ("Alice Johnson", "alice@example.com"),
        ("Bob Smith", "bob@example.com"),
        ("Charlie Lee", "charlie@example.com"),
    ]

    cur = conn.cursor()
    # Use INSERT OR IGNORE to remain safe even if the table had rows inserted concurrently.
    cur.executemany(
        "INSERT OR IGNORE INTO users (name, email) VALUES (?, ?)",
        seed_rows,
    )
    conn.commit()

    # SQLite cursor.rowcount for executemany is driver-dependent; compute inserted count.
    after = _table_row_count(conn, "users")
    return max(0, after - existing)


def _print_db_summary(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    )
    tables = [r[0] for r in cur.fetchall()]
    print(f"Tables present ({len(tables)}): {', '.join(tables) if tables else '(none)'}")

    if "users" in tables:
        cur.execute("SELECT COUNT(*) FROM users")
        users_count = int(cur.fetchone()[0])
        print(f"users rows: {users_count}")


# PUBLIC_INTERFACE
def main(argv: Optional[Sequence[str]] = None) -> int:
    """
    CLI entrypoint for initializing the SQLite database.

    Run:
      python init_db.py

    Returns:
      Process exit code (0 success, non-zero on error).
    """
    argv = argv if argv is not None else sys.argv[1:]

    # Simple CLI: no flags required (by request). We keep argv for future extension.
    if argv and argv[0] in ("-h", "--help"):
        print("Usage: python init_db.py\n\nInitializes SQLite schema and seeds sample users if empty.")
        return 0

    print("Starting SQLite database initialization...")

    try:
        db_path = get_db_path("db_connection.txt")
    except Exception as e:
        print(f"ERROR: {e}")
        return 2

    _ensure_parent_dir(db_path)
    print(f"Using SQLite database file: {db_path}")

    try:
        conn = sqlite3.connect(db_path)
        # Ensure constraint enforcement.
        conn.execute("PRAGMA foreign_keys = ON")

        print("Creating schema (idempotent)...")
        _create_schema(conn)
        print("✓ Schema ensured")

        print("Seeding sample users if table is empty...")
        inserted = _seed_users_if_empty(conn)
        if inserted > 0:
            print(f"✓ Seeded {inserted} sample user(s)")
        else:
            print("✓ Users table already has data; no seeding needed")

        print("\nDatabase status:")
        _print_db_summary(conn)

        conn.close()
        print("\nSQLite initialization complete.")
        return 0

    except sqlite3.Error as e:
        print(f"ERROR: SQLite error: {e}")
        return 3
    except Exception as e:
        print(f"ERROR: Unexpected error: {e}")
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
