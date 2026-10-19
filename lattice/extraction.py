"""Automated knowledge creation: extract quote-backed claims and question links from papers."""

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from lattice.models import Claim, Edge, normalize_text
from lattice.repository import Repository

_ABBREVIATIONS = ("dr.", "mr.", "mrs.", "ms.", "prof.", "et al.", "fig.", "eq.", "vs.", "e.g.", "i.e.")
_SUPPORT_MARKERS = (
    "increased", "improved", "improves", "enhanced", "stabilized", "reduced", "reduces",
    "eliminated", "eliminates", "outperformed", "demonstrate", "demonstrated", "confirmed",
    "consolidated", "consolidates", "amplified", "accelerated", "significant", "significantly",
)
_CONTRADICT_MARKERS = (
    "did not", "does not", "failed to", "fails to", "no significant", "no effect",
    "unchanged", "impaired", "impairs", "contradicts", "refuted", "refutes", "null effect",
    "ineffective", "lacked",
)
_EMPIRICAL_MARKERS = (
    *_SUPPORT_MARKERS,
    *_CONTRADICT_MARKERS,
    "compared with", "across", "participants", "subjects", "trials", "queries",
    "accuracy", "retention", "recall", "plasticity", "coupling", "reviews", "budget",
)
_QUANT_RE = re.compile(r"\b\d+(?:\.\d+)?%|\bp\s*[<=>]\s*0\.\d+|\b\d+\s+(?:participants|subjects|trials|queries|reviews|adults|hours)\b", re.IGNORECASE)


@dataclass(frozen=True)
class ExtractionResult:
    """Immutable summary of claims and edges extracted from a single paper."""

    paper_id: str
    claims: Tuple[Claim, ...]
    edges: Tuple[Edge, ...]

    def to_dict(self) -> Dict[str, Any]:
        """JSON-ready representation."""
        return {
            "paper_id": self.paper_id,
            "claims": [claim.to_dict() for claim in self.claims],
            "edges": [edge.to_dict() for edge in self.edges],
        }


def split_empirical_sentences(text: str, prefix: str = "abstract") -> List[Tuple[str, str]]:
    """Split text into `(locator, sentence)` pairs, keeping sentences with empirical findings."""
    cleaned = " ".join(str(text or "").split())
    if not cleaned:
        return []
    protected = cleaned
    placeholders: Dict[str, str] = {}
    for index, abbr in enumerate(_ABBREVIATIONS):
        token = f"__ABBR{index}__"
        placeholders[token] = abbr
        protected = re.sub(re.escape(abbr), token, protected, flags=re.IGNORECASE)
    raw_parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", protected)
    results: List[Tuple[str, str]] = []
    for index, raw in enumerate(raw_parts, start=1):
        restored = raw
        for token, abbr in placeholders.items():
            restored = restored.replace(token, abbr)
        sentence = restored.strip()
        if len(sentence) < 25:
            continue
        if _is_empirical(sentence):
            results.append((f"{prefix}:s{index}", sentence))
    if not results and len(cleaned) >= 25:
        first = raw_parts[0]
        for token, abbr in placeholders.items():
            first = first.replace(token, abbr)
        results.append((f"{prefix}:s1", first.strip()))
    return results


def infer_stance(sentence: str) -> str:
    """Classify an empirical sentence as `supports`, `contradicts`, or `mentions`."""
    lowered = f" {sentence.lower()} "
    for marker in _CONTRADICT_MARKERS:
        if marker in lowered:
            return "contradicts"
    for marker in _SUPPORT_MARKERS:
        if marker in lowered:
            return "supports"
    return "mentions"


def infer_confidence(sentence: str) -> float:
    """Assign a deterministic confidence weight in [0.55, 0.95] from evidential markers."""
    lowered = sentence.lower()
    score = 0.55
    if _QUANT_RE.search(sentence):
        score += 0.20
    if "compared with" in lowered or "versus" in lowered or "control" in lowered:
        score += 0.10
    if any(marker in lowered for marker in ("significantly", "demonstrate", "confirmed", "replicated")):
        score += 0.05
    return round(min(0.95, score), 2)


def extract_from_paper(repository: Repository, paper_ref: str,
                       question_ref: Optional[str] = None,
                       text: Optional[str] = None) -> ExtractionResult:
    """Extract quote-backed claims from a paper and link them to matching or target questions."""
    paper = repository.get_paper(paper_ref)
    source_text = text if text is not None else paper.abstract
    sentences = split_empirical_sentences(source_text, prefix="text" if text is not None else "abstract")
    existing_quotes = {
        normalize_text(row["quote"])
        for row in repository.connection.execute(
            "SELECT quote FROM claims WHERE paper_id = ?", (paper.id,)
        ).fetchall()
    }
    target_question = repository.get_question(question_ref) if question_ref else None
    all_questions = (
        [target_question]
        if target_question is not None
        else [
            repository.get_question(row["id"])
            for row in repository.connection.execute("SELECT id FROM questions ORDER BY id").fetchall()
        ]
    )
    created_claims: List[Claim] = []
    created_edges: List[Edge] = []
    for locator, sentence in sentences:
        normalized_quote = normalize_text(sentence)
        if not normalized_quote or normalized_quote in existing_quotes:
            continue
        stance = infer_stance(sentence)
        confidence = infer_confidence(sentence)
        claim = repository.add_claim(
            paper=paper.id,
            text=sentence,
            quote=sentence,
            locator=locator,
            stance=stance,
            confidence=confidence,
        )
        existing_quotes.add(normalized_quote)
        created_claims.append(claim)
        for question in all_questions:
            if question is None:
                continue
            if target_question is not None or _matches_question(sentence, paper.title, question.text):
                edge_kind = stance if stance in ("supports", "contradicts") else "answers"
                edge = _safe_add_edge(
                    repository,
                    src=f"claim:{claim.id}",
                    dst=f"question:{question.id}",
                    kind=edge_kind,
                    note=f"auto-linked from {paper.id} ({locator})",
                )
                if edge is not None:
                    created_edges.append(edge)
    return ExtractionResult(
        paper_id=paper.id,
        claims=tuple(created_claims),
        edges=tuple(created_edges),
    )


def extract_all(repository: Repository,
                question_ref: Optional[str] = None) -> Dict[str, Any]:
    """Run claim and edge extraction across every ingested paper in the graph."""
    paper_ids = [
        str(row["id"])
        for row in repository.connection.execute("SELECT id FROM papers ORDER BY id").fetchall()
    ]
    results: List[Dict[str, Any]] = []
    total_claims = 0
    total_edges = 0
    for paper_id in paper_ids:
        outcome = extract_from_paper(repository, paper_id, question_ref=question_ref)
        total_claims += len(outcome.claims)
        total_edges += len(outcome.edges)
        results.append(outcome.to_dict())
    return {
        "papers_processed": len(paper_ids),
        "claims_created": total_claims,
        "edges_created": total_edges,
        "results": results,
    }


def _is_empirical(sentence: str) -> bool:
    """Whether a sentence carries quantitative or empirical indicators."""
    lowered = sentence.lower()
    if _QUANT_RE.search(sentence):
        return True
    return any(marker in lowered for marker in _EMPIRICAL_MARKERS)


def _matches_question(sentence: str, title: str, question_text: str) -> bool:
    """Whether a claim sentence and its paper title share content keywords with a question."""
    stop = {"does", "what", "when", "where", "which", "with", "from", "that", "this", "have", "into"}
    q_terms = [
        term for term in normalize_text(question_text).split()
        if len(term) >= 4 and term not in stop
    ]
    if not q_terms:
        return False
    haystack = set(normalize_text(f"{title} {sentence}").split())
    overlap = sum(1 for term in q_terms if term in haystack)
    return overlap >= min(2, len(q_terms))


def _safe_add_edge(repository: Repository, src: str, dst: str,
                   kind: str, note: str) -> Optional[Edge]:
    """Add an edge if it does not already exist."""
    existing = repository.connection.execute(
        "SELECT 1 FROM edges WHERE src = ? AND dst = ? AND kind = ?",
        (src, dst, kind),
    ).fetchone()
    if existing is not None:
        return None
    return repository.add_edge(src, dst, kind, note=note)
