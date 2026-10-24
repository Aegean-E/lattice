"""Portable JSONL graph snapshots with atomic write and idempotent merge import."""

import json
import os
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List

from lattice.errors import fail
from lattice.models import normalize_text
from lattice.repository import Repository

_RECORD_TABLES = (
    ("paper", "papers"),
    ("question", "questions"),
    ("claim", "claims"),
    ("edge", "edges"),
)


def collect_repository_records(repository: Repository) -> List[Dict[str, Any]]:
    """Every paper, question, claim and edge as a snapshot record, in stable export order."""
    records: List[Dict[str, Any]] = []
    for record_type, table in _RECORD_TABLES:
        for row in repository.connection.execute(
                f"SELECT * FROM {table} ORDER BY id").fetchall():
            records.append({"record_type": record_type, **dict(row)})
    return records


def read_snapshot_records(path: Path) -> List[Dict[str, Any]]:
    """Read a JSONL snapshot file into validated records."""
    source = Path(path)
    if not source.exists() or not source.is_file():
        fail(f"snapshot '{path}' does not exist",
             "snapshot reading needs a readable JSONL file",
             "export a snapshot first or check the file path")
    try:
        raw_lines = source.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        fail(f"could not read snapshot '{path}': {exc}",
             "the file could not be opened as UTF-8 text",
             "check file permissions and encoding")
    return _parse_jsonl(raw_lines, str(source))


def export_snapshot(repository: Repository, path: Path) -> Dict[str, Any]:
    """Write all papers, questions, claims and edges to a portable JSONL file atomically."""
    target = Path(path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    records = collect_repository_records(repository)
    lines = [json.dumps(record, sort_keys=True) for record in records]
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
    record_table = dict(_RECORD_TABLES)
    counts = {table: 0 for _, table in _RECORD_TABLES}
    for record in records:
        counts[record_table[record["record_type"]]] += 1
    return {"path": str(target), **counts}


def export_bibtex_file(repository: Repository, path: Path) -> Dict[str, Any]:
    """Write papers in the graph to a BibTeX file atomically."""
    target = Path(path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    bibtex_str = repository.export_bibtex()
    payload = (bibtex_str + ("\n" if bibtex_str and not bibtex_str.endswith("\n") else "")).encode("utf-8")
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
        fail(f"could not export BibTeX to {target}: {exc}",
             "the destination file could not be written atomically",
             "choose a writable output path")
    count = len(repository.search_literature(limit=100000)["papers"])
    return {
        "path": str(target),
        "format": "bibtex",
        "papers": count,
    }


GRAPHML_NS = "http://graphml.graphdrawing.org/xmlns"


def _add_graphml_data(elem: ET.Element, key: str, value: str) -> None:
    d = ET.SubElement(elem, f"{{{GRAPHML_NS}}}data", {"key": key})
    d.text = value


def export_graphml_string(repository: Repository) -> str:
    """Generate standard GraphML XML string representing the evidence graph."""
    records = collect_repository_records(repository)
    root = ET.Element(f"{{{GRAPHML_NS}}}graphml")
    keys = [
        ("d_type", "node", "type", "string"),
        ("d_label", "node", "label", "string"),
        ("d_title", "node", "title", "string"),
        ("d_study_type", "node", "study_type", "string"),
        ("d_year", "node", "year", "string"),
        ("d_confidence", "node", "confidence", "double"),
        ("d_status", "node", "status", "string"),
        ("e_kind", "edge", "kind", "string"),
        ("e_weight", "edge", "weight", "double"),
    ]
    for key_id, for_type, attr_name, attr_type in keys:
        ET.SubElement(root, f"{{{GRAPHML_NS}}}key", {
            "id": key_id,
            "for": for_type,
            "attr.name": attr_name,
            "attr.type": attr_type,
        })
    graph = ET.SubElement(root, f"{{{GRAPHML_NS}}}graph", {
        "id": "lattice",
        "edgedefault": "directed",
    })
    paper_study_types: Dict[str, str] = {}
    for r in records:
        rtype = r["record_type"]
        if rtype == "paper":
            paper_study_types[r["id"]] = r.get("study_type") or ""
            node_id = f"paper:{r['id']}"
            n = ET.SubElement(graph, f"{{{GRAPHML_NS}}}node", {"id": node_id})
            _add_graphml_data(n, "d_type", "paper")
            _add_graphml_data(n, "d_label", r.get("title") or node_id)
            _add_graphml_data(n, "d_title", r.get("title") or "")
            if r.get("study_type"):
                _add_graphml_data(n, "d_study_type", str(r["study_type"]))
            if r.get("year"):
                _add_graphml_data(n, "d_year", str(r["year"]))
        elif rtype == "question":
            node_id = f"question:{r['id']}"
            n = ET.SubElement(graph, f"{{{GRAPHML_NS}}}node", {"id": node_id})
            _add_graphml_data(n, "d_type", "question")
            _add_graphml_data(n, "d_label", r.get("text") or node_id)
            if r.get("status"):
                _add_graphml_data(n, "d_status", str(r["status"]))
        elif rtype == "claim":
            node_id = f"claim:{r['id']}"
            n = ET.SubElement(graph, f"{{{GRAPHML_NS}}}node", {"id": node_id})
            _add_graphml_data(n, "d_type", "claim")
            _add_graphml_data(n, "d_label", r.get("assertion") or node_id)
            if r.get("confidence") is not None:
                _add_graphml_data(n, "d_confidence", str(r["confidence"]))
            st = paper_study_types.get(r.get("paper_id"), "")
            if st:
                _add_graphml_data(n, "d_study_type", st)
        elif rtype == "edge":
            edge_id = f"edge:{r['id']}"
            e = ET.SubElement(graph, f"{{{GRAPHML_NS}}}edge", {
                "id": edge_id,
                "source": str(r["src"]),
                "target": str(r["dst"]),
            })
            _add_graphml_data(e, "e_kind", str(r.get("kind") or "related"))
            _add_graphml_data(e, "e_weight", "1.0")
    xml_decl = '<?xml version="1.0" encoding="UTF-8"?>\n'
    return xml_decl + ET.tostring(root, encoding="utf-8").decode("utf-8")


def export_graphml_file(repository: Repository, path: Path) -> Dict[str, Any]:
    """Write graph in GraphML XML format atomically."""
    target = Path(path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    xml_str = export_graphml_string(repository)
    payload = xml_str.encode("utf-8")
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
        fail(f"could not export GraphML to {target}: {exc}",
             "the destination file could not be written atomically",
             "choose a writable output path")
    stats = repository.stats()
    return {
        "path": str(target),
        "format": "graphml",
        "papers": int(stats["papers"]),
        "claims": int(stats["claims"]),
        "questions": int(stats["questions"]),
        "edges": int(stats["edges"]),
    }


def export_cytoscape_data(repository: Repository) -> Dict[str, Any]:
    """Generate Cytoscape.js elements dictionary for graph visualization."""
    records = collect_repository_records(repository)
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    paper_study_types: Dict[str, str] = {}
    for r in records:
        rtype = r["record_type"]
        if rtype == "paper":
            paper_study_types[r["id"]] = r.get("study_type") or ""
            nodes.append({
                "data": {
                    "id": f"paper:{r['id']}",
                    "type": "paper",
                    "label": r.get("title") or r["id"],
                    "title": r.get("title") or "",
                    "authors": r.get("authors") or "",
                    "year": r.get("year"),
                    "venue": r.get("venue") or "",
                    "study_type": r.get("study_type") or "",
                }
            })
        elif rtype == "question":
            nodes.append({
                "data": {
                    "id": f"question:{r['id']}",
                    "type": "question",
                    "label": r.get("text") or r["id"],
                    "status": r.get("status") or "open",
                }
            })
        elif rtype == "claim":
            nodes.append({
                "data": {
                    "id": f"claim:{r['id']}",
                    "type": "claim",
                    "label": r.get("assertion") or r["id"],
                    "quote": r.get("quote") or "",
                    "locator": r.get("locator") or "",
                    "confidence": r.get("confidence", 1.0),
                    "stance": r.get("stance") or "supports",
                    "paper_id": r.get("paper_id") or "",
                    "study_type": paper_study_types.get(r.get("paper_id"), ""),
                }
            })
        elif rtype == "edge":
            edges.append({
                "data": {
                    "id": f"e_{r['id']}",
                    "source": str(r["src"]),
                    "target": str(r["dst"]),
                    "kind": str(r.get("kind") or "related"),
                    "weight": 1.0,
                }
            })
    return {
        "format": "cytoscape",
        "elements": {
            "nodes": nodes,
            "edges": edges,
        }
    }


def export_cytoscape_file(repository: Repository, path: Path) -> Dict[str, Any]:
    """Write graph in Cytoscape.js JSON format atomically."""
    target = Path(path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    data = export_cytoscape_data(repository)
    payload = json.dumps(data, indent=2).encode("utf-8")
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
        fail(f"could not export Cytoscape to {target}: {exc}",
             "the destination file could not be written atomically",
             "choose a writable output path")
    stats = repository.stats()
    return {
        "path": str(target),
        "format": "cytoscape",
        "papers": int(stats["papers"]),
        "claims": int(stats["claims"]),
        "questions": int(stats["questions"]),
        "edges": int(stats["edges"]),
    }



def import_snapshot(repository: Repository, path: Path) -> Dict[str, Any]:
    """Import a JSONL snapshot idempotently, remapping entity references as needed."""
    records = read_snapshot_records(path)
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
        "path": str(Path(path)),
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

