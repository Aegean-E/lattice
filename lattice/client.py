"""Turnkey client facade for AI hosts: own one connection, call MCP-parity tools.

`LatticeClient` wraps a single SQLite connection and exposes the same 22 tools the MCP server
advertises, so a Python agent can register `tool_schemas()` and dispatch through `call_tool`
without reimplementing the graph rules. `AsyncLatticeClient` runs that client on one dedicated
thread, which keeps SQLite's thread affinity intact for asyncio hosts.
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from typing import Any, Dict, Optional, Sequence

from lattice.database import open_database
from lattice.errors import fail
from lattice.mcp import (
    PROMPTS,
    RESOURCES,
    TOOLS,
    dispatch_tool,
    get_prompt as render_prompt,
    read_resource as load_resource,
)
from lattice.repository import Repository

DEFAULT_DB = "lattice.db"

_READ_ONLY_TOOLS = frozenset({
    "search", "get_entity", "neighbors", "subgraph", "related_findings", "outline",
    "brief", "review", "synthesize", "stats", "analyze_graph", "detect_contradictions",
    "diff_snapshot", "find_path", "propose_hypotheses", "get_prisma_flow",
})


class LatticeClient:
    """A synchronous, context-managed graph client with MCP tool parity.

    Use one client per thread: it owns one SQLite connection. Use `AsyncLatticeClient` to
    serialize calls from an event loop, or a separate client per worker for parallel access.
    A read-only client requires an existing database and opens it with SQLite `mode=ro`.
    """

    def __init__(self, db_path: str = DEFAULT_DB, read_only: bool = False) -> None:
        text = "" if db_path is None else str(db_path)
        if not text.strip():
            fail("a database path is required", "the client needs a file or :memory: database",
                 "pass a file path, ':memory:' or DEFAULT_DB")
        self.db_path = ":memory:" if text.strip() == ":memory:" else text
        self.read_only = bool(read_only)
        self._connection = open_database(self.db_path, read_only=self.read_only)
        self._repository = Repository(self._connection)
        self._closed = False

    @property
    def repository(self) -> Repository:
        """The underlying repository for advanced writable callers."""
        self._ensure_open()
        if self.read_only:
            fail("the repository is not exposed on a read-only client",
                 "direct repository writes would bypass the read-only policy",
                 "use call_tool or create a writable LatticeClient")
        return self._repository

    def __enter__(self) -> "LatticeClient":
        self._ensure_open()
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()

    def close(self) -> None:
        """Close the owned connection; safe to call more than once."""
        if not self._closed:
            self._connection.close()
            self._closed = True

    def _ensure_open(self) -> None:
        if self._closed:
            fail("the lattice client is closed", "the owned database connection is gone",
                 "use the client inside its context manager or create a new one")

    def tool_schemas(self) -> list[Dict[str, Any]]:
        """The MCP tool declarations, filtered to the read-only set when requested."""
        self._ensure_open()
        tools = [item for item in TOOLS
                 if not self.read_only or item["name"] in _READ_ONLY_TOOLS]
        result = deepcopy(tools)
        if self.read_only:
            for item in result:
                if item["name"] in ("analyze_graph", "detect_contradictions"):
                    item["inputSchema"]["properties"].pop("auto_link", None)
        return result

    def resource_schemas(self) -> list[Dict[str, Any]]:
        """A deep copy of the advertised MCP resource declarations."""
        self._ensure_open()
        return deepcopy(RESOURCES)

    def prompt_schemas(self) -> list[Dict[str, Any]]:
        """A deep copy of the advertised MCP prompt declarations."""
        self._ensure_open()
        return deepcopy(PROMPTS)

    def read_resource(self, uri: str) -> Any:
        """Read one advertised resource such as `lattice://stats`."""
        self._ensure_open()
        return load_resource(self._repository, uri)

    def get_prompt(self, name: str,
                   arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Render one advertised prompt with its arguments."""
        self._ensure_open()
        if arguments is not None and not isinstance(arguments, dict):
            fail("prompt arguments must be an object", "prompt schemas declare named fields",
                 "pass a dict such as {'target': 'q_000001'}")
        try:
            return render_prompt(self._repository, name, arguments)
        except (TypeError, ValueError) as exc:
            fail(str(exc), "the prompt arguments do not match its schema",
                 "read prompt_schemas() and pass the required fields")

    def call_tool(self, name: str, arguments: Optional[Dict[str, Any]] = None,
                  **kwargs: Any) -> Any:
        """Run one MCP tool by name; arguments may be a mapping plus keyword overrides."""
        self._ensure_open()
        if not isinstance(name, str) or not name.strip():
            fail("a tool name is required", "tool names are strings advertised by tool_schemas()",
                 "pass a name from tool_schemas()")
        if arguments is not None and not isinstance(arguments, dict):
            fail("tool arguments must be an object", "schemas declare named fields",
                 "pass a dict such as {'query': 'sleep'}")
        payload = dict(arguments or {})
        payload.update(kwargs)
        if self.read_only:
            if name not in _READ_ONLY_TOOLS:
                fail(f"tool '{name}' is not available in read-only mode",
                     "the read-only client advertises only non-mutating tools",
                     "use one of the tools in tool_schemas() or create a writable client")
            if name in ("analyze_graph", "detect_contradictions") and payload.get("auto_link"):
                fail(f"tool '{name}' cannot auto-link in read-only mode",
                     "auto_link writes edge rows",
                     "omit auto_link or create a writable client")
        try:
            return dispatch_tool(self._repository, name, payload)
        except (TypeError, ValueError) as exc:
            fail(str(exc), "the tool arguments do not match the advertised schema",
                 "read tool_schemas() and pass the required fields")

    def search(self, query: str, limit: int = 20, stance: Optional[str] = None,
               min_confidence: Optional[float] = None, year: Any = None,
               tokens: int = 800) -> Dict[str, Any]:
        return self.call_tool("search", {
            "query": query, "limit": limit, "stance": stance,
            "min_confidence": min_confidence, "year": year, "tokens": tokens})

    def discover_papers(self, query: str, source: str = "offline", limit: int = 10,
                        ingest: bool = True) -> Dict[str, Any]:
        return self.call_tool("discover_papers", {
            "query": query, "source": source, "limit": limit, "ingest": ingest})

    def extract_claims(self, paper: Optional[str] = None,
                       question: Optional[str] = None) -> Dict[str, Any]:
        return self.call_tool("extract_claims", {"paper": paper, "question": question})

    def get_entity(self, ref: str) -> Dict[str, Any]:
        return self.call_tool("get_entity", {"ref": ref})

    def neighbors(self, ref: str, kind: Optional[str] = None) -> list[Dict[str, Any]]:
        return self.call_tool("neighbors", {"ref": ref, "kind": kind})

    def subgraph(self, ref: str, depth: int = 1, tokens: int = 800) -> Dict[str, Any]:
        return self.call_tool("subgraph", {"ref": ref, "depth": depth, "tokens": tokens})

    def related_findings(self, target: str, limit: int = 10,
                         tokens: int = 600) -> Dict[str, Any]:
        return self.call_tool("related_findings", {
            "target": target, "limit": limit, "tokens": tokens})

    def outline(self, tokens: int = 400) -> Dict[str, Any]:
        return self.call_tool("outline", {"tokens": tokens})

    def add_paper(self, metadata: Dict[str, Any]) -> Dict[str, Any]:
        return self.call_tool("add_paper", metadata)

    def add_claim(self, paper: str, text: str, quote: str, locator: str = "",
                  stance: str = "mentions", confidence: Optional[float] = None) -> Dict[str, Any]:
        return self.call_tool("add_claim", {
            "paper": paper, "text": text, "quote": quote, "locator": locator,
            "stance": stance, "confidence": confidence})

    def add_question(self, text: str) -> Dict[str, Any]:
        return self.call_tool("add_question", {"text": text})

    def set_question_status(self, question: str, status: str) -> Dict[str, Any]:
        return self.call_tool("set_question_status", {"question": question, "status": status})

    def add_edge(self, src: str, dst: str, kind: str, note: str = "") -> Dict[str, Any]:
        return self.call_tool("add_edge", {
            "src": src, "dst": dst, "kind": kind, "note": note})

    def ask(self, target: str, limit: int = 20) -> Dict[str, Any]:
        """Evidence-first question answering, including search mode outside MCP."""
        self._ensure_open()
        from lattice.inquiry import ask
        return ask(self._repository, target, limit)

    def brief(self, target: str, tokens: int = 2000) -> Dict[str, Any]:
        return self.call_tool("brief", {"target": target, "tokens": tokens})

    def review(self, target: str) -> Dict[str, Any]:
        return self.call_tool("review", {"target": target})

    def synthesize(self, target: str, tokens: int = 2500) -> Dict[str, Any]:
        return self.call_tool("synthesize", {"target": target, "tokens": tokens})

    def analyze_graph(self, auto_link: bool = False, limit: int = 10) -> Dict[str, Any]:
        return self.call_tool("analyze_graph", {"auto_link": auto_link, "limit": limit})

    def detect_contradictions(self, auto_link: bool = False) -> Dict[str, Any]:
        return self.call_tool("detect_contradictions", {"auto_link": auto_link})

    def export_snapshot(self, path: str) -> Dict[str, Any]:
        return self.call_tool("export_snapshot", {"path": path})

    def export_graphml(self, path: str) -> Dict[str, Any]:
        """Export the evidence graph in standard GraphML XML format."""
        self._ensure_open()
        from pathlib import Path
        from lattice.snapshots import export_graphml_file
        return export_graphml_file(self._repository, Path(path))

    def export_cytoscape(self, path: str) -> Dict[str, Any]:
        """Export the evidence graph in Cytoscape.js JSON format."""
        self._ensure_open()
        from pathlib import Path
        from lattice.snapshots import export_cytoscape_file
        return export_cytoscape_file(self._repository, Path(path))

    def sync_article(self, article_data: Dict[str, Any], auto_extract: bool = False) -> Dict[str, Any]:
        """Sync a NeuroCore or external article dict into the evidence graph."""
        self._ensure_open()
        from lattice.ingest import sync_article_from_neurocore
        return sync_article_from_neurocore(self._repository, article_data, auto_extract=auto_extract)

    def import_snapshot(self, path: str) -> Dict[str, Any]:
        return self.call_tool("import_snapshot", {"path": path})

    def diff_snapshot(self, old_path: str, new_path: str = "") -> Dict[str, Any]:
        """Diff a baseline snapshot against another snapshot or the live graph."""
        arguments: Dict[str, Any] = {"old_path": old_path}
        if new_path:
            arguments["new_path"] = new_path
        return self.call_tool("diff_snapshot", arguments)

    def find_path(self, src: str, dst: str, max_depth: int = 5,
                  directed: bool = False,
                  edge_kinds: Optional[Sequence[str]] = None) -> Dict[str, Any]:
        """Find the shortest chain of relations connecting two entities via BFS."""
        return self.call_tool("find_path", {
            "src": src, "dst": dst, "max_depth": max_depth,
            "directed": directed, "edge_kinds": edge_kinds,
        })

    def propose_hypotheses(self, question: Optional[str] = None,
                           limit: int = 5) -> List[Dict[str, Any]]:
        """Formulate testable hypotheses from evidence gaps and contradiction clusters."""
        arguments: Dict[str, Any] = {"limit": limit}
        if question:
            arguments["question"] = question
        return self.call_tool("propose_hypotheses", arguments)

    def screen_paper(self, paper_id: str, status: str, reason: str = "", notes: str = "") -> Dict[str, Any]:
        """Record an auditable PRISMA 2020 screening decision for a paper."""
        return self.call_tool("screen_paper", {"paper_id": paper_id, "status": status, "reason": reason, "notes": notes})

    def get_prisma_flow(self, format: str = "json") -> Dict[str, Any]:
        """Get PRISMA 2020 review attrition metrics and flow diagram."""
        return self.call_tool("get_prisma_flow", {"format": format})

    def stats(self) -> Dict[str, Any]:
        return self.call_tool("stats", {})

    get = get_entity
    related = related_findings
    discover = discover_papers
    extract = extract_claims
    analyze = analyze_graph
    contradictions = detect_contradictions


class AsyncLatticeClient:
    """An asyncio facade that serializes the sync client on one dedicated thread."""

    def __init__(self, db_path: str = DEFAULT_DB, read_only: bool = False) -> None:
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="lattice-client")
        try:
            self._client: LatticeClient = self._executor.submit(
                LatticeClient, db_path, read_only).result()
        except BaseException:
            self._executor.shutdown(wait=True)
            raise
        self._closed = False

    async def __aenter__(self) -> "AsyncLatticeClient":
        self._ensure_open()
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        await self.close()

    async def close(self) -> None:
        """Close the owned connection and stop the worker thread."""
        if self._closed:
            return
        self._closed = True
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(self._executor, self._client.close)
        finally:
            self._executor.shutdown(wait=True)

    def _ensure_open(self) -> None:
        if self._closed:
            fail("the lattice client is closed", "the owned database connection is gone",
                 "use the client inside its context manager or create a new one")

    @property
    def repository(self) -> Repository:
        """The repository is sync-only; exposing it would cross the worker thread."""
        self._ensure_open()
        fail("the repository is not exposed on the async client",
             "direct use would cross the worker thread",
             "use call_tool or a synchronous LatticeClient")

    async def _run(self, func: Any, *args: Any, **kwargs: Any) -> Any:
        self._ensure_open()
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, lambda: func(*args, **kwargs))

    async def tool_schemas(self) -> list[Dict[str, Any]]:
        return await self._run(self._client.tool_schemas)

    async def resource_schemas(self) -> list[Dict[str, Any]]:
        return await self._run(self._client.resource_schemas)

    async def prompt_schemas(self) -> list[Dict[str, Any]]:
        return await self._run(self._client.prompt_schemas)

    async def read_resource(self, uri: str) -> Any:
        return await self._run(self._client.read_resource, uri)

    async def get_prompt(self, name: str,
                         arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return await self._run(self._client.get_prompt, name, arguments)

    async def call_tool(self, name: str, arguments: Optional[Dict[str, Any]] = None,
                        **kwargs: Any) -> Any:
        return await self._run(self._client.call_tool, name, arguments, **kwargs)

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_") or name == "repository":
            raise AttributeError(name)
        client = self.__dict__.get("_client")
        if client is None:
            raise AttributeError(name)
        value = getattr(client, name)
        if not callable(value):
            return value

        async def method(*args: Any, **kwargs: Any) -> Any:
            return await self._run(value, *args, **kwargs)

        method.__name__ = name
        return method
