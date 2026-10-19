"""Scientific contradiction detection, keystone entity centrality, and Paper x Question evidence matrices."""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple

from lattice.inquiry import STOPWORDS
from lattice.models import bare_id, entity_type, normalize_text
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
        "SELECT id, title, authors, year, doi FROM papers ORDER BY year DESC, title"
    ).fetchall()
    papers = [
        {
            "id": str(row["id"]),
            "title": str(row["title"]),
            "authors": str(row["authors"]),
            "year": str(row["year"]),
            "doi": str(row["doi"]),
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
