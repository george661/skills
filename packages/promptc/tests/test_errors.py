"""Tests for error handling."""
import pytest

from promptc import Parser, ParseError


class TestParseErrors:
    """Test structured ParseError with line and column."""
    
    def test_unclosed_tag_error(self) -> None:
        parser = Parser()
        
        with pytest.raises(ParseError) as exc_info:
            parser.parse("{% tag %}")
        
        assert exc_info.value.line == 1
        assert exc_info.value.column > 0
        assert "Unclosed tag" in exc_info.value.message
    
    def test_unclosed_raw_block_error(self) -> None:
        parser = Parser()
        
        with pytest.raises(ParseError) as exc_info:
            parser.parse("{% raw %}no closing tag")
        
        assert "Unclosed {% raw %}" in exc_info.value.message
    
    def test_invalid_attribute_value(self) -> None:
        parser = Parser()
        
        with pytest.raises(ParseError) as exc_info:
            parser.parse("{% tag attr=@invalid /%}")
        
        assert "Invalid attribute value" in exc_info.value.message
    
    def test_error_line_number_multiline(self) -> None:
        parser = Parser()
        source = "line1\nline2\n{% tag %}"
        
        with pytest.raises(ParseError) as exc_info:
            parser.parse(source)
        
        assert exc_info.value.line == 3
    
    def test_mismatched_closing_tag(self) -> None:
        parser = Parser()
        
        with pytest.raises(ParseError) as exc_info:
            parser.parse("{% tag1 %}{% /tag2 %}")
        
        # Should report unclosed tag1
        assert "Unclosed tag" in exc_info.value.message
