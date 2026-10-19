"""Tests for the web-based human UI and JSON API dispatcher (zero sockets)."""

import json
import sqlite3
import unittest

from lattice.database import open_database
from lattice.repository import Repository
from lattice.web import WebResponse, dispatch_web_request


class WebInterfaceTests(unittest.TestCase):
    """Verify HTML rendering and REST API handlers via pure request dispatch."""

    def setUp(self) -> None:
        self.connection: sqlite3.Connection = open_database(":memory:")
        self.addCleanup(self.connection.close)
        self.repository = Repository(self.connection)

    def request_json(self, method: str, path: str, payload: object = None) -> tuple[int, dict]:
        raw = json.dumps(payload) if payload is not None else None
        resp = dispatch_web_request(self.repository, method, path, raw)
        self.assertIsInstance(resp, WebResponse)
        return resp.status, json.loads(resp.body)

    def test_index_serves_self_contained_human_ui(self) -> None:
        resp = dispatch_web_request(self.repository, "GET", "/")
        self.assertEqual(resp.status, 200)
        self.assertIn("text/html", resp.content_type)
        self.assertIn("Lattice Research Studio", resp.body)
        self.assertIn("Load Demo Corpus", resp.body)
        self.assertIn("Corpus Outline", resp.body)
        self.assertIn("Export BibTeX", resp.body)
        self.assertIn("Export Filtered BibTeX", resp.body)
        self.assertIn("copySynthesisMarkdown", resp.body)
        self.assertIn("copySynthesisBibtex", resp.body)
        self.assertIn("outline-drawer", resp.body)

    def test_link_related_endpoint_and_map_legend(self) -> None:
        resp = dispatch_web_request(self.repository, "GET", "/")
        self.assertIn("Connect Findings", resp.body)
        self.assertIn("related (dashed)", resp.body)
        self.assertIn("const edgeStyles", resp.body)

        question = self.repository.add_question("Does sleep consolidate memory?")
        first, _ = self.repository.add_paper({"title": "Sleep One", "authors": "A"})
        second, _ = self.repository.add_paper({"title": "Sleep Two", "authors": "B"})
        c1 = self.repository.add_claim(first.id, "Sleep improved memory recall.",
                                       "Sleep improved memory recall by 28%.", stance="supports")
        c2 = self.repository.add_claim(second.id, "Sleep enhanced memory recall.",
                                       "Sleep enhanced memory recall across participants.",
                                       stance="supports")
        self.repository.add_edge(c1.id, question.id, kind="answers")
        self.repository.add_edge(c2.id, question.id, kind="answers")

        status, payload = self.request_json("POST", "/api/link-related", {})
        self.assertEqual(status, 200)
        self.assertEqual(payload["created"], 1)
        self.assertEqual(len(payload["edge_ids"]), 1)

        status, repeat = self.request_json("POST", "/api/link-related", {})
        self.assertEqual(status, 200)
        self.assertEqual(repeat["created"], 0)

    def test_demo_seed_and_overview_workflow(self) -> None:
        status, demo = self.request_json("POST", "/api/demo", {})
        self.assertEqual(status, 200)
        self.assertGreaterEqual(demo["stats"]["papers"], 3)
        self.assertGreaterEqual(demo["stats"]["claims"], 3)
        self.assertGreaterEqual(demo["stats"]["questions"], 1)

        status, overview = self.request_json("GET", "/api/overview")
        self.assertEqual(status, 200)
        self.assertTrue(overview["check"]["passed"])
        self.assertGreaterEqual(len(overview["papers"]), 3)
        self.assertGreaterEqual(len(overview["questions"]), 1)

    def test_create_entities_and_synthesize_via_web_api(self) -> None:
        status, q_res = self.request_json(
            "POST", "/api/questions", {"text": "Does sleep consolidate memory?"}
        )
        self.assertEqual(status, 200)
        qid = q_res["question"]["id"]

        status, p_res = self.request_json(
            "POST",
            "/api/papers",
            {
                "title": "Sleep Spindles and Memory",
                "authors": "Elena Vance",
                "year": "2024",
                "venue": "Nature",
                "doi": "10.1038/sleep.2024",
                "abstract": "Slow-wave sleep increased memory recall accuracy by 28% compared with wakeful rest.",
            },
        )
        self.assertEqual(status, 200)
        pid = p_res["paper"]["id"]

        status, c_res = self.request_json(
            "POST",
            "/api/claims",
            {
                "paper": pid,
                "text": "Slow-wave sleep increases recall by 28%.",
                "quote": "Slow-wave sleep increased memory recall accuracy by 28% compared with wakeful rest.",
                "locator": "abstract:s1",
                "stance": "supports",
                "confidence": 0.9,
                "question": qid,
            },
        )
        self.assertEqual(status, 200)
        cid = c_res["claim"]["id"]

        status, syn = self.request_json("GET", f"/api/synthesize?target={qid}&tokens=1500")
        self.assertEqual(status, 200)
        self.assertEqual(syn["mode"], "question")
        self.assertEqual(syn["consensus"]["supporting_count"], 1)

        status, sub = self.request_json("GET", f"/api/subgraph?ref={cid}&depth=1")
        self.assertEqual(status, 200)
        self.assertGreaterEqual(len(sub["nodes"]), 2)

        status, upd = self.request_json(
            "POST", "/api/question-status", {"question": qid, "status": "answered"}
        )
        self.assertEqual(status, 200)
        self.assertEqual(upd["question"]["status"], "answered")

    def test_discover_extract_and_search_endpoints(self) -> None:
        status, disc = self.request_json(
            "POST",
            "/api/discover",
            {"query": "sleep memory", "source": "offline", "limit": 2, "ingest": True},
        )
        self.assertEqual(status, 200)
        self.assertGreaterEqual(disc["count"], 1)

        status, ext = self.request_json("POST", "/api/extract", {"all": True})
        self.assertEqual(status, 200)
        self.assertGreaterEqual(ext["claims_created"], 1)

        status, search = self.request_json("GET", "/api/search?q=sleep&stance=supports")
        self.assertEqual(status, 200)
        self.assertGreaterEqual(len(search["papers"]), 1)

    def test_ingest_text_matrix_contradictions_and_export(self) -> None:
        bib = (
            "@article{vance2023,\n"
            "  title = {Slow-Wave Sleep Consolidates Hippocampal Memory},\n"
            "  author = {Elena Vance},\n"
            "  year = {2023},\n"
            "  doi = {10.1000/sws.bib.1},\n"
            "  abstract = {Slow-wave sleep stimulation significantly improved hippocampal declarative memory recall by 24%.}\n"
            "}"
        )
        status, ing = self.request_json(
            "POST",
            "/api/ingest-text",
            {"format": "bibtex", "text": bib, "extract": True},
        )
        self.assertEqual(status, 200)
        self.assertEqual(ing["ingested"], 1)
        self.assertGreaterEqual(ing["claims_created"], 1)

        status, demo = self.request_json("POST", "/api/demo", {})
        self.assertEqual(status, 200)

        status, mat = self.request_json("GET", "/api/matrix")
        self.assertEqual(status, 200)
        self.assertIn("matrix", mat)
        self.assertIn("contradictions", mat)
        self.assertIn("keystone", mat)
        self.assertGreaterEqual(len(mat["matrix"]["papers"]), 3)

        status, det = self.request_json(
            "POST", "/api/detect-contradictions", {"auto_link": True}
        )
        self.assertEqual(status, 200)
        self.assertIn("contradictions", det)

        exp_resp = dispatch_web_request(self.repository, "GET", "/api/export")
        self.assertEqual(exp_resp.status, 200)
        self.assertIn("application/x-ndjson", exp_resp.content_type)
        self.assertIn('"record_type": "paper"', exp_resp.body)

    def test_literature_search_ui_graph_and_api(self) -> None:
        status, p_res = self.request_json(
            "POST",
            "/api/papers",
            {
                "title": "A Randomized Controlled Trial of Sleep and Memory",
                "authors": "Elena Vance",
                "year": "2024",
                "tags": "sleep; memory",
                "study_type": "Randomized Controlled Trial",
                "abstract": "Slow-wave sleep increased recall accuracy by 28%.",
            },
        )
        self.assertEqual(status, 200)
        pid = p_res["paper"]["id"]

        status, lit = self.request_json(
            "GET",
            "/api/literature?q=Slow-wave%20sleep%20increased%20recall%20accuracy"
            "&tags=memory&study_type=Randomized%20Controlled%20Trial",
        )
        self.assertEqual(status, 200)
        self.assertEqual(len(lit["papers"]), 1)
        self.assertEqual(lit["papers"][0]["id"], pid)
        self.assertEqual(lit["papers"][0]["study_type"], "Randomized Controlled Trial")
        self.assertIn("sleep", lit["papers"][0]["tags"])

        status, sub = self.request_json("GET", f"/api/subgraph?ref={pid}&depth=1")
        self.assertEqual(status, 200)
        node = next(node for node in sub["nodes"] if node["ref"] == f"paper:{pid}")
        self.assertEqual(node["study_type"], "Randomized Controlled Trial")

        html = dispatch_web_request(self.repository, "GET", "/")
        self.assertIn("Literature Search", html.body)
        self.assertIn("Search tags, words or sentences", html.body)
        self.assertIn("n.study_type", html.body)

    def test_validation_error_and_not_found(self) -> None:
        status, err = self.request_json("POST", "/api/questions", {"text": ""})
        self.assertEqual(status, 400)
        self.assertIn("Error:", err["error"])

        status, missing = self.request_json("GET", "/api/unknown")
        self.assertEqual(status, 404)
        self.assertIn("not found", missing["error"])

    def test_api_outline_endpoint(self) -> None:
        self.request_json("POST", "/api/demo", {})
        status, payload = self.request_json("GET", "/api/outline?tokens=350")
        self.assertEqual(status, 200)
        self.assertIn("counts", payload)
        self.assertGreaterEqual(payload["counts"]["papers"], 3)
        self.assertIn("questions", payload)
        self.assertIn("study_types", payload)

    def test_api_export_bibtex_endpoint(self) -> None:
        self.request_json("POST", "/api/demo", {})
        resp = dispatch_web_request(self.repository, "GET", "/api/export-bibtex")
        self.assertEqual(resp.status, 200)
        self.assertIn("application/x-bibtex", resp.content_type)
        self.assertIn("@article{", resp.body)
        self.assertIn("filename=", resp.headers.get("Content-Disposition", ""))


if __name__ == "__main__":
    unittest.main()

