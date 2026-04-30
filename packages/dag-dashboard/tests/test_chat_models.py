"""Tests for chat message models and validation."""
import pytest
from pydantic import ValidationError

from dag_dashboard.models import ChatRole, ChatMessageRequest


def test_chat_role_enum_values():
    """ChatRole should have operator, agent, system values."""
    assert ChatRole.OPERATOR == "operator"
    assert ChatRole.AGENT == "agent"
    assert ChatRole.SYSTEM == "system"


def test_chat_message_request_valid():
    """Valid chat message request should pass validation."""
    msg = ChatMessageRequest(
        content="Hello, agent!",
        operator_username="alice"
    )
    assert msg.content == "Hello, agent!"
    assert msg.operator_username == "alice"


def test_chat_message_request_max_length():
    """Messages over 10000 chars should be rejected."""
    with pytest.raises(ValidationError) as exc_info:
        ChatMessageRequest(
            content="x" * 10001,
            operator_username="alice"
        )
    assert "10000" in str(exc_info.value)


def test_chat_message_request_allows_natural_punctuation():
    """Chat content is never shell-executed — natural punctuation including
    ``$``, ``:``, ``()``, ``<>``, ``\\n``, ``&`` must round-trip so users
    can paste error messages / code snippets when asking for help.
    Historical restriction (shell-metacharacter blacklist) is removed.
    """
    samples = [
        "What does ${creation_result_bug_key} mean?",
        "pipe: a | b",
        "backticks: `foo`",
        "parens (like this) and semi; colons",
        "multi\nline okay",
        "angle <brackets>",
        "ampersand & co",
    ]
    for s in samples:
        msg = ChatMessageRequest(content=s, operator_username="alice")
        assert msg.content == s


def test_chat_message_request_rejects_nul():
    """NUL bytes are rejected because SQLite silently truncates them."""
    with pytest.raises(ValidationError) as exc_info:
        ChatMessageRequest(
            content="has\x00nul",
            operator_username="alice",
        )
    assert "nul" in str(exc_info.value).lower()


def test_chat_message_request_empty_content():
    """Empty content should be rejected."""
    with pytest.raises(ValidationError) as exc_info:
        ChatMessageRequest(
            content="",
            operator_username="alice"
        )
    assert "at least 1 character" in str(exc_info.value).lower() or "min_length" in str(exc_info.value).lower()


def test_chat_message_request_whitespace_only():
    """Whitespace-only content should be rejected."""
    with pytest.raises(ValidationError) as exc_info:
        ChatMessageRequest(
            content="   \n\t  ",
            operator_username="alice"
        )
    # After stripping, it's empty
    assert "at least 1 character" in str(exc_info.value).lower() or "min_length" in str(exc_info.value).lower()
