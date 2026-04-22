"""
Stub module for drafts_fs - actual implementation in GW-5239.

This stub allows tests to run before GW-5239 lands.

TODO: TEMPORAL COUPLING WARNING
(1) This stub exists to let GW-5241 CI pass before GW-5239 lands.
(2) GW-5239 will replace this entire file with a real implementation.
(3) If you see this on main after GW-5239 merges, it means this PR was merged
    first by accident — rebase onto main and delete this file.

This keeps the stub but documents the temporal coupling explicitly so future
maintainers understand the situation.
"""


def list_drafts(wf_dir: str, name: str) -> list[str]:
    """List all draft timestamps for a workflow."""
    raise NotImplementedError("drafts_fs.list_drafts not yet implemented (GW-5239)")


def read_draft(wf_dir: str, name: str, timestamp: str) -> str:
    """Read a draft file."""
    raise NotImplementedError("drafts_fs.read_draft not yet implemented (GW-5239)")


def write_draft(wf_dir: str, name: str, content: str, author: str) -> str:
    """Write a new draft."""
    raise NotImplementedError("drafts_fs.write_draft not yet implemented (GW-5239)")


def publish(wf_dir: str, name: str, timestamp: str, publisher: str) -> None:
    """Publish a draft as canonical."""
    raise NotImplementedError("drafts_fs.publish not yet implemented (GW-5239)")


def delete_draft(wf_dir: str, name: str, timestamp: str) -> None:
    """Delete a draft."""
    raise NotImplementedError("drafts_fs.delete_draft not yet implemented (GW-5239)")


def prune(wf_dir: str, name: str, keep: int = 10) -> int:
    """Prune old drafts, keeping only the most recent N."""
    raise NotImplementedError("drafts_fs.prune not yet implemented (GW-5239)")
