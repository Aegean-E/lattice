"""Tests for automated knowledge creation and claim extraction from ingested papers."""

import sqlite3
import unittest

from lattice.database import open_database
from lattice.errors import LatticeError
from lattice.extraction import (
    ExtractionResult,
    extract_all,
    extract_from_paper,
    infer_confidence,
    infer_stance,
    split_empirical_sentences,
)
from lattice.repository import Repository


class ExtractionTests(unittest.TestCase):
    """Verify deterministic sentence splitting, stance/confidence scoring, and claim/edge creation."""

    def setUp(self) -> None:
        self.connection: sqlite3.Connection = open_database(":memory:")
        self.addCleanup(self.connection.close)
        self.repository = Repository(self.connection)

    def test_split_empirical_sentences_handles_abbreviations_and_decimals(self) -> None:
        abstract = (
            "Background context only. Slow-wave sleep increased recall accuracy by 28.5% "
            "compared with wakeful rest (p < 0.01) in Dr. Smith et al. trials. "
            "However, REM suppression did not impair motor sequence retention."
        )
        sentences = split_empirical_sentences(abstract)
        self.assertEqual(len(sentences), 2)
        self.assertIn("28.5%", sentences[0][1])
        self.assertEqual(sentences[0][0], "abstract:s2")
        self.assertEqual(sentences[1][0], "abstract:s3")

    def test_infer_stance_and_confidence(self) -> None:
        supporting = "Slow-wave sleep increased recall accuracy by 28% compared with wakeful rest."
        contradicting = "REM suppression did not reduce procedural motor retention in 60 adults."
        neutral = "We analyzed cortical recordings across three nocturnal sessions."
        self.assertEqual(infer_stance(supporting), "supports")
        self.assertEqual(infer_stance(contradicting), "contradicts")
        self.assertEqual(infer_stance(neutral), "mentions")
        self.assertGreater(infer_confidence(supporting), infer_confidence(neutral))

    def test_extract_from_paper_creates_claims_and_links_question(self) -> None:
        question = self.repository.add_question("Does sleep consolidate memory recall?")
        paper, _ = self.repository.add_paper({
            "title": "Sleep Spindles and Memory Consolidation",
            "authors": "Elena Vance",
            "year": "2024",
            "abstract": (
                "Slow-wave sleep increased memory recall accuracy by 28% compared with wakeful rest. "
                "Deprivation failed to improve retention in control subjects."
            ),
        })
        result = extract_from_paper(self.repository, paper.id, question_ref=question.id)
        self.assertIsInstance(result, ExtractionResult)
        self.assertEqual(result.paper_id, paper.id)
        self.assertEqual(len(result.claims), 2)
        self.assertEqual(len(result.edges), 2)

        repeat = extract_from_paper(self.repository, paper.id, question_ref=question.id)
        self.assertEqual(len(repeat.claims), 0)
        self.assertEqual(self.repository.stats()["claims"], 2)

    def test_extract_all_processes_every_paper_and_auto_matches_questions(self) -> None:
        question = self.repository.add_question("Does slow-wave sleep improve declarative memory?")
        self.repository.add_paper({
            "title": "Hippocampal Replay in Slow-Wave Sleep",
            "abstract": "Slow-wave sleep significantly improved declarative memory recall by 31%.",
        })
        self.repository.add_paper({
            "title": "Paper Without Abstract",
            "abstract": "",
        })
        summary = extract_all(self.repository)
        self.assertEqual(summary["papers_processed"], 2)
        self.assertEqual(summary["claims_created"], 1)
        self.assertGreaterEqual(summary["edges_created"], 1)
        evidence = self.repository.evidence(question.id)
        self.assertEqual(len(evidence["supports"]), 1)

    def test_extract_from_missing_paper_raises_lattice_error(self) -> None:
        with self.assertRaises(LatticeError):
            extract_from_paper(self.repository, "p_deadbeef0000")


if __name__ == "__main__":
    unittest.main()

