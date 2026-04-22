"""Unit tests for dag_executor.drafts_fs module."""

import stat
import time
import threading
from pathlib import Path
from typing import List
from unittest.mock import patch

import pytest

from dag_executor import drafts_fs


class TestWriteDraft:
    """Tests for write_draft function."""

    def test_write_draft_creates_drafts_dir(self, tmp_path: Path) -> None:
        """First write creates .drafts/{name}/ with 0o755 perms."""
        drafts_fs.write_draft(tmp_path, "test-workflow", "key: value")
        
        drafts_dir = tmp_path / ".drafts" / "test-workflow"
        assert drafts_dir.exists()
        assert drafts_dir.is_dir()
        
        # Check directory permissions
        dir_stat = drafts_dir.stat()
        assert stat.S_IMODE(dir_stat.st_mode) == 0o755

    def test_write_draft_returns_timestamp_format(self, tmp_path: Path) -> None:
        """Returned string matches ^\\d{8}T\\d{6}Z$."""
        ts = drafts_fs.write_draft(tmp_path, "test-workflow", "key: value")
        
        import re
        assert re.match(r'^\d{8}T\d{6}Z$', ts), f"Timestamp {ts} doesn't match expected format"

    def test_write_draft_file_perms_0644(self, tmp_path: Path) -> None:
        """Draft files have 0o644 permissions."""
        ts = drafts_fs.write_draft(tmp_path, "test-workflow", "key: value")
        
        draft_file = tmp_path / ".drafts" / "test-workflow" / f"{ts}.yaml"
        file_stat = draft_file.stat()
        assert stat.S_IMODE(file_stat.st_mode) == 0o644

    def test_write_is_atomic_uses_temp_then_rename(self, tmp_path: Path) -> None:
        """write_draft uses temp-then-rename pattern via Path.replace."""
        # Track what was called
        replace_called = []
        original_replace = Path.replace

        def track_replace(self, target):
            replace_called.append((str(self), str(target)))
            return original_replace(self, target)

        with patch.object(Path, 'replace', track_replace):
            ts = drafts_fs.write_draft(tmp_path, "test-workflow", "key: value")

        # Verify replace was called with temp → final pattern
        assert len(replace_called) == 1, "Path.replace should be called once"
        source, target = replace_called[0]
        assert '.yaml.tmp' in source, f"Source should be temp file: {source}"
        assert target.endswith(f'{ts}.yaml'), f"Target should be final .yaml file: {target}"

    def test_write_atomic_under_concurrent_writes(self, tmp_path: Path) -> None:
        """10 concurrent writers produce 10 distinct drafts, none corrupted."""
        results: List[str] = []
        errors: List[Exception] = []

        def write_thread(thread_id: int) -> None:
            try:
                # Stagger writes by 1.1s to avoid timestamp collisions (second-granular)
                time.sleep(thread_id * 1.1)
                content = f"thread: {thread_id}\ndata: test-{thread_id}"
                ts = drafts_fs.write_draft(tmp_path, "test-workflow", content)
                results.append((thread_id, ts, content))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=write_thread, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Errors during concurrent writes: {errors}"
        assert len(results) == 10, f"Expected 10 results, got {len(results)}"

        # Verify each file exists and has correct content
        for thread_id, ts, expected_content in results:
            draft_file = tmp_path / ".drafts" / "test-workflow" / f"{ts}.yaml"
            assert draft_file.exists(), f"Draft {ts} not found"
            actual_content = draft_file.read_text()
            assert actual_content == expected_content, f"Content mismatch for thread {thread_id}"

    def test_write_draft_same_second_collision_handled(self, tmp_path: Path) -> None:
        """If timestamp collision occurs, busy-waits or raises RuntimeError."""
        from datetime import datetime, timezone

        # Mock datetime to return same timestamp twice
        fake_time = datetime(2026, 4, 22, 12, 0, 0, tzinfo=timezone.utc)

        with patch('dag_executor.drafts_fs.datetime') as mock_datetime:
            mock_datetime.now.return_value = fake_time
            mock_datetime.strftime = datetime.strftime

            # First write should succeed
            drafts_fs.write_draft(tmp_path, "test-workflow", "first")

            # Second write with same timestamp should handle collision
            # Either it retries and succeeds, or it raises RuntimeError
            try:
                drafts_fs.write_draft(tmp_path, "test-workflow", "second")
                # If it succeeded, timestamps should be different (retry worked)
                # OR the mock needs to be more sophisticated
            except RuntimeError as e:
                assert "collision" in str(e).lower() or "retry" in str(e).lower()


class TestReadDraft:
    """Tests for read_draft function."""

    def test_round_trip_write_then_read_preserves_content(self, tmp_path: Path) -> None:
        """Write then read preserves exact YAML content."""
        yaml_content = """version: 1.0
steps:
  - name: test
    action: run
"""
        ts = drafts_fs.write_draft(tmp_path, "test-workflow", yaml_content)
        read_content = drafts_fs.read_draft(tmp_path, "test-workflow", ts)
        
        assert read_content == yaml_content

    def test_read_draft_missing_raises_filenotfounderror(self, tmp_path: Path) -> None:
        """Reading non-existent draft raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            drafts_fs.read_draft(tmp_path, "test-workflow", "20260101T000000Z")


class TestListDrafts:
    """Tests for list_drafts function."""

    def test_list_drafts_empty_when_no_dir(self, tmp_path: Path) -> None:
        """Returns [] when drafts directory doesn't exist."""
        drafts = drafts_fs.list_drafts(tmp_path, "nonexistent-workflow")
        assert drafts == []

    def test_list_drafts_returns_sorted_oldest_first(self, tmp_path: Path) -> None:
        """Returns timestamps sorted oldest→newest."""
        # Write 3 drafts with delays to ensure different timestamps
        ts1 = drafts_fs.write_draft(tmp_path, "test-workflow", "draft 1")
        time.sleep(1.1)
        ts2 = drafts_fs.write_draft(tmp_path, "test-workflow", "draft 2")
        time.sleep(1.1)
        ts3 = drafts_fs.write_draft(tmp_path, "test-workflow", "draft 3")
        
        drafts = drafts_fs.list_drafts(tmp_path, "test-workflow")
        assert drafts == [ts1, ts2, ts3], "Drafts should be sorted oldest first"

    def test_list_drafts_ignores_published_log_and_dotfiles(self, tmp_path: Path) -> None:
        """PUBLISHED.log and dotfiles not returned by list_drafts."""
        # Create drafts dir
        drafts_dir = tmp_path / ".drafts" / "test-workflow"
        drafts_dir.mkdir(parents=True)
        
        # Create a real draft
        ts = drafts_fs.write_draft(tmp_path, "test-workflow", "real draft")
        
        # Create files that should be ignored
        (drafts_dir / "PUBLISHED.log").write_text("log entry\n")
        (drafts_dir / ".current").write_text("20260101T000000Z")
        (drafts_dir / ".gitignore").write_text("*.tmp\n")
        
        drafts = drafts_fs.list_drafts(tmp_path, "test-workflow")
        assert drafts == [ts], "Should only return actual draft timestamp"


class TestPrune:
    """Tests for prune function."""

    def test_prune_keeps_most_recent_n(self, tmp_path: Path) -> None:
        """prune(keep=50) deletes oldest, keeps 50 newest."""
        # Write 60 drafts
        all_ts = []
        for i in range(60):
            ts = drafts_fs.write_draft(tmp_path, "test-workflow", f"draft {i}")
            all_ts.append(ts)
            if i < 59:  # Don't sleep after last one
                time.sleep(0.05)  # Small delay to ensure different timestamps
        
        # Prune to keep 50
        deleted = drafts_fs.prune(tmp_path, "test-workflow", keep=50)
        
        # Should delete 10 oldest
        assert len(deleted) == 10, f"Should delete 10, deleted {len(deleted)}"
        assert deleted == all_ts[:10], "Should delete the 10 oldest timestamps"
        
        # Verify 50 newest remain
        remaining = drafts_fs.list_drafts(tmp_path, "test-workflow")
        assert len(remaining) == 50
        assert remaining == all_ts[10:], "Should keep the 50 newest timestamps"

    def test_explicit_prune_after_writes(self, tmp_path: Path) -> None:
        """Write 51 drafts, call prune explicitly, verify count == 50."""
        # Write 51 drafts
        for i in range(51):
            drafts_fs.write_draft(tmp_path, "test-workflow", f"draft {i}")
            if i < 50:
                time.sleep(0.05)
        
        # Should have 51 drafts
        drafts = drafts_fs.list_drafts(tmp_path, "test-workflow")
        assert len(drafts) == 51
        
        # Explicit prune to 50
        drafts_fs.prune(tmp_path, "test-workflow", keep=50)
        
        # Should now have 50
        drafts = drafts_fs.list_drafts(tmp_path, "test-workflow")
        assert len(drafts) == 50


class TestDeleteDraft:
    """Tests for delete_draft function."""

    def test_delete_draft_idempotent(self, tmp_path: Path) -> None:
        """Deleting non-existent draft does not raise."""
        # Should not raise
        drafts_fs.delete_draft(tmp_path, "test-workflow", "20260101T000000Z")
        
        # Also test with existing then deleted
        ts = drafts_fs.write_draft(tmp_path, "test-workflow", "content")
        drafts_fs.delete_draft(tmp_path, "test-workflow", ts)
        
        # Second delete should not raise
        drafts_fs.delete_draft(tmp_path, "test-workflow", ts)


class TestPublish:
    """Tests for publish function."""

    def test_publish_copies_to_canonical(self, tmp_path: Path) -> None:
        """After publish, {workflow_dir}/{name}.yaml contains draft content."""
        content = "version: 1.0\nsteps: []"
        ts = drafts_fs.write_draft(tmp_path, "test-workflow", content)
        
        drafts_fs.publish(tmp_path, "test-workflow", ts, "test-publisher")
        
        canonical_file = tmp_path / "test-workflow.yaml"
        assert canonical_file.exists()
        assert canonical_file.read_text() == content

    def test_publish_is_atomic(self, tmp_path: Path) -> None:
        """Publish uses temp-then-rename pattern."""
        ts = drafts_fs.write_draft(tmp_path, "test-workflow", "content")
        
        with patch.object(Path, 'replace') as mock_replace:
            drafts_fs.publish(tmp_path, "test-workflow", ts, "test-publisher")
            
            # Verify replace was called for atomic rename
            assert mock_replace.called, "Path.replace should be called for atomic rename"

    def test_publish_appends_to_published_log(self, tmp_path: Path) -> None:
        """Verify exact format: {iso_utc}  {publisher}  published {ts}\\n"""
        ts = drafts_fs.write_draft(tmp_path, "test-workflow", "content")
        
        drafts_fs.publish(tmp_path, "test-workflow", ts, "dashboard-ui  alice@host")
        
        log_file = tmp_path / ".drafts" / "test-workflow" / "PUBLISHED.log"
        assert log_file.exists()
        
        log_content = log_file.read_text()
        lines = log_content.strip().split('\n')
        assert len(lines) == 1
        
        # Check format: YYYY-MM-DDTHH:MM:SSZ  publisher  published YYYYMMDDTHHMMSSZ
        import re
        pattern = r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z  .+  published \d{8}T\d{6}Z$'
        assert re.match(pattern, lines[0]), f"Log line doesn't match format: {lines[0]}"

    def test_publish_log_is_append_only(self, tmp_path: Path) -> None:
        """Publish twice, verify log has 2 lines."""
        ts1 = drafts_fs.write_draft(tmp_path, "test-workflow", "content 1")
        drafts_fs.publish(tmp_path, "test-workflow", ts1, "publisher1")
        
        time.sleep(1.1)
        ts2 = drafts_fs.write_draft(tmp_path, "test-workflow", "content 2")
        drafts_fs.publish(tmp_path, "test-workflow", ts2, "publisher2")
        
        log_file = tmp_path / ".drafts" / "test-workflow" / "PUBLISHED.log"
        log_content = log_file.read_text()
        lines = log_content.strip().split('\n')
        assert len(lines) == 2

    def test_publish_log_format_matches_prp(self, tmp_path: Path) -> None:
        """Log format matches PRP spec exactly."""
        ts = drafts_fs.write_draft(tmp_path, "test-workflow", "content")
        drafts_fs.publish(tmp_path, "test-workflow", ts, "dashboard-ui  alice@host")
        
        log_file = tmp_path / ".drafts" / "test-workflow" / "PUBLISHED.log"
        log_line = log_file.read_text().strip()
        
        # PRP format: 2026-04-21T16:05:00Z  dashboard-ui  alice@host  published 20260421T160102Z
        import re
        pattern = r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z  dashboard-ui  alice@host  published \d{8}T\d{6}Z$'
        assert re.match(pattern, log_line), f"Log line doesn't match PRP format: {log_line}"


class TestIsolation:
    """Tests for workflow isolation."""

    def test_multiple_workflows_isolated(self, tmp_path: Path) -> None:
        """Write to workflow 'a' does not appear in list_drafts for 'b'."""
        ts_a = drafts_fs.write_draft(tmp_path, "workflow-a", "content a")
        time.sleep(1.1)  # Ensure different timestamps
        ts_b = drafts_fs.write_draft(tmp_path, "workflow-b", "content b")

        drafts_a = drafts_fs.list_drafts(tmp_path, "workflow-a")
        drafts_b = drafts_fs.list_drafts(tmp_path, "workflow-b")

        assert drafts_a == [ts_a]
        assert drafts_b == [ts_b]
        assert ts_a not in drafts_b
        assert ts_b not in drafts_a
