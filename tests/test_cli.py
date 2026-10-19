"""End-to-end command contracts without spawning subprocesses."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from lattice.cli import main
from lattice.database import open_database
from lattice.repository import Repository


class CliTests(unittest.TestCase):
    """Drive the real parser and handlers against a temporary database."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.db = str(Path(self.directory.name) / "lattice.db")

    def run_cli(self, *arguments):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["--db", self.db, *arguments])
        return code, out.getvalue(), err.getvalue()

    def ingest_fixture(self):
        path = Path(self.directory.name) / "papers.bib"
        path.write_text(
            "@article{sleep, title={Sleep and memory}, author={A. Author}, year={2021},"
            " doi={10.1/sleep}}", encoding="utf-8")
        return path

    def test_init_is_idempotent(self):
        first, _, _ = self.run_cli("init")
        second, _, _ = self.run_cli("init")
        self.assertEqual((first, second), (0, 0))

    def test_ingest_question_claim_link_ask(self):
        fixture = self.ingest_fixture()
        code, out, _ = self.run_cli("ingest", str(fixture))
        self.assertEqual(code, 0)
        self.assertIn("1 new", out)
        code, out, _ = self.run_cli("question", "Does sleep consolidate memory?")
        self.assertEqual(code, 0)
        self.assertIn("q_000001", out)
        connection = open_database(self.db)
        self.addCleanup(connection.close)
        paper = Repository(connection).search("Sleep")["papers"][0]
        code, _, _ = self.run_cli("claim", "--paper", paper["id"], "--text",
                                  "Sleep consolidates memory", "--quote",
                                  "Sleep consolidates memory.", "--stance", "supports")
        self.assertEqual(code, 0)
        code, _, _ = self.run_cli("link", "claim:c_000001", "question:q_000001",
                                  "--type", "supports")
        self.assertEqual(code, 0)
        code, out, _ = self.run_cli("ask", "q_000001")
        self.assertEqual(code, 0)
        self.assertIn("Supports (1)", out)

    def test_json_output(self):
        code, out, _ = self.run_cli("--json", "question", "What is memory?")
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["question"]["id"], "q_000001")

    def test_brief_and_review_file(self):
        self.run_cli("ingest", str(self.ingest_fixture()))
        self.run_cli("question", "Does sleep consolidate memory?")
        code, out, _ = self.run_cli("brief", "q_000001", "--tokens", "400")
        self.assertEqual(code, 0)
        self.assertIn("QUESTION:", out)
        target = Path(self.directory.name) / "review.md"
        code, out, _ = self.run_cli("review", "q_000001", "--out", str(target))
        self.assertEqual(code, 0)
        self.assertTrue(target.is_file())
        self.assertIn("Evidence review", target.read_text(encoding="utf-8"))

    def test_check_passes_and_reports(self):
        self.run_cli("ingest", str(self.ingest_fixture()))
        code, out, _ = self.run_cli("check")
        self.assertEqual(code, 0)
        self.assertIn("0 error(s)", out)

    def test_user_error_prints_triad(self):
        code, _, err = self.run_cli("show", "paper:p_missing")
        self.assertEqual(code, 1)
        self.assertIn("Error:", err)
        self.assertIn("Why:", err)
        self.assertIn("Fix:", err)

    def test_search_and_stats(self):
        self.run_cli("ingest", str(self.ingest_fixture()))
        code, out, _ = self.run_cli("search", "sleep")
        self.assertEqual(code, 0)
        self.assertIn("Papers (1)", out)
        code, out, _ = self.run_cli("stats")
        self.assertEqual(code, 0)
        self.assertIn("papers: 1", out)

    def test_fetch_extract_synthesize_subgraph_and_snapshots(self):
        code, out, _ = self.run_cli("question", "Does slow-wave sleep consolidate memory?")
        self.assertEqual(code, 0)

        code, out, _ = self.run_cli("fetch", "slow-wave sleep memory", "--source", "offline", "--limit", "2")
        self.assertEqual(code, 0)
        self.assertIn("new", out)

        code, out, _ = self.run_cli("extract", "--all", "--question", "q_000001")
        self.assertEqual(code, 0)
        self.assertIn("extracted", out)

        synth_path = Path(self.directory.name) / "synthesis.md"
        code, out, _ = self.run_cli("synthesize", "q_000001", "--tokens", "2000", "--out", str(synth_path))
        self.assertEqual(code, 0)
        self.assertTrue(synth_path.is_file())
        self.assertIn("Literature Synthesis:", synth_path.read_text(encoding="utf-8"))

        code, out, _ = self.run_cli("subgraph", "q_000001", "--depth", "2")
        self.assertEqual(code, 0)
        self.assertIn("Nodes", out)

        snap_path = Path(self.directory.name) / "bundle.jsonl"
        code, out, _ = self.run_cli("export", str(snap_path))
        self.assertEqual(code, 0)
        self.assertTrue(snap_path.is_file())

        code, out, _ = self.run_cli("import", str(snap_path))
        self.assertEqual(code, 0)
        self.assertIn("imported", out)


if __name__ == "__main__":
    unittest.main()
