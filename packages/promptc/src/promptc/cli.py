"""Promptc CLI — validate, render, explain, and parse subcommands."""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Optional

from promptc import contract, migrate, parser, render, validator
from promptc.errors import ParseError, RenderError
from promptc.schema import Doc

SUPPORTED_VERSION = 1


def _check_version(doc: Doc, allow_future: bool) -> Optional[dict[str, Any]]:
    """Check document version and return error dict if unsupported."""
    if doc.meta is None:
        return None
    v = doc.meta.extras.get("version")
    if v is None:
        return None
    try:
        vn = int(v)
    except (TypeError, ValueError):
        return {"error": f"meta version must be an integer, got {v!r}"}
    if vn > SUPPORTED_VERSION and not allow_future:
        return {
            "error": (
                f"meta version={vn} exceeds supported version {SUPPORTED_VERSION}; "
                "pass --allow-future-version to override"
            )
        }
    return None


def _load_doc(path: str) -> tuple[Optional[Doc], Optional[dict[str, Any]]]:
    """Load and parse a promptc document. Returns (doc, error_dict)."""
    try:
        doc = parser.load(path)
        return doc, None
    except ParseError as e:
        return None, {"error": f"Parse error: {e}"}
    except FileNotFoundError:
        return None, {"error": f"File not found: {path}"}
    except OSError as e:
        return None, {"error": f"File read error: {e}"}


def _emit(payload: dict[str, Any], fmt: Optional[str]) -> None:
    """Emit output in the specified format."""
    if fmt == "json":
        print(json.dumps(payload, indent=2))
    else:
        # Human-readable format — subcommand-specific
        if "output" in payload:
            # render subcommand
            print(payload["output"])
        elif "ok" in payload:
            # validate subcommand
            if payload["ok"]:
                print("OK")
                if payload.get("issues"):
                    for issue in payload["issues"]:
                        severity = issue.get("severity", "").upper()
                        code = issue.get("code", "")
                        message = issue.get("message", "")
                        print(f"  [{severity}] {code}: {message}")
            else:
                print("VALIDATION FAILED")
                for issue in payload.get("issues", []):
                    severity = issue.get("severity", "").upper()
                    code = issue.get("code", "")
                    message = issue.get("message", "")
                    print(f"  [{severity}] {code}: {message}")
        elif "tier" in payload:
            # explain subcommand
            print(f"Path: {payload.get('path', 'N/A')}")
            print(f"Tier: {payload.get('tier', 'N/A')}")
            print(f"Doc Type: {payload.get('doc_type', 'N/A')}")
            meta = payload.get("meta", {})
            if meta:
                print(f"Meta Description: {meta.get('description', 'N/A')}")
                print(f"Meta Model: {meta.get('model', 'N/A')}")
                print(f"Meta Owner: {meta.get('owner', 'N/A')}")
            inputs = payload.get("inputs", [])
            if inputs:
                print(f"\nInputs ({len(inputs)}):")
                for inp in inputs:
                    req = " (required)" if inp.get("required") else ""
                    default_val = inp.get("default")
                    default = f", default={default_val}" if default_val is not None else ""
                    print(f"  - {inp['name']}: {inp['type']}{req}{default}")
            outputs = payload.get("outputs", [])
            if outputs:
                print(f"\nOutputs ({len(outputs)}):")
                for out in outputs:
                    req_when = out.get("required_when")
                    req_str = f", required_when={req_when}" if req_when else ""
                    print(f"  - {out['name']}: {out['type']}{req_str}")
            phases = payload.get("phases", [])
            if phases:
                print(f"\nPhases ({len(phases)}): {', '.join(phases)}")
            runs = payload.get("runs", [])
            if runs:
                print(f"\nRuns ({len(runs)}):")
                for run in runs:
                    skill = run.get("skill", "")
                    run_id = run.get("id", "")
                    capture = run.get("capture", "")
                    parts = []
                    if skill:
                        parts.append(f"skill={skill}")
                    if run_id:
                        parts.append(f"id={run_id}")
                    if capture:
                        parts.append(f"capture={capture}")
                    print(f"  - {', '.join(parts)}")
            refs = payload.get("refs", [])
            if refs:
                print(f"\nRefs ({len(refs)}):")
                for ref in refs:
                    file = ref.get("file", "")
                    include = ref.get("include", False)
                    mode = "include" if include else "link"
                    print(f"  - {file} ({mode})")
            skills = payload.get("skills", [])
            if skills:
                print(f"\nSkills ({len(skills)}): {', '.join(skills)}")
        elif "fields" in payload or "errors" in payload:
            # parse subcommand
            if payload.get("errors"):
                print("PARSE FAILED")
                for err in payload["errors"]:
                    print(f"  ERROR: {err}")
            else:
                print("OK")
                fields = payload.get("fields", {})
                if fields:
                    print(f"Fields extracted: {len(fields)}")
                    for field_name, field_value in fields.items():
                        print(f"  {field_name}: {field_value}")
        elif "error" in payload:
            # Generic error
            print(f"ERROR: {payload['error']}", file=sys.stderr)


def _cmd_validate(args: argparse.Namespace) -> int:
    """Handle validate subcommand."""
    doc, err = _load_doc(args.file)
    if err:
        _emit(err, args.format)
        return 1

    assert doc is not None

    # Check version
    ver_err = _check_version(doc, args.allow_future_version)
    if ver_err:
        _emit(ver_err, args.format)
        return 1

    # Run validation
    report = validator.validate_path(args.file)
    payload = report.model_dump()
    _emit(payload, args.format)

    # Exit 1 if validation failed
    return 0 if report.ok else 1


def _cmd_render(args: argparse.Namespace) -> int:
    """Handle render subcommand."""
    doc, err = _load_doc(args.file)
    if err:
        _emit(err, args.format)
        return 1

    assert doc is not None

    # Check version
    ver_err = _check_version(doc, args.allow_future_version)
    if ver_err:
        _emit(ver_err, args.format)
        return 1

    # Parse inputs if provided
    inputs_dict: dict[str, Any] = {}
    if args.inputs:
        try:
            inputs_dict = json.loads(args.inputs)
            if not isinstance(inputs_dict, dict):
                _emit({"error": "--inputs must be a JSON object"}, args.format)
                return 1
        except json.JSONDecodeError as e:
            _emit({"error": f"Invalid JSON in --inputs: {e}"}, args.format)
            return 1

    # Render
    try:
        output = render(doc, inputs_dict, mode=args.mode)
        payload = {"output": output, "mode": args.mode}
        _emit(payload, args.format)
        return 0
    except RenderError as e:
        _emit({"error": f"Render error: {e}"}, args.format)
        return 1


def _cmd_explain(args: argparse.Namespace) -> int:
    """Handle explain subcommand."""
    doc, err = _load_doc(args.file)
    if err:
        _emit(err, args.format)
        return 1

    assert doc is not None

    # Check version
    ver_err = _check_version(doc, args.allow_future_version)
    if ver_err:
        _emit(ver_err, args.format)
        return 1

    # Gather explain data
    inputs_list = []
    if doc.inputs:
        for inp in doc.inputs:
            inputs_list.append(
                {
                    "name": inp.name,
                    "type": inp.type,
                    "required": inp.required,
                    "default": inp.default,
                }
            )

    outputs_list = []
    if doc.outputs:
        for out in doc.outputs:
            outputs_list.append(
                {
                    "name": out.name,
                    "type": out.type,
                    "required_when": out.required_when,
                }
            )

    phases_list = []
    runs_list = []
    refs_list = []

    # Normalize a dict from raw AST shape to model_dump() shape
    def _normalize_dict(d: dict[str, Any]) -> dict[str, Any]:
        """Hoist attrs.{skill,tool,bash,id,capture} to top-level keys."""
        if "attrs" in d:
            # Raw AST shape: {kind: "run", attrs: {skill: "..."}}
            normalized = {"kind": d["kind"]}
            attrs = d.get("attrs", {})
            # Hoist common attrs to top-level
            for key in ["skill", "tool", "bash", "id", "capture"]:
                if key in attrs:
                    normalized[key] = attrs[key]
            return normalized
        # Already normalized (model_dump() shape)
        return d

    # Walk all nodes to find phases, runs, and refs
    def _walk_node(node: Any) -> None:
        from promptc.schema import PhaseNode, RefNode, RunNode, WhenNode

        if isinstance(node, PhaseNode):
            phases_list.append(node.name)
            for child_dict in node.children:
                # Children are dicts from to_dict(), need to reconstruct
                kind = child_dict.get("kind")
                if kind == "run":
                    runs_list.append(_normalize_dict(child_dict))
                elif kind == "ref":
                    refs_list.append(_normalize_dict(child_dict))
                elif kind == "when":
                    # Recursively walk when children
                    when_children = child_dict.get("children", [])
                    for when_child in when_children:
                        if when_child.get("kind") == "run":
                            runs_list.append(_normalize_dict(when_child))
                        elif when_child.get("kind") == "ref":
                            refs_list.append(_normalize_dict(when_child))
        elif isinstance(node, WhenNode):
            for child_dict in node.children:
                kind = child_dict.get("kind")
                if kind == "run":
                    runs_list.append(_normalize_dict(child_dict))
                elif kind == "ref":
                    refs_list.append(child_dict)
        elif isinstance(node, RunNode):
            runs_list.append(node.model_dump())
        elif isinstance(node, RefNode):
            refs_list.append(node.model_dump())

    for node in doc.nodes:
        _walk_node(node)

    # Deduplicate and extract skills
    skills_set = set()
    for run in runs_list:
        skill = run.get("skill")
        if skill:
            skills_set.add(skill)

    payload = {
        "path": doc.path or "N/A",
        "tier": doc.tier,
        "doc_type": doc.meta.doc_type if doc.meta else None,
        "meta": {
            "description": doc.meta.description if doc.meta else None,
            "model": doc.meta.model if doc.meta else None,
            "owner": doc.meta.owner if doc.meta else None,
            "extras": doc.meta.extras if doc.meta else {},
        },
        "inputs": inputs_list,
        "outputs": outputs_list,
        "phases": phases_list,
        "runs": runs_list,
        "refs": refs_list,
        "skills": sorted(skills_set),
    }

    _emit(payload, args.format)
    return 0


def _cmd_parse(args: argparse.Namespace) -> int:
    """Handle parse subcommand."""
    doc, err = _load_doc(args.file)
    if err:
        _emit(err, args.format)
        return 1

    assert doc is not None

    # Check version
    ver_err = _check_version(doc, args.allow_future_version)
    if ver_err:
        _emit(ver_err, args.format)
        return 1

    # Read response file
    try:
        with open(args.response, "r") as f:
            response_text = f.read()
    except FileNotFoundError:
        _emit({"error": f"Response file not found: {args.response}"}, args.format)
        return 1
    except OSError as e:
        _emit({"error": f"Response file read error: {e}"}, args.format)
        return 1

    # Parse output
    try:
        result = contract.parse_output(response_text, doc.outputs or [])
        payload = result.model_dump()
        _emit(payload, args.format)
        # Exit 1 if there were parse errors
        return 0 if not result.errors else 1
    except Exception as e:
        _emit({"error": f"Parse error: {e}"}, args.format)
        return 1


def _build_parser() -> argparse.ArgumentParser:
    """Build the argument parser."""
    # Root parser with global flags
    root = argparse.ArgumentParser(
        prog="promptc",
        description="Prompt composition language compiler for Claude agents",
    )
    root.add_argument(
        "--format",
        choices=["json"],
        default=None,
        help="Output format (default: human-readable)",
    )
    root.add_argument(
        "--allow-future-version",
        action="store_true",
        help="Allow documents with version > 1",
    )

    subparsers = root.add_subparsers(dest="subcommand", required=True)

    # validate subcommand
    validate_parser = subparsers.add_parser(
        "validate",
        help="Validate a promptc document",
    )
    validate_parser.add_argument("file", help="Path to promptc document")

    # render subcommand
    render_parser = subparsers.add_parser(
        "render",
        help="Render a promptc document",
    )
    render_parser.add_argument("file", help="Path to promptc document")
    render_parser.add_argument(
        "--inputs",
        help="Input values as JSON object",
    )
    render_parser.add_argument(
        "--mode",
        choices=["a", "b"],
        default="a",
        help="Rendering mode: a (default, emit run instructions) or b (strip run blocks)",
    )

    # explain subcommand
    explain_parser = subparsers.add_parser(
        "explain",
        help="Explain a promptc document structure",
    )
    explain_parser.add_argument("file", help="Path to promptc document")

    # parse subcommand
    parse_parser = subparsers.add_parser(
        "parse",
        help="Parse LLM output against contract",
    )
    parse_parser.add_argument("file", help="Path to promptc document with output contract")
    parse_parser.add_argument(
        "--response",
        required=True,
        help="Path to LLM response file",
    )

    # migrate subcommand
    migrate_parser = subparsers.add_parser(
        "migrate",
        help="Migrate legacy command format to promptc",
    )
    migrate_parser.add_argument("file", help="Path to legacy command file")

    return root


def _cmd_migrate(args: argparse.Namespace) -> int:
    """Handle migrate subcommand: convert legacy command to promptc format.

    Reads a legacy command file and outputs the converted promptc format to stdout.
    The original file is never modified.

    Returns:
        0 on success (including warnings), 1 on error
    """
    try:
        result = migrate.migrate_file(args.file)
        print(result, end='')
        return 0
    except FileNotFoundError:
        print(f"Error: File not found: {args.file}", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"Error parsing frontmatter: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Error migrating file: {e}", file=sys.stderr)
        return 1


def main(argv: Optional[list[str]] = None) -> int:
    """Main entry point for promptc CLI.

    Args:
        argv: Command-line arguments (defaults to sys.argv[1:])

    Returns:
        Exit code (0 = success, 1 = error, 2 = usage error)
    """
    parser = _build_parser()

    try:
        args = parser.parse_args(argv)
    except SystemExit as e:
        # argparse raises SystemExit on parse errors (--help, invalid args)
        # Return 2 for usage errors, 0 for --help
        return e.code if isinstance(e.code, int) else 2

    # Dispatch to subcommand handler
    if args.subcommand == "validate":
        return _cmd_validate(args)
    elif args.subcommand == "render":
        return _cmd_render(args)
    elif args.subcommand == "explain":
        return _cmd_explain(args)
    elif args.subcommand == "parse":
        return _cmd_parse(args)
    elif args.subcommand == "migrate":
        return _cmd_migrate(args)
    else:
        # Should never reach here if subparsers required=True
        print(f"Unknown subcommand: {args.subcommand}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
