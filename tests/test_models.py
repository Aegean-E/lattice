"""Identity, validation and budget helpers."""

import unittest

from lattice.errors import LatticeError
from lattice.models import (
    bare_id,
    estimate_tokens,
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


if __name__ == "__main__":
    unittest.main()
