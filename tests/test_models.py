"""Identity, validation and budget helpers."""

import unittest

from lattice.errors import LatticeError
from lattice.models import (
    bare_id,
    derive_tags,
    estimate_tokens,
    infer_study_type,
    normalize_tags,
    normalize_text,
    paper_id,
    parse_confidence,
    validate_edge_kind,
    validate_ref,
    validate_stance,
)


class IdentityTests(unittest.TestCase):
    """Stable identifiers make dedupe and citations reproducible."""

    def test_doi_wins_over_title(self):
        self.assertEqual(paper_id("A title", "10.1/ABC"), paper_id("Another", "10.1/abc"))

    def test_arxiv_is_next(self):
        self.assertEqual(paper_id("A", arxiv="2401.00001"), paper_id("B", arxiv="2401.00001"))

    def test_title_normalization(self):
        self.assertEqual(normalize_text("  Deep  Learning! "), "deep learning")

    def test_empty_identity_is_refused(self):
        with self.assertRaises(LatticeError):
            paper_id("   ")

    def test_bare_id(self):
        self.assertEqual(bare_id("claim:c_000003"), "c_000003")


class ValidationTests(unittest.TestCase):
    """User input fails with the triad instead of a traceback."""

    def test_stance_accepts_case(self):
        self.assertEqual(validate_stance("SUPPORTS"), "supports")

    def test_stance_rejects_unknown(self):
        with self.assertRaises(LatticeError):
            validate_stance("maybe")

    def test_confidence_range(self):
        self.assertEqual(parse_confidence(None), 0.5)
        self.assertEqual(parse_confidence(1), 1.0)
        with self.assertRaises(LatticeError):
            parse_confidence(1.1)

    def test_edge_kind(self):
        self.assertEqual(validate_edge_kind("CITES"), "cites")
        with self.assertRaises(LatticeError):
            validate_edge_kind("likes")

    def test_reference_forms(self):
        self.assertEqual(validate_ref("paper:p_abc123"), "paper:p_abc123")
        with self.assertRaises(LatticeError):
            validate_ref("paper:c_000001")
        with self.assertRaises(LatticeError):
            validate_ref("nonsense")

    def test_tokens_are_positive(self):
        self.assertGreaterEqual(estimate_tokens(""), 1)


class LiteratureMetadataTests(unittest.TestCase):
    """Study types and tags are normalized deterministically from paper metadata."""

    def test_study_type_inference(self):
        self.assertEqual(
            infer_study_type("A randomized controlled trial of slow-wave sleep"),
            "Randomized Controlled Trial",
        )
        self.assertEqual(
            infer_study_type("A meta-analysis of sleep and memory"),
            "Meta-Analysis",
        )
        self.assertEqual(
            infer_study_type("Sleep and memory in older adults",
                             "We conducted a cohort study of 1,200 participants."),
            "Cohort Study",
        )
        self.assertEqual(
            infer_study_type("An in vitro assay of hippocampal cells"),
            "In Vitro Study",
        )
        self.assertEqual(
            infer_study_type("A study with no design marker"),
            "General Study",
        )

    def test_tag_normalization_and_derivation(self):
        self.assertEqual(normalize_tags("Sleep; Memory, sleep"), "sleep, memory")
        tags = derive_tags(
            "Slow-Wave Sleep Consolidates Hippocampal Memory",
            "Sleep improved recall in older adults.",
        )
        self.assertIn("sleep", tags.split(", "))
        self.assertIn("memory", tags.split(", "))


if __name__ == "__main__":
    unittest.main()
