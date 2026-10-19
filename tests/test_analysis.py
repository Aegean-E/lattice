"""Unit tests for scientific contradiction detection, keystone centrality, and evidence matrix analysis."""

import sqlite3
import unittest

from lattice.analysis import (
    ContradictionPair,
    build_evidence_matrix,
    detect_contradictions,
    rank_influential_entities,
)
from lattice.database import open_database
from lattice.repository import Repository


class TestAnalysis(unittest.TestCase):
    """Verify contradiction detection, keystone entity ranking, and Paper x Question evidence matrix."""

    def setUp(self) -> None:
        self.connection: sqlite3.Connection = open_database(":memory:")
        self.addCleanup(self.connection.close)
        self.repo = Repository(self.connection)

    def _seed_conflicting_graph(self) -> dict:
        p1, _ = self.repo.add_paper({
            "title": "Slow-Wave Sleep Consolidates Hippocampal Memory",
            "authors": "Elena Vance",
            "year": "2023",
            "doi": "10.1000/sws.1",
        })
        p2, _ = self.repo.add_paper({
            "title": "Declarative Recall Without Slow-Wave Enhancement",
            "authors": "Arjun Patel",
            "year": "2024",
            "doi": "10.1000/sws.2",
        })
        c1 = self.repo.add_claim(
            paper=p1.id,
            text="Slow-wave sleep stimulation significantly improves hippocampal declarative memory recall.",
            quote="Closed-loop slow-wave sleep stimulation improved hippocampal declarative memory recall by 24%.",
            locator="Results",
            stance="supports",
            confidence=0.9,
        )
        c2 = self.repo.add_claim(
            paper=p2.id,
            text="Slow-wave sleep stimulation fails to improve hippocampal declarative memory recall.",
            quote="Acoustic slow-wave sleep stimulation failed to improve hippocampal declarative memory recall.",
            locator="Discussion",
            stance="contradicts",
            confidence=0.82,
        )
        q1 = self.repo.add_question(
            "Does slow-wave sleep stimulation improve hippocampal declarative memory?"
        )
        q2 = self.repo.add_question(
            "What is the role of thalamic spindles in motor learning?"
        )
        self.repo.add_edge(c1.id, q1.id, kind="answers", note="Direct positive trial")
        self.repo.add_edge(c2.id, q1.id, kind="answers", note="Null replication trial")
        self.repo.add_edge(p2.id, p1.id, kind="cites", note="Replication target")
        return {"p1": p1, "p2": p2, "c1": c1, "c2": c2, "q1": q1, "q2": q2}

    def test_detect_contradictions_and_idempotent_auto_link(self) -> None:
        seeded = self._seed_conflicting_graph()
        pairs = detect_contradictions(self.repo, auto_link=False)
        self.assertEqual(len(pairs), 1)
        pair = pairs[0]
        self.assertIsInstance(pair, ContradictionPair)
        self.assertEqual({pair.claim_a_id, pair.claim_b_id}, {seeded["c1"].id, seeded["c2"].id})
        self.assertIn(seeded["q1"].id, pair.shared_question_ids)
        self.assertIn("hippocampal", pair.shared_keywords)
        self.assertIsNone(pair.linked_edge_id)

        linked_pairs = detect_contradictions(self.repo, auto_link=True)
        self.assertEqual(len(linked_pairs), 1)
        self.assertIsNotNone(linked_pairs[0].linked_edge_id)

        # Calling a second time with auto_link=True must be idempotent
        linked_again = detect_contradictions(self.repo, auto_link=True)
        self.assertEqual(linked_again[0].linked_edge_id, linked_pairs[0].linked_edge_id)

    def test_rank_influential_entities_returns_keystone_papers_and_claims(self) -> None:
        seeded = self._seed_conflicting_graph()
        ranking = rank_influential_entities(self.repo, limit=5)
        self.assertIn("papers", ranking)
        self.assertIn("claims", ranking)
        self.assertGreaterEqual(len(ranking["papers"]), 2)
        self.assertGreaterEqual(len(ranking["claims"]), 2)
        top_paper_ids = [item["id"] for item in ranking["papers"]]
        self.assertIn(seeded["p1"].id, top_paper_ids)
        self.assertGreater(ranking["papers"][0]["score"], 0.0)
        self.assertGreater(ranking["claims"][0]["score"], 0.0)

    def test_build_evidence_matrix_identifies_cells_and_coverage_gaps(self) -> None:
        seeded = self._seed_conflicting_graph()
        matrix = build_evidence_matrix(self.repo)
        self.assertEqual(len(matrix["papers"]), 2)
        self.assertEqual(len(matrix["questions"]), 2)
        self.assertEqual(len(matrix["cells"]), 2)

        q_by_id = {q["id"]: q for q in matrix["questions"]}
        self.assertEqual(q_by_id[seeded["q1"].id]["supporting_count"], 1)
        self.assertEqual(q_by_id[seeded["q1"].id]["contradicting_count"], 1)
        self.assertFalse(q_by_id[seeded["q1"].id]["coverage_gap"])
        self.assertTrue(q_by_id[seeded["q2"].id]["coverage_gap"])

        gap_ids = [g["question_id"] for g in matrix["gaps"]]
        self.assertIn(seeded["q2"].id, gap_ids)


if __name__ == "__main__":
    unittest.main()
