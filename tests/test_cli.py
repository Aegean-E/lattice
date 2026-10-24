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

    def test_related_command_reports_and_links_findings(self):
        connection = open_database(self.db)
        repo = Repository(connection)
        question = repo.add_question("Does sleep consolidate memory?")
        first, _ = repo.add_paper({"title": "Sleep One", "authors": "A"})
        second, _ = repo.add_paper({"title": "Sleep Two", "authors": "B"})
        c1 = repo.add_claim(first.id, "Sleep improved memory recall.",
                            "Sleep improved memory recall by 28%.", stance="supports")
        c2 = repo.add_claim(second.id, "Sleep enhanced memory recall.",
                            "Sleep enhanced memory recall across participants.", stance="supports")
        repo.add_edge(c1.id, question.id, kind="answers")
        repo.add_edge(c2.id, question.id, kind="answers")
        connection.close()

        code, out, err = self.run_cli("--json", "related", f"claim:{c1.id}")
        self.assertEqual(code, 0, err)
        payload = json.loads(out)
        self.assertEqual(payload["root"], f"claim:{c1.id}")
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["related"][0]["id"], c2.id)

        code, out, err = self.run_cli("analyze", "--auto-link", "--limit", "3")
        self.assertEqual(code, 0, err)
        self.assertIn("Related finding pairs detected: 1 (linked: 1)", out)

        code, out, err = self.run_cli("related", f"claim:{c1.id}")
        self.assertEqual(code, 0, err)
        self.assertIn("related", out)
        self.assertIn(c2.id, out)

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

        bib_path = Path(self.directory.name) / "references.bib"
        code, out, _ = self.run_cli("export", str(bib_path))
        self.assertEqual(code, 0)
        self.assertTrue(bib_path.is_file())
        bib_content = bib_path.read_text(encoding="utf-8")
        self.assertIn("@article{", bib_content)
        self.assertIn("slow-wave sleep", bib_content.lower())

        custom_path = Path(self.directory.name) / "refs.txt"
        code, out, _ = self.run_cli("export", str(custom_path), "--format", "bibtex")
        self.assertEqual(code, 0)
        self.assertTrue(custom_path.is_file())
        self.assertIn("@article{", custom_path.read_text(encoding="utf-8"))

        gml_path = Path(self.directory.name) / "graph.graphml"
        code, out, _ = self.run_cli("export", str(gml_path))
        self.assertEqual(code, 0)
        self.assertTrue(gml_path.is_file())
        self.assertIn("GraphML", out)

        cy_path = Path(self.directory.name) / "graph.cyjs"
        code, out, _ = self.run_cli("export", str(cy_path))
        self.assertEqual(code, 0)
        self.assertTrue(cy_path.is_file())
        self.assertIn("Cytoscape", out)

    def test_web_subcommand_demo_and_dump_html(self):
        code, out, _ = self.run_cli("web", "--demo", "--dump-html")
        self.assertEqual(code, 0)
        self.assertIn("Lattice Research Studio", out)

    def test_outline_command_reports_a_cheap_index(self):
        self.run_cli("web", "--demo", "--dump-html")
        code, out, err = self.run_cli("outline")
        self.assertEqual(code, 0, err)
        self.assertIn("papers", out)
        self.assertIn("Questions", out)
        self.assertIn("get_entity", out)

        code, out, err = self.run_cli("--json", "outline", "--tokens", "300")
        self.assertEqual(code, 0, err)
        payload = json.loads(out)
        self.assertGreaterEqual(payload["counts"]["papers"], 1)
        self.assertIn("omitted_questions", payload)
        self.assertIn("study_types", payload)

    def test_compact_token_views_for_related_subgraph_and_search(self):
        connection = open_database(self.db)
        repo = Repository(connection)
        question = repo.add_question("Does sleep consolidate memory?")
        paper, _ = repo.add_paper({"title": "Sleep One", "authors": "A",
                                   "study_type": "Cohort Study"})
        first = repo.add_claim(paper.id, "Sleep improved memory recall.",
                               "Sleep improved memory recall by 28%.", stance="supports")
        second_paper, _ = repo.add_paper({"title": "Sleep Two", "authors": "B"})
        second = repo.add_claim(second_paper.id, "Sleep enhanced memory recall.",
                                "Sleep enhanced memory recall across participants.",
                                stance="supports")
        repo.add_edge(first.id, question.id, kind="answers")
        repo.add_edge(second.id, question.id, kind="answers")
        connection.close()

        code, out, err = self.run_cli("--json", "related", f"claim:{first.id}",
                                      "--tokens", "300")
        self.assertEqual(code, 0, err)
        payload = json.loads(out)
        self.assertEqual(payload["related"][0]["ref"], f"claim:{second.id}")
        self.assertIn("snippet", payload["related"][0])
        self.assertNotIn("id", payload["related"][0])

        code, out, err = self.run_cli("--json", "subgraph", f"question:{question.id}",
                                      "--tokens", "300")
        self.assertEqual(code, 0, err)
        payload = json.loads(out)
        self.assertTrue(payload["nodes"])
        self.assertTrue(all("details" not in node for node in payload["nodes"]))
        self.assertIn("omitted_nodes", payload)

        code, out, err = self.run_cli("--json", "search", "sleep", "--tokens", "300")
        self.assertEqual(code, 0, err)
        payload = json.loads(out)
        self.assertTrue(payload["papers"])
        self.assertNotIn("abstract", payload["papers"][0])

    def test_analyze_subcommand(self):
        self.run_cli("web", "--demo", "--dump-html")
        code, out, _ = self.run_cli("--json", "analyze", "--auto-link", "--limit", "5")
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertIn("contradictions", payload)
        self.assertIn("keystone", payload)
        self.assertIn("matrix", payload)

    def test_start_file_default_and_forwarding(self):
        import unittest.mock
        import start as start_module

        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = start_module.start(["start.py", "--db", self.db, "stats"])
        self.assertEqual(code, 0)
        self.assertIn("papers:", out.getvalue())

        with unittest.mock.patch("lattice.cli.serve_web", return_value=0) as mock_serve:
            code = start_module.start(["start.py"])
            self.assertEqual(code, 0)
            mock_serve.assert_called_once()
            db_path = Path(mock_serve.call_args.kwargs["db_path"])
            self.assertTrue(db_path.is_absolute())
            self.assertEqual(db_path, Path(start_module._ROOT) / "lattice.db")

    def test_cli_path_command(self):
        self.run_cli("web", "--demo", "--dump-html")
        code, out, _ = self.run_cli("--json", "path", "q_000001", "c_000001")
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertTrue(payload["found"])
        self.assertEqual(payload["length"], 1)

        code, text_out, _ = self.run_cli("path", "q_000001", "c_000001")
        self.assertEqual(code, 0)
        self.assertIn("Path found", text_out)

    def test_cli_hypothesize_command(self):
        self.run_cli("web", "--demo", "--dump-html")
        code, out, _ = self.run_cli("--json", "hypothesize")
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertIsInstance(payload, list)
        self.assertGreaterEqual(len(payload), 1)

        code, text_out, _ = self.run_cli("hypothesize")
        self.assertEqual(code, 0)
        self.assertIn("Proposed Hypotheses", text_out)

    def test_cli_screen_and_prisma_commands(self):
        fixture = self.ingest_fixture()
        self.run_cli("ingest", str(fixture))
        connection = open_database(self.db)
        paper = Repository(connection).search("Sleep")["papers"][0]
        connection.close()

        code, out, err = self.run_cli(
            "--json", "screen", paper["id"],
            "--status", "included",
            "--notes", "Matches PICO criteria",
        )
        self.assertEqual(code, 0, err)
        payload = json.loads(out)
        self.assertEqual(payload["status"], "included")

        code, out, err = self.run_cli("prisma")
        self.assertEqual(code, 0, err)
        self.assertIn("PRISMA 2020 Flow Diagram", out)

        code, out, err = self.run_cli("--json", "prisma")
        self.assertEqual(code, 0, err)
        flow_json = json.loads(out)
        self.assertEqual(flow_json["identified"], 1)
        self.assertEqual(flow_json["included"], 1)

        code, out, err = self.run_cli("prisma", "--format", "svg")
        self.assertEqual(code, 0, err)
        self.assertIn("<svg", out)

    def test_cli_pack_command(self):
        fixture = self.ingest_fixture()
        self.run_cli("ingest", str(fixture))
        code, out, _ = self.run_cli("question", "Does sleep consolidate memory?")
        self.assertEqual(code, 0)
        connection = open_database(self.db)
        paper = Repository(connection).search("Sleep")["papers"][0]
        connection.close()
        self.run_cli("claim", "--paper", paper["id"], "--text", "Sleep improves recall",
                     "--quote", "Sleep improves recall by 25%.", "--stance", "supports")
        self.run_cli("link", "claim:c_000001", "question:q_000001", "--type", "supports")

        code, out, err = self.run_cli("pack", "q_000001", "--tokens", "1000")
        self.assertEqual(code, 0, err)
        self.assertIn("GraphRAG Evidence Pack", out)
        self.assertIn("Sleep improves recall", out)

        code, out, err = self.run_cli("--json", "pack", "q_000001")
        self.assertEqual(code, 0, err)
        pack_json = json.loads(out)
        self.assertEqual(pack_json["counts"]["questions"], 1)
        self.assertEqual(pack_json["counts"]["claims"], 1)

    def test_cli_meta_command(self):
        fixture = self.ingest_fixture()
        self.run_cli("ingest", str(fixture))
        code, out, _ = self.run_cli("question", "Does sleep consolidate memory?")
        self.assertEqual(code, 0)
        connection = open_database(self.db)
        paper = Repository(connection).search("Sleep")["papers"][0]
        connection.close()
        self.run_cli("claim", "--paper", paper["id"], "--text", "Sleep improves recall",
                     "--quote", "Sleep improves recall by 25%.", "--stance", "supports")
        self.run_cli("link", "claim:c_000001", "question:q_000001", "--type", "supports")

        code, out, err = self.run_cli("meta", "q_000001")
        self.assertEqual(code, 0, err)
        self.assertIn("Pooled (Random)", out)
        self.assertIn("Heterogeneity:", out)

        code, out, err = self.run_cli("--json", "meta", "q_000001")
        self.assertEqual(code, 0, err)
        meta_json = json.loads(out)
        self.assertEqual(meta_json["model"], "random")
        self.assertEqual(len(meta_json["studies"]), 1)

        code, out, err = self.run_cli("meta", "q_000001", "--format", "svg")
        self.assertEqual(code, 0, err)
        self.assertIn("<svg", out)


if __name__ == "__main__":
    unittest.main()

