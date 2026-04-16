"""Channel abstraction layer for workflow state management.

Provides three channel types inspired by LangGraph:
- LastValueChannel: stores single value, raises ConflictError on parallel writes
- ReducerChannel: folds writes via ReducerStrategy
- BarrierChannel: accumulates writes from N sources, releases when all have written

Thread-safe: all writes acquire internal locks.
"""
import threading
from abc import ABC, abstractmethod
from typing import Any, Dict, Set, List, Tuple, Optional

from dag_executor.reducers import ReducerRegistry
from dag_executor.schema import ReducerDef, ReducerStrategy, WorkflowDef


class ChannelConflictError(Exception):
    """Raised when two parallel nodes write to the same LastValueChannel without a reducer."""

    def __init__(self, channel_key: str, writers: Set[str], message: str):
        """Initialize ChannelConflictError.

        Args:
            channel_key: Key of the channel where conflict occurred
            writers: Set of node IDs that caused the conflict
            message: Error message
        """
        super().__init__(message)
        self.channel_key = channel_key
        self.writers = writers


# Deprecated alias for backward compatibility
ConflictError = ChannelConflictError


class Channel(ABC):
    """Abstract base class for all channel types."""

    @abstractmethod
    def read(self) -> Tuple[Any, int]:
        """Read current value and version.
        
        Returns:
            Tuple of (value, version)
        """
        pass

    @abstractmethod
    def write(self, value: Any, writer_node_id: str) -> int:
        """Write a value to the channel.
        
        Args:
            value: Value to write
            writer_node_id: ID of the node writing the value
            
        Returns:
            New version number after write
        """
        pass

    @abstractmethod
    def reset(self) -> None:
        """Reset channel state for next execution tick."""
        pass

    @property
    @abstractmethod
    def value(self) -> Any:
        """Current value."""
        pass

    @property
    @abstractmethod
    def version(self) -> int:
        """Current version number."""
        pass

    @property
    @abstractmethod
    def writers(self) -> Set[str]:
        """Set of node IDs that have written to this channel."""
        pass


class LastValueChannel(Channel):
    """Channel that stores a single value.

    Raises ChannelConflictError if two different nodes write without a reducer.
    Thread-safe: all writes acquire internal lock.
    """

    def __init__(self, key: Optional[str] = None) -> None:
        """Initialize LastValueChannel.

        Args:
            key: Optional channel key (used in error messages)
        """
        self._key = key
        self._value: Any = None
        self._version: int = 0
        self._writers: Set[str] = set()
        self._lock = threading.Lock()

    def read(self) -> Tuple[Any, int]:
        """Read current value and version."""
        with self._lock:
            return (self._value, self._version)

    def write(self, value: Any, writer_node_id: str) -> int:
        """Write a value, raising ChannelConflictError if multiple writers.

        Args:
            value: Value to write
            writer_node_id: ID of the node writing

        Returns:
            New version number

        Raises:
            ChannelConflictError: If a different node has already written
        """
        with self._lock:
            # Check for conflict: if writers already contains a different node
            if self._writers and writer_node_id not in self._writers:
                # Add the new writer to the set for error reporting
                all_writers = self._writers | {writer_node_id}
                existing_writers = ", ".join(sorted(self._writers))
                channel_key = self._key or "unknown"
                message = (
                    f"Parallel write conflict on channel '{channel_key}': "
                    f"node '{writer_node_id}' attempted to write, "
                    f"but node(s) {existing_writers} already wrote. "
                    f"Use a reducer strategy to merge parallel writes."
                )
                raise ChannelConflictError(channel_key, all_writers, message)

            self._writers.add(writer_node_id)
            self._value = value
            self._version += 1
            return self._version

    def reset(self) -> None:
        """Reset writers set for next execution layer."""
        with self._lock:
            self._writers.clear()

    @property
    def value(self) -> Any:
        """Current value."""
        with self._lock:
            return self._value

    @property
    def version(self) -> int:
        """Current version."""
        with self._lock:
            return self._version

    @property
    def writers(self) -> Set[str]:
        """Set of writers (returns copy for thread safety)."""
        with self._lock:
            return self._writers.copy()


class ReducerChannel(Channel):
    """Channel that folds writes via a ReducerStrategy.
    
    Delegates to ReducerRegistry.apply() on each write.
    Thread-safe: all writes acquire internal lock.
    """

    def __init__(self, reducer_def: ReducerDef) -> None:
        """Initialize with a reducer definition.
        
        Args:
            reducer_def: Reducer definition (strategy + optional custom function)
        """
        self._reducer_def = reducer_def
        self._reducer_registry = ReducerRegistry()
        self._value: Any = None
        self._version: int = 0
        self._writers: Set[str] = set()
        self._lock = threading.Lock()

    def read(self) -> Tuple[Any, int]:
        """Read current value and version."""
        with self._lock:
            return (self._value, self._version)

    def write(self, value: Any, writer_node_id: str) -> int:
        """Write a value, applying reducer to merge with current value.
        
        Args:
            value: Value to write
            writer_node_id: ID of the node writing
            
        Returns:
            New version number
        """
        with self._lock:
            self._writers.add(writer_node_id)
            self._value = self._reducer_registry.apply(
                self._reducer_def.strategy,
                self._value,
                value,
                self._reducer_def.function
            )
            self._version += 1
            return self._version

    def reset(self) -> None:
        """Reset writers set for next execution layer."""
        with self._lock:
            self._writers.clear()

    @property
    def value(self) -> Any:
        """Current value."""
        with self._lock:
            return self._value

    @property
    def version(self) -> int:
        """Current version."""
        with self._lock:
            return self._version

    @property
    def writers(self) -> Set[str]:
        """Set of writers (returns copy for thread safety)."""
        with self._lock:
            return self._writers.copy()


class BarrierChannel(Channel):
    """Channel that accumulates writes from N sources, releasing when all have written.
    
    Used for fan-in synchronization patterns.
    Thread-safe: all writes acquire internal lock.
    """

    def __init__(self, expected_writers: int) -> None:
        """Initialize barrier with expected number of writers.
        
        Args:
            expected_writers: Number of nodes that must write before barrier releases
        """
        if expected_writers < 1:
            raise ValueError(f"expected_writers must be >= 1, got {expected_writers}")
        
        self._expected_writers = expected_writers
        self._accumulated: List[Any] = []
        self._writers: Set[str] = set()
        self._version: int = 0
        self._released: bool = False
        self._lock = threading.Lock()

    def read(self) -> Tuple[Optional[List[Any]], int]:
        """Read accumulated values if barrier has released.
        
        Returns:
            Tuple of (accumulated values list or None, version)
            Returns None if barrier hasn't released yet.
        """
        with self._lock:
            if self._released:
                return (self._accumulated.copy(), self._version)
            else:
                return (None, self._version)

    def write(self, value: Any, writer_node_id: str) -> int:
        """Write a value, accumulating until all expected writers have written.
        
        Args:
            value: Value to write
            writer_node_id: ID of the node writing
            
        Returns:
            New version number (increments only when barrier releases)
            
        Raises:
            ValueError: If the same writer tries to write twice
        """
        with self._lock:
            # Check for duplicate writer
            if writer_node_id in self._writers:
                raise ValueError(
                    f"Writer '{writer_node_id}' has already written to this barrier"
                )
            
            self._writers.add(writer_node_id)
            self._accumulated.append(value)
            
            # Check if barrier should release
            if len(self._writers) == self._expected_writers:
                self._released = True
                self._version += 1
            
            return self._version

    def reset(self) -> None:
        """Reset barrier for next cycle."""
        with self._lock:
            self._accumulated.clear()
            self._writers.clear()
            self._released = False

    @property
    def value(self) -> Optional[List[Any]]:
        """Current accumulated values (None if not released)."""
        with self._lock:
            if self._released:
                return self._accumulated.copy()
            return None

    @property
    def version(self) -> int:
        """Current version."""
        with self._lock:
            return self._version

    @property
    def writers(self) -> Set[str]:
        """Set of writers (returns copy for thread safety)."""
        with self._lock:
            return self._writers.copy()


class ChannelStore:
    """Container managing all channels for a workflow execution.
    
    Provides read/write/versioning API and factory method for building
    channels from WorkflowDef.state.
    """

    def __init__(self) -> None:
        self.channels: Dict[str, Channel] = {}

    def read(self, key: str) -> Tuple[Any, int]:
        """Read value and version from a channel.
        
        Args:
            key: Channel key (state field name)
            
        Returns:
            Tuple of (value, version)
            
        Raises:
            KeyError: If key doesn't exist
        """
        if key not in self.channels:
            raise KeyError(f"Channel '{key}' not found")
        return self.channels[key].read()

    def write(self, key: str, value: Any, writer_node_id: str) -> int:
        """Write a value to a channel.
        
        Args:
            key: Channel key (state field name)
            value: Value to write
            writer_node_id: ID of the node writing
            
        Returns:
            New version number
            
        Raises:
            KeyError: If key doesn't exist
        """
        if key not in self.channels:
            raise KeyError(f"Channel '{key}' not found")
        return self.channels[key].write(value, writer_node_id)

    def get_versions(self) -> Dict[str, int]:
        """Get immutable snapshot of all channel versions.

        Returns:
            Dict mapping channel keys to current version numbers
        """
        return {key: channel.version for key, channel in self.channels.items()}

    def to_dict(self) -> Dict[str, Any]:
        """Extract current state as a plain dictionary.

        Provides backwards-compatible view of workflow state for checkpoint
        serialization and output extraction.

        Returns:
            Dict mapping channel keys to their current values
        """
        return {key: channel.value for key, channel in self.channels.items()}

    @classmethod
    def from_workflow_def(cls, workflow_def: WorkflowDef) -> "ChannelStore":
        """Factory method to build ChannelStore from WorkflowDef.

        Creates channels based on reducer strategies:
        - OVERWRITE strategy -> LastValueChannel
        - All other strategies -> ReducerChannel

        Args:
            workflow_def: Workflow definition with state field declarations

        Returns:
            ChannelStore with channels for each state field
        """
        store = cls()

        for key, reducer_def in workflow_def.state.items():
            if reducer_def.strategy == ReducerStrategy.OVERWRITE:
                store.channels[key] = LastValueChannel(key=key)
            else:
                store.channels[key] = ReducerChannel(reducer_def)

        return store
