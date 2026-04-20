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


def test_chat_message_request_shell_metacharacters():
    """Messages with shell metacharacters should be rejected."""
    dangerous_chars = [";", "&", "|", "`", "$", "(", ")", "<", ">", "\n", "\\"]
    
    for char in dangerous_chars:
        with pytest.raises(ValidationError) as exc_info:
            ChatMessageRequest(
                content=f"test {char} command",
                operator_username="alice"
            )
        assert "shell metacharacters" in str(exc_info.value).lower()


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
