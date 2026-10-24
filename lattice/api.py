"""Stable public Python surface for host integrations such as neurocore.

The package is still organized by concern; this module is a thin, import-only facade that
re-exports every public symbol an integrator needs so callers never reach into private modules
or pay CLI/MCP overhead. Importing it has no side effects.

Names in the draft neurocore integration design are preserved as aliases:
`synthesize_question` is `synthesis.synthesize` and `extract_claims_for_paper` is
`extraction.extract_from_paper`. Inquiry is function-based (`ask`, `brief`, `review`); there is
no separate service class.
"""

import re
from typing import Any, Dict, Iterable, Optional

from lattice import __version__
from lattice.analysis import (
    ContradictionPair,
    RelatedPair,
    build_evidence_matrix,
    detect_contradictions,
    find_related_findings,
    link_related_findings,
    rank_influential_entities,
    related_findings,
)
from lattice.checks import CheckIssue, CheckReport, run_checks, summarize
from lattice.client import AsyncLatticeClient, DEFAULT_DB, LatticeClient
from lattice.context import (
    MIN_TOKENS,
    compact_related,
    compact_search,
    compact_subgraph,
    outline,
)
from lattice.database import SCHEMA, SCHEMA_VERSION, open_database, schema_version, utc_now
from lattice.diff import diff_records, diff_snapshot, diff_snapshots
from lattice.discovery import (
    ArxivProvider,
    CrossrefProvider,
    DiscoveryService,
    EuropePmcProvider,
    Fetcher,
    LiteratureProvider,
    OfflineCorpusProvider,
    OpenAlexProvider,
    PaperCandidate,
    ProviderRegistry,
    SEED_CORPUS,
    default_registry,
)
from lattice.errors import LatticeError, fail
from lattice.extraction import (
    ExtractionResult,
    extract_all,
    extract_from_paper,
    infer_confidence,
    infer_stance,
    split_empirical_sentences,
)
from lattice.ingest import (
    Record,
    empty_record,
    parse_bibtex,
    parse_csv,
    parse_file,
    parse_markdown,
    parse_paths,
    parse_ris,
    parse_text,
    sync_article_from_neurocore,
)
from lattice.inquiry import GROUPS, STOPWORDS, ask, brief, review
from lattice.mcp import (
    PROMPTS,
    PROTOCOL_VERSION,
    RESOURCES,
    SERVER_NAME,
    TOOLS,
    dispatch_tool,
    get_prompt,
    handle_message,
    read_resource,
    serve,
)
from lattice.models import (
    EDGE_KINDS,
    ENTITY_PREFIXES,
    REF_PREFIX,
    STANCES,
    STUDY_TYPES,
    Claim,
    Edge,
    Paper,
    Question,
    bare_id,
    derive_tags,
    entity_type,
    estimate_tokens,
    infer_study_type,
    next_id,
    normalize_study_type,
    normalize_tags,
    normalize_text,
    paper_id,
    parse_confidence,
    validate_edge_kind,
    validate_ref,
    validate_stance,
)
from lattice.repository import PAPER_FIELDS, Repository
from lattice.snapshots import (
    GRAPHML_NS,
    collect_repository_records,
    export_bibtex_file,
    export_cytoscape_data,
    export_cytoscape_file,
    export_graphml_file,
    export_graphml_string,
    export_snapshot,
    import_snapshot,
    read_snapshot_records,
)
from lattice.synthesis import (
    SynthesisReport,
    cluster_claims,
    compute_consensus,
    format_bibtex,
    synthesize,
)
from lattice.web import WEB_HTML, WebResponse, dispatch_web_request, serve_web

synthesize_question = synthesize
extract_claims_for_paper = extract_from_paper


_QUESTION_ID = re.compile(r"q_[A-Za-z0-9][A-Za-z0-9_-]*")


def _question_key(value: str) -> str:
    """Normalize `question:q_000001` or `q_000001` to the bare identifier."""
    text = str(value).strip()
    if ":" in text:
        kind, identifier = text.split(":", 1)
        if kind.strip().lower() != "question":
            fail(f"'{value}' is not a question reference",
                 "the evidence matrix is filtered by research question ids",
                 "pass question:q_xxx references or bare q_xxx ids")
        text = identifier.strip()
    if not _QUESTION_ID.fullmatch(text):
        fail(f"'{value}' is not a question reference",
             "question identifiers look like q_000001",
             "pass question:q_xxx references or bare q_xxx ids")
    return text


def get_evidence_matrix(repository: Repository,
                        question_ids: Optional[Iterable[str]] = None) -> Dict[str, Any]:
    """The Paper x Question matrix, optionally narrowed to selected research questions.

    Passing `None` returns the complete matrix. Passing one question reference string or an
    iterable of references and bare ids keeps only those questions, their cells and gaps, and
    the papers that carry a cell for them.
    """
    if question_ids is None:
        return build_evidence_matrix(repository)
    if isinstance(question_ids, str):
        question_ids = [question_ids]
    wanted = {_question_key(item) for item in question_ids}
    if not wanted:
        return {"papers": [], "questions": [], "cells": [], "gaps": []}
    matrix = build_evidence_matrix(repository)
    questions = [item for item in matrix["questions"] if item["id"] in wanted]
    cells = [item for item in matrix["cells"] if item["question_id"] in wanted]
    gaps = [item for item in matrix["gaps"] if item["question_id"] in wanted]
    paper_ids = {item["paper_id"] for item in cells}
    papers = [item for item in matrix["papers"] if item["id"] in paper_ids]
    return {"papers": papers, "questions": questions, "cells": cells, "gaps": gaps}


def get_hypothesis_evidence(repository: Repository, question_id: str) -> Dict[str, Any]:
    """Evidence grouped by role (supports, contradicts, answers, other) for one question."""
    return repository.evidence(question_id)


__all__ = sorted([
    "ArxivProvider",
    "AsyncLatticeClient",
    "CheckIssue",
    "CheckReport",
    "Claim",
    "ContradictionPair",
    "CrossrefProvider",
    "DEFAULT_DB",
    "DiscoveryService",
    "EDGE_KINDS",
    "ENTITY_PREFIXES",
    "Edge",
    "EuropePmcProvider",
    "ExtractionResult",
    "Fetcher",
    "GRAPHML_NS",
    "GROUPS",
    "LatticeClient",
    "LatticeError",
    "LiteratureProvider",
    "MIN_TOKENS",
    "OfflineCorpusProvider",
    "OpenAlexProvider",
    "PAPER_FIELDS",
    "PROMPTS",
    "PROTOCOL_VERSION",
    "Paper",
    "PaperCandidate",
    "ProviderRegistry",
    "Question",
    "REF_PREFIX",
    "RESOURCES",
    "Record",
    "RelatedPair",
    "Repository",
    "SCHEMA",
    "SCHEMA_VERSION",
    "SEED_CORPUS",
    "SERVER_NAME",
    "STANCES",
    "STOPWORDS",
    "STUDY_TYPES",
    "SynthesisReport",
    "TOOLS",
    "WEB_HTML",
    "WebResponse",
    "__version__",
    "ask",
    "bare_id",
    "brief",
    "build_evidence_matrix",
    "cluster_claims",
    "collect_repository_records",
    "compact_related",
    "compact_search",
    "compact_subgraph",
    "compute_consensus",
    "default_registry",
    "derive_tags",
    "detect_contradictions",
    "diff_records",
    "diff_snapshot",
    "diff_snapshots",
    "dispatch_tool",
    "dispatch_web_request",
    "empty_record",
    "entity_type",
    "estimate_tokens",
    "export_bibtex_file",
    "export_cytoscape_data",
    "export_cytoscape_file",
    "export_graphml_file",
    "export_graphml_string",
    "export_snapshot",
    "extract_all",
    "extract_claims_for_paper",
    "extract_from_paper",
    "fail",
    "find_related_findings",
    "format_bibtex",
    "get_evidence_matrix",
    "get_hypothesis_evidence",
    "get_prompt",
    "handle_message",
    "import_snapshot",
    "infer_confidence",
    "infer_stance",
    "infer_study_type",
    "link_related_findings",
    "next_id",
    "normalize_study_type",
    "normalize_tags",
    "normalize_text",
    "open_database",
    "outline",
    "paper_id",
    "parse_bibtex",
    "parse_confidence",
    "parse_csv",
    "parse_file",
    "parse_markdown",
    "parse_paths",
    "parse_ris",
    "parse_text",
    "rank_influential_entities",
    "read_resource",
    "read_snapshot_records",
    "related_findings",
    "review",
    "run_checks",
    "schema_version",
    "serve",
    "serve_web",
    "split_empirical_sentences",
    "summarize",
    "sync_article_from_neurocore",
    "synthesize",
    "synthesize_question",
    "utc_now",
    "validate_edge_kind",
    "validate_ref",
    "validate_stance",
])
