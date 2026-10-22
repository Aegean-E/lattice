"""Schema migration from the first release keeps an existing graph usable."""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from lattice.database import open_database, schema_version
from lattice.errors import LatticeError
from lattice.repository import Repository


OLD_SCHEMA = """
CREATE TABLE meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE papers (
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
INSERT INTO meta(key, value) VALUES('schema_version', '1');
INSERT INTO papers(id, kind, title, authors, year, venue, doi, arxiv, url, abstract, created_at)
VALUES(
    'p_legacy000001',
    'paper',
    'A randomized controlled trial of slow-wave sleep and memory',
    'Elena Vance',
    '2023',
    'Nature',
    '10.1000/legacy.1',
    '',
    '',
    'Slow-wave sleep increased recall accuracy across 120 participants.',
    '2023-01-01T00:00:00+00:00'
);
"""


class MigrationTests(unittest.TestCase):
    """A version 1 database gains the literature metadata columns without losing papers."""

    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "lattice.db"

    def test_v1_database_migrates_tags_and_study_type(self) -> None:
        connection = sqlite3.connect(str(self.path))
        connection.executescript(OLD_SCHEMA)
        connection.commit()
        connection.close()

        migrated = open_database(str(self.path))
        self.addCleanup(migrated.close)
        self.assertEqual(schema_version(migrated), 2)
        columns = {row["name"] for row in migrated.execute("PRAGMA table_info(papers)")}
        self.assertIn("tags", columns)
        self.assertIn("study_type", columns)

        paper = migrated.execute("SELECT * FROM papers WHERE id = 'p_legacy000001'").fetchone()
        self.assertEqual(
            paper["title"], "A randomized controlled trial of slow-wave sleep and memory"
        )
        self.assertEqual(paper["study_type"], "Randomized Controlled Trial")
        self.assertIn("sleep", paper["tags"])

        migrated.close()
        reopened = open_database(str(self.path))
        self.addCleanup(reopened.close)
        self.assertEqual(schema_version(reopened), 2)
        self.assertEqual(
            reopened.execute("SELECT COUNT(*) AS n FROM papers").fetchone()["n"], 1
        )


class ReadOnlyDatabaseTests(unittest.TestCase):
    """A read-only open neither creates, migrates nor writes the database."""

    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "lattice.db"

    def test_missing_database_is_not_created(self) -> None:
        with self.assertRaises(LatticeError):
            open_database(str(self.path), read_only=True)
        self.assertFalse(self.path.exists())

    def test_invalid_paths_raise_lattice_error(self) -> None:
        for bad_path in (None, ""):
            with self.subTest(path=bad_path), self.assertRaises(LatticeError):
                open_database(bad_path)

    def test_whitespace_memory_sentinel_is_normalized(self) -> None:
        connection = open_database(" :memory: ")
        self.addCleanup(connection.close)
        self.assertEqual(schema_version(connection), 2)

    def test_existing_database_is_current_and_query_only(self) -> None:
        connection = open_database(str(self.path))
        Repository(connection).add_question("Does read-only work?")
        connection.close()

        read_only = open_database(str(self.path), read_only=True)
        self.addCleanup(read_only.close)
        self.assertEqual(schema_version(read_only), 2)
        with self.assertRaises(sqlite3.OperationalError):
            read_only.execute(
                "INSERT INTO questions(id, text, status, created_at)"
                " VALUES('q_999999', 'blocked', 'open', 'now')")

    def test_in_memory_read_only_is_query_only(self) -> None:
        connection = open_database(":memory:", read_only=True)
        self.addCleanup(connection.close)
        self.assertEqual(schema_version(connection), 2)
        with self.assertRaises(sqlite3.OperationalError):
            connection.execute(
                "INSERT INTO questions(id, text, status, created_at)"
                " VALUES('q_999999', 'blocked', 'open', 'now')")

    def test_v1_database_is_not_migrated_read_only(self) -> None:
        connection = sqlite3.connect(str(self.path))
        connection.executescript(OLD_SCHEMA)
        connection.commit()
        connection.close()

        with self.assertRaises(LatticeError):
            open_database(str(self.path), read_only=True)

        raw = sqlite3.connect(str(self.path))
        self.addCleanup(raw.close)
        self.assertEqual(
            raw.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()[0],
            "1")


if __name__ == "__main__":
    unittest.main()
