# promptc — Typed Prompt Contracts

**Status:** draft spec, pre-implementation
**Audience:** dag-executor integrators, external coding agents, skill authors
**Non-goals:** replacing markdown as a doc format; handling orchestration (DAG runtime owns that)

## Problem

Prompt files today mix five concerns (params, directives, variables, phase sequencing, prose) with no schema. Two consequences:

1. **Non-deterministic rendering.** Variable syntax varies per file; the same input can produce subtly different prompts across runs.
2. **Literal-string output parsing.** Consumers scan the LLM's free-text reply for markers like `DEPLOY_STATUS:` or `Verdict: APPROVED`. Any prose drift silently breaks the consumer.

`promptc` is the minimum layer that fixes both: a typed prompt file format with a deterministic renderer and a structured output parser. It ships as a portable skill so any coding agent can use it; dag-executor imports it as a library for `prompt` nodes.

## Scope

In scope:
- File format (Markdoc-flavored tags over markdown — **our own parser, no Markdoc dependency**)
- Tag schema (7 tags)
- Deterministic rendering: `(file, inputs) -> prompt_string`
- Structured output parsing: `(llm_response, contract) -> {outputs, errors}`
- CLI: `validate`, `render`, `explain`, `parse`
- Python library surface
- Handles **all prompt-adjacent files**: commands, skills, CLAUDE.md, reference docs. Anything the LLM reads benefits from validation and interpolation.

Out of scope:
- Phase orchestration (DAG YAML's job)
- Retry / loop semantics (DAG's job)
- Model selection / dispatch (dag-executor's `model_invocation`)
- Checkpoint resume (executor's job)

### Relationship to Markdoc

We use Markdoc-flavored **syntax** (`{% tag attr=val %}...{% /tag %}`) because it's familiar, well-specified, and tooling-friendly. We do **not** depend on the Markdoc package:

- Markdoc's reference implementation is TypeScript; we want a pure-Python, pip-installable library with no Node dependency
- Our tag schema is fixed and small (7 tags); Markdoc supports arbitrary user-defined tags + functions, which we don't need
- Our parser is ~200 lines because we skip ~85% of Markdoc's surface (React/HTML renderers, plugin pipeline, generic functions, framework adapters)
- Syntax compatibility is a free lift: authors and LLMs trained on Markdoc work with our files without retraining; IDE extensions for Markdoc highlight our files correctly

If Markdoc ever ships a first-class Python port, swapping in is low-risk — the grammar is compatible on purpose.

### Document tiers

Not every file needs a full contract. promptc recognizes three tiers, and the validator adjusts its strictness accordingly:

| Tier | What it is | Example files | Required tags |
|---|---|---|---|
| **Contract** | Executable prompts with typed I/O | `commands/validate-deploy-status.md`, `commands/audit.md` | `{% meta %}`, `{% output %}` (if the file is parsed for results) |
| **Mixed** | Prompt material that declares some metadata but no output contract | Command-invocable skills (`skills/domain-map/SKILL.md`), helper prompts | `{% meta %}` |
| **Reference** | Prose consumed by the LLM as context, no structured contract | `CLAUDE.md`, `skills/fly-operations.md`, `skills/checkpointing.md` | none — any tag is optional |

**Key properties:**
- `{% meta %}`, `{% input %}`, `{% output %}`, `{% phase %}` are all **optional**. Absence just means the doc is tier-2 or tier-3.
- `render(doc, inputs)` on a reference doc interpolates `{% $var %}` and returns the body; no contract append.
- `validate` applies the rules relevant to the doc's tier. A CLAUDE.md without `{% meta %}` is fine; a contract doc without `{% meta %}` fails.
- `{% ref file="..." include=true /%}` **inlines** the referenced doc's rendered content, enabling command files to pull in CLAUDE.md/skill docs as part of one render call. Without `include=true`, `{% ref %}` stays an inline link.

This makes promptc the one tool for every file the LLM reads — `promptc validate skills/` lints a reference doc the same way it lints a contract command, catching dangling `{% ref %}` targets, bad interpolation, and malformed frontmatter in CI regardless of tier.

## File format

Markdoc-flavored: markdown body plus `{% tag %}` elements. Parser is a ~200-line Python module, no Node dependency.

### The 7 tags

| Tag | Purpose | Block vs inline |
|---|---|---|
| `{% meta %}` | File-level metadata (tier, dispatch mode, parent command) | inline, exactly one per file |
| `{% input %}` | Typed input parameter declaration | inline, 0..N per file |
| `{% output %}` | Typed output field the LLM must emit | inline, 0..N per file |
| `{% phase %}` | Named phase block, wraps prose + sub-tags | block, nestable |
| `{% when %}` | Typed conditional gate (prose inside runs only if expr true) | block |
| `{% run %}` | Prescriptive tool/skill invocation with args | block |
| `{% ref %}` | Reference to another command/skill (validated at load time) | inline |

Variable interpolation: `{% $inputs.foo %}`, `{% $run_id.field %}`. One syntax. No `$VAR`, no `${VAR}`, no `{{ }}`.

### Tag reference

#### `{% meta %}`

```
{% meta
   doc_type="command" | "skill" | "reference"    # required when present; defaults by file location
   tier="local" | "haiku" | "sonnet" | "opus"    # optional, contract/mixed only
   dispatch="inline" | "agent" | "completion"    # optional, contract/mixed only
   parent_command="/validate"                     # optional
   version="1"                                    # optional, for future format evolution
/%}
```

At most one `{% meta %}` per file.

**Tier detection:**
- `{% meta %}` present + `{% output %}` declared → contract tier
- `{% meta %}` present + no `{% output %}` → mixed tier
- no `{% meta %}` → reference tier (CLAUDE.md, pure prose skills)

`doc_type` defaults based on file path if omitted (`commands/*` → `command`, `skills/*` → `skill`, otherwise `reference`). Explicit `doc_type` overrides the path heuristic.

#### `{% input %}`

```
{% input
   name="issue"
   type="string" | "int" | "bool" | "url" | "enum" | "json"
   required=true | false
   default="..."                  # optional
   pattern="^[A-Z]+-\\d+$"        # optional, strings only
   values=["a","b"]               # required if type=enum
   description="Jira issue key"
/%}
```

Rendering substitutes `{% $inputs.issue %}` with the provided input, validated against type/pattern/values before render. Missing required input → render fails.

#### `{% output %}`

```
{% output
   name="DEPLOY_STATUS"
   type="string" | "int" | "bool" | "enum" | "url" | "json"
   values=["DEPLOYED","FAILED",...]   # required if type=enum
   required=true | false
   required_when="OTHER_FIELD == 'x'"  # optional, conditional requirement
   description="Deployment result"
/%}
```

The contract. Parser extracts these fields from the LLM response and validates. Unrecognized fields in response → warning (configurable to error). Missing required → error.

**Emission convention:** the renderer appends an auto-generated "OUTPUT CONTRACT" block to the prompt so the LLM knows the shape. Authors don't hand-write the output block anymore.

#### `{% phase %}`

```
{% phase id="1"
         name="Load context"
         when="$inputs.mode == 'full'"   # optional, same grammar as {% when %}
%}
  prose + nested tags
{% /phase %}
```

Phases are purely organizational within a single prompt file. They are *not* executable units — that's the DAG runtime's job. Their role here is (a) visible structure for the LLM, (b) enabling `promptc explain` to list phases, (c) conditional inclusion via `when=`.

`id` must be unique within the file. `name` is free-form. `when=` is sugar for wrapping the phase body in `{% when %}`.

#### `{% when %}`

```
{% when expr="$inputs.mode == 'fast'" %}
  Skip phase 2.
{% /when %}
```

Expression grammar (subset of SimpleEval, matches DAG executor's gate syntax):
- Comparisons: `==`, `!=`, `<`, `<=`, `>`, `>=`
- Logical: `and`, `or`, `not`
- Membership: `in`
- Function calls: whitelisted only (`len`, `contains`, `startswith`, `matches`)
- Variable access: `$inputs.X`, `$outputs.X` (for `required_when`), literals

No arbitrary expressions. No side effects. Parse errors at validate time, not render time.

#### `{% run %}`

```
{% run id="fetch_issue"
       skill="issues/get_issue"
       capture="json" %}
  { "issue_key": "{% $inputs.issue %}", "fields": "status,labels" }
{% /run %}
```

Declarative invocation of a tool or skill. Attributes:
- `id` — bind result to `$fetch_issue` for downstream refs
- `skill` or `tool` or `bash` — exactly one, determines invocation shape
- `capture` — `json`, `text`, or `lines`
- `timeout_ms` — optional

**Important:** `promptc` does not *execute* `{% run %}` blocks. It renders them into the prompt as instruction-to-the-LLM, OR the DAG runtime lifts them into real executor nodes. Which of those depends on the caller — see "Integration modes" below.

**Mode-A rendering shape:** the renderer emits the block as a fenced bash command followed by a capture-binding sentence. For the example above:

    Call the issues/get_issue skill:
    ```bash
    npx tsx ~/.claude/skills/issues/get_issue.ts '{"issue_key":"GW-5189","fields":"status,labels"}'
    ```
    Capture the JSON output and bind it as `$fetch_issue`. Downstream references like `$fetch_issue.status` refer to fields of that captured object.

This matches what today's prompt files already do, so LLM behavior is unchanged from the current baseline.

#### `{% ref %}`

```
{% ref command="/create-implementation-plan" /%}
{% ref skill="promptc/parse" /%}
{% ref file="CLAUDE.md" include=true /%}
```

Validate-time reference check. If the target doesn't exist, `promptc validate` fails.

Rendering modes:
- **Link mode (default):** renders as an inline markdown link to the target doc. The LLM sees a reference; it does not inline content.
- **Include mode (`include=true`):** loads the target file through `promptc.load()`, renders it (recursively, with the same input context), and inlines the rendered body at this position. Enables command files to compose CLAUDE.md + skill docs into one prompt without manual concatenation.

Include mode attributes:
- `file="path"` — path relative to project root. Only form that supports `include=true`.
- Cycles are detected at load time and cause a validate error.
- Max include depth is 3 (configurable via `promptc.config`). Prevents runaway composition.
- Included docs inherit the caller's input context but **cannot** access their outputs (include is a pre-render operation; outputs are post-LLM).

## Rendering semantics

`promptc.render(path, inputs: dict) -> str` is a **pure function**.

Algorithm:
1. Parse file → AST.
2. Validate AST against tag schema (fail fast on structural errors, strictness adjusted for tier).
3. Type-check inputs against `{% input %}` declarations (fail fast). Reference-tier docs with no declared inputs accept any context and do not validate.
4. Walk AST:
   - `{% meta %}` → stripped from output, exposed as metadata on result.
   - `{% input %}` / `{% output %}` → stripped from body (described in appended contract block if contract tier).
   - `{% phase %}` → rendered as `## Phase {id}: {name}` heading + body.
   - `{% when %}` → body rendered only if expression true.
   - `{% run %}` → rendered as a fenced block with its invocation + the LLM instruction "execute and bind to `${id}`".
   - `{% ref ... /%}` → rendered as markdown link.
   - `{% ref file=... include=true /%}` → recursively loads and renders the target, inlines the body.
   - `{% $inputs.X %}` / `{% $id.field %}` → string-substituted.
5. **Contract tier only:** append auto-generated OUTPUT CONTRACT section listing every `{% output %}` declaration with type/constraints. Mixed and reference tiers skip this.
6. Return prompt string.

Determinism: same file + same inputs + same promptc version = byte-identical output. No timestamps, no random keys, no dict-ordering bugs. Include cycles fail loudly at step 4 rather than producing nondeterministic output.

## Output parsing semantics

`promptc.parse_output(text: str, contract: Contract) -> ParseResult`

Contract is extracted from the source file's `{% output %}` declarations.

Parse strategy:
1. Prefer structured: if the LLM response contains a JSON block and every contract field is present in it, use that.
2. Fall back to line-scan: match `FIELD: value` pairs (declared field names only, case-sensitive).
3. Validate each extracted value against its declared type/enum/pattern.
4. Evaluate `required_when` expressions against already-extracted values.
5. Return:

```python
@dataclass
class ParseResult:
    fields: dict[str, Any]      # successfully extracted, type-coerced
    errors: list[ParseError]    # required-missing, type-mismatch, enum-invalid
    warnings: list[str]         # unknown fields, etc.
    raw: str                    # original response for debugging
```

**Error handling:** `parse_output` always returns a `ParseResult`. Errors are data, never exceptions. The caller decides how to react — dag-executor may retry with a reminder prompt; a CLI user may exit nonzero; a test may assert against the `errors` list. Keeping the library free of retry/escalation logic is deliberate — that's orchestration, and orchestration lives in the DAG runtime.

This is the single highest-leverage function in the library — it replaces N ad-hoc line-scanners with one typed parser.

## CLI surface

```
promptc validate <file|dir>       # schema + lint, exit nonzero on errors
promptc render <file> --inputs '{"issue":"GW-5189"}'    # print prompt
promptc explain <file>            # human-readable contract summary
promptc parse <file> --response response.txt            # apply contract to captured LLM output
```

All commands support `--format json` for machine consumption.

## Library surface

```python
from promptc import load, render, parse_output, Contract, ParseResult

doc = load("commands/validate-deploy-status.md")
doc.meta.tier            # "local"
doc.inputs               # list of InputDecl
doc.outputs              # list of OutputDecl (= Contract)
doc.phases               # list of phase ids
doc.refs                 # list of (kind, target) tuples

prompt_str = render(doc, inputs={"issue": "GW-5189"})
result = parse_output(llm_response, doc.outputs)
```

Also:
```python
doc = load_str(markdown_text)   # for non-file callers
```

## Integration modes

Two ways callers use promptc:

### Mode A: "render-only" (most agents, Claude Code, humans)
Call `render()`, send the string to an LLM, call `parse_output()` on the response. `{% run %}` blocks render as *instructions* — the LLM executes them as tool calls or bash.

### Mode B: "DAG-lifted" (dag-executor)
The executor's `prompt` node config gains `prompt_file: path/to.md` and `inputs: {...}`. Before invoking the model, the executor:
1. `load()`s the file
2. Extracts `{% run %}` blocks and hoists them into *separate executor nodes* with real `depends_on` edges
3. `render()`s the remaining prompt
4. Invokes the model via existing `model_invocation.py`
5. `parse_output()`s the result, writes fields into state channels

This is optional and additive — mode A works without it.

## Validation rules (`promptc validate`)

Validation is **tier-aware** — a rule that blocks a contract doc may be a no-op for a reference doc. Below, rules marked *[C]* apply only to contract tier; *[M]* to contract + mixed; unmarked rules apply to every tier.

Errors (exit nonzero):
- *[C]* No `{% meta %}` tag
- *[C]* Contract tier doc with no `{% output %}` declarations (use mixed tier if no outputs needed)
- *[M]* `{% meta %}` present but required attributes missing
- Duplicate `name` across `{% input %}` or `{% output %}`
- Duplicate `id` across `{% phase %}` or `{% run %}`
- `{% $inputs.X %}` reference with no matching `{% input %}` (in any tier that declares `{% input %}`)
- `{% $id.field %}` reference with no matching `{% run id=... %}`
- `{% when expr="..." %}` with invalid expression
- `{% run skill="..." %}` where skill doesn't resolve
- `{% ref command="..." %}` / `{% ref skill="..." %}` / `{% ref file="..." %}` where target doesn't exist
- `{% ref ... include=true %}` with cyclic inclusion or depth > 3
- Missing required attribute on any tag
- Input type=enum with no `values`
- Output type=enum with no `values`

Warnings:
- *[C]* `{% output %}` declared but never mentioned in prose (LLM may not know to emit it)
- `{% input %}` declared but never referenced in body
- Phase with no body
- `{% when %}` with constant expression (always true / always false)
- Reference-tier doc using `{% $inputs.X %}` without any declared `{% input %}` (ambiguous — the context it runs in must provide that variable, which is untyped)

## File layout

```
packages/promptc/
  pyproject.toml
  src/promptc/
    __init__.py           # public API: load, render, parse_output
    parser.py             # tag parser (~200 lines, regular grammar)
    schema.py             # tag schemas (pydantic or dataclass)
    expression.py         # SimpleEval-compatible expr evaluator
    renderer.py           # AST → prompt string
    contract.py           # parse_output + ParseResult
    cli.py                # promptc command
  tests/
    test_parser.py
    test_renderer.py
    test_contract.py
    fixtures/
      validate-deploy-status.md
      audit.md
skills/promptc/
  SKILL.md                # thin wrapper exposing the CLI to agents
```

Ships as a Python package (pip-installable) AND as a skill directory (portable to any agent).

## Dependencies

Target: **stdlib + pydantic v2 only.** No Node, no PyYAML (we use JSON for routing config), no regex engine beyond `re`. Pydantic is already a dag-executor dep, so this adds nothing new to that consumer.

The expression evaluator is a vendored copy of the subset of `dag_executor/variables.py` that handles gate expressions (~50 lines). Not imported — copied — so that `promptc` has no dependency on `dag-executor` and remains usable by any agent that `pip install promptc`s it. If the DAG team extends their evaluator, we mirror changes manually; the grammar is small enough that drift risk is low.

## Phased delivery

1. **Parser + renderer** (`load`, `render`). Validates format, renders prompt strings. No output parsing yet.
2. **Contract parser** (`parse_output`). The high-leverage piece. Replaces line-scanning.
3. **CLI + `validate`/`explain`**. Makes it usable standalone.
4. **DAG integration** (mode B). `prompt_file:` support in executor, `{% run %}` hoisting.
5. **Migration tool**. `promptc migrate <old.md>` best-effort conversion from current format.

Phases 1–3 are the MVP. 4 is additive. 5 is optional — can be done by hand for the ~30 files that matter.

## Decisions locked in

- **Deps:** pydantic v2 + stdlib. No dataclasses-only path.
- **Expression evaluator:** vendored copy of the dag-executor subset, ~50 lines. No cross-package import.
- **`{% run %}` mode-A rendering:** fenced bash block + standard "capture as `$id`" binding sentence. Matches current prompt-file shape; unchanged LLM behavior.
- **`{% phase when=... %}`:** supported as sugar for wrapping the phase body in `{% when %}`.
- **Escape hatch:** `{% raw %}...{% endraw %}` (Jinja convention).
- **Format versioning:** strict reject on unknown `{% meta version= %}`; CLI has `--allow-future-version` escape flag for emergencies. v0 defaults to `version=1`.
- **`parse_output` errors:** always returned as data on `ParseResult`. Never raised. Retry/escalation is caller responsibility.

## Success criteria

- `validate-deploy-status.md` round-trips: rewritten in new format, `render()` produces a prompt an LLM can follow, `parse_output()` extracts all declared fields from a real Bedrock response.
- `promptc validate` catches every class of error in the validation rules list above against hand-crafted bad fixtures.
- Integrated into one real `prompt` node in a DAG workflow and runs end-to-end.
- Installable as a skill (`skills/promptc/SKILL.md` + vendored Python) and usable from Claude Code without the DAG runtime present.
- A real CLAUDE.md renders through promptc as a reference-tier doc without requiring frontmatter, and a command doc can `{% ref file="CLAUDE.md" include=true /%}` to inline it.
- `promptc validate skills/` passes against the current tree with zero modifications beyond path-based tier inference (reference tier is the permissive default).
