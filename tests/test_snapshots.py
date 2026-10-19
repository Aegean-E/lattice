"""Tests for knowledge interaction: multi-term search, subgraphs, question status, and snapshots."""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from lattice.database import open_database
from lattice.errors import LatticeError
from lattice.repository import Repository
from lattice.snapshots import export_snapshot, import_snapshot


class InteractionAndSnapshotTests(unittest.TestCase):
    """Verify multi-term search, subgraph traversal, question status, and JSONL snapshot I/O."""

    def setUp(self) -> None:
        self.connection: sqlite3.Connection = open_database(":memory:")
        self.addCleanup(self.connection.close)
        self.repository = Repository(self.connection)

    def test_multi_term_search_and_filters(self) -> None:
        p1, _ = self.repository.add_paper({
            "title": "Hippocampal Slow-Wave Oscillations in Declarative Memory",
            "authors": "Elena Vance",
            "year": "2023",
            "abstract": "Slow-wave sleep stabilizes memory traces.",
        })
        p2, _ = self.repository.add_paper({
            "title": "Cortical Motor Plasticity During Wakefulness",
            "authors": "Haruki Sato",
            "year": "2024",
            "abstract": "Motor skill retention remained stable without sleep.",
        })
        self.repository.add_claim(
            p1.id, "Slow-wave sleep improves recall by 28%.",
            "Slow-wave sleep stabilizes memory traces.", stance="supports", confidence=0.85,
        )
        self.repository.add_claim(
            p2.id, "Wakeful rest does not impair motor retention.",
            "Motor skill retention remained stable without sleep.",
            stance="contradicts", confidence=0.60,
        )
        multi = self.repository.search("hippocampal memory traces")
        self.assertGreaterEqual(len(multi["papers"]), 1)
        self.assertEqual(multi["papers"][0]["id"], p1.id)

        filtered = self.repository.search(
            "sleep memory retention", stance="supports", min_confidence=0.80, year="2023"
        )
        self.assertEqual(len(filtered["papers"]), 1)
        self.assertEqual(filtered["papers"][0]["id"], p1.id)
        self.assertEqual(len(filtered["claims"]), 1)
        self.assertEqual(filtered["claims"][0]["stance"], "supports")

    def test_subgraph_traverses_multi_hop_neighborhood(self) -> None:
        paper, _ = self.repository.add_paper({"title": "Graph Paper", "year": "2025"})
        claim = self.repository.add_claim(paper.id, "Claim one", "Quote one", stance="supports")
        question = self.repository.add_question("Does graph traversal work?")
        self.repository.add_edge(f"claim:{claim.id}", f"question:{question.id}", "supports")
        self.repository.add_edge(f"claim:{claim.id}", f"paper:{paper.id}", "cites")

        hop1 = self.repository.subgraph(question.id, depth=1)
        node_refs_1 = {node["ref"] for node in hop1["nodes"]}
        self.assertIn(f"question:{question.id}", node_refs_1)
        self.assertIn(f"claim:{claim.id}", node_refs_1)
        self.assertNotIn(f"paper:{paper.id}", node_refs_1)

        hop2 = self.repository.subgraph(question.id, depth=2)
        node_refs_2 = {node["ref"] for node in hop2["nodes"]}
        self.assertIn(f"paper:{paper.id}", node_refs_2)
        self.assertEqual(len(hop2["edges"]), 2)

        with self.assertRaises(LatticeError):
            self.repository.subgraph(question.id, depth=0)

    def test_set_question_status_updates_and_validates(self) -> None:
        question = self.repository.add_question("Is this question answered?")
        updated = self.repository.set_question_status(question.id, "answered")
        self.assertEqual(updated.status, "answered")
        with self.assertRaises(LatticeError):
            self.repository.set_question_status(question.id, "invalid_status")

    def test_export_and_import_snapshot_roundtrip_is_idempotent(self) -> None:
        paper, _ = self.repository.add_paper({
            "title": "Portable Knowledge Graphs",
            "authors": "Ada Lovelace",
            "year": "2025",
            "doi": "10.1000/pkg.2025",
            "abstract": "Snapshots preserve papers, claims, questions and edges.",
        })
        claim = self.repository.add_claim(
            paper.id,
            "Snapshots preserve all entities.",
            "Snapshots preserve papers, claims, questions and edges.",
            locator="abstract:s1",
            stance="supports",
            confidence=0.9,
        )
        question = self.repository.add_question("Do snapshots preserve provenance?")
        self.repository.add_edge(
            f"claim:{claim.id}", f"question:{question.id}", "supports", note="direct proof"
        )

        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        bundle_path = Path(temp_dir.name) / "graph.jsonl"

        exported = export_snapshot(self.repository, bundle_path)
        self.assertEqual(exported["papers"], 1)
        self.assertEqual(exported["claims"], 1)
        self.assertEqual(exported["questions"], 1)
        self.assertEqual(exported["edges"], 1)
        self.assertTrue(bundle_path.exists())

        conn2 = open_database(":memory:")
        self.addCleanup(conn2.close)
        repo2 = Repository(conn2)

        imported = import_snapshot(repo2, bundle_path)
        self.assertEqual(imported["papers"], 1)
        self.assertEqual(imported["claims"], 1)
        self.assertEqual(imported["questions"], 1)
        self.assertEqual(imported["edges"], 1)
        self.assertEqual(repo2.stats()["edges"], 1)

        repeat = import_snapshot(repo2, bundle_path)
        self.assertEqual(repeat["claims_created"], 0)
        self.assertEqual(repo2.stats()["claims"], 1)
        self.assertEqual(repo2.stats()["edges"], 1)


if __name__ == "__main__":
    unittest.main()

