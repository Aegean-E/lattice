"""MCP JSON-RPC contracts and stdio framing."""

import io
import json
import unittest

from lattice.database import open_database
from lattice.mcp import handle_message, serve
from lattice.repository import Repository


class McpTests(unittest.TestCase):
    """Call the protocol handler directly; no sockets or spawns."""

    def setUp(self):
        self.connection = open_database(":memory:")
        self.addCleanup(self.connection.close)
        self.repository = Repository(self.connection)

    def call(self, method, params=None, request_id=1):
        return handle_message(self.repository, {
            "jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}})

    def tool(self, name, arguments):
        return self.call("tools/call", {"name": name, "arguments": arguments})

    def test_initialize(self):
        result = self.call("initialize")["result"]
        self.assertIn("protocolVersion", result)
        self.assertEqual(result["serverInfo"]["name"], "lattice")

    def test_tools_list(self):
        names = {tool["name"] for tool in self.call("tools/list")["result"]["tools"]}
        self.assertTrue({"search", "add_claim", "brief", "review", "stats"} <= names)

    def test_add_question_and_search(self):
        added = self.tool("add_question", {"text": "Does sleep help?"})["result"]
        self.assertFalse(added["isError"])
        payload = json.loads(added["content"][0]["text"])
        self.assertEqual(payload["question"]["id"], "q_000001")
        found = json.loads(self.tool("search", {"query": "sleep"})["result"]["content"][0]["text"])
        self.assertEqual(len(found["questions"]), 1)

    def test_add_claim_reports_missing_paper(self):
        response = self.tool("add_claim", {"paper": "p_missing", "text": "Claim",
                                           "quote": "A quote"})
        self.assertTrue(response["result"]["isError"])
        self.assertIn("Fix:", response["result"]["content"][0]["text"])

    def test_unknown_method(self):
        response = self.call("nope")
        self.assertEqual(response["error"]["code"], -32601)

    def test_invalid_request(self):
        response = handle_message(self.repository, {"jsonrpc": "2.0", "id": 3})
        self.assertEqual(response["error"]["code"], -32600)

    def test_notification_has_no_response(self):
        response = handle_message(self.repository, {
            "jsonrpc": "2.0", "method": "notifications/initialized"})
        self.assertIsNone(response)

    def test_stdio_serves_one_message(self):
        source = io.StringIO(json.dumps({
            "jsonrpc": "2.0", "id": 7, "method": "ping", "params": {}}) + "\n")
        sink = io.StringIO()
        serve(self.repository, stdin=source, stdout=sink)
        response = json.loads(sink.getvalue())
        self.assertEqual(response["id"], 7)
        self.assertEqual(response["result"], {})

    def test_stdio_reports_parse_error(self):
        sink = io.StringIO()
        serve(self.repository, stdin=io.StringIO("not json\n"), stdout=sink)
        self.assertEqual(json.loads(sink.getvalue())["error"]["code"], -32700)

    def test_discover_extract_synthesize_and_subgraph_tools(self):
        q_resp = json.loads(self.tool("add_question", {"text": "Does sleep consolidate memory?"})["result"]["content"][0]["text"])
        qid = q_resp["question"]["id"]

        disc = json.loads(self.tool("discover_papers", {"query": "sleep memory", "source": "offline", "limit": 2})["result"]["content"][0]["text"])
        self.assertGreaterEqual(disc["count"], 1)

        ext = json.loads(self.tool("extract_claims", {"question": qid})["result"]["content"][0]["text"])
        self.assertGreaterEqual(ext["claims_created"], 1)

        syn = json.loads(self.tool("synthesize", {"target": qid, "tokens": 1500})["result"]["content"][0]["text"])
        self.assertEqual(syn["mode"], "question")
        self.assertIn("consensus", syn)

        sub = json.loads(self.tool("subgraph", {"ref": qid, "depth": 1})["result"]["content"][0]["text"])
        self.assertGreaterEqual(len(sub["nodes"]), 2)

        status_res = json.loads(self.tool("set_question_status", {"question": qid, "status": "answered"})["result"]["content"][0]["text"])
        self.assertEqual(status_res["question"]["status"], "answered")

    def test_resources_and_prompts_endpoints(self):
        self.tool("add_question", {"text": "Does sleep consolidate memory?"})
        resources = self.call("resources/list")["result"]["resources"]
        uris = {item["uri"] for item in resources}
        self.assertIn("lattice://stats", uris)
        self.assertIn("lattice://questions", uris)

        read_stats = self.call("resources/read", {"uri": "lattice://stats"})["result"]
        stats_data = json.loads(read_stats["contents"][0]["text"])
        self.assertEqual(stats_data["questions"], 1)

        prompts = self.call("prompts/list")["result"]["prompts"]
        prompt_names = {item["name"] for item in prompts}
        self.assertIn("literature-synthesis", prompt_names)

        rendered = self.call("prompts/get", {"name": "literature-synthesis", "arguments": {"target": "q_000001"}})["result"]
        self.assertGreaterEqual(len(rendered["messages"]), 1)
        self.assertIn("Literature Synthesis", rendered["messages"][0]["content"]["text"])


if __name__ == "__main__":
    unittest.main()
