# promptc

Prompt composition language compiler for Claude agents.

## Overview

`promptc` is a Python library for composing, rendering, and validating structured prompts using a markdown-based templating language. It compiles `.md` files containing special `{% %}` tags into runtime prompts, handles variable substitution, and parses LLM responses against declared output contracts.

**Target users:**
- **dag-executor**: The primary consumer — uses `promptc` to load skill contracts, render prompts with runtime inputs, and parse assistant replies.
- **External agents**: Any Python-based agent that wants contract-first prompting with type-safe output parsing.
- **Skill authors**: Write skills as markdown files with structured inputs/outputs rather than string concatenation.

`promptc` compiles three document tiers: **contract** (input + output declarations only), **mixed** (contract + reference prose), and **reference** (no contract). See [Document Tiers](#document-tiers) for details.

For the full specification and design rationale, see [`docs/promptc-spec.md`](../../docs/promptc-spec.md).

## Installation

From the skills repository root:

```bash
pip install -e packages/promptc
```

**Development extras** (includes pytest, ruff, mypy):

```bash
pip install -e "packages/promptc[dev]"
```

**Requirements:**
- Python >= 3.9
- Runtime dependency: pydantic v2

## Quickstart

Create a simple contract file `greeting.md`:

```markdown
{% meta tier="contract" %}

{% input %}
name: string

{% output %}
greeting: string
message: string
```

Load, render, and parse:

```python
from promptc import load, render, parse_output

# Load the contract
doc = load("greeting.md")

# Render with inputs
prompt = render(doc, {"name": "Alice"})
# Send 'prompt' to your LLM...

# Parse the LLM response
response = """
greeting: Hello
message: Welcome to promptc, Alice!
"""

result = parse_output(response, doc.output.fields)

if result.errors:
    print(f"Parse errors: {result.errors}")
else:
    print(f"Greeting: {result.fields['greeting']}")
    print(f"Message: {result.fields['message']}")
```

## Document Tiers

`promptc` supports three document tiers (set via `{% meta tier="..." %}`):

| Tier | Description |
|------|-------------|
| **contract** | Input and output declarations only; no reference prose. Suitable for production skills. |
| **mixed** | Contract + reference prose. Skill documentation lives alongside the contract. |
| **reference** | No input/output declarations. Pure documentation (e.g., architecture docs). |

For full tier semantics and validation rules, see [`docs/promptc-spec.md`](../../docs/promptc-spec.md).

## Tag Reference

`promptc` provides seven special tags for declaring contract structure:

| Tag | Purpose |
|-----|---------|
| `{% meta %}` | Document metadata (tier, version, dependencies) |
| `{% input %}` | Declare input fields with types and defaults |
| `{% output %}` | Declare expected output fields from LLM responses |
| `{% phase name="..." %}` | Multi-phase prompts (render phases sequentially) |
| `{% run path="..." %}` | Include and render another contract at runtime |
| `{% ref path="..." %}` | Static reference to another contract (for validation only) |
| `{% when expr %}` | Conditional content based on input values |

For detailed tag syntax and semantics, see [`docs/promptc-spec.md`](../../docs/promptc-spec.md).

## CLI

**Status:** Stub (implementation tracked in GW-5482)

The CLI is currently a placeholder. Running `python -m promptc` will print:

```
promptc CLI not implemented yet — see GW-5475 for roadmap
```

And exit with code 2.

**Planned verbs** (when implemented):
- `validate` — check contract syntax and references
- `render` — render a contract with inputs to stdout
- `explain` — show parsed AST and metadata
- `parse` — parse an LLM response against an output contract

## Library API

### Loading and Parsing

```python
from promptc import load, parse, parse_str

# Load and compile a .md file (returns Doc with metadata, input, output, AST)
doc = load("path/to/contract.md")

# Parse raw markdown text into AST (returns Node tree)
ast = parse("path/to/contract.md")

# Parse markdown string (optional path for error reporting)
ast = parse_str(markdown_text, path="<inline>")
```

### Rendering

```python
from promptc import render

# Render a Doc with input values
prompt_text = render(doc, inputs={"name": "Alice", "count": 42})
```

**Note:** `render()` resolves `{% run %}` references, evaluates `{% when %}` gates, and substitutes input variables.

### Output Contract Parsing

```python
from promptc import parse_output, ParserConfig

# Parse LLM response against output contract
result = parse_output(
    text=assistant_response,
    contract=doc.output.fields,
    config=ParserConfig(regex_timeout_ms=500)  # optional
)

# result is a ContractParseResult with:
# - fields: dict[str, Any] — successfully extracted values
# - errors: list[ParseErrorInfo] — validation failures
# - warnings: list[str] — non-fatal issues
# - raw: str — original response text
# - strategy: "json" | "line-scan" | "none"
```

**Contract guarantee:** `parse_output()` **never raises** — all errors are returned as data in `result.errors`.

### Expression Evaluation

```python
from promptc import evaluate

# Evaluate gate expressions (used by {% when %} internally)
result = evaluate("count > 10 and name != ''", {"count": 5, "name": "Alice"})
# Returns False
```

### Schema Models

`promptc` exports schema models for working with parsed contracts:

- **`Doc`**: Compiled contract document (metadata, input, output, AST)
- **`MetaDecl`**: Metadata declaration (`tier`, `version`, `dependencies`)
- **`InputDecl`**: Input field declaration (`name`, `type`, `default`, `required_when`)
- **`OutputDecl`**: Output field declaration (`name`, `type`, `values` for enums, `pattern`)
- **`ParseResult`**: Result from parsing markdown (AST root node)
- **`ContractParseResult`**: Result from `parse_output()` (see below)
- **`ParseErrorInfo`**: Error detail (code, field, message)
- **`ValidationIssue`**: Contract validation issue (for pre-render checks)
- **`ValidationReport`**: Collection of validation issues

**AST node types** (from `parse()` / `parse_str()`):

- **`Node`**: Base AST node
- **`PhaseNode`**, **`RunNode`**, **`RefNode`**, **`WhenNode`**, **`TextNode`**, **`RawNode`**: Specific node types

**Configuration:**

- **`ParserConfig`**: Parser limits and timeouts (`max_tags_per_file`, `max_ast_nodes`, `regex_timeout_ms`)

**Errors:**

- **`ParseError`**: Markdown syntax error (line/column info)
- **`RenderError`**: Runtime rendering failure (missing input, cycle detection)
- **`LimitExceededError`**: Document exceeded configured limits
- **`TimeoutError`**: Regex validation exceeded timeout
- **`ExpressionError`**: Gate expression evaluation failure

## ParseResult and Error Handling

### ContractParseResult

`parse_output()` returns a `ContractParseResult` with the following fields:

```python
class ContractParseResult:
    fields: dict[str, Any]          # Extracted and type-coerced outputs
    errors: list[ParseErrorInfo]    # Validation failures
    warnings: list[str]             # Non-fatal issues
    raw: str                        # Original response text (for debugging)
    strategy: Literal["json", "line-scan", "none"]
```

**Strategy values:**

- **`"json"`**: A fenced JSON block covered all contract fields (JSON-first succeeded)
- **`"line-scan"`**: No complete JSON block; used regex line-scan fallback (`FIELDNAME: value`)
- **`"none"`**: No JSON and no line-scan matches; all fields missing

### Error Codes

Errors in `ContractParseResult.errors` use the following codes:

| Code | Description |
|------|-------------|
| `required_missing` | Required field missing from response |
| `type_mismatch` | Value cannot be coerced to declared type |
| `enum_invalid` | Value not in declared enum values |
| `contract_error` | Contract definition issue (e.g., `type=enum` without `values`) |
| `pattern_mismatch` | String value doesn't match declared regex pattern |
| `regex_timeout` | Pattern validation exceeded timeout (ReDoS protection) |
| `expression_error` | `required_when` expression failed to evaluate (becomes **warning**, not error) |

### JSON-First vs Line-Scan Fallback

`parse_output()` uses a two-stage extraction strategy:

1. **JSON-first:** Search for fenced JSON blocks (` ```json ... ``` `) that contain **all** declared contract fields. If a complete match is found, extract from JSON.
2. **Line-scan fallback:** If no JSON block covers the contract, scan for line-based patterns like `FIELDNAME: value`.

**Mixed responses** (JSON block present but incomplete):
- If a JSON block exists but doesn't contain all contract fields, promptc **ignores the JSON block** and falls back to line-scan.
- A warning is added to `ContractParseResult.warnings`: `"JSON block present but incomplete; fallback to line-scan"`

This prevents partial JSON extraction from causing silent data loss.

### Never-Raises Contract

`parse_output()` **never raises exceptions**. All errors (missing fields, type mismatches, regex timeouts) are returned as structured data in `ContractParseResult.errors`.

This allows callers to implement their own error-handling strategies (retry, fail-fast, partial acceptance, etc.).

## Caller Integration Examples

### Example 1: Retry-Driven Consumer (dag-executor)

The dag-executor uses a retry loop — if `parse_output()` returns errors, it builds a reminder prompt and retries the LLM call.

```python
from promptc import load, render, parse_output

doc = load("skill.md")
inputs = {"query": "explain photosynthesis"}
max_retries = 3

for attempt in range(max_retries):
    # Render prompt (include reminder on retry)
    if attempt == 0:
        prompt = render(doc, inputs)
    else:
        # Build reminder from previous errors
        reminder = "Previous response had errors:\n"
        for err in result.errors:
            reminder += f"- {err.field}: {err.message} (code: {err.code})\n"
        reminder += "\nPlease provide all required fields."
        prompt = render(doc, inputs) + "\n\n" + reminder

    # Call LLM (omitted — assume 'assistant_response' is returned)
    assistant_response = call_llm(prompt)

    # Parse response
    result = parse_output(assistant_response, doc.output.fields)

    if not result.errors:
        # Success — use result.fields
        print("Success:", result.fields)
        break
    elif attempt == max_retries - 1:
        # Final attempt failed
        print("Failed after retries:", result.errors)
```

### Example 2: Fail-Fast Consumer (CLI)

A command-line tool that parses an LLM response and exits immediately on error.

```python
import sys
import json
from promptc import load, parse_output

doc = load("task.md")

# Read LLM response from stdin or file
response = sys.stdin.read()

# Parse against contract
result = parse_output(response, doc.output.fields)

if result.errors:
    # Fail-fast: print errors and exit
    print("Error: Response did not match output contract", file=sys.stderr)
    for err in result.errors:
        print(f"  - {err.field}: {err.message} (code: {err.code})", file=sys.stderr)
    sys.exit(1)

# Success: write JSON to stdout
print(json.dumps(result.fields, indent=2))
sys.exit(0)
```

## Links

- **Canonical specification:** [`docs/promptc-spec.md`](../../docs/promptc-spec.md)
- **Parent PRP:** PRP-PLAT-011 (PromptC Language Design)
- **Repository:** [george661/skills](https://github.com/george661/skills)
