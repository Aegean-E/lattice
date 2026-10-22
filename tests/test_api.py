"""Unit tests for the public `lattice.api` integration surface."""

import ast
import sqlite3
import unittest
from pathlib import Path

from lattice import api
from lattice.database import open_database
from lattice.repository import Repository

SURFACED_MODULES = frozenset({
    "analysis", "checks", "context", "database", "discovery", "errors", "extraction",
    "ingest", "inquiry", "mcp", "models", "repository", "snapshots", "synthesis", "web",
})

EXPECTED_EXPORTS = {
    "Repository",
    "ContradictionPair",
    "RelatedPair",
    "detect_contradictions",
    "find_related_findings",
    "link_related_findings",
    "related_findings",
    "rank_influential_entities",
    "build_evidence_matrix",
    "get_evidence_matrix",
    "get_hypothesis_evidence",
    "SynthesisReport",
    "compute_consensus",
    "cluster_claims",
    "format_bibtex",
    "synthesize",
    "synthesize_question",
    "export_snapshot",
    "import_snapshot",
    "export_bibtex_file",
    "Fetcher",
    "PaperCandidate",
    "LiteratureProvider",
    "ProviderRegistry",
    "ArxivProvider",
    "CrossrefProvider",
    "OpenAlexProvider",
    "EuropePmcProvider",
    "OfflineCorpusProvider",
    "default_registry",
    "DiscoveryService",
    "ExtractionResult",
    "split_empirical_sentences",
    "infer_stance",
    "infer_confidence",
    "extract_from_paper",
    "extract_all",
    "extract_claims_for_paper",
    "empty_record",
    "parse_bibtex",
    "parse_ris",
    "parse_csv",
    "parse_markdown",
    "parse_text",
    "parse_file",
    "parse_paths",
    "CheckIssue",
    "CheckReport",
    "run_checks",
    "summarize",
    "STOPWORDS",
    "GROUPS",
    "ask",
    "brief",
    "review",
    "MIN_TOKENS",
    "outline",
    "compact_search",
    "compact_related",
    "compact_subgraph",
    "Paper",
    "Claim",
    "Question",
    "Edge",
    "STANCES",
    "STUDY_TYPES",
    "EDGE_KINDS",
    "ENTITY_PREFIXES",
    "REF_PREFIX",
    "normalize_text",
    "normalize_tags",
    "derive_tags",
    "normalize_study_type",
    "infer_study_type",
    "paper_id",
    "next_id",
    "validate_stance",
    "parse_confidence",
    "validate_edge_kind",
    "entity_type",
    "validate_ref",
    "bare_id",
    "estimate_tokens",
    "LatticeError",
    "fail",
    "SCHEMA_VERSION",
    "SCHEMA",
    "utc_now",
    "open_database",
    "schema_version",
    "PAPER_FIELDS",
    "SEED_CORPUS",
    "Record",
    "PROTOCOL_VERSION",
    "SERVER_NAME",
    "TOOLS",
    "RESOURCES",
    "PROMPTS",
    "handle_message",
    "serve",
    "WEB_HTML",
    "WebResponse",
    "dispatch_web_request",
    "serve_web",
    "__version__",
}


def public_definitions(module_name: str) -> list[str]:
    """Every public top-level name a surfaced module defines, from its AST."""
    source = (Path(api.__file__).parent / f"{module_name}.py").read_text(encoding="utf-8")
    names: list[str] = []
    for node in ast.parse(source).body:
        name = None
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            name = node.name
        elif isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            name = target.id if isinstance(target, ast.Name) else None
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            name = node.target.id
        if name and not name.startswith("_"):
            names.append(name)
    return names


class PublicApiTests(unittest.TestCase):
    """Verify the facade stays complete, inert at import time and faithful."""

    def setUp(self) -> None:
        self.connection: sqlite3.Connection = open_database(":memory:")
        self.addCleanup(self.connection.close)
        self.repo = Repository(self.connection)

    def test_every_expected_symbol_is_exported(self) -> None:
        missing = sorted(name for name in EXPECTED_EXPORTS if not hasattr(api, name))
        self.assertEqual(missing, [])

    def test_all_is_sorted_unique_and_resolves(self) -> None:
        self.assertEqual(list(api.__all__), sorted(set(api.__all__)))
        unresolved = sorted(name for name in api.__all__ if not hasattr(api, name))
        self.assertEqual(unresolved, [])
        self.assertTrue(EXPECTED_EXPORTS.issubset(set(api.__all__)))

    def test_every_public_definition_is_exported(self) -> None:
        missing = {
            module: absent
            for module in sorted(SURFACED_MODULES)
            if (absent := [name for name in public_definitions(module)
                           if name not in api.__all__])
        }
        self.assertEqual(missing, {})

    def test_reexports_are_the_original_objects(self) -> None:
        from lattice import analysis, context, models, repository
        self.assertIs(api.Repository, repository.Repository)
        self.assertIs(api.Paper, models.Paper)
        self.assertIs(api.detect_contradictions, analysis.detect_contradictions)
        self.assertIs(api.compact_search, context.compact_search)

    def test_design_aliases_resolve_to_canonical_functions(self) -> None:
        from lattice.extraction import extract_from_paper
        from lattice.synthesis import synthesize
        self.assertIs(api.extract_claims_for_paper, extract_from_paper)
        self.assertIs(api.synthesize_question, synthesize)

    def test_get_hypothesis_evidence_returns_the_question_bundle(self) -> None:
        question = self.repo.add_question("Does sleep consolidate memory?")
        result = api.get_hypothesis_evidence(self.repo, question.id)
        self.assertEqual(result["question"]["id"], question.id)
        self.assertEqual(result["ref"], f"question:{question.id}")
        self.assertEqual(result["evidence_count"], 0)
        self.assertTrue(result["gaps"])

    def test_get_evidence_matrix_filters_by_hypothesis_ids(self) -> None:
        q1 = self.repo.add_question("Does sleep consolidate memory?")
        q2 = self.repo.add_question("Does caffeine impair sleep?")
        paper, _ = self.repo.add_paper({
            "title": "Sleep and Memory Consolidation Trial",
            "study_type": "Randomized Controlled Trial",
        })
        claim = self.repo.add_claim(
            paper.id, "Sleep improves memory.", "Sleep improves memory.", stance="supports")
        self.repo.add_edge(claim.id, q1.id, kind="supports")
        self.repo.add_paper({"title": "Caffeine Trial", "study_type": "Randomized Controlled Trial"})

        full = api.get_evidence_matrix(self.repo)
        self.assertEqual({item["id"] for item in full["questions"]}, {q1.id, q2.id})

        filtered = api.get_evidence_matrix(self.repo, [f"question:{q1.id}", q2.id])
        self.assertEqual({item["id"] for item in filtered["questions"]}, {q1.id, q2.id})

        only_q1 = api.get_evidence_matrix(self.repo, [q1.id])
        self.assertEqual([item["id"] for item in only_q1["questions"]], [q1.id])
        self.assertEqual({cell["question_id"] for cell in only_q1["cells"]}, {q1.id})
        self.assertEqual([item["id"] for item in only_q1["papers"]], [paper.id])
        self.assertEqual([gap["question_id"] for gap in only_q1["gaps"]], [])

    def test_single_string_question_id_filters_like_a_list(self) -> None:
        q1 = self.repo.add_question("Does sleep consolidate memory?")
        q2 = self.repo.add_question("Does caffeine impair sleep?")
        as_list = api.get_evidence_matrix(self.repo, [q1.id])
        as_string = api.get_evidence_matrix(self.repo, q1.id)
        as_ref = api.get_evidence_matrix(self.repo, f"question:{q1.id}")
        self.assertEqual(as_string, as_list)
        self.assertEqual(as_ref, as_list)
        self.assertEqual([item["id"] for item in as_string["questions"]], [q1.id])
        self.assertNotIn(q2.id, {item["id"] for item in as_string["questions"]})

    def test_invalid_question_identifiers_raise(self) -> None:
        for selection in ("", "   ", "paper:p_000001", "not-an-id", ["p_000001"], [""]):
            with self.subTest(selection=selection), self.assertRaises(api.LatticeError):
                api.get_evidence_matrix(self.repo, selection)

    def test_get_evidence_matrix_filters_out_unlinked_questions(self) -> None:
        q1 = self.repo.add_question("Does sleep consolidate memory?")
        q2 = self.repo.add_question("Does caffeine impair sleep?")
        paper, _ = self.repo.add_paper({"title": "Sleep and Memory Trial"})
        claim = self.repo.add_claim(paper.id, "Sleep helps.", "Sleep helps.", stance="mentions")
        self.repo.add_edge(claim.id, q1.id, kind="answers")

        filtered = api.get_evidence_matrix(self.repo, [q2.id])
        self.assertEqual([item["id"] for item in filtered["questions"]], [q2.id])
        self.assertEqual(filtered["cells"], [])
        self.assertEqual(filtered["papers"], [])
        self.assertEqual([gap["question_id"] for gap in filtered["gaps"]], [q2.id])


if __name__ == "__main__":
    unittest.main()
