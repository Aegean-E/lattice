# Decisions

Why this project is built the way it is, oldest first. One entry per decision that changes a
contract, a dependency, a data format or the architecture; IDs are consecutive and never reused.

### ADR-001: One SQLite graph with quote-backed claims and stable identifiers
- **Date**: 2026-10-19
- **Status**: Accepted
- **Context**: Agents need a durable research memory that can prove where every statement came
  from, while staying local, inspectable and dependency-free.
- **Decision**: Store papers, claims, questions, edges and an append-only event log in one SQLite
  file (`schema_version` 1). Paper ids are `p_` plus a SHA-1 prefix of DOI, then arXiv ID, then
  normalized title. Claims are `c_NNNNNN` and questions `q_NNNNNN`. A claim requires non-empty
  assertion text, an exact quote and an existing paper; confidence is a float in [0, 1]. Edges
  use full references such as `claim:c_000001` and are unique per `(src, dst, kind)`. Duplicate
  DOIs, arXiv IDs and normalized title/year pairs are merged by filling missing metadata.
- **Consequences**: The file is portable and auditable with standard tools. Sequential claim and
  question ids are readable but require a table scan to allocate, which is acceptable at research
  scale. Query performance beyond personal or lab-sized corpora would need indexed full-text search.

### ADR-002: Evidence direction and deterministic review artifacts
- **Date**: 2026-10-19
- **Status**: Accepted
- **Context**: "Ask" must not turn into an untraceable chatbot answer, and agents need bounded
  context that fits a prompt.
- **Decision**: Evidence is a claim linked to a question with `supports`, `contradicts` or
  `answers`. `ask` groups linked claims and suggests unlinked claims by keyword. `brief` renders
  those groups under a character-based token estimate (`ceil(chars / 4)`) and drops the
  lowest-ranked evidence first, reporting how many items were omitted. `review` emits Markdown
  with resolved paper references and never generates a sentence that is not backed by a claim.
- **Consequences**: Outputs are deterministic and testable, but brief quality depends on the
  links a human or agent supplied. Keyword suggestions use SQLite substring matching rather than
  stemming or embeddings.

### ADR-003: MCP is a thin stdio transport over the same repository
- **Date**: 2026-10-19
- **Status**: Accepted
- **Context**: Agents need a standard tool protocol without adding an SDK, a server framework or
  a network listener to a zero-dependency project.
- **Decision**: Implement newline-delimited JSON-RPC 2.0 over stdio in `lattice.mcp`, supporting
  `initialize`, `ping`, `tools/list` and `tools/call`. Every tool maps to an existing repository
  or inquiry function; user-facing failures become `isError` content with the Error/Why/Fix
  triad, while protocol errors use standard JSON-RPC codes.
- **Consequences**: Any MCP-capable client can use the graph, and the transport remains testable
  without spawning processes. The server is single-client and does not implement resources,
  prompts or streaming notifications.

### ADR-004: Pluggable literature discovery with offline seed corpus
- **Date**: 2026-10-19
- **Status**: Accepted
- **Context**: Automated literature search needs access to open scholarly catalogs (arXiv, Crossref)
  while preserving deterministic offline testing, zero third-party dependencies, and strict
  subprocess/network timeouts.
- **Decision**: Define a 4-layer pluggable discovery boundary in `lattice.discovery`: immutable
  `PaperCandidate` DTO, `LiteratureProvider` protocol, `ProviderRegistry`, and concrete
  `ArxivProvider`, `CrossrefProvider`, and `OfflineCorpusProvider` wired into `DiscoveryService`
  with constructor DI. Network providers use `urllib.request.urlopen` with an explicit 10-second
  timeout and injectable fetcher callables for unit testing.
- **Consequences**: Agents can discover and deduplicate papers from live catalogs or offline
  corpora through a single contract while unit tests remain sub-millisecond and network-free.

### ADR-005: Automated claim extraction, consensus synthesis, and MCP resources/prompts
- **Date**: 2026-10-19
- **Status**: Accepted
- **Context**: Researchers and AI agents need end-to-end automated knowledge creation (turning
  abstracts into quote-backed claims and edges), multi-hop graph interaction, portable snapshots,
  and quantitative literature synthesis for scientific queries.
- **Decision**: Add `lattice.extraction` for deterministic empirical sentence segmentation,
  stance/confidence inference, and question auto-linking; `lattice.snapshots` for atomic JSONL
  export (`temp` + `fsync` + `os.replace`) and idempotent merge import; `lattice.synthesis` for
  confidence-weighted consensus scoring in `[-1.0, 1.0]`, thematic claim clustering, follow-up
  query generation, and BibTeX output; and expand `lattice.mcp` with `resources/list`,
  `resources/read`, `prompts/list`, and `prompts/get`.
- **Consequences**: AI agents can discover literature, extract grounded claims, traverse
  subgraphs, and retrieve consensus-scored scientific syntheses via CLI or MCP without losing
  verbatim quote provenance.

### ADR-006: Zero-dependency web Research Studio with pure request dispatch
- **Date**: 2026-10-19
- **Status**: Accepted
- **Context**: Human researchers need an intuitive visual interface for discovering papers,
  extracting and curating quote-backed claims, synthesizing evidence, and exploring multi-hop
  subgraphs without installing external frontend frameworks or web servers.
- **Decision**: Implement `lattice.web` with a pure `dispatch_web_request(repository, method,
  path, body)` router returning `WebResponse` DTOs and a thin `ThreadingHTTPServer` wrapper in
  `serve_web` exposed via `python -m lattice web`. Embed a self-contained single-page Research
  Studio (`WEB_HTML`) with inline CSS, vanilla JS, and interactive SVG subgraph rendering with
  zero third-party URLs.
- **Consequences**: Humans can launch the full visual studio with `python -m lattice web --demo
  --open` offline or online, while unit tests verify all HTML and JSON API routes in under a
  millisecond without sockets.



