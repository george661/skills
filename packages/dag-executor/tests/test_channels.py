"""Tests for channel abstraction layer."""
import pytest
import threading
from typing import Any

from dag_executor.channels import (
    Channel,
    LastValueChannel,
    ReducerChannel,
    BarrierChannel,
    ChannelStore,
    ConflictError,
)
from dag_executor.schema import ReducerStrategy, ReducerDef, WorkflowDef, WorkflowConfig


class TestLastValueChannel:
    """Tests for LastValueChannel."""

    def test_read_initial_state(self) -> None:
        """Initial read returns None with version 0."""
        channel = LastValueChannel()
        value, version = channel.read()
        assert value is None
        assert version == 0

    def test_single_write_increments_version(self) -> None:
        """Single write increments version to 1."""
        channel = LastValueChannel()
        new_version = channel.write("value1", "node_a")
        assert new_version == 1
        value, version = channel.read()
        assert value == "value1"
        assert version == 1

    def test_same_writer_multiple_times(self) -> None:
        """Same writer can write multiple times without conflict."""
        channel = LastValueChannel()
        channel.write("value1", "node_a")
        new_version = channel.write("value2", "node_a")
        assert new_version == 2
        value, version = channel.read()
        assert value == "value2"
        assert version == 2

    def test_different_writers_raises_conflict(self) -> None:
        """Two different writers raise ConflictError."""
        channel = LastValueChannel()
        channel.write("value1", "node_a")
        with pytest.raises(ConflictError) as exc_info:
            channel.write("value2", "node_b")
        assert "node_a" in str(exc_info.value)
        assert "node_b" in str(exc_info.value)

    def test_reset_clears_writers(self) -> None:
        """reset() clears writers set, allowing new writes."""
        channel = LastValueChannel()
        channel.write("value1", "node_a")
        channel.reset()
        # Now node_b can write
        new_version = channel.write("value2", "node_b")
        assert new_version == 2
        value, version = channel.read()
        assert value == "value2"

    def test_thread_safety_concurrent_writes(self) -> None:
        """Concurrent writes from same writer are thread-safe."""
        channel = LastValueChannel()
        results = []

        def write_values() -> None:
            for i in range(100):
                version = channel.write(f"value_{i}", "node_a")
                results.append(version)

        threads = [threading.Thread(target=write_values) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All 300 writes should complete
        assert len(results) == 300
        # Version should be 300
        _, version = channel.read()
        assert version == 300


class TestReducerChannel:
    """Tests for ReducerChannel."""

    def test_delegates_to_reducer_registry(self) -> None:
        """ReducerChannel delegates to ReducerRegistry."""
        reducer_def = ReducerDef(strategy=ReducerStrategy.APPEND)
        channel = ReducerChannel(reducer_def)
        
        channel.write("item1", "node_a")
        value, version = channel.read()
        assert value == ["item1"]
        assert version == 1

    def test_append_strategy_folds_correctly(self) -> None:
        """APPEND strategy folds multiple writes."""
        reducer_def = ReducerDef(strategy=ReducerStrategy.APPEND)
        channel = ReducerChannel(reducer_def)
        
        channel.write("item1", "node_a")
        channel.write("item2", "node_b")
        channel.write("item3", "node_c")
        
        value, version = channel.read()
        assert value == ["item1", "item2", "item3"]
        assert version == 3

    def test_version_increments_per_write(self) -> None:
        """Version increments for each write."""
        reducer_def = ReducerDef(strategy=ReducerStrategy.OVERWRITE)
        channel = ReducerChannel(reducer_def)
        
        v1 = channel.write("a", "node_a")
        v2 = channel.write("b", "node_b")
        v3 = channel.write("c", "node_c")
        
        assert v1 == 1
        assert v2 == 2
        assert v3 == 3

    def test_no_conflict_on_multi_writer(self) -> None:
        """Multiple writers don't raise ConflictError with reducer."""
        reducer_def = ReducerDef(strategy=ReducerStrategy.APPEND)
        channel = ReducerChannel(reducer_def)
        
        # Should not raise
        channel.write("a", "node_a")
        channel.write("b", "node_b")
        channel.write("c", "node_c")
        
        value, _ = channel.read()
        assert value == ["a", "b", "c"]

    def test_thread_safety_concurrent_appends(self) -> None:
        """10 concurrent writers with APPEND - all values present."""
        reducer_def = ReducerDef(strategy=ReducerStrategy.APPEND)
        channel = ReducerChannel(reducer_def)

        def write_items(node_id: str, count: int) -> None:
            for i in range(count):
                channel.write(f"{node_id}_{i}", node_id)

        threads = [
            threading.Thread(target=write_items, args=(f"node_{i}", 10))
            for i in range(10)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        value, version = channel.read()
        assert len(value) == 100
        assert version == 100


class TestBarrierChannel:
    """Tests for BarrierChannel."""

    def test_not_released_until_all_writers(self) -> None:
        """Barrier not released until all N writers have written."""
        channel = BarrierChannel(expected_writers=3)
        
        channel.write("a", "node_a")
        channel.write("b", "node_b")
        
        # Not yet released
        value, version = channel.read()
        assert value is None
        assert version == 0

    def test_released_when_all_write(self) -> None:
        """Barrier releases when all N writers write."""
        channel = BarrierChannel(expected_writers=3)
        
        channel.write("a", "node_a")
        channel.write("b", "node_b")
        channel.write("c", "node_c")
        
        # Now released
        value, version = channel.read()
        assert value == ["a", "b", "c"]
        assert version == 1

    def test_version_increments_on_release(self) -> None:
        """Version increments only when barrier releases."""
        channel = BarrierChannel(expected_writers=2)
        
        channel.write("a", "node_a")
        value, version = channel.read()
        assert version == 0  # Not released yet
        
        channel.write("b", "node_b")
        value, version = channel.read()
        assert version == 1  # Released

    def test_reset_clears_accumulated(self) -> None:
        """reset() clears accumulated values for next barrier cycle."""
        channel = BarrierChannel(expected_writers=2)
        
        channel.write("a", "node_a")
        channel.write("b", "node_b")
        
        # First cycle
        value, version = channel.read()
        assert value == ["a", "b"]
        assert version == 1
        
        # Reset
        channel.reset()
        value, version = channel.read()
        assert value is None
        assert version == 1  # Version doesn't decrease
        
        # Second cycle
        channel.write("c", "node_a")
        channel.write("d", "node_b")
        value, version = channel.read()
        assert value == ["c", "d"]
        assert version == 2

    def test_duplicate_writer_raises_error(self) -> None:
        """Same writer writing twice raises error."""
        channel = BarrierChannel(expected_writers=2)
        channel.write("a", "node_a")
        with pytest.raises(ValueError) as exc_info:
            channel.write("b", "node_a")
        assert "already written" in str(exc_info.value).lower()

    def test_thread_safety_concurrent_barrier(self) -> None:
        """Concurrent writes to barrier are thread-safe."""
        channel = BarrierChannel(expected_writers=10)

        def write_value(node_id: str) -> None:
            channel.write(f"value_{node_id}", node_id)

        threads = [
            threading.Thread(target=write_value, args=(f"node_{i}",))
            for i in range(10)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        value, version = channel.read()
        assert len(value) == 10
        assert version == 1


class TestChannelStore:
    """Tests for ChannelStore."""

    def test_read_write_delegation(self) -> None:
        """read() and write() delegate to channel."""
        store = ChannelStore()
        channel = LastValueChannel()
        store.channels["test_key"] = channel
        
        new_version = store.write("test_key", "value1", "node_a")
        assert new_version == 1
        
        value, version = store.read("test_key")
        assert value == "value1"
        assert version == 1

    def test_get_versions_snapshot_immutable(self) -> None:
        """get_versions() returns dict copy, not reference."""
        store = ChannelStore()
        store.channels["key1"] = LastValueChannel()
        store.channels["key2"] = LastValueChannel()
        
        store.write("key1", "a", "node_a")
        store.write("key2", "b", "node_b")
        
        versions1 = store.get_versions()
        assert versions1 == {"key1": 1, "key2": 1}
        
        # Modify original
        store.write("key1", "c", "node_a")
        
        # versions1 should be unchanged
        assert versions1 == {"key1": 1, "key2": 1}
        
        # New snapshot should reflect change
        versions2 = store.get_versions()
        assert versions2 == {"key1": 2, "key2": 1}

    def test_from_workflow_def_overwrite_strategy(self) -> None:
        """from_workflow_def builds LastValueChannel for OVERWRITE."""
        from dag_executor.schema import NodeDef
        workflow_def = WorkflowDef(
            name="test",
            config=WorkflowConfig(checkpoint_prefix="test"),
            nodes=[NodeDef(id="dummy", name="dummy", type="bash", script="echo test")],
            state={
                "field1": ReducerDef(strategy=ReducerStrategy.OVERWRITE),
            }
        )

        store = ChannelStore.from_workflow_def(workflow_def)

        assert "field1" in store.channels
        assert isinstance(store.channels["field1"], LastValueChannel)

    def test_from_workflow_def_reducer_strategies(self) -> None:
        """from_workflow_def builds ReducerChannel for non-OVERWRITE strategies."""
        from dag_executor.schema import NodeDef
        workflow_def = WorkflowDef(
            name="test",
            config=WorkflowConfig(checkpoint_prefix="test"),
            nodes=[NodeDef(id="dummy", name="dummy", type="bash", script="echo test")],
            state={
                "items": ReducerDef(strategy=ReducerStrategy.APPEND),
                "values": ReducerDef(strategy=ReducerStrategy.EXTEND),
                "score": ReducerDef(strategy=ReducerStrategy.MAX),
            }
        )

        store = ChannelStore.from_workflow_def(workflow_def)

        assert isinstance(store.channels["items"], ReducerChannel)
        assert isinstance(store.channels["values"], ReducerChannel)
        assert isinstance(store.channels["score"], ReducerChannel)

    def test_unknown_key_raises_key_error(self) -> None:
        """read() and write() raise KeyError for unknown key."""
        store = ChannelStore()
        
        with pytest.raises(KeyError):
            store.read("nonexistent")
        
        with pytest.raises(KeyError):
            store.write("nonexistent", "value", "node_a")


class TestVersionMonotonicity:
    """Tests for version monotonicity across all channel types."""

    def test_version_never_decreases_last_value(self) -> None:
        """LastValueChannel version never decreases."""
        channel = LastValueChannel()
        prev_version = 0
        
        for i in range(10):
            new_version = channel.write(f"value_{i}", "node_a")
            assert new_version > prev_version
            prev_version = new_version

    def test_version_never_decreases_reducer(self) -> None:
        """ReducerChannel version never decreases."""
        reducer_def = ReducerDef(strategy=ReducerStrategy.APPEND)
        channel = ReducerChannel(reducer_def)
        prev_version = 0
        
        for i in range(10):
            new_version = channel.write(f"item_{i}", f"node_{i}")
            assert new_version > prev_version
            prev_version = new_version

    def test_version_never_decreases_barrier(self) -> None:
        """BarrierChannel version never decreases across cycles."""
        channel = BarrierChannel(expected_writers=2)
        
        # Cycle 1
        channel.write("a", "node_a")
        channel.write("b", "node_b")
        _, v1 = channel.read()
        assert v1 == 1
        
        # Cycle 2
        channel.reset()
        channel.write("c", "node_a")
        channel.write("d", "node_b")
        _, v2 = channel.read()
        assert v2 == 2
        assert v2 > v1
