"""Graph writes, dedupe, references, search and evidence grouping."""

import unittest

from lattice.database import open_database
from lattice.errors import LatticeError
from lattice.repository import Repository


class RepositoryTests(unittest.TestCase):
    """Every test gets a fresh in-memory graph."""

    def setUp(self):
        self.connection = open_database(":memory:")
        self.addCleanup(self.connection.close)
        self.repository = Repository(self.connection)

    def paper(self, title="A paper", **values):
        metadata = {"title": title, "authors": "A. Author", "year": "2020", **values}
        return self.repository.add_paper(metadata)[0]

    def test_paper_dedupe_by_doi(self):
        first, created = self.repository.add_paper({"title": "One", "doi": "10.1/x"})
        second, again = self.repository.add_paper({"title": "Two", "doi": "10.1/X"})
        self.assertTrue(created)
        self.assertFalse(again)
        self.assertEqual(first.id, second.id)

    def test_paper_dedupe_by_normalized_title_and_year(self):
        first = self.paper("Deep  Learning!").id
        second = self.paper("deep learning").id
        self.assertEqual(first, second)

    def test_merge_fills_missing_metadata(self):
        first, _ = self.repository.add_paper({"title": "One"})
        second, created = self.repository.add_paper({"title": "One", "doi": "10.1/a",
                                                     "authors": "Filled"})
        self.assertFalse(created)
        self.assertEqual(first.id, second.id)
        self.assertEqual(second.doi, "10.1/a")
        self.assertEqual(second.authors, "Filled")

    def test_claim_requires_quote(self):
        paper = self.paper()
        with self.assertRaises(LatticeError):
            self.repository.add_claim(paper.id, "A claim", "   ")

    def test_claim_ids_are_sequential(self):
        paper = self.paper()
        first = self.repository.add_claim(paper.id, "One", "quote one")
        second = self.repository.add_claim(paper.id, "Two", "quote two", stance="supports")
        self.assertEqual(first.id, "c_000001")
        self.assertEqual(second.id, "c_000002")
        self.assertEqual(second.stance, "supports")

    def test_question_and_edges(self):
        paper = self.paper()
        claim = self.repository.add_claim(paper.id, "Sleep helps memory", "sleep helps memory")
        question = self.repository.add_question("Does sleep help memory?")
        edge = self.repository.add_edge(f"claim:{claim.id}", question.id, "supports", "quote match")
        self.assertEqual(edge.kind, "supports")
        self.assertEqual(self.repository.get(question.id)["edges"][0]["kind"], "supports")

    def test_duplicate_edge_is_refused(self):
        paper = self.paper()
        claim = self.repository.add_claim(paper.id, "One", "quote")
        question = self.repository.add_question("Question?")
        self.repository.add_edge(claim.id, question.id, "supports")
        with self.assertRaises(LatticeError):
            self.repository.add_edge(claim.id, question.id, "supports")

    def test_self_edge_is_refused(self):
        paper = self.paper()
        with self.assertRaises(LatticeError):
            self.repository.add_edge(paper.id, paper.id, "related")

    def test_missing_reference_is_refused(self):
        with self.assertRaises(LatticeError):
            self.repository.get("paper:p_missing")

    def test_search_across_entities(self):
        paper = self.paper("Memory consolidation")
        self.repository.add_claim(paper.id, "Sleep consolidates memory", "quote", stance="supports")
        self.repository.add_question("Does sleep consolidate memory?")
        found = self.repository.search("sleep")
        self.assertEqual(len(found["claims"]), 1)
        self.assertEqual(len(found["questions"]), 1)
        self.assertEqual(len(found["papers"]), 0)

    def test_paper_stores_tags_and_infers_study_type(self):
        paper = self.paper(
            "A randomized controlled trial of sleep and memory",
            abstract="Participants improved recall after acoustic stimulation.",
            tags="Sleep; Memory, sleep",
        )
        self.assertEqual(paper.study_type, "Randomized Controlled Trial")
        self.assertEqual(paper.tags, "sleep, memory")
        payload = paper.to_dict()
        self.assertIn("tags", payload)
        self.assertIn("study_type", payload)

    def test_literature_search_matches_tags_words_sentences_and_study_type(self):
        sleep_paper = self.paper(
            "Slow-Wave Sleep Consolidates Declarative Memory",
            abstract="Slow-wave sleep increased recall accuracy by 28%.",
            tags="sleep; memory",
        )
        computing_paper = self.paper(
            "Transformer Scaling Under Noisy Pretraining Corpora",
            abstract="Curated pretraining data improved accuracy by 19%.",
            study_type="Computational Study",
        )

        by_words = self.repository.search_literature("slow-wave sleep")
        self.assertEqual([paper["id"] for paper in by_words["papers"]], [sleep_paper.id])

        by_tag = self.repository.search_literature(tags="memory")
        self.assertEqual([paper["id"] for paper in by_tag["papers"]], [sleep_paper.id])

        by_sentence = self.repository.search_literature(
            "Slow-wave sleep increased recall accuracy by 28%."
        )
        self.assertEqual([paper["id"] for paper in by_sentence["papers"]], [sleep_paper.id])

        by_normalized_sentence = self.repository.search_literature(
            "Slow wave sleep, increased recall accuracy by 28!"
        )
        self.assertEqual(
            [paper["id"] for paper in by_normalized_sentence["papers"]], [sleep_paper.id]
        )

        by_type = self.repository.search_literature(study_type="Computational Study")
        self.assertEqual([paper["id"] for paper in by_type["papers"]], [computing_paper.id])

        everything = self.repository.search_literature()
        self.assertEqual(everything["total"], 2)
        self.assertIn("study_type", everything["papers"][0])
        self.assertIn("tags", everything["papers"][0])

    def test_evidence_groups_and_gaps(self):
        paper = self.paper()
        claim = self.repository.add_claim(paper.id, "It helps", "it helps")
        question = self.repository.add_question("Does it help?")
        self.repository.add_edge(claim.id, question.id, "supports")
        evidence = self.repository.evidence(question.id)
        self.assertEqual(evidence["evidence_count"], 1)
        self.assertEqual(evidence["supports"][0]["claim"]["id"], claim.id)
        self.assertIn("No contradicting evidence has been linked.", evidence["gaps"])

    def test_stats_and_event_log(self):
        paper = self.paper()
        self.repository.add_question("Why?")
        stats = self.repository.stats()
        self.assertEqual(stats["papers"], 1)
        self.assertEqual(stats["questions"], 1)
        events = self.connection.execute("SELECT action FROM events ORDER BY id").fetchall()
        self.assertIn("paper.add", [row["action"] for row in events])

    def test_neighbors_filter_by_kind(self):
        paper = self.paper()
        claim = self.repository.add_claim(paper.id, "One", "quote")
        self.repository.add_edge(paper.id, claim.id, "mentions")
        self.repository.add_edge(paper.id, claim.id, "supports")
        self.assertEqual(len(self.repository.neighbors(paper.id)), 2)
        self.assertEqual(len(self.repository.neighbors(paper.id, "supports")), 1)

    def test_export_bibtex(self):
        self.paper("Sleep Oscillations and Memory Consolidation", year="2021", authors="Diekelmann, S.", venue="Nature")
        bib = self.repository.export_bibtex()
        self.assertIn("@article{", bib)
        self.assertIn("Sleep Oscillations", bib)
        self.assertIn("year = {2021}", bib)
        self.assertIn("journal = {Nature}", bib)


if __name__ == "__main__":
    unittest.main()

