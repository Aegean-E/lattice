"""Evidence-first question answering: `ask`, token-budgeted `brief` and `review` outlines."""

from typing import Any, Dict, Iterable, List, Optional, Tuple

from lattice.errors import LatticeError, fail
from lattice.models import estimate_tokens
from lattice.repository import Repository

STOPWORDS = frozenset({
    "about", "after", "also", "among", "because", "between", "could", "does", "from",
    "have", "into", "more", "most", "other", "should", "than", "that", "their", "there",
    "these", "they", "this", "those", "through", "under", "what", "when", "where", "which",
    "while", "with", "would",
})
GROUPS = (("supports", "SUPPORTS"), ("contradicts", "CONTRADICTS"),
          ("answers", "ANSWERS"), ("other", "RELATED"))


def ask(repository: Repository, target: str, limit: int = 20) -> Dict[str, Any]:
    """Return evidence for a question, or matching claims when the target is a search phrase."""
    question = _match_question(repository, target)
    if question is not None:
        result = repository.evidence(question.id)
        linked = {f"claim:{item['claim']['id']}"
                  for group in ("supports", "contradicts", "answers", "other")
                  for item in result[group]}
        result["mode"] = "question"
        result["suggestions"] = _suggestions(repository, question.text, linked, limit)
        result["target"] = question.id
        return result
    found = repository.search(target, limit)
    gaps = []
    if not found["papers"] and not found["claims"] and not found["questions"]:
        gaps.append("Nothing in the graph matches this phrase.")
    return {"mode": "search", "target": target, "query": target, **found, "gaps": gaps}


def brief(repository: Repository, target: str, tokens: int = 2000) -> Dict[str, Any]:
    """Pack the strongest evidence for an agent under a deterministic token budget."""
    if tokens < 200:
        fail(f"token budget {tokens} is too small", "a useful brief needs room for evidence",
             "pass --tokens 200 or more")
    evidence = ask(repository, target)
    lines: List[str] = []
    included: List[Dict[str, Any]] = []
    omitted = 0
    if evidence["mode"] == "question":
        lines.extend(_question_header(evidence))
        for group, label in GROUPS:
            lines.append(f"{label}:")
            items = evidence[group]
            if not items:
                lines.append("- none")
                continue
            for item in items:
                line = _claim_line(item)
                if _fits(lines, line, tokens):
                    lines.append(line)
                    included.append(item["claim"])
                else:
                    omitted += 1
        gaps = [f"- {gap}" for gap in evidence["gaps"]]
        suggestions = _suggestion_lines(evidence.get("suggestions", []))
    else:
        lines.extend([f"TARGET: {target}", "MODE: search", "MATCHING CLAIMS:"])
        claims = evidence.get("claims", [])
        if not claims:
            lines.append("- none")
        for claim in claims:
            line = _search_line(claim)
            if _fits(lines, line, tokens):
                lines.append(line)
                included.append(claim)
            else:
                omitted += 1
        gaps = [f"- {gap}" for gap in evidence.get("gaps", [])]
        suggestions = []
    if omitted:
        lines.append(f"OMITTED: {omitted} lower-ranked evidence item(s) did not fit.")
    if gaps:
        lines.append("GAPS:")
        lines.extend(_fit(lines, gaps, tokens))
    if suggestions:
        lines.append("SUGGESTED UNLINKED CLAIMS:")
        lines.extend(_fit(lines, suggestions, tokens))
    refs: List[str] = []
    for claim in included:
        paper = claim.get("paper") or {}
        if paper.get("id") and f"paper:{paper['id']}" not in refs:
            refs.append(f"paper:{paper['id']}")
    citations = _citation_lines(repository, refs)
    if citations:
        lines.append("CITATIONS:")
        lines.extend(_fit(lines, citations, tokens))
    text = "\n".join(lines)
    if estimate_tokens(text) > tokens:
        text = text[: tokens * 4].rstrip()
    return {"target": target, "text": text, "tokens": estimate_tokens(text),
            "budget": tokens, "omitted": omitted,
            "refs": [f"claim:{claim['id']}" for claim in included]}


def review(repository: Repository, target: str) -> Dict[str, Any]:
    """A Markdown literature-review outline with every citation resolved in the graph."""
    evidence = ask(repository, target)
    if evidence["mode"] == "question":
        markdown, refs = _question_review(evidence)
    else:
        markdown, refs = _search_review(evidence)
    return {"target": target, "markdown": markdown, "refs": refs}


def _match_question(repository: Repository, target: str) -> Optional[Any]:
    """A question named by reference, exact text or unique substring."""
    text = str(target or "").strip()
    if not text:
        fail("a target is required", "ask, brief and review need a question or phrase",
             "pass a question reference, a question text or a search phrase")
    if text.startswith("q_") or text.startswith("question:"):
        try:
            return repository.get_question(text)
        except LatticeError:
            return None
    exact = repository.connection.execute(
        "SELECT * FROM questions WHERE lower(text) = lower(?) ORDER BY id LIMIT 1", (text,)).fetchone()
    if exact:
        return repository.get_question(exact["id"])
    partial = repository.connection.execute(
        "SELECT * FROM questions WHERE text LIKE ? ORDER BY id LIMIT 1", (f"%{text}%",)).fetchone()
    return repository.get_question(partial["id"]) if partial else None


def _suggestions(repository: Repository, question: str, linked: Iterable[str],
                 limit: int) -> List[Dict[str, Any]]:
    """Unlinked claims whose text matches a keyword from the question."""
    seen = set(linked)
    suggestions: List[Dict[str, Any]] = []
    for word in _keywords(question):
        found = repository.search(word, limit=limit)
        for claim in found["claims"]:
            ref = f"claim:{claim['id']}"
            if ref in seen:
                continue
            seen.add(ref)
            suggestions.append(claim)
            if len(suggestions) >= 5:
                return suggestions
    return suggestions


def _keywords(text: str) -> List[str]:
    """Distinct lowercase words of at least four letters, without common question words."""
    words: List[str] = []
    for raw in text.lower().replace("?", " ").replace(",", " ").split():
        word = "".join(char for char in raw if char.isalnum())
        if len(word) >= 4 and word not in STOPWORDS and word not in words:
            words.append(word)
    return words[:8]


def _question_header(evidence: Dict[str, Any]) -> List[str]:
    """The fixed header of a question brief."""
    question = evidence["question"]
    return [
        f"TARGET: {question['id']}",
        "MODE: question",
        f"QUESTION: {question['text']}",
        f"STATUS: {question['status']}",
        f"EVIDENCE: {evidence['evidence_count']} linked claim(s)",
    ]


def _claim_line(item: Dict[str, Any]) -> str:
    """One evidence line: claim, confidence, quote and source."""
    claim = item["claim"]
    paper = claim.get("paper", {})
    return (f"- [{claim['id']}] ({claim.get('confidence', 0.0):.1f}, {item['link']}) "
            f"{claim.get('text', '')} | quote: \"{claim.get('quote', '')}\" | "
            f"source: {_citation_short(paper)}")


def _search_line(claim: Dict[str, Any]) -> str:
    """One search hit line."""
    paper = claim.get("paper", {})
    return f"- [{claim['id']}] {claim.get('text', '')} | source: {_citation_short(paper)}"


def _suggestion_lines(suggestions: List[Dict[str, Any]]) -> List[str]:
    """Unlinked claim candidates, one line each."""
    return [f"- [{claim['id']}] {claim.get('text', '')}" for claim in suggestions]


def _fits(lines: List[str], candidate: str, tokens: int) -> bool:
    """Whether adding one line keeps the estimate under the budget."""
    return estimate_tokens("\n".join(lines) + "\n" + candidate) <= tokens


def _fit(lines: List[str], candidates: List[str], tokens: int) -> List[str]:
    """Append candidate lines while the running estimate stays under the budget."""
    accepted = []
    for candidate in candidates:
        if not _fits(lines + accepted, candidate, tokens):
            break
        accepted.append(candidate)
    return accepted


def _citation_lines(repository: Repository, refs: List[str]) -> List[str]:
    """Resolved citation lines for paper references, in first-seen order."""
    lines = []
    for ref in refs:
        try:
            paper = repository.get_paper(ref)
        except LatticeError:
            lines.append(f"- [{ref.split(':', 1)[1]}] missing record")
            continue
        venue = f" {paper.venue}." if paper.venue else ""
        identifier = f" doi:{paper.doi}" if paper.doi else (
            f" arXiv:{paper.arxiv}" if paper.arxiv else "")
        lines.append(f"- [{paper.id}] {_citation_short(paper.to_dict())}.{venue}{identifier}")
    return lines


def _citation_short(paper: Dict[str, Any]) -> str:
    """A compact inline source label."""
    authors = (paper.get("authors") or "").split(";")[0].strip() or "Unknown authors"
    year = paper.get("year") or "n.d."
    title = paper.get("title") or "untitled"
    return f"{authors} ({year}), {title}"


def _question_review(evidence: Dict[str, Any]) -> Tuple[str, List[str]]:
    """Render a question's evidence as a review outline."""
    question = evidence["question"]
    lines = [
        f"# Evidence review: {question['text']}",
        "",
        f"**Question:** {question['id']} ({question['status']})  ",
        f"**Evidence:** {len(evidence['supports'])} supporting, "
        f"{len(evidence['contradicts'])} contradicting, {len(evidence['answers'])} answering",
        "",
    ]
    lines += _review_section("Supporting evidence", evidence["supports"])
    lines += _review_section("Contradicting evidence", evidence["contradicts"])
    lines += _review_section("Direct answers", evidence["answers"])
    lines += ["## Gaps", ""]
    lines += [f"- {gap}" for gap in evidence["gaps"]] or ["- None recorded."]
    refs = _paper_refs(evidence)
    lines += ["", "## References", ""]
    for ref in refs:
        identifier = ref.split(":", 1)[1]
        lines.append(f"- **[{identifier}]** see `show {ref}` for the full record")
    return "\n".join(lines).strip() + "\n", refs


def _review_section(title: str, items: List[Dict[str, Any]]) -> List[str]:
    """One evidence section of a review outline."""
    lines = [f"## {title}", ""]
    if not items:
        return lines + ["- None linked.", ""]
    for item in items:
        claim = item["claim"]
        paper = claim.get("paper", {})
        lines.append(f"- **{claim['id']}** (confidence {claim.get('confidence', 0.0):.1f}) - "
                     f"{claim.get('text', '')}")
        if claim.get("quote"):
            lines.append(f"  > {claim['quote']}")
        if claim.get("locator"):
            lines.append(f"  Locator: {claim['locator']}")
        lines.append(f"  Source: {_citation_short(paper)}")
    lines.append("")
    return lines


def _paper_refs(evidence: Dict[str, Any]) -> List[str]:
    """Distinct paper references touched by evidence or search results."""
    refs: List[str] = []
    if evidence["mode"] == "question":
        claims = [item["claim"] for group in ("supports", "contradicts", "answers", "other")
                  for item in evidence[group]]
    else:
        claims = evidence.get("claims", [])
    for claim in claims:
        paper = claim.get("paper") or {}
        identifier = paper.get("id")
        if identifier and f"paper:{identifier}" not in refs:
            refs.append(f"paper:{identifier}")
    return refs


def _search_review(evidence: Dict[str, Any]) -> Tuple[str, List[str]]:
    """Render matching papers and claims when the target is not a tracked question."""
    lines = [f"# Search review: {evidence['target']}", "", "## Matching papers", ""]
    papers = evidence.get("papers", [])
    lines += [f"- **[{paper['id']}]** {paper['title']} - "
              f"{paper.get('authors') or 'Unknown authors'} ({paper.get('year') or 'n.d.'})"
              for paper in papers] or ["- None."]
    lines += ["", "## Matching claims", ""]
    claims = evidence.get("claims", [])
    lines += [f"- **[{claim['id']}]** {claim['text']} - {_citation_short(claim.get('paper', {}))}"
              for claim in claims] or ["- None."]
    refs = [f"paper:{paper['id']}" for paper in papers]
    for claim in claims:
        paper = claim.get("paper") or {}
        if paper.get("id") and f"paper:{paper['id']}" not in refs:
            refs.append(f"paper:{paper['id']}")
    return "\n".join(lines).strip() + "\n", refs

