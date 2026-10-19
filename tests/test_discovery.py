"""Tests for pluggable automated literature discovery (arXiv, Crossref, and offline corpus)."""

import sqlite3
import unittest

from lattice.database import open_database
from lattice.discovery import (
    ArxivProvider,
    CrossrefProvider,
    DiscoveryService,
    EuropePmcProvider,
    OfflineCorpusProvider,
    OpenAlexProvider,
    PaperCandidate,
    ProviderRegistry,
    default_registry,
)
from lattice.errors import LatticeError
from lattice.repository import Repository

SAMPLE_OPENALEX_JSON = """{
  "results": [
    {
      "id": "https://openalex.org/W4200000001",
      "doi": "https://doi.org/10.1000/raeg.2024.01",
      "title": "Retrieval-Augmented Evidence Graphs for Scientific Reasoning",
      "publication_year": 2024,
      "primary_location": {
        "source": {"display_name": "Nature Machine Intelligence"}
      },
      "authorships": [
        {"author": {"display_name": "Ada Lovelace"}},
        {"author": {"display_name": "Grace Hopper"}}
      ],
      "keywords": [
        {"display_name": "Evidence Graphs"},
        {"display_name": "Citation Networks"}
      ],
      "abstract_inverted_index": {
        "Quote-backed": [0],
        "graphs": [1],
        "reduce": [2],
        "hallucination": [3],
        "by": [4],
        "64%.": [5]
      }
    }
  ]
}"""

SAMPLE_EUROPEPMC_JSON = """{
  "resultList": {
    "result": [
      {
        "id": "38000001",
        "title": "Hippocampal Spindle Coupling in Human Slow-Wave Sleep.",
        "authorString": "Vance E, Chen M.",
        "journalTitle": "Journal of Neuroscience",
        "pubYear": "2024",
        "doi": "10.1523/jneurosci.2024.01",
        "abstractText": "Acoustic spindle stimulation increased memory recall by 31% in 80 adults."
      }
    ]
  }
}"""

SAMPLE_ARXIV_XML = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2401.12345v2</id>
    <published>2024-01-22T18:00:00Z</published>
    <title>Retrieval-Augmented Evidence Graphs for Scientific Reasoning</title>
    <summary>We demonstrate that quote-backed claim graphs reduce citation hallucination by 64% across 300 biomedical queries.</summary>
    <author><name>Ada Lovelace</name></author>
    <author><name>Grace Hopper</name></author>
    <arxiv:doi>10.1000/raeg.2024.01</arxiv:doi>
  </entry>
</feed>
"""

SAMPLE_CROSSREF_JSON = """{
  "status": "ok",
  "message": {
    "items": [
      {
        "DOI": "10.1038/s41586-023-00001-x",
        "title": ["Slow-Wave Sleep Consolidates Declarative Hippocampal Memory Traces"],
        "author": [
          {"given": "Elena", "family": "Vance"},
          {"given": "Marcus", "family": "Chen"}
        ],
        "issued": {"date-parts": [[2023, 5, 14]]},
        "container-title": ["Nature"],
        "URL": "https://doi.org/10.1038/s41586-023-00001-x",
        "abstract": "<jats:p>Slow-wave sleep increased recall accuracy by 28% compared with wakeful rest.</jats:p>"
      }
    ]
  }
}"""


class DiscoveryTests(unittest.TestCase):
    """Verify the 4-layer discovery boundary: DTOs, registry, providers, and service DI."""

    def setUp(self) -> None:
        self.connection: sqlite3.Connection = open_database(":memory:")
        self.addCleanup(self.connection.close)
        self.repository = Repository(self.connection)

    def test_paper_candidate_is_frozen_and_converts_to_metadata(self) -> None:
        candidate = PaperCandidate(
            title="Graph Epistemology",
            authors="Ada Lovelace; Alan Turing",
            year="2025",
            venue="Journal of AI Research",
            doi="10.1000/jair.2025",
            arxiv="2501.00001",
            url="https://example.org/paper",
            abstract="Structured claims ground automated literature synthesis.",
            tags="evidence graphs; citation",
            study_type="Computational Study",
            source="offline",
        )
        metadata = candidate.to_metadata()
        self.assertEqual(metadata["title"], "Graph Epistemology")
        self.assertEqual(metadata["doi"], "10.1000/jair.2025")
        self.assertEqual(metadata["tags"], "evidence graphs; citation")
        self.assertEqual(metadata["study_type"], "Computational Study")
        self.assertEqual(candidate.to_dict()["source"], "offline")

    def test_registry_registers_and_resolves_providers(self) -> None:
        registry = ProviderRegistry()
        provider = OfflineCorpusProvider()
        registry.register("offline", provider)
        self.assertIs(registry.get("offline"), provider)
        self.assertIn("offline", registry.names())
        with self.assertRaises(LatticeError):
            registry.get("nonexistent")

    def test_arxiv_provider_parses_atom_xml(self) -> None:
        provider = ArxivProvider(fetcher=lambda _url, _timeout: SAMPLE_ARXIV_XML)
        results = provider.search("citation hallucination", limit=5)
        self.assertEqual(len(results), 1)
        first = results[0]
        self.assertEqual(first.title, "Retrieval-Augmented Evidence Graphs for Scientific Reasoning")
        self.assertEqual(first.authors, "Ada Lovelace; Grace Hopper")
        self.assertEqual(first.year, "2024")
        self.assertEqual(first.arxiv, "2401.12345v2")
        self.assertEqual(first.doi, "10.1000/raeg.2024.01")
        self.assertIn("reduce citation hallucination by 64%", first.abstract)

    def test_crossref_provider_parses_json_and_strips_jats_tags(self) -> None:
        provider = CrossrefProvider(fetcher=lambda _url, _timeout: SAMPLE_CROSSREF_JSON)
        results = provider.search("slow-wave sleep memory", limit=5)
        self.assertEqual(len(results), 1)
        first = results[0]
        self.assertEqual(first.title, "Slow-Wave Sleep Consolidates Declarative Hippocampal Memory Traces")
        self.assertEqual(first.authors, "Elena Vance; Marcus Chen")
        self.assertEqual(first.year, "2023")
        self.assertEqual(first.venue, "Nature")
        self.assertEqual(first.doi, "10.1038/s41586-023-00001-x")
        self.assertEqual(
            first.abstract,
            "Slow-wave sleep increased recall accuracy by 28% compared with wakeful rest.",
        )

    def test_openalex_provider_reconstructs_inverted_index_abstract(self) -> None:
        provider = OpenAlexProvider(fetcher=lambda _url, _timeout: SAMPLE_OPENALEX_JSON)
        results = provider.search("evidence graphs", limit=5)
        self.assertEqual(len(results), 1)
        first = results[0]
        self.assertEqual(first.title, "Retrieval-Augmented Evidence Graphs for Scientific Reasoning")
        self.assertEqual(first.authors, "Ada Lovelace; Grace Hopper")
        self.assertEqual(first.year, "2024")
        self.assertEqual(first.venue, "Nature Machine Intelligence")
        self.assertEqual(first.doi, "10.1000/raeg.2024.01")
        self.assertEqual(first.abstract, "Quote-backed graphs reduce hallucination by 64%.")
        self.assertEqual(first.tags, "Evidence Graphs, Citation Networks")

    def test_europepmc_provider_parses_biomedical_results(self) -> None:
        provider = EuropePmcProvider(fetcher=lambda _url, _timeout: SAMPLE_EUROPEPMC_JSON)
        results = provider.search("hippocampal spindle sleep", limit=5)
        self.assertEqual(len(results), 1)
        first = results[0]
        self.assertEqual(first.title, "Hippocampal Spindle Coupling in Human Slow-Wave Sleep.")
        self.assertEqual(first.year, "2024")
        self.assertEqual(first.venue, "Journal of Neuroscience")
        self.assertEqual(first.doi, "10.1523/jneurosci.2024.01")
        self.assertIn("31%", first.abstract)

    def test_offline_provider_searches_curated_seed_catalog(self) -> None:
        provider = OfflineCorpusProvider()
        results = provider.search("sleep memory consolidation", limit=5)
        self.assertGreaterEqual(len(results), 2)
        self.assertTrue(any("sleep" in item.title.lower() or "sleep" in item.abstract.lower()
                            for item in results))

    def test_discovery_service_ingests_and_deduplicates_across_federated_sources(self) -> None:
        registry = default_registry()
        registry.register("mock_arxiv", ArxivProvider(fetcher=lambda _u, _t: SAMPLE_ARXIV_XML))
        registry.register("mock_openalex", OpenAlexProvider(fetcher=lambda _u, _t: SAMPLE_OPENALEX_JSON))
        registry.register("mock_epmc", EuropePmcProvider(fetcher=lambda _u, _t: SAMPLE_EUROPEPMC_JSON))
        service = DiscoveryService(self.repository, registry=registry)
        federated = service.discover(
            "scientific reasoning",
            source="mock_arxiv,mock_openalex,mock_epmc",
            limit=5,
            ingest=True,
        )
        self.assertEqual(federated["count"], 2)
        self.assertEqual(federated["created"], 2)
        self.assertEqual(self.repository.stats()["papers"], 2)

        second_run = service.discover("scientific reasoning", source="mock_arxiv", limit=5, ingest=True)
        self.assertEqual(second_run["count"], 1)
        self.assertEqual(second_run["created"], 0)
        self.assertEqual(self.repository.stats()["papers"], 2)


if __name__ == "__main__":
    unittest.main()

