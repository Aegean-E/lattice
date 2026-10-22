#!/usr/bin/env python3
"""Start file launcher for the Lattice Research Studio and CLI."""

import sys
from pathlib import Path

# Ensure the local lattice package is importable when executed directly
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from lattice.cli import main  # noqa: E402


def _with_project_db(argv):
    """Use the project-local database unless the caller explicitly chose one."""
    if any(arg == "--db" or arg.startswith("--db=") for arg in argv[1:]):
        return argv
    return [argv[0], "--db", str(_ROOT / "lattice.db"), *argv[1:]]


def start(argv=None) -> int:
    """Launch the Lattice Web Research Studio by default, or forward custom CLI arguments."""
    if argv is not None:
        sys.argv = list(argv)
    if len(sys.argv) == 1:
        # Default zero-friction startup: launch local web studio in browser with demo corpus
        sys.argv.extend(["web", "--open", "--demo"])
    sys.argv = _with_project_db(sys.argv)
    return main()


if __name__ == "__main__":
    sys.exit(start())
