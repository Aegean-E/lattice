"""Contradiction detection, related-finding links, keystone ranking and evidence matrices."""

from collections import deque
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from lattice.errors import fail
from lattice.inquiry import STOPWORDS
from lattice.models import Edge, bare_id, entity_type, normalize_text, validate_edge_kind
from lattice.repository import Repository

_EXTRA_STOPWORDS = {
    "significantly",
    "improves",
    "improved",
    "improve",
    "fails",
    "failed",
    "fail",
    "increases",
    "decreases",
    "demonstrates",
    "indicates",
    "suggests",
    "associated",
    "compared",
}


@dataclass(frozen=True)
class ContradictionPair:
    """An opposing pair of empirical claims sharing a research question or high domain keyword overlap."""

    claim_a_id: str
    claim_b_id: str
    claim_a_text: str
    claim_b_text: str
    paper_a_id: str
    paper_b_id: str
    shared_question_ids: Tuple[str, ...]
    shared_keywords: Tuple[str, ...]
    score: float
    linked_edge_id: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        """JSON-serializable representation."""
        return {
            "claim_a_id": self.claim_a_id,
            "claim_b_id": self.claim_b_id,
            "claim_a_text": self.claim_a_text,
            "claim_b_text": self.claim_b_text,
            "paper_a_id": self.paper_a_id,
            "paper_b_id": self.paper_b_id,
            "shared_question_ids": list(self.shared_question_ids),
            "shared_keywords": list(self.shared_keywords),
            "score": self.score,
            "linked_edge_id": self.linked_edge_id,
        }


_RELATED_LINK_LIMIT = 3


@dataclass(frozen=True)
class RelatedPair:
    """Two findings related by a shared research question or a domain-keyword overlap."""

    claim_a_id: str
    claim_b_id: str
    claim_a_text: str
    claim_b_text: str
    paper_a_id: str
    paper_b_id: str
    shared_question_ids: Tuple[str, ...]
    shared_keywords: Tuple[str, ...]
    score: float

    def to_dict(self) -> Dict[str, Any]:
        """JSON-serializable representation."""
        return {
            "claim_a_id": self.claim_a_id,
            "claim_b_id": self.claim_b_id,
            "claim_a_text": self.claim_a_text,
            "claim_b_text": self.claim_b_text,
            "paper_a_id": self.paper_a_id,
            "paper_b_id": self.paper_b_id,
            "shared_question_ids": list(self.shared_question_ids),
            "shared_keywords": list(self.shared_keywords),
            "score": self.score,
        }


def _domain_keywords(text: str) -> Set[str]:
    """Extract informative domain keywords of length >= 4 from claim text."""
    words = normalize_text(text).split()
    return {
        word
        for word in words
        if len(word) >= 4 and word not in STOPWORDS and word not in _EXTRA_STOPWORDS
    }


def _claim_question_map(repo: Repository) -> Dict[str, Set[str]]:
    """Map bare claim IDs to bare question IDs linked via edges."""
    mapping: Dict[str, Set[str]] = {}
    rows = repo.connection.execute("SELECT src, dst FROM edges").fetchall()
    for row in rows:
        src, dst = str(row["src"]), str(row["dst"])
        if entity_type(src) == "claim" and entity_type(dst) == "question":
            mapping.setdefault(bare_id(src), set()).add(bare_id(dst))
        elif entity_type(dst) == "claim" and entity_type(src) == "question":
            mapping.setdefault(bare_id(dst), set()).add(bare_id(src))
    return mapping


def _find_or_create_contradicts_edge(
    repo: Repository,
    claim_a_id: str,
    claim_b_id: str,
    auto_link: bool,
) -> Optional[int]:
    """Return existing `contradicts` edge ID between two claims, or create one when `auto_link` is True."""
    ref_a = claim_a_id if ":" in claim_a_id else f"claim:{claim_a_id}"
    ref_b = claim_b_id if ":" in claim_b_id else f"claim:{claim_b_id}"
    row = repo.connection.execute(
        "SELECT id FROM edges WHERE kind = 'contradicts'"
        " AND ((src = ? AND dst = ?) OR (src = ? AND dst = ?)) LIMIT 1",
        (ref_a, ref_b, ref_b, ref_a),
    ).fetchone()
    if row is not None:
        return int(row["id"])
    if not auto_link:
        return None
    edge = repo.add_edge(
        ref_a,
        ref_b,
        kind="contradicts",
        note="Auto-detected opposing stance on shared scientific topic",
    )
    return edge.id


def detect_contradictions(repo: Repository, auto_link: bool = False) -> List[ContradictionPair]:
    """Detect pairs of opposing claims (`supports` vs `contradicts`) across questions or domain topics."""
    claim_rows = repo.connection.execute(
        "SELECT id, paper_id, text, stance, confidence FROM claims ORDER BY id"
    ).fetchall()
    supporting = [row for row in claim_rows if str(row["stance"]) == "supports"]
    contradicting = [row for row in claim_rows if str(row["stance"]) == "contradicts"]
    q_map = _claim_question_map(repo)

    pairs: List[ContradictionPair] = []
    for sup in supporting:
        sup_id = str(sup["id"])
        sup_kw = _domain_keywords(str(sup["text"]))
        sup_qs = q_map.get(sup_id, set())
        for con in contradicting:
            con_id = str(con["id"])
            if sup_id == con_id:
                continue
            con_kw = _domain_keywords(str(con["text"]))
            con_qs = q_map.get(con_id, set())
            shared_qs = tuple(sorted(sup_qs & con_qs))
            shared_kw = tuple(sorted(sup_kw & con_kw))
            if not shared_qs and len(shared_kw) < 2:
                continue
            avg_conf = (float(sup["confidence"]) + float(con["confidence"])) / 2.0
            overlap_bonus = min(1.0, (len(shared_qs) * 0.4) + (len(shared_kw) * 0.15))
            score = round(min(1.0, avg_conf * 0.6 + overlap_bonus * 0.4), 3)
            edge_id = _find_or_create_contradicts_edge(repo, sup_id, con_id, auto_link=auto_link)
            pairs.append(
                ContradictionPair(
                    claim_a_id=sup_id,
                    claim_b_id=con_id,
                    claim_a_text=str(sup["text"]),
                    claim_b_text=str(con["text"]),
                    paper_a_id=str(sup["paper_id"]),
                    paper_b_id=str(con["paper_id"]),
                    shared_question_ids=shared_qs,
                    shared_keywords=shared_kw,
                    score=score,
                    linked_edge_id=edge_id,
                )
            )
    pairs.sort(key=lambda item: (item.score, len(item.shared_question_ids), len(item.shared_keywords)), reverse=True)
    return pairs


def _connected_claim_pairs(repo: Repository) -> Set[Tuple[str, str]]:
    """Unordered bare claim-ID pairs that any claim-to-claim edge already joins."""
    pairs: Set[Tuple[str, str]] = set()
    for row in repo.connection.execute("SELECT src, dst FROM edges").fetchall():
        src, dst = str(row["src"]), str(row["dst"])
        if entity_type(src) == "claim" and entity_type(dst) == "claim":
            pairs.add(tuple(sorted((bare_id(src), bare_id(dst)))))
    return pairs


def find_related_findings(repo: Repository, claim_ids: Optional[Sequence[str]] = None,
                          limit_per_claim: int = _RELATED_LINK_LIMIT) -> List[RelatedPair]:
    """Detect findings sharing a research question or enough domain keywords to be related.

    The pass is deterministic: claims are visited in identifier order, candidates rank by
    shared-question count, shared-keyword count and identifier, and each claim gains at most
    ``limit_per_claim`` new links. Pairs already joined by any claim-to-claim edge and pairs
    with opposing stances (owned by contradiction detection) are skipped.
    """
    cap = max(1, int(limit_per_claim))
    scope = None if claim_ids is None else {
        bare_id(str(item)) if ":" in str(item) else str(item) for item in claim_ids
    }
    rows = repo.connection.execute(
        "SELECT id, paper_id, text, stance FROM claims ORDER BY id"
    ).fetchall()
    claim_ids_all = [str(row["id"]) for row in rows]
    if len(claim_ids_all) < 2:
        return []
    text_by_id = {str(row["id"]): str(row["text"]) for row in rows}
    paper_by_id = {str(row["id"]): str(row["paper_id"]) for row in rows}
    stance_by_id = {str(row["id"]): str(row["stance"]) for row in rows}
    keywords = {claim_id: _domain_keywords(text) for claim_id, text in text_by_id.items()}
    question_map = _claim_question_map(repo)
    connected = _connected_claim_pairs(repo)
    degree: Dict[str, int] = {claim_id: 0 for claim_id in claim_ids_all}
    for left, right in connected:
        if left in degree:
            degree[left] += 1
        if right in degree:
            degree[right] += 1
    seeds = sorted(scope & set(claim_ids_all)) if scope is not None else claim_ids_all
    chosen: List[RelatedPair] = []
    selected: Set[Tuple[str, str]] = set()
    for current in seeds:
        if degree.get(current, 0) >= cap:
            continue
        candidates = []
        for other in claim_ids_all:
            if other == current:
                continue
            pair = tuple(sorted((current, other)))
            if pair in connected or pair in selected:
                continue
            if {stance_by_id[current], stance_by_id[other]} == {"supports", "contradicts"}:
                continue
            shared_questions = tuple(sorted(
                question_map.get(current, set()) & question_map.get(other, set())))
            shared_keywords = tuple(sorted(keywords[current] & keywords[other]))
            if not shared_questions and len(shared_keywords) < 2:
                continue
            candidates.append((len(shared_questions), len(shared_keywords), other,
                               shared_questions, shared_keywords))
        candidates.sort(key=lambda item: (-item[0], -item[1], item[2]))
        for _, _, other, shared_questions, shared_keywords in candidates:
            if degree.get(current, 0) >= cap:
                break
            pair = tuple(sorted((current, other)))
            if pair in selected or degree.get(other, 0) >= cap:
                continue
            selected.add(pair)
            degree[current] = degree.get(current, 0) + 1
            degree[other] = degree.get(other, 0) + 1
            first, second = pair
            score = round(min(1.0, (len(shared_questions) * 0.5)
                              + (len(shared_keywords) * 0.15)), 3)
            chosen.append(RelatedPair(
                claim_a_id=first,
                claim_b_id=second,
                claim_a_text=text_by_id[first],
                claim_b_text=text_by_id[second],
                paper_a_id=paper_by_id[first],
                paper_b_id=paper_by_id[second],
                shared_question_ids=shared_questions,
                shared_keywords=shared_keywords,
                score=score,
            ))
    return chosen


def link_related_findings(repo: Repository, claim_ids: Optional[Sequence[str]] = None,
                          limit_per_claim: int = _RELATED_LINK_LIMIT) -> List[Edge]:
    """Create `related` edges for detected finding pairs that are not linked yet."""
    created: List[Edge] = []
    for pair in find_related_findings(repo, claim_ids=claim_ids, limit_per_claim=limit_per_claim):
        reasons = []
        if pair.shared_question_ids:
            reasons.append("shared question " + ", ".join(pair.shared_question_ids))
        if pair.shared_keywords:
            reasons.append("keywords: " + ", ".join(pair.shared_keywords[:4]))
        created.append(repo.add_edge(
            f"claim:{pair.claim_a_id}", f"claim:{pair.claim_b_id}", "related",
            note="Auto-detected related findings (" + "; ".join(reasons) + ")",
        ))
    return created


def _related_reason(entry: Dict[str, Any]) -> str:
    """Human-readable explanation of why a finding is related."""
    parts = []
    if entry.get("edge_id") is not None:
        parts.append(f"linked by a {entry['relation']} edge")
    if entry["shared_questions"]:
        parts.append("shares question " + ", ".join(sorted(entry["shared_questions"])))
    if entry["shared_keywords"]:
        parts.append("keywords: " + ", ".join(sorted(entry["shared_keywords"])[:4]))
    return "; ".join(parts) or "same topic"


def related_findings(repo: Repository, ref: str, limit: int = 10) -> Dict[str, Any]:
    """Findings connected to a claim, paper or question, with reasons and next-hop references.

    For a claim the seeds are the claim itself. For a paper the seeds are its findings, and for
    a question its linked evidence. Direct claim-to-claim edges are reported first, then findings
    sharing a question (co-evidence) and finally findings that only share domain keywords.
    """
    entity = repo.get(ref)
    resolved = str(entity["ref"])
    kind = entity_type(resolved)
    cap = max(1, int(limit))
    rows = repo.connection.execute(
        "SELECT id, paper_id, text, stance, confidence FROM claims ORDER BY id"
    ).fetchall()
    by_id = {str(row["id"]): row for row in rows}
    text_by_id = {claim_id: str(row["text"]) for claim_id, row in by_id.items()}
    paper_by_id = {claim_id: str(row["paper_id"]) for claim_id, row in by_id.items()}
    stance_by_id = {claim_id: str(row["stance"]) for claim_id, row in by_id.items()}
    confidence_by_id = {claim_id: float(row["confidence"]) for claim_id, row in by_id.items()}
    keywords_by_id = {claim_id: _domain_keywords(text) for claim_id, text in text_by_id.items()}
    question_map = _claim_question_map(repo)
    paper_rows = repo.connection.execute("SELECT id, title, study_type FROM papers").fetchall()
    paper_titles = {str(row["id"]): str(row["title"]) for row in paper_rows}
    study_types = {str(row["id"]): str(row["study_type"]) for row in paper_rows}
    if kind == "claim":
        seeds = [bare_id(resolved)]
    elif kind == "paper":
        paper_id = bare_id(resolved)
        seeds = [claim_id for claim_id, paper in paper_by_id.items() if paper == paper_id]
    else:
        seeds = []
        for row in repo.connection.execute(
                "SELECT src, dst FROM edges WHERE (src = ? OR dst = ?)"
                " AND kind IN ('supports', 'contradicts', 'answers')",
                (resolved, resolved)).fetchall():
            src, dst = str(row["src"]), str(row["dst"])
            if entity_type(src) == "claim" and entity_type(dst) == "question":
                seeds.append(bare_id(src))
            elif entity_type(dst) == "claim" and entity_type(src) == "question":
                seeds.append(bare_id(dst))
    seeds = sorted(set(seeds))
    seed_set = set(seeds)
    entries: Dict[str, Dict[str, Any]] = {}
    for row in repo.connection.execute("SELECT * FROM edges ORDER BY id").fetchall():
        src, dst, edge_kind = str(row["src"]), str(row["dst"]), str(row["kind"])
        if entity_type(src) != "claim" or entity_type(dst) != "claim":
            continue
        left, right = bare_id(src), bare_id(dst)
        if left in seed_set and right not in seed_set:
            other, via = right, left
        elif right in seed_set and left not in seed_set:
            other, via = left, right
        else:
            continue
        entry = entries.setdefault(other, {
            "relation": edge_kind,
            "edge_id": int(row["id"]),
            "via": set(),
            "shared_questions": set(),
            "shared_keywords": set(),
        })
        entry["via"].add(via)
    for other in sorted(set(by_id) - seed_set):
        entry = entries.get(other)
        shared_questions: Set[str] = set()
        shared_keywords: Set[str] = set()
        via: Set[str] = set()
        for seed in seeds:
            seed_questions = question_map.get(seed, set()) & question_map.get(other, set())
            seed_keywords = keywords_by_id.get(seed, set()) & keywords_by_id.get(other, set())
            shared_questions |= seed_questions
            shared_keywords |= seed_keywords
            if seed_questions or len(seed_keywords) >= 2:
                via.add(seed)
        if entry is None:
            if not shared_questions and len(shared_keywords) < 2:
                continue
            entry = {
                "relation": "co-evidence" if shared_questions else "topic-overlap",
                "edge_id": None,
                "via": set(),
                "shared_questions": set(),
                "shared_keywords": set(),
            }
            entries[other] = entry
        entry["via"] |= via
        entry["shared_questions"] |= shared_questions
        entry["shared_keywords"] |= shared_keywords
    rank = {"contradicts": 0, "supports": 1, "related": 2, "replicates": 3,
            "extends": 4, "mentions": 5, "co-evidence": 6, "topic-overlap": 7}
    related: List[Dict[str, Any]] = []
    for other, entry in entries.items():
        paper = paper_by_id.get(other, "")
        related.append({
            "ref": f"claim:{other}",
            "id": other,
            "text": text_by_id.get(other, ""),
            "stance": stance_by_id.get(other, ""),
            "confidence": confidence_by_id.get(other, 0.0),
            "paper": paper,
            "paper_title": paper_titles.get(paper, ""),
            "study_type": study_types.get(paper, ""),
            "relation": entry["relation"],
            "edge_id": entry["edge_id"],
            "via": sorted(entry["via"]),
            "shared_questions": sorted(entry["shared_questions"]),
            "shared_keywords": sorted(entry["shared_keywords"]),
            "reason": _related_reason(entry),
        })
    related.sort(key=lambda item: (rank.get(item["relation"], 9),
                                   -len(item["shared_questions"]),
                                   -len(item["shared_keywords"]), item["id"]))
    return {"root": resolved, "type": kind, "seeds": [f"claim:{seed}" for seed in seeds],
            "count": len(related[:cap]), "related": related[:cap]}


def rank_influential_entities(repo: Repository, limit: int = 10) -> Dict[str, List[Dict[str, Any]]]:
    """Rank keystone papers and claims by evidence centrality, citation degree, and confidence."""
    cap = max(1, int(limit))
    edge_rows = repo.connection.execute("SELECT src, dst, kind FROM edges").fetchall()
    degree_by_ref: Dict[str, int] = {}
    citations_by_paper: Dict[str, int] = {}
    for row in edge_rows:
        src, dst, kind = str(row["src"]), str(row["dst"]), str(row["kind"])
        degree_by_ref[src] = degree_by_ref.get(src, 0) + 1
        degree_by_ref[dst] = degree_by_ref.get(dst, 0) + 1
        if kind == "cites" and entity_type(dst) == "paper":
            pid = bare_id(dst)
            citations_by_paper[pid] = citations_by_paper.get(pid, 0) + 1

    claim_rows = repo.connection.execute(
        "SELECT id, paper_id, text, stance, confidence FROM claims ORDER BY id"
    ).fetchall()
    claims_by_paper: Dict[str, List[Dict[str, Any]]] = {}
    ranked_claims: List[Dict[str, Any]] = []
    for row in claim_rows:
        cid = str(row["id"])
        pid = str(row["paper_id"])
        conf = float(row["confidence"])
        deg = degree_by_ref.get(f"claim:{cid}", 0)
        score = round(conf + (deg * 0.35), 3)
        entry = {
            "id": cid,
            "paper_id": pid,
            "text": str(row["text"]),
            "stance": str(row["stance"]),
            "confidence": conf,
            "edge_degree": deg,
            "score": score,
        }
        claims_by_paper.setdefault(pid, []).append(entry)
        ranked_claims.append(entry)
    ranked_claims.sort(key=lambda item: (item["score"], item["confidence"]), reverse=True)

    paper_rows = repo.connection.execute(
        "SELECT id, title, authors, year, doi FROM papers ORDER BY id"
    ).fetchall()
    ranked_papers: List[Dict[str, Any]] = []
    for row in paper_rows:
        pid = str(row["id"])
        p_claims = claims_by_paper.get(pid, [])
        claim_weight = sum(item["score"] for item in p_claims)
        cite_count = citations_by_paper.get(pid, 0)
        p_deg = degree_by_ref.get(f"paper:{pid}", 0)
        score = round(claim_weight + (cite_count * 0.75) + (p_deg * 0.25) + 0.1, 3)
        ranked_papers.append(
            {
                "id": pid,
                "title": str(row["title"]),
                "authors": str(row["authors"]),
                "year": str(row["year"]),
                "doi": str(row["doi"]),
                "claim_count": len(p_claims),
                "citation_count": cite_count,
                "edge_degree": p_deg,
                "score": score,
            }
        )
    ranked_papers.sort(key=lambda item: (item["score"], item["claim_count"]), reverse=True)
    return {
        "papers": ranked_papers[:cap],
        "claims": ranked_claims[:cap],
    }


def build_evidence_matrix(repo: Repository) -> Dict[str, Any]:
    """Build a Paper x Question evidence matrix highlighting stance cells and coverage gaps."""
    paper_rows = repo.connection.execute(
        "SELECT id, title, authors, year, doi, tags, study_type FROM papers"
        " ORDER BY year DESC, title"
    ).fetchall()
    papers = [
        {
            "id": str(row["id"]),
            "title": str(row["title"]),
            "authors": str(row["authors"]),
            "year": str(row["year"]),
            "doi": str(row["doi"]),
            "tags": str(row["tags"]),
            "study_type": str(row["study_type"]),
        }
        for row in paper_rows
    ]
    claim_rows = repo.connection.execute(
        "SELECT id, paper_id, text, stance, confidence FROM claims ORDER BY id"
    ).fetchall()
    claim_by_id = {
        str(row["id"]): {
            "id": str(row["id"]),
            "paper_id": str(row["paper_id"]),
            "text": str(row["text"]),
            "stance": str(row["stance"]),
            "confidence": float(row["confidence"]),
        }
        for row in claim_rows
    }
    q_rows = repo.connection.execute(
        "SELECT id, text, status FROM questions ORDER BY id"
    ).fetchall()
    edge_rows = repo.connection.execute("SELECT src, dst, kind FROM edges").fetchall()

    q_claims: Dict[str, List[Dict[str, Any]]] = {str(r["id"]): [] for r in q_rows}
    for row in edge_rows:
        src, dst = str(row["src"]), str(row["dst"])
        if entity_type(src) == "claim" and entity_type(dst) == "question":
            cid, qid = bare_id(src), bare_id(dst)
        elif entity_type(dst) == "claim" and entity_type(src) == "question":
            cid, qid = bare_id(dst), bare_id(src)
        else:
            continue
        if qid in q_claims and cid in claim_by_id:
            q_claims[qid].append(claim_by_id[cid])

    cells: List[Dict[str, Any]] = []
    questions: List[Dict[str, Any]] = []
    gaps: List[Dict[str, Any]] = []

    for q_row in q_rows:
        qid = str(q_row["id"])
        q_text = str(q_row["text"])
        linked = q_claims.get(qid, [])
        by_paper: Dict[str, List[Dict[str, Any]]] = {}
        sup_count = 0
        con_count = 0
        for claim in linked:
            by_paper.setdefault(claim["paper_id"], []).append(claim)
            if claim["stance"] == "supports":
                sup_count += 1
            elif claim["stance"] == "contradicts":
                con_count += 1
        for pid, p_claims in sorted(by_paper.items()):
            stances = [c["stance"] for c in p_claims]
            if "supports" in stances and "contradicts" in stances:
                dominant = "contested"
            elif "supports" in stances:
                dominant = "supports"
            elif "contradicts" in stances:
                dominant = "contradicts"
            else:
                dominant = "mentions"
            cells.append(
                {
                    "paper_id": pid,
                    "question_id": qid,
                    "claim_ids": [c["id"] for c in p_claims],
                    "stances": stances,
                    "dominant_stance": dominant,
                    "max_confidence": max(c["confidence"] for c in p_claims),
                }
            )
        has_gap = len(by_paper) == 0
        questions.append(
            {
                "id": qid,
                "prompt": q_text,
                "status": str(q_row["status"]),
                "supporting_count": sup_count,
                "contradicting_count": con_count,
                "answering_paper_count": len(by_paper),
                "coverage_gap": has_gap,
            }
        )
        if has_gap:
            gaps.append(
                {
                    "question_id": qid,
                    "prompt": q_text,
                    "reason": "Zero papers have linked empirical claims for this research question.",
                }
            )
        elif sup_count > 0 and con_count > 0:
            gaps.append(
                {
                    "question_id": qid,
                    "prompt": q_text,
                    "reason": f"Contested evidence ({sup_count} supporting vs {con_count} contradicting claims).",
                }
            )

    return {
        "papers": papers,
        "questions": questions,
        "cells": cells,
        "gaps": gaps,
    }


def find_path(repo: Repository,
              src: str,
              dst: str,
              max_depth: int = 5,
              directed: bool = False,
              edge_kinds: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    """Find the shortest chain of relations connecting two entities via BFS.

    Returns a dictionary with:
      - found: bool (whether a path was found)
      - length: int (number of edge hops, 0 for self, -1 if no path)
      - steps: list of edge transitions
      - nodes: list of entity summaries along the path
      - narrative: human-readable explanation of the evidence path
    """
    if not isinstance(max_depth, int) or max_depth < 1 or max_depth > 10:
        fail("max_depth must be an integer between 1 and 10",
             f"received {max_depth}",
             "pass max_depth between 1 and 10")

    source_ref = repo._resolve(src)
    target_ref = repo._resolve(dst)

    # Validate that both entities exist in repository
    source_summary = repo._summary(source_ref)
    target_summary = repo._summary(target_ref)

    allowed_kinds: Optional[Set[str]] = None
    if edge_kinds:
        allowed_kinds = {validate_edge_kind(k) for k in edge_kinds}

    if source_ref == target_ref:
        return {
            "found": True,
            "length": 0,
            "steps": [],
            "nodes": [source_summary],
            "narrative": f"Source and target are the same entity ({source_ref}).",
        }

    queue: deque[Tuple[str, List[Dict[str, Any]]]] = deque([(source_ref, [])])
    visited: Set[str] = {source_ref}
    found_steps: Optional[List[Dict[str, Any]]] = None

    while queue:
        current, steps = queue.popleft()
        if len(steps) >= max_depth:
            continue

        if directed:
            query = "SELECT id, src, dst, kind, note FROM edges WHERE src = ? ORDER BY id"
            params: Tuple[Any, ...] = (current,)
        else:
            query = "SELECT id, src, dst, kind, note FROM edges WHERE src = ? OR dst = ? ORDER BY id"
            params = (current, current)

        rows = repo.connection.execute(query, params).fetchall()
        for row in rows:
            edge_id = int(row["id"])
            edge_src = str(row["src"])
            edge_dst = str(row["dst"])
            edge_kind = str(row["kind"])
            edge_note = str(row["note"])

            if allowed_kinds is not None and edge_kind not in allowed_kinds:
                continue

            if edge_src == current:
                nxt = edge_dst
                direction = "forward"
            else:
                nxt = edge_src
                direction = "reverse"

            step = {
                "from": current,
                "to": nxt,
                "kind": edge_kind,
                "edge_id": edge_id,
                "direction": direction,
                "note": edge_note,
            }
            new_steps = steps + [step]

            if nxt == target_ref:
                found_steps = new_steps
                break

            if nxt not in visited:
                visited.add(nxt)
                queue.append((nxt, new_steps))

        if found_steps is not None:
            break

    if found_steps is None:
        return {
            "found": False,
            "length": -1,
            "steps": [],
            "nodes": [],
            "narrative": f"No path found between {source_ref} and {target_ref} within {max_depth} hops.",
        }

    # Collect nodes along the path
    node_refs = [source_ref] + [s["to"] for s in found_steps]
    nodes = [repo._summary(r) for r in node_refs]

    # Formulate narrative explanation
    narrative_parts = []
    for s in found_steps:
        from_name = s["from"]
        to_name = s["to"]
        kind = s["kind"]
        if s["direction"] == "forward":
            narrative_parts.append(f"{from_name} ({kind}) -> {to_name}")
        else:
            narrative_parts.append(f"{from_name} <- ({kind}) {to_name}")
    narrative = " then ".join(narrative_parts)

    return {
        "found": True,
        "length": len(found_steps),
        "steps": found_steps,
        "nodes": nodes,
        "narrative": narrative,
    }
