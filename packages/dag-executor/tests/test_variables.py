"""Tests for variable substitution engine."""
import pytest
from dag_executor.variables import resolve_variables, VariableResolutionError


class TestSimpleReferences:
    """Test basic variable reference resolution."""
    
    def test_simple_node_output_reference(self) -> None:
        """Test $node.output resolves to full output object."""
        node_outputs = {
            "fetch-user": {"output": {"id": 123, "name": "Alice"}}
        }
        result = resolve_variables("$fetch-user.output", node_outputs, {})
        assert result == {"id": 123, "name": "Alice"}
    
    def test_nested_field_access(self) -> None:
        """Test $node.output.data.field resolves to nested value."""
        node_outputs = {
            "fetch-data": {"output": {"data": {"field": "value123"}}}
        }
        result = resolve_variables("$fetch-data.output.data.field", node_outputs, {})
        assert result == "value123"
    
    def test_workflow_input_reference(self) -> None:
        """Test $input_name resolves to workflow input value."""
        workflow_inputs = {"issue_key": "GW-123"}
        result = resolve_variables("$issue_key", {}, workflow_inputs)
        assert result == "GW-123"


class TestStringInterpolation:
    """Test variable references in string templates."""
    
    def test_reference_in_string_template(self) -> None:
        """Test references mixed with text are interpolated."""
        node_outputs = {
            "fetch-user": {"output": {"name": "Bob"}}
        }
        result = resolve_variables(
            "Processing $fetch-user.output.name",
            node_outputs,
            {}
        )
        assert result == "Processing Bob"
    
    def test_pure_reference_returns_native_object(self) -> None:
        """Test string with only a reference returns the object, not stringified."""
        node_outputs = {
            "fetch-user": {"output": {"id": 456, "active": True}}
        }
        result = resolve_variables("$fetch-user.output", node_outputs, {})
        assert result == {"id": 456, "active": True}
        assert isinstance(result, dict)
    
    def test_pure_reference_returns_list(self) -> None:
        """Test pure reference can return a list."""
        node_outputs = {
            "get-items": {"output": [1, 2, 3]}
        }
        result = resolve_variables("$get-items.output", node_outputs, {})
        assert result == [1, 2, 3]
        assert isinstance(result, list)


class TestRecursiveResolution:
    """Test recursive resolution in data structures."""
    
    def test_dict_values_resolution(self) -> None:
        """Test references in dict values are resolved."""
        node_outputs = {
            "node1": {"output": {"key": "resolved_value"}}
        }
        value = {
            "field1": "$node1.output.key",
            "field2": "static"
        }
        result = resolve_variables(value, node_outputs, {})
        assert result == {
            "field1": "resolved_value",
            "field2": "static"
        }
    
    def test_list_resolution(self) -> None:
        """Test references in list items are resolved."""
        node_outputs = {
            "node1": {"output": {"val": "A"}},
            "node2": {"output": {"val": "B"}}
        }
        value = ["$node1.output.val", "static", "$node2.output.val"]
        result = resolve_variables(value, node_outputs, {})
        assert result == ["A", "static", "B"]
    
    def test_nested_data_structures(self) -> None:
        """Test recursive resolution in nested dicts and lists."""
        node_outputs = {
            "config": {"output": {"url": "https://api.example.com"}}
        }
        value = {
            "endpoints": [
                {"name": "api", "url": "$config.output.url"},
                {"name": "backup", "url": "https://backup.com"}
            ]
        }
        result = resolve_variables(value, node_outputs, {})
        assert result == {
            "endpoints": [
                {"name": "api", "url": "https://api.example.com"},
                {"name": "backup", "url": "https://backup.com"}
            ]
        }


class TestErrorHandling:
    """Test error handling and messages."""
    
    def test_unresolved_reference_error(self) -> None:
        """Test unresolved reference produces clear error."""
        node_outputs = {
            "node1": {"output": {"key": "value"}}
        }
        with pytest.raises(VariableResolutionError) as exc_info:
            resolve_variables("$missing-node.output", node_outputs, {})
        
        error_msg = str(exc_info.value)
        assert "missing-node" in error_msg
        assert "node1" in error_msg  # Should show available nodes
    
    def test_unresolvable_nested_path_error(self) -> None:
        """Test unresolvable nested path produces clear error."""
        node_outputs = {
            "node1": {"output": {"key": "value"}}
        }
        with pytest.raises(VariableResolutionError) as exc_info:
            resolve_variables("$node1.output.missing.path", node_outputs, {})
        
        error_msg = str(exc_info.value)
        assert "missing" in error_msg
        assert "node1.output.missing.path" in error_msg
    
    def test_error_includes_available_context(self) -> None:
        """Test error message includes available nodes and inputs."""
        node_outputs = {
            "node1": {"output": {}},
            "node2": {"output": {}}
        }
        workflow_inputs = {
            "input1": "val1",
            "input2": "val2"
        }
        with pytest.raises(VariableResolutionError) as exc_info:
            resolve_variables("$invalid_ref", node_outputs, workflow_inputs)
        
        error_msg = str(exc_info.value)
        # Should mention available context
        assert "node1" in error_msg or "input1" in error_msg


class TestNoOpBehavior:
    """Test no-op behavior when no references present."""
    
    def test_no_references_returns_unchanged(self) -> None:
        """Test values without references pass through unchanged."""
        value = {"key": "value", "list": [1, 2, 3]}
        result = resolve_variables(value, {}, {})
        assert result == value
    
    def test_string_without_references_unchanged(self) -> None:
        """Test strings without $ pass through unchanged."""
        result = resolve_variables("plain text", {}, {})
        assert result == "plain text"
    
    def test_primitive_values_unchanged(self) -> None:
        """Test primitive values pass through."""
        assert resolve_variables(123, {}, {}) == 123
        assert resolve_variables(True, {}, {}) is True
        assert resolve_variables(None, {}, {}) is None


class TestHyphenatedNodeIds:
    """Test hyphenated node IDs (e.g., fetch-data)."""
    
    def test_hyphenated_node_id(self) -> None:
        """Test $fetch-data.output.result works with hyphens."""
        node_outputs = {
            "fetch-data": {"output": {"result": "success"}}
        }
        result = resolve_variables("$fetch-data.output.result", node_outputs, {})
        assert result == "success"
    
    def test_multiple_hyphens_in_node_id(self) -> None:
        """Test node IDs with multiple hyphens."""
        node_outputs = {
            "fetch-user-data": {"output": {"value": 42}}
        }
        result = resolve_variables("$fetch-user-data.output.value", node_outputs, {})
        assert result == 42


class TestResolutionPriority:
    """Test resolution priority (node outputs before workflow inputs)."""

    def test_node_outputs_take_priority(self) -> None:
        """Test node outputs are checked before workflow inputs."""
        node_outputs = {
            "data": {"output": {"value": "from_node"}}
        }
        workflow_inputs = {
            "data": "from_input"
        }
        # $data.output should resolve from node_outputs, not inputs
        result = resolve_variables("$data.output", node_outputs, workflow_inputs)
        assert result == {"value": "from_node"}

    def test_workflow_input_used_if_no_node_match(self) -> None:
        """Test workflow inputs used if node lookup fails."""
        node_outputs = {
            "node1": {"output": {}}
        }
        workflow_inputs = {
            "issue_key": "GW-999"
        }
        result = resolve_variables("$issue_key", node_outputs, workflow_inputs)
        assert result == "GW-999"


class TestExtractVariableReferences:
    """Test static analysis of variable references."""

    def test_extract_from_string(self) -> None:
        """Test extracting references from a simple string."""
        from dag_executor.variables import extract_variable_references

        text = "Hello $node1.output and $node2.result"
        refs = extract_variable_references(text)
        assert set(refs) == {
            ("node1", "output"),
            ("node2", "result")
        }

    def test_extract_from_dict(self) -> None:
        """Test extracting references from dict values."""
        from dag_executor.variables import extract_variable_references

        data = {
            "field1": "$node1.output.data",
            "field2": "static",
            "field3": "$node2.value"
        }
        refs = extract_variable_references(data)
        assert set(refs) == {
            ("node1", "output.data"),
            ("node2", "value")
        }

    def test_extract_from_list(self) -> None:
        """Test extracting references from list items."""
        from dag_executor.variables import extract_variable_references

        data = ["$node1.output", "static", "$node2.result"]
        refs = extract_variable_references(data)
        assert set(refs) == {
            ("node1", "output"),
            ("node2", "result")
        }

    def test_extract_from_nested_structures(self) -> None:
        """Test extracting from nested dicts and lists."""
        from dag_executor.variables import extract_variable_references

        data = {
            "items": [
                {"url": "$config.api_url"},
                {"url": "https://backup.com"}
            ],
            "script": "curl $fetch-data.output.url"
        }
        refs = extract_variable_references(data)
        assert set(refs) == {
            ("config", "api_url"),
            ("fetch-data", "output.url")
        }

    def test_extract_no_references(self) -> None:
        """Test extracting from data with no references."""
        from dag_executor.variables import extract_variable_references

        data = {"key": "value", "list": [1, 2, 3]}
        refs = extract_variable_references(data)
        assert refs == []

    def test_extract_workflow_input_references(self) -> None:
        """Test extracting workflow input references (single part)."""
        from dag_executor.variables import extract_variable_references

        text = "Issue: $issue_key and $repo"
        refs = extract_variable_references(text)
        # Workflow inputs have empty field_path
        assert set(refs) == {
            ("issue_key", ""),
            ("repo", "")
        }

    def test_extract_deduplicates(self) -> None:
        """Test that duplicate references are deduplicated."""
        from dag_executor.variables import extract_variable_references

        text = "First $node.output and second $node.output"
        refs = extract_variable_references(text)
        assert len(refs) == 1
        assert refs[0] == ("node", "output")

    def test_extract_handles_primitives(self) -> None:
        """Test that primitives don't crash extraction."""
        from dag_executor.variables import extract_variable_references

        assert extract_variable_references(123) == []
        assert extract_variable_references(True) == []
        assert extract_variable_references(None) == []
