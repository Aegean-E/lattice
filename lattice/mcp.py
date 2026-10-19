"""A dependency-free MCP stdio server exposing the graph as JSON-RPC tools."""

import json
import sys
from typing import Any, Dict, List, Optional, TextIO

from lattice import __version__
from lattice.errors import LatticeError
from lattice.inquiry import brief, review
from lattice.repository import Repository

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "lattice"


def _tool(name: str, description: str, properties: Dict[str, Any],
          required: List[str]) -> Dict[str, Any]:
    """An MCP tool declaration with a JSON Schema for its arguments."""
    return {"name": name, "description": description,
            "inputSchema": {"type": "object", "properties": properties, "required": required}}


TOOLS: List[Dict[str, Any]] = [
    _tool("search", "Search papers, claims and questions by substring.",
          {"query": {"type": "string"}, "limit": {"type": "integer", "default": 20}}, ["query"]),
    _tool("get_entity", "Fetch one paper, claim or question with all attached edges.",
          {"ref": {"type": "string"}}, ["ref"]),
    _tool("neighbors", "List edges touching an entity, optionally filtered by kind.",
          {"ref": {"type": "string"}, "kind": {"type": "string"}}, ["ref"]),
    _tool("add_paper", "Ingest one paper; duplicate DOIs, arXiv IDs and titles are merged.",
          {"title": {"type": "string"}, "authors": {"type": "string"},
           "year": {"type": "string"}, "venue": {"type": "string"}, "doi": {"type": "string"},
           "arxiv": {"type": "string"}, "url": {"type": "string"},
           "abstract": {"type": "string"}}, ["title"]),
    _tool("add_claim", "Record a claim with the exact quote that grounds it.",
          {"paper": {"type": "string"}, "text": {"type": "string"},
           "quote": {"type": "string"}, "locator": {"type": "string"},
           "stance": {"type": "string"}, "confidence": {"type": "number"}},
          ["paper", "text", "quote"]),
    _tool("add_question", "Record a research question.",
          {"text": {"type": "string"}}, ["text"]),
    _tool("add_edge", "Add a typed relation between two entities.",
          {"src": {"type": "string"}, "dst": {"type": "string"},
           "kind": {"type": "string"}, "note": {"type": "string"}}, ["src", "dst", "kind"]),
    _tool("brief", "Token-budgeted evidence pack for a question or search phrase.",
          {"target": {"type": "string"}, "tokens": {"type": "integer", "default": 2000}},
          ["target"]),
    _tool("review", "Markdown literature-review outline for a question or phrase.",
          {"target": {"type": "string"}}, ["target"]),
    _tool("stats", "Entity and edge counts.", {}, []),
]


def handle_message(repository: Repository, message: Any) -> Optional[Dict[str, Any]]:
    """Dispatch one JSON-RPC message; notifications return None."""
    if not isinstance(message, dict) or not isinstance(message.get("method"), str):
        return _error(None, -32600, "invalid request")
    request_id = message.get("id")
    method = message["method"]
    params = message.get("params") or {}
    if method == "initialize":
        return _result(request_id, {
            "protocolVersion": PROTOCOL_VERSION,
            "serverInfo": {"name": SERVER_NAME, "version": __version__},
            "capabilities": {"tools": {}},
        })
    if method in ("notifications/initialized", "initialized", "shutdown"):
        return None
    if method == "ping":
        return _result(request_id, {})
    if method == "tools/list":
        return _result(request_id, {"tools": TOOLS})
    if method == "tools/call":
        return _call_tool(repository, request_id, params)
    return _error(request_id, -32601, f"method not found: {method}")


def _call_tool(repository: Repository, request_id: Any, params: Any) -> Dict[str, Any]:
    """Run one MCP tool call and wrap the result as text content."""
    if not isinstance(params, dict) or not isinstance(params.get("name"), str):
        return _error(request_id, -32602, "tools/call needs a tool name")
    name = params["name"]
    arguments = params.get("arguments") or {}
    if not isinstance(arguments, dict):
        return _error(request_id, -32602, "arguments must be an object")
    try:
        payload = _dispatch(repository, name, arguments)
    except LatticeError as exc:
        return _result(request_id, {"content": [{"type": "text", "text": exc.render()}],
                                    "isError": True})
    except (TypeError, ValueError) as exc:
        return _error(request_id, -32602, str(exc))
    return _result(request_id, {"content": [{"type": "text",
                                             "text": json.dumps(payload, indent=2, sort_keys=True)}],
                                "isError": False})


def _dispatch(repository: Repository, name: str, arguments: Dict[str, Any]) -> Any:
    """Map a tool name to its repository or inquiry operation."""
    if name == "search":
        return repository.search(_text(arguments, "query"), int(arguments.get("limit", 20)))
    if name == "get_entity":
        return repository.get(_text(arguments, "ref"))
    if name == "neighbors":
        return [edge.to_dict() for edge in repository.neighbors(
            _text(arguments, "ref"), arguments.get("kind"))]
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
    if name == "add_edge":
        edge = repository.add_edge(_text(arguments, "src"), _text(arguments, "dst"),
                                   _text(arguments, "kind"), str(arguments.get("note", "")))
        return {"edge": edge.to_dict()}
    if name == "brief":
        return brief(repository, _text(arguments, "target"), int(arguments.get("tokens", 2000)))
    if name == "review":
        return review(repository, _text(arguments, "target"))
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
