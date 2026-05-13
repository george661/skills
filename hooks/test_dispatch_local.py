"""Unit tests for the contract-tier router in dispatch-local.py (GW-5491)."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

# Load dispatch-local.py as a module despite the hyphen in the filename.
_HOOKS = Path(__file__).resolve().parent
_DISPATCH_PATH = _HOOKS / "dispatch-local.py"
_spec = importlib.util.spec_from_file_location("dispatch_local", _DISPATCH_PATH)
assert _spec is not None and _spec.loader is not None
dispatch_local = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dispatch_local)

# Skip the whole module on workstations without promptc on sys.path. The
# hooks-quality CI job pip-installs packages/promptc before running these
# tests, so it always exercises the contract path.
promptc_pytest = pytest.importorskip("promptc")


@pytest.fixture
def repo_root() -> Path:
    """Path to the worktree root (two levels up from hooks/)."""
    return _HOOKS.parent


@pytest.fixture
def contract_command_md(tmp_path: Path) -> Path:
    """Write a minimal contract-tier command file to a temp ~/.claude/commands."""
    commands_dir = tmp_path / ".claude" / "commands"
    commands_dir.mkdir(parents=True)
    cmd = commands_dir / "demo-contract.md"
    cmd.write_text(
        '{% meta description="demo" doc_type="command" tier="contract" /%}\n'
        '\n'
        '{% input name="issue" type="string" required="true" pattern="^[A-Z]+-\\d+$" /%}\n'
        '\n'
        '{% output name="STATUS" type="string" /%}\n'
        '{% output name="DETAIL" type="string" required_when="false" /%}\n'
        '\n'
        '# Demo: {% $inputs.issue %}\n'
    )
    return tmp_path


@pytest.fixture
def non_contract_command_md(tmp_path: Path) -> Path:
    """Write a plain-markdown command (no promptc tags) to a temp ~/.claude/commands."""
    commands_dir = tmp_path / ".claude" / "commands"
    commands_dir.mkdir(parents=True)
    cmd = commands_dir / "demo-plain.md"
    cmd.write_text("# Plain command\n\nNo promptc tags here.\n")
    return tmp_path


def test_non_contract_command_falls_through(non_contract_command_md, monkeypatch):
    """A command file without contract-tier frontmatter returns None from
    _load_contract_doc, so main() takes the existing raw-markdown path."""
    monkeypatch.setattr(Path, "home", lambda: non_contract_command_md)
    doc = dispatch_local._load_contract_doc("demo-plain")
    assert doc is None


def test_missing_command_file_returns_none(tmp_path, monkeypatch):
    """A command name that doesn't have a corresponding .md returns None."""
    (tmp_path / ".claude" / "commands").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    doc = dispatch_local._load_contract_doc("does-not-exist")
    assert doc is None


def test_contract_command_loads(contract_command_md, monkeypatch):
    """A command file with tier=\"contract\" frontmatter loads successfully."""
    monkeypatch.setattr(Path, "home", lambda: contract_command_md)
    doc = dispatch_local._load_contract_doc("demo-contract")
    assert doc is not None
    assert doc.tier == "contract"
    assert len(doc.inputs) == 1
    assert doc.inputs[0].name == "issue"
    assert len(doc.outputs) == 2


def test_contract_command_renders_with_inputs(contract_command_md, monkeypatch):
    """promptc.render is called with the positional arg bound to the input."""
    monkeypatch.setattr(Path, "home", lambda: contract_command_md)
    doc = dispatch_local._load_contract_doc("demo-contract")
    assert doc is not None
    rendered = dispatch_local._render_contract_prompt(doc, "GW-5491")
    assert "GW-5491" in rendered
    # mode-B should expand inputs but keep the rest of the structure
    assert "Demo:" in rendered


def test_contract_command_missing_required_input(contract_command_md, monkeypatch):
    """Missing required positional arg raises a clear error before the LLM call."""
    monkeypatch.setattr(Path, "home", lambda: contract_command_md)
    doc = dispatch_local._load_contract_doc("demo-contract")
    assert doc is not None
    with pytest.raises(ValueError, match="missing required input 'issue'"):
        dispatch_local._render_contract_prompt(doc, "")


def test_contract_command_pattern_validation(contract_command_md, monkeypatch):
    """An input value that fails the declared pattern raises a clear error."""
    monkeypatch.setattr(Path, "home", lambda: contract_command_md)
    doc = dispatch_local._load_contract_doc("demo-contract")
    assert doc is not None
    with pytest.raises(ValueError, match="does not match required pattern"):
        dispatch_local._render_contract_prompt(doc, "not-a-jira-key")


def test_emit_contract_response_clean_parse(capsys, repo_root):
    """A well-formed LLM response emits one KEY: value line per declared output."""
    import promptc as _promptc
    doc = _promptc.load(str(repo_root / "commands" / "validate-deploy-status.md"))
    fixture = (
        repo_root
        / "packages/promptc/tests/fixtures/responses/validate-deploy-status-DEPLOYED.txt"
    )
    full_output = fixture.read_text()
    dispatch_local._emit_contract_response(full_output, doc)
    captured = capsys.readouterr()
    # All 7 declared outputs appear on stdout as KEY: value lines
    for field in (
        "DEPLOY_STATUS",
        "REPO",
        "PIPELINE",
        "BUILD_ID",
        "BUILD_STATUS",
        "ENV_URL",
        "DEPLOY_GAP_REASON",
    ):
        assert f"{field}:" in captured.out, (
            f"Missing {field} in stdout:\n{captured.out}"
        )
    # Specific values from the DEPLOYED fixture
    assert "DEPLOY_STATUS: DEPLOYED" in captured.out
    assert "REPO: skills" in captured.out
    # Parse was clean — no PROMPTC_PARSE_ERRORS on stderr
    assert "PROMPTC_PARSE_ERRORS" not in captured.err


def test_emit_contract_response_optional_field_emits_n_a(capsys, repo_root):
    """When an optional output (required_when=False) is absent from the LLM
    response, the line is still emitted as `KEY: N/A` so downstream regex
    scrapers don't silently miss the field."""
    import promptc as _promptc
    doc = _promptc.load(str(repo_root / "commands" / "validate-deploy-status.md"))
    fixture = (
        repo_root
        / "packages/promptc/tests/fixtures/responses/validate-deploy-status-DEPLOYED.txt"
    )
    full_output = fixture.read_text()
    dispatch_local._emit_contract_response(full_output, doc)
    captured = capsys.readouterr()
    # DEPLOY_GAP_REASON is required_when DEPLOY_STATUS=="NEEDS_DEPLOY"; it's
    # absent from the DEPLOYED fixture, so the router emits N/A.
    assert "DEPLOY_GAP_REASON: N/A" in captured.out


def test_emit_contract_response_parse_error_falls_back_to_raw(capsys, repo_root):
    """When parse_output reports errors, the raw LLM output goes to stdout
    (so /validate's regex scraper still works) AND a PROMPTC_PARSE_ERRORS
    block goes to stderr."""
    import promptc as _promptc
    doc = _promptc.load(str(repo_root / "commands" / "validate-deploy-status.md"))
    # Malformed response: missing all declared output fields
    malformed = "I'm sorry, I couldn't determine the deploy status.\n"
    dispatch_local._emit_contract_response(malformed, doc)
    captured = capsys.readouterr()
    # Raw output preserved on stdout
    assert "I'm sorry" in captured.out
    # Errors surfaced on stderr
    assert "PROMPTC_PARSE_ERRORS:" in captured.err
    assert "DEPLOY_STATUS" in captured.err  # the missing field is named


def test_promptc_unavailable_falls_through(monkeypatch):
    """When PROMPTC_AVAILABLE is False, _load_contract_doc returns None for
    every command — no crash, no contract dispatch, just raw-markdown."""
    monkeypatch.setattr(dispatch_local, "PROMPTC_AVAILABLE", False)
    # Should return None without even attempting to read the file
    doc = dispatch_local._load_contract_doc("validate-deploy-status")
    assert doc is None


def test_input_coercion_int(contract_command_md, monkeypatch):
    """Int inputs get coerced from positional CLI strings."""
    # Build a doc with an int input on the fly
    md = contract_command_md / ".claude/commands/demo-int.md"
    md.write_text(
        '{% meta description="d" doc_type="command" tier="contract" /%}\n'
        '{% input name="count" type="int" required="true" /%}\n'
        '{% output name="OUT" type="string" /%}\n'
        '\nN={% $inputs.count %}\n'
    )
    monkeypatch.setattr(Path, "home", lambda: contract_command_md)
    doc = dispatch_local._load_contract_doc("demo-int")
    assert doc is not None
    inputs = dispatch_local._build_input_dict(doc, "42")
    assert inputs == {"count": 42}


def test_input_coercion_int_invalid(contract_command_md, monkeypatch):
    """A non-numeric value for an int input raises a clear error."""
    md = contract_command_md / ".claude/commands/demo-int2.md"
    md.write_text(
        '{% meta description="d" doc_type="command" tier="contract" /%}\n'
        '{% input name="count" type="int" required="true" /%}\n'
        '{% output name="OUT" type="string" /%}\n'
        '\nN={% $inputs.count %}\n'
    )
    monkeypatch.setattr(Path, "home", lambda: contract_command_md)
    doc = dispatch_local._load_contract_doc("demo-int2")
    assert doc is not None
    with pytest.raises(ValueError, match="must be an int"):
        dispatch_local._build_input_dict(doc, "not-a-number")


def test_input_default_used_when_arg_absent(contract_command_md, monkeypatch):
    """When a non-required input has a default and no positional arg is
    supplied, the default value is used."""
    md = contract_command_md / ".claude/commands/demo-default.md"
    md.write_text(
        '{% meta description="d" doc_type="command" tier="contract" /%}\n'
        '{% input name="issue" type="string" required="true" /%}\n'
        '{% input name="env" type="string" required="false" default="dev" /%}\n'
        '{% output name="OUT" type="string" /%}\n'
        '\nIssue={% $inputs.issue %} Env={% $inputs.env %}\n'
    )
    monkeypatch.setattr(Path, "home", lambda: contract_command_md)
    doc = dispatch_local._load_contract_doc("demo-default")
    assert doc is not None
    inputs = dispatch_local._build_input_dict(doc, "GW-1")
    assert inputs == {"issue": "GW-1", "env": "dev"}
