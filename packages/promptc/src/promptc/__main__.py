"""Allow running promptc as a module: python -m promptc."""
from __future__ import annotations

from promptc.cli import main

raise SystemExit(main())
