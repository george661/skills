"""Tests for limit enforcement."""
import pytest

from promptc import LimitExceededError, Parser, ParserConfig


class TestLimits:
    """Test tag and node count limits."""
    
    def test_tag_count_limit_enforced(self) -> None:
        config = ParserConfig(max_tags=5)
        parser = Parser(config)
        
        # 6 tags should exceed limit of 5
        source = " ".join(["{% tag /%}"] * 6)
        
        with pytest.raises(LimitExceededError) as exc_info:
            parser.parse(source)
        
        assert exc_info.value.limit == 5
        assert exc_info.value.actual > 5
    
    def test_node_count_limit_enforced(self) -> None:
        config = ParserConfig(max_nodes=5)
        parser = Parser(config)
        
        # Create 6 nodes (each tag is a node)
        source = "{% tag1 /%} {% tag2 /%} {% tag3 /%} {% tag4 /%} {% tag5 /%} {% tag6 /%}"
        
        with pytest.raises(LimitExceededError) as exc_info:
            parser.parse(source)
        
        assert exc_info.value.limit == 5
    
    def test_configurable_limits(self) -> None:
        config = ParserConfig(max_tags=100, max_nodes=200)
        parser = Parser(config)
        
        # Should not raise with increased limits
        source = " ".join(["{% tag /%}"] * 50)
        nodes = parser.parse(source)
        
        # Should have 50 tags + text nodes between them
        assert len([n for n in nodes if n.kind == "tag"]) == 50
    
    def test_no_stack_overflow_on_deep_nesting(self) -> None:
        """Test that deeply nested tags don't cause stack overflow."""
        parser = Parser(ParserConfig(max_tags=1000, max_nodes=2000))
        
        # Create 100 levels of nesting
        depth = 100
        source = ""
        for i in range(depth):
            source += f"{{% tag{i} %}}"
        source += "center"
        for i in range(depth - 1, -1, -1):
            source += f"{{% /tag{i} %}}"
        
        # Should parse without stack overflow
        nodes = parser.parse(source)
        assert len(nodes) == 1


class TestReDoSProtection:
    """Test parser safety against pathological inputs.
    
    Note: Our patterns are simple and not vulnerable to ReDoS.
    The config timeout parameter is reserved for future use with
    more complex patterns.
    """
    
    def test_timeout_config_parameter_exists(self) -> None:
        """Test that timeout configuration exists."""
        config = ParserConfig(regex_timeout_ms=50)
        assert config.regex_timeout_ms == 50
    
    def test_very_long_attribute_values_handled(self) -> None:
        """Test that very long inputs don't cause hangs."""
        parser = Parser()
        
        # Very long attribute value
        long_value = "a" * 10000
        source = f'{{% tag attr="{long_value}" /%}}'
        
        # Should complete quickly
        nodes = parser.parse(source)
        assert nodes[0].attrs["attr"] == long_value
