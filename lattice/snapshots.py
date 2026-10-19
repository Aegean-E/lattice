"""Portable JSONL graph snapshots with atomic write and idempotent merge import."""

import json
import os
from pathlib import Path
from typing import Any, Dict, List

from lattice.errors import fail
from lattice.models import normalize_text
from lattice.repository import Repository


def export_snapshot(repository: Repository, path: Path) -> Dict[str, Any]:
    """Write all papers, questions, claims and edges to a portable JSONL file atomically."""
    target = Path(path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    papers = [
        dict(row)
        for row in repository.connection.execute("SELECT * FROM papers ORDER BY id").fetchall()
    ]
    questions = [
        dict(row)
        for row in repository.connection.execute("SELECT * FROM questions ORDER BY id").fetchall()
    ]
    claims = [
        dict(row)
        for row in repository.connection.execute("SELECT * FROM claims ORDER BY id").fetchall()
    ]
    edges = [
        dict(row)
        for row in repository.connection.execute("SELECT * FROM edges ORDER BY id").fetchall()
    ]
    lines: List[str] = []
    for item in papers:
        lines.append(json.dumps({"record_type": "paper", **item}, sort_keys=True))
    for item in questions:
        lines.append(json.dumps({"record_type": "question", **item}, sort_keys=True))
    for item in claims:
        lines.append(json.dumps({"record_type": "claim", **item}, sort_keys=True))
    for item in edges:
        lines.append(json.dumps({"record_type": "edge", **item}, sort_keys=True))
    payload = ("\n".join(lines) + ("\n" if lines else "")).encode("utf-8")
    temp_path = target.with_name(f".tmp_{target.name}_{os.getpid()}")
    try:
        with open(temp_path, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, target)
    except OSError as exc:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)
        fail(f"could not export snapshot to {target}: {exc}",
             "the destination file could not be written atomically",
             "choose a writable output path")
    return {
        "path": str(target),
        "papers": len(papers),
        "questions": len(questions),
        "claims": len(claims),
        "edges": len(edges),
    }


def import_snapshot(repository: Repository, path: Path) -> Dict[str, Any]:
    """Import a JSONL snapshot idempotently, remapping entity references as needed."""
    source = Path(path)
    if not source.exists() or not source.is_file():
        fail(f"snapshot '{path}' does not exist",
             "import_snapshot needs a readable JSONL file",
             "export a snapshot first or check the file path")
    try:
        raw_lines = source.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        fail(f"could not read snapshot '{path}': {exc}",
             "the file could not be opened as UTF-8 text",
             "check file permissions and encoding")
    records = _parse_jsonl(raw_lines, str(source))
    paper_map: Dict[str, str] = {}
    question_map: Dict[str, str] = {}
    claim_map: Dict[str, str] = {}
    papers_count = 0
    questions_count = 0
    claims_count = 0
    claims_created = 0
    edges_count = 0
    for record in records:
        if record.get("record_type") != "paper":
            continue
        paper, _ = repository.add_paper(record)
        paper_map[str(record.get("id") or paper.id)] = paper.id
        papers_count += 1
    for record in records:
        if record.get("record_type") != "question":
            continue
        q_id = _import_question(repository, record)
        question_map[str(record.get("id") or q_id)] = q_id
        questions_count += 1
    for record in records:
        if record.get("record_type") != "claim":
            continue
        c_id, created = _import_claim(repository, record, paper_map)
        claim_map[str(record.get("id") or c_id)] = c_id
        claims_count += 1
        if created:
            claims_created += 1
    for record in records:
        if record.get("record_type") != "edge":
            continue
        if _import_edge(repository, record, paper_map, claim_map, question_map):
            edges_count += 1
    return {
        "path": str(source),
        "papers": papers_count,
        "questions": questions_count,
        "claims": claims_count,
        "claims_created": claims_created,
        "edges": edges_count,
    }


def _parse_jsonl(lines: List[str], label: str) -> List[Dict[str, Any]]:
    """Parse non-empty JSONL lines and verify each is an object."""
    records: List[Dict[str, Any]] = []
    for lineno, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            item = json.loads(stripped)
        except ValueError as exc:
            fail(f"{label}:{lineno}: invalid JSON line: {exc}",
                 "every line in a snapshot must be a JSON object",
                 "re-export the snapshot with `lattice export`")
        if not isinstance(item, dict):
            fail(f"{label}:{lineno}: snapshot line is not a JSON object",
                 "every line must carry `record_type` and fields",
                 "re-export the snapshot with `lattice export`")
        records.append(item)
    return records


def _import_question(repository: Repository, record: Dict[str, Any]) -> str:
    """Find an existing question with the same text or create it."""
    text = " ".join(str(record.get("text") or "").split())
    existing = repository.connection.execute(
        "SELECT id FROM questions WHERE lower(text) = lower(?) LIMIT 1", (text,)
    ).fetchone()
    if existing is not None:
        q_id = str(existing["id"])
    else:
        q_id = repository.add_question(text).id
    status = str(record.get("status") or "open").strip().lower()
    if status in ("open", "answered", "abandoned") and status != "open":
        repository.set_question_status(q_id, status)
    return q_id


def _import_claim(repository: Repository, record: Dict[str, Any],
                  paper_map: Dict[str, str]) -> tuple[str, bool]:
    """Find an existing claim on the target paper or create it."""
    old_paper_id = str(record.get("paper_id") or "")
    paper_id = paper_map.get(old_paper_id, old_paper_id)
    text = " ".join(str(record.get("text") or "").split())
    quote = " ".join(str(record.get("quote") or "").split())
    wanted_quote = normalize_text(quote)
    for row in repository.connection.execute(
        "SELECT id, quote FROM claims WHERE paper_id = ?", (paper_id,)
    ).fetchall():
        if normalize_text(row["quote"]) == wanted_quote:
            return str(row["id"]), False
    claim = repository.add_claim(
        paper=paper_id,
        text=text,
        quote=quote,
        locator=str(record.get("locator") or ""),
        stance=str(record.get("stance") or "mentions"),
        confidence=float(record.get("confidence", 0.5)),
    )
    return claim.id, True


def _import_edge(repository: Repository, record: Dict[str, Any],
                 paper_map: Dict[str, str], claim_map: Dict[str, str],
                 question_map: Dict[str, str]) -> bool:
    """Remap endpoints and insert the edge if not already present."""
    src = _remap_ref(str(record.get("src") or ""), paper_map, claim_map, question_map)
    dst = _remap_ref(str(record.get("dst") or ""), paper_map, claim_map, question_map)
    kind = str(record.get("kind") or "related")
    existing = repository.connection.execute(
        "SELECT 1 FROM edges WHERE src = ? AND dst = ? AND kind = ?",
        (src, dst, kind),
    ).fetchone()
    if existing is not None:
        return False
    repository.add_edge(src, dst, kind, note=str(record.get("note") or ""))
    return True


def _remap_ref(ref: str, paper_map: Dict[str, str], claim_map: Dict[str, str],
               question_map: Dict[str, str]) -> str:
    """Translate an exported entity reference to its imported identifier."""
    if ":" not in ref:
        return ref
    prefix, bare = ref.split(":", 1)
    if prefix == "paper":
        return f"paper:{paper_map.get(bare, bare)}"
    if prefix == "claim":
        return f"claim:{claim_map.get(bare, bare)}"
    if prefix == "question":
        return f"question:{question_map.get(bare, bare)}"
    return ref
