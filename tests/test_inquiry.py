"""Ask, brief and review are deterministic and never invent a citation."""

import unittest

from lattice.database import open_database
from lattice.errors import LatticeError
from lattice.inquiry import ask, brief, review
from lattice.repository import Repository


class InquiryTests(unittest.TestCase):
    """A small graph with one supporting, one contradicting and one unrelated claim."""

    def setUp(self):
        self.connection = open_database(":memory:")
        self.addCleanup(self.connection.close)
        self.repository = Repository(self.connection)
        paper, _ = self.repository.add_paper({
            "title": "Sleep and memory", "authors": "A. Researcher", "year": "2021",
            "venue": "Journal of Sleep", "doi": "10.1/sleep"})
        self.paper = paper
        support = self.repository.add_claim(
            paper.id, "Sleep consolidates memory", "Sleep consolidates memory.", "p. 4",
            "supports", 0.9)
        contradict = self.repository.add_claim(
            paper.id, "Sleep does not affect recall", "We found no effect.", "p. 9",
            "contradicts", 0.6)
        self.question = self.repository.add_question("Does sleep consolidate memory?")
        self.repository.add_edge(support.id, self.question.id, "supports")
        self.repository.add_edge(contradict.id, self.question.id, "contradicts")

    def test_ask_question(self):
        result = ask(self.repository, self.question.id)
        self.assertEqual(result["mode"], "question")
        self.assertEqual(len(result["supports"]), 1)
        self.assertEqual(len(result["contradicts"]), 1)
        self.assertEqual(result["supports"][0]["claim"]["paper"]["id"], self.paper.id)

    def test_ask_by_text(self):
        result = ask(self.repository, "sleep consolidate memory")
        self.assertEqual(result["question"]["id"], self.question.id)

    def test_ask_search_mode(self):
        result = ask(self.repository, "recall")
        self.assertEqual(result["mode"], "search")
        self.assertTrue(result["claims"])

    def test_brief_contains_sections_and_citations(self):
        result = brief(self.repository, self.question.id, tokens=2000)
        self.assertIn("QUESTION:", result["text"])
        self.assertIn("SUPPORTS:", result["text"])
        self.assertIn("CONTRADICTS:", result["text"])
        self.assertIn("CITATIONS:", result["text"])
        self.assertIn("10.1/sleep", result["text"])
        self.assertLessEqual(result["tokens"], 2000)

    def test_brief_respects_tight_budget(self):
        result = brief(self.repository, self.question.id, tokens=230)
        self.assertLessEqual(result["tokens"], 230)

    def test_brief_rejects_tiny_budget(self):
        with self.assertRaises(LatticeError):
            brief(self.repository, self.question.id, tokens=20)

    def test_review_markdown(self):
        result = review(self.repository, self.question.id)
        self.assertIn("# Evidence review", result["markdown"])
        self.assertIn("## Supporting evidence", result["markdown"])
        self.assertIn("## Contradicting evidence", result["markdown"])
        self.assertIn("p_", result["refs"][0])

    def test_review_search_mode(self):
        result = review(self.repository, "zebra")
        self.assertIn("Search review", result["markdown"])

    def test_suggestions_exclude_linked_claims(self):
        result = ask(self.repository, self.question.id)
        suggested = {claim["id"] for claim in result["suggestions"]}
        linked = {item["claim"]["id"] for item in result["supports"] + result["contradicts"]}
        self.assertFalse(suggested & linked)


if __name__ == "__main__":
    unittest.main()
