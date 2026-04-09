---
description: "Collect SDLC metrics from Claude Code session JSONL files, aggregate into categories, and store in AgentDB for trend analysis."
model_tier: haiku
dispatch: true
---

# /loop:metrics - Hourly SDLC Metrics Collection

Collect metrics from Claude Code session JSONL files, aggregate into structured categories, and store in AgentDB. This command is designed to run hourly via launchd but can also be invoked manually.

## Phase 0: Check Watermark

Read the watermark file to determine the last collection window.

```bash
WATERMARK_FILE="$HOME/.claude/cache/loop-metrics-last-run.json"
if [ -f "$WATERMARK_FILE" ]; then
  LAST_RUN=$(cat "$WATERMARK_FILE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('last_run',''))" 2>/dev/null || echo "")
  echo "Last metrics collection: $LAST_RUN"
else
  echo "No previous metrics collection found. Will scan all recent JSONL files."
  LAST_RUN=""
fi
```

## Phase 1: Find Session JSONL Files

Find JSONL files modified since the last run. These files contain Claude Code session events including tool calls, user messages, and assistant responses.

Search locations:
- `~/.claude/projects/` - Project-scoped session data
- `~/.claude/` - Global session data

If `LAST_RUN` is empty, default to files modified in the last 24 hours.

```bash
if [ -n "$LAST_RUN" ]; then
  # Create a reference file with the watermark timestamp
  touch -d "$LAST_RUN" /tmp/loop-metrics-ref 2>/dev/null || touch -t "$(echo $LAST_RUN | sed 's/[-T:]//g' | cut -c1-12)" /tmp/loop-metrics-ref 2>/dev/null
  JSONL_FILES=$(find ~/.claude/projects/ -name "*.jsonl" -newer /tmp/loop-metrics-ref 2>/dev/null)
  rm -f /tmp/loop-metrics-ref
else
  JSONL_FILES=$(find ~/.claude/projects/ -name "*.jsonl" -mtime -1 2>/dev/null)
fi
echo "Found $(echo "$JSONL_FILES" | grep -c . || echo 0) JSONL files to process"
```

## Phase 2: Parse Events

For each JSONL file, parse events and extract metrics using a Python script. Extract:

- **Command invocations**: User messages matching slash command patterns (`/work`, `/validate`, `/next`, `/review`, `/fix-pr`, `/resolve-pr`, `/implement`, `/plan`, `/groom`, `/loop:*`, `/design`, `/bug`, `/issue`, etc.)
- **Tool call counts**: Assistant messages containing `tool_use` blocks, grouped by tool name
- **Session duration**: Delta between first and last event timestamps
- **Model usage**: Model identifiers from metadata if available
- **Error signals**: Messages containing error patterns, failed assertions, or retry indicators

```python
import json, glob, os, sys, re
from collections import defaultdict
from datetime import datetime

command_pattern = ['/work', '/validate', '/next', '/review', '/fix-pr', '/resolve-pr',
                   '/implement', '/plan', '/groom', '/loop:', '/design', '/bug', '/issue',
                   '/garden', '/sequence', '/audit', '/investigate', '/triage',
                   '/daily-report', '/rx', '/metrics']

issue_key_pattern = re.compile(r'\b[A-Z]{2,}-\d+\b')

# Claude API pricing per 1M tokens (USD)
PRICING = {
    'claude-opus':   {'input': 15.0,  'output': 75.0,  'cache_creation': 18.75, 'cache_read': 1.50},
    'claude-sonnet': {'input': 3.0,   'output': 15.0,  'cache_creation': 3.75,  'cache_read': 0.30},
    'claude-haiku':  {'input': 0.80,  'output': 4.0,   'cache_creation': 1.00,  'cache_read': 0.08},
}

def _model_pricing(model_id):
    m = model_id.lower()
    for k, p in PRICING.items():
        if k in m:
            return p
    return PRICING['claude-sonnet']

def _compute_usd(model_id, usage):
    p = _model_pricing(model_id)
    return (
        usage.get('input_tokens', 0)                * p['input']           / 1_000_000 +
        usage.get('output_tokens', 0)               * p['output']          / 1_000_000 +
        usage.get('cache_creation_input_tokens', 0) * p['cache_creation']  / 1_000_000 +
        usage.get('cache_read_input_tokens', 0)     * p['cache_read']      / 1_000_000
    )

metrics = {
    'command_invocations': defaultdict(int),
    'issues_worked': defaultdict(lambda: defaultdict(int)),  # {issue_key: {command: count}}
    'issue_agent_usd': defaultdict(float),                   # {issue_key: total_USD} attributed from sessions
    'validated_issues': set(),                               # issue keys that had a /validate invocation this window
    'tool_calls': defaultdict(int),
    'session_count': 0,
    'total_duration_seconds': 0,
    'total_cost_usd': 0.0,
    'model_usage': defaultdict(int),
    'error_count': 0,
    'bug_count': 0,
}

for filepath in jsonl_files:
    timestamps = []
    file_issue_keys = set()
    file_cost_usd = 0.0
    for line in open(filepath):
        try:
            event = json.loads(line)
        except:
            continue
        if 'timestamp' in event:
            timestamps.append(event['timestamp'])
        msg_type = event.get('type', '')
        if msg_type == 'user':
            content = event.get('content', '')
            if isinstance(content, str):
                for cmd in command_pattern:
                    if content.strip().startswith(cmd):
                        metrics['command_invocations'][cmd] += 1
                        keys = issue_key_pattern.findall(content)
                        for key in keys:
                            metrics['issues_worked'][key][cmd] += 1
                            file_issue_keys.add(key)
                            if cmd == '/validate':
                                metrics['validated_issues'].add(key)
                        break
                for key in issue_key_pattern.findall(content):
                    file_issue_keys.add(key)
        elif msg_type == 'assistant':
            msg = event.get('message', {})
            tool_uses = [b for b in event.get('content', []) if isinstance(b, dict) and b.get('type') == 'tool_use']
            for tu in tool_uses:
                metrics['tool_calls'][tu.get('name', 'unknown')] += 1
            # Compute USD cost from token usage
            model = msg.get('model', '') if isinstance(msg, dict) else ''
            usage = msg.get('usage', {}) if isinstance(msg, dict) else {}
            if model and usage:
                metrics['model_usage'][model] += 1
                file_cost_usd += _compute_usd(model, usage)
    if timestamps:
        metrics['session_count'] += 1
        try:
            first = datetime.fromisoformat(timestamps[0].replace('Z', '+00:00'))
            last = datetime.fromisoformat(timestamps[-1].replace('Z', '+00:00'))
            metrics['total_duration_seconds'] += (last - first).total_seconds()
        except:
            pass
        metrics['total_cost_usd'] += file_cost_usd
        # Attribute session USD cost to every issue key that appeared in this file
        for key in file_issue_keys:
            metrics['issue_agent_usd'][key] += file_cost_usd
```

## Phase 3: Aggregate into Metric Categories

Structure the parsed data into four metric categories:

### command_metrics
- command name, invocation count, inferred success/failure (presence of outcome labels or error patterns after invocation)

### cost_metrics
- model name, estimated token count (approximate from tool call count and message length)

### compliance_metrics
- workflow phase completion rates: how many `/work` invocations reached `/validate`
- skip detection: direct `/implement` without `/create-implementation-plan`

### defect_metrics
- `/bug` invocation count
- recidivism signals: same issue key appearing in multiple `/work` cycles

## Phase 3.5: Update Jira Cost for Validated Issues

For each issue that received a `/validate` invocation this window, check if it is now Done in Jira
and write the total agent hours as the Cost field. Skips issues that already have a cost set.
Only runs when `JIRA_COST_FIELD_ID` is configured in `$PROJECT_ROOT/.env`.

```python
import os, subprocess, json

project_root = os.environ.get('PROJECT_ROOT', os.getcwd())

# Load JIRA_COST_FIELD_ID from env or .env file
cost_field_id = os.environ.get('JIRA_COST_FIELD_ID', '')
if not cost_field_id:
    env_path = os.path.join(project_root, '.env')
    if os.path.exists(env_path):
        for line in open(env_path):
            line = line.strip()
            if line.startswith('JIRA_COST_FIELD_ID='):
                cost_field_id = line.split('=', 1)[1].strip().strip('"').strip("'")
                break

if not cost_field_id:
    print("JIRA_COST_FIELD_ID not configured — skipping cost update")
else:
    validated = metrics.get('validated_issues', set())
    issue_usd = metrics.get('issue_agent_usd', {})
    print(f"Checking {len(validated)} validated issue(s) for cost update...")
    updated = 0
    skipped = 0
    for issue_key in sorted(validated):
        cost_usd = round(issue_usd.get(issue_key, 0.0), 2)
        if cost_usd <= 0:
            skipped += 1
            continue
        # Query Jira for issue status and existing cost
        result = subprocess.run(
            ['npx', 'tsx', os.path.expanduser('~/.claude/skills/issues/get_issue.ts'),
             json.dumps({'issue_key': issue_key, 'fields': ['status', cost_field_id]})],
            capture_output=True, text=True, cwd=project_root
        )
        if result.returncode != 0:
            print(f"  {issue_key}: Jira lookup failed — {result.stderr.strip()[:80]}")
            continue
        try:
            issue_data = json.loads(result.stdout)
            status_name = issue_data.get('fields', {}).get('status', {}).get('name', '')
            existing_cost = issue_data.get('fields', {}).get(cost_field_id)
        except Exception as e:
            print(f"  {issue_key}: parse error — {e}")
            continue
        if status_name != 'Done':
            print(f"  {issue_key}: status={status_name!r} (not Done) — skipping")
            skipped += 1
            continue
        if existing_cost is not None:
            print(f"  {issue_key}: cost already set (${existing_cost}) — skipping")
            skipped += 1
            continue
        # Write cost (USD)
        update_result = subprocess.run(
            ['npx', 'tsx', os.path.expanduser('~/.claude/skills/issues/update_issue.ts'),
             json.dumps({'issue_key': issue_key, 'cost': cost_usd, 'notify_users': False})],
            capture_output=True, text=True, cwd=project_root
        )
        if update_result.returncode == 0:
            print(f"  {issue_key}: cost set to ${cost_usd}")
            updated += 1
        else:
            print(f"  {issue_key}: update failed — {update_result.stderr.strip()[:80]}")
    print(f"Cost updates: {updated} written, {skipped} skipped")
```

## Phase 4: Store in AgentDB

Store the aggregated metrics as a reflexion episode for trend analysis.

```bash
METRICS_PAYLOAD=$(python3 -c "
import json
metrics = $METRICS_JSON
print(json.dumps({
    'session_id': '${TENANT_NAMESPACE:-gw}',
    'task': 'metrics-hourly-$(date -u +%Y%m%dT%H%M%S)',
    'reward': 1.0,
    'success': True,
    'trajectory': [{
        'action': 'metrics-collection',
        'result': metrics
    }]
}))
")
npx tsx ~/.claude/skills/agentdb/reflexion_store_episode.ts "$METRICS_PAYLOAD"
```

## Phase 5: Update Watermark

Record the current timestamp so the next run only processes new files.

```bash
mkdir -p "$HOME/.claude/cache"
echo "{\"last_run\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"}" > "$HOME/.claude/cache/loop-metrics-last-run.json"
echo "Watermark updated."
```

## Phase 6: Session-Start Surfacing

At the next interactive session start, read the latest metrics from AgentDB and present actionable recommendations. Focus on:

1. **Workflow compliance gaps**: Commands that were started but not completed through the full lifecycle
2. **Cost outliers**: Sessions with unusually high tool call counts
3. **Defect trends**: Increasing `/bug` frequency or issue recidivism
4. **Efficiency wins**: Patterns that correlate with faster cycle times

Present a summary table and ask for HITL confirmation before taking any corrective action (e.g., creating Jira issues for recurring defects).

```bash
npx tsx ~/.claude/skills/agentdb/reflexion_retrieve_relevant.ts '{"task": "metrics-hourly", "k": 3}'
```

Review the retrieved episodes and surface the top 3 actionable findings.
