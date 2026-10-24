"""
Print Lattice's UI inventory, one entry per line.

The UI guard snapshots this output before a surface edit and compares it afterwards, so
a dropped control, click handler, API route or theme token becomes a lost line. The dump
is pure parsing of the served studio HTML and the dispatcher source: it never starts a
server or a browser, and its order is stable.

Usage: python tools/ui_inventory.py [project-root]

PRINCIPLE-003, PRINCIPLE-010, PRINCIPLE-015.
"""

import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from typing import List, Set

ROOT = Path(__file__).resolve().parent.parent
GET_ROUTE_PATTERN = re.compile(r'verb == "GET" and route == "([^"]+)"')
POST_DEF_PATTERN = re.compile(r"def _dispatch_post\(.*?(?=\ndef |\Z)", re.DOTALL)
ROUTE_PATTERN = re.compile(r'route == "([^"]+)"')
TOKEN_PATTERN = re.compile(r"^\s*(--[a-z0-9-]+)\s*:", re.MULTILINE)
ONCLICK_NAME = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s*\(")


class SurfaceParser(HTMLParser):
    """Collects identified elements, click handlers, roles and live regions of the studio."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.entries: Set[str] = set()

    def handle_starttag(self, tag: str, attrs) -> None:
        values = {name: value or "" for name, value in attrs}
        element = values.get("id")
        if element:
            self.entries.add(f"element {tag}#{element}")
        if "aria-live" in values:
            self.entries.add(f"live-region {values.get('id') or tag}")
        if values.get("role"):
            self.entries.add(f"role {values['role']}")
        handler = values.get("onclick")
        if handler:
            match = ONCLICK_NAME.search(handler)
            if match:
                self.entries.add(f"handler {match.group(1)}")


def html_entries(html: str) -> Set[str]:
    """Identified elements, click handlers, roles and live regions of the studio page."""
    parser = SurfaceParser()
    parser.feed(html)
    parser.close()
    return parser.entries


def token_entries(html: str) -> Set[str]:
    """Theme custom properties the studio's embedded stylesheet declares."""
    return {f"token {name}" for name in TOKEN_PATTERN.findall(html)}


def route_entries(source: str) -> Set[str]:
    """The GET and POST routes the web dispatcher answers, parsed from its source."""
    entries = {f"route GET {route}" for route in GET_ROUTE_PATTERN.findall(source)}
    post_body = POST_DEF_PATTERN.search(source)
    if post_body is not None:
        entries |= {f"route POST {route}" for route in ROUTE_PATTERN.findall(post_body.group(0))}
    return entries


def _studio_html(root: Path) -> str:
    """The exact HTML the studio serves, imported from the package rather than re-parsed."""
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from lattice.web import WEB_HTML
    return WEB_HTML


def inventory(root: Path) -> List[str]:
    """Every inventory entry of the studio surface, sorted and deduplicated."""
    source = (root / "lattice" / "web.py").read_text(encoding="utf-8")
    html = _studio_html(root)
    entries = route_entries(source) | html_entries(html) | token_entries(html)
    return sorted(entries)


def main(argv: List[str]) -> int:
    """Write the inventory to stdout; exit 1 when the surface has no entries at all."""
    root = Path(argv[1]).resolve() if len(argv) > 1 else ROOT
    module = root / "lattice" / "web.py"
    if not module.is_file():
        print(f"no such studio module: {module}", file=sys.stderr)
        print("Why: the inventory proof needs lattice/web.py, the studio surface.", file=sys.stderr)
        print("Fix: run it from the project root, or pass the project root.", file=sys.stderr)
        return 2
    try:
        entries = inventory(root)
    except ImportError as exc:
        print(f"cannot import the studio module: {exc}", file=sys.stderr)
        print("Why: the inventory reads the exact HTML the studio serves.", file=sys.stderr)
        print("Fix: run it from the project root with lattice/ importable.", file=sys.stderr)
        return 2
    if not entries:
        print(f"no UI inventory found for {root}", file=sys.stderr)
        print("Why: an empty inventory would hide every lost control.", file=sys.stderr)
        print("Fix: check that lattice/web.py still carries ids, handlers, routes and tokens.",
              file=sys.stderr)
        return 1
    print("\n".join(entries))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
