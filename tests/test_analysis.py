"""Unit tests for scientific contradiction detection, keystone centrality, and evidence matrix analysis."""

import sqlite3
import unittest

from lattice.analysis import (
    ContradictionPair,
    build_evidence_matrix,
    detect_contradictions,
    find_related_findings,
    link_related_findings,
    rank_influential_entities,
    related_findings,
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

    def test_find_and_link_related_findings_is_deterministic_and_idempotent(self) -> None:
        q = self.repo.add_question("Does slow-wave sleep consolidate memory?")
        p1, _ = self.repo.add_paper({"title": "Sleep and Memory", "authors": "A"})
        p2, _ = self.repo.add_paper({"title": "Spindles and Recall", "authors": "B"})
        p3, _ = self.repo.add_paper({"title": "Transformers for Text", "authors": "C"})
        c1 = self.repo.add_claim(
            p1.id, "Slow-wave sleep improved memory recall in participants.",
            "Slow-wave sleep improved memory recall in participants by 28%.", stance="supports")
        c2 = self.repo.add_claim(
            p2.id, "Slow-wave sleep enhanced memory recall across participants.",
            "Slow-wave sleep enhanced memory recall across participants.", stance="supports")
        c3 = self.repo.add_claim(
            p3.id, "Transformers classify benchmark text.",
            "Transformer models classify benchmark text.", stance="mentions")
        self.repo.add_edge(c1.id, q.id, kind="answers")
        self.repo.add_edge(c2.id, q.id, kind="answers")

        pairs = find_related_findings(self.repo)
        self.assertEqual(len(pairs), 1)
        pair = pairs[0]
        self.assertEqual((pair.claim_a_id, pair.claim_b_id), (c1.id, c2.id))
        self.assertIn(q.id, pair.shared_question_ids)
        self.assertIn("memory", pair.shared_keywords)
        self.assertNotIn(c3.id, {pair.claim_a_id, pair.claim_b_id})

        created = link_related_findings(self.repo)
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0].kind, "related")
        self.assertIn("shared question", created[0].note)
        self.assertEqual(self.repo.stats()["edge_kinds"].get("related"), 1)
        self.assertEqual(link_related_findings(self.repo), [])

    def test_related_link_requires_question_or_two_shared_keywords(self) -> None:
        p1, _ = self.repo.add_paper({"title": "One", "authors": "A"})
        p2, _ = self.repo.add_paper({"title": "Two", "authors": "B"})
        p3, _ = self.repo.add_paper({"title": "Three", "authors": "C"})
        one = self.repo.add_claim(
            p1.id, "Memory recall improved with sleep.",
            "Memory recall improved with sleep.", stance="supports")
        two = self.repo.add_claim(
            p2.id, "Sleep alters memory recall.",
            "Sleep alters memory recall.", stance="supports")
        three = self.repo.add_claim(
            p3.id, "Diet alters memory.",
            "Diet alters memory.", stance="mentions")
        threshold = self.repo.add_claim(
            p3.id, "Diet alters skin.",
            "Diet alters skin.", stance="mentions")

        pairs = find_related_findings(self.repo)
        overlap = {tuple(sorted((pair.claim_a_id, pair.claim_b_id))) for pair in pairs}
        self.assertIn(tuple(sorted((one.id, two.id))), overlap)
        self.assertNotIn(tuple(sorted((one.id, three.id))), overlap)
        self.assertNotIn(tuple(sorted((one.id, threshold.id))), overlap)

        linked = link_related_findings(self.repo, claim_ids=[one.id, two.id])
        linked_pairs = {
            tuple(sorted((edge.src.split(":", 1)[1], edge.dst.split(":", 1)[1])))
            for edge in linked
        }
        self.assertIn(tuple(sorted((one.id, two.id))), linked_pairs)
        for edge in linked:
            self.assertIn("keywords:", edge.note)
            self.assertNotIn("shared question", edge.note)

    def test_related_linking_skips_opposing_and_already_connected_pairs(self) -> None:
        q = self.repo.add_question("Does slow-wave sleep consolidate memory?")
        p1, _ = self.repo.add_paper({"title": "One", "authors": "A"})
        p2, _ = self.repo.add_paper({"title": "Two", "authors": "B"})
        p3, _ = self.repo.add_paper({"title": "Three", "authors": "C"})
        supporting = self.repo.add_claim(
            p1.id, "Slow-wave sleep improved memory recall.",
            "Slow-wave sleep improved memory recall by 28%.", stance="supports")
        opposing = self.repo.add_claim(
            p2.id, "Slow-wave sleep did not improve memory recall.",
            "Slow-wave sleep did not improve memory recall.", stance="contradicts")
        linked = self.repo.add_claim(
            p3.id, "Slow-wave sleep enhanced memory recall.",
            "Slow-wave sleep enhanced memory recall.", stance="supports")
        for claim in (supporting, opposing, linked):
            self.repo.add_edge(claim.id, q.id, kind="answers")
        self.repo.add_edge(supporting.id, linked.id, kind="related", note="manual")

        self.assertEqual(find_related_findings(self.repo), [])
        self.assertEqual(link_related_findings(self.repo), [])

    def test_related_linking_caps_links_per_claim(self) -> None:
        q = self.repo.add_question("Does slow-wave sleep consolidate memory?")
        claims = []
        for index in range(5):
            paper, _ = self.repo.add_paper({
                "title": f"Sleep Study {index}",
                "authors": "A",
                "abstract": "Slow-wave sleep improved memory recall in participants by 28%.",
            })
            claim = self.repo.add_claim(
                paper.id, "Slow-wave sleep improved memory recall.",
                "Slow-wave sleep improved memory recall in participants by 28%.", stance="supports")
            self.repo.add_edge(claim.id, q.id, kind="answers")
            claims.append(claim)
        created = link_related_findings(self.repo, limit_per_claim=2)
        degrees = {}
        for edge in created:
            for ref in (edge.src, edge.dst):
                key = ref.split(":", 1)[1]
                degrees[key] = degrees.get(key, 0) + 1
        self.assertLessEqual(max(degrees.values()), 2)
        self.assertEqual(len(created), 4)

    def test_related_findings_navigates_claim_paper_and_question(self) -> None:
        q = self.repo.add_question("Does slow-wave sleep consolidate memory?")
        p1, _ = self.repo.add_paper({"title": "Sleep and Memory", "authors": "A"})
        p2, _ = self.repo.add_paper({"title": "Spindles and Recall", "authors": "B"})
        p3, _ = self.repo.add_paper({"title": "Sleep Without Question", "authors": "C"})
        c1 = self.repo.add_claim(
            p1.id, "Slow-wave sleep improved memory recall in adults.",
            "Slow-wave sleep improved memory recall in adults by 28%.", stance="supports")
        c2 = self.repo.add_claim(
            p2.id, "Slow-wave sleep enhanced memory recall in older adults.",
            "Slow-wave sleep enhanced memory recall in older adults.", stance="supports")
        c3 = self.repo.add_claim(
            p3.id, "Slow-wave sleep improved memory recall after training.",
            "Slow-wave sleep improved memory recall after training.", stance="supports")
        self.repo.add_edge(c1.id, q.id, kind="answers")
        self.repo.add_edge(c2.id, q.id, kind="answers")

        navigation = related_findings(self.repo, f"claim:{c1.id}")
        self.assertEqual(navigation["type"], "claim")
        self.assertEqual(navigation["count"], 2)
        by_id = {item["id"]: item for item in navigation["related"]}
        self.assertEqual(by_id[c2.id]["relation"], "co-evidence")
        self.assertEqual(by_id[c3.id]["relation"], "topic-overlap")
        self.assertIn(q.id, by_id[c2.id]["shared_questions"])
        self.assertTrue(by_id[c2.id]["reason"])
        self.assertEqual(by_id[c2.id]["paper"], p2.id)
        self.assertEqual(by_id[c2.id]["paper_title"], "Spindles and Recall")
        self.assertTrue(by_id[c2.id]["study_type"])

        link_related_findings(self.repo)
        linked_navigation = related_findings(self.repo, f"claim:{c1.id}")
        linked_by_id = {item["id"]: item for item in linked_navigation["related"]}
        self.assertEqual(linked_by_id[c2.id]["relation"], "related")
        self.assertIsNotNone(linked_by_id[c2.id]["edge_id"])
        self.assertIn("linked by a related edge", linked_by_id[c2.id]["reason"])

        paper_navigation = related_findings(self.repo, f"paper:{p1.id}")
        self.assertEqual(paper_navigation["seeds"], [f"claim:{c1.id}"])
        self.assertNotIn(c1.id, {item["id"] for item in paper_navigation["related"]})

        question_navigation = related_findings(self.repo, f"question:{q.id}")
        self.assertEqual(set(question_navigation["seeds"]), {f"claim:{c1.id}", f"claim:{c2.id}"})
        self.assertIn(c3.id, {item["id"] for item in question_navigation["related"]})
        self.assertEqual(len(related_findings(self.repo, f"claim:{c1.id}", limit=1)["related"]), 1)

    def test_related_findings_navigation_works_before_linking(self) -> None:
        q = self.repo.add_question("Does sleep consolidate memory?")
        p1, _ = self.repo.add_paper({"title": "One", "authors": "A"})
        p2, _ = self.repo.add_paper({"title": "Two", "authors": "B"})
        c1 = self.repo.add_claim(
            p1.id, "Sleep improved memory recall.", "Sleep improved memory recall.",
            stance="supports")
        c2 = self.repo.add_claim(
            p2.id, "Sleep enhanced memory recall.", "Sleep enhanced memory recall.",
            stance="supports")
        self.repo.add_edge(c1.id, q.id, kind="answers")
        self.repo.add_edge(c2.id, q.id, kind="answers")

        navigation = related_findings(self.repo, f"claim:{c1.id}")
        self.assertEqual(navigation["count"], 1)
        item = navigation["related"][0]
        self.assertEqual(item["relation"], "co-evidence")
        self.assertIsNone(item["edge_id"])
        self.assertIn("shares question", item["reason"])

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
