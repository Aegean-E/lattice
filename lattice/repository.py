"""The knowledge graph API: papers, claims, questions, typed edges and evidence queries."""

import json
import sqlite3
from typing import Any, Dict, List, Optional, Tuple

from lattice.database import utc_now
from lattice.errors import fail
from lattice.models import (
    Claim,
    Edge,
    Paper,
    Question,
    bare_id,
    derive_tags,
    entity_type,
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

PAPER_FIELDS = ("kind", "title", "authors", "year", "venue", "doi", "arxiv", "url",
                "abstract", "tags", "study_type")
_SEARCH_STOPWORDS = frozenset(
    "a an and are as at be by for from in into is it of on or that the to was were with".split()
)


def _paper(row: sqlite3.Row) -> Paper:
    """Map a papers row to its value object."""
    return Paper(id=row["id"], title=row["title"], authors=row["authors"], year=row["year"],
                 venue=row["venue"], doi=row["doi"], arxiv=row["arxiv"], url=row["url"],
                 abstract=row["abstract"], tags=row["tags"], study_type=row["study_type"],
                 kind=row["kind"], created_at=row["created_at"])


def _claim(row: sqlite3.Row) -> Claim:
    """Map a claims row to its value object."""
    return Claim(id=row["id"], paper_id=row["paper_id"], text=row["text"], quote=row["quote"],
                 locator=row["locator"], stance=row["stance"], confidence=row["confidence"],
                 created_at=row["created_at"])


def _question(row: sqlite3.Row) -> Question:
    """Map a questions row to its value object."""
    return Question(id=row["id"], text=row["text"], status=row["status"],
                    created_at=row["created_at"])


def _edge(row: sqlite3.Row) -> Edge:
    """Map an edges row to its value object."""
    return Edge(id=row["id"], src=row["src"], dst=row["dst"], kind=row["kind"],
                note=row["note"], created_at=row["created_at"])


class Repository:
    """One connection's view of the graph; every write is committed before it returns."""

    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def add_paper(self, metadata: Dict[str, Any]) -> Tuple[Paper, bool]:
        """Insert a paper, or merge missing metadata into the matching existing record."""
        title = str(metadata.get("title") or "").strip()
        if not title:
            fail("a paper needs a title", "the title is the human-facing identity",
                 "pass title in the BibTeX, RIS, CSV or front matter")
        normalized = {field: str(metadata.get(field) or "").strip() for field in PAPER_FIELDS}
        normalized["title"] = title
        normalized["doi"] = _normalize_doi(normalized["doi"])
        normalized["arxiv"] = _normalize_arxiv(normalized["arxiv"])
        normalized["kind"] = normalized["kind"] or "paper"
        normalized["tags"] = normalize_tags(
            normalized["tags"] or derive_tags(title, normalized["abstract"])
        )
        normalized["study_type"] = (
            normalize_study_type(normalized["study_type"])
            or infer_study_type(title, normalized["abstract"])
        )
        existing = self._find_paper(normalized)
        if existing is not None:
            merged = self._merge_paper(existing, normalized)
            self._log("paper.merge", {"id": existing.id, "changed": merged})
            return self.get_paper(existing.id), False
        identifier = paper_id(title, normalized["doi"], normalized["arxiv"])
        created = utc_now()
        try:
            self.connection.execute(
                "INSERT INTO papers(id, kind, title, authors, year, venue, doi, arxiv, url,"
                " abstract, tags, study_type, created_at)"
                " VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (identifier, normalized["kind"], title, normalized["authors"], normalized["year"],
                 normalized["venue"], normalized["doi"], normalized["arxiv"], normalized["url"],
                 normalized["abstract"], normalized["tags"], normalized["study_type"], created),
            )
            self.connection.commit()
        except sqlite3.IntegrityError as exc:
            self.connection.rollback()
            fail(f"could not store paper '{title}': {exc}",
                 "another record already owns that DOI or arXiv ID",
                 "merge the duplicates or remove the conflicting identifier")
        self._log("paper.add", {"id": identifier})
        return self.get_paper(identifier), True

    def add_claim(self, paper: str, text: str, quote: str, locator: str = "",
                  stance: str = "mentions", confidence: float = 0.5) -> Claim:
        """Record one claim with the exact source quote that grounds it."""
        paper_ref = self._resolve(paper)
        if entity_type(paper_ref) != "paper":
            fail(f"'{paper}' is not a paper reference", "claims must point at a source paper",
                 "pass --paper paper:p_xxx or the bare p_xxx id")
        if self._row("SELECT 1 FROM papers WHERE id = ?", bare_id(paper_ref)) is None:
            fail(f"paper '{paper}' does not exist", "a claim must cite an ingested source",
                 "ingest the paper first, then pass its p_ id")
        claim_text = " ".join(str(text or "").split())
        source_quote = " ".join(str(quote or "").split())
        if not claim_text:
            fail("a claim needs text", "an empty claim carries no assertion",
                 "pass the claim as --text")
        if not source_quote:
            fail("a claim needs a quote", "provenance is the point of the graph",
                 "pass the exact source sentence as --quote")
        identifier = next_id("c", self._ids("claims"))
        created = utc_now()
        self.connection.execute(
            "INSERT INTO claims(id, paper_id, text, quote, locator, stance, confidence, created_at)"
            " VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
            (identifier, bare_id(paper_ref), claim_text, source_quote, str(locator or "").strip(),
             validate_stance(stance), parse_confidence(confidence), created),
        )
        self.connection.commit()
        self._log("claim.add", {"id": identifier, "paper": paper_ref})
        return self.get_claim(identifier)

    def add_question(self, text: str) -> Question:
        """Record a research question that evidence can later be linked to."""
        value = " ".join(str(text or "").split())
        if not value:
            fail("a question needs text", "an empty question cannot collect evidence",
                 "pass the question as a quoted argument")
        identifier = next_id("q", self._ids("questions"))
        self.connection.execute(
            "INSERT INTO questions(id, text, status, created_at) VALUES(?, ?, 'open', ?)",
            (identifier, value, utc_now()),
        )
        self.connection.commit()
        self._log("question.add", {"id": identifier})
        return self.get_question(identifier)

    def add_edge(self, src: str, dst: str, kind: str, note: str = "") -> Edge:
        """Add a typed relation after checking both endpoints exist."""
        source = self._resolve(src)
        target = self._resolve(dst)
        if source == target:
            fail("an edge needs two different endpoints", "a self-relation adds no information",
                 "link the entity to a different paper, claim or question")
        edge_kind = validate_edge_kind(kind)
        try:
            cursor = self.connection.execute(
                "INSERT INTO edges(src, dst, kind, note, created_at) VALUES(?, ?, ?, ?, ?)",
                (source, target, edge_kind, str(note or "").strip(), utc_now()),
            )
            self.connection.commit()
        except sqlite3.IntegrityError:
            self.connection.rollback()
            fail(f"edge {source} -{edge_kind}-> {target} already exists",
                 "the graph stores each typed relation once",
                 "inspect it with `show`, or use a different kind")
        self._log("edge.add", {"src": source, "dst": target, "kind": edge_kind})
        return Edge(id=int(cursor.lastrowid), src=source, dst=target, kind=edge_kind,
                    note=str(note or "").strip())

    def get_paper(self, identifier: str) -> Paper:
        """A paper by bare id or reference."""
        row = self._row("SELECT * FROM papers WHERE id = ?", bare_id(self._resolve(identifier)))
        if row is None:
            fail(f"paper '{identifier}' does not exist", "the graph has no such record",
                 "use `search` to find an ingested paper")
        return _paper(row)

    def get_claim(self, identifier: str) -> Claim:
        """A claim by bare id or reference."""
        row = self._row("SELECT * FROM claims WHERE id = ?", bare_id(self._resolve(identifier)))
        if row is None:
            fail(f"claim '{identifier}' does not exist", "the graph has no such record",
                 "use `search` to find a recorded claim")
        return _claim(row)

    def get_question(self, identifier: str) -> Question:
        """A question by bare id or reference."""
        row = self._row("SELECT * FROM questions WHERE id = ?", bare_id(self._resolve(identifier)))
        if row is None:
            fail(f"question '{identifier}' does not exist", "the graph has no such record",
                 "use `search` or add it with the question command")
        return _question(row)

    def get(self, ref: str) -> Dict[str, Any]:
        """One entity and every edge attached to it."""
        resolved = self._resolve(ref)
        return {"ref": resolved, "entity": self._summary(resolved),
                "edges": [edge.to_dict() for edge in self.neighbors(resolved)]}

    def search(self, query: str, limit: int = 20, stance: Optional[str] = None,
               min_confidence: Optional[float] = None,
               year: Optional[str] = None) -> Dict[str, Any]:
        """Search papers, claims and questions by phrase or multi-term lexical overlap."""
        value = str(query or "").strip()
        if not value:
            fail("search needs a query", "an empty query would match everything",
                 "pass a word or phrase")
        if limit < 1:
            fail(f"limit {limit} is not positive", "a result set needs at least one row",
                 "pass --limit 1 or more")
        stance_filter = validate_stance(stance) if stance else None
        conf_filter = parse_confidence(min_confidence) if min_confidence is not None else None
        year_filter = str(year).strip() if year else None
        terms = [term for term in normalize_text(value).split() if len(term) >= 2]
        papers = self._search_papers(value, terms, year_filter, limit)
        claims = self._search_claims(value, terms, stance_filter, conf_filter, year_filter, limit)
        questions = self._search_questions(value, terms, limit)
        return {
            "query": value,
            "papers": [item.to_dict() for item in papers],
            "claims": [self._claim_dict(item) for item in claims],
            "questions": [item.to_dict() for item in questions],
        }

    def search_literature(self, query: str = "", tags: str = "", study_type: str = "",
                          year: Optional[str] = None, limit: int = 20) -> Dict[str, Any]:
        """Search papers by tags, words, sentences, study type or year."""
        value = " ".join(str(query or "").split())
        tag_filter = [tag for tag in normalize_tags(tags).split(", ") if tag]
        type_filter = normalize_study_type(study_type).lower()
        year_filter = str(year).strip() if year else None
        if int(limit) < 1:
            fail(f"limit {limit} is not positive", "a literature result set needs at least one row",
                 "pass limit=1 or more")
        terms = [term for term in normalize_text(value).split()
                 if len(term) >= 2 and term not in _SEARCH_STOPWORDS]
        rows = self.connection.execute(
            "SELECT * FROM papers ORDER BY year DESC, title"
        ).fetchall()
        scored: List[Tuple[int, int, Paper]] = []
        needle = value.lower()
        normalized_needle = normalize_text(value)
        for idx, row in enumerate(rows):
            paper = _paper(row)
            if year_filter and paper.year != year_filter:
                continue
            paper_tags = {tag for tag in normalize_tags(paper.tags).split(", ") if tag}
            if tag_filter and not set(tag_filter).issubset(paper_tags):
                continue
            if type_filter and type_filter not in paper.study_type.lower():
                continue
            if value:
                blob = (
                    f"{paper.title} {paper.authors} {paper.year} {paper.venue} {paper.doi} "
                    f"{paper.arxiv} {paper.url} {paper.abstract} {paper.tags} {paper.study_type}"
                ).lower()
                score = _lexical_score(needle, terms, blob, paper.title.lower())
                if (normalized_needle and needle not in blob
                        and normalized_needle in normalize_text(blob)):
                    score += 100
            else:
                score = 1
            if score > 0:
                scored.append((score, -idx, paper))
        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        papers = [item[2] for item in scored[:int(limit)]]
        return {
            "query": value,
            "tags": ", ".join(tag_filter),
            "study_type": normalize_study_type(study_type),
            "total": len(scored),
            "papers": [paper.to_dict() for paper in papers],
        }

    def export_bibtex(self, query: str = "", tags: str = "", study_type: str = "",
                      year: Optional[str] = None) -> str:
        """Export papers matching filters as deterministic BibTeX entries."""
        from .synthesis import format_bibtex
        papers = self.search_literature(
            query=query, tags=tags, study_type=study_type, year=year, limit=100000
        )["papers"]
        return format_bibtex(papers)

    def set_question_status(self, question: str, status: str) -> Question:
        """Update a question's lifecycle status ('open', 'answered' or 'abandoned')."""
        entity = self.get_question(question)
        cleaned = str(status or "").strip().lower()
        if cleaned not in ("open", "answered", "abandoned"):
            fail(f"unknown question status '{status}'",
                 "questions are open, answered or abandoned",
                 "pass --status open, answered or abandoned")
        self.connection.execute(
            "UPDATE questions SET status = ? WHERE id = ?",
            (cleaned, entity.id),
        )
        self.connection.commit()
        self._log("question.status", {"id": entity.id, "status": cleaned})
        return self.get_question(entity.id)

    def subgraph(self, ref: str, depth: int = 1) -> Dict[str, Any]:
        """Return the multi-hop neighborhood of nodes and edges around `ref`."""
        if int(depth) < 1 or int(depth) > 3:
            fail(f"subgraph depth {depth} is out of range",
                 "multi-hop traversal supports depths 1 to 3",
                 "pass --depth 1, 2 or 3")
        root = self._resolve(ref)
        self._summary(root)
        visited_nodes = {root}
        frontier = {root}
        seen_edges: Dict[int, Dict[str, Any]] = {}
        for _ in range(int(depth)):
            next_frontier = set()
            for current in sorted(frontier):
                for edge in self.neighbors(current):
                    seen_edges[edge.id] = edge.to_dict()
                    other = edge.dst if edge.src == current else edge.src
                    if other not in visited_nodes:
                        visited_nodes.add(other)
                        next_frontier.add(other)
            frontier = next_frontier
            if not frontier:
                break
        nodes = []
        for node_ref in sorted(visited_nodes):
            node = {"ref": node_ref, **self._safe_summary(node_ref)}
            node["study_type"] = self._study_type(node_ref)
            nodes.append(node)
        edges = [seen_edges[edge_id] for edge_id in sorted(seen_edges)]
        return {"root": root, "depth": int(depth), "nodes": nodes, "edges": edges}

    def neighbors(self, ref: str, kind: Optional[str] = None) -> List[Edge]:
        """Every edge touching `ref`, optionally narrowed to one kind."""
        resolved = self._resolve(ref)
        if kind:
            rows = self.connection.execute(
                "SELECT * FROM edges WHERE (src = ? OR dst = ?) AND kind = ? ORDER BY id",
                (resolved, resolved, validate_edge_kind(kind))).fetchall()
        else:
            rows = self.connection.execute(
                "SELECT * FROM edges WHERE src = ? OR dst = ? ORDER BY id",
                (resolved, resolved)).fetchall()
        edges = []
        for row in rows:
            edge = _edge(row)
            other = edge.dst if edge.src == resolved else edge.src
            edges.append(Edge(id=edge.id, src=edge.src, dst=edge.dst, kind=edge.kind,
                              note=edge.note, created_at=edge.created_at,
                              details={"other": self._safe_summary(other)}))
        return edges

    def evidence(self, question: str) -> Dict[str, Any]:
        """Claims linked to a question, grouped by the stance of the link."""
        resolved = self._resolve(question)
        if entity_type(resolved) != "question":
            fail(f"'{question}' is not a question reference", "evidence is grouped per question",
                 "pass a question:q_xxx reference")
        entity = self.get_question(resolved)
        groups: Dict[str, List[Dict[str, Any]]] = {"supports": [], "contradicts": [],
                                                   "answers": [], "other": []}
        rows = self.connection.execute(
            "SELECT * FROM edges WHERE src = ? OR dst = ? ORDER BY id",
            (resolved, resolved)).fetchall()
        for row in rows:
            edge = _edge(row)
            other = edge.dst if edge.src == resolved else edge.src
            if entity_type(other) != "claim":
                continue
            item = {"link": edge.kind, "note": edge.note, "claim": self._safe_summary(other)}
            bucket = edge.kind if edge.kind in groups else "other"
            groups[bucket].append(item)
        total = sum(len(items) for items in groups.values())
        gaps = []
        if total == 0:
            gaps.append("No claims are linked to this question yet.")
        if not groups["contradicts"]:
            gaps.append("No contradicting evidence has been linked.")
        return {"question": entity.to_dict(), "ref": resolved,
                "supports": groups["supports"], "contradicts": groups["contradicts"],
                "answers": groups["answers"], "other": groups["other"],
                "evidence_count": total, "gaps": gaps}

    def stats(self) -> Dict[str, Any]:
        """Entity and edge counts for a quick orientation report."""
        counts = {}
        for table in ("papers", "claims", "questions", "edges"):
            row = self.connection.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()
            counts[table] = int(row["n"])
        kinds = {row["kind"]: int(row["n"]) for row in self.connection.execute(
            "SELECT kind, COUNT(*) AS n FROM edges GROUP BY kind ORDER BY kind").fetchall()}
        counts["edge_kinds"] = kinds
        return counts

    def _resolve(self, value: str) -> str:
        """Accept a full reference or a bare id and return the validated reference."""
        text = str(value or "").strip()
        if ":" in text:
            resolved = validate_ref(text)
        elif text[:2] in ("p_", "c_", "q_"):
            resolved = f"{ {'p': 'paper', 'c': 'claim', 'q': 'question'}[text[0]] }:{text}"
        else:
            fail(f"'{value}' is not an entity reference",
                 "ids look like p_xxx, c_xxx or q_xxx",
                 "use `search` to find an id, then pass it with its prefix")
        return resolved

    def _row(self, query: str, *args: Any) -> Optional[sqlite3.Row]:
        """One row or None."""
        return self.connection.execute(query, args).fetchone()

    def _ids(self, table: str) -> List[str]:
        """Every id in a table, used to allocate the next sequential claim or question id."""
        return [str(row[0]) for row in self.connection.execute(f"SELECT id FROM {table}").fetchall()]

    def _find_paper(self, metadata: Dict[str, str]) -> Optional[Paper]:
        """Find a duplicate by DOI, arXiv ID, or normalized title and year."""
        if metadata["doi"]:
            row = self._row("SELECT * FROM papers WHERE lower(doi) = ?", metadata["doi"].lower())
            if row:
                return _paper(row)
        if metadata["arxiv"]:
            row = self._row("SELECT * FROM papers WHERE lower(arxiv) = ?", metadata["arxiv"].lower())
            if row:
                return _paper(row)
        wanted = normalize_text(metadata["title"])
        for row in self.connection.execute("SELECT * FROM papers").fetchall():
            if normalize_text(row["title"]) != wanted:
                continue
            if not metadata["year"] or not row["year"] or row["year"] == metadata["year"]:
                return _paper(row)
        return None

    def _merge_paper(self, existing: Paper, metadata: Dict[str, str]) -> List[str]:
        """Fill fields the existing record lacks; return the names that changed."""
        changed = []
        updates = {}
        for field in PAPER_FIELDS:
            if metadata[field] and not getattr(existing, field):
                updates[field] = metadata[field]
                changed.append(field)
        if updates:
            assignments = ", ".join(f"{field} = ?" for field in updates)
            self.connection.execute(f"UPDATE papers SET {assignments} WHERE id = ?",
                                    (*updates.values(), existing.id))
            self.connection.commit()
        return changed

    def _claim_dict(self, claim: Claim) -> Dict[str, Any]:
        """A claim plus a compact citation summary of its paper."""
        value = claim.to_dict()
        value["paper"] = self._safe_summary(f"paper:{claim.paper_id}")
        return value

    def _safe_summary(self, ref: str) -> Dict[str, Any]:
        """Summary of an entity, or a missing marker instead of raising."""
        try:
            return self._summary(ref)
        except Exception:
            return {"ref": ref, "missing": True}

    def _summary(self, ref: str) -> Dict[str, Any]:
        """A compact JSON representation of any entity, with paper context for claims."""
        kind = entity_type(ref)
        identifier = bare_id(ref)
        if kind == "paper":
            return {"type": "paper", **self.get_paper(identifier).to_dict()}
        if kind == "question":
            return {"type": "question", **self.get_question(identifier).to_dict()}
        claim = self.get_claim(identifier)
        value = {"type": "claim", **claim.to_dict()}
        paper_row = self._row("SELECT * FROM papers WHERE id = ?", claim.paper_id)
        if paper_row:
            paper = _paper(paper_row)
            value["paper"] = {
                "id": paper.id, "title": paper.title, "authors": paper.authors,
                "year": paper.year, "doi": paper.doi, "venue": paper.venue,
                "tags": paper.tags, "study_type": paper.study_type,
            }
            value["study_type"] = paper.study_type
        return value

    def _study_type(self, ref: str) -> str:
        """The study type behind a paper or claim, or every type linked to a question."""
        kind = entity_type(ref)
        if kind == "paper":
            return self.get_paper(ref).study_type
        if kind == "claim":
            return self.get_paper(self.get_claim(ref).paper_id).study_type
        rows = self.connection.execute(
            "SELECT DISTINCT p.study_type FROM edges e"
            " JOIN claims c ON c.id = CASE WHEN e.src LIKE 'claim:%'"
            "   THEN substr(e.src, 7) ELSE substr(e.dst, 7) END"
            " JOIN papers p ON p.id = c.paper_id"
            " WHERE (e.src = ? OR e.dst = ?)"
            "   AND (e.src LIKE 'claim:%' OR e.dst LIKE 'claim:%')"
            "   AND p.study_type != ''"
            " ORDER BY p.study_type",
            (ref, ref),
        ).fetchall()
        return ", ".join(str(row["study_type"]) for row in rows)

    def _log(self, action: str, payload: Dict[str, Any]) -> None:
        """Append an immutable audit event."""
        self.connection.execute(
            "INSERT INTO events(at, action, payload) VALUES(?, ?, ?)",
            (utc_now(), action, json.dumps(payload, sort_keys=True)),
        )
        self.connection.commit()

    def _search_papers(self, raw_query: str, terms: List[str],
                       year: Optional[str], limit: int) -> List[Paper]:
        """Rank papers by exact substring match first, then multi-term lexical overlap."""
        rows = self.connection.execute(
            "SELECT * FROM papers ORDER BY year DESC, title"
        ).fetchall()
        scored: List[Tuple[int, int, Paper]] = []
        needle = raw_query.lower()
        for idx, row in enumerate(rows):
            paper = _paper(row)
            if year and paper.year != year:
                continue
            blob = f"{paper.title} {paper.authors} {paper.abstract} {paper.doi} {paper.arxiv}".lower()
            score = _lexical_score(needle, terms, blob, paper.title.lower())
            if score > 0:
                scored.append((score, -idx, paper))
        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [item[2] for item in scored[:limit]]

    def _search_claims(self, raw_query: str, terms: List[str],
                       stance: Optional[str], min_confidence: Optional[float],
                       year: Optional[str], limit: int) -> List[Claim]:
        """Rank claims by phrase or multi-term overlap and apply optional filters."""
        rows = self.connection.execute("SELECT * FROM claims ORDER BY id").fetchall()
        paper_years = {
            str(row["id"]): str(row["year"])
            for row in self.connection.execute("SELECT id, year FROM papers").fetchall()
        }
        scored: List[Tuple[int, int, Claim]] = []
        needle = raw_query.lower()
        for idx, row in enumerate(rows):
            claim = _claim(row)
            if stance and claim.stance != stance:
                continue
            if min_confidence is not None and claim.confidence < min_confidence:
                continue
            if year and paper_years.get(claim.paper_id) != year:
                continue
            blob = f"{claim.text} {claim.quote}".lower()
            score = _lexical_score(needle, terms, blob, claim.text.lower())
            if score > 0:
                scored.append((score, -idx, claim))
        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [item[2] for item in scored[:limit]]

    def _search_questions(self, raw_query: str, terms: List[str], limit: int) -> List[Question]:
        """Rank questions by phrase or multi-term overlap."""
        rows = self.connection.execute("SELECT * FROM questions ORDER BY id").fetchall()
        scored: List[Tuple[int, int, Question]] = []
        needle = raw_query.lower()
        for idx, row in enumerate(rows):
            question = _question(row)
            blob = question.text.lower()
            score = _lexical_score(needle, terms, blob, blob)
            if score > 0:
                scored.append((score, -idx, question))
        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [item[2] for item in scored[:limit]]


def _lexical_score(needle: str, terms: List[str], blob: str, primary: str) -> int:
    """Compute a deterministic relevance score combining exact substring and multi-term hits."""
    score = 0
    if needle in blob:
        score += 100
    if needle in primary:
        score += 50
    if len(terms) > 1:
        matched_terms = [term for term in terms if term in blob]
        if len(matched_terms) >= 2 or (len(terms) == 1 and matched_terms):
            score += sum(3 if term in primary else 1 for term in matched_terms)
    return score


def _normalize_doi(value: str) -> str:
    """Strip resolver prefixes and lowercase a DOI."""
    text = value.strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if text.lower().startswith(prefix):
            text = text[len(prefix):]
    return text.strip().lower()


def _normalize_arxiv(value: str) -> str:
    """Strip the arXiv prefix from an identifier."""
    text = value.strip()
    if text.lower().startswith("arxiv:"):
        text = text.split(":", 1)[1]
    return text.strip()
