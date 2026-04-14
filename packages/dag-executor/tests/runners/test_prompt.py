"""Tests for prompt runner."""
from unittest.mock import Mock, patch
import pytest

from dag_executor.schema import NodeDef, NodeStatus, ModelTier
from dag_executor.runners.base import RunnerContext
from dag_executor.runners.prompt import PromptRunner


@pytest.fixture
def inline_prompt_node():
    """Create a prompt node with inline prompt."""
    return NodeDef(
        id="prompt1",
        name="Test Prompt",
        type="prompt",
        prompt="What is 2+2?",
        model=ModelTier.SONNET
    )


@pytest.fixture
def file_prompt_node():
    """Create a prompt node with prompt_file."""
    return NodeDef(
        id="prompt2",
        name="File Prompt",
        type="prompt",
        prompt_file="prompts/analyze.md",
        model=ModelTier.OPUS
    )


def test_prompt_inline_mode(inline_prompt_node):
    """Test inline prompt mode constructs correct CLI args."""
    ctx = RunnerContext(node_def=inline_prompt_node)
    
    mock_result = Mock()
    mock_result.returncode = 0
    mock_result.stdout = "The answer is 4"
    mock_result.stderr = ""
    
    with patch("subprocess.run", return_value=mock_result) as mock_run:
        runner = PromptRunner()
        result = runner.run(ctx)
        
        assert result.status == NodeStatus.COMPLETED
        assert "answer" in result.output["response"].lower()
        
        # Verify dispatch-local.sh was called
        call_args = mock_run.call_args[0][0]
        assert any("dispatch-local.sh" in str(arg) for arg in call_args)


def test_prompt_file_mode(file_prompt_node):
    """Test prompt_file mode constructs correct CLI args."""
    ctx = RunnerContext(node_def=file_prompt_node)
    
    mock_result = Mock()
    mock_result.returncode = 0
    mock_result.stdout = "Analysis complete"
    mock_result.stderr = ""
    
    with patch("subprocess.run", return_value=mock_result) as mock_run:
        runner = PromptRunner()
        result = runner.run(ctx)
        
        assert result.status == NodeStatus.COMPLETED


def test_prompt_model_tier_mapping():
    """Test model tier maps to correct --model flag."""
    # Test different model tiers
    for tier in [ModelTier.OPUS, ModelTier.SONNET, ModelTier.LOCAL]:
        node = NodeDef(
            id="p1",
            name="Prompt",
            type="prompt",
            prompt="test",
            model=tier
        )
        ctx = RunnerContext(node_def=node)
        
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = "response"
        mock_result.stderr = ""
        
        with patch("subprocess.run", return_value=mock_result) as mock_run:
            runner = PromptRunner()
            runner.run(ctx)
            
            # Verify model flag was passed
            call_args = str(mock_run.call_args[0][0])
            assert "--model" in call_args or tier.value in call_args


def test_prompt_dispatch_local_only(inline_prompt_node):
    """Test MVP dispatch is local only."""
    ctx = RunnerContext(node_def=inline_prompt_node)
    
    mock_result = Mock()
    mock_result.returncode = 0
    mock_result.stdout = "response"
    mock_result.stderr = ""
    
    with patch("subprocess.run", return_value=mock_result) as mock_run:
        runner = PromptRunner()
        runner.run(ctx)
        
        # Verify dispatch-local.sh was used
        call_args = mock_run.call_args[0][0]
        assert any("dispatch-local.sh" in str(arg) for arg in call_args)


def test_prompt_subprocess_error(inline_prompt_node):
    """Test subprocess error handling."""
    ctx = RunnerContext(node_def=inline_prompt_node)
    
    mock_result = Mock()
    mock_result.returncode = 1
    mock_result.stdout = ""
    mock_result.stderr = "CLI error"
    
    with patch("subprocess.run", return_value=mock_result):
        runner = PromptRunner()
        result = runner.run(ctx)
        
        assert result.status == NodeStatus.FAILED
        assert "CLI error" in result.error


def test_prompt_captures_output(inline_prompt_node):
    """Test subprocess output is captured."""
    ctx = RunnerContext(node_def=inline_prompt_node)
    
    mock_result = Mock()
    mock_result.returncode = 0
    mock_result.stdout = "Detailed response text"
    mock_result.stderr = ""
    
    with patch("subprocess.run", return_value=mock_result):
        runner = PromptRunner()
        result = runner.run(ctx)
        
        assert result.status == NodeStatus.COMPLETED
        assert result.output["response"] == "Detailed response text"
