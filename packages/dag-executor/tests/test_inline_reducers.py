"""Tests for inline reducer syntax parsing."""
import pytest
from dag_executor.reducers import parse_reducer
from dag_executor.schema import ReducerDef, ReducerStrategy


class TestInlineReducers:
    """Test inline reducer syntax parsing."""

    def test_inline_strategy_only(self) -> None:
        """Inline syntax {strategy: append} produces correct ReducerDef."""
        inline_spec = {"strategy": "append"}
        reducer = parse_reducer(inline_spec)

        assert isinstance(reducer, ReducerDef)
        assert reducer.strategy == ReducerStrategy.APPEND
        assert reducer.function is None

    def test_explicit_reducer_def_unchanged(self) -> None:
        """Explicit ReducerDef returned as-is."""
        explicit = ReducerDef(strategy=ReducerStrategy.OVERWRITE)
        result = parse_reducer(explicit)

        assert result is explicit
        assert result.strategy == ReducerStrategy.OVERWRITE

    def test_inline_with_custom_function(self) -> None:
        """Inline syntax with custom function."""
        inline_spec = {"strategy": "custom", "function": "mymodule.my_reducer"}
        reducer = parse_reducer(inline_spec)

        assert reducer.strategy == ReducerStrategy.CUSTOM
        assert reducer.function == "mymodule.my_reducer"

    def test_all_builtin_strategies(self) -> None:
        """All built-in reducer strategies work with parse_reducer."""
        strategies = ["overwrite", "append", "extend", "max", "min", "merge_dict"]

        for strategy_name in strategies:
            inline_spec = {"strategy": strategy_name}
            reducer = parse_reducer(inline_spec)
            assert reducer.strategy.value == strategy_name

    def test_invalid_strategy_raises(self) -> None:
        """Invalid strategy raises ValueError."""
        inline_spec = {"strategy": "invalid_strategy"}

        with pytest.raises(ValueError, match="Invalid reducer strategy"):
            parse_reducer(inline_spec)

    def test_missing_strategy_key_raises(self) -> None:
        """Missing strategy key raises ValueError."""
        inline_spec = {"foo": "bar"}

        with pytest.raises(ValueError, match="must have 'strategy' key"):
            parse_reducer(inline_spec)

    def test_invalid_type_raises(self) -> None:
        """Invalid spec type raises ValueError."""
        with pytest.raises(ValueError, match="Invalid reducer spec type"):
            parse_reducer("not a dict or ReducerDef")  # type: ignore
