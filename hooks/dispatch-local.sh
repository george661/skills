#!/bin/bash
# dispatch-local.sh — Thin wrapper that calls dispatch-local.py
# Exists for backward compat. All logic is in Python to avoid bash 3.2 issues on macOS.
exec python3 "$(dirname "$0")/dispatch-local.py" "$@"
