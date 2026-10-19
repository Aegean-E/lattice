"""Scientific literature synthesis engine: consensus scoring, thematic clustering, and BibTeX."""

from dataclasses import dataclass
from typing import Any, Dict, List, Sequence

from lattice.errors import LatticeError, fail
from lattice.inquiry import STOPWORDS, ask
from lattice.models import estimate_tokens, normalize_text
from lattice.repository import Repository


@dataclass(frozen=True)
class SynthesisReport:
    """Immutable structured synthesis for AI agents and human literature reviews."""

    target: str
    mode: str
    query_text: str
    consensus: Dict[str, Any]
    clusters: List[Dict[str, Any]]
    follow_up_queries: List[str]
    gaps: List[str]
    bibliography: List[Dict[str, Any]]
    bibtex: str
    markdown: str
    tokens: int
    budget: int

    def to_dict(self) -> Dict[str, Any]:
        """JSON-serializable representation."""
        return {
            "target": self.target,
            "mode": self.mode,
            "query_text": self.query_text,
            "consensus": self.consensus,
            "clusters": self.clusters,
            "follow_up_queries": self.follow_up_queries,
            "gaps": self.gaps,
            "bibliography": self.bibliography,
            "bibtex": self.bibtex,
            "markdown": self.markdown,
            "tokens": self.tokens,
            "budget": self.budget,
        }


def compute_consensus(supporting: Sequence[Dict[str, Any]],
                      contradicting: Sequence[Dict[str, Any]],
                      neutral: Sequence[Dict[str, Any]] = ()) -> Dict[str, Any]:
    """Compute a confidence-weighted consensus score in [-1.0, 1.0] and classification label."""
    sup_weight = round(sum(float(item.get("confidence", 0.5)) for item in supporting), 3)
    con_weight = round(sum(float(item.get("confidence", 0.5)) for item in contradicting), 3)
    total_weight = sup_weight + con_weight
    total_claims = len(supporting) + len(contradicting) + len(neutral)
    if total_claims == 0:
        return {
            "score": 0.0,
            "label": "insufficient_evidence",
            "supporting_count": 0,
            "contradicting_count": 0,
            "neutral_count": 0,
            "support_weight": 0.0,
            "contradict_weight": 0.0,
        }
    score = round((sup_weight - con_weight) / total_weight, 3) if total_weight > 0 else 0.0
    if supporting and contradicting and abs(score) < 0.5:
        label = "contested"
    elif score >= 0.5 and (len(supporting) >= 2 or sup_weight >= 0.8):
        label = "strong_support"
    elif score > 0:
        label = "moderate_support"
    elif score < 0:
        label = "contradicted"
    else:
        label = "neutral"
    return {
        "score": score,
        "label": label,
        "supporting_count": len(supporting),
        "contradicting_count": len(contradicting),
        "neutral_count": len(neutral),
        "support_weight": sup_weight,
        "contradict_weight": con_weight,
    }


def cluster_claims(claims: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Group claims into thematic clusters by dominant domain keyword."""
    if not claims:
        return []
    buckets: Dict[str, List[Dict[str, Any]]] = {}
    for claim in claims:
        theme = _dominant_theme(str(claim.get("text") or ""))
        buckets.setdefault(theme, []).append(claim)
    clusters: List[Dict[str, Any]] = []
    for theme, items in sorted(buckets.items(), key=lambda pair: (-len(pair[1]), pair[0])):
        ordered = sorted(items, key=lambda c: (-float(c.get("confidence", 0.0)), str(c.get("id", ""))))
        clusters.append({
            "theme": theme,
            "claim_count": len(ordered),
            "claims": [
                {
                    "id": item.get("id"),
                    "paper_id": item.get("paper_id") or (item.get("paper") or {}).get("id", ""),
                    "stance": item.get("stance", "mentions"),
                    "confidence": float(item.get("confidence", 0.5)),
                    "text": item.get("text", ""),
                    "quote": item.get("quote", ""),
                    "locator": item.get("locator", ""),
                    "citation": _inline_citation(item.get("paper") or {}),
                }
                for item in ordered
            ],
        })
    return clusters


def format_bibtex(papers: Sequence[Dict[str, Any]]) -> str:
    """Format paper dictionaries as deterministic BibTeX entries."""
    entries: List[str] = []
    for paper in papers:
        pid = paper.get("id", "unknown")
        lines = [f"@article{{{pid},"]
        lines.append(f"  title = {{{paper.get('title', '')}}},")
        if paper.get("authors"):
            lines.append(f"  author = {{{paper['authors'].replace(';', ' and')}}},")
        if paper.get("year"):
            lines.append(f"  year = {{{paper['year']}}},")
        if paper.get("venue"):
            lines.append(f"  journal = {{{paper['venue']}}},")
        if paper.get("doi"):
            lines.append(f"  doi = {{{paper['doi']}}},")
        if paper.get("arxiv"):
            lines.append(f"  eprint = {{{paper['arxiv']}}},")
        if paper.get("url"):
            lines.append(f"  url = {{{paper['url']}}},")
        lines.append("}")
        entries.append("\n".join(lines))
    return "\n\n".join(entries)


def synthesize(repository: Repository, target: str, tokens: int = 2500) -> SynthesisReport:
    """Produce a token-bounded, citation-checked scientific synthesis for a question or query."""
    if int(tokens) < 200:
        fail(f"token budget {tokens} is too small",
             "a scientific synthesis requires space for claims, quotes and bibliography",
             "pass --tokens 200 or more")
    evidence = ask(repository, target)
    mode = evidence["mode"]
    if mode == "question":
        query_text = str(evidence["question"]["text"])
        supporting = [item["claim"] for item in evidence["supports"] + evidence["answers"]]
        contradicting = [item["claim"] for item in evidence["contradicts"]]
        neutral = [item["claim"] for item in evidence["other"]]
        all_claims = supporting + contradicting + neutral
        gaps = list(evidence.get("gaps", []))
        suggestions = list(evidence.get("suggestions", []))
    else:
        query_text = str(evidence["query"])
        all_claims = list(evidence.get("claims", []))
        supporting = [c for c in all_claims if c.get("stance") == "supports"]
        contradicting = [c for c in all_claims if c.get("stance") == "contradicts"]
        neutral = [c for c in all_claims if c.get("stance") not in ("supports", "contradicts")]
        gaps = list(evidence.get("gaps", []))
        suggestions = []

    consensus = compute_consensus(supporting, contradicting, neutral)
    clusters = cluster_claims(all_claims)
    bibliography = _collect_bibliography(repository, all_claims, evidence.get("papers", []))
    if len(bibliography) == 1 and all_claims:
        gaps.append("All supporting claims originate from a single source paper; independent replication needed.")
    follow_ups = _build_follow_up_queries(query_text, consensus, suggestions, bibliography)
    bibtex = format_bibtex(bibliography)
    markdown = _render_markdown(
        query_text=query_text,
        mode=mode,
        consensus=consensus,
        clusters=clusters,
        gaps=gaps,
        follow_ups=follow_ups,
        bibliography=bibliography,
        tokens=int(tokens),
    )
    return SynthesisReport(
        target=str(evidence.get("target") or target),
        mode=mode,
        query_text=query_text,
        consensus=consensus,
        clusters=clusters,
        follow_up_queries=follow_ups,
        gaps=gaps,
        bibliography=bibliography,
        bibtex=bibtex,
        markdown=markdown,
        tokens=estimate_tokens(markdown),
        budget=int(tokens),
    )


def _dominant_theme(text: str) -> str:
    """Select the most informative domain keyword from a claim sentence."""
    generic = STOPWORDS | {
        "increased", "improved", "reduced", "compared", "across", "showed", "demonstrated",
        "significant", "significantly", "failed", "did", "not", "remain", "remained",
    }
    candidates = [
        word for word in normalize_text(text).split()
        if len(word) >= 5 and word not in generic and not word.isdigit()
    ]
    return candidates[0] if candidates else "general"


def _inline_citation(paper: Dict[str, Any]) -> str:
    """Format `Author (Year) [p_xxx]` for inline evidence attribution."""
    pid = paper.get("id") or "missing"
    author = (paper.get("authors") or "Unknown").split(";")[0].strip() or "Unknown"
    year = paper.get("year") or "n.d."
    return f"{author} ({year}) [{pid}]"


def _collect_bibliography(repository: Repository, claims: Sequence[Dict[str, Any]],
                          extra_papers: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Collect unique resolved paper records referenced by claims or search results."""
    seen: set[str] = set()
    papers: List[Dict[str, Any]] = []
    for claim in claims:
        pid = str(claim.get("paper_id") or (claim.get("paper") or {}).get("id") or "")
        if not pid or pid in seen:
            continue
        seen.add(pid)
        try:
            papers.append(repository.get_paper(pid).to_dict())
        except LatticeError:
            continue
    for paper in extra_papers:
        pid = str(paper.get("id") or "")
        if not pid or pid in seen:
            continue
        seen.add(pid)
        try:
            papers.append(repository.get_paper(pid).to_dict())
        except LatticeError:
            continue
    return papers


def _build_follow_up_queries(query_text: str, consensus: Dict[str, Any],
                             suggestions: Sequence[Dict[str, Any]],
                             bibliography: Sequence[Dict[str, Any]]) -> List[str]:
    """Generate actionable follow-up scientific queries for AI agents."""
    queries: List[str] = []
    if consensus["contradicting_count"] == 0 and consensus["supporting_count"] > 0:
        queries.append(f"What boundary conditions or negative trials contradict: {query_text}?")
    if len(bibliography) <= 1:
        queries.append(f"Which independent cohorts replicate findings on: {query_text}?")
    for item in suggestions[:2]:
        cid = item.get("id", "")
        queries.append(f"Evaluate unlinked claim [{cid}] for direct linkage to '{query_text}'.")
    if not queries:
        queries.append(f"What methodological moderators explain variance in: {query_text}?")
    return queries


def _render_markdown(query_text: str, mode: str, consensus: Dict[str, Any],
                     clusters: Sequence[Dict[str, Any]], gaps: Sequence[str],
                     follow_ups: Sequence[str], bibliography: Sequence[Dict[str, Any]],
                     tokens: int) -> str:
    """Render a deterministic, token-bounded Markdown literature synthesis report."""
    lines = [
        f"# Literature Synthesis: {query_text}",
        "",
        f"- **Mode**: `{mode}`",
        f"- **Consensus**: `{consensus['label']}` (score `{consensus['score']:+.2f}`; "
        f"{consensus['supporting_count']} supporting, "
        f"{consensus['contradicting_count']} contradicting, "
        f"{consensus['neutral_count']} neutral)",
        f"- **Sources Cited**: {len(bibliography)} paper(s)",
        "",
        "## Thematic Evidence Clusters",
        "",
    ]
    if not clusters:
        lines.append("- No quote-backed claims matched this query yet.")
        lines.append("")
    for cluster in clusters:
        lines.append(f"### Theme: {cluster['theme']} ({cluster['claim_count']} claim(s))")
        for claim in cluster["claims"]:
            candidate = (
                f"- **[{claim['id']} -> {claim['paper_id']}]** "
                f"(`{claim['stance']}`, conf `{claim['confidence']:.2f}`): {claim['text']}\n"
                f"  > \"{claim['quote']}\" — *{claim['citation']}*"
                + (f" ({claim['locator']})" if claim.get("locator") else "")
            )
            if estimate_tokens("\n".join(lines + [candidate])) <= tokens:
                lines.append(candidate)
        lines.append("")
    lines.extend(["## Evidence Gaps & Follow-Up Queries", ""])
    for gap in gaps:
        lines.append(f"- **Gap**: {gap}")
    for follow in follow_ups:
        lines.append(f"- **Next Query**: {follow}")
    lines.extend(["", "## Bibliography", ""])
    if not bibliography:
        lines.append("- None.")
    for paper in bibliography:
        doi = f" doi:{paper['doi']}" if paper.get("doi") else ""
        arxiv = f" arXiv:{paper['arxiv']}" if paper.get("arxiv") else ""
        venue = f" *{paper['venue']}*." if paper.get("venue") else ""
        line = (
            f"- **[{paper['id']}]** {paper.get('authors') or 'Unknown'} "
            f"({paper.get('year') or 'n.d.'}). {paper.get('title', '')}.{venue}{doi}{arxiv}"
        )
        if estimate_tokens("\n".join(lines + [line])) <= tokens:
            lines.append(line)
    text = "\n".join(lines).strip() + "\n"
    if estimate_tokens(text) > tokens:
        text = text[: tokens * 4].rstrip() + "\n"
    return text
