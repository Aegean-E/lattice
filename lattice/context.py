"""Token-budgeted context views for AI agents: peek, search, expand, drill down.

The views are pure functions over the repository's full payloads. Every item keeps its stable
`ref` so an agent can walk the graph recursively, and every trimmed list reports how many items
were omitted instead of overflowing the caller's context window.
"""

import json
from typing import Any, Dict, List, Sequence, Tuple

from lattice.errors import fail
from lattice.models import estimate_tokens
from lattice.repository import Repository

MIN_TOKENS = 100
_RESERVE = 40


def _budget(tokens: int) -> int:
    """Validate a token budget and return it as an integer."""
    value = int(tokens)
    if value < MIN_TOKENS:
        fail(f"token budget {value} is too small", "a compact context needs room for handles",
             f"pass {MIN_TOKENS} tokens or more")
    return value


def _truncate(text: Any, limit: int) -> str:
    """Collapse whitespace and shorten a value to `limit` characters."""
    value = " ".join(str(text or "").split())
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 3)].rstrip() + "..."


def _cost(item: Dict[str, Any]) -> int:
    """Estimated tokens of one JSON item."""
    return estimate_tokens(json.dumps(item, sort_keys=True))


def _pack(items: Sequence[Dict[str, Any]], tokens: int) -> Tuple[List[Dict[str, Any]], int, int]:
    """Keep as many leading items as fit, returning `(kept, omitted, used_tokens)`.

    The first item is always kept so a very small budget still yields a usable handle.
    """
    room = max(0, int(tokens) - _RESERVE)
    kept: List[Dict[str, Any]] = []
    used = 0
    for item in items:
        cost = _cost(item)
        if kept and used + cost > room:
            break
        kept.append(item)
        used += cost
    return kept, len(items) - len(kept), used


def outline(repository: Repository, tokens: int = 400) -> Dict[str, Any]:
    """A cheap orientation map: counts, edge kinds, study types and evidenced questions."""
    budget = _budget(tokens)
    stats = repository.stats()
    rows = repository.connection.execute(
        "SELECT q.id, q.text, q.status,"
        " (SELECT COUNT(*) FROM edges e WHERE (e.src = 'question:' || q.id"
        "   OR e.dst = 'question:' || q.id)"
        "   AND e.kind IN ('supports', 'contradicts', 'answers')) AS evidence"
        " FROM questions q ORDER BY evidence DESC, q.id"
    ).fetchall()
    questions = [
        {
            "ref": f"question:{row['id']}",
            "text": _truncate(row["text"], 110),
            "status": str(row["status"]),
            "evidence": int(row["evidence"]),
        }
        for row in rows
    ]
    kept, omitted, _ = _pack(questions, max(60, budget - 140))
    type_rows = repository.connection.execute(
        "SELECT study_type, COUNT(*) AS n FROM papers WHERE study_type != ''"
        " GROUP BY study_type ORDER BY n DESC, study_type LIMIT 8"
    ).fetchall()
    return {
        "counts": {key: value for key, value in stats.items() if key != "edge_kinds"},
        "edge_kinds": stats.get("edge_kinds", {}),
        "study_types": [
            {"study_type": str(row["study_type"]), "papers": int(row["n"])}
            for row in type_rows
        ],
        "budget_tokens": budget,
        "questions": kept,
        "omitted_questions": omitted,
        "next": "Pick a ref, then search, related_findings or subgraph; get_entity expands one node.",
    }


def compact_search(result: Dict[str, Any], tokens: int = 800) -> Dict[str, Any]:
    """Search hits as short handles, split across papers, claims and questions."""
    budget = _budget(tokens)
    share = max(60, budget // 3)
    papers = [
        {
            "ref": f"paper:{paper['id']}",
            "title": _truncate(paper.get("title"), 120),
            "year": str(paper.get("year") or ""),
            "study_type": str(paper.get("study_type") or ""),
        }
        for paper in result.get("papers", [])
    ]
    claims = [
        {
            "ref": f"claim:{claim['id']}",
            "snippet": _truncate(claim.get("text"), 160),
            "stance": str(claim.get("stance") or ""),
            "confidence": claim.get("confidence", 0.0),
            "paper": str((claim.get("paper") or {}).get("id") or ""),
        }
        for claim in result.get("claims", [])
    ]
    questions = [
        {
            "ref": f"question:{question['id']}",
            "text": _truncate(question.get("text"), 120),
            "status": str(question.get("status") or ""),
        }
        for question in result.get("questions", [])
    ]
    kept_papers, omitted_papers, _ = _pack(papers, share)
    kept_claims, omitted_claims, _ = _pack(claims, share)
    kept_questions, omitted_questions, _ = _pack(questions, max(60, budget - (2 * share)))
    return {
        "query": str(result.get("query") or ""),
        "budget_tokens": budget,
        "papers": kept_papers,
        "omitted_papers": omitted_papers,
        "claims": kept_claims,
        "omitted_claims": omitted_claims,
        "questions": kept_questions,
        "omitted_questions": omitted_questions,
        "next": "Expand a ref with get_entity; list neighbors with related_findings.",
    }


def compact_related(result: Dict[str, Any], tokens: int = 600) -> Dict[str, Any]:
    """Related-finding navigation as short snippets, reasons and next-hop refs."""
    budget = _budget(tokens)
    items = [
        {
            "ref": item["ref"],
            "relation": str(item.get("relation") or ""),
            "snippet": _truncate(item.get("text"), 160),
            "stance": str(item.get("stance") or ""),
            "confidence": item.get("confidence", 0.0),
            "paper": str(item.get("paper") or ""),
            "study_type": str(item.get("study_type") or ""),
            "reason": _truncate(item.get("reason"), 120),
            "via": item.get("via", []),
        }
        for item in result.get("related", [])
    ]
    kept, omitted, _ = _pack(items, budget)
    return {
        "root": str(result.get("root") or ""),
        "type": str(result.get("type") or ""),
        "budget_tokens": budget,
        "count": len(kept),
        "omitted": omitted,
        "related": kept,
        "next": "Call related_findings on any ref to continue, or get_entity for the full claim.",
    }


def compact_subgraph(result: Dict[str, Any], tokens: int = 800) -> Dict[str, Any]:
    """A subgraph as short node labels and bare edges, trimmed around a token budget."""
    budget = _budget(tokens)
    nodes = [
        {
            "ref": node["ref"],
            "type": str(node.get("type") or ""),
            "label": _truncate(node.get("title") or node.get("text") or node["ref"], 100),
            "study_type": str(node.get("study_type") or ""),
        }
        for node in result.get("nodes", [])
    ]
    kept_nodes, omitted_nodes, used = _pack(nodes, budget)
    kept_refs = {node["ref"] for node in kept_nodes}
    edges = [
        {"src": edge["src"], "dst": edge["dst"], "kind": edge["kind"]}
        for edge in result.get("edges", [])
        if edge["src"] in kept_refs and edge["dst"] in kept_refs
    ]
    kept_edges, omitted_edges, _ = _pack(edges, max(60, budget - used))
    return {
        "root": str(result.get("root") or ""),
        "depth": int(result.get("depth", 1)),
        "budget_tokens": budget,
        "nodes": kept_nodes,
        "omitted_nodes": omitted_nodes,
        "edges": kept_edges,
        "omitted_edges": omitted_edges,
        "next": "Pick a node ref and call subgraph again to walk outward, or get_entity to read it.",
    }
