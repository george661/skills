#!/usr/bin/env python3
"""
Checkpoint System for Resumable Workflows

Provides AgentDB-backed checkpointing for long-running commands,
with filesystem fallback when AgentDB is unavailable.

Stores ONE pattern per issue in AgentDB with all phases in metadata.
This works with AgentDB's vector-based pattern store (not key-value).

Usage:
  checkpoint.py save <issue> <phase> <data-json>
  checkpoint.py load <issue> [phase]
  checkpoint.py list <issue>
  checkpoint.py clear <issue> [phase]
  checkpoint.py status
  checkpoint.py history <issue> [--brief]
  checkpoint.py inspect <issue> <step>
  checkpoint.py replay <issue> <from-step> [--override=key=value ...]
"""

import json
import sys
import os
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any, List

# Import AgentDB client (same directory)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from agentdb_client import agentdb_request, get_namespace
    AGENTDB_AVAILABLE = True
except ImportError:
    AGENTDB_AVAILABLE = False

# Configuration
CHECKPOINT_TTL_HOURS = int(os.environ.get('CHECKPOINT_TTL_HOURS', 168))  # 7 days
TASK_TYPE = 'checkpoint'

# Filesystem fallback (only used when AgentDB is unavailable)
FALLBACK_DIR = Path(os.environ.get('CHECKPOINT_DIR', os.path.expanduser('~/.claude/checkpoints')))


def approach_text(issue: str) -> str:
    """Consistent embedding text — MUST match checkpoint-loader.py."""
    return f"checkpoint {issue}"


# ---------------------------------------------------------------------------
# AgentDB operations — one pattern per issue, phases dict in metadata
# ---------------------------------------------------------------------------

def _agentdb_get_state(issue: str) -> Optional[Dict[str, Any]]:
    """Get the full checkpoint state for an issue from AgentDB."""
    result = agentdb_request('POST', '/api/v1/pattern/search', {
        'task': approach_text(issue),
        'k': 10,
        'filters': {'taskType': TASK_TYPE},
    })
    if not result:
        return None

    hits = result.get('results', [])
    # Find exact match for this issue, most recent first.
    # If the most recent entry is a tombstone (deleted=True), the issue is cleared.
    for hit in sorted(hits, key=lambda h: h.get('createdAt', 0), reverse=True):
        meta = hit.get('metadata', {})
        if meta.get('issue') == issue:
            if meta.get('deleted'):
                return None  # Tombstone — issue was cleared
            return meta
    return None


def _agentdb_put_state(issue: str, state: Dict[str, Any]) -> bool:
    """Store the full checkpoint state for an issue to AgentDB."""
    result = agentdb_request('POST', '/api/v1/pattern/store', {
        'task_type': TASK_TYPE,
        'approach': approach_text(issue),
        'success_rate': 1.0,
        'metadata': state,
    })
    return result is not None


def _agentdb_save(issue: str, phase: str, data: Dict[str, Any]) -> bool:
    """Save a checkpoint phase — merges into existing issue state."""
    state = _agentdb_get_state(issue) or {
        'issue': issue,
        'namespace': get_namespace(),
    }
    # Ensure phases dict exists (handles migration from old format)
    if 'phases' not in state:
        state['phases'] = {}
    state['phases'][phase] = {
        'data': data,
        'timestamp': datetime.now().isoformat(),
        'resumable': True,
    }
    state['updated_at'] = datetime.now().isoformat()
    return _agentdb_put_state(issue, state)


def _agentdb_load(issue: str, phase: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Load checkpoint(s) for an issue from AgentDB."""
    state = _agentdb_get_state(issue)
    if not state:
        return None

    phases = state.get('phases', {})
    if not phases:
        return None

    if phase:
        if phase not in phases:
            return None
        cp = phases[phase]
        return {
            'issue': issue,
            'phase': phase,
            'data': cp.get('data', {}),
            'timestamp': cp.get('timestamp', ''),
            'resumable': cp.get('resumable', True),
        }
    else:
        # Return the most recent phase
        latest_phase = max(phases.keys(), key=lambda p: phases[p].get('timestamp', ''))
        cp = phases[latest_phase]
        return {
            'issue': issue,
            'phase': latest_phase,
            'data': cp.get('data', {}),
            'timestamp': cp.get('timestamp', ''),
            'resumable': cp.get('resumable', True),
            'total_phases': len(phases),
        }


def _agentdb_list(issue: str) -> List[Dict[str, Any]]:
    """List all phases for an issue."""
    state = _agentdb_get_state(issue)
    if not state:
        return []

    result = []
    for phase_name, cp in state.get('phases', {}).items():
        ts = cp.get('timestamp', '')
        age = 0.0
        if ts:
            try:
                age = (datetime.now() - datetime.fromisoformat(ts)).total_seconds() / 3600
            except ValueError:
                pass
        result.append({
            'phase': phase_name,
            'timestamp': ts,
            'age_hours': round(age, 1),
            'resumable': cp.get('resumable', True),
            'data_keys': list(cp.get('data', {}).keys()),
        })
    result.sort(key=lambda r: r['timestamp'], reverse=True)
    return result


def _agentdb_clear(issue: str, phase: Optional[str] = None) -> int:
    """Clear checkpoint(s). If phase given, remove just that phase; otherwise tombstone all."""
    if phase:
        state = _agentdb_get_state(issue)
        if not state:
            return 0
        phases = state.get('phases', {})
        if phase not in phases:
            return 0
        del phases[phase]
        state['updated_at'] = datetime.now().isoformat()
        _agentdb_put_state(issue, state)
        return 1
    else:
        # Tombstone the whole issue
        _agentdb_put_state(issue, {
            'issue': issue,
            'deleted': True,
            'timestamp': datetime.now().isoformat(),
            'namespace': get_namespace() if AGENTDB_AVAILABLE else 'default',
        })
        return 1


# ---------------------------------------------------------------------------
# Filesystem fallback operations
# ---------------------------------------------------------------------------

def _fs_ensure():
    FALLBACK_DIR.mkdir(parents=True, exist_ok=True)


def _fs_path(issue: str, phase: str) -> Path:
    safe = issue.replace('/', '-').replace('\\', '-')
    return FALLBACK_DIR / f"{safe}-{phase}.json"


def _fs_issue_files(issue: str) -> List[Path]:
    _fs_ensure()
    safe = issue.replace('/', '-').replace('\\', '-')
    return sorted(FALLBACK_DIR.glob(f"{safe}-*.json"), key=lambda p: p.stat().st_mtime, reverse=True)


# ---------------------------------------------------------------------------
# Public API (AgentDB primary, filesystem fallback)
# ---------------------------------------------------------------------------

def save_checkpoint(issue: str, phase: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """Save a checkpoint."""
    if AGENTDB_AVAILABLE:
        try:
            if _agentdb_save(issue, phase, data):
                return {'saved': True, 'storage': 'agentdb', 'phase': phase, 'issue': issue}
        except Exception as e:
            print(f"[checkpoint] AgentDB save failed, falling back to filesystem: {e}", file=sys.stderr)

    # Filesystem fallback
    _fs_ensure()
    checkpoint = {
        'issue': issue,
        'phase': phase,
        'data': data,
        'timestamp': datetime.now().isoformat(),
        'resumable': True,
    }
    path = _fs_path(issue, phase)
    with open(path, 'w') as f:
        json.dump(checkpoint, f, indent=2)
    return {'saved': True, 'storage': 'filesystem', 'path': str(path), 'phase': phase, 'issue': issue}


def load_checkpoint(issue: str, phase: Optional[str] = None) -> Dict[str, Any]:
    """Load checkpoint(s) for an issue."""
    # Try AgentDB first
    if AGENTDB_AVAILABLE:
        try:
            cp = _agentdb_load(issue, phase)
            if cp:
                ts = cp.get('timestamp', '')
                age = 0.0
                if ts:
                    try:
                        age = (datetime.now() - datetime.fromisoformat(ts)).total_seconds() / 3600
                    except ValueError:
                        pass
                return {
                    'found': True,
                    'source': 'agentdb',
                    'checkpoint': cp,
                    'total_checkpoints': cp.get('total_phases', 1),
                    'age_hours': round(age, 2),
                }
        except Exception as e:
            print(f"[checkpoint] AgentDB load failed, falling back to filesystem: {e}", file=sys.stderr)

    # Filesystem fallback
    _fs_ensure()
    if phase:
        path = _fs_path(issue, phase)
        if not path.exists():
            return {'found': False, 'issue': issue, 'phase': phase}
        with open(path) as f:
            cp = json.load(f)
        age = (datetime.now() - datetime.fromisoformat(cp['timestamp'])).total_seconds() / 3600
        return {'found': True, 'source': 'filesystem', 'checkpoint': cp, 'age_hours': round(age, 2)}
    else:
        files = _fs_issue_files(issue)
        if not files:
            return {'found': False, 'issue': issue, 'checkpoints': []}
        with open(files[0]) as f:
            cp = json.load(f)
        age = (datetime.now() - datetime.fromisoformat(cp['timestamp'])).total_seconds() / 3600
        return {'found': True, 'source': 'filesystem', 'checkpoint': cp, 'total_checkpoints': len(files), 'age_hours': round(age, 2)}


def list_checkpoints(issue: str) -> Dict[str, Any]:
    """List all checkpoints for an issue."""
    # Try AgentDB
    if AGENTDB_AVAILABLE:
        try:
            items = _agentdb_list(issue)
            if items:
                return {'issue': issue, 'checkpoints': items, 'total': len(items), 'storage': 'agentdb'}
        except Exception as e:
            print(f"[checkpoint] AgentDB list failed: {e}", file=sys.stderr)

    # Filesystem fallback
    result = []
    for cp_path in _fs_issue_files(issue):
        try:
            with open(cp_path) as f:
                cp = json.load(f)
            age = datetime.now() - datetime.fromisoformat(cp['timestamp'])
            result.append({
                'phase': cp['phase'],
                'timestamp': cp['timestamp'],
                'age_hours': round(age.total_seconds() / 3600, 1),
                'resumable': cp.get('resumable', True),
                'data_keys': list(cp.get('data', {}).keys()),
            })
        except Exception:
            continue

    return {'issue': issue, 'checkpoints': result, 'total': len(result), 'storage': 'filesystem'}


def clear_checkpoints(issue: str, phase: Optional[str] = None) -> Dict[str, Any]:
    """Clear checkpoint(s) for an issue."""
    count = 0

    # Clear from AgentDB
    if AGENTDB_AVAILABLE:
        try:
            count += _agentdb_clear(issue, phase)
        except Exception as e:
            print(f"[checkpoint] AgentDB clear failed: {e}", file=sys.stderr)

    # Also clear filesystem
    _fs_ensure()
    if phase:
        path = _fs_path(issue, phase)
        if path.exists():
            path.unlink()
            count += 1
    else:
        for cp in _fs_issue_files(issue):
            cp.unlink()
            count += 1

    return {'cleared': True, 'issue': issue, 'phase': phase, 'count': count}


def status() -> Dict[str, Any]:
    """Get overall checkpoint system status."""
    info: Dict[str, Any] = {
        'agentdb_available': AGENTDB_AVAILABLE,
        'primary_storage': 'agentdb' if AGENTDB_AVAILABLE else 'filesystem',
        'ttl_hours': CHECKPOINT_TTL_HOURS,
    }

    # Filesystem stats
    _fs_ensure()
    fs_files = list(FALLBACK_DIR.glob('*.json'))
    info['filesystem'] = {
        'dir': str(FALLBACK_DIR),
        'count': len(fs_files),
        'size_kb': round(sum(f.stat().st_size for f in fs_files) / 1024, 1) if fs_files else 0,
    }

    # AgentDB stats
    if AGENTDB_AVAILABLE:
        try:
            result = agentdb_request('POST', '/api/v1/pattern/search', {
                'task': 'checkpoint',
                'k': 50,
                'filters': {'taskType': TASK_TYPE},
            })
            hits = result.get('results', []) if result else []
            active = [h for h in hits if not h.get('metadata', {}).get('deleted')]
            issues = set()
            total_phases = 0
            for h in active:
                meta = h.get('metadata', {})
                iss = meta.get('issue', '')
                if iss:
                    issues.add(iss)
                total_phases += len(meta.get('phases', {}))
            info['agentdb'] = {
                'total_issues': len(issues),
                'total_phases': total_phases,
                'issues': list(issues),
            }
        except Exception as e:
            info['agentdb'] = {'error': str(e)}

    return info


# ---------------------------------------------------------------------------
# Replay, History, and Inspect commands
# ---------------------------------------------------------------------------

def history_checkpoints(issue: str, brief: bool = False) -> Dict[str, Any]:
    """List all checkpoints for a run with metadata and content hashes.

    Args:
        issue: Issue identifier (e.g., GW-4986)
        brief: If True, omit full data from output

    Returns:
        Dict with issue, checkpoints list, and total count
    """
    if not AGENTDB_AVAILABLE:
        return {'error': 'AgentDB unavailable - history requires AgentDB'}

    try:
        phases = _agentdb_list(issue)
        if phases is None:
            return {'error': 'AgentDB unavailable - could not retrieve history'}

        checkpoints = []
        for phase_data in phases:
            phase_name = phase_data.get('phase', '')
            timestamp = phase_data.get('timestamp', '')
            data = phase_data.get('data', {})

            # Calculate age
            age_hours = 0.0
            if timestamp:
                try:
                    ts_dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                    age_hours = (datetime.now(timezone.utc) - ts_dt).total_seconds() / 3600
                except (ValueError, AttributeError):
                    pass

            # Calculate content hash
            content_str = json.dumps(data, sort_keys=True)
            content_hash = hashlib.sha256(content_str.encode()).hexdigest()[:16]

            # Determine status
            status = data.get('status', 'unknown')
            if status not in ['pass', 'fail', 'running']:
                # Infer status from data presence
                status = 'pass' if data else 'unknown'

            checkpoint_info = {
                'phase': phase_name,
                'timestamp': timestamp,
                'age_hours': round(age_hours, 2),
                'status': status,
                'content_hash': content_hash,
                'data_keys': list(data.keys()) if not brief else None,
            }

            if not brief:
                checkpoint_info['data'] = data

            checkpoints.append(checkpoint_info)

        # Sort by timestamp descending (newest first)
        checkpoints.sort(key=lambda x: x['timestamp'], reverse=True)

        return {
            'issue': issue,
            'checkpoints': checkpoints,
            'total': len(checkpoints),
        }
    except Exception as e:
        return {'error': f'Failed to retrieve history: {str(e)}'}


def inspect_checkpoint(issue: str, step: str) -> Dict[str, Any]:
    """Dump the full state snapshot at a given checkpoint.

    Args:
        issue: Issue identifier
        step: Phase/step name to inspect

    Returns:
        Dict with full checkpoint data and metadata
    """
    if not AGENTDB_AVAILABLE:
        return {'error': 'AgentDB unavailable - inspect requires AgentDB'}

    try:
        checkpoint = _agentdb_load(issue, step)
        if not checkpoint:
            return {'error': f'Checkpoint not found for issue={issue}, step={step}'}

        data = checkpoint.get('data', {})
        timestamp = checkpoint.get('timestamp', '')

        # Calculate content hash
        content_str = json.dumps(data, sort_keys=True)
        content_hash = hashlib.sha256(content_str.encode()).hexdigest()

        # Calculate data size
        data_size = len(content_str.encode())

        return {
            'issue': issue,
            'phase': step,
            'data': data,
            'timestamp': timestamp,
            'content_hash': content_hash,
            'data_size_bytes': data_size,
            'resumable': True,
        }
    except Exception as e:
        return {'error': f'Failed to inspect checkpoint: {str(e)}'}


def replay_checkpoint(issue: str, from_step: str, overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Replay workflow from a checkpoint with optional overrides.

    Creates a new run-id with ~replay~ suffix, loads the checkpoint state,
    applies any overrides, and saves as a new checkpoint. Marks all phases
    after from_step as cleared for re-execution.

    Args:
        issue: Issue identifier
        from_step: Phase name to replay from
        overrides: Optional dict of key-value pairs to merge into loaded state

    Returns:
        Dict with new_run_id, parent_run_id, replayed_from, and phases_cleared
    """
    if not AGENTDB_AVAILABLE:
        return {'error': 'AgentDB unavailable - replay requires AgentDB'}

    try:
        # Load checkpoint at from_step
        checkpoint = _agentdb_load(issue, from_step)
        if not checkpoint:
            return {'error': f'Checkpoint not found for issue={issue}, step={from_step}'}

        # Get all phases to identify which ones come after from_step
        all_phases = _agentdb_list(issue)
        if not all_phases:
            all_phases = []

        # Load the data
        data = checkpoint.get('data', {}).copy()

        # Apply overrides if provided
        if overrides:
            data.update(overrides)

        # Generate new run-id with replay timestamp
        timestamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
        new_run_id = f"{issue}~replay~{timestamp}"

        # Find phases that come after from_step (to be cleared)
        phases_to_clear = []
        found_from_step = False
        for phase_data in sorted(all_phases, key=lambda x: x.get('timestamp', '')):
            if found_from_step:
                phases_to_clear.append(phase_data.get('phase', ''))
            if phase_data.get('phase') == from_step:
                found_from_step = True

        # Add metadata about the replay
        replay_metadata = {
            'parent_run_id': issue,
            'replayed_from': from_step,
            'replay_timestamp': datetime.now(timezone.utc).isoformat(),
            'phases_cleared': phases_to_clear,
        }
        data['_replay_metadata'] = replay_metadata

        # Save the new checkpoint under the new run-id
        # This is non-destructive - original checkpoints are not modified
        saved = _agentdb_save(new_run_id, from_step, data)
        if not saved:
            return {'error': 'Failed to save replay checkpoint'}

        return {
            'success': True,
            'new_run_id': new_run_id,
            'parent_run_id': issue,
            'replayed_from': from_step,
            'phases_cleared': phases_to_clear,
            'overrides_applied': list(overrides.keys()) if overrides else [],
        }
    except Exception as e:
        return {'error': f'Failed to replay checkpoint: {str(e)}'}


def main():
    if len(sys.argv) < 2:
        print(json.dumps({'error': 'Usage: checkpoint.py <command> [args]'}))
        sys.exit(1)

    command = sys.argv[1]

    try:
        if command == 'save':
            if len(sys.argv) < 5:
                print(json.dumps({'error': 'Usage: checkpoint.py save <issue> <phase> <data-json>'}))
                sys.exit(1)
            issue, phase, data_json = sys.argv[2], sys.argv[3], sys.argv[4]
            data = json.loads(data_json)
            result = save_checkpoint(issue, phase, data)

        elif command == 'load':
            if len(sys.argv) < 3:
                print(json.dumps({'error': 'Usage: checkpoint.py load <issue> [phase]'}))
                sys.exit(1)
            issue = sys.argv[2]
            phase = sys.argv[3] if len(sys.argv) > 3 else None
            result = load_checkpoint(issue, phase)

        elif command == 'list':
            if len(sys.argv) < 3:
                print(json.dumps({'error': 'Usage: checkpoint.py list <issue>'}))
                sys.exit(1)
            result = list_checkpoints(sys.argv[2])

        elif command == 'clear':
            if len(sys.argv) < 3:
                print(json.dumps({'error': 'Usage: checkpoint.py clear <issue> [phase]'}))
                sys.exit(1)
            issue = sys.argv[2]
            phase = sys.argv[3] if len(sys.argv) > 3 else None
            result = clear_checkpoints(issue, phase)

        elif command == 'status':
            result = status()

        elif command == 'history':
            if len(sys.argv) < 3:
                print(json.dumps({'error': 'Usage: checkpoint.py history <issue> [--brief]'}))
                sys.exit(1)
            issue = sys.argv[2]
            brief = '--brief' in sys.argv
            result = history_checkpoints(issue, brief=brief)

        elif command == 'inspect':
            if len(sys.argv) < 4:
                print(json.dumps({'error': 'Usage: checkpoint.py inspect <issue> <step>'}))
                sys.exit(1)
            issue, step = sys.argv[2], sys.argv[3]
            result = inspect_checkpoint(issue, step)

        elif command == 'replay':
            if len(sys.argv) < 4:
                print(json.dumps({'error': 'Usage: checkpoint.py replay <issue> <from-step> [--override key=value ...]'}))
                sys.exit(1)
            issue, from_step = sys.argv[2], sys.argv[3]

            # Parse --override arguments
            overrides = {}
            for arg in sys.argv[4:]:
                if arg.startswith('--override='):
                    kv = arg.replace('--override=', '')
                    if '=' in kv:
                        key, value = kv.split('=', 1)
                        # Try to parse as JSON, fall back to string
                        try:
                            overrides[key] = json.loads(value)
                        except json.JSONDecodeError:
                            overrides[key] = value

            result = replay_checkpoint(issue, from_step, overrides if overrides else None)

        else:
            result = {'error': f'Unknown command: {command}'}

        print(json.dumps(result, indent=2))

    except Exception as e:
        print(json.dumps({'error': str(e)}))
        sys.exit(1)


if __name__ == '__main__':
    main()
