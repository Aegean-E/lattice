"""Pluggable automated literature discovery: arXiv, Crossref, and offline scientific seed corpus."""

import json
import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Protocol, Sequence

from lattice.errors import fail
from lattice.models import normalize_text
from lattice.repository import Repository

Fetcher = Callable[[str, float], str]
_TAG_RE = re.compile(r"<[^>]+>")
_ATOM_NS = "{http://www.w3.org/2005/Atom}"
_ARXIV_NS = "{http://arxiv.org/schemas/atom}"

SEED_CORPUS: Sequence[Dict[str, str]] = (
    {
        "title": "Slow-Wave Sleep Consolidates Declarative Hippocampal Memory Traces",
        "authors": "Elena Vance; Marcus Chen",
        "year": "2023",
        "venue": "Nature Neuroscience",
        "doi": "10.1038/nn.2023.014",
        "arxiv": "",
        "url": "https://doi.org/10.1038/nn.2023.014",
        "abstract": (
            "Slow-wave sleep increased declarative recall accuracy by 28% compared with wakeful rest "
            "across 120 human participants. Targeted acoustic stimulation amplified spindle-oscillation "
            "coupling and stabilized hippocampal-neocortical memory traces."
        ),
    },
    {
        "title": "REM Sleep Deprivation Fails to Impair Motor Skill Retention in Young Adults",
        "authors": "Haruki Sato; Priya Nair",
        "year": "2024",
        "venue": "Sleep",
        "doi": "10.1093/sleep/zsae042",
        "arxiv": "",
        "url": "https://doi.org/10.1093/sleep/zsae042",
        "abstract": (
            "Selective REM sleep suppression did not reduce procedural motor sequence retention "
            "compared with uninterrupted sleep controls. Cortical plasticity markers remained "
            "unchanged after 48 hours of recovery."
        ),
    },
    {
        "title": "Quote-Backed Evidence Graphs Eliminate Citation Drift in Scientific Synthesis",
        "authors": "Ada Lovelace; Grace Hopper",
        "year": "2025",
        "venue": "Journal of AI Research",
        "doi": "10.1613/jair.2025.109",
        "arxiv": "2502.04109",
        "url": "https://arxiv.org/abs/2502.04109",
        "abstract": (
            "Enforcing exact verbatim quotes and typed claim-question links reduced unsupported "
            "synthesis statements by 73% across 500 biomedical literature reviews. Contradiction "
            "edges surfaced replication failures that flat vector retrieval missed."
        ),
    },
    {
        "title": "Transformer Scaling Laws Exhibit Diminishing Returns Under Noisy Pretraining Corpora",
        "authors": "Linus Kowalski; Mei Lin",
        "year": "2024",
        "venue": "ICML",
        "doi": "10.5555/icml.2024.881",
        "arxiv": "2406.08810",
        "url": "https://arxiv.org/abs/2406.08810",
        "abstract": (
            "Curated deduplication improved downstream scientific question-answering accuracy by 19% "
            "at one-quarter of the compute budget compared with unfiltered web text."
        ),
    },
)


@dataclass(frozen=True)
class PaperCandidate:
    """Immutable DTO returned by any literature discovery provider."""

    title: str
    authors: str = ""
    year: str = ""
    venue: str = ""
    doi: str = ""
    arxiv: str = ""
    url: str = ""
    abstract: str = ""
    source: str = "offline"

    def to_metadata(self) -> Dict[str, str]:
        """Dictionary ready for `Repository.add_paper`."""
        return {
            "title": self.title,
            "authors": self.authors,
            "year": self.year,
            "venue": self.venue,
            "doi": self.doi,
            "arxiv": self.arxiv,
            "url": self.url,
            "abstract": self.abstract,
            "kind": "paper",
        }

    def to_dict(self) -> Dict[str, str]:
        """JSON-serializable representation including discovery source."""
        data = self.to_metadata()
        data["source"] = self.source
        return data


class LiteratureProvider(Protocol):
    """Contract layer for pluggable scientific literature search providers."""

    def search(self, query: str, limit: int = 10) -> List[PaperCandidate]:
        """Return up to `limit` candidate papers matching `query`."""
        raise NotImplementedError


class ProviderRegistry:
    """Registry layer mapping provider names to `LiteratureProvider` implementations."""

    def __init__(self) -> None:
        self._providers: Dict[str, LiteratureProvider] = {}

    def register(self, name: str, provider: LiteratureProvider) -> None:
        """Register or replace a provider by lowercase key."""
        key = str(name or "").strip().lower()
        if not key:
            fail("provider name cannot be empty", "the registry indexes providers by name",
                 "pass a non-empty name such as 'arxiv', 'crossref' or 'offline'")
        self._providers[key] = provider

    def get(self, name: str) -> LiteratureProvider:
        """Look up a registered provider or raise `LatticeError`."""
        key = str(name or "").strip().lower()
        provider = self._providers.get(key)
        if provider is None:
            known = ", ".join(sorted(self._providers)) or "none"
            fail(f"unknown literature provider '{name}'",
                 f"registered providers are: {known}",
                 f"pass --source with one of: {known}")
        return provider

    def names(self) -> List[str]:
        """Sorted list of registered provider names."""
        return sorted(self._providers)


def _http_get(url: str, timeout: float = 10.0) -> str:
    """Perform a bounded HTTP GET with a scholarly User-Agent header."""
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "LatticeKnowledgeGraph/0.2 (+https://localhost/lattice)"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw: bytes = response.read()
            return raw.decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        fail(f"literature query failed for {url}: {exc}",
             "the remote scholarly catalog could not be reached within the timeout",
             "use --source offline for local discovery or check network connectivity")
        raise AssertionError("unreachable")


class ArxivProvider:
    """Concrete provider querying the arXiv Atom API."""

    def __init__(self, fetcher: Optional[Fetcher] = None, timeout: float = 10.0) -> None:
        self._fetcher = fetcher or _http_get
        self._timeout = timeout

    def search(self, query: str, limit: int = 10) -> List[PaperCandidate]:
        """Search arXiv by query terms and parse Atom XML entries."""
        cleaned = _validate_search_args(query, limit)
        encoded = urllib.parse.quote_plus(f"all:{cleaned}")
        url = f"http://export.arxiv.org/api/query?search_query={encoded}&start=0&max_results={limit}"
        payload = self._fetcher(url, self._timeout)
        try:
            root = ET.fromstring(payload)
        except ET.ParseError as exc:
            fail(f"could not parse arXiv XML response: {exc}",
                 "the feed returned malformed XML",
                 "retry later or use --source offline")
        candidates: List[PaperCandidate] = []
        for entry in root.findall(f"{_ATOM_NS}entry"):
            title = " ".join((entry.findtext(f"{_ATOM_NS}title") or "").split())
            if not title:
                continue
            summary = " ".join((entry.findtext(f"{_ATOM_NS}summary") or "").split())
            published = (entry.findtext(f"{_ATOM_NS}published") or "").strip()
            year = published[:4] if len(published) >= 4 and published[:4].isdigit() else ""
            raw_id = (entry.findtext(f"{_ATOM_NS}id") or "").strip()
            arxiv_id = raw_id.rsplit("/abs/", 1)[-1] if "/abs/" in raw_id else raw_id
            doi = (entry.findtext(f"{_ARXIV_NS}doi") or "").strip()
            authors = "; ".join(
                " ".join((author.findtext(f"{_ATOM_NS}name") or "").split())
                for author in entry.findall(f"{_ATOM_NS}author")
                if (author.findtext(f"{_ATOM_NS}name") or "").strip()
            )
            candidates.append(
                PaperCandidate(
                    title=title,
                    authors=authors,
                    year=year,
                    venue="arXiv",
                    doi=doi,
                    arxiv=arxiv_id,
                    url=raw_id,
                    abstract=summary,
                    source="arxiv",
                )
            )
        return candidates[:limit]


class CrossrefProvider:
    """Concrete provider querying the Crossref REST works endpoint."""

    def __init__(self, fetcher: Optional[Fetcher] = None, timeout: float = 10.0) -> None:
        self._fetcher = fetcher or _http_get
        self._timeout = timeout

    def search(self, query: str, limit: int = 10) -> List[PaperCandidate]:
        """Search Crossref works and normalize bibliographic items."""
        cleaned = _validate_search_args(query, limit)
        encoded = urllib.parse.quote_plus(cleaned)
        url = f"https://api.crossref.org/works?query={encoded}&rows={limit}"
        payload = self._fetcher(url, self._timeout)
        try:
            data = json.loads(payload)
        except ValueError as exc:
            fail(f"could not parse Crossref JSON response: {exc}",
                 "the remote endpoint did not return valid JSON",
                 "retry later or use --source offline")
        items = ((data.get("message") or {}).get("items")) or []
        candidates: List[PaperCandidate] = []
        for item in items:
            titles = item.get("title") or []
            title = " ".join(str(titles[0]).split()) if titles else ""
            if not title:
                continue
            authors = _format_crossref_authors(item.get("author") or [])
            year = _extract_crossref_year(item)
            venues = item.get("container-title") or []
            venue = " ".join(str(venues[0]).split()) if venues else ""
            raw_abstract = str(item.get("abstract") or "")
            abstract = " ".join(_TAG_RE.sub(" ", raw_abstract).split())
            candidates.append(
                PaperCandidate(
                    title=title,
                    authors=authors,
                    year=year,
                    venue=venue,
                    doi=str(item.get("DOI") or "").strip(),
                    arxiv="",
                    url=str(item.get("URL") or "").strip(),
                    abstract=abstract,
                    source="crossref",
                )
            )
        return candidates[:limit]


class OfflineCorpusProvider:
    """Deterministic local provider over a curated seed catalog for offline/instant search."""

    def __init__(self, records: Optional[Sequence[Dict[str, str]]] = None) -> None:
        self._records = list(records if records is not None else SEED_CORPUS)

    def search(self, query: str, limit: int = 10) -> List[PaperCandidate]:
        """Rank local corpus records by token overlap with `query`."""
        cleaned = _validate_search_args(query, limit)
        terms = [term for term in normalize_text(cleaned).split() if term]
        scored: List[ tuple[int, int, PaperCandidate] ] = []
        for idx, record in enumerate(self._records):
            haystack = normalize_text(
                f"{record.get('title', '')} {record.get('abstract', '')} "
                f"{record.get('authors', '')} {record.get('venue', '')}"
            )
            score = sum(2 if term in normalize_text(record.get("title", "")) else 1
                        for term in terms if term in haystack)
            if score > 0:
                scored.append((
                    score,
                    -idx,
                    PaperCandidate(
                        title=record.get("title", ""),
                        authors=record.get("authors", ""),
                        year=record.get("year", ""),
                        venue=record.get("venue", ""),
                        doi=record.get("doi", ""),
                        arxiv=record.get("arxiv", ""),
                        url=record.get("url", ""),
                        abstract=record.get("abstract", ""),
                        source="offline",
                    ),
                ))
        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [item[2] for item in scored[:limit]]


def default_registry() -> ProviderRegistry:
    """Create the default provider registry with offline, arXiv, and Crossref adapters."""
    registry = ProviderRegistry()
    registry.register("offline", OfflineCorpusProvider())
    registry.register("arxiv", ArxivProvider())
    registry.register("crossref", CrossrefProvider())
    return registry


class DiscoveryService:
    """Orchestration layer with constructor DI for discovering and ingesting papers."""

    def __init__(self, repository: Repository,
                 registry: Optional[ProviderRegistry] = None) -> None:
        self.repository = repository
        self.registry = registry or default_registry()

    def discover(self, query: str, source: str = "offline",
                 limit: int = 10, ingest: bool = True) -> Dict[str, Any]:
        """Search `source` for `query` and optionally ingest discovered papers into the graph."""
        provider = self.registry.get(source)
        candidates = provider.search(query, limit=limit)
        records: List[Dict[str, Any]] = []
        created_count = 0
        for candidate in candidates:
            entry = candidate.to_dict()
            if ingest:
                paper, created = self.repository.add_paper(candidate.to_metadata())
                entry["id"] = paper.id
                entry["created"] = created
                if created:
                    created_count += 1
            records.append(entry)
        return {
            "query": query,
            "source": source,
            "ingested": ingest,
            "count": len(records),
            "created": created_count,
            "records": records,
        }


def _validate_search_args(query: str, limit: int) -> str:
    """Ensure a discovery query is non-empty and `limit` is positive."""
    cleaned = " ".join(str(query or "").split())
    if not cleaned:
        fail("discovery needs a search query",
             "an empty query cannot be dispatched to a literature catalog",
             "pass a scientific topic or phrase to search")
    if int(limit) < 1:
        fail(f"limit {limit} is not positive",
             "discovery must request at least one candidate paper",
             "pass --limit 1 or more")
    return cleaned


def _format_crossref_authors(authors: Sequence[Dict[str, Any]]) -> str:
    """Join Crossref author objects into `Given Family; Given Family`."""
    names: List[str] = []
    for author in authors:
        given = str(author.get("given") or "").strip()
        family = str(author.get("family") or author.get("name") or "").strip()
        full = " ".join(part for part in (given, family) if part)
        if full:
            names.append(full)
    return "; ".join(names)


def _extract_crossref_year(item: Dict[str, Any]) -> str:
    """Extract a 4-digit publication year from Crossref date-parts."""
    for key in ("issued", "published-print", "published-online", "created"):
        parts = ((item.get(key) or {}).get("date-parts")) or []
        if parts and parts[0]:
            first = str(parts[0][0])
            if len(first) == 4 and first.isdigit():
                return first
    return ""

