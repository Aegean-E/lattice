"""Tests for scientific literature synthesis: consensus scoring, thematic clusters, and BibTeX."""

import sqlite3
import unittest

from lattice.database import open_database
from lattice.errors import LatticeError
from lattice.repository import Repository
from lattice.synthesis import (
    SynthesisReport,
    compute_consensus,
    format_bibtex,
    synthesize,
)


class SynthesisTests(unittest.TestCase):
    """Verify consensus scoring, thematic clustering, follow-up queries, and BibTeX generation."""

    def setUp(self) -> None:
        self.connection: sqlite3.Connection = open_database(":memory:")
        self.addCleanup(self.connection.close)
        self.repository = Repository(self.connection)

    def test_compute_consensus_handles_support_contradiction_and_empty(self) -> None:
        empty = compute_consensus([], [])
        self.assertEqual(empty["label"], "insufficient_evidence")
        self.assertEqual(empty["score"], 0.0)

        strong = compute_consensus([{"confidence": 0.9}, {"confidence": 0.8}], [])
        self.assertEqual(strong["label"], "strong_support")
        self.assertEqual(strong["score"], 1.0)

        contested = compute_consensus([{"confidence": 0.8}], [{"confidence": 0.7}])
        self.assertEqual(contested["label"], "contested")
        self.assertTrue(-0.5 < contested["score"] < 0.5)

        refuted = compute_consensus([], [{"confidence": 0.85}])
        self.assertEqual(refuted["label"], "contradicted")
        self.assertEqual(refuted["score"], -1.0)

    def test_synthesize_question_produces_structured_ai_pack_and_markdown(self) -> None:
        q = self.repository.add_question("Does slow-wave sleep consolidate declarative memory?")
        p1, _ = self.repository.add_paper({
            "title": "Hippocampal Replay During Slow-Wave Sleep",
            "authors": "Elena Vance; Marcus Chen",
            "year": "2023",
            "venue": "Nature Neuroscience",
            "doi": "10.1038/nn.2023.014",
            "abstract": "Slow-wave sleep increased recall accuracy by 28%.",
        })
        p2, _ = self.repository.add_paper({
            "title": "Acoustic Spindle Stimulation in Nocturnal Sleep",
            "authors": "Haruki Sato",
            "year": "2024",
            "venue": "Sleep",
            "doi": "10.1093/sleep/zsae042",
            "abstract": "Spindle stimulation during slow-wave sleep improved memory retention.",
        })
        c1 = self.repository.add_claim(
            p1.id,
            "Slow-wave sleep increased declarative recall accuracy by 28%.",
            "Slow-wave sleep increased recall accuracy by 28%.",
            locator="abstract:s1",
            stance="supports",
            confidence=0.90,
        )
        c2 = self.repository.add_claim(
            p2.id,
            "Spindle stimulation during slow-wave sleep improved memory retention.",
            "Spindle stimulation during slow-wave sleep improved memory retention.",
            locator="abstract:s1",
            stance="supports",
            confidence=0.80,
        )
        self.repository.add_edge(f"claim:{c1.id}", f"question:{q.id}", "supports")
        self.repository.add_edge(f"claim:{c2.id}", f"question:{q.id}", "supports")

        report = synthesize(self.repository, q.id, tokens=2500)
        self.assertIsInstance(report, SynthesisReport)
        payload = report.to_dict()
        self.assertEqual(payload["mode"], "question")
        self.assertEqual(payload["consensus"]["label"], "strong_support")
        self.assertEqual(payload["consensus"]["supporting_count"], 2)
        self.assertGreaterEqual(len(payload["clusters"]), 1)
        self.assertEqual(len(payload["bibliography"]), 2)
        self.assertIn("@article{", payload["bibtex"])
        self.assertIn("# Literature Synthesis:", payload["markdown"])
        self.assertIn(c1.id, payload["markdown"])
        self.assertIn("10.1038/nn.2023.014", payload["markdown"])

    def test_synthesize_search_phrase_and_bibtex_formatting(self) -> None:
        paper, _ = self.repository.add_paper({
            "title": "Quote-Backed Evidence Graphs",
            "authors": "Ada Lovelace",
            "year": "2025",
            "venue": "JAIR",
            "doi": "10.1613/jair.2025.109",
        })
        self.repository.add_claim(
            paper.id,
            "Evidence graphs reduce citation drift by 73%.",
            "Evidence graphs reduce citation drift by 73%.",
            stance="supports",
            confidence=0.92,
        )
        report = synthesize(self.repository, "citation drift", tokens=1500)
        self.assertEqual(report.mode, "search")
        self.assertEqual(report.consensus["supporting_count"], 1)
        bib = format_bibtex([paper.to_dict()])
        self.assertIn(f"@article{{{paper.id},", bib)
        self.assertIn("title = {Quote-Backed Evidence Graphs}", bib)

    def test_synthesize_rejects_tiny_token_budget(self) -> None:
        with self.assertRaises(LatticeError):
            synthesize(self.repository, "memory", tokens=100)


if __name__ == "__main__":
    unittest.main()

