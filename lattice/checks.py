"""Integrity gate: every citation, endpoint, quote and support cycle is decidable locally."""

from dataclasses import dataclass, field
from typing import Dict, List, Set, Tuple

from lattice.database import SCHEMA_VERSION, schema_version
from lattice.models import entity_type, normalize_text
from lattice.repository import Repository


@dataclass(frozen=True)
class CheckIssue:
    """One finding, tagged error or warning and named by a stable code."""

    level: str
    code: str
    message: str

    def to_dict(self) -> Dict[str, str]:
        """JSON-ready representation."""
        return {"level": self.level, "code": self.code, "message": self.message}


@dataclass
class CheckReport:
    """The gate's complete result; only errors block delivery."""

    issues: List[CheckIssue] = field(default_factory=list)

    @property
    def errors(self) -> List[CheckIssue]:
        """Blocking findings."""
        return [issue for issue in self.issues if issue.level == "error"]

    @property
    def warnings(self) -> List[CheckIssue]:
        """Non-blocking findings."""
        return [issue for issue in self.issues if issue.level == "warning"]

    @property
    def passed(self) -> bool:
        """True when no blocking finding exists."""
        return not self.errors

    def to_dict(self) -> Dict[str, object]:
        """JSON-ready representation used by the CLI and MCP clients."""
        return {"passed": self.passed, "errors": [issue.to_dict() for issue in self.errors],
                "warnings": [issue.to_dict() for issue in self.warnings]}


def run_checks(repository: Repository) -> CheckReport:
    """Run every integrity check and return one report."""
    report = CheckReport()
    connection = repository.connection
    _check_schema(connection, report)
    _check_claims(connection, report)
    _check_edges(connection, report)
    _check_duplicates(connection, report)
    _check_support_cycles(connection, report)
    _check_orphans(connection, report)
    return report


def _check_schema(connection, report: CheckReport) -> None:
    """The database must declare this build's schema version."""
    actual = schema_version(connection)
    if actual != SCHEMA_VERSION:
        report.issues.append(CheckIssue(
            "error", "schema.version",
            f"schema version {actual} does not match the supported {SCHEMA_VERSION}"))


def _check_claims(connection, report: CheckReport) -> None:
    """Every claim needs assertion text, a quote and an existing paper."""
    rows = connection.execute(
        "SELECT c.id, c.text, c.quote, c.paper_id, p.id AS found FROM claims c"
        " LEFT JOIN papers p ON p.id = c.paper_id").fetchall()
    for row in rows:
        if not str(row["text"]).strip() or not str(row["quote"]).strip():
            report.issues.append(CheckIssue(
                "error", "claim.provenance",
                f"{row['id']} has empty text or quote; every claim needs both"))
        if row["found"] is None:
            report.issues.append(CheckIssue(
                "error", "claim.source", f"{row['id']} points at missing paper {row['paper_id']}"))


def _check_edges(connection, report: CheckReport) -> None:
    """Both endpoints of every edge must exist."""
    rows = connection.execute("SELECT id, src, dst FROM edges ORDER BY id").fetchall()
    for row in rows:
        for ref in (row["src"], row["dst"]):
            if not _exists(connection, ref):
                report.issues.append(CheckIssue(
                    "error", "edge.endpoint", f"edge {row['id']} names missing endpoint {ref}"))


def _check_duplicates(connection, report: CheckReport) -> None:
    """DOI, arXiv and normalized title/year duplicates are errors."""
    for column in ("doi", "arxiv"):
        rows = connection.execute(
            f"SELECT lower({column}) AS value, COUNT(*) AS n FROM papers"
            f" WHERE {column} != '' GROUP BY lower({column}) HAVING n > 1").fetchall()
        for row in rows:
            report.issues.append(CheckIssue(
                "error", f"paper.duplicate_{column}",
                f"{row['n']} papers share {column} '{row['value']}'"))
    groups: Dict[str, List[str]] = {}
    for row in connection.execute("SELECT id, title, year FROM papers").fetchall():
        key = f"{normalize_text(row['title'])}|{row['year']}"
        groups.setdefault(key, []).append(row["id"])
    for key, identifiers in groups.items():
        if len(identifiers) > 1:
            report.issues.append(CheckIssue(
                "error", "paper.duplicate_title",
                f"normalized title/year {key.split('|')[0]!r} is shared by {', '.join(identifiers)}"))


def _check_support_cycles(connection, report: CheckReport) -> None:
    """Support and extension relations between claims must stay acyclic."""
    rows = connection.execute(
        "SELECT src, dst FROM edges WHERE kind IN ('supports', 'extends')").fetchall()
    graph: Dict[str, Set[str]] = {}
    for row in rows:
        source, target = row["src"], row["dst"]
        if entity_type(source) != "claim" or entity_type(target) != "claim":
            continue
        graph.setdefault(source, set()).add(target)
    for cycle in _cycles(graph):
        report.issues.append(CheckIssue(
            "error", "edge.support_cycle", "support cycle: " + " -> ".join(cycle)))


def _cycles(graph: Dict[str, Set[str]]) -> List[List[str]]:
    """Every distinct cycle reachable in a directed graph, each reported once."""
    found: List[List[str]] = []
    seen: Set[str] = set()
    done: Set[str] = set()

    def visit(node: str, path: List[str]) -> None:
        if node in done:
            return
        if node in seen:
            start = path.index(node)
            cycle = path[start:] + [node]
            canonical = _canonical_cycle(cycle)
            if canonical not in found:
                found.append(canonical)
            return
        seen.add(node)
        for nxt in sorted(graph.get(node, ())):
            visit(nxt, path + [node])
        seen.discard(node)
        done.add(node)

    for node in sorted(graph):
        visit(node, [])
    return found


def _canonical_cycle(cycle: List[str]) -> List[str]:
    """A rotation-independent form so the same cycle is reported once."""
    body = cycle[:-1]
    if not body:
        return cycle
    rotations = [body[index:] + body[:index] for index in range(len(body))]
    best = min(rotations)
    return best + [best[0]]


def _check_orphans(connection, report: CheckReport) -> None:
    """Warnings for questions without evidence and claims with no question link."""
    for row in connection.execute(
            "SELECT q.id FROM questions q WHERE NOT EXISTS ("
            " SELECT 1 FROM edges e WHERE (e.src = 'question:' || q.id OR e.dst = 'question:' || q.id)"
            " AND e.kind IN ('supports', 'contradicts', 'answers'))").fetchall():
        report.issues.append(CheckIssue(
            "warning", "question.no_evidence", f"{row['id']} has no linked evidence"))
    for row in connection.execute(
            "SELECT c.id FROM claims c WHERE NOT EXISTS ("
            " SELECT 1 FROM edges e WHERE (e.src = 'claim:' || c.id OR e.dst = 'claim:' || c.id)"
            " AND e.kind IN ('supports', 'contradicts', 'answers'))").fetchall():
        report.issues.append(CheckIssue(
            "warning", "claim.unlinked", f"{row['id']} is not linked to any question"))


def _exists(connection, ref: str) -> bool:
    """Whether a reference's target row exists."""
    if ":" not in ref:
        return False
    prefix, identifier = ref.split(":", 1)
    table = {"paper": "papers", "claim": "claims", "question": "questions",
             "p": "papers", "c": "claims", "q": "questions"}.get(prefix)
    if table is None:
        return False
    row = connection.execute(f"SELECT 1 FROM {table} WHERE id = ?", (identifier,)).fetchone()
    return row is not None


def summarize(report: CheckReport) -> Tuple[int, int]:
    """Error and warning counts for a compact text report."""
    return len(report.errors), len(report.warnings)
