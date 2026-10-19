"""Unit tests for the token-budgeted, RLM-style AI context views."""

import sqlite3
import unittest

from lattice.context import (
    MIN_TOKENS,
    compact_related,
    compact_search,
    compact_subgraph,
    outline,
)
from lattice.database import open_database
from lattice.errors import LatticeError
from lattice.repository import Repository


class ContextViewTests(unittest.TestCase):
    """Verify compact payloads, truncation, omission counts and the budget floor."""

    def setUp(self) -> None:
        self.connection: sqlite3.Connection = open_database(":memory:")
        self.addCleanup(self.connection.close)
        self.repo = Repository(self.connection)

    def test_outline_reports_counts_questions_and_study_types(self) -> None:
        question = self.repo.add_question("Does sleep consolidate memory?")
        paper, _ = self.repo.add_paper({
            "title": "Sleep Study",
            "abstract": "A randomized trial of sleep and memory.",
            "study_type": "Randomized Controlled Trial",
        })
        claim = self.repo.add_claim(
            paper.id, "Sleep improves memory.", "Sleep improves memory.", stance="supports")
        self.repo.add_edge(claim.id, question.id, kind="answers")

        result = outline(self.repo, tokens=400)
        self.assertEqual(result["counts"]["papers"], 1)
        self.assertEqual(result["counts"]["claims"], 1)
        self.assertEqual(result["counts"]["questions"], 1)
        self.assertEqual(result["edge_kinds"], {"answers": 1})
        self.assertEqual(result["questions"][0]["ref"], f"question:{question.id}")
        self.assertEqual(result["questions"][0]["evidence"], 1)
        self.assertEqual(result["study_types"][0]["study_type"], "Randomized Controlled Trial")
        self.assertIn("get_entity", result["next"])

    def test_outline_omits_questions_over_a_small_budget(self) -> None:
        for index in range(20):
            self.repo.add_question(f"Question number {index} about a distinct topic?")
        small = outline(self.repo, tokens=150)
        large = outline(self.repo, tokens=1200)
        self.assertLess(len(small["questions"]), len(large["questions"]))
        self.assertGreater(small["omitted_questions"], 0)
        self.assertEqual(large["omitted_questions"], 0)

    def test_compact_search_truncates_items_and_reports_omissions(self) -> None:
        result = {
            "query": "sleep",
            "papers": [
                {"id": f"p_{index:012d}", "title": "A very long paper title " * 8,
                 "year": "2024", "study_type": "Cohort Study", "abstract": "abstract " * 200}
                for index in range(12)
            ],
            "claims": [
                {"id": f"c_{index:06d}", "text": "A long claim sentence " * 12,
                 "stance": "supports", "confidence": 0.8, "paper": {"id": "p_000000000001"}}
                for index in range(12)
            ],
            "questions": [
                {"id": f"q_{index:06d}", "text": "A long research question " * 10,
                 "status": "open"}
                for index in range(12)
            ],
        }
        compact = compact_search(result, tokens=300)
        self.assertLess(len(compact["papers"]), 12)
        self.assertGreater(
            compact["omitted_papers"] + compact["omitted_claims"]
            + compact["omitted_questions"], 0)
        self.assertNotIn("abstract", compact["papers"][0])
        self.assertTrue(compact["papers"][0]["ref"].startswith("paper:"))
        self.assertTrue(compact["claims"][0]["ref"].startswith("claim:"))
        self.assertLessEqual(len(compact["claims"][0]["snippet"]), 160)
        self.assertLessEqual(len(compact["questions"][0]["text"]), 120)
        self.assertIn("get_entity", compact["next"])

    def test_compact_related_drops_full_text_but_keeps_reasons_and_refs(self) -> None:
        result = {
            "root": "claim:c_000001",
            "type": "claim",
            "related": [
                {
                    "ref": f"claim:c_{index:06d}",
                    "text": "Full claim text " * 40,
                    "stance": "supports",
                    "confidence": 0.7,
                    "paper": "p_000000000001",
                    "study_type": "Meta-Analysis",
                    "relation": "related",
                    "reason": "shares question q_000001; keywords: memory, sleep",
                    "via": ["c_000001"],
                }
                for index in range(10)
            ],
        }
        compact = compact_related(result, tokens=300)
        self.assertLess(compact["count"], 10)
        self.assertGreater(compact["omitted"], 0)
        item = compact["related"][0]
        self.assertEqual(item["ref"], "claim:c_000000")
        self.assertLessEqual(len(item["snippet"]), 160)
        self.assertIn("shares question", item["reason"])
        self.assertEqual(item["study_type"], "Meta-Analysis")
        self.assertIn("related_findings", compact["next"])

    def test_compact_subgraph_keeps_only_edges_between_kept_nodes(self) -> None:
        nodes = [
            {"ref": f"claim:c_{index:06d}", "type": "claim", "text": "Node text " * 30,
             "study_type": "Cohort Study"}
            for index in range(20)
        ]
        edges = [
            {"src": nodes[0]["ref"], "dst": nodes[index]["ref"], "kind": "related",
             "note": "verbose note " * 40, "id": index, "created_at": "2026-01-01"}
            for index in range(1, 20)
        ]
        result = {"root": "question:q_000001", "depth": 2, "nodes": nodes, "edges": edges}
        compact = compact_subgraph(result, tokens=400)
        kept_refs = {node["ref"] for node in compact["nodes"]}
        self.assertGreater(compact["omitted_nodes"], 0)
        self.assertGreater(compact["omitted_edges"], 0)
        self.assertTrue(all(
            edge["src"] in kept_refs and edge["dst"] in kept_refs
            for edge in compact["edges"]))
        self.assertTrue(all(
            set(edge) == {"src", "dst", "kind"} for edge in compact["edges"]))
        self.assertEqual(compact["depth"], 2)
        self.assertIn("subgraph", compact["next"])

    def test_budgets_below_the_floor_fail_with_the_triad(self) -> None:
        calls = (
            lambda: outline(self.repo, tokens=0),
            lambda: compact_search({"query": "x"}, tokens=MIN_TOKENS - 1),
            lambda: compact_related({"related": []}, tokens=1),
            lambda: compact_subgraph({"nodes": [], "edges": []}, tokens=MIN_TOKENS - 1),
        )
        for call in calls:
            with self.assertRaises(LatticeError):
                call()


if __name__ == "__main__":
    unittest.main()
