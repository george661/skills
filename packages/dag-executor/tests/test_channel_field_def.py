"""Tests for ChannelFieldDef model and state field union type."""
import pytest
from dag_executor.schema import ChannelFieldDef, ReducerDef, ReducerStrategy


class TestChannelFieldDefModel:
    """Test ChannelFieldDef model creation and validation."""
    
    def test_basic_channel_field_def(self):
        """Test basic ChannelFieldDef with type only."""
        field_def = ChannelFieldDef(type="string")
        assert field_def.type == "string"
        assert field_def.reducer is None
        assert field_def.default is None
    
    def test_channel_field_def_with_reducer_dict(self):
        """Test ChannelFieldDef with nested ReducerDef."""
        field_def = ChannelFieldDef(
            type="list",
            reducer=ReducerDef(strategy=ReducerStrategy.APPEND),
            default=[]
        )
        assert field_def.type == "list"
        assert isinstance(field_def.reducer, ReducerDef)
        assert field_def.reducer.strategy == ReducerStrategy.APPEND
        assert field_def.default == []
    
    def test_channel_field_def_bare_string_reducer(self):
        """Test ChannelFieldDef with bare string reducer shorthand."""
        field_def = ChannelFieldDef(type="list", reducer="append", default=[])
        assert field_def.type == "list"
        assert isinstance(field_def.reducer, ReducerDef)
        assert field_def.reducer.strategy == ReducerStrategy.APPEND
        assert field_def.default == []
    
    def test_channel_field_def_invalid_extra_field(self):
        """Test ChannelFieldDef rejects extra fields."""
        with pytest.raises(Exception):  # Pydantic ValidationError
            ChannelFieldDef(type="string", invalid_field="value")


class TestStateFieldUnion:
    """Test state field union type handling in WorkflowDef."""

    def test_mixed_state_syntax(self):
        """Test WorkflowDef accepts both ReducerDef and ChannelFieldDef in state."""
        from dag_executor.schema import WorkflowDef, WorkflowConfig, NodeDef, ModelTier

        workflow_def = WorkflowDef(
            name="test_workflow",
            config=WorkflowConfig(checkpoint_prefix="test"),
            nodes=[
                NodeDef(
                    id="node1",
                    name="Test Node",
                    type="prompt",
                    prompt="test",
                    model=ModelTier.SONNET
                )
            ],
            state={
                # Old syntax (ReducerDef)
                "severity": ReducerDef(strategy=ReducerStrategy.OVERWRITE),
                # New syntax (ChannelFieldDef)
                "messages": ChannelFieldDef(type="list", reducer="append"),
                "best_score": ChannelFieldDef(type="float", reducer=ReducerDef(strategy=ReducerStrategy.MAX)),
                "config": ChannelFieldDef(type="dict")  # No reducer = LastValueChannel
            }
        )

        assert "severity" in workflow_def.state
        assert "messages" in workflow_def.state
        assert "best_score" in workflow_def.state
        assert "config" in workflow_def.state


class TestBackwardsCompatibility:
    """Test that existing ReducerDef YAML continues to work."""

    def test_legacy_reducer_def_still_parses(self):
        """Test existing workflow YAML with only ReducerDef entries."""
        from dag_executor.schema import WorkflowDef, WorkflowConfig, NodeDef, ModelTier

        workflow_def = WorkflowDef(
            name="legacy_workflow",
            config=WorkflowConfig(checkpoint_prefix="test"),
            nodes=[
                NodeDef(
                    id="node1",
                    name="Test Node",
                    type="prompt",
                    prompt="test",
                    model=ModelTier.SONNET
                )
            ],
            state={
                "severity": ReducerDef(strategy=ReducerStrategy.OVERWRITE),
                "count": ReducerDef(strategy=ReducerStrategy.APPEND)
            }
        )

        assert len(workflow_def.state) == 2
        assert "severity" in workflow_def.state
        assert "count" in workflow_def.state


class TestChannelStoreWithChannelFieldDef:
    """Test ChannelStore.from_workflow_def() handles ChannelFieldDef."""
    
    def test_channel_store_with_channel_field_def_reducer(self):
        """Test ChannelStore creates ReducerChannel for ChannelFieldDef with reducer."""
        from dag_executor.schema import WorkflowDef, WorkflowConfig, NodeDef, ModelTier
        from dag_executor.channels import ChannelStore
        
        workflow_def = WorkflowDef(
            name="test_workflow",
            config=WorkflowConfig(checkpoint_prefix="test"),
            nodes=[
                NodeDef(
                    id="node1",
                    name="Test Node",
                    type="prompt",
                    prompt="test",
                    model=ModelTier.SONNET
                )
            ],
            state={
                "messages": ChannelFieldDef(type="list", reducer="append", default=[])
            }
        )
        
        channel_store = ChannelStore.from_workflow_def(workflow_def)
        assert "messages" in channel_store.channels
        # Should have initial value from default (read returns tuple of (value, version))
        value, version = channel_store.read("messages")
        assert value == []
    
    def test_channel_store_with_channel_field_def_no_reducer(self):
        """Test ChannelStore creates LastValueChannel for ChannelFieldDef without reducer."""
        from dag_executor.schema import WorkflowDef, WorkflowConfig, NodeDef, ModelTier
        from dag_executor.channels import ChannelStore
        
        workflow_def = WorkflowDef(
            name="test_workflow",
            config=WorkflowConfig(checkpoint_prefix="test"),
            nodes=[
                NodeDef(
                    id="node1",
                    name="Test Node",
                    type="prompt",
                    prompt="test",
                    model=ModelTier.SONNET
                )
            ],
            state={
                "status": ChannelFieldDef(type="string")
            }
        )
        
        channel_store = ChannelStore.from_workflow_def(workflow_def)
        assert "status" in channel_store.channels


class TestValidatorWithChannelFieldDef:
    """Test validator handles ChannelFieldDef entries correctly."""

    def test_validator_accepts_input_keys_in_reads(self):
        """Test validator accepts workflow input keys in node reads."""
        from dag_executor.schema import WorkflowDef, WorkflowConfig, NodeDef, ModelTier, InputDef
        from dag_executor.validator import WorkflowValidator

        workflow_def = WorkflowDef(
            name="test_workflow",
            config=WorkflowConfig(checkpoint_prefix="test"),
            inputs={
                "config": InputDef(type="dict", required=True)
            },
            nodes=[
                NodeDef(
                    id="node1",
                    name="Test Node",
                    type="prompt",
                    prompt="test",
                    model=ModelTier.SONNET,
                    reads=["config"]  # Should accept input key
                )
            ]
        )

        # Should not raise validation error
        validator = WorkflowValidator()
        result = validator.validate(workflow_def)
        assert result.passed

    def test_validator_handles_channel_field_def_in_reducer_consistency(self):
        """Test _check_reducer_consistency handles ChannelFieldDef entries."""
        from dag_executor.schema import WorkflowDef, WorkflowConfig, NodeDef, ModelTier
        from dag_executor.validator import WorkflowValidator

        workflow_def = WorkflowDef(
            name="test_workflow",
            config=WorkflowConfig(checkpoint_prefix="test"),
            nodes=[
                NodeDef(
                    id="node1",
                    name="Test Node",
                    type="prompt",
                    prompt="test",
                    model=ModelTier.SONNET,
                    writes=["messages", "status"]
                )
            ],
            state={
                "messages": ChannelFieldDef(type="list", reducer="append"),
                "status": ChannelFieldDef(type="string")  # No reducer
            }
        )

        # Should not raise validation error
        validator = WorkflowValidator()
        result = validator.validate(workflow_def)
        assert result.passed
