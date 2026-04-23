# dag-executor

DAG-based workflow executor for Claude agents. Defines workflows as YAML DAGs with layer-parallel execution, file-based checkpointing, state channels, human-in-the-loop interrupts, and structured event streaming.

Replaces ad-hoc markdown command sequencing with machine-enforced orchestration: deterministic node ordering, content-addressed cache skipping, and pre-flight validation that catches errors before execution starts.

## Quick Start

```bash
pip install -e packages/dag-executor
```

```bash
# Validate a workflow
dag-exec --dry-run workflow.yaml

# Execute a workflow
dag-exec workflow.yaml user_id=U123 dry_run=false

# Resume from interrupt
dag-exec workflow.yaml --resume --run-id abc123 \
  --resume-values '{"approval_decision": true}'

# Stream execution events to stderr
dag-exec workflow.yaml --stream user_id=U123
```

## YAML Workflow Format

```yaml
name: deploy-pipeline
config:
  checkpoint_prefix: .dag-checkpoints
  worktree: true
  labels:
    on_failure: workflow-failed
  on_exit:
    - id: cleanup
      type: bash
      script: "rm -rf /tmp/work"
      run_on: [completed, failed]

inputs:
  repo_url:
    type: string
    required: true
  dry_run:
    type: boolean
    required: false
    default: false

state:
  messages:
    type: list
    reducer: append
    default: []
  best_score:
    type: float
    reducer:
      strategy: max
  status:
    type: string

nodes:
  - id: fetch
    name: Fetch Repository
    type: bash
    script: git clone "$REPO_URL" /tmp/work
    checkpoint: true

  - id: analyze
    name: Analyze Code
    type: skill
    depends_on: [fetch]
    skill: "/skills/analyze/code-review.skill.md"
    params:
      path: /tmp/work
    output_format: json
    retry:
      max_attempts: 2
      delay_ms: 1000

  - id: review
    name: Review Results
    type: prompt
    depends_on: [analyze]
    prompt: "Review: {{ nodes.analyze.output }}"
    model: sonnet
    dispatch: inline
    edges:
      - target: deploy
        condition: review.verdict == "approve"
      - target: fix
        condition: review.verdict == "revise"
      - target: escalate
        default: true

  - id: deploy
    name: Deploy
    type: command
    command: deploy
    args: ["--env", "prod"]
    when: "dry_run == false"
    trigger_rule: all_success

  - id: approval
    name: Human Approval
    type: interrupt
    depends_on: [review]
    message: "Approve deployment?"
    resume_key: approval_decision
    timeout: 7200

  - id: gate
    name: Check Approval
    type: gate
    depends_on: [approval]
    condition: "approval_decision == true"

outputs:
  review_result:
    node: review
  deploy_status:
    node: deploy
    field: exit_code
```

## Node Types

| Type | Purpose | Key Fields |
|------|---------|------------|
| `skill` | Execute a `.skill.md` file | `skill`, `params`, `output_format` |
| `bash` | Run inline shell script | `script` |
| `command` | Invoke external command | `command`, `args` |
| `prompt` | LLM prompt via Claude Code | `prompt`/`prompt_file`, `model`, `dispatch` |
| `gate` | Evaluate a boolean condition | `condition` |
| `interrupt` | Pause for human input | `message`, `resume_key`, `timeout` |

## Node Configuration

Every node supports these optional fields:

| Field | Type | Purpose |
|-------|------|---------|
| `depends_on` | `list[str]` | Node IDs that must complete first |
| `edges` | `list[EdgeDef]` | Conditional routing to downstream nodes |
| `when` | `str` | Skip condition (node runs only if expression is true) |
| `trigger_rule` | `all_success` / `one_success` / `all_done` | When to trigger based on upstream results |
| `on_failure` | `stop` / `continue` / `skip_downstream` | Failure behavior |
| `retry` | `RetryConfig` | Retry on failure (`max_attempts`, `delay_ms`, `retry_on`) |
| `timeout` | `int` | Seconds before timeout (defaults vary by type) |
| `checkpoint` | `bool` | Enable content-addressed checkpointing |
| `output_format` | `json` / `text` / `yaml` | Parse node output |
| `reads` | `list[str]` | State channels or inputs this node reads |
| `writes` | `list[str]` | State channels this node writes to |

## Prompt Node Output Contract

Prompt nodes produce output dictionaries with behavior determined by `output_format` and `writes`:

### Default Behavior (`output_format: text`)

By default, the full LLM response text is stored in the `response` key:

```yaml
nodes:
  - id: prompt1
    type: prompt
    prompt: "What is 2+2?"
    output_format: text
```

**Output:** `{"response": "The answer is 4"}`

### JSON Mode (`output_format: json`)

When `output_format: json` is set, the runner parses the LLM output as JSON and spreads parsed fields into the output dictionary, while preserving the raw response text:

```yaml
nodes:
  - id: prompt1
    type: prompt
    prompt: "Generate JSON with result and count fields"
    output_format: json
```

If the LLM responds with `{"result": "success", "count": 42}`, the node output becomes:

**Output:** `{"result": "success", "count": 42, "response": "{\"result\": \"success\", \"count\": 42}"}`

- Parsed fields (`result`, `count`) are spread into the output dictionary
- The raw JSON string is preserved in `response` for backward compatibility
- If the LLM output contains a `response` key, it is overwritten by the raw text

### State Writes (`writes: [key, ...]`)

The `writes` field declares which state channels the node populates. For each key in `writes`:

- **In text mode:** the key is populated with the full response text
- **In JSON mode:** the key is populated with the corresponding parsed field (if it exists), otherwise the full response text

```yaml
state:
  result:
    type: channel
    default: null

nodes:
  - id: prompt1
    type: prompt
    prompt: "What is 2+2?"
    output_format: text
    writes:
      - result
```

**Output:** `{"response": "The answer is 4", "result": "The answer is 4"}`  
**State:** `state.result = "The answer is 4"`

For JSON mode with writes:

```yaml
state:
  result:
    type: channel
    default: null

nodes:
  - id: prompt1
    type: prompt
    prompt: "Generate JSON"
    output_format: json
    writes:
      - result
```

If the LLM responds with `{"result": "success", "count": 42}`:

**Output:** `{"result": "success", "count": 42, "response": "{...}"}`  
**State:** `state.result = "success"` (the parsed `result` field, not the full text)

This enables downstream nodes to reference `state.result` for fan-out writes.

## Execution Model

The executor uses Kahn's algorithm to sort nodes into parallel layers:

```
Layer 0: [fetch]           # No dependencies — runs first
Layer 1: [analyze, lint]   # Both depend only on fetch — run in parallel
Layer 2: [review]          # Depends on analyze and lint
Layer 3: [deploy]          # Depends on review
```

Within each layer, nodes execute concurrently up to `--concurrency` (default 10). Layers execute sequentially. Cycles are detected at load time.

**Content-addressed caching**: When checkpointing is enabled, completed nodes are skipped on re-run if their input hash matches. This makes resume and replay efficient.

**Default timeouts** (seconds): prompt=300, command=300, bash=60, skill=60, gate=30.

## Variable Substitution

Reference upstream outputs and workflow inputs in any string field:

```yaml
prompt: "Summarize: {{ nodes.fetch-user.output }}"
args: ["--id", "$input-user_id"]
script: echo "$FETCH_USER_OUTPUT"
```

Syntax: `{{ nodes.<node-id>.output[.field] }}` or `$<node-id>.<field>` or `$input-<name>`. Bash nodes also receive upstream outputs as environment variables.

## State Channels

Channels manage shared state across nodes (inspired by LangGraph). Declare them in the `state:` block:

```yaml
state:
  messages:
    type: list
    reducer: append      # Fold parallel writes
    default: []
  best_score:
    type: float
    reducer:
      strategy: max
  status:
    type: string         # No reducer = LastValueChannel (conflicts on parallel write)
```

**Reducer strategies**: `overwrite`, `append`, `extend`, `max`, `min`, `merge_dict`, `custom`.

Custom reducers load a Python function by dotted path:

```yaml
reducer:
  strategy: custom
  custom_function: mypackage.reducers.merge_scores
```

## Conditional Edges

Route execution dynamically based on node output:

```yaml
- id: review
  type: bash
  script: 'echo ''{"verdict": "approve"}'''
  output_format: json
  edges:
    - target: merge
      condition: review.verdict == "approve"
    - target: fix_pr
      condition: review.verdict == "revise"
    - target: escalate
      default: true
```

Exactly one `default: true` edge is required. Conditions are evaluated with `simpleeval`.

## Checkpointing & Resume

File-based checkpoint store persists workflow state:

```
.dag-checkpoints/<workflow-name>-<run-id>/
  meta.json              # Workflow metadata, inputs, status
  nodes/
    <node-id>.json       # Per-node output, status, content hash
  interrupt.json         # Present when paused at interrupt node
  events.jsonl           # Structured execution log
```

Resume a paused workflow:

```bash
dag-exec workflow.yaml --resume --run-id abc123 \
  --resume-values '{"approval_decision": true}'
```

Replay from a specific node (copies checkpoint, clears downstream, re-executes):

```bash
dag-exec replay workflow.yaml --run-id abc123 --from-node review \
  --with-override verdict=approve
```

## Validation

Pre-flight validation catches 12 categories of errors before execution:

```bash
dag-exec --dry-run workflow.yaml
```

| Check | What it validates |
|-------|-------------------|
| Graph structure | Cycles, unreachable nodes, missing dependencies |
| Node type fields | Required fields present for each node type |
| Skill file existence | Skill paths resolve to real files |
| Command file existence | Command references exist |
| Input contracts | Pattern regex compilation, required inputs |
| Output references | Output declarations point to real nodes |
| Edge consistency | Targets exist, exactly one default per edge set |
| Environment variables | `DAG_*` env vars have values |
| Reducer consistency | Custom reducer functions are importable |
| Trigger rule sanity | `one_success`/`all_done` only on multi-dependency nodes |
| Variable references | `$node.field` syntax resolves correctly |
| Read state constraints | `reads` references point to declared channels or inputs |

## Events

The executor emits structured events throughout execution:

| Event | When |
|-------|------|
| `workflow_started` / `workflow_completed` / `workflow_failed` | Workflow lifecycle |
| `node_started` / `node_completed` / `node_failed` / `node_skipped` | Node lifecycle |
| `node_interrupted` / `workflow_interrupted` | Human-in-the-loop pauses |
| `node_stream_token` / `node_progress` | Streaming output from prompt nodes |

Events are written as JSONL to the checkpoint directory and can be streamed to subscribers via `EventEmitter`. Stream modes: `ALL`, `STATE_UPDATES`, `DEBUG`.

## CLI Reference

| Command | Purpose |
|---------|---------|
| `dag-exec <workflow.yaml> [inputs...]` | Execute a workflow |
| `dag-exec <workflow.yaml> --dry-run` | Validate and print execution plan |
| `dag-exec <workflow.yaml> --visualize` | Output Mermaid DAG diagram |
| `dag-exec <workflow.yaml> --resume --run-id ID` | Resume from checkpoint |
| `dag-exec list [directory]` | Catalog workflows in a directory |
| `dag-exec info <workflow.yaml>` | Show workflow details and execution plan |
| `dag-exec inspect <workflow.yaml> --run-id ID [--node NODE]` | Inspect checkpoint data |
| `dag-exec history <workflow.yaml> [--run-id ID]` | Show execution history |
| `dag-exec replay <workflow.yaml> --run-id ID --from-node NODE` | Replay from a specific node |

**Input formats**: `key=value` pairs or JSON objects (`'{"user_id": "U123"}'`).

**Flags**: `--concurrency N` (default 10), `--checkpoint-dir DIR`, `--stream [all|state_updates]`.

## Python API

```python
from dag_executor import load_workflow, execute_workflow, resume_workflow

# Load and execute
wf = load_workflow("workflow.yaml")
result = execute_workflow(wf, inputs={"user_id": "U123"})

print(result.status)       # WorkflowStatus.COMPLETED
print(result.node_results) # Dict[str, NodeResult]

# Resume from interrupt
result = resume_workflow(
    workflow_name="deploy-pipeline",
    run_id="abc123",
    checkpoint_store=CheckpointStore(".dag-checkpoints"),
    workflow_def=wf,
    resume_values={"approval_decision": True},
)
```

### Validation

```python
from dag_executor import WorkflowValidator, load_workflow

wf = load_workflow("workflow.yaml")
validator = WorkflowValidator(skills_dir=Path("skills"))
result = validator.validate(wf)

if not result.passed:
    for error in result.errors:
        print(f"[{error.node_id}] {error.message}")
```

### Event Streaming

```python
from dag_executor import EventEmitter, StreamMode, execute_workflow

emitter = EventEmitter()
emitter.subscribe(lambda e: print(e.event_type, e.node_id), StreamMode.ALL)

result = execute_workflow(wf, inputs={}, event_emitter=emitter)
```

### Channels

```python
from dag_executor import ChannelStore, ReducerChannel, ReducerStrategy

store = ChannelStore()
store.register("scores", ReducerChannel(ReducerStrategy.MAX))
store.write("scores", 0.85, writer_node_id="node-a")
store.write("scores", 0.92, writer_node_id="node-b")
value, version = store.read("scores")  # (0.92, 2)
```

## Architecture

```
src/dag_executor/
  __init__.py       Public API (load_workflow, execute_workflow, resume_workflow)
  schema.py         Pydantic v2 models for YAML definitions and runtime state
  parser.py         YAML loader with duplicate-ID and schema validation
  executor.py       Layer-parallel execution engine with retry, timeout, caching
  graph.py          Topological sort (Kahn's algorithm) with cycle detection
  channels.py       State channels (LastValue, Reducer, Barrier)
  reducers.py       Reducer registry (overwrite, append, extend, max, min, merge_dict, custom)
  checkpoint.py     File-based checkpoint store with content-addressed caching
  events.py         Event system with JSONL logging and subscriber streaming
  validator.py      Pre-flight validation (12 checks)
  variables.py      Template variable substitution engine
  labels.py         Event-driven label management (issue tracker integration)
  replay.py         Execution trace recording and replay
  cli.py            dag-exec CLI entry point
  runners/
    base.py         Runner registry and RunnerContext
    bash.py         Shell script execution
    command.py      External command invocation
    prompt.py       LLM prompt dispatch via Claude Code CLI
    skill.py        Skill file execution
    gate.py         Condition evaluation (simpleeval)
    interrupt.py    Human-in-the-loop pause/resume
```

## Development

```bash
pip install -e packages/dag-executor[dev]
pytest packages/dag-executor/tests/ -v
mypy packages/dag-executor/src/
```

Requires Python 3.9+. Dependencies: `pyyaml`, `pydantic>=2.0`, `simpleeval`.
