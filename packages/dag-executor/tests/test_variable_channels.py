"""Tests for variable resolution with ChannelStore integration.

Tests the channel-first lookup behavior when channel_store parameter is provided
to resolve_variables().
"""
import pytest
from typing import Any, Dict, Tuple

from dag_executor.variables import resolve_variables, VariableResolutionError
from dag_executor.channels import ChannelStore, LastValueChannel


class MockChannelStore:
    """Mock ChannelStore for testing without full workflow setup."""
    
    def __init__(self, data: Dict[str, Tuple[Any, int]]):
        """Initialize with data map of key -> (value, version)."""
        self._data = data
    
    def read(self, key: str) -> Tuple[Any, int]:
        """Read value and version from mock store."""
        if key not in self._data:
            raise KeyError(f"Channel '{key}' not found")
        return self._data[key]


def test_resolve_from_channel_store():
    """Test that resolve_variables reads from channel_store when provided."""
    channel_store = MockChannelStore({
        "user_name": ("Alice", 1),
        "user_age": (30, 1)
    })
    
    result = resolve_variables(
        "$user_name",
        node_outputs={},
        workflow_inputs={},
        channel_store=channel_store
    )
    
    assert result == "Alice"


def test_channel_store_priority_over_node_outputs():
    """Test that channel_store lookup takes priority over node_outputs."""
    channel_store = MockChannelStore({
        "result": ({"channel": "value"}, 1)
    })
    
    node_outputs = {
        "result": {"node": "value"}
    }
    
    result = resolve_variables(
        "$result",
        node_outputs=node_outputs,
        workflow_inputs={},
        channel_store=channel_store
    )
    
    # Should get channel value, not node_outputs value
    assert result == {"channel": "value"}


def test_fallback_to_node_outputs_when_no_channel_store():
    """Test backwards compatibility: when channel_store=None, use node_outputs."""
    node_outputs = {
        "node1": {"output": "value"}
    }
    
    result = resolve_variables(
        "$node1.output",
        node_outputs=node_outputs,
        workflow_inputs={},
        channel_store=None
    )
    
    assert result == "value"


def test_fallback_to_node_outputs_on_channel_miss():
    """Test that when key not in channel_store, falls back to node_outputs."""
    channel_store = MockChannelStore({
        "channel_key": ("channel_value", 1)
    })
    
    node_outputs = {
        "node_key": {"output": "node_value"}
    }
    
    result = resolve_variables(
        "$node_key.output",
        node_outputs=node_outputs,
        workflow_inputs={},
        channel_store=channel_store
    )
    
    # Key not in channel_store, should fall back to node_outputs
    assert result == "node_value"


def test_error_includes_channel_version():
    """Test that VariableResolutionError includes channel version when available."""
    channel_store = MockChannelStore({
        "user": ({"name": "Alice"}, 3)
    })
    
    with pytest.raises(VariableResolutionError) as exc_info:
        resolve_variables(
            "$user.missing_field",
            node_outputs={},
            workflow_inputs={},
            channel_store=channel_store
        )
    
    error = exc_info.value
    # Should have channel_version attribute
    assert hasattr(error, "channel_version")
    assert error.channel_version == 3


def test_nested_path_traversal_from_channel():
    """Test that nested path traversal works with channel values."""
    channel_store = MockChannelStore({
        "config": ({"database": {"host": "localhost", "port": 5432}}, 1)
    })
    
    result = resolve_variables(
        "$config.database.host",
        node_outputs={},
        workflow_inputs={},
        channel_store=channel_store
    )
    
    assert result == "localhost"


def test_channel_value_tuple_unpacking():
    """Test that (value, version) tuple from channel.read() is properly unpacked."""
    channel_store = MockChannelStore({
        "data": ([1, 2, 3], 5)
    })
    
    result = resolve_variables(
        "$data",
        node_outputs={},
        workflow_inputs={},
        channel_store=channel_store
    )
    
    # Should return the value, not the tuple
    assert result == [1, 2, 3]
    assert not isinstance(result, tuple)


def test_backwards_compat_all_existing_tests_pass():
    """Test that existing variable resolution still works without channel_store.
    
    This verifies backwards compatibility - resolve_variables should work
    exactly as before when channel_store parameter is not provided.
    """
    node_outputs = {
        "node1": {"output": "value1"},
        "node2": {"result": {"nested": "value2"}}
    }
    
    workflow_inputs = {
        "input1": "input_value"
    }
    
    # Test node reference
    assert resolve_variables(
        "$node1.output",
        node_outputs=node_outputs,
        workflow_inputs=workflow_inputs
    ) == "value1"
    
    # Test workflow input reference
    assert resolve_variables(
        "$input1",
        node_outputs=node_outputs,
        workflow_inputs=workflow_inputs
    ) == "input_value"
    
    # Test nested node reference
    assert resolve_variables(
        "$node2.result.nested",
        node_outputs=node_outputs,
        workflow_inputs=workflow_inputs
    ) == "value2"
