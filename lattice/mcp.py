"""A dependency-free MCP stdio server exposing the graph as JSON-RPC tools."""

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, TextIO

from lattice import __version__
from lattice.analysis import (
    build_evidence_matrix,
    detect_contradictions,
    find_related_findings,
    link_related_findings,
    rank_influential_entities,
    related_findings,
)
from lattice.context import compact_related, compact_search, compact_subgraph, outline
from lattice.discovery import DiscoveryService
from lattice.errors import LatticeError, fail
from lattice.extraction import extract_all, extract_from_paper
from lattice.inquiry import brief, review
from lattice.repository import Repository
from lattice.snapshots import export_snapshot, import_snapshot
from lattice.synthesis import synthesize

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "lattice"


def _tool(name: str, description: str, properties: Dict[str, Any],
          required: List[str]) -> Dict[str, Any]:
    """An MCP tool declaration with a JSON Schema for its arguments."""
    return {"name": name, "description": description,
            "inputSchema": {"type": "object", "properties": properties, "required": required}}


TOOLS: List[Dict[str, Any]] = [
    _tool("search", "Search papers, claims and questions by phrase or multi-term overlap; "
          "returns compact refs, snippets and omitted counts under a token budget.",
          {"query": {"type": "string"}, "limit": {"type": "integer", "default": 20},
           "stance": {"type": "string"}, "min_confidence": {"type": "number"},
           "year": {"type": "string"}, "tokens": {"type": "integer", "default": 800}},
          ["query"]),
    _tool("discover_papers", "Search offline, arXiv, Crossref, OpenAlex, or EuropePMC catalogs and ingest papers.",
          {"query": {"type": "string"}, "source": {"type": "string", "default": "offline"},
           "limit": {"type": "integer", "default": 10},
           "ingest": {"type": "boolean", "default": True}}, ["query"]),
    _tool("extract_claims", "Extract quote-backed claims and edges from one or all papers.",
          {"paper": {"type": "string"}, "question": {"type": "string"}}, []),
    _tool("get_entity", "Fetch one paper, claim or question with all attached edges.",
          {"ref": {"type": "string"}}, ["ref"]),
    _tool("neighbors", "List edges touching an entity, optionally filtered by kind.",
          {"ref": {"type": "string"}, "kind": {"type": "string"}}, ["ref"]),
    _tool("subgraph", "Traverse the multi-hop neighborhood (depth 1-3) around an entity as "
          "compact refs and bare edges under a token budget; omitted nodes are reported.",
          {"ref": {"type": "string"}, "depth": {"type": "integer", "default": 1},
           "tokens": {"type": "integer", "default": 800}}, ["ref"]),
    _tool("related_findings", "List findings connected to a claim, paper or question with the "
          "relation, reason and next-hop ref; snippets are budgeted and omissions reported.",
          {"target": {"type": "string"}, "limit": {"type": "integer", "default": 10},
           "tokens": {"type": "integer", "default": 600}}, ["target"]),
    _tool("outline", "Cheap orientation map: counts, edge kinds, study-type mix and evidenced "
          "question refs, so an agent can choose where to expand next.",
          {"tokens": {"type": "integer", "default": 400}}, []),
    _tool("add_paper", "Ingest one paper; duplicate DOIs, arXiv IDs and titles are merged.",
          {"title": {"type": "string"}, "authors": {"type": "string"},
           "year": {"type": "string"}, "venue": {"type": "string"}, "doi": {"type": "string"},
           "arxiv": {"type": "string"}, "url": {"type": "string"},
           "abstract": {"type": "string"}, "tags": {"type": "string"},
           "study_type": {"type": "string"}}, ["title"]),
    _tool("add_claim", "Record a claim with the exact quote that grounds it.",
          {"paper": {"type": "string"}, "text": {"type": "string"},
           "quote": {"type": "string"}, "locator": {"type": "string"},
           "stance": {"type": "string"}, "confidence": {"type": "number"}},
          ["paper", "text", "quote"]),
    _tool("add_question", "Record a research question.",
          {"text": {"type": "string"}}, ["text"]),
    _tool("set_question_status", "Update a question status to open, answered or abandoned.",
          {"question": {"type": "string"}, "status": {"type": "string"}}, ["question", "status"]),
    _tool("add_edge", "Add a typed relation between two entities.",
          {"src": {"type": "string"}, "dst": {"type": "string"},
           "kind": {"type": "string"}, "note": {"type": "string"}}, ["src", "dst", "kind"]),
    _tool("brief", "Token-budgeted evidence pack for a question or search phrase.",
          {"target": {"type": "string"}, "tokens": {"type": "integer", "default": 2000}},
          ["target"]),
    _tool("review", "Markdown literature-review outline for a question or phrase.",
          {"target": {"type": "string"}}, ["target"]),
    _tool("synthesize", "Consensus-scored scientific literature synthesis with clusters and BibTeX.",
          {"target": {"type": "string"}, "tokens": {"type": "integer", "default": 2500}},
          ["target"]),
    _tool("analyze_graph", "Detect contradictions and related findings, rank keystone papers/claims, and build the Paper x Question matrix.",
          {"auto_link": {"type": "boolean", "default": False},
           "limit": {"type": "integer", "default": 10}}, []),
    _tool("detect_contradictions", "Find opposing claims across shared questions or domain keywords.",
          {"auto_link": {"type": "boolean", "default": False}}, []),
    _tool("export_snapshot", "Export the graph to an atomic JSONL snapshot file.",
          {"path": {"type": "string"}}, ["path"]),
    _tool("import_snapshot", "Import a JSONL snapshot file idempotently.",
          {"path": {"type": "string"}}, ["path"]),
    _tool("stats", "Entity and edge counts.", {}, []),
]

RESOURCES: List[Dict[str, Any]] = [
    {"uri": "lattice://stats", "name": "Graph Statistics",
     "description": "Counts of papers, claims, questions and typed edges.",
     "mimeType": "application/json"},
    {"uri": "lattice://questions", "name": "Research Questions",
     "description": "All tracked research questions and their status.",
     "mimeType": "application/json"},
    {"uri": "lattice://matrix", "name": "Paper x Question Evidence Matrix",
     "description": "Structured Paper x Question evidence matrix and coverage gaps.",
     "mimeType": "application/json"},
]

PROMPTS: List[Dict[str, Any]] = [
    {"name": "literature-synthesis",
     "description": "Assemble a citation-checked scientific synthesis for a research question or query.",
     "arguments": [{"name": "target", "description": "Question ID or scientific query", "required": True}]},
]


def handle_message(repository: Repository, message: Any) -> Optional[Dict[str, Any]]:
    """Dispatch one JSON-RPC message; notifications return None."""
    if not isinstance(message, dict) or not isinstance(message.get("method"), str):
        return _error(None, -32600, "invalid request")
    request_id = message.get("id")
    method = message["method"]
    params = message.get("params")
    if params is None:
        params = {}
    if method == "initialize":
        return _result(request_id, {
            "protocolVersion": PROTOCOL_VERSION,
            "serverInfo": {"name": SERVER_NAME, "version": __version__},
            "capabilities": {"tools": {}, "resources": {}, "prompts": {}},
        })
    if method in ("notifications/initialized", "initialized", "shutdown"):
        return None
    if method == "ping":
        return _result(request_id, {})
    if method == "tools/list":
        return _result(request_id, {"tools": TOOLS})
    if method == "tools/call":
        return _call_tool(repository, request_id, params)
    if method == "resources/list":
        return _result(request_id, {"resources": RESOURCES})
    if method == "resources/read":
        return _read_resource(repository, request_id, params)
    if method == "prompts/list":
        return _result(request_id, {"prompts": PROMPTS})
    if method == "prompts/get":
        return _get_prompt(repository, request_id, params)
    return _error(request_id, -32601, f"method not found: {method}")


def _call_tool(repository: Repository, request_id: Any, params: Any) -> Dict[str, Any]:
    """Run one MCP tool call and wrap the result as text content."""
    if not isinstance(params, dict) or not isinstance(params.get("name"), str) \
            or not params["name"].strip():
        return _error(request_id, -32602, "tools/call needs a tool name")
    name = params["name"]
    arguments = params.get("arguments")
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        return _error(request_id, -32602, "arguments must be an object")
    try:
        payload = dispatch_tool(repository, name, arguments)
    except LatticeError as exc:
        return _result(request_id, {"content": [{"type": "text", "text": exc.render()}],
                                    "isError": True})
    except (TypeError, ValueError) as exc:
        return _error(request_id, -32602, str(exc))
    return _result(request_id, {"content": [{"type": "text",
                                             "text": json.dumps(payload, indent=2, sort_keys=True)}],
                                "isError": False})


def read_resource(repository: Repository, uri: str) -> Any:
    """Return the payload for one advertised resource URI."""
    text = str(uri or "").strip()
    if text == "lattice://stats":
        return repository.stats()
    if text == "lattice://questions":
        rows = repository.connection.execute("SELECT * FROM questions ORDER BY id").fetchall()
        return {"questions": [dict(row) for row in rows]}
    if text == "lattice://matrix":
        return build_evidence_matrix(repository)
    fail(f"unknown resource uri: {text}", "the server advertises its resources",
         "use lattice://stats, lattice://questions or lattice://matrix")


def get_prompt(repository: Repository, name: str,
               arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Render one advertised prompt into MCP message content."""
    prompt_name = str(name or "").strip()
    if arguments is not None and not isinstance(arguments, dict):
        fail("prompt arguments must be an object", "prompt schemas declare named fields",
             "pass a dict such as {'target': 'q_000001'}")
    values = arguments or {}
    if prompt_name != "literature-synthesis":
        fail(f"unknown prompt: {prompt_name}", "the server advertises its prompts",
             "use literature-synthesis")
    target = str(values.get("target") or "").strip()
    if not target:
        fail("prompt 'literature-synthesis' requires 'target'",
             "a synthesis prompt needs a question or search phrase",
             "pass the target argument")
    try:
        tokens = int(values.get("tokens", 2500))
    except (TypeError, ValueError):
        fail(f"token budget {values.get('tokens')!r} is not an integer",
             "synthesis needs a numeric token budget",
             "pass an integer tokens value such as 2500")
    report = synthesize(repository, target, tokens=tokens)
    return {
        "description": f"Scientific literature synthesis for {target}",
        "messages": [{
            "role": "user",
            "content": {"type": "text", "text": report.markdown},
        }],
    }


def _read_resource(repository: Repository, request_id: Any, params: Any) -> Dict[str, Any]:
    """Return an MCP resource payload by URI."""
    if not isinstance(params, dict):
        return _error(request_id, -32602, "params must be an object")
    uri = str(params.get("uri") or "")
    try:
        payload = read_resource(repository, uri)
    except LatticeError as exc:
        return _error(request_id, -32602, exc.message)
    return _result(request_id, {
        "contents": [{
            "uri": uri,
            "mimeType": "application/json",
            "text": json.dumps(payload, indent=2, sort_keys=True),
        }]
    })


def _get_prompt(repository: Repository, request_id: Any, params: Any) -> Dict[str, Any]:
    """Render a structured scientific synthesis prompt for an AI agent."""
    if not isinstance(params, dict):
        return _error(request_id, -32602, "params must be an object")
    name = str(params.get("name") or "")
    arguments = params.get("arguments")
    if arguments is None:
        arguments = {}
    try:
        payload = get_prompt(repository, name, arguments)
    except (LatticeError, TypeError, ValueError) as exc:
        message = exc.message if isinstance(exc, LatticeError) else str(exc)
        return _error(request_id, -32602, message)
    return _result(request_id, payload)


def dispatch_tool(repository: Repository, name: str, arguments: Dict[str, Any]) -> Any:
    """Map a tool name to its repository, discovery, extraction or synthesis operation.

    Public so a Python host can reuse the exact MCP semantics without a JSON-RPC hop.
    """
    if not isinstance(name, str) or not name.strip():
        fail("a tool name is required", "tool names are strings advertised by tools/list",
             "call one of the names returned by tools/list")
    if not isinstance(arguments, dict):
        fail("tool arguments must be an object", "tool schemas declare named fields",
             "pass a dict such as {'query': 'sleep'}")
    if name == "search":
        return compact_search(repository.search(
            _text(arguments, "query"),
            int(arguments.get("limit", 20)),
            stance=arguments.get("stance"),
            min_confidence=arguments.get("min_confidence"),
            year=arguments.get("year"),
        ), int(arguments.get("tokens", 800)))
    if name == "discover_papers":
        service = DiscoveryService(repository)
        return service.discover(
            _text(arguments, "query"),
            source=str(arguments.get("source") or "offline"),
            limit=int(arguments.get("limit", 10)),
            ingest=bool(arguments.get("ingest", True)),
        )
    if name == "extract_claims":
        paper = arguments.get("paper")
        question = arguments.get("question")
        if paper:
            return extract_from_paper(repository, str(paper), question_ref=question).to_dict()
        return extract_all(repository, question_ref=question)
    if name == "get_entity":
        return repository.get(_text(arguments, "ref"))
    if name == "neighbors":
        return [edge.to_dict() for edge in repository.neighbors(
            _text(arguments, "ref"), arguments.get("kind"))]
    if name == "subgraph":
        return compact_subgraph(
            repository.subgraph(_text(arguments, "ref"), int(arguments.get("depth", 1))),
            int(arguments.get("tokens", 800)))
    if name == "related_findings":
        return compact_related(
            related_findings(repository, _text(arguments, "target"),
                             int(arguments.get("limit", 10))),
            int(arguments.get("tokens", 600)))
    if name == "outline":
        return outline(repository, int(arguments.get("tokens", 400)))
    if name == "add_paper":
        paper, created = repository.add_paper(arguments)
        return {"paper": paper.to_dict(), "created": created}
    if name == "add_claim":
        claim = repository.add_claim(
            _text(arguments, "paper"), _text(arguments, "text"), _text(arguments, "quote"),
            str(arguments.get("locator", "")), str(arguments.get("stance", "mentions")),
            arguments.get("confidence"))
        return {"claim": claim.to_dict()}
    if name == "add_question":
        return {"question": repository.add_question(_text(arguments, "text")).to_dict()}
    if name == "set_question_status":
        q = repository.set_question_status(_text(arguments, "question"), _text(arguments, "status"))
        return {"question": q.to_dict()}
    if name == "add_edge":
        edge = repository.add_edge(_text(arguments, "src"), _text(arguments, "dst"),
                                   _text(arguments, "kind"), str(arguments.get("note", "")))
        return {"edge": edge.to_dict()}
    if name == "brief":
        return brief(repository, _text(arguments, "target"), int(arguments.get("tokens", 2000)))
    if name == "review":
        return review(repository, _text(arguments, "target"))
    if name == "synthesize":
        return synthesize(
            repository, _text(arguments, "target"), int(arguments.get("tokens", 2500))
        ).to_dict()
    if name == "analyze_graph":
        auto_link = bool(arguments.get("auto_link", False))
        limit = int(arguments.get("limit", 10))
        related_pairs = find_related_findings(repository)
        related_links = link_related_findings(repository) if auto_link else []
        return {
            "contradictions": [
                item.to_dict() for item in detect_contradictions(repository, auto_link=auto_link)
            ],
            "related_pairs": len(related_pairs),
            "related_links_created": len(related_links),
            "keystone": rank_influential_entities(repository, limit=limit),
            "matrix": build_evidence_matrix(repository),
        }
    if name == "detect_contradictions":
        auto_link = bool(arguments.get("auto_link", False))
        pairs = [item.to_dict() for item in detect_contradictions(repository, auto_link=auto_link)]
        return {"count": len(pairs), "contradictions": pairs}
    if name == "export_snapshot":
        return export_snapshot(repository, Path(_text(arguments, "path")))
    if name == "import_snapshot":
        return import_snapshot(repository, Path(_text(arguments, "path")))
    if name == "stats":
        return repository.stats()
    raise LatticeError(f"unknown tool '{name}'", "the server advertises its tools in tools/list",
                       "call one of the names returned by tools/list")


def _text(arguments: Dict[str, Any], name: str) -> str:
    """A required string argument."""
    value = arguments.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"argument '{name}' must be a non-empty string")
    return value


def _result(request_id: Any, result: Any) -> Dict[str, Any]:
    """A JSON-RPC success response."""
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id: Any, code: int, message: str) -> Dict[str, Any]:
    """A JSON-RPC error response."""
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def serve(repository: Repository, stdin: Optional[TextIO] = None,
          stdout: Optional[TextIO] = None) -> None:
    """Serve newline-delimited JSON-RPC until the input stream closes."""
    source = stdin or sys.stdin
    sink = stdout or sys.stdout
    for line in source:
        text = line.strip()
        if not text:
            continue
        try:
            message = json.loads(text)
        except ValueError:
            response = _error(None, -32700, "parse error")
        else:
            response = handle_message(repository, message)
        if response is not None:
            sink.write(json.dumps(response, sort_keys=True) + "\n")
            sink.flush()
