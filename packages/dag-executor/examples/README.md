# dag-executor examples

Runnable workflows that double as ladder tests. Each step proves one more
primitive works end-to-end before stacking the next.

Run any of them with:

```bash
cd packages/dag-executor
dag-exec examples/01-hello.yaml
```

## Ladder

| File | Proves |
|---|---|
| `01-hello.yaml` | Bash runner harness, single node, no inputs |
| `02-variable-substitution.yaml` | Input `default:`, `$name` substitution in bash body, state channel flow between two nodes (`writes:` → `reads:`) |
| `03-prompt-node.yaml` | Prompt node, `context: shared`, `mode: completion` via sonnet or local Ollama, `writes: [reply]` capturing the LLM response |

## Author contracts worth knowing

### Bash output → state channels

When a bash node has `output_format: json` and `writes: [some_key]`, the
executor parses the script's stdout and writes **dict keys** into matching
state channels. If the top-level JSON doesn't contain a key named
`some_key`, nothing lands in the channel.

```yaml
writes:
  - audit_results
script: |
  # WRONG — stdout is a bare array, won't populate `audit_results`
  echo '[{"a": 1}]'
```

```yaml
writes:
  - audit_results
script: |
  # RIGHT — wrap under the writes key name
  echo '{"audit_results": [{"a": 1}]}'
```

This is the most common "my bash node runs, output looks fine, downstream
gets `None`" trap.

### State channels → bash scripts

Channel values declared in `reads:` are exposed as environment variables in
two forms: `$DAG_<UPPER>` (legacy) and `$<lowercase>` (matches the YAML).
Dict/list values are JSON-serialized so bash pipelines (e.g.
`echo "$children_list" | jq '.issues[]'`) get valid JSON, not Python repr.

### Prompt node modes

- `mode: agent` — full Claude Code harness: tools, CLAUDE.md auto-discovery,
  hooks, skills. Use for nodes that read/edit files, call Jira, drive tool
  loops.
- `mode: completion` — bare LLM call: no tools, no harness. Use for pure
  reasoning, JSON judgment, formatting.
- `model: sonnet | opus | haiku | local` — independent of mode. Completion
  mode with sonnet is the fast path for structured JSON reasoning.

Missing `mode` on a prompt node emits a deprecation warning at dry-run;
the runner falls back to `agent` for backward compat.

### Checkpoint location

Workflow `checkpoint_prefix: vale` stores run data under
`.dag-checkpoints/vale/` relative to CWD. `.dag-checkpoints/` is gitignored.
Pass `--checkpoint-dir` to override.
