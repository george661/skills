"""Parity test: verify promptc.expression matches simpleeval behavior on whitelisted cases."""
from __future__ import annotations

import json
import pathlib
import re

import pytest

from promptc.expression import evaluate

simpleeval = pytest.importorskip("simpleeval")

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "expression_parity.json"

# Whitelist mirrored from promptc.expression._FUNCS. If this drifts from the
# module, the parity CI job (GW-5483) will catch it.
_PARITY_FUNCS = {
    "len": len,
    "contains": lambda hay, needle: needle in hay,
    "startswith": lambda s, prefix: s.startswith(prefix),
    "matches": lambda s, pattern: bool(re.fullmatch(pattern, s)),
}


@pytest.mark.parametrize("case", json.loads(FIXTURE.read_text()))
def test_parity(case: dict) -> None:
    """Test that promptc and simpleeval produce identical results."""
    expr, names, expected = case["expr"], case["names"], case["expected"]

    ours = evaluate(expr, names)

    their_names = {**names, "true": True, "false": False, "null": None}
    their_eval = simpleeval.SimpleEval(names=their_names, functions=_PARITY_FUNCS)
    theirs = their_eval.eval(expr)

    assert ours == expected, f"promptc diverged from expected on {expr!r}"
    assert theirs == expected, f"simpleeval diverged from expected on {expr!r}"
    assert ours == theirs, f"promptc vs simpleeval diverged on {expr!r}"
