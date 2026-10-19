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


if __name__ == "__main__":
    unittest.main()
