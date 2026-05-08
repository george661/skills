---
name: promptc
description: Validate, render, explain, and parse promptc contract documents. CLI wrapper for agent integration.
---

# Promptc Contract Compiler Skill

## Purpose

Promptc is a contract compiler that validates, renders, and parses LLM interaction contracts. This skill provides a CLI interface for agents to work with promptc documents without requiring DAG runtime dependencies.

## Architecture Decision

**Shim vs. Symlink:** This skill uses a thin shell shim (`skills/promptc/promptc`) that `exec`s the installed `promptc` binary rather than symlinking source code. This approach was validated via spike testing:

```bash
# Spike verification (completed during planning)
python3 -m venv /tmp/promptc-spike-venv
source /tmp/promptc-spike-venv/bin/activate
uv pip install packages/promptc
which promptc  # → /tmp/promptc-spike-venv/bin/promptc
promptc --help  # works with zero dag_executor imports
```

The shim makes the skill directory self-contained for agents that invoke commands by skill-relative paths (e.g., `./skills/promptc/promptc validate file.md`) while avoiding source duplication. The promptc package is installed via `pip install packages/promptc` in CI and agent environments.

## Installation

Before using this skill, ensure promptc is installed:

```bash
# From the skills repo root
uv pip install -e packages/promptc[dev]

# Or for production use
uv pip install packages/promptc
```

## Subcommands

### validate

Validate a promptc document for syntax errors, semantic issues, and schema compliance.

**Usage:**
```bash
promptc validate <file>
```

**Examples:**
```bash
# Validate a contract document
promptc validate commands/analyze-logs.md

# Validate this skill's documentation
promptc validate skills/promptc/SKILL.md

# Validate an example contract
promptc validate skills/promptc/examples/contract.md
```

**Exit codes:**
- `0`: Validation passed (no errors)
- `1`: Validation failed (syntax or semantic errors)

**Output format:**
- Default: human-readable text with issue list
- JSON: Use `--format=json` for machine-parseable output

### render

Render a promptc contract by substituting input variables and expanding conditional sections.

**Usage:**
```bash
promptc render <file> [--inputs <json>]
```

**Examples:**
```bash
# Render with default inputs
promptc render commands/analyze-logs.md

# Render with custom inputs (JSON)
promptc render commands/analyze-logs.md --inputs '{"log_file": "errors.log", "severity": "ERROR"}'

# Pipe to file
promptc render commands/analyze-logs.md --inputs '{"format": "json"}' > rendered-contract.md
```

**Exit codes:**
- `0`: Rendering succeeded
- `1`: Rendering failed (missing required inputs, syntax error, etc.)

**Output format:**
- Default: rendered contract text (stdout)
- Use `--format=json` for structured output with metadata

### explain

Explain the structure and metadata of a promptc document without rendering it.

**Usage:**
```bash
promptc explain <file>
```

**Examples:**
```bash
# Show contract structure
promptc explain commands/analyze-logs.md

# See tier classification
promptc explain skills/promptc/SKILL.md

# Inspect inputs/outputs
promptc explain skills/promptc/examples/contract.md
```

**Exit codes:**
- `0`: Explanation generated
- `1`: File not found or parse error

**Output includes:**
- Path, tier, document type
- Meta block (description, model, owner)
- Inputs (name, type, required, defaults)
- Outputs (name, type, required_when)
- Phases (execution phase names)
- Runs (skill invocations)

### parse

Parse LLM output against a contract's output schema, validating structure and extracting typed data.

**Usage:**
```bash
promptc parse <file> <llm-output>
```

**Examples:**
```bash
# Parse LLM response against contract
promptc parse commands/analyze-logs.md "Found 3 errors: [...]"

# Parse from file
promptc parse commands/analyze-logs.md "$(cat llm-response.txt)"

# JSON mode for programmatic use
promptc parse commands/analyze-logs.md "result" --format=json
```

**Exit codes:**
- `0`: Parsing succeeded (output matches schema)
- `1`: Parsing failed (schema mismatch or invalid output)

**Output format:**
- Default: validation status + extracted fields
- JSON: structured parse result with field values

## Pre-requisites

- Python 3.9+ environment with promptc installed
- Run from skills repo root or use the shim: `./skills/promptc/promptc <subcommand>`
- Documents must follow promptc syntax (see `packages/promptc/README.md` for spec)

## Common Workflows

**Agent contract validation before execution:**
```bash
# 1. Validate the contract
promptc validate commands/my-command.md || exit 1

# 2. Explain to understand inputs
promptc explain commands/my-command.md

# 3. Render with actual inputs
promptc render commands/my-command.md --inputs '{"key": "value"}'
```

**CI/CD integration:**
```bash
# Validate all contracts in CI
find commands skills docs -name '*.md' -exec promptc validate {} \;
```

**LLM output validation:**
```bash
# After LLM execution, parse output against contract
llm_response=$(some_llm_call)
promptc parse commands/my-command.md "$llm_response" --format=json
```

## Related

- Promptc package: `packages/promptc/`
- Promptc syntax spec: `packages/promptc/README.md`
- CI validation: `.github/workflows/` (promptc-validate job)
- Domain map skill: `skills/domain-map/SKILL.md` (similar portable skill pattern)
