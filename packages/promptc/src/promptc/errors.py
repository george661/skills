"""Structured errors for the promptc parser."""
from __future__ import annotations


class ParseError(Exception):
    """Structured parse error with line and column information."""

    def __init__(self, message: str, line: int, column: int, path: str | None = None) -> None:
        self.message = message
        self.line = line
        self.column = column
        self.path = path

        if path:
            super().__init__(f"{path}:{line}:{column}: {message}")
        else:
            super().__init__(f"Parse error at line {line}, column {column}: {message}")


class LimitExceededError(Exception):
    """Raised when tag count or AST node limits are exceeded."""

    def __init__(self, message: str, limit: int, actual: int) -> None:
        super().__init__(f"{message}: limit={limit}, actual={actual}")
        self.message = message
        self.limit = limit
        self.actual = actual


class TimeoutError(Exception):
    """Raised when regex match exceeds configured timeout."""

    def __init__(self, message: str, timeout_ms: int) -> None:
        super().__init__(f"{message}: timeout={timeout_ms}ms")
        self.message = message
        self.timeout_ms = timeout_ms
