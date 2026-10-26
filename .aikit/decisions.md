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

## ADR-007: Federated Discovery, Contradiction Detection, and Evidence Matrices (2026-10-19)

- **Status**: Accepted
- **Context**: Researchers and AI agents need broader biomedical and open-access catalog coverage
  beyond arXiv and Crossref, plus automated ways to surface conflicting empirical claims, identify
  keystone papers/claims by graph centrality, and inspect Paper x Question coverage matrices.
- **Decision**:
  1. Add `OpenAlexProvider` (reconstructing `abstract_inverted_index` into plaintext abstracts) and
     `EuropePmcProvider` to `lattice.discovery`, and upgrade `DiscoveryService.discover` to accept
     comma-separated provider lists (e.g. `--source offline,openalex,europepmc`) with cross-catalog
     deduplication by DOI, arXiv ID, and normalized title+year.
  2. Implement `lattice.analysis` with `ContradictionPair` frozen DTOs, `detect_contradictions`
     (with idempotent `auto_link=True` edge creation), `rank_influential_entities`, and
     `build_evidence_matrix`.
  3. Expose these capabilities across the CLI (`lattice analyze`), MCP server (`analyze_graph`,
     `detect_contradictions`, and `lattice://matrix`), and Web Research Studio (Tab 5 Evidence
     Matrix & Contradictions, browser paste-ingestion via `/api/ingest-text`, and JSONL snapshot
     export via `/api/export`).
- **Consequences**: Both AI agents and human users can query multiple scientific catalogs at once,
  automatically detect and link conflicting claims, and audit Paper x Question evidence matrices
  with zero third-party dependencies.

## ADR-008: Searchable literature metadata and study types on graph nodes (2026-10-19)

- **Status**: Accepted
- **Context**: Researchers need to find an ingested paper by a remembered tag, a keyword or a full
  sentence, and the graph must say what kind of study a paper represents so evidence is not read
  without its design context.
- **Decision**:
  1. Extend papers with normalized `tags` and `study_type` fields and raise the SQLite schema to
     version 2. `open_database` migrates a version 1 file in place with idempotent `ADD COLUMN`
     statements, backfills tags and study types for existing papers, and refuses versions newer
     than this build.
  2. Explicit metadata wins. Otherwise `derive_tags` weights title keywords above abstract
     keywords, `infer_study_type` classifies design markers (meta-analysis, systematic review,
     randomized trial, cohort, case-control, cross-sectional, qualitative, case study, in vitro,
     animal, computational and experimental), and the fallback is `General Study`.
  3. `Repository.search_literature` matches title, authors, year, venue, DOI, arXiv ID, URL,
     abstract, tags and study type. A query may be a tag filter, one or more words or an exact
     sentence; an empty query with filters acts as a browse.
  4. The Web Research Studio adds a Literature Search panel with tag chips and a study-type filter,
     and every SVG subgraph node carries a study-type label (papers directly, claims via their
     source paper, questions as the distinct types of their linked evidence). Ingestion accepts
     `keywords`/`KW`/`tags` and `studytype`/`M3`/`study_type` in the supported formats.
- **Consequences**: Existing databases upgrade without data loss, snapshots remain backward
  compatible because missing fields default to empty, and CLI/MCP/web paper payloads gain two
  additive fields. Inference is deterministic but heuristic, so callers can always override it.

## ADR-009: Related-finding links and AI-navigable evidence connections (2026-10-19)

- **Status**: Accepted
- **Context**: Findings linked only to research questions, so the map around a question was a
  star: two findings that supported the same question were not connected to each other, and an AI
  agent had to re-derive relevance from raw text instead of walking the graph.
- **Decision**:
  1. Add `find_related_findings` and `link_related_findings` to `lattice.analysis`. Findings are
     related when they share a research question or at least two domain keywords; opposing stances
     remain the domain of contradiction detection, and pairs already joined by any claim-to-claim
     edge are skipped. Links are deterministic `related` edges with reason notes, capped at three
     new links per claim, and idempotent.
  2. `extract` links each newly created finding automatically; `analyze --auto-link` and its MCP
     and web counterparts catch up graphs that predate this change.
  3. Add `related_findings(target, limit)` to `lattice.analysis`, exposed as `lattice related REF`
     and the MCP tool `related_findings`. It returns connected findings (direct claim-to-claim
     edges first, then co-evidence on a shared question, then keyword-only overlap) with the
     relation, the reason, the source paper's study type and a `ref` for the next hop. The view is
     read-only and works before edges are linked.
  4. The Web Studio colors edges by kind, renders `related` edges as a dashed amber line with a
     legend, and adds a Connect Findings action backed by `POST /api/link-related`.
- **Consequences**: The map becomes an evidence web instead of disconnected satellites, and an
  agent can traverse finding-to-finding relations in one bounded call. Auto-linking mutates the
  graph during extraction, so every edge carries a human-readable note and can be deleted like any
  other edge; the cap keeps dense corpora readable.

## ADR-010: Token-frugal, RLM-style AI context views (2026-10-19)

- **Status**: Accepted
- **Context**: The MCP read tools returned full repository payloads: `search` included complete
  paper abstracts, `subgraph` edges repeated each endpoint's summary inside `details`, and
  `related_findings` carried whole claim texts plus paper titles. On a three-paper demo those
  calls cost roughly 944, 1763 and 427 tokens; on a real corpus an agent could exhaust its context
  before reasoning. The user asked for RLM-style navigation that does not spend many tokens.
- **Decision**:
  1. Add `lattice.context` with pure functions over the existing payloads: `outline`,
     `compact_search`, `compact_related` and `compact_subgraph`. Each truncates long text, keeps a
     stable `ref` on every item, packs items within a token budget, and reports `omitted_*` counts
     instead of silently overflowing. Budgets below `MIN_TOKENS` (100) fail with the Error/Why/Fix
     triad.
  2. Treat the graph as an external context. `outline` is the cheap first peek (counts, edge
     kinds, study-type mix and evidenced question refs, about 120 tokens on the demo); compact
     search and related/subgraph views are bounded expansion steps; `get_entity` remains the
     explicit full-text drill-down for one chosen ref. Every view ends with a short `next` hint so
     an agent can recurse without guessing the tool grammar.
  3. MCP `search`, `related_findings` and `subgraph` return compact views by default and accept a
     `tokens` argument (800, 600 and 800). Add the MCP `outline` tool (400) and expose `tags` and
     `study_type` on `add_paper`. `get_entity` and `neighbors` are unchanged.
  4. The CLI gains `outline [--tokens N]` and `--tokens N` on `search`, `related` and `subgraph`;
     without the flag humans and scripts keep the full payloads. The web UI continues to use full
     subgraphs because it renders the complete map.
- **Consequences**: Default MCP payloads shrink substantially on the demo (`search` 944 to 288,
  `related` 427 to 316, `subgraph` 1763 to 394 tokens; `outline` 123) while every omitted item
  stays reachable by ref. Budgets bound the item lists, not the small JSON envelope, so callers
  should treat them as guidance rather than exact caps. Compact views are additive and the full
  repository functions are unchanged; only MCP consumers that relied on fields such as `id`,
  `paper_title`, `text` or edge `details` need to use `ref`/`snippet` and drill down.

## ADR-011: Corpus Outline Drawer, Web Clipboard Actions, and BibTeX Exports (2026-10-19)

- **Status**: Accepted
- **Context**: While token-frugal AI context was introduced in ADR-010, the Web Research Studio had no
  direct visual access to graph orientation metrics, researchers lacked one-click ways to export
  ingested bibliographies to BibTeX for reference managers, and copying synthesis reports required
  manually selecting text across expandable blocks.
- **Decision**:
  1. Add `Repository.export_bibtex(query, tags, study_type, year)` and `snapshots.export_bibtex_file(repository, path)`
     with atomic temp-file replacement. Extend CLI `lattice export PATH [--format jsonl|bibtex]` to
     automatically detect BibTeX format when the path ends in `.bib` or `.bibtex`, defaulting to JSONL.
  2. Expose `GET /api/outline` and `GET /api/export-bibtex` in `lattice.web` with content disposition
     headers (`attachment; filename="lattice-references.bib"`).
  3. Enhance `WebResponse` with a frozen `headers` map and update `Handler._handle` to send custom headers.
  4. In the Web Studio, add a "Corpus Outline" quick drawer displaying entity counts, study-type breakdown,
     edge relations, and evidenced research questions with instant "Synthesize" and "Explore Map" links;
     add "Copy Markdown" and "Copy BibTeX" 1-click clipboard actions to synthesis results; and add
     "Export BibTeX" in the stats bar and "Export Filtered BibTeX (.bib)" in Literature Search.
- **Consequences**: Researchers can instantly export whole or filtered bibliographies in standard BibTeX
  format, AI agents and humans can access orientation stats in the browser via a lightweight drawer, and
  synthesis reports can be copied to the clipboard in one click without altering database schemas.

## ADR-012: NeuroCore Integration as Research Evidence Backend (2026-10-20)

- **Status**: Proposed
- **Context**: NeuroCore (`projects/neurocore/`) is a self-hosted AI agent framework with a research module (`core/research_manager.py`) managing hypotheses, articles, study designs, and findings. Lattice provides a more sophisticated evidence graph with quote-backed claims, deterministic contradiction detection, consensus synthesis, MCP server for AI agents, and a Web Research Studio. Integrating lattice as neurocore's research backend eliminates duplicate data stores and gives neurocore agents provenance-rich evidence access.
- **Decision**:
  1. Expose lattice's repository and inquiry functions via a clean Python API (`lattice.api` module) for neurocore's `LatticeAdapter` to consume. **This module must expose EVERY internal function, class, and constant** - zero detail loss.
  2. Ensure MCP server stability for neurocore agent integration (stdio JSON-RPC with all 21 tools: `search`, `discover_papers`, `extract_claims`, `get_entity`, `neighbors`, `subgraph`, `related_findings`, `outline`, `add_paper`, `add_claim`, `add_question`, `set_question_status`, `add_edge`, `brief`, `review`, `synthesize`, `analyze_graph`, `detect_contradictions`, `export_snapshot`, `import_snapshot`, `stats`).
  3. Add neurocore-specific query helpers: `get_evidence_matrix(hypothesis_ids)`, `get_hypothesis_evidence(question_id)`, `sync_article_from_neurocore(article_data)`.
  4. Maintain lattice's stdlib-only, zero-dependency constraint; neurocore handles FAISS/vector search separately.
  5. Document integration contract in `docs/lattice_integration_design.md` (in neurocore project).
  6. **All lattice CLI commands, web API endpoints, analytical functions, token budgets, validation rules, and data model constraints must remain fully functional and testable independently of neurocore.**
- **Consequences**:
  - *Positive*: Lattice becomes a reusable evidence engine; neurocore gains provenance, contradiction detection, synthesis without reimplementation; shared MCP tools enable consistent agent behavior across both systems.
  - *Trade-offs*: Lattice must maintain backward compatibility for neurocore adapter; schema changes require coordinated migration; neurocore's ResearchManager migration is a separate effort tracked in neurocore's ADR-007. **Lattice's own test suite and CLI must remain the primary verification surface.**

## ADR-013: Public Python API Surface for Host Integrations (2026-10-22)

- **Status**: Accepted
- **Context**: ADR-012's Phase 1 requires a `lattice/api.py` module so a host such as neurocore can
  use the graph without CLI or MCP overhead. The drafted import block named several symbols that do
  not exist in this package (`InquiryService`, `synthesize_question`,
  `extract_claims_for_paper`), so following it literally would fail at import.
  The package also exposes ingestion, checks, database, MCP dispatch and web dispatch contracts that
  a host may need, and the draft omitted them.
- **Decision**:
  1. Add `lattice/api.py` as a thin, import-only facade that re-exports the existing public symbols
     from repository, analysis, synthesis, snapshots, discovery, extraction, ingest, checks,
     inquiry, context, models, errors, database, MCP dispatch and web dispatch. Importing it has no
     side effects and must not duplicate behavior.
  2. Keep inquiry function-based (`ask`, `brief`, `review`) rather than inventing a service class.
     Preserve the draft integration names as aliases: `synthesize_question = synthesize` and
     `extract_claims_for_paper = extract_from_paper`.
  3. Add two read-only helpers: `get_evidence_matrix(repository, question_ids=None)` narrows the
     Paper x Question matrix to selected question references (keeping only their cells, gaps and
     the papers that carry a cell), and `get_hypothesis_evidence(repository, question_id)` returns
     `Repository.evidence` for one question.
  4. Pin the surface with `tests/test_api.py`: expected exports, sorted unique `__all__`, identity
     of re-exports, alias identity, and both helper behaviors.
  5. Do not implement the still-aspirational ADR-012 items such as `details` JSON columns,
     update/delete methods, a sync engine or `sync_article_from_neurocore`; they need their own
     schema and adapter decisions.
- **Consequences**: Hosts get one stable, documented import surface and the neurocore adapter can
  start from real symbols. Every future public module addition must update `api.__all__` and the
  test; the facade cannot drift silently. No runtime behavior, schema or persistence changes.
  The draft design document's `InquiryService` and helper names must be read through this ADR.

## ADR-014: API Input Hardening and a Self-Checking Export Inventory (2026-10-22)

- **Status**: Accepted
- **Context**: Reviewing ADR-013 found three gaps. A single string passed to
  `get_evidence_matrix` was iterated character-by-character and silently returned an empty
  matrix; bare identifiers skipped validation, so a paper id or a typo filtered to nothing; and
  the subset-only export test let eight public definitions (`PAPER_FIELDS`, `SEED_CORPUS`,
  `Record`, `__version__`, `PROTOCOL_VERSION`, `RESOURCES`, `PROMPTS`, `WEB_HTML`) stay outside
  `api.__all__` despite the no-silent-drift claim.
- **Decision**:
  1. `get_evidence_matrix` accepts one question reference string or an iterable. A string is
     treated as a one-item selection.
  2. `_question_key` rejects empty or whitespace-only values and anything that is not a `q_xxx`
     or `question:q_xxx` identifier with the Error/Why/Fix triad. Well-formed ids that do not
     exist still filter to an empty selection.
  3. Export the remaining public definitions, including the adapter's canonical `PAPER_FIELDS`
     tuple, the MCP protocol/resources/prompts metadata and `lattice.__version__`.
  4. `tests/test_api.py` derives every public top-level function, class and assignment from the
     AST of each surfaced module and fails when one is missing from `api.__all__`. The inventory
     replaces manual bookkeeping as the drift guard.
- **Consequences**: Host adapters can pass either form without a silent wrong result, malformed
  selections fail loudly, and adding a public symbol to a surfaced module now requires exporting
  it. No runtime, dependency, schema or persistence change.

## ADR-015: Strict Question References and a Self-Discovering Surface Inventory (2026-10-22)

- **Status**: Accepted
- **Context**: ADR-014's prefix check still accepted malformed references (`q_`,
  `question:q_`, `question:q_1:extra`) and filtered to empty. It also built the entire Paper x
  Question matrix before validating the selection, and its export inventory relied on a hardcoded
  module set plus an AST walk that ignored multi-target and conditional definitions.
- **Decision**:
  1. `_question_key` accepts exactly `q_<id>` or `question:q_<id>`, where `<id>` starts with an
     alphanumeric and continues with alphanumerics, underscores or hyphens. Everything else fails
     with the Error/Why/Fix triad before any graph work.
  2. `get_evidence_matrix` normalizes and validates the selection first, returns the empty matrix
     for an empty selection, and only then builds the full matrix.
  3. `tests/test_api.py` discovers surfaced modules with `pkgutil` (excluding `api`, `cli` and
     `__main__`) and collects functions, classes and assignments, including multi-target,
     augmented and conditional definitions, so new public symbols fail the test until exported.
  4. The evidence helper is documented as grouping by role (`supports`, `contradicts`, `answers`,
     `other`); each item still carries its exact `link` kind.
- **Consequences**: Malformed selections cost nothing and cannot silently produce an empty result,
  and the inventory test keeps pace with new modules and assignment forms without manual lists. No
  dependency, schema or persistence change.

## ADR-016: Turnkey Client Facade for AI Hosts (2026-10-22)

- **Status**: Accepted
- **Context**: `lattice.api` is a stable library surface, but an AI host still had to open and
  close the SQLite connection, copy the 21 MCP tool declarations, map tool names to repository
  calls, and find a thread-safe way to call the graph from asyncio. The published MCP server
  already has the exact tool semantics, so duplicating them in a new adapter would let the two
  surfaces drift.
- **Decision**:
  1. Add `lattice.client.LatticeClient`, a synchronous context manager that owns one connection.
     It exposes `tool_schemas()` (a deep copy of the MCP declarations), `call_tool(name,
     arguments)`, and one convenience method per MCP tool (21, plus `ask` for search-mode
     question answering). Close is idempotent; any call after close fails with the Error/Why/Fix
     triad.
  2. Publish the existing dispatcher as `lattice.mcp.dispatch_tool`, so the client and the MCP
     server share one implementation. Malformed tool arguments become `LatticeError` instead of
     leaking `ValueError`.
  3. Add `AsyncLatticeClient`, which opens and uses the synchronous client on one dedicated
     `ThreadPoolExecutor` thread. This preserves SQLite's thread affinity without weakening
     `check_same_thread` globally. It supports `async with`; public methods are awaitable;
     `repository` is intentionally unavailable because direct cross-thread use would be unsafe.
  4. Export `LatticeClient`, `AsyncLatticeClient`, `DEFAULT_DB` and `dispatch_tool` from
     `lattice.api`, and cover lifecycle, tool parity, schemas, failure modes and async behavior in
     `tests/test_client.py`.
- **Consequences**: A Python AI host imports one client, lists the 21 tool schemas, and dispatches
  calls with the same behavior as the MCP server; async hosts do not need to know about SQLite
  threads. The client adds no schema, dependency or persistence change. The async facade serializes
  calls on one thread, so it is not a parallel query pool; hosts that need concurrency should open
  one client per worker.

## ADR-017: Read-Only Client Policy, Path Validation and Resource Parity (2026-10-22)

- **Status**: Accepted
- **Context**: The first client facade gave an autonomous agent every tool, including writes,
  arbitrary snapshot paths and remote discovery. It also accepted an empty or `None` database
  path (`str(None)` became a file named `None`), exposed tools but not the MCP resources or prompt,
  and only spot-checked tool execution in its tests. ADR-016 documented the tool surface but no
  safety boundary.
- **Decision**:
  1. `LatticeClient(db_path, read_only=False)` validates that the path is a non-empty string
     before opening the database. A read-only client requires an existing file, opens it through
     SQLite's `mode=ro` URI, sets `PRAGMA query_only=ON`, and refuses a schema version that would
     need a migration. It never creates or migrates a file; an in-memory read-only database still
     creates only its in-memory schema.
  2. A read-only client advertises only the 12 non-mutating tools; `tool_schemas()` removes the
     `auto_link` property from `analyze_graph` and `detect_contradictions`, and `call_tool()`
     rejects every other tool name plus any `auto_link=True` call. The raw `repository` is not
     exposed in read-only mode, so the facade cannot be trivially bypassed.
  3. Publish `mcp.read_resource` and `mcp.get_prompt` (the JSON-RPC handlers now wrap them) and
     expose `resource_schemas`, `prompt_schemas`, `read_resource` and `get_prompt` on the client.
     Prompt arguments and MCP params/arguments are validated before use, so malformed tokens or
     non-object values return a `-32602` error instead of escaping the JSON-RPC loop.
  4. Add a table-driven test that executes all 21 tools through the client and JSON-serializes
     every payload, plus read-only, path-validation, resource and async-policy tests, and database
     tests for missing files, query-only enforcement and refused v1 migration.
- **Consequences**: Hosts can hand an autonomous agent a client whose advertised and accepted
  surface contains no writes, network discovery or snapshot paths, and whose connection cannot
  write the database file. Hard isolation from other OS users still benefits from file permissions.
  The 12-tool allowlist is conservative: a new tool stays blocked until it is reviewed and added.
  Read-only WAL access may still require a readable `-shm` file, so filesystems that cannot provide
  one need a copy or immutable storage. The async facade inherits the same policy. No schema change.






## ADR-018: Guided Cold Start and Decluttered Studio Chrome (2026-10-22)

- **Status**: Accepted
- **Context**: The Web Research Studio opened with nine header controls, five long numbered tab
  labels, and always-visible import and manual-entry forms. A first-time user had no single
  obvious entry point, and the chrome competed with the evidence workflow on narrow screens.
- **Decision**:
  1. Add a "Start here" onboarding card to the Synthesize tab with a three-step path and three
     actions: load the demo, add own papers, or ask a question. It hides automatically as soon as
     the corpus contains a paper or claim.
  2. Keep one primary header action (Load Demo Corpus) and move Corpus Outline, Extract All
     Claims, Download Snapshot and Export BibTeX behind a single "More Actions" overflow menu.
  3. Shorten the workflow tabs to Synthesize, Discover, Curate, Graph and Matrix; keep their full
     descriptions as tooltips, allow horizontal scrolling on narrow screens, and expose one-line
     pane intros on every tab.
  4. Put the paste-ingestion and manual-paper forms behind collapsed disclosure cards so
     discovery remains the visible first task.
- **Consequences**: The first screen presents one primary path instead of a wall of controls, and
  the tab bar remains usable on small viewports. All existing commands, endpoints and identifiers
  remain available through the overflow menu or disclosures. No API, schema or persistence change.

## ADR-019: Deterministic Snapshot Diffing (2026-10-23)

- **Status**: Accepted
- **Context**: Snapshots could be exported and imported but never compared. A researcher or
  agent holding a baseline JSONL export had no way to see how the evidence graph had evolved
  since, and scripts had no gate for "did the graph change".
- **Decision**:
  1. Add `lattice/diff.py` with three public functions: `diff_records` (pure comparison of two
     record sets), `diff_snapshots` (two JSONL files) and `diff_snapshot` (a baseline file
     against the live repository). Records are matched by `(record_type, id)`; the report lists
     added and removed ids plus changed ids with their changed field names, sorted for
     determinism.
  2. The volatile `created_at` field never counts as a change, so an idempotent re-import of a
     snapshot diffs as unchanged rather than reporting timestamp noise.
  3. Extract `read_snapshot_records` and `collect_repository_records` in `snapshots.py` so
     export, import and diff share one record reader; `export_snapshot` and `import_snapshot`
     now build on them.
  4. Surface the feature everywhere snapshots already live: the `diff OLD [NEW]` CLI command
     (exit code 1 when the graphs differ, like `git diff`), the read-only-allowed
     `diff_snapshot` MCP tool with `old_path`/optional `new_path`, client convenience methods
     (async facade proxies them automatically), and `lattice.api` re-exports.
- **Consequences**: Graph evolution becomes inspectable and scriptable. Ids are stable within
  one database lineage, so diffs are meaningful for snapshots of an evolving graph; two
  unrelated graphs still compare deterministically by id. Read-only clients gain a new allowed
  tool because diffing only reads files and the database. No schema or persistence change.

## ADR-020: AIKit UI Guard Integration (2026-10-23)

- **Status**: Accepted
- **Context**: The Research Studio is a large single-file web UI (`lattice/web.py`), but the
  project had no UI contract, so `aikit ui begin/verify/finish` could not bound or prove a
  studio edit: a dropped control, API route or theme token would regress silently.
- **Decision**:
  1. Commit `.aikit/ui.json` (schema 1): the `studio` surface is exactly `lattice/web.py`;
     tests, tools, launchers, docs, `.aikit/` and every other lattice module are protected;
     the fast proof is `python -m unittest discover`; the snapshot proof is
     `python tools/ui_inventory.py`; the theme lives in `lattice/web.py` itself; the diff
     budget is 2 files and 400 lines.
  2. Add `tools/ui_inventory.py`: a pure-parsing inventory that imports the exact served
     `WEB_HTML` and reads the dispatcher source, printing one stable sorted line per element
     id, click handler, role, live region, GET/POST route and theme token (116 entries at
     adoption). It never starts a server or browser.
  3. Cover it with `tests/test_ui_inventory.py`, asserting real studio entries, and document
     the `ui begin/verify/finish` flow in the README's AIKit command table.
- **Consequences**: A studio edit is now a bounded task: verify refuses changes outside
  `lattice/web.py`, protects every other path, enforces the diff budget, reruns the suite,
  compares the inventory snapshot (lost entries are findings unless allowed with a reason)
  and lints hardcoded style literals; finish additionally requires a recorded human review.
  The contract must stay committed, and an open UI task blocks delivery until finished or
  aborted. No package, schema or persistence change.

## ADR-021: Validation and Adoption Pass (2026-10-23)

- **Status**: Accepted
- **Context**: The PM review of lattice concluded that engineering quality is high but
  adoption is unmeasured: PDFs - where researchers actually keep papers - hit a generic binary
  error with no recipe, the full user journey was never exercised as a repeatable gate, the
  agent (MCP) channel had no integration story in the README, and there were no evidence-health
  metrics to judge whether the core loop works.
- **Decision**:
  1. Reject `.pdf` before reading it and fail with the documented conversion recipe
     (`pdftotext paper.pdf paper.txt`, or a BibTeX/RIS export from the reference manager), so the
     error names the fix instead of a decoding failure. Document the same recipes in the README.
  2. Add `tools/dogfood.py` (PRINCIPLE-015): the real CLI golden path on a temporary database
     (init, question, offline discovery, extraction, synthesis, export, diff, re-export and
     idempotent import) plus the live Research Studio server on a free port driven over HTTP
     (page, demo seeding, overview, search, matrix, question), then chaos (malformed JSON,
     unknown route, missing entity, empty payload, PDF ingestion), a liveness check after
     chaos, and a before/after fingerprint of the tracked tree. 25 steps, errors/Why/Fix, exit
     0/1/2, full log in `.aikit/dogfood_last_run.log`.
  3. Document the agent channel in the README: the MCP host configuration, the 22 advertised
     tools (13 read-only), the budgeted outline -> compact views -> brief -> get_entity flow, and
     the read-only client policy.
  4. Add an `evidence` health block to `stats` (claims per paper, questions answered/open/
     abandoned, linked questions, coverage gaps, contested questions, claim-question links),
     rendered as one line by the CLI and returned unchanged by MCP and the studio overview.
- **Consequences**: Input friction is explained at the failure point, the whole research loop is
  a one-command gate that leaves the tree untouched, agents have a documented onboarding path,
  and graph health is measurable from any database. The dogfood found two harness bugs during
  adoption (wrong search parameter name, comparing an import against a since-evolved database)
  and now guards both. `stats` grows additive keys only; no schema change.

## ADR-022: Research Studio Evidence Health and Graph Inspector (2026-10-24)

- **Status**: Accepted
- **Context**: The Web Research Studio lacked visual feedback for the evidence health block (gaps and contested counts) introduced in ADR-021, and clicking nodes in the interactive SVG diagram immediately re-centered and reloaded the whole graph without offering an on-page provenance inspection card for the selected entity.
- **Decision**:
  1. Add `Gaps` and `Contested` pills to the header stats bar (`st-gaps`, `st-contested`) and populate them from `/api/overview`'s `data.stats.evidence`.
  2. Embed the Evidence Health metrics breakdown (`Claims/Paper`, `Gaps`, `Contested`) in the Corpus Outline drawer.
  3. Add an interactive `#graph-node-detail` inspector card directly under `#svg-container`. When any node in the SVG diagram is clicked, display its entity type badge, reference id, full title or assertion text, verbatim quote (for claims), locator, confidence, and source paper metadata without forcing an immediate subgraph re-query. Provide a dedicated "Recenter on this node" action for multi-hop drilling.
  4. Bound all UI additions within the AIKit UI guard contract (`.aikit/ui.json`, `studio` surface in `lattice/web.py`), passing `aikit ui verify` with 0 strikes and preserving all 116 baseline inventory entries.
- **Consequences**: Researchers immediately see coverage gaps and contested findings in the header and outline drawer, and provenance inspection during multi-hop graph exploration becomes seamless without visual re-layout disruption. All 195 tests, dogfood (25/25), and UI inventory proofs pass. No schema change.

## ADR-023: Multi-Format Graph Export and NeuroCore Article Synchronization (2026-10-24)

- **Status**: Accepted
- **Context**: Researchers and downstream network visualization tools (Gephi, Cytoscape, NetworkX, Obsidian) required standard graph interchange formats (GraphML XML and Cytoscape.js JSON) rather than only JSONL snapshots or BibTeX bibliographies. Additionally, NeuroCore research agents needed an automated, field-mapped article synchronization entry point fulfilling the design in ADR-012.
- **Decision**:
  1. Add `export_graphml_string` and `export_graphml_file` in `lattice.snapshots`, generating standard GraphML XML (`http://graphml.graphdrawing.org/xmlns`) with declared node keys (`type`, `label`, `title`, `study_type`, `year`, `confidence`, `status`) and edge keys (`kind`, `weight`).
  2. Add `export_cytoscape_data` and `export_cytoscape_file` in `lattice.snapshots`, generating standard Cytoscape.js elements JSON for web-based graph analysis.
  3. Expand `lattice export` CLI command to auto-detect `.graphml` and `.cyjs`/`.cytoscape` extensions and accept `--format graphml|cytoscape`.
  4. Expose `sync_article_from_neurocore` in `lattice.ingest` and `lattice.api` to normalize authors, tags, venue, and study types from NeuroCore article records, automatically recording quote-backed claims from `key_findings` and optional full extraction.
  5. Provide `export_graphml`, `export_cytoscape`, and `sync_article` convenience methods on `LatticeClient` and `AsyncLatticeClient`, and allow `format` parameter dispatch in `export_snapshot` MCP tool.
- **Consequences**: Lattice graphs can be opened directly in Gephi, Cytoscape, and NetworkX with full typed semantics and metadata. NeuroCore agents can synchronize articles into the evidence graph in one step. All 199 unit tests and 25/25 dogfood steps pass. Zero third-party dependencies added (standard library `xml.etree.ElementTree` and `json` only). No database schema changes.

## ADR-024: Multi-Hop Evidence Path Tracing and Reasoning Chains (2026-10-24)

- **Status**: Accepted
- **Context**: Researchers and AI agents need to understand how distant papers, claims, and questions relate across the knowledge graph. Prior to this decision, graph traversal was limited to 1-hop direct neighbors and unoriented ego-network subgraphs, leaving agents to manually search for connecting evidence chains.
- **Decision**:
  1. Implement `find_path` in `lattice.analysis` using deterministic Breadth-First Search (BFS) to find the shortest relation path between any two validated entity references.
  2. Support configurable `max_depth` (1 to 10, default 5), optional `directed` constraint (default undirected for provenance navigation), and optional `edge_kinds` filtering (e.g. evidentiary links `supports,contradicts,answers` vs citation links `cites`).
  3. Return a structured result dictionary containing `found`, `length` (edge hops), ordered `steps` with edge IDs and directions, resolved `nodes` summaries, and a human-readable `narrative` explanation.
  4. Expose `find_path` across all access surfaces: `lattice path SRC DST` CLI command (with `--depth`, `--directed`, `--kinds`, and `--json`), `find_path` in `lattice.api`, `client.find_path()` on `LatticeClient` and `AsyncLatticeClient`, and the `find_path` MCP tool (added to `_READ_ONLY_TOOLS` allowlist).
- **Consequences**: Agents and humans can query the exact chain of evidentiary backing between any two findings without heuristics or third-party graph dependencies. The algorithm guarantees the shortest path in $O(V + E)$ time and memory bounded by `max_depth`. All 208 unit tests pass and import cycles are strictly avoided. No database schema changes.

## ADR-025: Automated Hypothesis Formulation and Research Gap Generation (2026-10-24)

- **Status**: Accepted
- **Context**: While Lattice effectively detects contradictions and coverage gaps in the evidence matrix, researchers and autonomous AI agents needed an automated, structured formulation mechanism to propose testable next hypotheses (with explicit independent and dependent variables, predicted interaction directions, and recommended study designs) to resolve scientific tension or investigate unbacked questions.
- **Decision**:
  1. Implement `propose_hypotheses` in `lattice.analysis`, classifying targets into reconciliation hypotheses (for contested questions with opposing supporting and contradicting claims) and gap-filling hypotheses (for questions with zero linked claims).
  2. Deterministically extract candidate independent and dependent variables from question prompts using verbal/clausal splitters (`improve`, `enhance`, `increase`, `affect`, `consolidate`, `in`) and domain keyword extraction.
  3. Formulate structured dictionaries containing `id`, `question_id`, `kind` (`reconciliation` | `gap_fill`), `statement`, `independent_variable`, `dependent_variable`, `predicted_effect` (`interaction` | `positive`), `recommended_study_type`, `rationale`, and supporting/contradicting claim IDs.
  4. Expose `propose_hypotheses` across all interfaces: `lattice hypothesize [TARGET]` CLI command, `propose_hypotheses` in `lattice.api`, `client.propose_hypotheses()` on `LatticeClient` and `AsyncLatticeClient`, and the `propose_hypotheses` MCP tool (added to `_READ_ONLY_TOOLS`).
- **Consequences**: Autonomous agents and scientists can programmatically generate principled, testable experimental hypotheses grounded directly in the graph's empirical gaps and conflicts. 213 unit tests pass, and zero third-party dependencies are required. No database schema changes.

## ADR-026: CSL-JSON Bibliography Ingestion and Universal Citation Interoperability (2026-10-24)

- **Status**: Accepted
- **Context**: While Lattice previously ingested BibTeX, RIS, CSV, Markdown, and plain text files, Citation Style Language JSON (CSL-JSON) is the universal modern exchange format used across citation managers (Zotero, Mendeley, Papers), bibliographic APIs (Crossref, DOI.org content negotiation), and toolchains (Citation.js, Pandoc). Ingesting research bibliographies exported in CSL-JSON or fetched directly from Crossref required external format conversion.
- **Decision**:
  1. Implement `parse_csl_json` in `lattice.ingest` using Python's standard library `json` module, with zero external dependencies.
  2. Support array format (`[{...}]`), single-item dictionaries (`{...}`), and container wrapper objects (`{"items": [...]}`).
  3. Map CSL-JSON fields defensively: extract title and shortTitle; normalize author lists from family/given name objects, literal names, or string representations; extract 4-digit publication years from `issued.date-parts` arrays, `issued.raw`, or string dates; extract container-title/journal/publisher for venue; map `DOI`, `URL`, `abstract`, and `tags`; infer or extract `arxiv` IDs from URL/eprint.
  4. Standardize study type extraction: respect explicit `study_type`/`study-type`, fallback to title/abstract heuristic inference via `infer_study_type`, map standard CSL types (e.g. `type: review` -> `"Review"`), and default to `"General Study"`.
  5. Extend `parse_file` suffix dispatch to accept `.csl` and `.json` extensions.
  6. Re-export `parse_csl_json` in `lattice.api` and verify export integrity with `tests/test_api.py`.
- **Consequences**: Researchers and downstream agents can directly ingest `.csl` and `.json` citation bibliographies and Crossref payloads into the Lattice evidence graph without conversion overhead. All 219 unit tests pass, and gate hygiene invariant is preserved with zero dependencies added. No database schema changes.

## ADR-027: Research Studio Visual Controls, Layout Modes, and Vector SVG Export (2026-10-24)

- **Status**: Accepted
- **Context**: The Web Research Studio previously rendered ego-network subgraphs using a single, static radial layout without relation-kind filtering controls. Researchers could not toggle specific edge types (e.g. isolating evidentiary `supports`/`contradicts`/`answers` links from citation or thematic links) or switch to a layered hierarchical layout (organizing questions, claims, and papers vertically). Furthermore, there was no vector export mechanism to download publication-ready SVG diagrams directly from the canvas, and pasted text ingestion lacked CSL-JSON format selection.
- **Decision**:
  1. Add relation visibility checkboxes to the Provenance Subgraph legend in `lattice.web` (`ef-supports`, `ef-contradicts`, `ef-answers`, `ef-related`, `ef-cites`) with reactive re-rendering.
  2. Implement layout mode selection (`graph-layout`): Radial (default ego-network circle) and Hierarchical (three vertical layers: questions at $y=65$, claims at $y=210$, papers at $y=355$).
  3. Add `downloadSvg()` action ("Export SVG") that serializes the rendered SVG DOM element into a standalone vector `.svg` file with XMLSerializer and Blob URL download.
  4. Expand the browser paste-ingest card with `csl-json` format option and wire `_handle_ingest_text` to parse pasted CSL-JSON payloads.
  5. Enforce all additions through the AIKit UI guard contract (`.aikit/ui.json`), maintaining 0 strikes and preserving the full baseline inventory.
- **Consequences**: Researchers have interactive visual control over graph density, edge types, and structure, and can export publication-grade SVG graphics directly without external tools. 220 unit tests, 25/25 dogfood steps, and UI guard verification pass. No schema changes.

## ADR-028: PRISMA 2020 Systematic Review Screening & Attrition Engine (2026-10-25)

- **Status**: Accepted
- **Context**: Systematic literature reviews and meta-analyses require auditable, reproducible study identification, screening, and attrition reporting conforming to the PRISMA 2020 statement (Preferred Reporting Items for Systematic Reviews and Meta-Analyses). While Lattice maintained an evidence graph of papers, claims, and relations, there was no native screening workflow to record title/abstract and full-text eligibility decisions, track specific exclusion reasons (e.g., wrong population, animal model, insufficient data), or generate publication-ready PRISMA 2020 flow diagrams.
- **Decision**:
  1. Add an auditable `screening` table to the database schema (`paper_id`, `status`, `reason`, `notes`, `screened_at`) with indexing on `paper_id` and `status`.
  2. Implement `lattice.screening` providing `ScreeningDecision` and `PrismaFlow` data structures, along with `record_screening_decision`, `get_screening_decision`, `list_screening_decisions`, and `compute_prisma_flow`.
  3. Support standardized status stages (`identified`, `screened_in`, `screened_out`, `included`, `excluded`) and predefined exclusion reason categories (`wrong_population`, `out_of_scope_design`, `animal_model`, `in_vitro_only`, `uncontrolled`, `insufficient_data`, `duplicate`, `other`).
  4. Generate both structured Markdown reports (`render_prisma_markdown`) and standalone, publication-ready vector SVG diagrams (`render_prisma_svg`) displaying the classic 4-phase PRISMA attrition pipeline (Identification -> Screening -> Eligibility -> Included) with explicit reason breakdowns.
  5. Expose screening capabilities across all interfaces: `lattice screen` and `lattice prisma` CLI commands, `lattice.api` public facade, MCP tools `screen_paper` and `get_prisma_flow` (with read-only filtering), and convenience methods on `LatticeClient` and `AsyncLatticeClient`.
- **Consequences**: Researchers and autonomous systematic review agents can conduct reproducible screening workflows and generate compliant PRISMA flowcharts directly from the graph with zero external dependencies. 228 unit tests pass, and gate hygiene invariant is maintained.

## ADR-029: Token-Bounded GraphRAG Context Pack Engine (2026-10-25)

- **Status**: Accepted
- **Context**: Autonomous LLM agents and retrieval-augmented generation (RAG) systems querying Lattice need high-density, citation-anchored context packs. Prior views either returned unoriented shallow subgraphs (`subgraph`), isolated search snippets (`search`), or full synthesis reports (`synthesize`) without adaptive multi-target assembly or deterministic compaction. Downstream agents risked context window overflow when injecting multi-hop evidence clusters or scientific tension.
- **Decision**:
  1. Implement `build_context_pack` and `ContextPack` in `lattice.context` to assemble structured GraphRAG context packages for arbitrary target sets (questions, claims, papers, or search queries).
  2. Structure the context pack with 4 core evidentiary layers: (1) Target Questions & Status, (2) Evidentiary Claims with verbatim quote anchors, confidence scores, and source paper provenance, (3) Scientific Contradictions and Tension Callouts, and (4) Bibliographic Source Details.
  3. Support both human/agent Markdown and machine JSON serializations.
  4. Implement deterministic token-budgeted compaction: prioritize keystone claims participating in scientific contradictions and high-confidence evidence; iteratively trim lower-weight claims with explicit omission annotations when exceeding `max_tokens`.
  5. Expose context packs across all access layers: `lattice pack [TARGET...]` CLI command, `lattice.api` public re-exports, `get_context_pack` MCP tool (added to `_READ_ONLY_TOOLS`), and `client.get_context_pack()` on `LatticeClient` and `AsyncLatticeClient`.
- **Consequences**: Autonomous reasoning agents can retrieve self-contained, citation-anchored GraphRAG context packs strictly bounded by token budgets without losing quote provenance or scientific tension. 233 unit tests pass with zero third-party dependencies.

## ADR-030: Quantitative Effect Sizes and Forest Plot Generation (2026-10-25)

- **Status**: Accepted
- **Context**: Systematic literature reviews require quantitative meta-analytic pooling to synthesize empirical effect sizes across heterogeneous studies. Prior to this decision, Lattice provided qualitative consensus scoring and contradiction detection, but lacked statistical pooling models (inverse-variance fixed effects and DerSimonian-Laird random effects), heterogeneity quantification (Cochran's Q, Higgins' I², and τ²), or visual Forest Plot generators.
- **Decision**:
  1. Implement `lattice.meta` providing `MetaStudy` and `MetaAnalysisResult` data structures, along with `compute_meta_analysis`, `meta_analyze_question`, `study_from_confidence_interval`, and `study_from_two_groups`.
  2. Implement fixed-effect inverse-variance pooling and DerSimonian-Laird random-effects pooling (τ², Q, df, I²) with chi-square p-value calculation using pure Python standard library `math` and incomplete gamma series expansion (zero external dependencies).
  3. Render aligned terminal-friendly **ASCII Forest Plots** (`render_forest_ascii`) and publication-grade, self-contained vector **SVG Forest Plots** (`render_forest_svg`) with weighted study effect squares, confidence interval whiskers, zero reference lines, and summary diamonds.
  4. Expose meta-analysis across all interfaces: `lattice meta [TARGET]` CLI command (supporting both question references and JSON study files), `lattice.api` public re-exports, `compute_meta_analysis` MCP tool (added to `_READ_ONLY_TOOLS`), and convenience methods on `LatticeClient` and `AsyncLatticeClient`.
- **Consequences**: Researchers and autonomous systematic review agents can quantitatively pool effect sizes, evaluate between-study heterogeneity, and generate publication-ready forest plots directly from the graph with zero dependencies. 241 unit tests pass and gate hygiene invariant is maintained.

## Licensing migration (v0.4.0-agpl)

- New versions use the Aegean License 1.1 (AL-1.1); versions up to and including `v0.4.0-agpl` remain under GNU AGPL-3.0.
- Rights holder: AegeanWorks; commercial use under ACL-1.0.
- Counsel review of the 1.1 texts remains pending.
