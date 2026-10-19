"""Command-line interface: ingest, assert, link, ask, brief, review, check and serve MCP."""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from lattice.checks import run_checks
from lattice.database import SCHEMA_VERSION, open_database
from lattice.errors import LatticeError
from lattice.ingest import parse_paths
from lattice.inquiry import ask, brief, review
from lattice.mcp import serve
from lattice.repository import Repository

DEFAULT_DB = "lattice.db"


def build_parser() -> argparse.ArgumentParser:
    """The complete command grammar."""
    parser = argparse.ArgumentParser(
        prog="lattice",
        description="A provenance-first research knowledge graph for humans and AI agents.",
    )
    parser.add_argument("--db", default=DEFAULT_DB,
                        help=f"SQLite database file (default: {DEFAULT_DB})")
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON")
    commands = parser.add_subparsers(dest="command", required=True)

    init = commands.add_parser("init", help="create the database and report its schema")
    init.set_defaults(handler=_run_init)

    ingest = commands.add_parser("ingest", help="import BibTeX, RIS, CSV, Markdown or text")
    ingest.add_argument("paths", nargs="+", help="one or more files to ingest")
    ingest.set_defaults(handler=_run_ingest)

    claim = commands.add_parser("claim", help="record a claim with its source quote")
    claim.add_argument("--paper", required=True, help="paper reference or bare p_ id")
    claim.add_argument("--text", required=True, help="the asserted claim")
    claim.add_argument("--quote", required=True, help="exact sentence from the source")
    claim.add_argument("--locator", default="", help="page, section or paragraph")
    claim.add_argument("--stance", default="mentions", help="supports, contradicts or mentions")
    claim.add_argument("--confidence", type=float, default=0.5, help="weight in [0, 1]")
    claim.set_defaults(handler=_run_claim)

    question = commands.add_parser("question", help="record a research question")
    question.add_argument("text", help="the question")
    question.set_defaults(handler=_run_question)

    link = commands.add_parser("link", help="add a typed relation between entities")
    link.add_argument("src", help="source reference")
    link.add_argument("dst", help="target reference")
    link.add_argument("--type", required=True, dest="kind", help="edge kind")
    link.add_argument("--note", default="", help="why the relation holds")
    link.set_defaults(handler=_run_link)

    search = commands.add_parser("search", help="search papers, claims and questions")
    search.add_argument("query", help="word or phrase")
    search.add_argument("--limit", type=int, default=20, help="maximum rows per section")
    search.set_defaults(handler=_run_search)

    show = commands.add_parser("show", help="show one entity and its edges")
    show.add_argument("ref", help="paper, claim or question reference")
    show.set_defaults(handler=_run_show)

    ask_parser = commands.add_parser("ask", help="assemble evidence for a question")
    ask_parser.add_argument("target", help="question reference, question text or phrase")
    ask_parser.add_argument("--limit", type=int, default=20, help="suggestion search limit")
    ask_parser.set_defaults(handler=_run_ask)

    brief_parser = commands.add_parser("brief", help="token-budgeted evidence pack")
    brief_parser.add_argument("target", help="question reference, question text or phrase")
    brief_parser.add_argument("--tokens", type=int, default=2000, help="approximate token budget")
    brief_parser.set_defaults(handler=_run_brief)

    review_parser = commands.add_parser("review", help="Markdown literature-review outline")
    review_parser.add_argument("target", help="question reference, question text or phrase")
    review_parser.add_argument("--out", default=None, help="write the outline to this file")
    review_parser.set_defaults(handler=_run_review)

    stats = commands.add_parser("stats", help="entity and edge counts")
    stats.set_defaults(handler=_run_stats)

    check = commands.add_parser("check", help="run the integrity gate")
    check.set_defaults(handler=_run_check)

    mcp = commands.add_parser("mcp", help="serve the graph over MCP stdio JSON-RPC")
    mcp.set_defaults(handler=_run_mcp)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Parse arguments, open the database and dispatch one command."""
    parser = build_parser()
    args = parser.parse_args(argv)
    connection = open_database(args.db)
    repository = Repository(connection)
    try:
        return int(args.handler(args, repository))
    except LatticeError as exc:
        print(exc.render(), file=sys.stderr)
        return 1
    finally:
        connection.close()


def _emit(payload: Dict[str, Any], lines: List[str], as_json: bool) -> None:
    """Print either stable JSON or human text."""
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print("\n".join(lines))


def _run_init(args: argparse.Namespace, repository: Repository) -> int:
    """Create the schema, which opening the database already did."""
    payload = {"database": args.db, "schema": SCHEMA_VERSION, "stats": repository.stats()}
    _emit(payload, [f"[OK] database ready at {args.db}",
                    f"     schema {payload['schema']}; {payload['stats']['papers']} papers, "
                    f"{payload['stats']['claims']} claims, "
                    f"{payload['stats']['questions']} questions"], args.json)
    return 0


def _run_ingest(args: argparse.Namespace, repository: Repository) -> int:
    """Import every file and report created versus merged records."""
    records = parse_paths([Path(path) for path in args.paths])
    imported = []
    for record in records:
        paper, created = repository.add_paper(record)
        imported.append({"id": paper.id, "title": paper.title, "created": created})
    created_count = sum(1 for item in imported if item["created"])
    payload = {"imported": len(imported), "created": created_count, "records": imported}
    lines = [f"[OK] parsed {len(imported)} record(s); {created_count} new, "
             f"{len(imported) - created_count} merged"]
    lines += [f"     {item['id']}  {'new    ' if item['created'] else 'merged '}  {item['title']}"
              for item in imported]
    _emit(payload, lines, args.json)
    return 0


def _run_claim(args: argparse.Namespace, repository: Repository) -> int:
    """Record one claim."""
    claim = repository.add_claim(args.paper, args.text, args.quote, args.locator,
                                 args.stance, args.confidence)
    _emit({"claim": claim.to_dict()},
          [f"[OK] added {claim.id} to {claim.paper_id} ({claim.stance}, "
           f"confidence {claim.confidence:.2f})"], args.json)
    return 0


def _run_question(args: argparse.Namespace, repository: Repository) -> int:
    """Record one question."""
    question = repository.add_question(args.text)
    _emit({"question": question.to_dict()},
          [f"[OK] added {question.id}: {question.text}"], args.json)
    return 0


def _run_link(args: argparse.Namespace, repository: Repository) -> int:
    """Record one typed edge."""
    edge = repository.add_edge(args.src, args.dst, args.kind, args.note)
    _emit({"edge": edge.to_dict()},
          [f"[OK] {edge.src} -{edge.kind}-> {edge.dst}"], args.json)
    return 0


def _run_search(args: argparse.Namespace, repository: Repository) -> int:
    """Search and print the three result sections."""
    result = repository.search(args.query, args.limit)
    lines = [f"Papers ({len(result['papers'])}):"]
    lines += [f"  [{paper['id']}] {paper['title']} ({paper.get('year') or 'n.d.'})"
              for paper in result["papers"]] or ["  none"]
    lines += [f"Claims ({len(result['claims'])}):"]
    lines += [f"  [{claim['id']}] {claim['text']}" for claim in result["claims"]] or ["  none"]
    lines += [f"Questions ({len(result['questions'])}):"]
    lines += [f"  [{question['id']}] {question['text']}"
              for question in result["questions"]] or ["  none"]
    _emit(result, lines, args.json)
    return 0


def _run_show(args: argparse.Namespace, repository: Repository) -> int:
    """Show one entity and each attached edge."""
    result = repository.get(args.ref)
    entity = result["entity"]
    lines = [f"{result['ref']}: {entity.get('title') or entity.get('text', '')}"]
    for edge in result["edges"]:
        other = edge["details"].get("other", {})
        lines.append(f"  {edge['src']} -{edge['kind']}-> {edge['dst']}  "
                     f"({other.get('type', 'missing')})")
    _emit(result, lines, args.json)
    return 0


def _run_ask(args: argparse.Namespace, repository: Repository) -> int:
    """Assemble and print evidence."""
    result = ask(repository, args.target, args.limit)
    if result["mode"] == "question":
        lines = [f"Question {result['question']['id']}: {result['question']['text']}"]
        for group, label in (("supports", "Supports"), ("contradicts", "Contradicts"),
                             ("answers", "Answers")):
            lines.append(f"{label} ({len(result[group])}):")
            lines += [f"  [{item['claim']['id']}] {item['claim']['text']}"
                      for item in result[group]] or ["  none"]
        lines.append("Gaps:")
        lines += [f"  - {gap}" for gap in result["gaps"]] or ["  none"]
        lines.append("Suggested unlinked claims:")
        lines += [f"  [{claim['id']}] {claim['text']}" for claim in result["suggestions"]] \
            or ["  none"]
    else:
        lines = [f"No tracked question matched; search mode for {args.target!r}."]
        lines += [f"  claim [{claim['id']}] {claim['text']}" for claim in result["claims"]]
        lines += [f"  paper [{paper['id']}] {paper['title']}" for paper in result["papers"]]
    _emit(result, lines, args.json)
    return 0


def _run_brief(args: argparse.Namespace, repository: Repository) -> int:
    """Print a token-budgeted evidence pack."""
    result = brief(repository, args.target, args.tokens)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(result["text"])
    return 0


def _run_review(args: argparse.Namespace, repository: Repository) -> int:
    """Print or write a review outline."""
    result = review(repository, args.target)
    if args.out:
        target = Path(args.out)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(result["markdown"], encoding="utf-8")
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    elif args.out:
        print(f"[OK] wrote {len(result['markdown'])} characters to {args.out}")
    else:
        print(result["markdown"])
    return 0


def _run_stats(args: argparse.Namespace, repository: Repository) -> int:
    """Print counts."""
    result = repository.stats()
    lines = [f"papers: {result['papers']}", f"claims: {result['claims']}",
             f"questions: {result['questions']}", f"edges: {result['edges']}"]
    lines += [f"  {kind}: {count}" for kind, count in result["edge_kinds"].items()]
    _emit(result, lines, args.json)
    return 0


def _run_check(args: argparse.Namespace, repository: Repository) -> int:
    """Run the integrity gate and return 1 on any error."""
    report = run_checks(repository)
    lines = [f"[{'OK' if report.passed else 'FAIL'}] {len(report.errors)} error(s), "
             f"{len(report.warnings)} warning(s)"]
    lines += [f"  {issue.level.upper():7} {issue.code}: {issue.message}" for issue in report.issues]
    _emit(report.to_dict(), lines, args.json)
    return 0 if report.passed else 1


def _run_mcp(args: argparse.Namespace, repository: Repository) -> int:
    """Serve MCP on stdio; stdout carries protocol messages only."""
    serve(repository)
    return 0
