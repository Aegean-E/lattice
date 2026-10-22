"""Tests for the turnkey client facade used by AI hosts."""

import json
import tempfile
import unittest
from pathlib import Path

from lattice import api
from lattice.client import AsyncLatticeClient, LatticeClient
from lattice.mcp import PROMPTS, RESOURCES, TOOLS


def seed(client: LatticeClient) -> tuple[dict, dict, dict]:
    """Create one question, paper, claim and support edge through the client."""
    question = client.add_question("Does sleep consolidate memory?")
    paper = client.add_paper({"title": "Sleep and Memory Trial"})
    claim = client.add_claim(
        paper["paper"]["id"], "Sleep improves memory.", "Sleep improves memory.",
        stance="supports", confidence=0.8)
    client.add_edge(claim["claim"]["id"], question["question"]["id"], "supports")
    return question, paper, claim


class LatticeClientTests(unittest.TestCase):
    """Verify lifecycle, tool parity, convenience methods and failure modes."""

    def setUp(self) -> None:
        self.client = LatticeClient(":memory:")
        self.addCleanup(self.client.close)

    def test_context_manager_owns_and_closes_the_connection(self) -> None:
        with LatticeClient(":memory:") as client:
            client.add_question("A question?")
        with self.assertRaises(api.LatticeError):
            client.outline()

    def test_close_is_idempotent(self) -> None:
        client = LatticeClient(":memory:")
        client.close()
        client.close()
        with self.assertRaises(api.LatticeError):
            client.stats()

    def test_write_and_read_flow(self) -> None:
        question, paper, claim = seed(self.client)
        stats = self.client.stats()
        self.assertEqual(stats["questions"], 1)
        self.assertEqual(stats["papers"], 1)
        self.assertEqual(stats["claims"], 1)
        self.assertEqual(stats["edges"], 1)

        outline = self.client.outline()
        self.assertEqual(outline["counts"]["questions"], 1)
        found = self.client.search("sleep")
        self.assertTrue(found["papers"])
        entity = self.client.get(f"claim:{claim['claim']['id']}")
        self.assertEqual(entity["entity"]["id"], claim["claim"]["id"])
        self.assertEqual(self.client.get(paper["paper"]["id"])["entity"]["title"],
                         "Sleep and Memory Trial")
        self.assertTrue(self.client.neighbors(f"question:{question['question']['id']}"))

    def test_synthesis_and_brief(self) -> None:
        question, _, _ = seed(self.client)
        report = self.client.synthesize(f"question:{question['question']['id']}", tokens=500)
        self.assertEqual(report["target"], question["question"]["id"])
        self.assertIn("markdown", report)
        brief = self.client.brief(question["question"]["id"], tokens=500)
        self.assertIn("text", brief)
        self.assertIn("budget", brief)

    def test_tool_schemas_match_mcp_and_are_copies(self) -> None:
        schemas = self.client.tool_schemas()
        self.assertEqual([item["name"] for item in schemas],
                         [item["name"] for item in TOOLS])
        self.assertEqual(len(schemas), 21)
        schemas[0]["name"] = "mutated"
        self.assertEqual(TOOLS[0]["name"], "search")

    def test_call_tool_matches_mcp_tool_names(self) -> None:
        schemas = self.client.tool_schemas()
        for item in schemas:
            self.assertTrue(callable(getattr(self.client, item["name"], None)),
                            f"no client method for tool {item['name']}")
        result = self.client.call_tool("add_question", {"text": "Tool question?"})
        self.assertEqual(result["question"]["text"], "Tool question?")
        self.assertEqual(self.client.call_tool("stats", {})["questions"], 1)

    def test_unknown_tool_raises_lattice_error(self) -> None:
        with self.assertRaises(api.LatticeError):
            self.client.call_tool("no_such_tool", {})

    def test_missing_argument_raises_lattice_error(self) -> None:
        with self.assertRaises(api.LatticeError):
            self.client.call_tool("search", {})

    def test_non_mapping_arguments_raise_lattice_error(self) -> None:
        with self.assertRaises(api.LatticeError):
            self.client.call_tool("search", ["sleep"])

    def test_non_string_tool_names_raise_lattice_error(self) -> None:
        with LatticeClient(":memory:", read_only=True) as client:
            for name in (None, [], {}, ""):
                with self.subTest(name=name), self.assertRaises(api.LatticeError):
                    client.call_tool(name, {})


class AsyncLatticeClientTests(unittest.IsolatedAsyncioTestCase):
    """Verify the async facade serializes work on its dedicated thread."""

    async def asyncSetUp(self) -> None:
        self.client = AsyncLatticeClient(":memory:")

    async def asyncTearDown(self) -> None:
        await self.client.close()

    async def test_async_write_and_read_flow(self) -> None:
        question = await self.client.add_question("Does async work?")
        paper = await self.client.add_paper({"title": "Async Trial"})
        claim = await self.client.add_claim(
            paper["paper"]["id"], "Async works.", "Async works.", stance="mentions")
        await self.client.add_edge(
            claim["claim"]["id"], question["question"]["id"], "answers")
        outline = await self.client.outline()
        self.assertEqual(outline["counts"]["questions"], 1)
        self.assertEqual(outline["counts"]["claims"], 1)

    async def test_async_schemas_and_call_tool(self) -> None:
        schemas = await self.client.tool_schemas()
        self.assertEqual(len(schemas), 21)
        stats = await self.client.call_tool("stats", {})
        self.assertEqual(stats["questions"], 0)

    async def test_async_context_manager_closes(self) -> None:
        client = AsyncLatticeClient(":memory:")
        async with client:
            await client.add_question("Context question?")
        with self.assertRaises(api.LatticeError):
            await client.outline()
        await client.close()

    async def test_async_rejects_sync_repository_access(self) -> None:
        with self.assertRaises(api.LatticeError):
            _ = self.client.repository


class ClientSafetyTests(unittest.TestCase):
    """Verify read-only policy, path validation, metadata parity and full tool coverage."""

    def test_invalid_database_paths_raise(self) -> None:
        for bad_path in ("", "   ", None):
            with self.subTest(path=bad_path), self.assertRaises(api.LatticeError):
                LatticeClient(bad_path)

    def test_whitespace_memory_sentinel_is_normalized(self) -> None:
        with LatticeClient(" :memory: ") as client:
            self.assertEqual(client.db_path, ":memory:")

    def test_read_only_requires_an_existing_database(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            missing = Path(temp_dir) / "missing.db"
            with self.assertRaises(api.LatticeError):
                LatticeClient(str(missing), read_only=True)
            self.assertFalse(missing.exists())

    def test_read_only_client_reads_existing_database(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "kb.db"
            with LatticeClient(str(path)) as writable:
                writable.add_question("Does read-only work?")
            with LatticeClient(str(path), read_only=True) as client:
                self.assertEqual(client.stats()["questions"], 1)
                with self.assertRaises(api.LatticeError):
                    client.add_question("Blocked?")

    def test_read_only_filters_schemas_and_blocks_writes(self) -> None:
        allowed = {
            "search", "get_entity", "neighbors", "subgraph", "related_findings", "outline",
            "brief", "review", "synthesize", "stats", "analyze_graph", "detect_contradictions",
        }
        blocked = (
            ("add_paper", {"title": "x"}), ("add_claim", {"paper": "p_x"}),
            ("add_question", {"text": "x"}), ("set_question_status", {"question": "q_1"}),
            ("add_edge", {"src": "q_1", "dst": "q_1", "kind": "mentions"}),
            ("extract_claims", {}), ("discover_papers", {"query": "sleep"}),
            ("export_snapshot", {"path": "x"}), ("import_snapshot", {"path": "x"}),
        )
        with LatticeClient(":memory:", read_only=True) as client:
            schemas = client.tool_schemas()
            self.assertEqual({item["name"] for item in schemas}, allowed)
            for item in schemas:
                if item["name"] in ("analyze_graph", "detect_contradictions"):
                    self.assertNotIn("auto_link", item["inputSchema"]["properties"])
            self.assertEqual(client.outline()["counts"]["questions"], 0)
            self.assertIn("matrix", client.analyze_graph(auto_link=False))
            self.assertEqual(client.detect_contradictions(auto_link=False)["count"], 0)
            for name, arguments in blocked:
                with self.subTest(tool=name), self.assertRaises(api.LatticeError):
                    client.call_tool(name, arguments)
            with self.assertRaises(api.LatticeError):
                client.analyze_graph(auto_link=True)
            with self.assertRaises(api.LatticeError):
                client.detect_contradictions(auto_link=True)
            with self.assertRaises(api.LatticeError):
                _ = client.repository

    def test_resource_and_prompt_parity(self) -> None:
        with LatticeClient(":memory:", read_only=True) as client:
            self.assertEqual(len(client.resource_schemas()), len(RESOURCES))
            self.assertEqual(len(client.prompt_schemas()), len(PROMPTS))
            self.assertEqual(client.read_resource("lattice://stats")["questions"], 0)
            prompt = client.get_prompt(
                "literature-synthesis", {"target": "sleep", "tokens": 500})
            self.assertTrue(prompt["messages"])
            with self.assertRaises(api.LatticeError):
                client.read_resource("lattice://unknown")
            with self.assertRaises(api.LatticeError):
                client.get_prompt("unknown", {})
            with self.assertRaises(api.LatticeError):
                client.get_prompt("literature-synthesis", ["bad"])

    def test_every_tool_executes_and_serializes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            snapshot = str(Path(temp_dir) / "snapshot.jsonl")
            with LatticeClient(":memory:") as client:
                question = client.add_question("Does sleep consolidate memory?")["question"]
                paper = client.add_paper({
                    "title": "Sleep Trial",
                    "abstract": "A randomized trial shows sleep improves memory.",
                    "study_type": "Randomized Controlled Trial",
                })["paper"]
                claim = client.add_claim(
                    paper["id"], "Sleep improves memory.", "Sleep improves memory.",
                    stance="supports")["claim"]
                client.add_edge(claim["id"], question["id"], "supports")
                calls = {
                    "search": {"query": "sleep"},
                    "discover_papers": {"query": "sleep", "source": "offline",
                                        "limit": 2, "ingest": False},
                    "extract_claims": {"paper": paper["id"]},
                    "get_entity": {"ref": question["id"]},
                    "neighbors": {"ref": question["id"]},
                    "subgraph": {"ref": question["id"], "depth": 1, "tokens": 800},
                    "related_findings": {"target": claim["id"]},
                    "outline": {"tokens": 400},
                    "brief": {"target": question["id"], "tokens": 600},
                    "review": {"target": question["id"]},
                    "synthesize": {"target": question["id"], "tokens": 600},
                    "analyze_graph": {"auto_link": False, "limit": 5},
                    "detect_contradictions": {"auto_link": False},
                    "set_question_status": {"question": question["id"], "status": "answered"},
                    "export_snapshot": {"path": snapshot},
                    "import_snapshot": {"path": snapshot},
                    "stats": {},
                }
                for name, arguments in calls.items():
                    with self.subTest(tool=name):
                        json.dumps(client.call_tool(name, arguments))


class AsyncClientSafetyTests(unittest.IsolatedAsyncioTestCase):
    """Verify the read-only policy survives the async facade."""

    async def test_async_read_only_filters_and_blocks_writes(self) -> None:
        async with AsyncLatticeClient(":memory:", read_only=True) as client:
            names = {item["name"] for item in await client.tool_schemas()}
            self.assertNotIn("add_paper", names)
            self.assertEqual(len(await client.resource_schemas()), len(RESOURCES))
            self.assertEqual(len(await client.prompt_schemas()), len(PROMPTS))
            self.assertEqual((await client.read_resource("lattice://stats"))["questions"], 0)
            with self.assertRaises(api.LatticeError):
                await client.add_question("Blocked?")
            self.assertEqual((await client.outline())["counts"]["questions"], 0)


if __name__ == "__main__":
    unittest.main()
