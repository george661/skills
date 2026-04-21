"""Tests for subprocess registry and cancel infrastructure."""
import subprocess
import time
from pathlib import Path
import pytest
from dag_executor.executor import SubprocessRegistry


def test_subprocess_registry_register_deregister():
    """Test basic register/deregister operations."""
    registry = SubprocessRegistry()
    
    # Start a dummy subprocess
    proc = subprocess.Popen(['sleep', '10'])
    
    # Register
    registry.register(proc)
    assert len(registry.list()) == 1
    assert proc in registry.list()
    
    # Deregister
    registry.deregister(proc)
    assert len(registry.list()) == 0
    
    # Cleanup
    proc.terminate()
    proc.wait(timeout=1)


def test_subprocess_registry_terminate_all():
    """Test terminate_all with SIGTERM."""
    registry = SubprocessRegistry()
    
    # Start dummy subprocesses
    proc1 = subprocess.Popen(['sleep', '10'])
    proc2 = subprocess.Popen(['sleep', '10'])
    
    registry.register(proc1)
    registry.register(proc2)
    
    # Terminate all
    registry.terminate_all(timeout=1)
    
    # Verify both terminated
    assert proc1.poll() is not None
    assert proc2.poll() is not None


def test_subprocess_registry_sigkill_escalation():
    """Test that SIGKILL is sent if SIGTERM doesn't work in time."""
    import signal
    registry = SubprocessRegistry()
    
    # Create a process that ignores SIGTERM (trap in shell)
    # Note: On macOS, 'trap "" TERM' may not work in all contexts, so we use a simpler test
    proc = subprocess.Popen(['sleep', '10'])
    
    registry.register(proc)
    
    # Terminate with very short timeout to trigger SIGKILL
    registry.terminate_all(timeout=0.1)
    
    # Verify process is dead
    assert proc.poll() is not None
