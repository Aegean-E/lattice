# lattice

A provenance-first research knowledge graph for humans and AI agents. Ingest papers, record
claims only with an exact quote and locator, link those claims to research questions, and let
agents query a deterministic evidence graph instead of a pile of summaries.

Lattice is local-first: one SQLite file, the Python standard library, and no network calls.

## 30-Second Cold-Start Quick Reference

- **Runtime Prerequisites**: Python 3.10 or newer (standard library only; no third-party packages)
- **Canonical Regression Shield Gate**:
  ```bash
  python -m unittest discover
  ```
- **Try it now** (under 10 seconds, from this folder):
  ```bash
  # Option A: 1-Click interactive Web Research Studio
  python start.py         # or ./start.sh (Mac/Linux), or double-click start.bat (Windows)

  # Option B: CLI fast path
  python -m lattice init
  python -m lattice question "Does slow-wave sleep consolidate memory?"
  python -m lattice fetch "slow-wave sleep memory" --source offline
  python -m lattice extract --all --question q_000001
  python -m lattice synthesize q_000001
  ```

### AIKit Commands (run from the AIKit folder)

| Role | Command |
|---|---|
| Status, task and gates | `python aikit.py status lattice` |
| Phase 4: every gate | `python aikit.py check lattice` |
| Repair memory and map, then check | `python aikit.py fix lattice` |
| Resume an interrupted task | `python aikit.py resume lattice` |

## How It Works

- **Discovery (`fetch`)** queries offline corpora, arXiv, Crossref, OpenAlex, or EuropePMC (or a
  comma-separated federated list such as `--source offline,openalex,europepmc`) through a 4-layer
  pluggable provider boundary and deduplicates discovered papers automatically.
- **Knowledge Creation (`extract`)** segments abstracts into empirical sentences, infers stance
  (`supports`, `contradicts`, `mentions`) and confidence, records quote-backed claims with
  locators, links matching research questions, and connects each new finding to related findings
  that share a question or enough domain keywords.
- **Papers** carry bibliographic metadata plus searchable tags and a study type (for example
  `Randomized Controlled Trial`, `Cohort Study`, `Meta-Analysis`, `Computational Study`). Explicit
  values win; otherwise the type is inferred from the title and abstract and tags are derived from
  the most informative title/abstract keywords. DOIs, arXiv IDs and normalized title/year pairs are
  deduplicated; a later record fills fields the first one lacked.
- **Claims** are the unit of knowledge. Every claim needs assertion text, an exact source quote
  and optionally a locator and confidence. A claim cannot exist without provenance.
- **Questions** collect evidence. Links such as `supports`, `contradicts` and `answers` connect
  claims to questions; `cites`, `replicates`, `extends`, `uses_method`, `measures`, `mentions`
  and `related` cover the rest of the graph.
- **Analysis (`analyze`)** detects opposing claim pairs (`supports` vs `contradicts`) on shared
  questions or domain keywords (with optional `--auto-link`), links related findings through
  deterministic `related` edges, ranks keystone papers and claims by evidence centrality, and
  builds a `Paper x Question` evidence matrix with coverage gaps.
- **Token-frugal AI context (`outline`)** treats the graph as an external context. An agent peeks
  at a cheap index (counts, edge kinds, study-type mix and evidenced question refs), expands
  compact search or finding snippets that keep a stable `ref`, and pays for full text only by
  drilling into one ref. MCP `search`, `related_findings` and `subgraph` are compact and budgeted
  by default (`tokens` argument), and every trimmed list reports its omissions.
- **Synthesis (`synthesize`)** computes a confidence-weighted consensus score in `[-1.0, 1.0]`,
  groups claims into thematic clusters with verbatim quotes, identifies research gaps and
  follow-up queries, and formats resolved Markdown and BibTeX references.
- **Snapshots & BibTeX (`export` / `import`)** write and merge portable JSONL graph bundles atomically,
  or export bibliographies to standard `.bib` files (with auto-detection or `--format bibtex`).
- **Web Research Studio (`web`)** serves a local, zero-dependency human UI with one-click demo
  seeding, multi-source literature discovery, browser paste-ingestion (BibTeX/RIS/CSV/Markdown),
  literature search by tag, word, full sentence or study type, a Corpus Outline quick drawer with
  study-type and edge-relation breakdowns, one-click clipboard copy for Markdown and BibTeX syntheses,
  JSONL snapshot download, direct BibTeX export, interactive SVG subgraph exploration whose
  paper/claim/question nodes carry the study type and whose edges are colored by relation (dashed amber
  for `related`) with a legend and a Connect Findings action, and a `Paper x Question` Evidence Matrix
  & Contradictions tab.
- **The gate (`check`)** reports broken endpoints, missing quotes, duplicate identifiers,
  support cycles and unlinked evidence.

### Commands

```text
python -m lattice [--db PATH] [--json] init
python -m lattice [--db PATH] [--json] ingest PATH [PATH ...]
python -m lattice [--db PATH] [--json] fetch QUERY [--source offline|arxiv|crossref|openalex|europepmc] [--limit N]
python -m lattice [--db PATH] [--json] extract [PAPER_REF] [--all] [--question Q_REF]
python -m lattice [--db PATH] [--json] claim --paper REF --text TEXT --quote QUOTE
python -m lattice [--db PATH] [--json] question TEXT
python -m lattice [--db PATH] [--json] link SRC DST --type KIND
python -m lattice [--db PATH] [--json] search QUERY [--stance S] [--min-confidence C] [--year Y] [--tokens N]
python -m lattice [--db PATH] [--json] show REF
python -m lattice [--db PATH] [--json] subgraph REF [--depth 1..3] [--tokens N]
python -m lattice [--db PATH] [--json] related REF [--limit N] [--tokens N]
python -m lattice [--db PATH] [--json] outline [--tokens N]
python -m lattice [--db PATH] [--json] ask TARGET
python -m lattice [--db PATH] [--json] brief TARGET --tokens N
python -m lattice [--db PATH] [--json] review TARGET [--out PATH]
python -m lattice [--db PATH] [--json] synthesize TARGET [--tokens N] [--out PATH]
python -m lattice [--db PATH] [--json] analyze [--auto-link] [--limit N]
python -m lattice [--db PATH] [--json] export PATH [--format jsonl|bibtex]
python -m lattice [--db PATH] [--json] import PATH
python -m lattice [--db PATH] [--json] stats
python -m lattice [--db PATH] check
python -m lattice [--db PATH] mcp
python -m lattice [--db PATH] web [--host 127.0.0.1] [--port 8765] [--demo] [--open]
```

`--json` prints stable machine-readable payloads. `mcp` serves newline-delimited JSON-RPC on
stdio with tools (`search`, `discover_papers`, `extract_claims`, `get_entity`, `neighbors`,
`subgraph`, `related_findings`, `outline`, `add_paper`, `add_claim`, `add_question`,
`set_question_status`, `add_edge`, `brief`, `review`, `synthesize`, `analyze_graph`,
`detect_contradictions`, `export_snapshot`, `import_snapshot`, `stats`), resources
(`lattice://stats`, `lattice://questions`, `lattice://matrix`), and prompts
(`literature-synthesis`). `outline` is the cheap first call; `search`, `related_findings` and
`subgraph` return compact token-budgeted views by default; `get_entity` is the full drill-down.

### Supported Inputs

| Format | Suffix | Notes |
|---|---|---|
| BibTeX | `.bib`, `.bibtex` | nested braces and quoted values; `keywords` and `studytype` |
| RIS | `.ris` | `TY`, `TI`, `AU`, `PY`, `DO`, `UR`, `AB`, `KW`, `M3`, `ER` |
| CSV | `.csv` | header names map to metadata fields; `keywords`/`tags`, `study_type`/`type` |
| Markdown | `.md`, `.markdown` | YAML-like front matter (including `tags` and `study_type`), heading or filename title |
| Plain text | `.txt` | filename becomes the title, body the abstract |

PDF extraction is intentionally out of scope; convert a PDF to text first.

## What's Inside

```text
lattice/
├── .aikit/                   <- project memory: guidelines, decisions, ledger, codebase map
├── .gitignore                <- local databases and transient AIKit state
├── LICENSE
├── README.md
├── pyproject.toml            <- package metadata and the `lattice` console script
├── start.py                  <- 1-click launcher for Web Research Studio and CLI
├── start.bat                 <- Windows batch launcher
├── start.sh                  <- POSIX shell launcher
├── lattice/
│   ├── __init__.py
│   ├── __main__.py           <- `python -m lattice`
│   ├── analysis.py           <- contradiction detection, related-finding links, keystone centrality and evidence matrix
│   ├── checks.py             <- integrity gate: endpoints, provenance, duplicates, cycles
│   ├── cli.py                <- argument grammar, handlers and human/JSON output
│   ├── context.py            <- token-budgeted AI views: outline, compact search/related/subgraph
│   ├── database.py           <- SQLite schema, connection and version refusal
│   ├── discovery.py          <- pluggable literature discovery (arXiv, Crossref, OpenAlex, EuropePMC, offline)
│   ├── errors.py             <- the Error/Why/Fix triad
│   ├── extraction.py         <- automated quote-backed claim and edge extraction
│   ├── ingest.py             <- BibTeX, RIS, CSV, Markdown and text parsers
│   ├── inquiry.py            <- ask, token-budgeted brief and review outline
│   ├── mcp.py                <- MCP stdio server and tool dispatch
│   ├── models.py             <- value objects, identifiers and validators
│   ├── repository.py         <- graph writes, dedupe, search and evidence queries
│   ├── snapshots.py          <- atomic JSONL graph snapshot export and merge import
│   ├── synthesis.py          <- consensus scoring, thematic clusters and BibTeX synthesis
│   └── web.py                <- web-based Research Studio UI and JSON API dispatcher
└── tests/
    ├── __init__.py
    ├── test_analysis.py
    ├── test_checks.py
    ├── test_cli.py
    ├── test_context.py
    ├── test_database.py
    ├── test_discovery.py
    ├── test_extraction.py
    ├── test_ingest.py
    ├── test_inquiry.py
    ├── test_mcp.py
    ├── test_models.py
    ├── test_repository.py
    ├── test_snapshots.py
    ├── test_synthesis.py
    └── test_web.py
```

## Design Notes

The schema, identifier policy, dedupe order and evidence direction are recorded in
`.aikit/decisions.md` (ADR-001 and ADR-002). The graph deliberately stores claims rather than
free-form notes: an agent may only cite an ingested paper, and only through a claim that carries
the quote it came from. Token budgets and compact AI views are recorded in ADR-010, and
the web outline drawer and BibTeX export in ADR-011.
