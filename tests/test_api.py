"""Unit tests for the public `lattice.api` integration surface."""

import ast
import pkgutil
import sqlite3
import unittest
from pathlib import Path
from unittest import mock

import lattice as lattice_package
from lattice import api
from lattice.database import open_database
from lattice.repository import Repository

NON_SURFACE_MODULES = frozenset({"api", "cli", "__main__"})
CONDITIONAL_BLOCKS = tuple(
    block for block in (ast.If, ast.Try, getattr(ast, "TryStar", None)) if block is not None
)
SURFACED_MODULES = frozenset(
    info.name for info in pkgutil.iter_modules(lattice_package.__path__)
    if info.name not in NON_SURFACE_MODULES
)

EXPECTED_EXPORTS = {
    "Repository",
    "ContradictionPair",
    "RelatedPair",
    "detect_contradictions",
    "find_path",
    "find_related_findings",
    "link_related_findings",
    "propose_hypotheses",
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
    "export_graphml_file",
    "export_graphml_string",
    "export_cytoscape_file",
    "export_cytoscape_data",
    "GRAPHML_NS",
    "sync_article_from_neurocore",
    "collect_repository_records",
    "read_snapshot_records",
    "diff_records",
    "diff_snapshots",
    "diff_snapshot",
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
    "parse_csl_json",
    "parse_markdown",
    "parse_text",
    "parse_file",
    "parse_paths",
    "CheckIssue",
    "CheckReport",
    "run_checks",
    "summarize",
    "SCREENING_STATUSES",
    "DEFAULT_EXCLUSION_REASONS",
    "ScreeningDecision",
    "PrismaFlow",
    "record_screening_decision",
    "get_screening_decision",
    "list_screening_decisions",
    "compute_prisma_flow",
    "render_prisma_markdown",
    "render_prisma_svg",
    "STOPWORDS",
    "GROUPS",
    "ask",
    "brief",
    "review",
    "MIN_TOKENS",
    "ContextPack",
    "build_context_pack",
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


def _definition_names(nodes: list[ast.stmt]) -> list[str]:
    """Public names bound by top-level statements, including conditional blocks."""
    names: list[str] = []
    for node in nodes:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.append(node.name)
        elif isinstance(node, ast.Assign):
            names.extend(target.id for target in node.targets if isinstance(target, ast.Name))
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            if isinstance(node.target, ast.Name):
                names.append(node.target.id)
        elif isinstance(node, CONDITIONAL_BLOCKS):
            names.extend(_definition_names(node.body))
            names.extend(_definition_names(node.orelse))
            names.extend(_definition_names(getattr(node, "finalbody", [])))
    return names


def public_definitions(module_name: str) -> list[str]:
    """Every public top-level name a surfaced module defines, from its AST."""
    source = (Path(api.__file__).parent / f"{module_name}.py").read_text(encoding="utf-8")
    return [name for name in _definition_names(ast.parse(source).body)
            if not name.startswith("_")]


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
        self.assertIs(api.build_context_pack, context.build_context_pack)
        self.assertIs(api.ContextPack, context.ContextPack)

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
        for selection in (
            "", "   ", "paper:p_000001", "not-an-id", "q_", "question:q_",
            "question:q_1:extra", "question:q 1", ["p_000001"], [""],
        ):
            with self.subTest(selection=selection), self.assertRaises(api.LatticeError):
                api.get_evidence_matrix(self.repo, selection)

    def test_invalid_selection_never_builds_the_matrix(self) -> None:
        with mock.patch.object(api, "build_evidence_matrix") as build:
            with self.assertRaises(api.LatticeError):
                api.get_evidence_matrix(self.repo, "not-an-id")
        build.assert_not_called()

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

    def test_sync_article_from_neurocore_creates_paper_and_claims(self) -> None:
        article = {
            "title": "Sleep Slow Oscillations and Declarative Memory",
            "authors": ["Elena Vance", "Marcus Bell"],
            "year": 2024,
            "journal": "Neuroscience Reports",
            "doi": "10.1016/j.neurorep.2024.01",
            "abstract": "Slow oscillations during deep sleep coordinate memory replay across hippocampal-neocortical networks.",
            "keywords": ["slow waves", "memory consolidation"],
            "article_type": "cohort_study",
            "key_findings": [
                "Slow oscillations during deep sleep coordinate memory replay across hippocampal-neocortical networks.",
                "Consolidation was enhanced by 25% under targeted acoustic stimulation."
            ]
        }
        res = api.sync_article_from_neurocore(self.repo, article)
        self.assertTrue(res["created"])
        paper = res["paper"]
        self.assertEqual(paper["title"], article["title"])
        self.assertEqual(paper["authors"], "Elena Vance, Marcus Bell")
        self.assertEqual(paper["venue"], "Neuroscience Reports")
        self.assertEqual(paper["year"], "2024")
        self.assertEqual(paper["study_type"], "Cohort Study")
        self.assertIn("slow waves", paper["tags"])
        self.assertEqual(len(res["claims"]), 2)
        c0 = res["claims"][0]
        self.assertEqual(c0["quote"], "Slow oscillations during deep sleep coordinate memory replay across hippocampal-neocortical networks.")
        self.assertEqual(c0["locator"], "abstract")

        # Second sync is idempotent
        res2 = api.sync_article_from_neurocore(self.repo, article)
        self.assertFalse(res2["created"])
        self.assertEqual(res2["paper"]["id"], paper["id"])

    def test_sync_article_with_related_hypotheses(self) -> None:
        article = {
            "title": "Theta Oscillations in Spatial Navigation",
            "authors": ["Ada Lovelace"],
            "year": 2024,
            "abstract": "Hippocampal theta rhythms synchronize place cell assemblies during navigation.",
            "key_findings": [
                "Hippocampal theta rhythms synchronize place cell assemblies during navigation."
            ],
            "related_hypotheses": [
                "Does theta rhythm organize grid-place coordination?",
                {"title": "Navigation Hypothesis", "statement": "Theta rhythms pace memory encoding."}
            ]
        }
        res = api.sync_article_from_neurocore(self.repo, article)
        self.assertEqual(len(res["questions"]), 2)
        self.assertGreaterEqual(len(res["edges"]), 2)
        self.assertEqual(self.repo.stats()["questions"], 2)
        # Verify edges connect claims to questions
        edges = self.repo.neighbors(f"claim:{res['claims'][0]['id']}")
        self.assertEqual(len(edges), 2)
        kinds = {edge.kind for edge in edges}
        self.assertIn("supports", kinds)



if __name__ == "__main__":
    unittest.main()
