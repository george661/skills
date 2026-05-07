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


class RenderError(Exception):
    """Raised when rendering fails due to missing inputs, type errors, or unsupported features."""

    def __init__(
        self,
        message: str,
        *,
        missing: list[str] | None = None,
        type_errors: list[str] | None = None,
        path: str | None = None,
    ) -> None:
        self.message = message
        self.missing = missing or []
        self.type_errors = type_errors or []
        self.path = path

        # Build summary
        parts = [message]
        if self.missing:
            parts.append(f"missing: {', '.join(self.missing)}")
        if self.type_errors:
            parts.append(f"type errors: {', '.join(self.type_errors)}")
        if self.path:
            parts.append(f"path: {self.path}")

        super().__init__("; ".join(parts))
