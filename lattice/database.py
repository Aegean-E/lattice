"""SQLite connection, versioned schema and migration veil for the knowledge graph."""

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from lattice.errors import fail

SCHEMA_VERSION = 2

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
    tags TEXT NOT NULL DEFAULT '',
    study_type TEXT NOT NULL DEFAULT '',
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

CREATE TABLE IF NOT EXISTS screening (
    paper_id TEXT PRIMARY KEY REFERENCES papers(id) ON DELETE CASCADE,
    status TEXT NOT NULL CHECK (status IN ('identified', 'screened_in', 'screened_out', 'included', 'excluded')),
    reason TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    screened_at TEXT NOT NULL
);
"""


def utc_now() -> str:
    """An ISO-8601 UTC timestamp with a stable seconds precision."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def open_database(path: str, read_only: bool = False) -> sqlite3.Connection:
    """Open or create the database, verify its schema version and return it.

    A read-only open never creates a file, never migrates a schema and sets SQLite's
    `query_only` guard. An in-memory read-only database still creates its schema in memory.
    """
    if not isinstance(path, (str, os.PathLike)):
        fail("a database path must be a string or path", "a connection needs a file or :memory:",
             "pass a path string or pathlib.Path")
    text = str(path)
    if not text.strip():
        fail("a database path is required", "an empty path cannot identify a knowledge base",
             "pass a file path or :memory:")
    path = ":memory:" if text.strip() == ":memory:" else text
    if path != ":memory:" and not read_only:
        parent = Path(path).resolve().parent
        parent.mkdir(parents=True, exist_ok=True)
    try:
        if read_only and path != ":memory:":
            candidate = Path(path).resolve()
            if not candidate.is_file():
                fail(f"database {path} does not exist",
                     "a read-only client cannot create a knowledge base",
                     "create it with a writable client, or pass a writable client")
            connection = sqlite3.connect(candidate.as_uri() + "?mode=ro", uri=True, timeout=3.0)
        else:
            connection = sqlite3.connect(path, timeout=3.0)
    except sqlite3.Error as exc:
        fail(f"could not open {path}: {exc}", "the knowledge base path is not usable",
             "choose a writable file path with --db")
    try:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 3000")
        if read_only and path != ":memory:":
            _verify_schema_read_only(connection)
            connection.execute("PRAGMA query_only = ON")
        else:
            connection.execute("PRAGMA synchronous = FULL")
            if path != ":memory:":
                connection.execute("PRAGMA journal_mode = WAL")
            _ensure_schema(connection)
            if read_only:
                connection.execute("PRAGMA query_only = ON")
        return connection
    except BaseException:
        connection.close()
        raise


def _verify_schema_read_only(connection: sqlite3.Connection) -> None:
    """Verify a read-only database is current without creating or migrating anything."""
    try:
        row = connection.execute(
            "SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    except sqlite3.Error as exc:
        fail(f"not a lattice knowledge base: {exc}",
             "a read-only open cannot create the metadata table",
             "open a database written by lattice, or create one with a writable client")
    if row is None:
        fail("the database has no lattice schema version",
             "a read-only open cannot initialize or migrate it",
             "create it with a writable client first")
    try:
        version = int(row["value"])
    except (TypeError, ValueError):
        fail(f"database schema version {row['value']} is not supported",
             "the metadata row is not a schema version this build understands",
             "restore a backup written by lattice, or export and re-ingest the graph")
    if version != SCHEMA_VERSION:
        fail(f"database schema version {version} cannot be opened read-only",
             f"this build reads schema version {SCHEMA_VERSION} and migrating it would write",
             "open it once with a writable client to migrate it, or use a migrated copy")


def _ensure_schema(connection: sqlite3.Connection) -> None:
    """Create the schema once, migrate v1 and refuse a database from a newer version."""
    connection.executescript(SCHEMA)
    row = connection.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    if row is None:
        _set_schema_version(connection, SCHEMA_VERSION)
        return
    try:
        version = int(row["value"])
    except (TypeError, ValueError):
        fail(f"database schema version {row['value']} is not supported",
             "the metadata row is not a schema version this build understands",
             "restore a backup written by lattice, or export and re-ingest the graph")
    if version == SCHEMA_VERSION:
        return
    if version == 1:
        _migrate_v1_to_v2(connection)
        _set_schema_version(connection, SCHEMA_VERSION)
        return
    fail(f"database schema version {row['value']} is not supported",
         f"this build reads schema version {SCHEMA_VERSION}",
         "use the lattice version that wrote the file, or export and re-ingest into a new database")


def _set_schema_version(connection: sqlite3.Connection, version: int) -> None:
    """Persist the schema version after a fresh create or a completed migration."""
    connection.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES('schema_version', ?)", (str(version),)
    )
    connection.commit()


def _add_column_if_missing(connection: sqlite3.Connection, table: str,
                           column: str, definition: str) -> None:
    """Add one column once, so an interrupted migration can be retried."""
    columns = {str(row["name"]) for row in connection.execute(f"PRAGMA table_info({table})")}
    if column not in columns:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _migrate_v1_to_v2(connection: sqlite3.Connection) -> None:
    """Add searchable tags and study type, backfilling them for existing papers."""
    from lattice.models import derive_tags, infer_study_type, normalize_tags

    _add_column_if_missing(connection, "papers", "tags", "TEXT NOT NULL DEFAULT ''")
    _add_column_if_missing(connection, "papers", "study_type", "TEXT NOT NULL DEFAULT ''")
    rows = connection.execute(
        "SELECT id, title, abstract, tags, study_type FROM papers"
    ).fetchall()
    for row in rows:
        tags = normalize_tags(row["tags"] or derive_tags(row["title"], row["abstract"]))
        study_type = row["study_type"] or infer_study_type(row["title"], row["abstract"])
        if tags != row["tags"] or study_type != row["study_type"]:
            connection.execute(
                "UPDATE papers SET tags = ?, study_type = ? WHERE id = ?",
                (tags, study_type, row["id"]),
            )
    connection.commit()


def schema_version(connection: sqlite3.Connection) -> int:
    """The declared schema version, or 0 when the metadata row is missing."""
    row = connection.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    return int(row["value"]) if row else 0
