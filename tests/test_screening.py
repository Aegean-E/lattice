"""Unit tests for PRISMA 2020 systematic review screening and flow generation."""

import tempfile
import unittest
from pathlib import Path

from lattice.database import open_database
from lattice.errors import LatticeError
from lattice.repository import Repository
from lattice.screening import (
    DEFAULT_EXCLUSION_REASONS,
    SCREENING_STATUSES,
    PrismaFlow,
    ScreeningDecision,
    compute_prisma_flow,
    get_screening_decision,
    list_screening_decisions,
    record_screening_decision,
    render_prisma_markdown,
    render_prisma_svg,
)


class ScreeningTests(unittest.TestCase):
    """Test paper screening decisions, validation, and PRISMA 2020 flow computation."""

    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.db_path = Path(self.directory.name) / "test.db"
        self.connection = open_database(str(self.db_path))
        self.addCleanup(self.connection.close)
        self.repository = Repository(self.connection)

        # Seed 4 papers
        self.p1, _ = self.repository.add_paper({"title": "Study One: High Quality RCT", "study_type": "Randomized Controlled Trial"})
        self.p2, _ = self.repository.add_paper({"title": "Study Two: Observational Cohort", "study_type": "Cohort Study"})
        self.p3, _ = self.repository.add_paper({"title": "Study Three: Animal Trial", "study_type": "Animal Study"})
        self.p4, _ = self.repository.add_paper({"title": "Study Four: Non-peer reviewed preprint", "study_type": "Preprint"})

    def test_record_and_get_screening_decision(self) -> None:
        dec = record_screening_decision(
            self.repository,
            self.p1.id,
            status="included",
            notes="Meets all primary inclusion criteria",
        )
        self.assertEqual(dec.paper_id, self.p1.id)
        self.assertEqual(dec.status, "included")
        self.assertEqual(dec.notes, "Meets all primary inclusion criteria")

        retrieved = get_screening_decision(self.repository, self.p1.id)
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.status, "included")

    def test_record_exclusion_with_reason(self) -> None:
        dec = record_screening_decision(
            self.repository,
            self.p3.id,
            status="excluded",
            reason="animal_model",
            notes="Animal in vivo model only, human data required",
        )
        self.assertEqual(dec.status, "excluded")
        self.assertEqual(dec.reason, "animal_model")

    def test_invalid_status_raises_error(self) -> None:
        with self.assertRaises(LatticeError):
            record_screening_decision(self.repository, self.p1.id, status="invalid_status")

    def test_invalid_paper_id_raises_error(self) -> None:
        with self.assertRaises(LatticeError):
            record_screening_decision(self.repository, "p_nonexistent", status="included")

    def test_compute_prisma_flow(self) -> None:
        # p1: included
        record_screening_decision(self.repository, self.p1.id, status="included")
        # p2: screened_in
        record_screening_decision(self.repository, self.p2.id, status="screened_in")
        # p3: excluded at eligibility stage
        record_screening_decision(self.repository, self.p3.id, status="excluded", reason="animal_model")
        # p4: screened_out at title/abstract screening
        record_screening_decision(self.repository, self.p4.id, status="screened_out", reason="out_of_scope_design")

        flow = compute_prisma_flow(self.repository)
        self.assertIsInstance(flow, PrismaFlow)
        self.assertEqual(flow.identified, 4)
        self.assertEqual(flow.screened, 4)
        self.assertEqual(flow.screened_out, 1)
        self.assertEqual(flow.screened_out_reasons.get("out_of_scope_design"), 1)
        self.assertEqual(flow.assessed_for_eligibility, 3)
        self.assertEqual(flow.excluded, 1)
        self.assertEqual(flow.excluded_reasons.get("animal_model"), 1)
        self.assertEqual(flow.included, 1)

    def test_render_prisma_markdown(self) -> None:
        record_screening_decision(self.repository, self.p1.id, status="included")
        record_screening_decision(self.repository, self.p3.id, status="excluded", reason="animal_model")
        flow = compute_prisma_flow(self.repository)
        md = render_prisma_markdown(flow)
        self.assertIn("# PRISMA 2020 Flow Diagram", md)
        self.assertIn("Identification", md)
        self.assertIn("Screening", md)
        self.assertIn("Eligibility", md)
        self.assertIn("Included", md)
        self.assertIn("animal_model", md)

    def test_render_prisma_svg(self) -> None:
        record_screening_decision(self.repository, self.p1.id, status="included")
        record_screening_decision(self.repository, self.p4.id, status="screened_out", reason="out_of_scope_design")
        flow = compute_prisma_flow(self.repository)
        svg = render_prisma_svg(flow)
        self.assertTrue(svg.startswith("<svg"))
        self.assertTrue(svg.strip().endswith("</svg>"))
        self.assertIn("PRISMA 2020", svg)
        self.assertIn("Identification", svg)
        self.assertIn("Screening", svg)
        self.assertIn("Included", svg)


if __name__ == "__main__":
    unittest.main()
