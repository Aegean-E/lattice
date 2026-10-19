"""The one error type every layer raises, carrying the Error/Why/Fix triad."""

from typing import NoReturn


class LatticeError(Exception):
    """A user-facing failure: what happened, why it matters and how to fix it."""

    def __init__(self, message: str, why: str, fix: str):
        super().__init__(message)
        self.message = message
        self.why = why
        self.fix = fix

    def render(self) -> str:
        """The full three-line report used by the CLI and the MCP server."""
        return f"Error: {self.message}\nWhy: {self.why}\nFix: {self.fix}"


def fail(message: str, why: str, fix: str) -> NoReturn:
    """Raise a `LatticeError`; keeps call sites to one line."""
    raise LatticeError(message, why, fix)
