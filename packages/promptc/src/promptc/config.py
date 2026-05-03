"""Configuration for the promptc parser."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ParserConfig:
    """Configuration options for the parser."""

    max_tags: int = 1000
    max_nodes: int = 5000
    regex_timeout_ms: int = 100
