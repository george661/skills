"""Tests for AST serialization."""
from promptc import Parser


class TestSerialization:
    """Test AST node serialization to dict."""
    
    def test_node_to_dict_basic(self) -> None:
        parser = Parser()
        nodes = parser.parse("{% tag /%}")
        
        result = nodes[0].to_dict()
        
        assert result["kind"] == "tag"
        assert result["attrs"] == {}
        assert result["children"] == []
        assert result["body"] is None
        assert "source_span" in result
    
    def test_node_to_dict_with_attributes(self) -> None:
        parser = Parser()
        nodes = parser.parse('{% tag name="value" count=42 /%}')
        
        result = nodes[0].to_dict()
        
        assert result["attrs"] == {"name": "value", "count": 42}
    
    def test_node_to_dict_with_children(self) -> None:
        parser = Parser()
        nodes = parser.parse("{% outer %}{% inner /%}{% /outer %}")
        
        result = nodes[0].to_dict()
        
        assert len(result["children"]) == 1
        assert result["children"][0]["kind"] == "inner"
    
    def test_node_to_dict_with_body(self) -> None:
        parser = Parser()
        nodes = parser.parse("{% raw %}content{% /raw %}")
        
        result = nodes[0].to_dict()
        
        assert result["body"] == "content"
    
    def test_source_span_includes_columns(self) -> None:
        parser = Parser()
        nodes = parser.parse("{% tag /%}")
        
        result = nodes[0].to_dict()
        span = result["source_span"]
        
        assert "start_line" in span
        assert "start_col" in span
        assert "end_line" in span
        assert "end_col" in span
        assert span["start_line"] == 1
        assert span["start_col"] == 1
    
    def test_full_ast_serialization(self) -> None:
        """Test that entire AST can be serialized."""
        parser = Parser()
        source = """
{% prompt name="test" %}
  Text content
  {% if enabled=true %}
    {% nested /%}
  {% /if %}
{% /prompt %}
""".strip()
        
        nodes = parser.parse(source)
        result = [node.to_dict() for node in nodes]
        
        # Should be JSON-serializable
        import json
        json_str = json.dumps(result)
        assert len(json_str) > 0
        
        # Verify structure is preserved
        parsed = json.loads(json_str)
        assert parsed[0]["kind"] == "prompt"
