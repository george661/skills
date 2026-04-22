"""Tests for model_resolver module."""
import pytest
from dag_executor.model_resolver import resolve_model
from dag_executor.schema import NodeDef, WorkflowDef, WorkflowConfig, ModelTier


def test_resolve_override_when_set_and_not_strict():
    """Tier 1: override takes precedence when strict_model=False."""
    node = NodeDef(id="test", name="test", type="prompt", prompt="test", model=ModelTier.LOCAL, strict_model=False)
    config = WorkflowConfig(checkpoint_prefix="test")
    workflow = WorkflowDef(name="test", config=config, nodes=[node])
    inputs = {"__model_override__": "sonnet"}
    
    result = resolve_model(node, workflow, inputs)
    assert result == ModelTier.SONNET


def test_resolve_node_model_when_no_override():
    """Tier 2: node-level model when override is None."""
    node = NodeDef(id="test", name="test", type="prompt", prompt="test", model=ModelTier.OPUS)
    config = WorkflowConfig(checkpoint_prefix="test")
    workflow = WorkflowDef(name="test", config=config, nodes=[node])
    inputs = {}
    
    result = resolve_model(node, workflow, inputs)
    assert result == ModelTier.OPUS


def test_resolve_workflow_default_when_node_has_none():
    """Tier 3: workflow default_model when node has no model."""
    node = NodeDef(id="test", name="test", type="prompt", prompt="test", model=None)
    config = WorkflowConfig(checkpoint_prefix="test")
    workflow = WorkflowDef(name="test", config=config, nodes=[node], default_model=ModelTier.SONNET)
    inputs = {}
    
    result = resolve_model(node, workflow, inputs)
    assert result == ModelTier.SONNET


def test_resolve_fallback_local_when_nothing_set():
    """Tier 4: ModelTier.LOCAL as global fallback."""
    node = NodeDef(id="test", name="test", type="prompt", prompt="test", model=None)
    config = WorkflowConfig(checkpoint_prefix="test")
    workflow = WorkflowDef(name="test", config=config, nodes=[node], default_model=None)
    inputs = {}
    
    result = resolve_model(node, workflow, inputs)
    assert result == ModelTier.LOCAL


def test_strict_model_blocks_override():
    """strict_model=True: override is ignored, node model wins."""
    node = NodeDef(id="test", name="test", type="prompt", prompt="test", model=ModelTier.LOCAL, strict_model=True)
    config = WorkflowConfig(checkpoint_prefix="test")
    workflow = WorkflowDef(name="test", config=config, nodes=[node])
    inputs = {"__model_override__": "sonnet"}
    
    result = resolve_model(node, workflow, inputs)
    assert result == ModelTier.LOCAL  # node model, not override


def test_strict_model_with_workflow_default():
    """strict_model=True with no node model but workflow default should use workflow default."""
    node = NodeDef(id="test", name="test", type="prompt", prompt="test", model=None, strict_model=True)
    config = WorkflowConfig(checkpoint_prefix="test")
    workflow = WorkflowDef(name="test", config=config, nodes=[node], default_model=ModelTier.OPUS)
    inputs = {"__model_override__": "sonnet"}
    
    # When strict_model=True and node has no model, fallback to workflow default (override ignored)
    result = resolve_model(node, workflow, inputs)
    assert result == ModelTier.OPUS
