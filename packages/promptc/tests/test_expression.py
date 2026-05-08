"""Tests for promptc.expression — safe expression evaluator for {% when %} conditions."""
from __future__ import annotations

from pathlib import Path

import pytest

from promptc.expression import ExpressionError, evaluate


class TestOperatorsHappyPath:
    """Test every supported operator with valid inputs."""

    def test_equality(self) -> None:
        assert evaluate("1 == 1", {}) is True
        assert evaluate("1 == 2", {}) is False

    def test_inequality(self) -> None:
        assert evaluate("1 != 2", {}) is True
        assert evaluate("1 != 1", {}) is False

    def test_less_than(self) -> None:
        assert evaluate("1 < 2", {}) is True
        assert evaluate("2 < 1", {}) is False

    def test_less_than_or_equal(self) -> None:
        assert evaluate("1 <= 2", {}) is True
        assert evaluate("2 <= 2", {}) is True
        assert evaluate("3 <= 2", {}) is False

    def test_greater_than(self) -> None:
        assert evaluate("2 > 1", {}) is True
        assert evaluate("1 > 2", {}) is False

    def test_greater_than_or_equal(self) -> None:
        assert evaluate("2 >= 1", {}) is True
        assert evaluate("2 >= 2", {}) is True
        assert evaluate("1 >= 2", {}) is False

    def test_logical_and(self) -> None:
        assert evaluate("True and True", {}) is True
        assert evaluate("True and False", {}) is False
        assert evaluate("x and y", {"x": True, "y": False}) is False

    def test_logical_or(self) -> None:
        assert evaluate("False or True", {}) is True
        assert evaluate("False or False", {}) is False
        assert evaluate("x or y", {"x": False, "y": True}) is True

    def test_logical_not(self) -> None:
        assert evaluate("not False", {}) is True
        assert evaluate("not True", {}) is False

    def test_in_operator(self) -> None:
        assert evaluate("'a' in ['a', 'b']", {}) is True
        assert evaluate("'c' in ['a', 'b']", {}) is False

    def test_not_in_operator(self) -> None:
        assert evaluate("'c' not in ['a', 'b']", {}) is True
        assert evaluate("'a' not in ['a', 'b']", {}) is False

    def test_addition(self) -> None:
        assert evaluate("1 + 2", {}) == 3

    def test_subtraction(self) -> None:
        assert evaluate("5 - 3", {}) == 2

    def test_multiplication(self) -> None:
        assert evaluate("3 * 4", {}) == 12

    def test_division(self) -> None:
        assert evaluate("10 / 2", {}) == 5.0

    def test_modulo(self) -> None:
        assert evaluate("10 % 3", {}) == 1

    def test_unary_minus(self) -> None:
        assert evaluate("-5", {}) == -5
        assert evaluate("-x", {"x": 5}) == -5

    def test_unary_plus(self) -> None:
        assert evaluate("+5", {}) == 5


class TestWhitelistedFunctions:
    """Test every whitelisted function."""

    def test_len_function(self) -> None:
        assert evaluate("len(xs)", {"xs": [1, 2, 3]}) == 3
        assert evaluate("len(xs) > 0", {"xs": [1, 2]}) is True
        assert evaluate("len(xs) == 0", {"xs": []}) is True

    def test_contains_function(self) -> None:
        assert evaluate("contains(s, 'foo')", {"s": "foobar"}) is True
        assert evaluate("contains(s, 'baz')", {"s": "foobar"}) is False
        assert evaluate("contains(xs, 2)", {"xs": [1, 2, 3]}) is True

    def test_startswith_function(self) -> None:
        assert evaluate("startswith(s, 'foo')", {"s": "foobar"}) is True
        assert evaluate("startswith(s, 'bar')", {"s": "foobar"}) is False

    def test_matches_function(self) -> None:
        assert evaluate("matches(s, '[a-z]+')", {"s": "abc"}) is True
        assert evaluate("matches(s, '[a-z]+')", {"s": "abc123"}) is False
        assert evaluate("matches(s, '\\\\d+')", {"s": "123"}) is True


class TestVariableAccess:
    """Test variable binding and JSON alias support."""

    def test_bare_variable(self) -> None:
        assert evaluate("x", {"x": 42}) == 42
        assert evaluate("x", {"x": "hello"}) == "hello"

    def test_json_false_alias(self) -> None:
        assert evaluate("x == false", {"x": False}) is True
        assert evaluate("false", {}) is False

    def test_json_true_alias(self) -> None:
        assert evaluate("x == true", {"x": True}) is True
        assert evaluate("true", {}) is True

    def test_json_null_alias(self) -> None:
        assert evaluate("x == null", {"x": None}) is True
        assert evaluate("null", {}) is None

    def test_caller_can_override_aliases(self) -> None:
        # Caller-provided values take precedence
        assert evaluate("true", {"true": "custom"}) == "custom"


class TestRejectionCases:
    """Test that disallowed constructs raise ExpressionError."""

    def test_unknown_variable(self) -> None:
        with pytest.raises(ExpressionError, match="unknown_var"):
            evaluate("unknown_var", {})

    def test_non_whitelisted_function(self) -> None:
        with pytest.raises(ExpressionError, match="__import__|non-whitelisted"):
            evaluate("__import__('os')", {})

    def test_attribute_access(self) -> None:
        with pytest.raises(ExpressionError, match="unsupported|Attribute"):
            evaluate("os.system('ls')", {})

    def test_method_call(self) -> None:
        with pytest.raises(ExpressionError, match="unsupported|Attribute|call target"):
            evaluate("x.upper()", {"x": "a"})

    def test_subscript(self) -> None:
        with pytest.raises(ExpressionError, match="unsupported|Subscript"):
            evaluate("x[0]", {"x": [1, 2]})

    def test_lambda(self) -> None:
        with pytest.raises(ExpressionError, match="unsupported|Lambda"):
            evaluate("lambda y: y", {})

    def test_list_comprehension(self) -> None:
        with pytest.raises(ExpressionError, match="unsupported|ListComp"):
            evaluate("[i for i in range(3)]", {})

    def test_power_operator(self) -> None:
        with pytest.raises(ExpressionError, match="unsupported|Pow"):
            evaluate("2 ** 10", {})

    def test_f_string(self) -> None:
        with pytest.raises(ExpressionError, match="unsupported|JoinedStr"):
            evaluate("f'{x}'", {"x": 1})

    def test_walrus_operator(self) -> None:
        with pytest.raises(ExpressionError, match="unsupported|NamedExpr"):
            evaluate("(x := 5)", {})

    def test_syntax_error(self) -> None:
        with pytest.raises(ExpressionError, match="parse error"):
            evaluate("1 +", {})

    def test_callable_runtime_error_wrapped(self) -> None:
        # re.fullmatch on non-string raises TypeError — must surface as ExpressionError
        with pytest.raises(ExpressionError, match="matches.*failed"):
            evaluate("matches(42, '\\\\d+')", {})


class TestStaticInvariants:
    """Static checks on the module source."""

    def test_no_eval_or_exec_in_source(self) -> None:
        src = (
            Path(__file__).parent.parent / "src" / "promptc" / "expression.py"
        ).read_text()
        import re

        assert not re.search(r"\beval\(", src), "eval() found in expression.py"
        assert not re.search(r"\bexec\(", src), "exec() found in expression.py"
        assert not re.search(
            r"\bcompile\(", src
        ), "compile() found in expression.py"

    def test_no_dag_executor_import(self) -> None:
        src = (
            Path(__file__).parent.parent / "src" / "promptc" / "expression.py"
        ).read_text()
        import re

        # Look for actual import statements, not docstring mentions
        assert not re.search(
            r"^import dag_executor", src, re.MULTILINE
        ), "dag_executor import found"
        assert not re.search(
            r"^from dag_executor", src, re.MULTILINE
        ), "dag_executor import found"

    def test_docstring_mentions_parity(self) -> None:
        import promptc.expression

        doc = promptc.expression.__doc__ or ""
        assert (
            "promptc-evaluator-parity" in doc
        ), "docstring missing parity CI job reference"
        assert (
            "expression_parity.json" in doc
        ), "docstring missing parity fixture reference"


def test_validate_expr_parity_with_evaluate() -> None:
    """validate_expr should return [] iff evaluate does not raise ExpressionError."""
    import json

    from promptc.expression import validate_expr

    # Load parity fixtures
    fixtures_path = Path(__file__).parent / "fixtures" / "expression_parity.json"
    if not fixtures_path.exists():
        pytest.skip("expression_parity.json not found")

    with open(fixtures_path) as f:
        cases = json.load(f)

    for case in cases:
        expr = case["expr"]
        bindings = case["bindings"]

        # Test validate_expr
        known_names = list(bindings.keys())
        issues = validate_expr(expr, known_names)
        validate_ok = len(issues) == 0

        # Test evaluate
        from promptc.expression import ExpressionError, evaluate
        try:
            evaluate(expr, bindings)
            eval_ok = True
        except ExpressionError:
            eval_ok = False

        # They should agree
        assert validate_ok == eval_ok, (
            f"validate_expr and evaluate disagree on '{expr}': "
            f"validate_ok={validate_ok}, eval_ok={eval_ok}, issues={issues}"
        )
