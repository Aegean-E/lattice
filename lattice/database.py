"""SQLite connection, versioned schema and migration veil for the knowledge graph."""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from lattice.errors import fail

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS papers (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL DEFAULT 'paper',
    title TEXT NOT NULL,
    authors TEXT NOT NULL DEFAULT '',
    year TEXT NOT NULL DEFAULT '',
    venue TEXT NOT NULL DEFAULT '',
    doi TEXT NOT NULL DEFAULT '',
    arxiv TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL DEFAULT '',
    abstract TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS papers_doi ON papers(lower(doi)) WHERE doi != '';
CREATE UNIQUE INDEX IF NOT EXISTS papers_arxiv ON papers(lower(arxiv)) WHERE arxiv != '';

CREATE TABLE IF NOT EXISTS claims (
    id TEXT PRIMARY KEY,
    paper_id TEXT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    text TEXT NOT NULL,
    quote TEXT NOT NULL,
    locator TEXT NOT NULL DEFAULT '',
    stance TEXT NOT NULL CHECK (stance IN ('supports', 'contradicts', 'mentions')),
    confidence REAL NOT NULL DEFAULT 0.5 CHECK (confidence >= 0 AND confidence <= 1),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS questions (
    id TEXT PRIMARY KEY,
    text TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'answered', 'abandoned')),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    src TEXT NOT NULL,
    dst TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN (
        'cites', 'supports', 'contradicts', 'replicates', 'extends',
        'uses_method', 'measures', 'answers', 'mentions', 'related'
    )),
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE(src, dst, kind)
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL,
    action TEXT NOT NULL,
    payload TEXT NOT NULL
);
"""


def utc_now() -> str:
    """An ISO-8601 UTC timestamp with a stable seconds precision."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def open_database(path: str) -> sqlite3.Connection:
    """Open or create the database, verify its schema version and return it."""
    if path != ":memory:":
        parent = Path(path).resolve().parent
        parent.mkdir(parents=True, exist_ok=True)
    try:
        connection = sqlite3.connect(path, timeout=3.0)
    except sqlite3.Error as exc:
        fail(f"could not open {path}: {exc}", "the knowledge base path is not usable",
             "choose a writable file path with --db")
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 3000")
    connection.execute("PRAGMA synchronous = FULL")
    if path != ":memory:":
        connection.execute("PRAGMA journal_mode = WAL")
    _ensure_schema(connection)
    return connection


def _ensure_schema(connection: sqlite3.Connection) -> None:
    """Create the schema once and refuse a database written by a newer version."""
    connection.executescript(SCHEMA)
    row = connection.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    if row is None:
        connection.execute("INSERT INTO meta(key, value) VALUES('schema_version', ?)",
                           (str(SCHEMA_VERSION),))
        connection.commit()
        return
    if str(row["value"]) != str(SCHEMA_VERSION):
        fail(f"database schema version {row['value']} is not supported",
             f"this build reads schema version {SCHEMA_VERSION}",
             "use the lattice version that wrote the file, or export and re-ingest into a new database")


def schema_version(connection: sqlite3.Connection) -> int:
    """The declared schema version, or 0 when the metadata row is missing."""
    row = connection.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    return int(row["value"]) if row else 0
