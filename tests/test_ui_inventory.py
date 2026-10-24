"""The UI inventory proof covers the studio's controls, handlers, routes and theme tokens."""

import unittest
from pathlib import Path

from tools.ui_inventory import inventory

ROOT = Path(__file__).resolve().parent.parent


class InventoryTest(unittest.TestCase):

    def test_the_inventory_names_controls_handlers_routes_and_tokens(self):
        entries = inventory(ROOT)
        for expected in ("element input#disc-query", "handler loadDemo",
                         "route GET /api/overview", "route POST /api/demo",
                         "token --accent"):
            self.assertIn(expected, entries)
        self.assertGreaterEqual(len(entries), 90)

    def test_the_studio_page_and_panels_are_part_of_the_surface(self):
        entries = inventory(ROOT)
        self.assertIn("element div#matrix-output", entries)
        self.assertIn("element select#graph-depth", entries)
        self.assertIn("element div#outline-drawer", entries)
        self.assertIn("element div#graph-node-detail", entries)
        self.assertIn("element strong#st-gaps", entries)
        self.assertIn("element strong#st-contested", entries)
        self.assertIn("element input#claim-text", entries)
        self.assertIn("handler runSynthesis", entries)
        self.assertIn("handler switchTab", entries)
        self.assertIn("route GET /", entries)
        self.assertIn("route POST /api/claims", entries)
        self.assertIn("token --warn", entries)


if __name__ == "__main__":
    unittest.main()
