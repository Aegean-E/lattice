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

    def test_validation_error_and_not_found(self) -> None:
        status, err = self.request_json("POST", "/api/questions", {"text": ""})
        self.assertEqual(status, 400)
        self.assertIn("Error:", err["error"])

        status, missing = self.request_json("GET", "/api/unknown")
        self.assertEqual(status, 404)
        self.assertIn("not found", missing["error"])


if __name__ == "__main__":
    unittest.main()
