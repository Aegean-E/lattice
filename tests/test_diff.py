"""Tests for graph snapshot diffing: record comparison, snapshot pairs and live-repository diffs."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from lattice.cli import main
from lattice.database import open_database
from lattice.diff import diff_records, diff_snapshot, diff_snapshots
from lattice.errors import LatticeError
from lattice.repository import Repository
from lattice.snapshots import export_snapshot


def seed_graph(repository):
    """One paper, claim, question and edge as a diffing baseline."""
    paper, _ = repository.add_paper({"title": "Baseline Sleep Trial", "year": "2024"})
    claim = repository.add_claim(
        paper.id, "Sleep improves memory.", "Sleep improves memory.", stance="supports")
    question = repository.add_question("Does sleep consolidate memory?")
    repository.add_edge(f"claim:{claim.id}", f"question:{question.id}", "supports")
    return paper, claim, question


class DiffRecordsTests(unittest.TestCase):
    """The pure record comparison behind every diff entry point."""

    def test_reports_added_removed_changed_and_unchanged(self):
        old = [
            {"record_type": "paper", "id": "p_000001", "title": "Old title"},
            {"record_type": "claim", "id": "c_000001", "text": "kept", "stance": "mentions"},
            {"record_type": "question", "id": "q_000001", "text": "removed?"},
            {"record_type": "edge", "id": 1, "src": "claim:c_000001",
             "dst": "question:q_000001", "kind": "supports"},
        ]
        new = [
            {"record_type": "paper", "id": "p_000001", "title": "New title"},
            {"record_type": "claim", "id": "c_000001", "text": "kept", "stance": "mentions"},
            {"record_type": "question", "id": "q_000002", "text": "added?"},
            {"record_type": "edge", "id": 2, "src": "claim:c_000001",
             "dst": "question:q_000002", "kind": "answers"},
        ]
        report = diff_records(old, new)
        self.assertEqual(report["added"],
                         {"papers": [], "questions": ["q_000002"], "claims": [], "edges": ["2"]})
        self.assertEqual(report["removed"],
                         {"papers": [], "questions": ["q_000001"], "claims": [], "edges": ["1"]})
        self.assertEqual(report["changed"]["papers"], [{"id": "p_000001", "fields": ["title"]}])
        self.assertEqual(report["changed"]["questions"], [])
        self.assertEqual(report["changed"]["claims"], [])
        self.assertEqual(report["changed"]["edges"], [])
        self.assertEqual(report["summary"],
                         {"added": 2, "removed": 2, "changed": 1, "unchanged": 1})

    def test_created_at_differences_are_not_changes(self):
        old = [{"record_type": "claim", "id": "c_000001", "text": "same",
                "created_at": "2026-01-01T00:00:00Z"}]
        new = [{"record_type": "claim", "id": "c_000001", "text": "same",
                "created_at": "2026-06-01T00:00:00Z"}]
        report = diff_records(old, new)
        self.assertEqual(report["summary"],
                         {"added": 0, "removed": 0, "changed": 0, "unchanged": 1})

    def test_identical_records_in_any_order_report_no_differences(self):
        records = [{"record_type": "question", "id": "q_000001", "text": "same?"},
                   {"record_type": "edge", "id": 7, "src": "a", "dst": "b", "kind": "cites"}]
        report = diff_records(records, [dict(records[1]), dict(records[0])])
        self.assertEqual(report["summary"],
                         {"added": 0, "removed": 0, "changed": 0, "unchanged": 2})


class SnapshotDiffTests(unittest.TestCase):
    """Diff exported snapshot files and snapshots against the live repository."""

    def setUp(self):
        connection = open_database(":memory:")
        self.addCleanup(connection.close)
        self.repository = Repository(connection)
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.snapshot_path = Path(self.directory.name) / "baseline.jsonl"
        self.paper, self.claim, self.question = seed_graph(self.repository)
        export_snapshot(self.repository, self.snapshot_path)

    def test_diff_snapshots_between_two_files(self):
        added_question = self.repository.add_question("Does caffeine impair memory?")
        added_claim = self.repository.add_claim(
            self.paper.id, "Caffeine impairs recall.", "Caffeine impairs recall.",
            stance="contradicts")
        self.repository.add_edge(f"claim:{added_claim.id}",
                                 f"question:{added_question.id}", "answers")
        newer_path = Path(self.directory.name) / "newer.jsonl"
        export_snapshot(self.repository, newer_path)

        report = diff_snapshots(self.snapshot_path, newer_path)
        self.assertEqual(report["old"]["label"], str(self.snapshot_path))
        self.assertEqual(report["new"]["label"], str(newer_path))
        self.assertEqual(report["old"]["questions"], 1)
        self.assertEqual(report["new"]["questions"], 2)
        self.assertEqual(report["added"]["papers"], [])
        self.assertEqual(report["added"]["questions"], [added_question.id])
        self.assertEqual(report["added"]["claims"], [added_claim.id])
        self.assertEqual(report["added"]["edges"], ["2"])
        self.assertEqual(report["removed"],
                         {"papers": [], "questions": [], "claims": [], "edges": []})
        self.assertEqual(report["summary"],
                         {"added": 3, "removed": 0, "changed": 0, "unchanged": 4})

    def test_diff_snapshot_against_live_repository(self):
        self.repository.set_question_status(self.question.id, "answered")
        report = diff_snapshot(self.repository, self.snapshot_path)
        self.assertEqual(report["old"]["label"], str(self.snapshot_path))
        self.assertEqual(report["new"]["label"], ":memory:")
        self.assertEqual(report["changed"]["questions"],
                         [{"id": self.question.id, "fields": ["status"]}])
        self.assertEqual(report["summary"],
                         {"added": 0, "removed": 0, "changed": 1, "unchanged": 3})

    def test_diff_snapshot_identical_to_repository_reports_nothing(self):
        report = diff_snapshot(self.repository, self.snapshot_path)
        self.assertEqual(report["summary"],
                         {"added": 0, "removed": 0, "changed": 0, "unchanged": 4})

    def test_diff_missing_snapshot_file_fails(self):
        missing = Path(self.directory.name) / "missing.jsonl"
        with self.assertRaises(LatticeError):
            diff_snapshots(missing, self.snapshot_path)
        with self.assertRaises(LatticeError):
            diff_snapshot(self.repository, missing)


class DiffCliTests(unittest.TestCase):
    """The `diff` command against a temporary database file."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.db = str(Path(self.directory.name) / "lattice.db")
        connection = open_database(self.db)
        repository = Repository(connection)
        self.paper, self.claim, self.question = seed_graph(repository)
        connection.close()
        self.snapshot = str(Path(self.directory.name) / "baseline.jsonl")
        code, out, err = self.run_cli("export", self.snapshot)
        self.assertEqual(code, 0, err)

    def run_cli(self, *arguments):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["--db", self.db, *arguments])
        return code, out.getvalue(), err.getvalue()

    def test_diff_against_unchanged_graph_exits_zero(self):
        code, out, err = self.run_cli("diff", self.snapshot)
        self.assertEqual(code, 0, err)
        self.assertIn("0 added, 0 removed, 0 changed", out)

    def test_diff_against_changed_graph_exits_one_and_reports(self):
        connection = open_database(self.db)
        repository = Repository(connection)
        repository.set_question_status(self.question.id, "answered")
        repository.add_question("Does caffeine impair memory?")
        connection.close()
        code, out, err = self.run_cli("diff", self.snapshot)
        self.assertEqual(code, 1, err)
        self.assertIn("1 added", out)
        self.assertIn("1 changed", out)
        self.assertIn(self.question.id, out)

        code, out, err = self.run_cli("--json", "diff", self.snapshot)
        self.assertEqual(code, 1, err)
        payload = json.loads(out)
        self.assertEqual(payload["summary"]["added"], 1)
        self.assertEqual(payload["summary"]["changed"], 1)
        self.assertEqual(payload["changed"]["questions"][0]["id"], self.question.id)

    def test_diff_between_two_snapshot_files(self):
        code, out, err = self.run_cli("diff", self.snapshot, self.snapshot)
        self.assertEqual(code, 0, err)
        self.assertIn("0 added, 0 removed, 0 changed", out)

    def test_diff_missing_snapshot_fails(self):
        missing = str(Path(self.directory.name) / "missing.jsonl")
        code, out, err = self.run_cli("diff", missing)
        self.assertEqual(code, 1)
        self.assertIn("does not exist", err)


if __name__ == "__main__":
    unittest.main()
