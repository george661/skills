"""Tests for state reducer registry and strategies."""
import pytest

from dag_executor.reducers import ReducerRegistry
from dag_executor.schema import ReducerStrategy


class TestOverwriteReducer:
    """Test overwrite reducer strategy."""

    def test_overwrite_none_with_value(self) -> None:
        """Test overwriting None with a value."""
        registry = ReducerRegistry()
        result = registry.apply(ReducerStrategy.OVERWRITE, None, "new_value")
        assert result == "new_value"

    def test_overwrite_existing_value(self) -> None:
        """Test overwriting an existing value."""
        registry = ReducerRegistry()
        result = registry.apply(ReducerStrategy.OVERWRITE, "old_value", "new_value")
        assert result == "new_value"

    def test_overwrite_dict(self) -> None:
        """Test overwriting a dict."""
        registry = ReducerRegistry()
        result = registry.apply(ReducerStrategy.OVERWRITE, {"a": 1}, {"b": 2})
        assert result == {"b": 2}


class TestAppendReducer:
    """Test append reducer strategy."""

    def test_append_to_none_creates_list(self) -> None:
        """Test appending to None creates a new list."""
        registry = ReducerRegistry()
        result = registry.apply(ReducerStrategy.APPEND, None, "item1")
        assert result == ["item1"]

    def test_append_to_list(self) -> None:
        """Test appending to an existing list."""
        registry = ReducerRegistry()
        result = registry.apply(ReducerStrategy.APPEND, ["item1"], "item2")
        assert result == ["item1", "item2"]

    def test_append_dict_to_list(self) -> None:
        """Test appending a dict to a list."""
        registry = ReducerRegistry()
        result = registry.apply(ReducerStrategy.APPEND, [{"a": 1}], {"b": 2})
        assert result == [{"a": 1}, {"b": 2}]

    def test_append_to_non_list_raises(self) -> None:
        """Test appending to non-list raises ValueError."""
        registry = ReducerRegistry()
        with pytest.raises(ValueError, match="APPEND strategy requires"):
            registry.apply(ReducerStrategy.APPEND, "not_a_list", "item")


class TestExtendReducer:
    """Test extend reducer strategy."""

    def test_extend_none_with_list(self) -> None:
        """Test extending None with a list."""
        registry = ReducerRegistry()
        result = registry.apply(ReducerStrategy.EXTEND, None, ["item1", "item2"])
        assert result == ["item1", "item2"]

    def test_extend_list_with_list(self) -> None:
        """Test extending a list with another list."""
        registry = ReducerRegistry()
        result = registry.apply(ReducerStrategy.EXTEND, ["item1"], ["item2", "item3"])
        assert result == ["item1", "item2", "item3"]

    def test_extend_list_with_single_item_appends(self) -> None:
        """Test extending a list with a single item appends it."""
        registry = ReducerRegistry()
        result = registry.apply(ReducerStrategy.EXTEND, ["item1"], "item2")
        assert result == ["item1", "item2"]

    def test_extend_non_list_current_raises(self) -> None:
        """Test extending non-list current raises ValueError."""
        registry = ReducerRegistry()
        with pytest.raises(ValueError, match="EXTEND strategy requires"):
            registry.apply(ReducerStrategy.EXTEND, "not_a_list", ["item"])


class TestMaxReducer:
    """Test max reducer strategy."""

    def test_max_none_with_number(self) -> None:
        """Test max with None returns the number."""
        registry = ReducerRegistry()
        result = registry.apply(ReducerStrategy.MAX, None, 5)
        assert result == 5

    def test_max_two_numbers(self) -> None:
        """Test max returns the larger number."""
        registry = ReducerRegistry()
        result = registry.apply(ReducerStrategy.MAX, 3, 7)
        assert result == 7

    def test_max_negative_numbers(self) -> None:
        """Test max with negative numbers."""
        registry = ReducerRegistry()
        result = registry.apply(ReducerStrategy.MAX, -5, -2)
        assert result == -2

    def test_max_floats(self) -> None:
        """Test max with floats."""
        registry = ReducerRegistry()
        result = registry.apply(ReducerStrategy.MAX, 3.14, 2.71)
        assert result == 3.14

    def test_max_non_numeric_raises(self) -> None:
        """Test max with non-numeric values raises ValueError."""
        registry = ReducerRegistry()
        with pytest.raises(ValueError, match="MAX strategy requires numeric"):
            registry.apply(ReducerStrategy.MAX, "not_a_number", 5)


class TestMinReducer:
    """Test min reducer strategy."""

    def test_min_none_with_number(self) -> None:
        """Test min with None returns the number."""
        registry = ReducerRegistry()
        result = registry.apply(ReducerStrategy.MIN, None, 5)
        assert result == 5

    def test_min_two_numbers(self) -> None:
        """Test min returns the smaller number."""
        registry = ReducerRegistry()
        result = registry.apply(ReducerStrategy.MIN, 3, 7)
        assert result == 3

    def test_min_negative_numbers(self) -> None:
        """Test min with negative numbers."""
        registry = ReducerRegistry()
        result = registry.apply(ReducerStrategy.MIN, -5, -2)
        assert result == -5

    def test_min_non_numeric_raises(self) -> None:
        """Test min with non-numeric values raises ValueError."""
        registry = ReducerRegistry()
        with pytest.raises(ValueError, match="MIN strategy requires numeric"):
            registry.apply(ReducerStrategy.MIN, 5, "not_a_number")


class TestMergeDictReducer:
    """Test merge_dict reducer strategy."""

    def test_merge_none_with_dict(self) -> None:
        """Test merging None with a dict."""
        registry = ReducerRegistry()
        result = registry.apply(ReducerStrategy.MERGE_DICT, None, {"a": 1})
        assert result == {"a": 1}

    def test_merge_two_dicts(self) -> None:
        """Test merging two dicts."""
        registry = ReducerRegistry()
        result = registry.apply(ReducerStrategy.MERGE_DICT, {"a": 1}, {"b": 2})
        assert result == {"a": 1, "b": 2}

    def test_merge_dicts_with_overlap_new_wins(self) -> None:
        """Test merging dicts with overlapping keys (new wins)."""
        registry = ReducerRegistry()
        result = registry.apply(ReducerStrategy.MERGE_DICT, {"a": 1, "b": 2}, {"b": 3, "c": 4})
        assert result == {"a": 1, "b": 3, "c": 4}

    def test_merge_dict_non_dict_current_raises(self) -> None:
        """Test merging with non-dict current raises ValueError."""
        registry = ReducerRegistry()
        with pytest.raises(ValueError, match="MERGE_DICT strategy requires"):
            registry.apply(ReducerStrategy.MERGE_DICT, "not_a_dict", {"a": 1})

    def test_merge_dict_non_dict_new_raises(self) -> None:
        """Test merging with non-dict new raises ValueError."""
        registry = ReducerRegistry()
        with pytest.raises(ValueError, match="MERGE_DICT strategy requires"):
            registry.apply(ReducerStrategy.MERGE_DICT, {"a": 1}, "not_a_dict")


class TestCustomReducer:
    """Test custom reducer strategy."""

    def test_custom_reducer_loads_and_executes(self) -> None:
        """Test custom reducer loads function and executes it."""
        # Create a test reducer module inline
        import sys
        import types

        test_module = types.ModuleType("test_reducers_module")
        test_module.sum_reducer = lambda current, new: (current or 0) + new
        sys.modules["test_reducers_module"] = test_module

        try:
            registry = ReducerRegistry()
            result = registry.apply(
                ReducerStrategy.CUSTOM,
                5,
                3,
                custom_function="test_reducers_module.sum_reducer"
            )
            assert result == 8
        finally:
            del sys.modules["test_reducers_module"]

    def test_custom_reducer_without_function_raises(self) -> None:
        """Test custom strategy without function path raises ValueError."""
        registry = ReducerRegistry()
        with pytest.raises(ValueError, match="CUSTOM strategy requires"):
            registry.apply(ReducerStrategy.CUSTOM, None, 5)

    def test_custom_reducer_invalid_path_raises(self) -> None:
        """Test custom strategy with invalid function path raises ValueError."""
        registry = ReducerRegistry()
        with pytest.raises(ValueError, match="Could not load custom reducer"):
            registry.apply(
                ReducerStrategy.CUSTOM,
                None,
                5,
                custom_function="nonexistent.module.function"
            )
