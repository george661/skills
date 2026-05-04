"""Tests for basic parser functionality."""

from promptc.parser import Parser


class TestBasicTags:
    """Test parsing of basic tag forms."""

    def test_self_closing_tag(self) -> None:
        parser = Parser()
        nodes = parser.parse("{% tag /%}")

        assert len(nodes) == 1
        assert nodes[0].kind == "tag"
        assert nodes[0].attrs == {}
        assert nodes[0].children == []
        assert nodes[0].body is None

    def test_paired_tag_empty(self) -> None:
        parser = Parser()
        nodes = parser.parse("{% tag %}{% /tag %}")

        assert len(nodes) == 1
        assert nodes[0].kind == "tag"
        assert nodes[0].children == []

    def test_paired_tag_with_text(self) -> None:
        parser = Parser()
        nodes = parser.parse("{% tag %}Hello world{% /tag %}")

        assert len(nodes) == 1
        assert nodes[0].kind == "tag"
        assert len(nodes[0].children) == 1
        assert nodes[0].children[0].kind == "text"
        assert nodes[0].children[0].body == "Hello world"

    def test_nested_tags(self) -> None:
        parser = Parser()
        nodes = parser.parse("{% outer %}{% inner /%}{% /outer %}")

        assert len(nodes) == 1
        assert nodes[0].kind == "outer"
        assert len(nodes[0].children) == 1
        assert nodes[0].children[0].kind == "inner"

    def test_multiple_top_level_tags(self) -> None:
        parser = Parser()
        nodes = parser.parse("{% tag1 /%}{% tag2 /%}")

        assert len(nodes) == 2
        assert nodes[0].kind == "tag1"
        assert nodes[1].kind == "tag2"


class TestAttributes:
    """Test attribute parsing."""

    def test_string_attribute(self) -> None:
        parser = Parser()
        nodes = parser.parse('{% tag name="value" /%}')

        assert nodes[0].attrs == {"name": "value"}

    def test_boolean_attributes(self) -> None:
        parser = Parser()
        nodes = parser.parse('{% tag enabled=true disabled=false /%}')

        assert nodes[0].attrs == {"enabled": True, "disabled": False}

    def test_number_attributes(self) -> None:
        parser = Parser()
        nodes = parser.parse('{% tag count=42 ratio=3.14 negative=-5 /%}')

        assert nodes[0].attrs == {"count": 42, "ratio": 3.14, "negative": -5}

    def test_array_attribute(self) -> None:
        parser = Parser()
        nodes = parser.parse('{% tag items=["a", "b", "c"] /%}')

        assert nodes[0].attrs == {"items": ["a", "b", "c"]}

    def test_empty_array(self) -> None:
        parser = Parser()
        nodes = parser.parse('{% tag items=[] /%}')

        assert nodes[0].attrs == {"items": []}

    def test_mixed_attributes(self) -> None:
        parser = Parser()
        nodes = parser.parse('{% tag name="test" count=5 enabled=true tags=["a","b"] /%}')

        assert nodes[0].attrs["name"] == "test"
        assert nodes[0].attrs["count"] == 5
        assert nodes[0].attrs["enabled"] is True
        assert nodes[0].attrs["tags"] == ["a", "b"]


class TestRawBlocks:
    """Test {% raw %} blocks."""

    def test_raw_block_simple(self) -> None:
        parser = Parser()
        nodes = parser.parse("{% raw %}plain text{% endraw %}")

        assert len(nodes) == 1
        assert nodes[0].kind == "raw"
        assert nodes[0].body == "plain text"

    def test_raw_block_with_tag_like_syntax(self) -> None:
        parser = Parser()
        nodes = parser.parse("{% raw %}This {% looks %} like {% a tag %}{% endraw %}")

        assert nodes[0].body == "This {% looks %} like {% a tag %}"

    def test_raw_block_preserves_newlines(self) -> None:
        parser = Parser()
        nodes = parser.parse("{% raw %}line1\nline2\nline3{% endraw %}")

        assert nodes[0].body == "line1\nline2\nline3"


class TestMarkdownTolerance:
    """Test parser tolerance for markdown prose."""

    def test_text_before_tag(self) -> None:
        parser = Parser()
        nodes = parser.parse("Some text before {% tag /%}")

        assert len(nodes) == 2
        assert nodes[0].kind == "text"
        assert nodes[0].body == "Some text before "
        assert nodes[1].kind == "tag"

    def test_text_between_tags(self) -> None:
        parser = Parser()
        nodes = parser.parse("{% tag1 /%} middle text {% tag2 /%}")

        assert len(nodes) == 3
        assert nodes[0].kind == "tag1"
        assert nodes[1].kind == "text"
        assert nodes[1].body == " middle text "
        assert nodes[2].kind == "tag2"

    def test_text_after_tag(self) -> None:
        parser = Parser()
        nodes = parser.parse("{% tag /%} text after")

        assert len(nodes) == 2
        assert nodes[0].kind == "tag"
        assert nodes[1].kind == "text"
        assert nodes[1].body == " text after"


class TestUnknownTags:
    """Test that unknown tag names become structural nodes."""

    def test_unknown_tag_self_closing(self) -> None:
        parser = Parser()
        nodes = parser.parse("{% unknown_tag /%}")

        assert len(nodes) == 1
        assert nodes[0].kind == "unknown_tag"

    def test_unknown_tag_paired(self) -> None:
        parser = Parser()
        nodes = parser.parse("{% custom_tag %}content{% /custom_tag %}")

        assert len(nodes) == 1
        assert nodes[0].kind == "custom_tag"
        assert len(nodes[0].children) == 1


class TestStandardTags:
    """Test all 7 standard tags in both forms."""

    def test_prompt_tag(self) -> None:
        parser = Parser()
        nodes = parser.parse('{% prompt name="test" /%}')
        assert nodes[0].kind == "prompt"

        nodes = parser.parse('{% prompt name="test" %}body{% /prompt %}')
        assert nodes[0].kind == "prompt"

    def test_import_tag(self) -> None:
        parser = Parser()
        nodes = parser.parse('{% import src="path" /%}')
        assert nodes[0].kind == "import"

    def test_define_tag(self) -> None:
        parser = Parser()
        nodes = parser.parse('{% define var="x" %}value{% /define %}')
        assert nodes[0].kind == "define"

    def test_if_tag(self) -> None:
        parser = Parser()
        nodes = parser.parse('{% if cond=true %}text{% /if %}')
        assert nodes[0].kind == "if"

    def test_for_tag(self) -> None:
        parser = Parser()
        nodes = parser.parse('{% for items=["a"] %}{% /for %}')
        assert nodes[0].kind == "for"

    def test_include_tag(self) -> None:
        parser = Parser()
        nodes = parser.parse('{% include path="file" /%}')
        assert nodes[0].kind == "include"

    def test_raw_tag(self) -> None:
        parser = Parser()
        nodes = parser.parse('{% raw %}text{% endraw %}')
        assert nodes[0].kind == "raw"
