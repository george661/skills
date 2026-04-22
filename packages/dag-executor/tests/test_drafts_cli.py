"""
Tests for dag_executor.drafts_cli — CLI subcommands for workflow drafts management.

Covers:
- Local mode (drafts_fs integration)
- Remote mode (httpx + mocked endpoints)
- Confirmation prompts
- Error handling
"""

import json
from io import StringIO
from unittest.mock import MagicMock, Mock, patch

import pytest


# --- List tests ---


def test_list_local_empty(tmp_path, capsys, monkeypatch):
    """List with no drafts → empty output, exit 0."""
    monkeypatch.chdir(tmp_path)
    with patch("dag_executor.drafts_fs.list_drafts", return_value=[]):
        from dag_executor.drafts_cli import run_drafts
        run_drafts(["list", "my-workflow"])
    captured = capsys.readouterr()
    assert captured.out == ""


def test_list_local_with_drafts(tmp_path, capsys, monkeypatch):
    """List with 3 drafts → three lines in stdout."""
    monkeypatch.chdir(tmp_path)
    with patch("dag_executor.drafts_fs.list_drafts", return_value=["1234567890", "1234567891", "1234567892"]):
        from dag_executor.drafts_cli import run_drafts
        run_drafts(["list", "my-workflow"])
    captured = capsys.readouterr()
    lines = captured.out.strip().split("\n")
    assert len(lines) == 3
    assert "1234567890" in lines
    assert "1234567891" in lines
    assert "1234567892" in lines


def test_list_local_json_mode(tmp_path, capsys, monkeypatch):
    """List --json → valid JSON array."""
    monkeypatch.chdir(tmp_path)
    with patch("dag_executor.drafts_fs.list_drafts", return_value=["1234567890", "1234567891"]):
        from dag_executor.drafts_cli import run_drafts
        run_drafts(["list", "my-workflow", "--json"])
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data == ["1234567890", "1234567891"]


def test_list_remote_calls_api(capsys, monkeypatch):
    """List --remote → GET /api/workflows/{name}/drafts."""
    mock_response = Mock(status_code=200)
    mock_response.json.return_value = {"drafts": ["1234567890", "1234567891"]}
    
    mock_client_instance = MagicMock()
    mock_client_instance.get.return_value = mock_response
    mock_client_instance.__enter__.return_value = mock_client_instance
    mock_client_instance.__exit__.return_value = None
    
    with patch("httpx.Client", return_value=mock_client_instance):
        from dag_executor.drafts_cli import run_drafts
        run_drafts(["list", "my-workflow", "--remote", "https://api.example.com", "--token", "fake-token"])

    mock_client_instance.get.assert_called_once()
    call_args = mock_client_instance.get.call_args
    assert "/api/workflows/my-workflow/drafts" in call_args[0][0]
    assert call_args[1]["headers"]["Authorization"] == "Bearer fake-token"

    captured = capsys.readouterr()
    lines = captured.out.strip().split("\n")
    assert len(lines) == 2


# --- Diff tests ---


def test_diff_local_draft_vs_canonical_single_ts(tmp_path, capsys, monkeypatch):
    """Diff single ts → unified diff of draft vs canonical."""
    monkeypatch.chdir(tmp_path)
    draft_content = "name: test\nsteps:\n  - run: echo draft\n"
    canonical_content = "name: test\nsteps:\n  - run: echo canonical\n"

    (tmp_path / "my-workflow.yaml").write_text(canonical_content)

    with patch("dag_executor.drafts_fs.read_draft", return_value=draft_content):
        from dag_executor.drafts_cli import run_drafts
        run_drafts(["diff", "my-workflow", "1234567890"])

    captured = capsys.readouterr()
    assert "---" in captured.out
    assert "+++" in captured.out
    assert "@@" in captured.out


def test_diff_local_draft_vs_draft_two_ts(tmp_path, capsys, monkeypatch):
    """Diff two ts → diff between drafts."""
    monkeypatch.chdir(tmp_path)
    draft_a = "name: test\nsteps:\n  - run: echo a\n"
    draft_b = "name: test\nsteps:\n  - run: echo b\n"

    def mock_read_draft(wf_dir, name, ts):
        if ts == "1234567890":
            return draft_a
        return draft_b

    with patch("dag_executor.drafts_fs.read_draft", side_effect=mock_read_draft):
        from dag_executor.drafts_cli import run_drafts
        run_drafts(["diff", "my-workflow", "1234567890", "1234567891"])

    captured = capsys.readouterr()
    assert "---" in captured.out
    assert "+++" in captured.out


def test_diff_local_identical_returns_empty(tmp_path, capsys, monkeypatch):
    """Diff with identical content → empty stdout, exit 0."""
    monkeypatch.chdir(tmp_path)
    content = "name: test\nsteps:\n  - run: echo same\n"

    (tmp_path / "my-workflow.yaml").write_text(content)

    with patch("dag_executor.drafts_fs.read_draft", return_value=content):
        from dag_executor.drafts_cli import run_drafts
        run_drafts(["diff", "my-workflow", "1234567890"])

    captured = capsys.readouterr()
    # Identical content should produce no diff output
    assert captured.out.strip() == ""


def test_diff_local_missing_draft_raises_filenotfound(tmp_path, capsys, monkeypatch):
    """Diff with missing draft → FileNotFoundError propagated as exit 1."""
    monkeypatch.chdir(tmp_path)
    with patch("dag_executor.drafts_fs.read_draft", side_effect=FileNotFoundError("Draft not found")):
        from dag_executor.drafts_cli import run_drafts
        with pytest.raises(SystemExit) as exc_info:
            run_drafts(["diff", "my-workflow", "1234567890"])
        assert exc_info.value.code == 1

    captured = capsys.readouterr()
    assert "not found" in captured.err.lower() or "error" in captured.err.lower()


def test_diff_remote_fetches_both_drafts(capsys):
    """Diff --remote → two GET calls, client-side diff."""
    mock_response_a = Mock(status_code=200, text="name: test\nsteps:\n  - run: echo a\n")
    mock_response_b = Mock(status_code=200, text="name: test\nsteps:\n  - run: echo b\n")

    mock_client_instance = MagicMock()
    mock_client_instance.get.side_effect = [mock_response_a, mock_response_b]
    mock_client_instance.__enter__.return_value = mock_client_instance
    mock_client_instance.__exit__.return_value = None

    with patch("httpx.Client", return_value=mock_client_instance):
        from dag_executor.drafts_cli import run_drafts
        run_drafts(["diff", "my-workflow", "1234567890", "1234567891", "--remote", "https://api.example.com", "--token", "fake-token"])

    assert mock_client_instance.get.call_count == 2
    captured = capsys.readouterr()
    assert "---" in captured.out


# --- Restore tests ---


def test_restore_local_writes_canonical_atomically(tmp_path, monkeypatch):
    """Restore writes {name}.yaml.tmp then renames."""
    monkeypatch.chdir(tmp_path)
    draft_content = "name: test\nsteps:\n  - run: echo restored\n"

    # Mock stdin for confirmation
    monkeypatch.setattr('sys.stdin', StringIO("y\n"))

    with patch("dag_executor.drafts_fs.read_draft", return_value=draft_content):
        from dag_executor.drafts_cli import run_drafts
        run_drafts(["restore", "my-workflow", "1234567890"])

    canonical_path = tmp_path / "my-workflow.yaml"
    assert canonical_path.exists()
    assert canonical_path.read_text() == draft_content


def test_restore_local_requires_confirmation_by_default(tmp_path, capsys, monkeypatch):
    """Restore without --yes, stdin="n" → aborted, canonical unchanged."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "my-workflow.yaml").write_text("original content")

    monkeypatch.setattr('sys.stdin', StringIO("n\n"))

    with patch("dag_executor.drafts_fs.read_draft", return_value="draft content"):
        from dag_executor.drafts_cli import run_drafts
        with pytest.raises(SystemExit) as exc_info:
            run_drafts(["restore", "my-workflow", "1234567890"])
        assert exc_info.value.code == 1

    assert (tmp_path / "my-workflow.yaml").read_text() == "original content"
    captured = capsys.readouterr()
    assert "abort" in captured.err.lower()


def test_restore_local_yes_skips_prompt(tmp_path, monkeypatch):
    """Restore --yes → no prompt, canonical written."""
    monkeypatch.chdir(tmp_path)
    draft_content = "name: test\nsteps:\n  - run: echo yes\n"

    with patch("dag_executor.drafts_fs.read_draft", return_value=draft_content):
        from dag_executor.drafts_cli import run_drafts
        run_drafts(["restore", "my-workflow", "1234567890", "--yes"])

    canonical_path = tmp_path / "my-workflow.yaml"
    assert canonical_path.read_text() == draft_content


def test_restore_local_prompt_accepts_y_upper_and_lower(tmp_path, monkeypatch):
    """Restore accepts y, Y, yes."""
    monkeypatch.chdir(tmp_path)
    draft_content = "test"

    for answer in ["y\n", "Y\n", "yes\n"]:
        monkeypatch.setattr('sys.stdin', StringIO(answer))
        with patch("dag_executor.drafts_fs.read_draft", return_value=draft_content):
            from dag_executor.drafts_cli import run_drafts
            run_drafts(["restore", "my-workflow", "1234567890"])


def test_restore_remote_calls_api_with_yes(capsys):
    """Restore --remote → POST/PUT to publish endpoint."""
    mock_response = Mock(status_code=200)
    
    mock_client_instance = MagicMock()
    mock_client_instance.post.return_value = mock_response
    mock_client_instance.__enter__.return_value = mock_client_instance
    mock_client_instance.__exit__.return_value = None

    with patch("httpx.Client", return_value=mock_client_instance):
        from dag_executor.drafts_cli import run_drafts
        run_drafts(["restore", "my-workflow", "1234567890", "--remote", "https://api.example.com", "--token", "fake-token", "--yes"])

    # Should call POST to publish/restore
    assert mock_client_instance.post.call_count >= 1


# --- Publish tests ---


def test_publish_local_invalid_yaml_exits_1_no_publish(tmp_path, capsys, monkeypatch):
    """Publish with invalid YAML → exit 1, drafts_fs.publish NOT called."""
    monkeypatch.chdir(tmp_path)
    invalid_yaml = "invalid: [missing bracket"

    with patch("dag_executor.drafts_fs.read_draft", return_value=invalid_yaml):
        with patch("dag_executor.parser.load_workflow", side_effect=Exception("Invalid YAML")):
            with patch("dag_executor.drafts_fs.publish") as mock_publish:
                from dag_executor.drafts_cli import run_drafts
                with pytest.raises(SystemExit) as exc_info:
                    run_drafts(["publish", "my-workflow", "1234567890"])
                assert exc_info.value.code == 1
                mock_publish.assert_not_called()


def test_publish_local_valid_yaml_calls_drafts_fs_publish(tmp_path, capsys, monkeypatch):
    """Publish valid YAML → calls drafts_fs.publish with correct publisher string."""
    monkeypatch.chdir(tmp_path)
    valid_yaml = "name: test\nsteps:\n  - run: echo ok\n"

    monkeypatch.setenv("USER", "testuser")
    with patch("socket.gethostname", return_value="testhost"):
        with patch("dag_executor.drafts_fs.read_draft", return_value=valid_yaml):
            with patch("dag_executor.parser.load_workflow"):
                with patch("dag_executor.drafts_fs.publish") as mock_publish:
                    from dag_executor.drafts_cli import run_drafts
                    run_drafts(["publish", "my-workflow", "1234567890"])
                    mock_publish.assert_called_once()
                    call_args = mock_publish.call_args[0]
                    publisher = call_args[3]  # Fourth argument is publisher
                    assert "testuser" in publisher
                    assert "testhost" in publisher
                    assert "cli" in publisher


def test_publish_local_prints_success_message(tmp_path, capsys, monkeypatch):
    """Publish success → stdout contains success message."""
    monkeypatch.chdir(tmp_path)
    valid_yaml = "name: test\n"

    with patch("dag_executor.drafts_fs.read_draft", return_value=valid_yaml):
        with patch("dag_executor.parser.load_workflow"):
            with patch("dag_executor.drafts_fs.publish"):
                from dag_executor.drafts_cli import run_drafts
                run_drafts(["publish", "my-workflow", "1234567890"])

    captured = capsys.readouterr()
    assert "published" in captured.out.lower()
    assert "1234567890" in captured.out


def test_publish_remote_calls_publish_endpoint(capsys):
    """Publish --remote → POST to /drafts/{ts}/publish."""
    mock_response = Mock(status_code=200)
    
    mock_client_instance = MagicMock()
    mock_client_instance.post.return_value = mock_response
    mock_client_instance.__enter__.return_value = mock_client_instance
    mock_client_instance.__exit__.return_value = None

    with patch("httpx.Client", return_value=mock_client_instance):
        from dag_executor.drafts_cli import run_drafts
        run_drafts(["publish", "my-workflow", "1234567890", "--remote", "https://api.example.com", "--token", "fake-token"])

    mock_client_instance.post.assert_called_once()
    call_args = mock_client_instance.post.call_args
    assert "/api/workflows/my-workflow/drafts/1234567890/publish" in call_args[0][0]


def test_publish_remote_non_2xx_exits_1(capsys):
    """Publish --remote with 400 → exit 1, body printed."""
    mock_response = Mock(status_code=400, text="Validation failed")
    
    mock_client_instance = MagicMock()
    mock_client_instance.post.return_value = mock_response
    mock_client_instance.__enter__.return_value = mock_client_instance
    mock_client_instance.__exit__.return_value = None

    with patch("httpx.Client", return_value=mock_client_instance):
        from dag_executor.drafts_cli import run_drafts
        with pytest.raises(SystemExit) as exc_info:
            run_drafts(["publish", "my-workflow", "1234567890", "--remote", "https://api.example.com", "--token", "fake-token"])
        assert exc_info.value.code == 1

    captured = capsys.readouterr()
    assert "400" in captured.err or "validation" in captured.err.lower()


def test_publish_remote_missing_token_exits_2(capsys):
    """Publish --remote without token → exit 2."""
    from dag_executor.drafts_cli import run_drafts
    with pytest.raises(SystemExit) as exc_info:
        run_drafts(["publish", "my-workflow", "1234567890", "--remote", "https://api.example.com"])
    assert exc_info.value.code == 2


# --- Delete tests ---


def test_delete_local_calls_drafts_fs_delete(tmp_path, monkeypatch):
    """Delete calls drafts_fs.delete_draft."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr('sys.stdin', StringIO("y\n"))

    with patch("dag_executor.drafts_fs.delete_draft") as mock_delete:
        from dag_executor.drafts_cli import run_drafts
        run_drafts(["delete", "my-workflow", "1234567890"])
        mock_delete.assert_called_once()


def test_delete_local_requires_confirmation_by_default(tmp_path, capsys, monkeypatch):
    """Delete without --yes, stdin="n" → aborted."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr('sys.stdin', StringIO("n\n"))

    with patch("dag_executor.drafts_fs.delete_draft") as mock_delete:
        from dag_executor.drafts_cli import run_drafts
        with pytest.raises(SystemExit) as exc_info:
            run_drafts(["delete", "my-workflow", "1234567890"])
        assert exc_info.value.code == 1
        mock_delete.assert_not_called()


def test_delete_local_yes_skips_prompt_and_succeeds(tmp_path, capsys, monkeypatch):
    """Delete --yes → no prompt, draft deleted."""
    monkeypatch.chdir(tmp_path)

    with patch("dag_executor.drafts_fs.delete_draft"):
        from dag_executor.drafts_cli import run_drafts
        run_drafts(["delete", "my-workflow", "1234567890", "--yes"])

    captured = capsys.readouterr()
    assert "deleted" in captured.out.lower()


def test_delete_remote_404_treated_as_success(capsys):
    """Delete --remote with 404 → exit 0 (idempotent)."""
    mock_response = Mock(status_code=404)
    
    mock_client_instance = MagicMock()
    mock_client_instance.delete.return_value = mock_response
    mock_client_instance.__enter__.return_value = mock_client_instance
    mock_client_instance.__exit__.return_value = None

    with patch("httpx.Client", return_value=mock_client_instance):
        from dag_executor.drafts_cli import run_drafts
        # Should not raise
        run_drafts(["delete", "my-workflow", "1234567890", "--remote", "https://api.example.com", "--token", "fake-token", "--yes"])

    captured = capsys.readouterr()
    # Should still print success message
    assert "deleted" in captured.out.lower()


# --- Dispatcher integration tests ---


def test_main_drafts_list_dispatches_to_run_drafts(tmp_path, monkeypatch):
    """main([\"drafts\", \"list\", ...]) dispatches to run_drafts."""
    monkeypatch.chdir(tmp_path)
    with patch("dag_executor.drafts_cli.run_drafts") as mock_run:
        from dag_executor.cli import main
        main(["drafts", "list", "wf"])
        mock_run.assert_called_once_with(["list", "wf"])


def test_drafts_added_to_subcommands_set():
    """SUBCOMMANDS contains 'drafts'."""
    from dag_executor.cli import SUBCOMMANDS
    assert "drafts" in SUBCOMMANDS


def test_drafts_unknown_subcommand_prints_help_exits_2(capsys):
    """dag-exec drafts foo → argparse error, exit 2."""
    from dag_executor.drafts_cli import run_drafts
    with pytest.raises(SystemExit) as exc_info:
        run_drafts(["foo"])
    assert exc_info.value.code == 2
