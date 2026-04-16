"""State reducer registry for merging node outputs."""
import importlib
from typing import Any, Callable, Dict, Optional, Union

from dag_executor.schema import ReducerStrategy, ReducerDef


class ReducerRegistry:
    """Registry for state reduction strategies.

    Provides built-in strategies and custom function loading for merging
    outputs from multiple nodes into shared workflow state.
    """

    def apply(
        self,
        strategy: ReducerStrategy,
        current_value: Any,
        new_value: Any,
        custom_function: Optional[str] = None
    ) -> Any:
        """Apply reducer strategy to merge new value into current value.

        Args:
            strategy: Reducer strategy to use
            current_value: Current value in workflow state (may be None)
            new_value: New value from node output
            custom_function: Dotted path to custom reducer function (for CUSTOM strategy)

        Returns:
            Merged value

        Raises:
            ValueError: If strategy requirements are not met or custom function fails
        """
        if strategy == ReducerStrategy.OVERWRITE:
            return self._overwrite(current_value, new_value)
        elif strategy == ReducerStrategy.APPEND:
            return self._append(current_value, new_value)
        elif strategy == ReducerStrategy.EXTEND:
            return self._extend(current_value, new_value)
        elif strategy == ReducerStrategy.MAX:
            return self._max(current_value, new_value)
        elif strategy == ReducerStrategy.MIN:
            return self._min(current_value, new_value)
        elif strategy == ReducerStrategy.MERGE_DICT:
            return self._merge_dict(current_value, new_value)
        elif strategy == ReducerStrategy.CUSTOM:
            return self._custom(current_value, new_value, custom_function)
        else:
            raise ValueError(f"Unknown reducer strategy: {strategy}")

    def _overwrite(self, current_value: Any, new_value: Any) -> Any:
        """Overwrite strategy: replace current with new."""
        return new_value

    def _append(self, current_value: Any, new_value: Any) -> Any:
        """Append strategy: append new item to list."""
        if current_value is None:
            return [new_value]
        if not isinstance(current_value, list):
            raise ValueError(
                f"APPEND strategy requires current value to be None or list, "
                f"got {type(current_value).__name__}"
            )
        return current_value + [new_value]

    def _extend(self, current_value: Any, new_value: Any) -> Any:
        """Extend strategy: extend list with list or append single item."""
        if current_value is None:
            if isinstance(new_value, list):
                return new_value.copy()
            return [new_value]
        if not isinstance(current_value, list):
            raise ValueError(
                f"EXTEND strategy requires current value to be None or list, "
                f"got {type(current_value).__name__}"
            )
        if isinstance(new_value, list):
            return current_value + new_value
        return current_value + [new_value]

    def _max(self, current_value: Any, new_value: Any) -> Any:
        """Max strategy: return maximum of current and new."""
        if current_value is None:
            return new_value
        if not isinstance(current_value, (int, float)) or not isinstance(new_value, (int, float)):
            raise ValueError(
                f"MAX strategy requires numeric values, got "
                f"{type(current_value).__name__} and {type(new_value).__name__}"
            )
        return max(current_value, new_value)

    def _min(self, current_value: Any, new_value: Any) -> Any:
        """Min strategy: return minimum of current and new."""
        if current_value is None:
            return new_value
        if not isinstance(current_value, (int, float)) or not isinstance(new_value, (int, float)):
            raise ValueError(
                f"MIN strategy requires numeric values, got "
                f"{type(current_value).__name__} and {type(new_value).__name__}"
            )
        return min(current_value, new_value)

    def _merge_dict(self, current_value: Any, new_value: Any) -> Any:
        """Merge dict strategy: merge new dict into current dict."""
        if current_value is None:
            if not isinstance(new_value, dict):
                raise ValueError(
                    f"MERGE_DICT strategy requires new value to be dict, "
                    f"got {type(new_value).__name__}"
                )
            return new_value.copy()
        if not isinstance(current_value, dict):
            raise ValueError(
                f"MERGE_DICT strategy requires current value to be None or dict, "
                f"got {type(current_value).__name__}"
            )
        if not isinstance(new_value, dict):
            raise ValueError(
                f"MERGE_DICT strategy requires new value to be dict, "
                f"got {type(new_value).__name__}"
            )
        return {**current_value, **new_value}

    def _custom(
        self,
        current_value: Any,
        new_value: Any,
        custom_function: Optional[str]
    ) -> Any:
        """Custom strategy: load and execute custom reducer function.

        Args:
            current_value: Current value
            new_value: New value
            custom_function: Dotted path to function (e.g., 'mypackage.reducers.merge')

        Returns:
            Result of custom function

        Raises:
            ValueError: If custom_function is not provided or cannot be loaded
        """
        if not custom_function:
            raise ValueError(
                "CUSTOM strategy requires custom_function parameter with dotted path"
            )

        try:
            module_path, function_name = custom_function.rsplit(".", 1)
            module = importlib.import_module(module_path)
            reducer_func: Callable[[Any, Any], Any] = getattr(module, function_name)
            return reducer_func(current_value, new_value)
        except (ValueError, ImportError, AttributeError) as e:
            raise ValueError(
                f"Could not load custom reducer function '{custom_function}': {e}"
            ) from e


def parse_reducer(spec: Union[Dict[str, Any], ReducerDef]) -> ReducerDef:
    """Parse reducer specification from inline dict or explicit ReducerDef.

    Supports two formats:
    1. Explicit ReducerDef: Already validated, return as-is
    2. Inline dict: {strategy: "append"} → ReducerDef(strategy="append")

    Args:
        spec: Reducer specification (dict or ReducerDef)

    Returns:
        Validated ReducerDef object

    Raises:
        ValueError: If spec is invalid

    Examples:
        >>> parse_reducer({"strategy": "append"})
        ReducerDef(strategy=ReducerStrategy.APPEND, function=None)

        >>> parse_reducer(ReducerDef(strategy=ReducerStrategy.OVERWRITE))
        ReducerDef(strategy=ReducerStrategy.OVERWRITE, function=None)
    """
    # If already a ReducerDef, return as-is
    if isinstance(spec, ReducerDef):
        return spec

    # If dict, parse to ReducerDef
    if isinstance(spec, dict):
        # Inline format: {strategy: "append"} or {strategy: "custom", function: "..."}
        if "strategy" in spec:
            strategy_str = spec["strategy"]
            # Convert string to ReducerStrategy enum
            try:
                strategy = ReducerStrategy(strategy_str)
            except ValueError:
                raise ValueError(f"Invalid reducer strategy: '{strategy_str}'")

            function = spec.get("function")
            return ReducerDef(strategy=strategy, function=function)
        else:
            raise ValueError("Inline reducer dict must have 'strategy' key")

    raise ValueError(f"Invalid reducer spec type: {type(spec)}")
