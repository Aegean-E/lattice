"""Unit tests for quantitative meta-analysis, effect sizes and forest plots."""

import sqlite3
import unittest

from lattice.database import open_database
from lattice.meta import (
    MetaStudy,
    compute_meta_analysis,
    meta_analyze_question,
    render_forest_ascii,
    render_forest_svg,
    study_from_confidence_interval,
    study_from_two_groups,
)
from lattice.repository import Repository


class MetaAnalysisTests(unittest.TestCase):
    """Verify statistical pooling, heterogeneity metrics and forest plot renderers."""

    def test_fixed_effect_pooling_and_heterogeneity(self) -> None:
        studies = [
            {"id": "s1", "label": "Study A", "effect_size": 0.5, "se": 0.1},
            {"id": "s2", "label": "Study B", "effect_size": 1.0, "se": 0.1},
        ]
        res = compute_meta_analysis(studies, model="fixed")
        self.assertEqual(res.model, "fixed")
        self.assertAlmostEqual(res.pooled_effect, 0.75, places=2)
        self.assertAlmostEqual(res.cochran_q, 12.5, places=1)
        self.assertEqual(res.df, 1)
        self.assertAlmostEqual(res.i_squared, 92.0, places=1)
        self.assertLess(res.p_value, 0.01)

    def test_random_effects_pooling(self) -> None:
        studies = [
            MetaStudy("s1", "Chen et al. (2022)", 0.35, 0.12, 0.11, 0.59),
            MetaStudy("s2", "Vance et al. (2023)", 0.55, 0.10, 0.35, 0.75),
            MetaStudy("s3", "Kim et al. (2024)", 0.42, 0.14, 0.15, 0.69),
        ]
        res = compute_meta_analysis(studies, model="random")
        self.assertEqual(res.model, "random")
        self.assertGreater(res.pooled_effect, 0.4)
        self.assertLess(res.pooled_effect, 0.55)
        self.assertEqual(len(res.studies), 3)
        self.assertAlmostEqual(sum(s.weight for s in res.studies), 100.0, places=1)

    def test_study_from_confidence_interval(self) -> None:
        study = study_from_confidence_interval("s_ci", "Trial CI", 0.60, 0.20, 1.00)
        self.assertEqual(study.effect_size, 0.60)
        self.assertAlmostEqual(study.se, 0.2041, places=3)
        self.assertEqual(study.ci_lower, 0.20)
        self.assertEqual(study.ci_upper, 1.00)

    def test_study_from_two_groups(self) -> None:
        # Treatment: n=30, mean=112.5, sd=15.0
        # Control: n=30, mean=100.0, sd=14.0
        study = study_from_two_groups(
            "rct1", "Memory Trial",
            n1=30, m1=112.5, sd1=15.0,
            n2=30, m2=100.0, sd2=14.0,
        )
        self.assertGreater(study.effect_size, 0.7)
        self.assertLess(study.effect_size, 1.0)
        self.assertGreater(study.se, 0.2)
        self.assertEqual(study.study_type, "Randomized Controlled Trial")

    def test_render_forest_ascii(self) -> None:
        studies = [
            {"id": "s1", "label": "Study One", "effect_size": 0.40, "se": 0.10},
            {"id": "s2", "label": "Study Two", "effect_size": 0.60, "se": 0.12},
        ]
        res = compute_meta_analysis(studies, model="random")
        ascii_plot = render_forest_ascii(res)
        self.assertIn("Study One", ascii_plot)
        self.assertIn("Study Two", ascii_plot)
        self.assertIn("Pooled (Random)", ascii_plot)
        self.assertIn("Heterogeneity:", ascii_plot)
        self.assertIn("Q =", ascii_plot)

    def test_render_forest_svg(self) -> None:
        studies = [
            {"id": "s1", "label": "Study One", "effect_size": 0.40, "se": 0.10},
            {"id": "s2", "label": "Study Two", "effect_size": 0.60, "se": 0.12},
        ]
        res = compute_meta_analysis(studies, model="random")
        svg_plot = render_forest_svg(res, title="Trial Meta-Analysis")
        self.assertIn("<svg", svg_plot)
        self.assertIn("</svg>", svg_plot)
        self.assertIn("Study One", svg_plot)
        self.assertIn("Study Two", svg_plot)
        self.assertIn("<polygon", svg_plot)  # summary diamond
        self.assertIn("Heterogeneity:", svg_plot)

    def test_meta_analyze_question(self) -> None:
        conn = open_database(":memory:")
        self.addCleanup(conn.close)
        repo = Repository(conn)

        q = repo.add_question("Does exercise enhance neurogenesis?")
        p1, _ = repo.add_paper({"title": "Exercise Trial 1", "year": 2021, "study_type": "RCT"})
        p2, _ = repo.add_paper({"title": "Exercise Trial 2", "year": 2023, "study_type": "Cohort"})

        c1 = repo.add_claim(p1.id, "Exercise increased neurogenesis by 40%.", "Quote 1", stance="supports", confidence=0.85)
        c2 = repo.add_claim(p2.id, "Exercise enhanced hippocampal volume.", "Quote 2", stance="supports", confidence=0.75)

        repo.add_edge(c1.id, q.id, "supports")
        repo.add_edge(c2.id, q.id, "supports")

        res = meta_analyze_question(repo, q.id, model="random")
        self.assertEqual(len(res.studies), 2)
        self.assertGreater(res.pooled_effect, 0.0)
        self.assertIn("Exercise Trial 1", res.studies[0].label)


if __name__ == "__main__":
    unittest.main()
