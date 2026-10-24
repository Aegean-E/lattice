"""Token-budgeted context views for AI agents: peek, search, expand, drill down.

The views are pure functions over the repository's full payloads. Every item keeps its stable
`ref` so an agent can walk the graph recursively, and every trimmed list reports how many items
were omitted instead of overflowing the caller's context window.
"""

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

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


@dataclass(frozen=True)
class ContextPack:
    """Token-budgeted GraphRAG context pack for LLM reasoning and question-answering."""

    targets: List[str]
    budget_tokens: int
    estimated_tokens: int
    format: str
    content: str
    data: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        """JSON-ready representation."""
        return {
            "targets": self.targets,
            "budget_tokens": self.budget_tokens,
            "estimated_tokens": self.estimated_tokens,
            "format": self.format,
            "content": self.content,
            "data": self.data,
        }


def _render_markdown_pack(
    targets: List[str],
    questions: List[Dict[str, Any]],
    claims: List[Dict[str, Any]],
    papers: List[Dict[str, Any]],
    contradictions: List[Dict[str, Any]],
    budget: int,
) -> Tuple[str, List[Dict[str, Any]], int]:
    papers_by_id = {p["id"]: p for p in papers}

    def _render(kept_c: List[Dict[str, Any]], omitted_c: int) -> str:
        lines: List[str] = [
            "# GraphRAG Evidence Pack",
            f"**Targets:** {', '.join(targets) if targets else '(global)'}",
            "",
            "## 1. Research Questions",
        ]
        if questions:
            for q in questions:
                lines.append(f"- **[{q['id']}]** {q['text']} *(status: {q.get('status', 'open')})*")
        else:
            lines.append("*(No specific questions linked)*")

        lines.extend(["", "## 2. Evidentiary Claims & Quotes"])
        if kept_c:
            for c in kept_c:
                p = papers_by_id.get(c.get("paper_id", ""))
                src_label = f"{p['title']} ({p.get('year') or 'n.d.'})" if p else (c.get("paper_id") or "unknown")
                lines.append(f"- **[{c['id']}]** {c['text']}")
                lines.append(f"  - *Stance:* `{c.get('stance', 'mentions')}` | *Confidence:* {float(c.get('confidence', 0.5)):.2f}")
                if c.get("quote"):
                    lines.append(f"  - *Verbatim Quote:* \"{c['quote']}\"")
                lines.append(f"  - *Source Paper:* {src_label}")
        else:
            lines.append("*(No empirical claims available)*")

        if omitted_c > 0:
            lines.append(f"\n> [!NOTE]\n> {omitted_c} claim(s) omitted to fit within token budget.")

        if contradictions:
            lines.extend(["", "## 3. Scientific Contradictions & Tensions"])
            for pair in contradictions:
                lines.append(f"- **Tension:** `{pair['claim_a_id']}` vs `{pair['claim_b_id']}` (Score: {float(pair.get('score', 0)):.2f})")
                lines.append(f"  - *Claim A:* {pair.get('claim_a_text', '')}")
                lines.append(f"  - *Claim B:* {pair.get('claim_b_text', '')}")

        lines.extend(["", "## 4. Ingested Papers & Provenance"])
        if papers:
            for p in papers:
                venue_str = f" | {p['venue']}" if p.get("venue") else ""
                doi_str = f" | DOI: {p['doi']}" if p.get("doi") else ""
                study_str = f" [{p['study_type']}]" if p.get("study_type") else ""
                lines.append(f"- **[{p['id']}]** {p['title']} ({p.get('year') or 'n.d.'}){study_str}{venue_str}{doi_str}")
        else:
            lines.append("*(No source papers)*")

        return "\n".join(lines)

    kept: List[Dict[str, Any]] = list(claims)
    while len(kept) > 1 and estimate_tokens(_render(kept, len(claims) - len(kept))) > budget:
        kept.pop()

    md = _render(kept, len(claims) - len(kept))
    return md, kept, len(claims) - len(kept)


def _render_json_pack(
    targets: List[str],
    questions: List[Dict[str, Any]],
    claims: List[Dict[str, Any]],
    papers: List[Dict[str, Any]],
    contradictions: List[Dict[str, Any]],
    budget: int,
) -> Tuple[str, List[Dict[str, Any]], int]:
    kept: List[Dict[str, Any]] = list(claims)
    while len(kept) > 1:
        payload = {
            "targets": targets,
            "budget_tokens": budget,
            "counts": {
                "questions": len(questions),
                "claims": len(kept),
                "omitted_claims": len(claims) - len(kept),
                "papers": len(papers),
                "contradictions": len(contradictions),
            },
            "questions": questions,
            "claims": kept,
            "papers": papers,
            "contradictions": contradictions,
        }
        text = json.dumps(payload, indent=2, sort_keys=True)
        if estimate_tokens(text) <= budget:
            return text, kept, len(claims) - len(kept)
        kept.pop()

    payload = {
        "targets": targets,
        "budget_tokens": budget,
        "counts": {
            "questions": len(questions),
            "claims": len(kept),
            "omitted_claims": len(claims) - len(kept),
            "papers": len(papers),
            "contradictions": len(contradictions),
        },
        "questions": questions,
        "claims": kept,
        "papers": papers,
        "contradictions": contradictions,
    }
    return json.dumps(payload, indent=2, sort_keys=True), kept, len(claims) - len(kept)


def build_context_pack(
    repository: Repository,
    targets: Optional[Sequence[str] | str] = None,
    max_tokens: int = 2000,
    format: str = "markdown",
) -> ContextPack:
    """Assemble a high-density, token-bounded GraphRAG context pack for AI agents."""
    budget = _budget(max_tokens)
    norm_format = str(format or "markdown").strip().lower()
    if norm_format not in ("markdown", "json"):
        fail(
            f"unknown format '{format}'",
            "context packs support markdown or json",
            "pass format='markdown' or format='json'",
        )

    target_list: List[str] = []
    if targets is None:
        rows = repository.connection.execute("SELECT id FROM questions ORDER BY id LIMIT 5").fetchall()
        target_list = [f"question:{r['id']}" for r in rows]
    elif isinstance(targets, str):
        cleaned = targets.strip()
        if cleaned:
            target_list = [cleaned]
    else:
        target_list = [str(t).strip() for t in targets if str(t).strip()]

    questions_map: Dict[str, Dict[str, Any]] = {}
    claims_map: Dict[str, Dict[str, Any]] = {}
    papers_map: Dict[str, Dict[str, Any]] = {}

    for t in target_list:
        clean = t
        if clean.startswith("question:"):
            q_id = clean.split(":", 1)[1]
            q = repository.get_question(q_id)
            if q:
                questions_map[q.id] = q.to_dict()
                q_ref = f"question:{q.id}"
                for edge in repository.neighbors(q_ref):
                    other = edge.dst if edge.src == q_ref else edge.src
                    if other.startswith("claim:"):
                        cid = other.split(":", 1)[1]
                        c = repository.get_claim(cid)
                        if c:
                            claims_map[c.id] = c.to_dict()
                            p = repository.get_paper(c.paper_id)
                            if p:
                                papers_map[p.id] = p.to_dict()
        elif clean.startswith("q_") and repository.get_question(clean):
            q = repository.get_question(clean)
            if q:
                questions_map[q.id] = q.to_dict()
                q_ref = f"question:{q.id}"
                for edge in repository.neighbors(q_ref):
                    other = edge.dst if edge.src == q_ref else edge.src
                    if other.startswith("claim:"):
                        cid = other.split(":", 1)[1]
                        c = repository.get_claim(cid)
                        if c:
                            claims_map[c.id] = c.to_dict()
                            p = repository.get_paper(c.paper_id)
                            if p:
                                papers_map[p.id] = p.to_dict()
        elif clean.startswith("paper:"):
            p_id = clean.split(":", 1)[1]
            p = repository.get_paper(p_id)
            if p:
                papers_map[p.id] = p.to_dict()
                c_rows = repository.connection.execute("SELECT id FROM claims WHERE paper_id = ?", (p.id,)).fetchall()
                for cr in c_rows:
                    c = repository.get_claim(cr["id"])
                    if c:
                        claims_map[c.id] = c.to_dict()
                        c_ref = f"claim:{c.id}"
                        for edge in repository.neighbors(c_ref):
                            other = edge.dst if edge.src == c_ref else edge.src
                            if other.startswith("question:"):
                                qid = other.split(":", 1)[1]
                                q = repository.get_question(qid)
                                if q:
                                    questions_map[q.id] = q.to_dict()
        elif clean.startswith("p_") and repository.get_paper(clean):
            p = repository.get_paper(clean)
            if p:
                papers_map[p.id] = p.to_dict()
                c_rows = repository.connection.execute("SELECT id FROM claims WHERE paper_id = ?", (p.id,)).fetchall()
                for cr in c_rows:
                    c = repository.get_claim(cr["id"])
                    if c:
                        claims_map[c.id] = c.to_dict()
                        c_ref = f"claim:{c.id}"
                        for edge in repository.neighbors(c_ref):
                            other = edge.dst if edge.src == c_ref else edge.src
                            if other.startswith("question:"):
                                qid = other.split(":", 1)[1]
                                q = repository.get_question(qid)
                                if q:
                                    questions_map[q.id] = q.to_dict()
        elif clean.startswith("claim:"):
            c_id = clean.split(":", 1)[1]
            c = repository.get_claim(c_id)
            if c:
                claims_map[c.id] = c.to_dict()
                p = repository.get_paper(c.paper_id)
                if p:
                    papers_map[p.id] = p.to_dict()
                c_ref = f"claim:{c.id}"
                for edge in repository.neighbors(c_ref):
                    other = edge.dst if edge.src == c_ref else edge.src
                    if other.startswith("question:"):
                        qid = other.split(":", 1)[1]
                        q = repository.get_question(qid)
                        if q:
                            questions_map[q.id] = q.to_dict()
        elif clean.startswith("c_") and repository.get_claim(clean):
            c = repository.get_claim(clean)
            if c:
                claims_map[c.id] = c.to_dict()
                p = repository.get_paper(c.paper_id)
                if p:
                    papers_map[p.id] = p.to_dict()
                c_ref = f"claim:{c.id}"
                for edge in repository.neighbors(c_ref):
                    other = edge.dst if edge.src == c_ref else edge.src
                    if other.startswith("question:"):
                        qid = other.split(":", 1)[1]
                        q = repository.get_question(qid)
                        if q:
                            questions_map[q.id] = q.to_dict()
        else:
            hits = repository.search(clean, limit=5)
            for q_hit in hits.get("questions", []):
                questions_map[q_hit["id"]] = q_hit
            for c_hit in hits.get("claims", []):
                claims_map[c_hit["id"]] = c_hit
                p_ref = c_hit.get("paper_id") or (c_hit.get("paper") or {}).get("id")
                if p_ref:
                    p = repository.get_paper(str(p_ref))
                    if p:
                        papers_map[p.id] = p.to_dict()
            for p_hit in hits.get("papers", []):
                papers_map[p_hit["id"]] = p_hit

    contradictions: List[Dict[str, Any]] = []
    from lattice.analysis import detect_contradictions
    all_contra = detect_contradictions(repository, auto_link=False)
    for pair in all_contra:
        if pair.claim_a_id in claims_map and pair.claim_b_id in claims_map:
            contradictions.append(pair.to_dict())

    contra_claim_ids = {c["claim_a_id"] for c in contradictions} | {c["claim_b_id"] for c in contradictions}
    sorted_claims = sorted(
        claims_map.values(),
        key=lambda c: (1 if c["id"] in contra_claim_ids else 0, float(c.get("confidence", 0.5))),
        reverse=True,
    )

    if norm_format == "markdown":
        content, kept_claims, omitted_claims = _render_markdown_pack(
            target_list, list(questions_map.values()), sorted_claims,
            list(papers_map.values()), contradictions, budget
        )
    else:
        content, kept_claims, omitted_claims = _render_json_pack(
            target_list, list(questions_map.values()), sorted_claims,
            list(papers_map.values()), contradictions, budget
        )

    pack_data = {
        "targets": target_list,
        "counts": {
            "questions": len(questions_map),
            "claims": len(kept_claims),
            "omitted_claims": omitted_claims,
            "papers": len(papers_map),
            "contradictions": len(contradictions),
        },
        "questions": list(questions_map.values()),
        "claims": kept_claims,
        "papers": list(papers_map.values()),
        "contradictions": contradictions,
    }

    return ContextPack(
        targets=target_list,
        budget_tokens=budget,
        estimated_tokens=estimate_tokens(content),
        format=norm_format,
        content=content,
        data=pack_data,
    )
