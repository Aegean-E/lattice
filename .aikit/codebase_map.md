# Codebase Map & Symbol Catalog 🗺️

> **AUTO-GENERATED & VERIFIED BY `scripts/update_knowledge_base.py`**
> This document provides an automated, up-to-date registry of all modules, classes, and exported functions across this repository.

---

## 📊 Codebase Metrics
- **Total Python Modules**: `34`
- **Total Classes**: `43`
- **Total Top-Level Functions**: `170`
- **Total Class Methods**: `216`
- **Total Source Lines**: `8988`

---

## 📦 Modules & Exported Symbols

### [`lattice/__init__.py`](lattice/__init__.py)
> *Lattice: a provenance-first research knowledge graph for humans and AI agents.*

**Size**: `6` lines (`111` bytes)

---

### [`lattice/__main__.py`](lattice/__main__.py)
> *Run the command-line interface with `python -m lattice`.*

**Size**: `8` lines (`154` bytes)

---

### [`lattice/analysis.py`](lattice/analysis.py)
> *Contradiction detection, related-finding links, keystone ranking and evidence matrices.*

**Size**: `610` lines (`25235` bytes)

**Classes:**
- `class ContradictionPair` - *An opposing pair of empirical claims sharing a research question or high domain keyword overlap.*
  - Method `.to_dict()` - *JSON-serializable representation.*
- `class RelatedPair` - *Two findings related by a shared research question or a domain-keyword overlap.*
  - Method `.to_dict()` - *JSON-serializable representation.*

**Functions:**
- `def _domain_keywords(text)` - *Extract informative domain keywords of length >= 4 from claim text.*
- `def _claim_question_map(repo)` - *Map bare claim IDs to bare question IDs linked via edges.*
- `def _find_or_create_contradicts_edge(repo, claim_a_id, claim_b_id, auto_link)` - *Return existing `contradicts` edge ID between two claims, or create one when `auto_link` is True.*
- `def detect_contradictions(repo, auto_link)` - *Detect pairs of opposing claims (`supports` vs `contradicts`) across questions or domain topics.*
- `def _connected_claim_pairs(repo)` - *Unordered bare claim-ID pairs that any claim-to-claim edge already joins.*
- `def find_related_findings(repo, claim_ids, limit_per_claim)` - *Detect findings sharing a research question or enough domain keywords to be related.*
- `def link_related_findings(repo, claim_ids, limit_per_claim)` - *Create `related` edges for detected finding pairs that are not linked yet.*
- `def _related_reason(entry)` - *Human-readable explanation of why a finding is related.*
- `def related_findings(repo, ref, limit)` - *Findings connected to a claim, paper or question, with reasons and next-hop references.*
- `def rank_influential_entities(repo, limit)` - *Rank keystone papers and claims by evidence centrality, citation degree, and confidence.*
- `def build_evidence_matrix(repo)` - *Build a Paper x Question evidence matrix highlighting stance cells and coverage gaps.*

---

### [`lattice/checks.py`](lattice/checks.py)
> *Integrity gate: every citation, endpoint, quote and support cycle is decidable locally.*

**Size**: `202` lines (`8098` bytes)

**Classes:**
- `class CheckIssue` - *One finding, tagged error or warning and named by a stable code.*
  - Method `.to_dict()` - *JSON-ready representation.*
- `class CheckReport` - *The gate's complete result; only errors block delivery.*
  - Property `.errors` - *Blocking findings.*
  - Property `.warnings` - *Non-blocking findings.*
  - Property `.passed` - *True when no blocking finding exists.*
  - Method `.to_dict()` - *JSON-ready representation used by the CLI and MCP clients.*

**Functions:**
- `def run_checks(repository)` - *Run every integrity check and return one report.*
- `def _check_schema(connection, report)` - *The database must declare this build's schema version.*
- `def _check_claims(connection, report)` - *Every claim needs assertion text, a quote and an existing paper.*
- `def _check_edges(connection, report)` - *Both endpoints of every edge must exist.*
- `def _check_duplicates(connection, report)` - *DOI, arXiv and normalized title/year duplicates are errors.*
- `def _check_support_cycles(connection, report)` - *Support and extension relations between claims must stay acyclic.*
- `def _cycles(graph)` - *Every distinct cycle reachable in a directed graph, each reported once.*
- `def _canonical_cycle(cycle)` - *A rotation-independent form so the same cycle is reported once.*
- `def _check_orphans(connection, report)` - *Warnings for questions without evidence and claims with no question link.*
- `def _exists(connection, ref)` - *Whether a reference's target row exists.*
- `def summarize(report)` - *Error and warning counts for a compact text report.*

---

### [`lattice/cli.py`](lattice/cli.py)
> *Command-line interface: ingest, assert, link, ask, brief, review, check and serve MCP.*

**Size**: `583` lines (`26155` bytes)

**Functions:**
- `def build_parser()` - *The complete command grammar.*
- `def main(argv)` - *Parse arguments, open the database and dispatch one command.*
- `def _emit(payload, lines, as_json)` - *Print either stable JSON or human text.*
- `def _run_init(args, repository)` - *Create the schema, which opening the database already did.*
- `def _run_ingest(args, repository)` - *Import every file and report created versus merged records.*
- `def _run_fetch(args, repository)` - *Discover candidate papers and optionally ingest them.*
- `def _run_extract(args, repository)` - *Extract quote-backed claims and question links from one or all papers.*
- `def _run_claim(args, repository)` - *Record one claim.*
- `def _run_question(args, repository)` - *Record one question.*
- `def _run_link(args, repository)` - *Record one typed edge.*
- `def _run_search(args, repository)` - *Search and print the three result sections.*
- `def _run_show(args, repository)` - *Show one entity and each attached edge.*
- `def _run_subgraph(args, repository)` - *Traverse and print the multi-hop neighborhood around an entity.*
- `def _run_related(args, repository)` - *List findings connected to an entity, with the reason for each connection.*
- `def _run_outline(args, repository)` - *Print a cheap orientation index before an agent expands a reference.*
- `def _run_ask(args, repository)` - *Assemble and print evidence.*
- `def _run_brief(args, repository)` - *Print a token-budgeted evidence pack.*
- `def _run_review(args, repository)` - *Print or write a review outline.*
- `def _run_synthesize(args, repository)` - *Generate a consensus-scored scientific synthesis report.*
- `def _run_export(args, repository)` - *Export the graph to an atomic JSONL snapshot.*
- `def _run_import(args, repository)` - *Import a JSONL snapshot idempotently.*
- `def _run_stats(args, repository)` - *Print counts.*
- `def _run_check(args, repository)` - *Run the integrity gate and return 1 on any error.*
- `def _run_mcp(args, repository)` - *Serve MCP on stdio; stdout carries protocol messages only.*
- `def _run_web(args, repository)` - *Launch the Research Studio web UI, optionally seeding demo data or dumping HTML.*
- `def _run_analyze(args, repository)` - *Detect contradictions and related findings, rank keystones, and build the matrix.*

---

### [`lattice/context.py`](lattice/context.py)
> *Token-budgeted context views for AI agents: peek, search, expand, drill down.*

**Size**: `202` lines (`7652` bytes)

**Functions:**
- `def _budget(tokens)` - *Validate a token budget and return it as an integer.*
- `def _truncate(text, limit)` - *Collapse whitespace and shorten a value to `limit` characters.*
- `def _cost(item)` - *Estimated tokens of one JSON item.*
- `def _pack(items, tokens)` - *Keep as many leading items as fit, returning `(kept, omitted, used_tokens)`.*
- `def outline(repository, tokens)` - *A cheap orientation map: counts, edge kinds, study types and evidenced questions.*
- `def compact_search(result, tokens)` - *Search hits as short handles, split across papers, claims and questions.*
- `def compact_related(result, tokens)` - *Related-finding navigation as short snippets, reasons and next-hop refs.*
- `def compact_subgraph(result, tokens)` - *A subgraph as short node labels and bare edges, trimmed around a token budget.*

---

### [`lattice/database.py`](lattice/database.py)
> *SQLite connection, versioned schema and migration veil for the knowledge graph.*

**Size**: `164` lines (`6270` bytes)

**Functions:**
- `def utc_now()` - *An ISO-8601 UTC timestamp with a stable seconds precision.*
- `def open_database(path)` - *Open or create the database, verify its schema version and return it.*
- `def _ensure_schema(connection)` - *Create the schema once, migrate v1 and refuse a database from a newer version.*
- `def _set_schema_version(connection, version)` - *Persist the schema version after a fresh create or a completed migration.*
- `def _add_column_if_missing(connection, table, column, definition)` - *Add one column once, so an interrupted migration can be retried.*
- `def _migrate_v1_to_v2(connection)` - *Add searchable tags and study type, backfilling them for existing papers.*
- `def schema_version(connection)` - *The declared schema version, or 0 when the metadata row is missing.*

---

### [`lattice/discovery.py`](lattice/discovery.py)
> *Pluggable automated literature discovery: arXiv, Crossref, OpenAlex, EuropePMC, and offline corpus.*

**Size**: `571` lines (`24042` bytes)

**Classes:**
- `class PaperCandidate` - *Immutable DTO returned by any literature discovery provider.*
  - Method `.to_metadata()` - *Dictionary ready for `Repository.add_paper`.*
  - Method `.to_dict()` - *JSON-serializable representation including discovery source.*
- `class LiteratureProvider` - *Contract layer for pluggable scientific literature search providers.*
  - Method `.search(query, limit)` - *Return up to `limit` candidate papers matching `query`.*
- `class ProviderRegistry` - *Registry layer mapping provider names to `LiteratureProvider` implementations.*
  - Method `.__init__()`
  - Method `.register(name, provider)` - *Register or replace a provider by lowercase key.*
  - Method `.get(name)` - *Look up a registered provider or raise `LatticeError`.*
  - Method `.names()` - *Sorted list of registered provider names.*
- `class ArxivProvider` - *Concrete provider querying the arXiv Atom API.*
  - Method `.__init__(fetcher, timeout)`
  - Method `.search(query, limit)` - *Search arXiv by query terms and parse Atom XML entries.*
- `class CrossrefProvider` - *Concrete provider querying the Crossref REST works endpoint.*
  - Method `.__init__(fetcher, timeout)`
  - Method `.search(query, limit)` - *Search Crossref works and normalize bibliographic items.*
- `class OpenAlexProvider` - *Concrete provider querying the OpenAlex works REST endpoint.*
  - Method `.__init__(fetcher, timeout)`
  - Method `.search(query, limit)` - *Search OpenAlex works and reconstruct inverted-index abstracts.*
- `class EuropePmcProvider` - *Concrete provider querying the EuropePMC biomedical REST API.*
  - Method `.__init__(fetcher, timeout)`
  - Method `.search(query, limit)` - *Search EuropePMC articles and extract biomedical metadata and abstracts.*
- `class OfflineCorpusProvider` - *Deterministic local provider over a curated seed catalog for offline/instant search.*
  - Method `.__init__(records)`
  - Method `.search(query, limit)` - *Rank local corpus records by token overlap with `query`.*
- `class DiscoveryService` - *Orchestration layer with constructor DI for discovering and ingesting papers.*
  - Method `.__init__(repository, registry)`
  - Method `.discover(query, source, limit, ingest)` - *Search one or comma-separated `source` providers and optionally ingest papers.*

**Functions:**
- `def _http_get(url, timeout)` - *Perform a bounded HTTP GET with a scholarly User-Agent header.*
- `def default_registry()` - *Create the default provider registry with offline, arXiv, Crossref, OpenAlex, and EuropePMC.*
- `def _dedupe_candidates(candidates)` - *Deduplicate candidate papers across providers by DOI, arXiv ID, or normalized title.*
- `def _reconstruct_inverted_abstract(inverted)` - *Reconstruct a plain-text abstract from an OpenAlex inverted index mapping.*
- `def _validate_search_args(query, limit)` - *Ensure a discovery query is non-empty and `limit` is positive.*
- `def _format_crossref_authors(authors)` - *Join Crossref author objects into `Given Family; Given Family`.*
- `def _extract_crossref_year(item)` - *Extract a 4-digit publication year from Crossref date-parts.*

---

### [`lattice/errors.py`](lattice/errors.py)
> *The one error type every layer raises, carrying the Error/Why/Fix triad.*

**Size**: `22` lines (`738` bytes)

**Classes:**
- `class LatticeError` - *A user-facing failure: what happened, why it matters and how to fix it.*
  - Method `.__init__(message, why, fix)`
  - Method `.render()` - *The full three-line report used by the CLI and the MCP server.*

**Functions:**
- `def fail(message, why, fix)` - *Raise a `LatticeError`; keeps call sites to one line.*

---

### [`lattice/extraction.py`](lattice/extraction.py)
> *Automated knowledge creation: extract quote-backed claims and question links from papers.*

**Size**: `222` lines (`8833` bytes)

**Classes:**
- `class ExtractionResult` - *Immutable summary of claims and edges extracted from a single paper.*
  - Method `.to_dict()` - *JSON-ready representation.*

**Functions:**
- `def split_empirical_sentences(text, prefix)` - *Split text into `(locator, sentence)` pairs, keeping sentences with empirical findings.*
- `def infer_stance(sentence)` - *Classify an empirical sentence as `supports`, `contradicts`, or `mentions`.*
- `def infer_confidence(sentence)` - *Assign a deterministic confidence weight in [0.55, 0.95] from evidential markers.*
- `def extract_from_paper(repository, paper_ref, question_ref, text)` - *Extract quote-backed claims from a paper and link them to matching or target questions.*
- `def extract_all(repository, question_ref)` - *Run claim and edge extraction across every ingested paper in the graph.*
- `def _is_empirical(sentence)` - *Whether a sentence carries quantitative or empirical indicators.*
- `def _matches_question(sentence, title, question_text)` - *Whether a claim sentence and its paper title share content keywords with a question.*
- `def _safe_add_edge(repository, src, dst, kind, note)` - *Add an edge if it does not already exist.*

---

### [`lattice/ingest.py`](lattice/ingest.py)
> *Parsers for the text bibliography formats lattice accepts, with no third-party dependencies.*

**Size**: `253` lines (`9238` bytes)

**Functions:**
- `def empty_record()` - *A record with every supported metadata field present.*
- `def _clean(value)` - *Collapse whitespace and strip one layer of surrounding delimiters.*
- `def _braced_span(text, start)` - *Index of the brace closing the one at `start`, or -1 when it is unbalanced.*
- `def _split_top_level(text)` - *Split a BibTeX field list on commas that are not inside braces or quotes.*
- `def parse_bibtex(text)` - *Parse one or more BibTeX entries into metadata records.*
- `def parse_ris(text)` - *Parse RIS records into metadata records.*
- `def parse_csv(text)` - *Parse a CSV with a header row naming any of the supported metadata fields.*
- `def parse_markdown(text, source_name)` - *Parse one Markdown note: YAML-like front matter, a heading or the filename as title.*
- `def parse_text(text, source_name)` - *Parse a plain-text note as one record titled by its filename.*
- `def parse_file(path)` - *Detect a file's format by suffix and parse it.*
- `def parse_paths(paths)` - *Parse every path in order and concatenate the records.*

---

### [`lattice/inquiry.py`](lattice/inquiry.py)
> *Evidence-first question answering: `ask`, token-budgeted `brief` and `review` outlines.*

**Size**: `308` lines (`12959` bytes)

**Functions:**
- `def ask(repository, target, limit)` - *Return evidence for a question, or matching claims when the target is a search phrase.*
- `def brief(repository, target, tokens)` - *Pack the strongest evidence for an agent under a deterministic token budget.*
- `def review(repository, target)` - *A Markdown literature-review outline with every citation resolved in the graph.*
- `def _match_question(repository, target)` - *A question named by reference, exact text or unique substring.*
- `def _suggestions(repository, question, linked, limit)` - *Unlinked claims whose text matches a keyword from the question.*
- `def _keywords(text)` - *Distinct lowercase words of at least four letters, without common question words.*
- `def _question_header(evidence)` - *The fixed header of a question brief.*
- `def _claim_line(item)` - *One evidence line: claim, confidence, quote and source.*
- `def _search_line(claim)` - *One search hit line.*
- `def _suggestion_lines(suggestions)` - *Unlinked claim candidates, one line each.*
- `def _fits(lines, candidate, tokens)` - *Whether adding one line keeps the estimate under the budget.*
- `def _fit(lines, candidates, tokens)` - *Append candidate lines while the running estimate stays under the budget.*
- `def _citation_lines(repository, refs)` - *Resolved citation lines for paper references, in first-seen order.*
- `def _citation_short(paper)` - *A compact inline source label.*
- `def _question_review(evidence)` - *Render a question's evidence as a review outline.*
- `def _review_section(title, items)` - *One evidence section of a review outline.*
- `def _paper_refs(evidence)` - *Distinct paper references touched by evidence or search results.*
- `def _search_review(evidence)` - *Render matching papers and claims when the target is not a tracked question.*

---

### [`lattice/mcp.py`](lattice/mcp.py)
> *A dependency-free MCP stdio server exposing the graph as JSON-RPC tools.*

**Size**: `343` lines (`17193` bytes)

**Functions:**
- `def _tool(name, description, properties, required)` - *An MCP tool declaration with a JSON Schema for its arguments.*
- `def handle_message(repository, message)` - *Dispatch one JSON-RPC message; notifications return None.*
- `def _call_tool(repository, request_id, params)` - *Run one MCP tool call and wrap the result as text content.*
- `def _read_resource(repository, request_id, params)` - *Return an MCP resource payload by URI.*
- `def _get_prompt(repository, request_id, params)` - *Render a structured scientific synthesis prompt for an AI agent.*
- `def _dispatch(repository, name, arguments)` - *Map a tool name to its repository, discovery, extraction or synthesis operation.*
- `def _text(arguments, name)` - *A required string argument.*
- `def _result(request_id, result)` - *A JSON-RPC success response.*
- `def _error(request_id, code, message)` - *A JSON-RPC error response.*
- `def serve(repository, stdin, stdout)` - *Serve newline-delimited JSON-RPC until the input stream closes.*

---

### [`lattice/models.py`](lattice/models.py)
> *Value objects and the validation rules shared by storage, ingestion and queries.*

**Size**: `331` lines (`11378` bytes)

**Classes:**
- `class Paper` - *A source record: bibliographic metadata plus its stable identifier.*
  - Method `.to_dict()` - *JSON-ready representation.*
- `class Claim` - *One asserted statement tied to an exact source quote and locator.*
  - Method `.to_dict()` - *JSON-ready representation.*
- `class Question` - *A research question whose evidence is assembled from linked claims.*
  - Method `.to_dict()` - *JSON-ready representation.*
- `class Edge` - *A typed, directed relation between two entity references.*
  - Method `.to_dict()` - *JSON-ready representation, including resolved endpoint details when present.*

**Functions:**
- `def normalize_text(value)` - *Lowercase and collapse punctuation for identity comparisons.*
- `def normalize_tags(value)` - *Normalize comma- or semicolon-separated tags into one lowercase, deduplicated string.*
- `def derive_tags(title, abstract, limit)` - *Derive deterministic keyword tags, weighting title words over abstract words.*
- `def normalize_study_type(value)` - *Trim a study type and map common abbreviations to a canonical label.*
- `def infer_study_type(title, abstract)` - *Classify a paper by design markers in its title and abstract.*
- `def paper_id(title, doi, arxiv)` - *A stable identifier derived from DOI, then arXiv ID, then normalized title.*
- `def next_id(prefix, rows)` - *The next sequential identifier for a table whose ids share a prefix.*
- `def validate_stance(stance)` - *A claim stance must be one of `STANCES`.*
- `def parse_confidence(value)` - *Confidence is a number in [0, 1]; the default is 0.5.*
- `def validate_edge_kind(kind)` - *An edge kind must be one of `EDGE_KINDS`.*
- `def entity_type(ref)` - *The entity type named by a reference such as `claim:c_000001`.*
- `def validate_ref(ref)` - *Normalize `claim:c_000001` and reject malformed references.*
- `def bare_id(ref)` - *The identifier part of a reference.*
- `def estimate_tokens(text)` - *A deterministic, conservative token estimate used by `brief`.*

---

### [`lattice/repository.py`](lattice/repository.py)
> *The knowledge graph API: papers, claims, questions, typed edges and evidence queries.*

**Size**: `598` lines (`28737` bytes)

**Classes:**
- `class Repository` - *One connection's view of the graph; every write is committed before it returns.*
  - Method `.__init__(connection)`
  - Method `.add_paper(metadata)` - *Insert a paper, or merge missing metadata into the matching existing record.*
  - Method `.add_claim(paper, text, quote, locator, stance, confidence)` - *Record one claim with the exact source quote that grounds it.*
  - Method `.add_question(text)` - *Record a research question that evidence can later be linked to.*
  - Method `.add_edge(src, dst, kind, note)` - *Add a typed relation after checking both endpoints exist.*
  - Method `.get_paper(identifier)` - *A paper by bare id or reference.*
  - Method `.get_claim(identifier)` - *A claim by bare id or reference.*
  - Method `.get_question(identifier)` - *A question by bare id or reference.*
  - Method `.get(ref)` - *One entity and every edge attached to it.*
  - Method `.search(query, limit, stance, min_confidence, year)` - *Search papers, claims and questions by phrase or multi-term lexical overlap.*
  - Method `.search_literature(query, tags, study_type, year, limit)` - *Search papers by tags, words, sentences, study type or year.*
  - Method `.set_question_status(question, status)` - *Update a question's lifecycle status ('open', 'answered' or 'abandoned').*
  - Method `.subgraph(ref, depth)` - *Return the multi-hop neighborhood of nodes and edges around `ref`.*
  - Method `.neighbors(ref, kind)` - *Every edge touching `ref`, optionally narrowed to one kind.*
  - Method `.evidence(question)` - *Claims linked to a question, grouped by the stance of the link.*
  - Method `.stats()` - *Entity and edge counts for a quick orientation report.*
  - Method `._resolve(value)` - *Accept a full reference or a bare id and return the validated reference.*
  - Method `._row(query, *args)` - *One row or None.*
  - Method `._ids(table)` - *Every id in a table, used to allocate the next sequential claim or question id.*
  - Method `._find_paper(metadata)` - *Find a duplicate by DOI, arXiv ID, or normalized title and year.*
  - Method `._merge_paper(existing, metadata)` - *Fill fields the existing record lacks; return the names that changed.*
  - Method `._claim_dict(claim)` - *A claim plus a compact citation summary of its paper.*
  - Method `._safe_summary(ref)` - *Summary of an entity, or a missing marker instead of raising.*
  - Method `._summary(ref)` - *A compact JSON representation of any entity, with paper context for claims.*
  - Method `._study_type(ref)` - *The study type behind a paper or claim, or every type linked to a question.*
  - Method `._log(action, payload)` - *Append an immutable audit event.*
  - Method `._search_papers(raw_query, terms, year, limit)` - *Rank papers by exact substring match first, then multi-term lexical overlap.*
  - Method `._search_claims(raw_query, terms, stance, min_confidence, year, limit)` - *Rank claims by phrase or multi-term overlap and apply optional filters.*
  - Method `._search_questions(raw_query, terms, limit)` - *Rank questions by phrase or multi-term overlap.*

**Functions:**
- `def _paper(row)` - *Map a papers row to its value object.*
- `def _claim(row)` - *Map a claims row to its value object.*
- `def _question(row)` - *Map a questions row to its value object.*
- `def _edge(row)` - *Map an edges row to its value object.*
- `def _lexical_score(needle, terms, blob, primary)` - *Compute a deterministic relevance score combining exact substring and multi-term hits.*
- `def _normalize_doi(value)` - *Strip resolver prefixes and lowercase a DOI.*
- `def _normalize_arxiv(value)` - *Strip the arXiv prefix from an identifier.*

---

### [`lattice/snapshots.py`](lattice/snapshots.py)
> *Portable JSONL graph snapshots with atomic write and idempotent merge import.*

**Size**: `213` lines (`8393` bytes)

**Functions:**
- `def export_snapshot(repository, path)` - *Write all papers, questions, claims and edges to a portable JSONL file atomically.*
- `def import_snapshot(repository, path)` - *Import a JSONL snapshot idempotently, remapping entity references as needed.*
- `def _parse_jsonl(lines, label)` - *Parse non-empty JSONL lines and verify each is an object.*
- `def _import_question(repository, record)` - *Find an existing question with the same text or create it.*
- `def _import_claim(repository, record, paper_map)` - *Find an existing claim on the target paper or create it.*
- `def _import_edge(repository, record, paper_map, claim_map, question_map)` - *Remap endpoints and insert the edge if not already present.*
- `def _remap_ref(ref, paper_map, claim_map, question_map)` - *Translate an exported entity reference to its imported identifier.*

---

### [`lattice/synthesis.py`](lattice/synthesis.py)
> *Scientific literature synthesis engine: consensus scoring, thematic clustering, and BibTeX.*

**Size**: `319` lines (`13220` bytes)

**Classes:**
- `class SynthesisReport` - *Immutable structured synthesis for AI agents and human literature reviews.*
  - Method `.to_dict()` - *JSON-serializable representation.*

**Functions:**
- `def compute_consensus(supporting, contradicting, neutral)` - *Compute a confidence-weighted consensus score in [-1.0, 1.0] and classification label.*
- `def cluster_claims(claims)` - *Group claims into thematic clusters by dominant domain keyword.*
- `def format_bibtex(papers)` - *Format paper dictionaries as deterministic BibTeX entries.*
- `def synthesize(repository, target, tokens)` - *Produce a token-bounded, citation-checked scientific synthesis for a question or query.*
- `def _dominant_theme(text)` - *Select the most informative domain keyword from a claim sentence.*
- `def _inline_citation(paper)` - *Format `Author (Year) [p_xxx]` for inline evidence attribution.*
- `def _collect_bibliography(repository, claims, extra_papers)` - *Collect unique resolved paper records referenced by claims or search results.*
- `def _build_follow_up_queries(query_text, consensus, suggestions, bibliography)` - *Generate actionable follow-up scientific queries for AI agents.*
- `def _render_markdown(query_text, mode, consensus, clusters, gaps, follow_ups, bibliography, tokens)` - *Render a deterministic, token-bounded Markdown literature synthesis report.*

---

### [`lattice/web.py`](lattice/web.py)
> *Zero-dependency web server and human-friendly Research Studio UI for Lattice.*

**Size**: `1655` lines (`64947` bytes)

**Classes:**
- `class WebResponse` - *Immutable HTTP response returned by `dispatch_web_request`.*

**Functions:**
- `def dispatch_web_request(repository, method, path, body)` - *Route an HTTP method and path to the UI or JSON API without network sockets.*
- `def _dispatch_post(repository, route, payload)` - *Handle JSON POST routes for mutations, discovery, extraction, and demo seeding.*
- `def _build_overview(repository)` - *Assemble full workspace state for the Human UI dashboard.*
- `def _handle_search(repository, query)` - *Run filtered search from query parameters.*
- `def _handle_literature(repository, query)` - *Search the literature by tags, words, sentences, study type and year.*
- `def _handle_subgraph(repository, query)` - *Run multi-hop subgraph traversal from query parameters.*
- `def _handle_synthesize(repository, query)` - *Run scientific literature synthesis from query parameters.*
- `def _build_matrix_bundle(repository)` - *Assemble the Paper x Question evidence matrix, contradictions, and keystone ranking.*
- `def _handle_ingest_text(repository, payload)` - *Parse raw bibliography or note text (BibTeX, RIS, CSV, Markdown, text) and ingest into the graph.*
- `def _export_jsonl_string(repository)` - *Serialize all graph entities and edges as portable JSONL text.*
- `def _seed_demo(repository)` - *Populate the built-in seed corpus, create research questions, and extract claims.*
- `def _first(query, key)` - *First query parameter value or empty string.*
- `def _parse_json_body(body)` - *Parse an optional JSON request body into a dictionary.*
- `def _json_response(status, payload)` - *Serialize a dictionary as an application/json `WebResponse`.*
- `def serve_web(db_path, host, port, open_browser, once)` - *Run the local HTTP server for the Lattice Research Studio UI.*

---

### [`tests/__init__.py`](tests/__init__.py)
> *Regression suite for lattice.*

**Size**: `1` lines (`36` bytes)

---

### [`tests/test_analysis.py`](tests/test_analysis.py)
> *Unit tests for scientific contradiction detection, keystone centrality, and evidence matrix analysis.*

**Size**: `290` lines (`14779` bytes)

**Classes:**
- `class TestAnalysis` - *Verify contradiction detection, keystone entity ranking, and Paper x Question evidence matrix.*
  - Method `.setUp()`
  - Method `._seed_conflicting_graph()`
  - Method `.test_detect_contradictions_and_idempotent_auto_link()`
  - Method `.test_find_and_link_related_findings_is_deterministic_and_idempotent()`
  - Method `.test_related_link_requires_question_or_two_shared_keywords()`
  - Method `.test_related_linking_skips_opposing_and_already_connected_pairs()`
  - Method `.test_related_linking_caps_links_per_claim()`
  - Method `.test_related_findings_navigates_claim_paper_and_question()`
  - Method `.test_related_findings_navigation_works_before_linking()`
  - Method `.test_rank_influential_entities_returns_keystone_papers_and_claims()`
  - Method `.test_build_evidence_matrix_identifies_cells_and_coverage_gaps()`

---

### [`tests/test_checks.py`](tests/test_checks.py)
> *The integrity gate catches broken provenance, endpoints, duplicates and cycles.*

**Size**: `70` lines (`3308` bytes)

**Classes:**
- `class CheckTests` - *Each test injects one defect into an otherwise clean graph.*
  - Method `.setUp()`
  - Method `.test_clean_graph_passes()`
  - Method `.test_warning_for_unlinked_claim()`
  - Method `.test_cycle_is_an_error()`
  - Method `.test_missing_endpoint_is_an_error()`
  - Method `.test_empty_quote_is_an_error()`
  - Method `.test_doi_duplicate_is_an_error()`
  - Method `.test_question_without_evidence_is_a_warning()`

---

### [`tests/test_cli.py`](tests/test_cli.py)
> *End-to-end command contracts without spawning subprocesses.*

**Size**: `234` lines (`10271` bytes)

**Classes:**
- `class CliTests` - *Drive the real parser and handlers against a temporary database.*
  - Method `.setUp()`
  - Method `.run_cli(*arguments)`
  - Method `.ingest_fixture()`
  - Method `.test_related_command_reports_and_links_findings()`
  - Method `.test_init_is_idempotent()`
  - Method `.test_ingest_question_claim_link_ask()`
  - Method `.test_json_output()`
  - Method `.test_brief_and_review_file()`
  - Method `.test_check_passes_and_reports()`
  - Method `.test_user_error_prints_triad()`
  - Method `.test_search_and_stats()`
  - Method `.test_fetch_extract_synthesize_subgraph_and_snapshots()`
  - Method `.test_web_subcommand_demo_and_dump_html()`
  - Method `.test_outline_command_reports_a_cheap_index()`
  - Method `.test_compact_token_views_for_related_subgraph_and_search()`
  - Method `.test_analyze_subcommand()`

---

### [`tests/test_context.py`](tests/test_context.py)
> *Unit tests for the token-budgeted, RLM-style AI context views.*

**Size**: `153` lines (`6717` bytes)

**Classes:**
- `class ContextViewTests` - *Verify compact payloads, truncation, omission counts and the budget floor.*
  - Method `.setUp()`
  - Method `.test_outline_reports_counts_questions_and_study_types()`
  - Method `.test_outline_omits_questions_over_a_small_budget()`
  - Method `.test_compact_search_truncates_items_and_reports_omissions()`
  - Method `.test_compact_related_drops_full_text_but_keeps_reasons_and_refs()`
  - Method `.test_compact_subgraph_keeps_only_edges_between_kept_nodes()`
  - Method `.test_budgets_below_the_floor_fail_with_the_triad()`

---

### [`tests/test_database.py`](tests/test_database.py)
> *Schema migration from the first release keeps an existing graph usable.*

**Size**: `85` lines (`2717` bytes)

**Classes:**
- `class MigrationTests` - *A version 1 database gains the literature metadata columns without losing papers.*
  - Method `.setUp()`
  - Method `.test_v1_database_migrates_tags_and_study_type()`

---

### [`tests/test_discovery.py`](tests/test_discovery.py)
> *Tests for pluggable automated literature discovery (arXiv, Crossref, and offline corpus).*

**Size**: `222` lines (`9254` bytes)

**Classes:**
- `class DiscoveryTests` - *Verify the 4-layer discovery boundary: DTOs, registry, providers, and service DI.*
  - Method `.setUp()`
  - Method `.test_paper_candidate_is_frozen_and_converts_to_metadata()`
  - Method `.test_registry_registers_and_resolves_providers()`
  - Method `.test_arxiv_provider_parses_atom_xml()`
  - Method `.test_crossref_provider_parses_json_and_strips_jats_tags()`
  - Method `.test_openalex_provider_reconstructs_inverted_index_abstract()`
  - Method `.test_europepmc_provider_parses_biomedical_results()`
  - Method `.test_offline_provider_searches_curated_seed_catalog()`
  - Method `.test_discovery_service_ingests_and_deduplicates_across_federated_sources()`

---

### [`tests/test_extraction.py`](tests/test_extraction.py)
> *Tests for automated knowledge creation and claim extraction from ingested papers.*

**Size**: `114` lines (`5305` bytes)

**Classes:**
- `class ExtractionTests` - *Verify deterministic sentence splitting, stance/confidence scoring, and claim/edge creation.*
  - Method `.setUp()`
  - Method `.test_split_empirical_sentences_handles_abbreviations_and_decimals()`
  - Method `.test_infer_stance_and_confidence()`
  - Method `.test_extract_from_paper_creates_claims_and_links_question()`
  - Method `.test_extract_from_paper_links_related_findings_automatically()`
  - Method `.test_extract_all_processes_every_paper_and_auto_matches_questions()`
  - Method `.test_extract_from_missing_paper_raises_lattice_error()`

---

### [`tests/test_ingest.py`](tests/test_ingest.py)
> *Format parsers stay dependency-free and deterministic.*

**Size**: `138` lines (`5141` bytes)

**Classes:**
- `class BibtexTests` - *BibTeX braces, authors and identifiers.*
  - Method `.test_two_entries()`
  - Method `.test_unbalanced_braces_fail()`
  - Method `.test_keywords_and_study_type_fields()`
- `class RisTests` - *RIS tag handling.*
  - Method `.test_single_record()`
  - Method `.test_keywords_and_study_type_tags()`
- `class CsvTests` - *CSV headers map to metadata fields case-insensitively.*
  - Method `.test_header_mapping()`
  - Method `.test_keyword_and_study_type_aliases()`
- `class MarkdownTests` - *Front matter and heading fallbacks.*
  - Method `.test_front_matter()`
  - Method `.test_heading_and_filename_fallbacks()`
  - Method `.test_front_matter_carries_tags_and_study_type()`
- `class FileTests` - *Suffix dispatch and readable failures.*
  - Method `.setUp()`
  - Method `.write(name, content)`
  - Method `.test_plain_text()`
  - Method `.test_parse_paths()`
  - Method `.test_unsupported_suffix()`

---

### [`tests/test_inquiry.py`](tests/test_inquiry.py)
> *Ask, brief and review are deterministic and never invent a citation.*

**Size**: `84` lines (`3680` bytes)

**Classes:**
- `class InquiryTests` - *A small graph with one supporting, one contradicting and one unrelated claim.*
  - Method `.setUp()`
  - Method `.test_ask_question()`
  - Method `.test_ask_by_text()`
  - Method `.test_ask_search_mode()`
  - Method `.test_brief_contains_sections_and_citations()`
  - Method `.test_brief_respects_tight_budget()`
  - Method `.test_brief_rejects_tiny_budget()`
  - Method `.test_review_markdown()`
  - Method `.test_review_search_mode()`
  - Method `.test_suggestions_exclude_linked_claims()`

---

### [`tests/test_mcp.py`](tests/test_mcp.py)
> *MCP JSON-RPC contracts and stdio framing.*

**Size**: `221` lines (`11129` bytes)

**Classes:**
- `class McpTests` - *Call the protocol handler directly; no sockets or spawns.*
  - Method `.setUp()`
  - Method `.call(method, params, request_id)`
  - Method `.tool(name, arguments)`
  - Method `.test_initialize()`
  - Method `.test_tools_list()`
  - Method `.test_related_findings_tool_navigates_and_links()`
  - Method `.test_add_question_and_search()`
  - Method `.test_search_budget_omits_lower_ranked_hits()`
  - Method `.test_outline_tool_returns_a_cheap_index()`
  - Method `.test_add_claim_reports_missing_paper()`
  - Method `.test_unknown_method()`
  - Method `.test_invalid_request()`
  - Method `.test_notification_has_no_response()`
  - Method `.test_stdio_serves_one_message()`
  - Method `.test_stdio_reports_parse_error()`
  - Method `.test_discover_extract_synthesize_and_subgraph_tools()`
  - Method `.test_resources_and_prompts_endpoints()`
  - Method `.test_analyze_and_contradictions_tools_and_matrix_resource()`

---

### [`tests/test_models.py`](tests/test_models.py)
> *Identity, validation and budget helpers.*

**Size**: `110` lines (`3576` bytes)

**Classes:**
- `class IdentityTests` - *Stable identifiers make dedupe and citations reproducible.*
  - Method `.test_doi_wins_over_title()`
  - Method `.test_arxiv_is_next()`
  - Method `.test_title_normalization()`
  - Method `.test_empty_identity_is_refused()`
  - Method `.test_bare_id()`
- `class ValidationTests` - *User input fails with the triad instead of a traceback.*
  - Method `.test_stance_accepts_case()`
  - Method `.test_stance_rejects_unknown()`
  - Method `.test_confidence_range()`
  - Method `.test_edge_kind()`
  - Method `.test_reference_forms()`
  - Method `.test_tokens_are_positive()`
- `class LiteratureMetadataTests` - *Study types and tags are normalized deterministically from paper metadata.*
  - Method `.test_study_type_inference()`
  - Method `.test_tag_normalization_and_derivation()`

---

### [`tests/test_repository.py`](tests/test_repository.py)
> *Graph writes, dedupe, references, search and evidence grouping.*

**Size**: `169` lines (`7611` bytes)

**Classes:**
- `class RepositoryTests` - *Every test gets a fresh in-memory graph.*
  - Method `.setUp()`
  - Method `.paper(title, **values)`
  - Method `.test_paper_dedupe_by_doi()`
  - Method `.test_paper_dedupe_by_normalized_title_and_year()`
  - Method `.test_merge_fills_missing_metadata()`
  - Method `.test_claim_requires_quote()`
  - Method `.test_claim_ids_are_sequential()`
  - Method `.test_question_and_edges()`
  - Method `.test_duplicate_edge_is_refused()`
  - Method `.test_self_edge_is_refused()`
  - Method `.test_missing_reference_is_refused()`
  - Method `.test_search_across_entities()`
  - Method `.test_paper_stores_tags_and_infers_study_type()`
  - Method `.test_literature_search_matches_tags_words_sentences_and_study_type()`
  - Method `.test_evidence_groups_and_gaps()`
  - Method `.test_stats_and_event_log()`
  - Method `.test_neighbors_filter_by_kind()`

---

### [`tests/test_snapshots.py`](tests/test_snapshots.py)
> *Tests for knowledge interaction: multi-term search, subgraphs, question status, and snapshots.*

**Size**: `135` lines (`5889` bytes)

**Classes:**
- `class InteractionAndSnapshotTests` - *Verify multi-term search, subgraph traversal, question status, and JSONL snapshot I/O.*
  - Method `.setUp()`
  - Method `.test_multi_term_search_and_filters()`
  - Method `.test_subgraph_traverses_multi_hop_neighborhood()`
  - Method `.test_set_question_status_updates_and_validates()`
  - Method `.test_export_and_import_snapshot_roundtrip_is_idempotent()`

---

### [`tests/test_synthesis.py`](tests/test_synthesis.py)
> *Tests for scientific literature synthesis: consensus scoring, thematic clusters, and BibTeX.*

**Size**: `121` lines (`5111` bytes)

**Classes:**
- `class SynthesisTests` - *Verify consensus scoring, thematic clustering, follow-up queries, and BibTeX generation.*
  - Method `.setUp()`
  - Method `.test_compute_consensus_handles_support_contradiction_and_empty()`
  - Method `.test_synthesize_question_produces_structured_ai_pack_and_markdown()`
  - Method `.test_synthesize_search_phrase_and_bibtex_formatting()`
  - Method `.test_synthesize_rejects_tiny_token_budget()`

---

### [`tests/test_web.py`](tests/test_web.py)
> *Tests for the web-based human UI and JSON API dispatcher (zero sockets).*

**Size**: `231` lines (`9819` bytes)

**Classes:**
- `class WebInterfaceTests` - *Verify HTML rendering and REST API handlers via pure request dispatch.*
  - Method `.setUp()`
  - Method `.request_json(method, path, payload)`
  - Method `.test_index_serves_self_contained_human_ui()`
  - Method `.test_link_related_endpoint_and_map_legend()`
  - Method `.test_demo_seed_and_overview_workflow()`
  - Method `.test_create_entities_and_synthesize_via_web_api()`
  - Method `.test_discover_extract_and_search_endpoints()`
  - Method `.test_ingest_text_matrix_contradictions_and_export()`
  - Method `.test_literature_search_ui_graph_and_api()`
  - Method `.test_validation_error_and_not_found()`

---
