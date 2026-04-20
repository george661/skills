## REVISED IMPLEMENTATION PLAN (v2)

### Changes from v1:

**Critical Fixes:**
1. **Resume delivery mechanism corrected**: Changed from NDJSON event consumption to file-based `resume_values.json` in checkpoint dir. Added `save_resume_values()` and `load_resume_values()` methods to `CheckpointStore`. The executor's `run_resume()` already merges checkpoint-based values with CLI `--resume-values` arg (explicit arg wins). Dashboard POST route writes via `CheckpointStore.save_resume_values()`.

2. **Checkpoint path resolution fixed**: Parse `checkpoint_prefix` from `workflow_runs.workflow_definition` YAML at request time. Resolve as `{checkpoint_prefix}/{workflow_name}-{run_id}/interrupt.json`. Add `DAG_CHECKPOINT_DIR` env var as fallback for tests.

3. **Node type discrimination fixed**: Extend interrupt runner to output `"node_type": "interrupt"` in its output dict (alongside message, resume_key, channels). UI branches on `node.outputs?.node_type === 'interrupt'` instead of checking inputs.

**Warning Fixes:**
4. Frontend testing restricted to manual browser verification (screenshots) + Python unit tests for HTML rendering via `TestClient`. No Playwright harness added.
5. GateIndicator tooltip enhancement marked as optional stretch goal (deferred).
6. Validation commands split: `mypy packages/dag-dashboard/src/` and `mypy packages/dag-executor/src/` as separate invocations.

---

### Updated Plan:

**Issue Type:** UI_INTERACTION (also touches API_ENDPOINT for new resume route)
**Repository:** skills
**Worktree:** worktrees/skills/GW-5061-interrupt-approval-ui
**Branch:** GW-5061-interrupt-approval-ui

#### Files to Change

**Backend (dag-executor):**
- `packages/dag-executor/src/dag_executor/checkpoint.py` — add `save_resume_values(workflow_name, run_id, values: Dict[str, Any])` (writes `{checkpoint_prefix}/{workflow_name}-{run_id}/resume_values.json`) and `load_resume_values(workflow_name, run_id) -> Dict[str, Any]` (returns empty dict if missing)
- `packages/dag-executor/src/dag_executor/__init__.py` — extend `run_resume()` to load checkpoint-based resume values via `CheckpointStore.load_resume_values()` and merge with explicit `resume_values` arg (explicit arg wins)
- `packages/dag-executor/src/dag_executor/runners/interrupt.py:84-88` — add `"node_type": "interrupt"` to the output dict in the INTERRUPTED result

**Backend (dag-dashboard):**
- `packages/dag-dashboard/src/dag_dashboard/models.py` — add `InterruptResumeRequest` (resume_value of `Any`, decided_by, comment)
- `packages/dag-dashboard/src/dag_dashboard/queries.py` — add `get_interrupt_checkpoint(db_path, workflow_name, run_id, node_name)` helper that:
  1. Queries `workflow_runs` for `workflow_definition` YAML
  2. Parses `checkpoint_prefix` from YAML (or uses env `DAG_CHECKPOINT_DIR` fallback)
  3. Resolves `{checkpoint_prefix}/{workflow_name}-{run_id}/interrupt.json`
  4. Calls `CheckpointStore(checkpoint_prefix).load_interrupt(workflow_name, run_id)`
  5. Returns `InterruptCheckpoint` or None
- `packages/dag-dashboard/src/dag_dashboard/routes.py` — add:
  - `GET /api/workflows/{run_id}/nodes/{node_name}/interrupt` (returns message, resume_key, channels, timeout, workflow_state, pending_nodes, node_type from checkpoint)
  - `POST /api/workflows/{run_id}/interrupts/{node_name}/resume` (writes resume value via `CheckpointStore.save_resume_values()`, marks node completed with output carrying resume_value, inserts decision audit row)
- `packages/dag-dashboard/src/dag_dashboard/server.py` — inject `checkpoint_dir_fallback` into app state from env `DAG_CHECKPOINT_DIR` (default `~/.dag-executor/checkpoints` for tests)

**Frontend:**
- `packages/dag-dashboard/src/dag_dashboard/static/js/node-detail-panel.js` — branch `renderApproval` on `node.outputs?.node_type === 'interrupt'`; new `renderInterruptResume(node)` renders message, resume_key form, channels, timeout, state viewer, buttons
- `packages/dag-dashboard/src/dag_dashboard/static/css/styles.css` — styles for interrupt panel

#### Tests to Write

**Backend (pytest, in `packages/dag-executor/tests/`):**
- `test_checkpoint.py` (extend): `test_save_load_resume_values`, `test_load_resume_values_missing_returns_empty_dict`
- `test_init.py` (extend or new `test_resume.py`): `test_run_resume_merges_checkpoint_values`, `test_run_resume_explicit_arg_wins_over_checkpoint`
- `test_interrupt_runner.py` (extend): `test_interrupt_output_includes_node_type`

**Backend (pytest, in `packages/dag-dashboard/tests/`):**
- `test_routes.py` (extend): interrupt GET/POST endpoint tests
- `test_queries.py` (extend): checkpoint query tests
