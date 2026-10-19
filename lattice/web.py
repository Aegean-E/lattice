"""Zero-dependency web server and human-friendly Research Studio UI for Lattice."""

import json
import urllib.parse
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional

from lattice.analysis import (
    build_evidence_matrix,
    detect_contradictions,
    rank_influential_entities,
)
from lattice.checks import run_checks
from lattice.database import open_database
from lattice.discovery import DiscoveryService
from lattice.errors import LatticeError, fail
from lattice.extraction import extract_all, extract_from_paper
from lattice.ingest import (
    parse_bibtex,
    parse_csv,
    parse_markdown,
    parse_ris,
    parse_text,
)
from lattice.repository import Repository
from lattice.synthesis import synthesize


@dataclass(frozen=True)
class WebResponse:
    """Immutable HTTP response returned by `dispatch_web_request`."""

    status: int
    content_type: str
    body: str


def dispatch_web_request(repository: Repository, method: str, path: str,
                         body: Optional[str] = None) -> WebResponse:
    """Route an HTTP method and path to the UI or JSON API without network sockets."""
    parsed = urllib.parse.urlsplit(path or "/")
    route = parsed.path.rstrip("/") or "/"
    query = urllib.parse.parse_qs(parsed.query)
    verb = (method or "GET").upper()
    try:
        if verb == "GET" and route == "/":
            return WebResponse(200, "text/html; charset=utf-8", WEB_HTML)
        if verb == "GET" and route == "/api/overview":
            return _json_response(200, _build_overview(repository))
        if verb == "GET" and route == "/api/matrix":
            return _json_response(200, _build_matrix_bundle(repository))
        if verb == "GET" and route == "/api/export":
            return WebResponse(
                200,
                "application/x-ndjson; charset=utf-8",
                _export_jsonl_string(repository),
            )
        if verb == "GET" and route == "/api/search":
            return _json_response(200, _handle_search(repository, query))
        if verb == "GET" and route == "/api/literature":
            return _json_response(200, _handle_literature(repository, query))
        if verb == "GET" and route == "/api/subgraph":
            return _json_response(200, _handle_subgraph(repository, query))
        if verb == "GET" and route == "/api/synthesize":
            return _json_response(200, _handle_synthesize(repository, query))
        if verb == "POST":
            payload = _parse_json_body(body)
            return _dispatch_post(repository, route, payload)
        return _json_response(404, {"error": f"route not found: {verb} {route}"})
    except LatticeError as exc:
        return _json_response(400, {"error": exc.render(), "message": exc.message,
                                    "why": exc.why, "fix": exc.fix})
    except (ValueError, TypeError) as exc:
        return _json_response(400, {"error": f"Error: {exc}"})


def _dispatch_post(repository: Repository, route: str,
                   payload: Dict[str, Any]) -> WebResponse:
    """Handle JSON POST routes for mutations, discovery, extraction, and demo seeding."""
    if route == "/api/demo":
        return _json_response(200, _seed_demo(repository))
    if route == "/api/discover":
        service = DiscoveryService(repository)
        result = service.discover(
            str(payload.get("query") or ""),
            source=str(payload.get("source") or "offline"),
            limit=int(payload.get("limit", 10)),
            ingest=bool(payload.get("ingest", True)),
        )
        return _json_response(200, result)
    if route == "/api/extract":
        q_ref = str(payload.get("question") or "").strip() or None
        paper_ref = str(payload.get("paper") or "").strip() or None
        if paper_ref and not payload.get("all"):
            out = extract_from_paper(repository, paper_ref, question_ref=q_ref)
            return _json_response(200, {
                "papers_processed": 1,
                "claims_created": len(out.claims),
                "edges_created": len(out.edges),
                "result": out.to_dict(),
            })
        return _json_response(200, extract_all(repository, question_ref=q_ref))
    if route == "/api/ingest-text":
        return _json_response(200, _handle_ingest_text(repository, payload))
    if route == "/api/detect-contradictions":
        auto_link = bool(payload.get("auto_link", True))
        pairs = [item.to_dict() for item in detect_contradictions(repository, auto_link=auto_link)]
        return _json_response(200, {"count": len(pairs), "contradictions": pairs})
    if route == "/api/questions":
        question = repository.add_question(str(payload.get("text") or ""))
        return _json_response(200, {"question": question.to_dict()})
    if route == "/api/question-status":
        question = repository.set_question_status(
            str(payload.get("question") or ""),
            str(payload.get("status") or ""),
        )
        return _json_response(200, {"question": question.to_dict()})
    if route == "/api/papers":
        paper, created = repository.add_paper(payload)
        return _json_response(200, {"paper": paper.to_dict(), "created": created})
    if route == "/api/claims":
        claim = repository.add_claim(
            paper=str(payload.get("paper") or ""),
            text=str(payload.get("text") or ""),
            quote=str(payload.get("quote") or ""),
            locator=str(payload.get("locator") or ""),
            stance=str(payload.get("stance") or "mentions"),
            confidence=float(payload.get("confidence", 0.5)),
        )
        q_ref = str(payload.get("question") or "").strip()
        edge_dict = None
        if q_ref:
            q_obj = repository.get_question(q_ref)
            kind = claim.stance if claim.stance in ("supports", "contradicts") else "answers"
            edge = repository.add_edge(
                f"claim:{claim.id}", f"question:{q_obj.id}", kind, note="linked via web studio"
            )
            edge_dict = edge.to_dict()
        return _json_response(200, {"claim": claim.to_dict(), "edge": edge_dict})
    if route == "/api/edges":
        edge = repository.add_edge(
            str(payload.get("src") or ""),
            str(payload.get("dst") or ""),
            str(payload.get("kind") or ""),
            note=str(payload.get("note") or ""),
        )
        return _json_response(200, {"edge": edge.to_dict()})
    return _json_response(404, {"error": f"route not found: POST {route}"})


def _build_overview(repository: Repository) -> Dict[str, Any]:
    """Assemble full workspace state for the Human UI dashboard."""
    papers = [
        dict(row)
        for row in repository.connection.execute(
            "SELECT * FROM papers ORDER BY year DESC, title LIMIT 100"
        ).fetchall()
    ]
    questions = [
        dict(row)
        for row in repository.connection.execute(
            "SELECT * FROM questions ORDER BY id DESC LIMIT 100"
        ).fetchall()
    ]
    claims = [
        dict(row)
        for row in repository.connection.execute(
            "SELECT * FROM claims ORDER BY id DESC LIMIT 100"
        ).fetchall()
    ]
    edges = [
        dict(row)
        for row in repository.connection.execute(
            "SELECT * FROM edges ORDER BY id DESC LIMIT 100"
        ).fetchall()
    ]
    check = run_checks(repository)
    study_types = sorted({str(paper["study_type"]) for paper in papers
                          if str(paper.get("study_type") or "").strip()})
    tags = sorted({tag.strip() for paper in papers
                   for tag in str(paper.get("tags") or "").split(",") if tag.strip()})
    return {
        "stats": repository.stats(),
        "check": check.to_dict(),
        "papers": papers,
        "questions": questions,
        "claims": claims,
        "edges": edges,
        "study_types": study_types,
        "tags": tags,
    }


def _handle_search(repository: Repository, query: Dict[str, List[str]]) -> Dict[str, Any]:
    """Run filtered search from query parameters."""
    q = _first(query, "q")
    limit = int(_first(query, "limit") or "20")
    stance = _first(query, "stance") or None
    min_conf_str = _first(query, "min_confidence")
    min_conf = float(min_conf_str) if min_conf_str else None
    year = _first(query, "year") or None
    return repository.search(q, limit=limit, stance=stance, min_confidence=min_conf, year=year)


def _handle_literature(repository: Repository, query: Dict[str, List[str]]) -> Dict[str, Any]:
    """Search the literature by tags, words, sentences, study type and year."""
    q = _first(query, "q")
    tags = ",".join(query.get("tags", []) + query.get("tag", []))
    study_type = _first(query, "study_type") or _first(query, "type")
    year = _first(query, "year") or None
    limit = int(_first(query, "limit") or "50")
    return repository.search_literature(
        q, tags=tags, study_type=study_type, year=year, limit=limit
    )


def _handle_subgraph(repository: Repository, query: Dict[str, List[str]]) -> Dict[str, Any]:
    """Run multi-hop subgraph traversal from query parameters."""
    ref = _first(query, "ref")
    depth = int(_first(query, "depth") or "2")
    return repository.subgraph(ref, depth=depth)


def _handle_synthesize(repository: Repository, query: Dict[str, List[str]]) -> Dict[str, Any]:
    """Run scientific literature synthesis from query parameters."""
    target = _first(query, "target")
    tokens = int(_first(query, "tokens") or "2500")
    return synthesize(repository, target, tokens=tokens).to_dict()


def _build_matrix_bundle(repository: Repository) -> Dict[str, Any]:
    """Assemble the Paper x Question evidence matrix, contradictions, and keystone ranking."""
    return {
        "matrix": build_evidence_matrix(repository),
        "contradictions": [item.to_dict() for item in detect_contradictions(repository, auto_link=False)],
        "keystone": rank_influential_entities(repository, limit=10),
    }


def _handle_ingest_text(repository: Repository, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Parse raw bibliography or note text (BibTeX, RIS, CSV, Markdown, text) and ingest into the graph."""
    raw = str(payload.get("text") or "").strip()
    if not raw:
        fail("ingest-text requires non-empty text",
             "cannot parse an empty bibliography or note",
             "paste BibTeX, RIS, CSV, or Markdown text")
    fmt = str(payload.get("format") or "bibtex").strip().lower()
    source_name = str(payload.get("source_name") or "web-paste").strip() or "web-paste"
    if fmt in ("bibtex", "bib"):
        records = parse_bibtex(raw)
    elif fmt == "ris":
        records = parse_ris(raw)
    elif fmt == "csv":
        records = parse_csv(raw)
    elif fmt in ("markdown", "md"):
        records = parse_markdown(raw, source_name)
    elif fmt in ("text", "txt"):
        records = parse_text(raw, source_name)
    else:
        fail(f"unsupported text format '{fmt}'",
             "supported formats are bibtex, ris, csv, markdown, and text",
             "pass format='bibtex', 'ris', 'csv', 'markdown', or 'text'")
    if not records:
        fail("no paper records could be parsed from the pasted text",
             "the parser found zero entries with a title",
             "verify the format matches the pasted bibliography")
    papers_out = []
    created_count = 0
    claims_created = 0
    edges_created = 0
    q_ref = str(payload.get("question") or "").strip() or None
    do_extract = bool(payload.get("extract", True))
    for record in records:
        paper, created = repository.add_paper(record)
        if created:
            created_count += 1
        papers_out.append(paper.to_dict())
        if do_extract and paper.abstract.strip():
            extracted = extract_from_paper(repository, paper.id, question_ref=q_ref)
            claims_created += len(extracted.claims)
            edges_created += len(extracted.edges)
    return {
        "format": fmt,
        "parsed": len(records),
        "ingested": len(papers_out),
        "created": created_count,
        "claims_created": claims_created,
        "edges_created": edges_created,
        "papers": papers_out,
    }


def _export_jsonl_string(repository: Repository) -> str:
    """Serialize all graph entities and edges as portable JSONL text."""
    lines: List[str] = []
    for table, record_type in (
        ("papers", "paper"),
        ("questions", "question"),
        ("claims", "claim"),
        ("edges", "edge"),
    ):
        for row in repository.connection.execute(f"SELECT * FROM {table} ORDER BY id").fetchall():
            lines.append(json.dumps({"record_type": record_type, **dict(row)}, sort_keys=True))
    return "\n".join(lines) + ("\n" if lines else "")



def _seed_demo(repository: Repository) -> Dict[str, Any]:
    """Populate the built-in seed corpus, create research questions, and extract claims."""
    q1_text = "Does slow-wave sleep consolidate declarative and motor memory?"
    existing_q = repository.connection.execute(
        "SELECT id FROM questions WHERE lower(text) = lower(?) LIMIT 1", (q1_text,)
    ).fetchone()
    q1_id = str(existing_q["id"]) if existing_q else repository.add_question(q1_text).id

    q2_text = "Do quote-backed evidence graphs reduce citation drift in scientific synthesis?"
    existing_q2 = repository.connection.execute(
        "SELECT id FROM questions WHERE lower(text) = lower(?) LIMIT 1", (q2_text,)
    ).fetchone()
    q2_id = str(existing_q2["id"]) if existing_q2 else repository.add_question(q2_text).id

    service = DiscoveryService(repository)
    service.discover("sleep memory recall", source="offline", limit=10, ingest=True)
    service.discover("evidence graphs citation synthesis", source="offline", limit=10, ingest=True)
    extraction = extract_all(repository)
    return {
        "seeded_questions": [q1_id, q2_id],
        "extraction": extraction,
        "stats": repository.stats(),
    }


def _first(query: Dict[str, List[str]], key: str) -> str:
    """First query parameter value or empty string."""
    values = query.get(key) or []
    return values[0].strip() if values else ""


def _parse_json_body(body: Optional[str]) -> Dict[str, Any]:
    """Parse an optional JSON request body into a dictionary."""
    if not body or not body.strip():
        return {}
    data = json.loads(body)
    if not isinstance(data, dict):
        fail("request body must be a JSON object",
             "API endpoints expect named fields",
             "send a JSON object payload")
    return data


def _json_response(status: int, payload: Dict[str, Any]) -> WebResponse:
    """Serialize a dictionary as an application/json `WebResponse`."""
    return WebResponse(
        status=status,
        content_type="application/json; charset=utf-8",
        body=json.dumps(payload, indent=2, sort_keys=True),
    )


def serve_web(db_path: str, host: str = "127.0.0.1", port: int = 8765,
              open_browser: bool = False, once: bool = False) -> None:
    """Run the local HTTP server for the Lattice Research Studio UI."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self._handle("GET")

        def do_POST(self) -> None:
            self._handle("POST")

        def _handle(self, method: str) -> None:
            length = int(self.headers.get("Content-Length") or "0")
            raw_body = self.rfile.read(length).decode("utf-8", errors="replace") if length > 0 else None
            conn = open_database(db_path)
            try:
                repo = Repository(conn)
                response = dispatch_web_request(repo, method, self.path, raw_body)
            finally:
                conn.close()
            encoded = response.body.encode("utf-8")
            self.send_response(response.status)
            self.send_header("Content-Type", response.content_type)
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, format: str, *args: Any) -> None:
            return

    server = ThreadingHTTPServer((host, int(port)), Handler)
    actual_port = server.server_address[1]
    url = f"http://{host}:{actual_port}"
    print(f"[OK] Lattice Research Studio running at {url} (db: {db_path})")
    if open_browser:
        webbrowser.open_new_tab(url)
    try:
        if once:
            server.handle_request()
        else:
            server.serve_forever()
    except KeyboardInterrupt:
        print("\n[OK] Lattice Research Studio stopped.")
    finally:
        server.server_close()


WEB_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Lattice Research Studio</title>
<style>
  :root {
    --bg: #0f172a;
    --panel: #1e293b;
    --panel-alt: #263349;
    --border: #334155;
    --text: #f8fafc;
    --muted: #94a3b8;
    --accent: #38bdf8;
    --accent-hover: #0ea5e9;
    --support: #22c55e;
    --contradict: #ef4444;
    --warn: #f59e0b;
    --purple: #a855f7;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.5;
  }
  header {
    background: var(--panel);
    border-bottom: 1px solid var(--border);
    padding: 14px 24px;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
  }
  .brand {
    display: flex;
    align-items: center;
    gap: 12px;
  }
  .brand h1 {
    margin: 0;
    font-size: 1.25rem;
    letter-spacing: -0.02em;
  }
  .brand span {
    font-size: 0.82rem;
    color: var(--muted);
    background: var(--panel-alt);
    padding: 3px 9px;
    border-radius: 999px;
    border: 1px solid var(--border);
  }
  .stats-bar {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px;
  }
  .pill {
    background: var(--panel-alt);
    border: 1px solid var(--border);
    padding: 5px 11px;
    border-radius: 8px;
    font-size: 0.82rem;
    color: var(--muted);
  }
  .pill strong { color: var(--text); margin-left: 4px; }
  .pill.ok { border-color: rgba(34,197,94,0.45); color: #86efac; }
  .pill.fail { border-color: rgba(239,68,68,0.5); color: #fca5a5; }
  .btn {
    background: var(--accent);
    color: #082f49;
    border: none;
    border-radius: 8px;
    padding: 8px 14px;
    font-weight: 600;
    font-size: 0.86rem;
    cursor: pointer;
    transition: background 0.15s;
  }
  .btn:hover { background: var(--accent-hover); }
  .btn.secondary {
    background: var(--panel-alt);
    color: var(--text);
    border: 1px solid var(--border);
  }
  .btn.secondary:hover { background: #334155; }
  .btn.sm { padding: 4px 10px; font-size: 0.78rem; }
  nav.tabs {
    display: flex;
    gap: 6px;
    padding: 12px 24px 0;
    border-bottom: 1px solid var(--border);
    background: #131d33;
  }
  .tab-btn {
    background: transparent;
    color: var(--muted);
    border: 1px solid transparent;
    border-bottom: none;
    padding: 9px 16px;
    border-radius: 8px 8px 0 0;
    font-weight: 600;
    font-size: 0.9rem;
    cursor: pointer;
  }
  .tab-btn.active {
    background: var(--bg);
    color: var(--accent);
    border-color: var(--border);
  }
  main {
    max-width: 1400px;
    margin: 0 auto;
    padding: 20px 24px 48px;
  }
  .tab-pane { display: none; }
  .tab-pane.active { display: block; }
  .grid-2 {
    display: grid;
    grid-template-columns: 1fr 1.35fr;
    gap: 20px;
  }
  @media (max-width: 980px) {
    .grid-2 { grid-template-columns: 1fr; }
  }
  .card {
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 18px;
    margin-bottom: 18px;
  }
  .card h2 {
    margin: 0 0 12px;
    font-size: 1.05rem;
    display: flex;
    align-items: center;
    justify-content: space-between;
  }
  .form-row {
    display: flex;
    gap: 10px;
    margin-bottom: 10px;
    flex-wrap: wrap;
  }
  input, select, textarea {
    background: #0f172a;
    color: var(--text);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 8px 11px;
    font-size: 0.88rem;
    font-family: inherit;
    width: 100%;
  }
  textarea { min-height: 70px; resize: vertical; }
  label {
    display: block;
    font-size: 0.8rem;
    color: var(--muted);
    margin-bottom: 4px;
  }
  .item-list {
    display: flex;
    flex-direction: column;
    gap: 10px;
    max-height: 520px;
    overflow-y: auto;
  }
  .item {
    background: var(--panel-alt);
    border: 1px solid var(--border);
    border-radius: 9px;
    padding: 12px;
  }
  .item-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    margin-bottom: 6px;
  }
  .badge {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 999px;
    font-size: 0.74rem;
    font-weight: 600;
    background: #334155;
    color: var(--text);
  }
  .badge.supports, .badge.strong_support, .badge.moderate_support {
    background: rgba(34,197,94,0.2);
    color: #86efac;
  }
  .badge.contradicts, .badge.contradicted {
    background: rgba(239,68,68,0.2);
    color: #fca5a5;
  }
  .badge.contested {
    background: rgba(245,158,11,0.2);
    color: #fde68a;
  }
  .badge.study {
    background: rgba(168,85,247,0.2);
    color: #d8b4fe;
  }
  .tag-row {
    display: flex;
    flex-wrap: wrap;
    gap: 5px;
    margin: 6px 0 8px;
  }
  .tag {
    background: #0f172a;
    color: #7dd3fc;
    border: 1px solid var(--border);
    border-radius: 999px;
    padding: 2px 8px;
    font-size: 0.72rem;
    cursor: pointer;
  }
  .tag:hover { border-color: var(--accent); }
  .search-note { color: var(--muted); font-size: 0.8rem; margin: 2px 0 8px; }
  blockquote {
    margin: 6px 0;
    padding: 6px 12px;
    border-left: 3px solid var(--accent);
    background: rgba(15,23,42,0.55);
    color: #cbd5e1;
    font-style: italic;
    font-size: 0.85rem;
  }
  .consensus-meter {
    height: 12px;
    background: #0f172a;
    border-radius: 999px;
    overflow: hidden;
    border: 1px solid var(--border);
    margin: 8px 0 14px;
  }
  .consensus-fill {
    height: 100%;
    background: linear-gradient(90deg, var(--contradict), var(--warn), var(--support));
    transition: width 0.3s;
  }
  #toast {
    position: fixed;
    bottom: 20px;
    right: 24px;
    background: #0284c7;
    color: #fff;
    padding: 10px 16px;
    border-radius: 9px;
    font-size: 0.88rem;
    display: none;
    z-index: 999;
    box-shadow: 0 8px 24px rgba(0,0,0,0.4);
  }
  #toast.error { background: #dc2626; }
  pre.code-box {
    background: #090e1a;
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 12px;
    overflow-x: auto;
    font-size: 0.8rem;
    color: #e2e8f0;
    max-height: 300px;
  }
</style>
</head>
<body>
<header>
  <div class="brand">
    <h1>Lattice Research Studio</h1>
    <span>Provenance-First Scientific Knowledge Graph</span>
  </div>
  <div class="stats-bar">
    <div class="pill">Papers <strong id="st-papers">0</strong></div>
    <div class="pill">Claims <strong id="st-claims">0</strong></div>
    <div class="pill">Questions <strong id="st-questions">0</strong></div>
    <div class="pill">Edges <strong id="st-edges">0</strong></div>
    <div class="pill ok" id="st-gate">Gate: PASS</div>
    <button class="btn sm" onclick="loadDemo()">Load Demo Corpus</button>
    <button class="btn secondary sm" onclick="extractAllClaims()">Extract All Claims</button>
    <button class="btn secondary sm" onclick="downloadSnapshot()">Download Snapshot</button>
  </div>
</header>

<nav class="tabs">
  <button class="tab-btn active" onclick="switchTab('synthesize', this)">1. Synthesize &amp; Ask</button>
  <button class="tab-btn" onclick="switchTab('discover', this)">2. Discover &amp; Ingest</button>
  <button class="tab-btn" onclick="switchTab('curate', this)">3. Questions &amp; Claims</button>
  <button class="tab-btn" onclick="switchTab('graph', this)">4. Graph Explorer &amp; Search</button>
  <button class="tab-btn" onclick="switchTab('matrix', this); loadMatrix();">5. Evidence Matrix &amp; Contradictions</button>
</nav>

<main>
  <!-- TAB 1: SYNTHESIZE & ASK -->
  <section id="tab-synthesize" class="tab-pane active">
    <div class="grid-2">
      <div>
        <div class="card">
          <h2>Scientific Query or Research Question</h2>
          <label>Choose a tracked Research Question</label>
          <div class="form-row">
            <select id="syn-question-select" onchange="pickQuestionForSynthesis()">
              <option value="">-- Select a tracked question --</option>
            </select>
          </div>
          <label>Or enter any scientific question / topic phrase</label>
          <div class="form-row">
            <input id="syn-target" placeholder="e.g. Does slow-wave sleep consolidate memory?">
          </div>
          <div class="form-row">
            <div style="flex:1">
              <label>Token Budget</label>
              <input id="syn-tokens" type="number" value="2500" min="200" max="16000">
            </div>
            <div style="display:flex;align-items:flex-end;gap:8px">
              <button class="btn" onclick="runSynthesis()">Synthesize Evidence</button>
            </div>
          </div>
        </div>

        <div class="card">
          <h2>Tracked Research Questions</h2>
          <div id="syn-questions-list" class="item-list"></div>
        </div>
      </div>

      <div>
        <div class="card" id="syn-result-card">
          <h2>
            <span>Literature Synthesis Report</span>
            <span id="syn-consensus-badge" class="badge">Ready</span>
          </h2>
          <div id="syn-output">
            <p style="color:var(--muted)">
              Click <strong>Load Demo Corpus</strong> in the top bar or select a question on the left to generate a citation-checked scientific synthesis with consensus scoring, thematic claim clusters, verbatim quotes, and BibTeX references.
            </p>
          </div>
        </div>
      </div>
    </div>
  </section>

  <!-- TAB 2: DISCOVER & INGEST -->
  <section id="tab-discover" class="tab-pane">
    <div class="grid-2">
      <div>
        <div class="card">
          <h2>Automated Literature Discovery</h2>
          <label>Search Query</label>
          <div class="form-row">
            <input id="disc-query" value="slow-wave sleep memory consolidation" placeholder="Scientific topic, keywords, or methods">
          </div>
          <div class="form-row">
            <div style="flex:1">
              <label>Catalog Source</label>
              <select id="disc-source">
                <option value="offline">Offline Curated Corpus (Instant)</option>
                <option value="openalex">OpenAlex Live Works API</option>
                <option value="europepmc">EuropePMC Live Biomedical API</option>
                <option value="arxiv">arXiv Live Atom API</option>
                <option value="crossref">Crossref Live REST API</option>
                <option value="offline,openalex,europepmc">Federated Multi-Source Search</option>
              </select>
            </div>
            <div style="width:110px">
              <label>Max Papers</label>
              <input id="disc-limit" type="number" value="5" min="1" max="50">
            </div>
          </div>
          <button class="btn" onclick="discoverPapers()">Discover &amp; Ingest Papers</button>
        </div>

        <div class="card">
          <h2>Paste BibTeX / RIS / CSV / Markdown</h2>
          <div class="form-row">
            <select id="paste-format" style="flex:1">
              <option value="bibtex">BibTeX (.bib)</option>
              <option value="ris">RIS (.ris)</option>
              <option value="csv">CSV (.csv)</option>
              <option value="markdown">Markdown Note (.md)</option>
              <option value="text">Plain Text (.txt)</option>
            </select>
            <button class="btn secondary" onclick="ingestPastedText()">Parse &amp; Ingest</button>
          </div>
          <div class="form-row">
            <textarea id="paste-text" placeholder="Paste @article{...} BibTeX entries, RIS records, or Markdown notes here to ingest papers and automatically extract empirical claims..."></textarea>
          </div>
        </div>

        <div class="card">
          <h2>Add Paper Manually</h2>
          <div class="form-row">
            <input id="paper-title" placeholder="Paper Title (required)">
          </div>
          <div class="form-row">
            <input id="paper-authors" placeholder="Authors (e.g. Elena Vance; Marcus Chen)" style="flex:2">
            <input id="paper-year" placeholder="Year (2025)" style="flex:1">
          </div>
          <div class="form-row">
            <input id="paper-venue" placeholder="Journal / Venue" style="flex:1">
            <input id="paper-doi" placeholder="DOI (optional)" style="flex:1">
          </div>
          <div class="form-row">
            <input id="paper-study-type" list="study-type-choices"
                   placeholder="Study type (auto-detected when blank)" style="flex:1">
            <datalist id="study-type-choices">
              <option value="Meta-Analysis"></option>
              <option value="Systematic Review"></option>
              <option value="Literature Review"></option>
              <option value="Randomized Controlled Trial"></option>
              <option value="Cohort Study"></option>
              <option value="Case-Control Study"></option>
              <option value="Cross-Sectional Study"></option>
              <option value="Observational Study"></option>
              <option value="Qualitative Study"></option>
              <option value="Case Study"></option>
              <option value="Experimental Study"></option>
              <option value="In Vitro Study"></option>
              <option value="Animal Study"></option>
              <option value="Computational Study"></option>
              <option value="General Study"></option>
            </datalist>
            <input id="paper-tags" placeholder="Tags (comma separated, optional)" style="flex:1">
          </div>
          <div class="form-row">
            <textarea id="paper-abstract" placeholder="Paste abstract so Lattice can automatically extract empirical claims and quotes..."></textarea>
          </div>
          <button class="btn secondary" onclick="addPaperManual()">Save Paper</button>
        </div>
      </div>

      <div>
        <div class="card">
          <h2>
            <span>Literature Search</span>
            <span id="lit-count" class="badge">0 papers</span>
          </h2>
          <div class="form-row">
            <input id="lit-query" placeholder="Search tags, words or sentences..."
                   onkeydown="if (event.key === 'Enter') searchLiterature()">
          </div>
          <div class="form-row">
            <input id="lit-tags" placeholder="Tags (comma separated, optional)" style="flex:1.2"
                   onkeydown="if (event.key === 'Enter') searchLiterature()">
            <select id="lit-study-type" style="flex:1">
              <option value="">Any study type</option>
            </select>
            <button class="btn" onclick="searchLiterature()">Search</button>
            <button class="btn secondary" onclick="clearLiteratureSearch()">Clear</button>
          </div>
          <div class="search-note">
            Search matches title, authors, abstract, venue, DOI, tags and study type. Click a tag
            on any paper to filter by it.
          </div>
        </div>

        <div class="card">
          <h2>Ingested Papers in Graph</h2>
          <div id="papers-list" class="item-list"></div>
        </div>
      </div>
    </div>
  </section>

  <!-- TAB 3: QUESTIONS & CLAIMS -->
  <section id="tab-curate" class="tab-pane">
    <div class="grid-2">
      <div>
        <div class="card">
          <h2>Add a Research Question</h2>
          <div class="form-row">
            <input id="new-question-text" placeholder="e.g. Does spindle-oscillation coupling stabilize memory?">
            <button class="btn" onclick="createQuestion()">Add Question</button>
          </div>
        </div>

        <div class="card">
          <h2>Record a Quote-Backed Claim</h2>
          <label>Source Paper</label>
          <div class="form-row">
            <select id="claim-paper"></select>
          </div>
          <label>Asserted Claim</label>
          <div class="form-row">
            <input id="claim-text" placeholder="Concise empirical assertion">
          </div>
          <label>Verbatim Quote from Paper (Required for Provenance)</label>
          <div class="form-row">
            <textarea id="claim-quote" placeholder="Exact sentence from the paper supporting this claim"></textarea>
          </div>
          <div class="form-row">
            <div style="flex:1">
              <label>Stance</label>
              <select id="claim-stance">
                <option value="supports">supports</option>
                <option value="contradicts">contradicts</option>
                <option value="mentions">mentions</option>
              </select>
            </div>
            <div style="flex:1">
              <label>Confidence (0.0 - 1.0)</label>
              <input id="claim-conf" type="number" step="0.05" min="0" max="1" value="0.85">
            </div>
            <div style="flex:1">
              <label>Locator</label>
              <input id="claim-locator" placeholder="p. 4 / abstract:s1">
            </div>
          </div>
          <label>Link to Research Question (Optional)</label>
          <div class="form-row">
            <select id="claim-question">
              <option value="">-- Optional: auto-link to question --</option>
            </select>
          </div>
          <button class="btn" onclick="createClaim()">Record Grounded Claim</button>
        </div>
      </div>

      <div>
        <div class="card">
          <h2>Recorded Quote-Backed Claims</h2>
          <div id="claims-list" class="item-list"></div>
        </div>
      </div>
    </div>
  </section>

  <!-- TAB 4: GRAPH EXPLORER & SEARCH -->
  <section id="tab-graph" class="tab-pane">
    <div class="grid-2">
      <div>
        <div class="card">
          <h2>Multi-Hop Subgraph Explorer</h2>
          <div class="form-row">
            <input id="graph-ref" placeholder="Entity ID (e.g. q_000001, c_000001, p_xxx)" style="flex:2">
            <select id="graph-depth" style="flex:1">
              <option value="1">Depth 1</option>
              <option value="2" selected>Depth 2</option>
              <option value="3">Depth 3</option>
            </select>
            <button class="btn" onclick="loadSubgraph()">Render Graph</button>
          </div>
          <p style="font-size:0.8rem;color:var(--muted);margin:4px 0 0">
            Click any node in the diagram to recenter the neighborhood around it.
          </p>
        </div>

        <div class="card">
          <h2>Filtered Knowledge Search</h2>
          <div class="form-row">
            <input id="search-query" placeholder="Search papers, claims, quotes, DOIs...">
          </div>
          <div class="form-row">
            <select id="search-stance" style="flex:1">
              <option value="">Any stance</option>
              <option value="supports">supports</option>
              <option value="contradicts">contradicts</option>
              <option value="mentions">mentions</option>
            </select>
            <input id="search-conf" type="number" step="0.1" min="0" max="1" placeholder="Min confidence" style="flex:1">
            <input id="search-year" placeholder="Year" style="flex:1">
            <button class="btn secondary" onclick="runSearch()">Search</button>
          </div>
          <div id="search-results" class="item-list"></div>
        </div>
      </div>

      <div>
        <div class="card">
          <h2>Interactive Provenance Subgraph</h2>
          <div id="svg-container" style="background:#090e1a;border:1px solid var(--border);border-radius:10px;min-height:420px;display:flex;align-items:center;justify-content:center;overflow:hidden">
            <span style="color:var(--muted);font-size:0.88rem">Select an entity to visualize its connected claims, papers, and questions.</span>
          </div>
        </div>
      </div>
    </div>
  </section>

  <!-- TAB 5: EVIDENCE MATRIX & CONTRADICTIONS -->
  <section id="tab-matrix" class="tab-pane">
    <div class="grid-2">
      <div>
        <div class="card">
          <h2>
            <span>Contradiction Detector</span>
            <button class="btn sm" onclick="autoLinkContradictions()">Auto-Link Contradictions</button>
          </h2>
          <div id="contradictions-list" class="item-list"></div>
        </div>

        <div class="card">
          <h2>Keystone Papers &amp; Claims (Centrality)</h2>
          <div id="keystone-list" class="item-list"></div>
        </div>
      </div>

      <div>
        <div class="card">
          <h2>Paper &times; Question Evidence Matrix</h2>
          <div id="matrix-output"></div>
        </div>
      </div>
    </div>
  </section>
</main>

<div id="toast"></div>

<script>
let STATE = { papers: [], questions: [], claims: [], edges: [] };

function notify(msg, isError) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.className = isError ? 'error' : '';
  el.style.display = 'block';
  clearTimeout(window._toastTimer);
  window._toastTimer = setTimeout(() => { el.style.display = 'none'; }, 3500);
}

function switchTab(name, btn) {
  document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('tab-' + name).classList.add('active');
  if (btn) btn.classList.add('active');
}

async function api(method, path, body) {
  const opts = { method, headers: { 'Content-Type': 'application/json' } };
  if (body !== undefined) opts.body = JSON.stringify(body);
  const res = await fetch(path, opts);
  const data = await res.json();
  if (!res.ok) throw new Error(data.message || data.error || 'Request failed');
  return data;
}

function esc(str) {
  return String(str || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

async function refreshOverview() {
  const data = await api('GET', '/api/overview');
  STATE = data;
  document.getElementById('st-papers').textContent = data.stats.papers;
  document.getElementById('st-claims').textContent = data.stats.claims;
  document.getElementById('st-questions').textContent = data.stats.questions;
  document.getElementById('st-edges').textContent = data.stats.edges;
  const gate = document.getElementById('st-gate');
  gate.textContent = data.check.passed ? 'Gate: PASS' : ('Gate: ' + data.check.errors.length + ' ERR');
  gate.className = 'pill ' + (data.check.passed ? 'ok' : 'fail');

  renderQuestions(data.questions);
  renderPaperOptions(data.papers);
  renderStudyTypeOptions(data.study_types || []);
  const literatureFiltered = ['lit-query', 'lit-tags', 'lit-study-type'].some(
    id => document.getElementById(id).value.trim());
  if (literatureFiltered) {
    await searchLiterature(true);
  } else {
    renderPapers(data.papers, data.papers.length);
  }
  renderClaims(data.claims);
}

function renderQuestions(questions) {
  const sel = document.getElementById('syn-question-select');
  const claimQ = document.getElementById('claim-question');
  const current = sel.value;
  sel.innerHTML = '<option value="">-- Select a tracked question --</option>' +
    questions.map(q => `<option value="${esc(q.id)}">[${esc(q.id)}] ${esc(q.text)} (${esc(q.status)})</option>`).join('');
  if (current) sel.value = current;

  claimQ.innerHTML = '<option value="">-- Optional: auto-link to question --</option>' +
    questions.map(q => `<option value="${esc(q.id)}">[${esc(q.id)}] ${esc(q.text)}</option>`).join('');

  const list = document.getElementById('syn-questions-list');
  if (!questions.length) {
    list.innerHTML = '<div style="color:var(--muted);font-size:0.85rem">No questions yet. Click <strong>Load Demo Corpus</strong> above!</div>';
    return;
  }
  list.innerHTML = questions.map(q => `
    <div class="item">
      <div class="item-header">
        <strong>[${esc(q.id)}] ${esc(q.text)}</strong>
        <span class="badge">${esc(q.status)}</span>
      </div>
      <div style="display:flex;gap:6px;margin-top:8px">
        <button class="btn sm" onclick="synthesizeQuestion('${esc(q.id)}')">Synthesize</button>
        <button class="btn secondary sm" onclick="inspectGraph('${esc(q.id)}')">Graph</button>
        <button class="btn secondary sm" onclick="setQuestionStatus('${esc(q.id)}', '${q.status === 'open' ? 'answered' : 'open'}')">
          Mark ${q.status === 'open' ? 'Answered' : 'Open'}
        </button>
      </div>
    </div>
  `).join('');
}

function renderPaperOptions(papers) {
  const sel = document.getElementById('claim-paper');
  sel.innerHTML = papers.map(p => `<option value="${esc(p.id)}">[${esc(p.id)}] ${esc(p.title)} (${esc(p.year || 'n.d.')})</option>`).join('');
}

function renderStudyTypeOptions(studyTypes) {
  const sel = document.getElementById('lit-study-type');
  const current = sel.value;
  const options = (studyTypes || []).map(type =>
    `<option value="${esc(type)}">${esc(type)}</option>`).join('');
  sel.innerHTML = '<option value="">Any study type</option>' + options;
  if (current) sel.value = current;
}

function paperTags(p) {
  return String(p.tags || '').split(',').map(tag => tag.trim()).filter(Boolean);
}

function renderPapers(papers, total) {
  const list = document.getElementById('papers-list');
  const counter = document.getElementById('lit-count');
  const shown = total === undefined ? papers.length : total;
  if (counter) counter.textContent = `${shown} paper${shown === 1 ? '' : 's'}`;
  if (!papers.length) {
    list.innerHTML = '<div style="color:var(--muted);font-size:0.85rem">No papers matched the search.</div>';
    return;
  }
  list.innerHTML = papers.map(p => {
    const tags = paperTags(p);
    return `
    <div class="item">
      <div class="item-header">
        <strong>${esc(p.title)}</strong>
        <span>
          <span class="badge study">${esc(p.study_type || 'General Study')}</span>
          <span class="badge">${esc(p.year || 'n.d.')}</span>
        </span>
      </div>
      <div style="font-size:0.8rem;color:var(--muted);margin-bottom:6px">
        <code>${esc(p.id)}</code> &middot; ${esc(p.authors || 'Unknown authors')}
        ${p.venue ? ' &middot; <em>' + esc(p.venue) + '</em>' : ''}
        ${p.doi ? ' &middot; doi:' + esc(p.doi) : ''}
      </div>
      ${tags.length ? `<div class="tag-row">${tags.map(tag =>
        `<button class="tag" onclick="filterByTag('${esc(tag)}')">${esc(tag)}</button>`).join('')}</div>` : ''}
      ${p.abstract ? `<div style="font-size:0.83rem;color:#cbd5e1;margin-bottom:8px">${esc(p.abstract)}</div>` : ''}
      <div style="display:flex;gap:6px">
        <button class="btn secondary sm" onclick="extractPaper('${esc(p.id)}')">Extract Claims</button>
        <button class="btn secondary sm" onclick="inspectGraph('${esc(p.id)}')">Subgraph</button>
      </div>
    </div>
  `; }).join('');
}

async function searchLiterature(silent) {
  const q = document.getElementById('lit-query').value.trim();
  const tags = document.getElementById('lit-tags').value.trim();
  const studyType = document.getElementById('lit-study-type').value;
  try {
    const params = new URLSearchParams();
    if (q) params.set('q', q);
    if (tags) params.set('tags', tags);
    if (studyType) params.set('study_type', studyType);
    const res = await api('GET', '/api/literature?' + params.toString());
    renderPapers(res.papers, res.total);
    if (!res.total && !silent) notify('No papers matched the literature search', true);
  } catch (err) {
    notify(err.message, true);
  }
}

function filterByTag(tag) {
  document.getElementById('lit-query').value = '';
  document.getElementById('lit-tags').value = tag;
  searchLiterature();
}

function clearLiteratureSearch() {
  document.getElementById('lit-query').value = '';
  document.getElementById('lit-tags').value = '';
  document.getElementById('lit-study-type').value = '';
  searchLiterature();
}

function renderClaims(claims) {
  const list = document.getElementById('claims-list');
  if (!claims.length) {
    list.innerHTML = '<div style="color:var(--muted);font-size:0.85rem">No claims recorded yet.</div>';
    return;
  }
  list.innerHTML = claims.map(c => `
    <div class="item">
      <div class="item-header">
        <span><code>${esc(c.id)}</code> &rarr; <code>${esc(c.paper_id)}</code></span>
        <span>
          <span class="badge ${esc(c.stance)}">${esc(c.stance)}</span>
          <span class="badge">conf ${Number(c.confidence).toFixed(2)}</span>
        </span>
      </div>
      <div style="font-size:0.88rem;font-weight:500">${esc(c.text)}</div>
      <blockquote>&ldquo;${esc(c.quote)}&rdquo; ${c.locator ? `<span style="color:var(--muted)">(${esc(c.locator)})</span>` : ''}</blockquote>
      <button class="btn secondary sm" onclick="inspectGraph('${esc(c.id)}')">Subgraph</button>
    </div>
  `).join('');
}

function pickQuestionForSynthesis() {
  const val = document.getElementById('syn-question-select').value;
  if (val) {
    document.getElementById('syn-target').value = val;
    runSynthesis();
  }
}

function synthesizeQuestion(qid) {
  document.getElementById('syn-target').value = qid;
  document.getElementById('syn-question-select').value = qid;
  switchTab('synthesize', document.querySelectorAll('.tab-btn')[0]);
  runSynthesis();
}

async function runSynthesis() {
  const target = document.getElementById('syn-target').value.trim();
  const tokens = document.getElementById('syn-tokens').value || 2500;
  if (!target) {
    notify('Select a question or enter a scientific query first', true);
    return;
  }
  try {
    const syn = await api('GET', `/api/synthesize?target=${encodeURIComponent(target)}&tokens=${encodeURIComponent(tokens)}`);
    const badge = document.getElementById('syn-consensus-badge');
    badge.textContent = `${syn.consensus.label} (${syn.consensus.score >= 0 ? '+' : ''}${syn.consensus.score})`;
    badge.className = 'badge ' + syn.consensus.label;

    const pct = Math.round(((syn.consensus.score + 1) / 2) * 100);
    const clustersHtml = (syn.clusters || []).map(cl => `
      <div style="margin-bottom:14px">
        <div style="font-weight:600;color:var(--accent);margin-bottom:6px">
          Theme: ${esc(cl.theme)} (${cl.claim_count} claim${cl.claim_count === 1 ? '' : 's'})
        </div>
        ${cl.claims.map(c => `
          <div class="item" style="margin-bottom:8px">
            <div class="item-header">
              <span><code>${esc(c.id)}</code> &middot; <em>${esc(c.citation)}</em></span>
              <span>
                <span class="badge ${esc(c.stance)}">${esc(c.stance)}</span>
                <span class="badge">conf ${Number(c.confidence).toFixed(2)}</span>
              </span>
            </div>
            <div>${esc(c.text)}</div>
            <blockquote>&ldquo;${esc(c.quote)}&rdquo;</blockquote>
          </div>
        `).join('')}
      </div>
    `).join('') || '<p style="color:var(--muted)">No quote-backed claims matched yet.</p>';

    const followHtml = (syn.follow_up_queries || []).map(q =>
      `<li><a href="#" style="color:var(--accent)" onclick="document.getElementById('syn-target').value='${esc(q)}';runSynthesis();return false;">${esc(q)}</a></li>`
    ).join('');

    document.getElementById('syn-output').innerHTML = `
      <div style="font-size:0.86rem;color:var(--muted)">
        Query: <strong style="color:var(--text)">${esc(syn.query_text)}</strong> &middot;
        Supporting: <strong>${syn.consensus.supporting_count}</strong> &middot;
        Contradicting: <strong>${syn.consensus.contradicting_count}</strong> &middot;
        Sources: <strong>${syn.bibliography.length}</strong>
      </div>
      <div class="consensus-meter"><div class="consensus-fill" style="width:${pct}%"></div></div>
      ${clustersHtml}
      <h3 style="font-size:0.92rem;margin:14px 0 6px">Follow-Up Scientific Queries</h3>
      <ul style="margin:0 0 14px;padding-left:20px;font-size:0.85rem">${followHtml}</ul>
      <details>
        <summary style="cursor:pointer;color:var(--accent);font-size:0.86rem;font-weight:600">Markdown Synthesis &amp; BibTeX Citations</summary>
        <pre class="code-box">${esc(syn.markdown)}</pre>
        <pre class="code-box">${esc(syn.bibtex)}</pre>
      </details>
    `;
  } catch (err) {
    notify(err.message, true);
  }
}

async function loadDemo() {
  try {
    const res = await api('POST', '/api/demo', {});
    await refreshOverview();
    notify(`Loaded demo corpus (${res.stats.papers} papers, ${res.stats.claims} claims)`);
    if (res.seeded_questions && res.seeded_questions[0]) {
      synthesizeQuestion(res.seeded_questions[0]);
    }
  } catch (err) {
    notify(err.message, true);
  }
}

async function extractAllClaims() {
  try {
    const res = await api('POST', '/api/extract', { all: true });
    await refreshOverview();
    notify(`Extracted ${res.claims_created} new claim(s) and ${res.edges_created} link(s)`);
  } catch (err) {
    notify(err.message, true);
  }
}

async function extractPaper(pid) {
  try {
    const res = await api('POST', '/api/extract', { paper: pid });
    await refreshOverview();
    notify(`Extracted ${res.claims_created} claim(s) from ${pid}`);
  } catch (err) {
    notify(err.message, true);
  }
}

async function discoverPapers() {
  const query = document.getElementById('disc-query').value.trim();
  const source = document.getElementById('disc-source').value;
  const limit = Number(document.getElementById('disc-limit').value || 5);
  try {
    const res = await api('POST', '/api/discover', { query, source, limit, ingest: true });
    await refreshOverview();
    notify(`Discovered ${res.count} paper(s) from ${source} (${res.created} new)`);
  } catch (err) {
    notify(err.message, true);
  }
}

async function addPaperManual() {
  const title = document.getElementById('paper-title').value.trim();
  const authors = document.getElementById('paper-authors').value.trim();
  const year = document.getElementById('paper-year').value.trim();
  const venue = document.getElementById('paper-venue').value.trim();
  const doi = document.getElementById('paper-doi').value.trim();
  const abstract = document.getElementById('paper-abstract').value.trim();
  const study_type = document.getElementById('paper-study-type').value.trim();
  const tags = document.getElementById('paper-tags').value.trim();
  try {
    const res = await api('POST', '/api/papers',
      { title, authors, year, venue, doi, abstract, study_type, tags });
    document.getElementById('paper-title').value = '';
    document.getElementById('paper-abstract').value = '';
    document.getElementById('paper-study-type').value = '';
    document.getElementById('paper-tags').value = '';
    await refreshOverview();
    notify(`Saved paper ${res.paper.id}`);
  } catch (err) {
    notify(err.message, true);
  }
}

async function createQuestion() {
  const text = document.getElementById('new-question-text').value.trim();
  try {
    const res = await api('POST', '/api/questions', { text });
    document.getElementById('new-question-text').value = '';
    await refreshOverview();
    notify(`Added question ${res.question.id}`);
  } catch (err) {
    notify(err.message, true);
  }
}

async function setQuestionStatus(question, status) {
  try {
    await api('POST', '/api/question-status', { question, status });
    await refreshOverview();
    notify(`Updated ${question} to ${status}`);
  } catch (err) {
    notify(err.message, true);
  }
}

async function createClaim() {
  const paper = document.getElementById('claim-paper').value;
  const text = document.getElementById('claim-text').value.trim();
  const quote = document.getElementById('claim-quote').value.trim();
  const stance = document.getElementById('claim-stance').value;
  const confidence = Number(document.getElementById('claim-conf').value || 0.8);
  const locator = document.getElementById('claim-locator').value.trim();
  const question = document.getElementById('claim-question').value;
  try {
    const res = await api('POST', '/api/claims', { paper, text, quote, stance, confidence, locator, question });
    document.getElementById('claim-text').value = '';
    document.getElementById('claim-quote').value = '';
    await refreshOverview();
    notify(`Recorded claim ${res.claim.id}`);
  } catch (err) {
    notify(err.message, true);
  }
}

function inspectGraph(ref) {
  document.getElementById('graph-ref').value = ref;
  switchTab('graph', document.querySelectorAll('.tab-btn')[3]);
  loadSubgraph();
}

async function loadSubgraph() {
  const ref = document.getElementById('graph-ref').value.trim();
  const depth = document.getElementById('graph-depth').value || 2;
  if (!ref) {
    notify('Enter an entity ID (e.g. q_000001) to render its subgraph', true);
    return;
  }
  try {
    const data = await api('GET', `/api/subgraph?ref=${encodeURIComponent(ref)}&depth=${encodeURIComponent(depth)}`);
    renderSvgGraph(data);
  } catch (err) {
    notify(err.message, true);
  }
}

function renderSvgGraph(data) {
  const container = document.getElementById('svg-container');
  const nodes = data.nodes || [];
  const edges = data.edges || [];
  if (!nodes.length) {
    container.innerHTML = '<span style="color:var(--muted)">No nodes found.</span>';
    return;
  }
  const width = 680, height = 420, cx = width / 2, cy = height / 2;
  const positions = {};
  nodes.forEach((n, i) => {
    if (n.ref === data.root) {
      positions[n.ref] = { x: cx, y: cy };
    } else {
      const angle = (2 * Math.PI * i) / Math.max(1, nodes.length - 1);
      const radius = nodes.length > 6 ? 155 : 130;
      positions[n.ref] = {
        x: Math.round(cx + radius * Math.cos(angle)),
        y: Math.round(cy + radius * Math.sin(angle))
      };
    }
  });
  const colors = { question: '#a855f7', claim: '#22c55e', paper: '#38bdf8' };
  const edgeLines = edges.map(e => {
    const p1 = positions[e.src] || { x: cx, y: cy };
    const p2 = positions[e.dst] || { x: cx, y: cy };
    const mx = Math.round((p1.x + p2.x) / 2);
    const my = Math.round((p1.y + p2.y) / 2);
    return `<line x1="${p1.x}" y1="${p1.y}" x2="${p2.x}" y2="${p2.y}" stroke="#475569" stroke-width="2"/>
            <text x="${mx}" y="${my - 4}" fill="#94a3b8" font-size="10" text-anchor="middle">${esc(e.kind)}</text>`;
  }).join('');
  const nodeCircles = nodes.map(n => {
    const pos = positions[n.ref];
    const color = colors[n.type] || '#64748b';
    const shortId = n.id || n.ref;
    const title = (n.title || n.text || shortId).slice(0, 26);
    const studyType = n.study_type || (n.paper && n.paper.study_type) || '';
    const studyLabel = n.type === 'claim' && studyType ? `via ${studyType}` : studyType;
    return `<g style="cursor:pointer" onclick="inspectGraph('${esc(n.ref)}')">
      <circle cx="${pos.x}" cy="${pos.y}" r="20" fill="${color}" stroke="#0f172a" stroke-width="3"/>
      <text x="${pos.x}" y="${pos.y + 4}" fill="#0f172a" font-size="10" font-weight="700" text-anchor="middle">${esc(shortId)}</text>
      <text x="${pos.x}" y="${pos.y + 34}" fill="#e2e8f0" font-size="11" text-anchor="middle">${esc(title)}</text>
      ${studyLabel ? `<text x="${pos.x}" y="${pos.y + 47}" fill="#c4b5fd" font-size="9" text-anchor="middle">${esc(studyLabel.slice(0, 30))}</text>` : ''}
    </g>`;
  }).join('');
  container.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${width} ${height}" width="100%" height="420">${edgeLines}${nodeCircles}</svg>`;
}

async function runSearch() {
  const q = document.getElementById('search-query').value.trim();
  const stance = document.getElementById('search-stance').value;
  const conf = document.getElementById('search-conf').value;
  const year = document.getElementById('search-year').value.trim();
  if (!q) {
    notify('Enter a search query first', true);
    return;
  }
  try {
    const params = new URLSearchParams({ q });
    if (stance) params.set('stance', stance);
    if (conf) params.set('min_confidence', conf);
    if (year) params.set('year', year);
    const res = await api('GET', '/api/search?' + params.toString());
    const box = document.getElementById('search-results');
    const items = [];
    (res.papers || []).forEach(p => items.push(
      `<div class="item"><strong>[Paper ${esc(p.id)}]</strong> ${esc(p.title)} (${esc(p.year || 'n.d.')})
       <span class="badge study">${esc(p.study_type || 'General Study')}</span></div>`));
    (res.claims || []).forEach(c => items.push(`<div class="item"><strong>[Claim ${esc(c.id)}]</strong> <span class="badge ${esc(c.stance)}">${esc(c.stance)}</span> ${esc(c.text)}</div>`));
    (res.questions || []).forEach(qu => items.push(`<div class="item"><strong>[Question ${esc(qu.id)}]</strong> ${esc(qu.text)}</div>`));
    box.innerHTML = items.join('') || '<div style="color:var(--muted)">No matching entities.</div>';
  } catch (err) {
    notify(err.message, true);
  }
}

async function ingestPastedText() {
  const fmt = document.getElementById('paste-format').value;
  const text = document.getElementById('paste-text').value.trim();
  if (!text) {
    notify('Paste BibTeX, RIS, CSV, or Markdown text first', true);
    return;
  }
  try {
    const res = await api('POST', '/api/ingest-text', { format: fmt, text, extract: true });
    document.getElementById('paste-text').value = '';
    notify(`Ingested ${res.ingested} paper(s) and extracted ${res.claims_created} claim(s)`);
    await refreshOverview();
  } catch (err) {
    notify(err.message, true);
  }
}

async function downloadSnapshot() {
  try {
    const res = await fetch('/api/export');
    const text = await res.text();
    const blob = new Blob([text], { type: 'application/x-ndjson' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'lattice_snapshot.jsonl';
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    notify('Snapshot downloaded (lattice_snapshot.jsonl)');
  } catch (err) {
    notify(err.message, true);
  }
}

async function loadMatrix() {
  try {
    const data = await api('GET', '/api/matrix');
    const cBox = document.getElementById('contradictions-list');
    const pairs = data.contradictions || [];
    cBox.innerHTML = pairs.map(p => `
      <div class="item">
        <div style="display:flex;justify-content:space-between;margin-bottom:4px">
          <strong>${esc(p.claim_a_id)} vs ${esc(p.claim_b_id)}</strong>
          <span class="badge contradicts">Score: ${esc(p.score)}</span>
        </div>
        <div style="font-size:0.82rem;color:#86efac">+ ${esc(p.claim_a_text)}</div>
        <div style="font-size:0.82rem;color:#fca5a5">- ${esc(p.claim_b_text)}</div>
        <div style="font-size:0.75rem;color:var(--muted);margin-top:4px">
          Shared keywords: ${esc((p.shared_keywords || []).join(', ') || 'question link')}
          ${p.linked_edge_id ? ' • <span style="color:#38bdf8">Linked (edge #' + esc(p.linked_edge_id) + ')</span>' : ''}
        </div>
      </div>
    `).join('') || '<div style="color:var(--muted)">No opposing claim pairs detected yet.</div>';

    const kBox = document.getElementById('keystone-list');
    const kp = (data.keystone && data.keystone.papers) || [];
    kBox.innerHTML = kp.map(p => `
      <div class="item">
        <div style="display:flex;justify-content:space-between">
          <strong>[${esc(p.id)}] ${esc(p.title)}</strong>
          <span>
            <span class="badge study">${esc(p.study_type || 'General Study')}</span>
            <span class="badge">Centrality: ${esc(p.score)}</span>
          </span>
        </div>
        <div style="font-size:0.78rem;color:var(--muted)">
          ${esc(p.authors)} (${esc(p.year || 'n.d.')}) • Claims: ${esc(p.claim_count)} • Citations: ${esc(p.citation_count)}
        </div>
      </div>
    `).join('') || '<div style="color:var(--muted)">No papers ranked yet.</div>';

    const mBox = document.getElementById('matrix-output');
    const mat = data.matrix || { papers: [], questions: [], cells: [], gaps: [] };
    const cellMap = {};
    (mat.cells || []).forEach(c => { cellMap[c.paper_id + '::' + c.question_id] = c; });
    if (!mat.questions.length || !mat.papers.length) {
      mBox.innerHTML = '<div style="color:var(--muted)">Add papers and questions (or click Load Demo Corpus) to view the Paper &times; Question matrix.</div>';
      return;
    }
    const headers = mat.questions.map(q => `<th style="padding:8px;border-bottom:1px solid var(--border);text-align:left;font-size:0.78rem">${esc(q.id)}: ${esc(q.prompt.slice(0, 42))}...</th>`).join('');
    const rows = mat.papers.map(p => {
      const cols = mat.questions.map(q => {
        const cell = cellMap[p.id + '::' + q.id];
        if (!cell) return '<td style="padding:8px;border-bottom:1px solid var(--border);color:var(--muted);font-size:0.78rem">—</td>';
        return `<td style="padding:8px;border-bottom:1px solid var(--border)"><span class="badge ${esc(cell.dominant_stance)}">${esc(cell.dominant_stance)} (${esc(cell.claim_ids.length)})</span></td>`;
      }).join('');
      return `<tr><td style="padding:8px;border-bottom:1px solid var(--border);font-size:0.82rem"><strong>${esc(p.id)}</strong> ${esc(p.title.slice(0, 38))} <span class="badge study">${esc(p.study_type || 'General Study')}</span></td>${cols}</tr>`;
    }).join('');
    const gapsHtml = (mat.gaps || []).map(g => `<div style="font-size:0.8rem;color:#fbbf24;margin-top:4px">⚠ <strong>${esc(g.question_id)}</strong>: ${esc(g.reason)}</div>`).join('');
    mBox.innerHTML = `<div style="overflow-x:auto"><table style="width:100%;border-collapse:collapse"><thead><tr><th style="padding:8px;border-bottom:1px solid var(--border);text-align:left;font-size:0.78rem">Paper</th>${headers}</tr></thead><tbody>${rows}</tbody></table></div><div style="margin-top:10px">${gapsHtml}</div>`;
  } catch (err) {
    notify(err.message, true);
  }
}

async function autoLinkContradictions() {
  try {
    const res = await api('POST', '/api/detect-contradictions', { auto_link: true });
    notify(`Linked ${res.count} contradiction pair(s) in the knowledge graph`);
    await refreshOverview();
    await loadMatrix();
  } catch (err) {
    notify(err.message, true);
  }
}

refreshOverview();
</script>
</body>
</html>
"""

