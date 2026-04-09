#!/usr/bin/env python3
"""
Optimized session start hook with lazy loading.
Sets environment markers for available resources without loading them.
Actual loading happens on-demand when explicitly requested.
"""

import json
import os
import sys
from pathlib import Path

# Process-level cache for tenant config
_TENANT_CONFIG_CACHE = {}


def load_tenant_config():
    """Load tenant configuration with caching."""
    global _TENANT_CONFIG_CACHE

    cache_key = "tenant_config"
    if cache_key in _TENANT_CONFIG_CACHE:
        return _TENANT_CONFIG_CACHE[cache_key]

    script_dir = Path(__file__).parent
    loader_script = script_dir / 'load-tenant-config.py'

    if not loader_script.exists():
        return None

    try:
        import subprocess
        result = subprocess.run(
            ['python3', str(loader_script)],
            capture_output=True,
            text=True,
            timeout=2  # Reduced timeout
        )

        if result.returncode == 0 and result.stdout.strip():
            tenant_vars = {}
            for line in result.stdout.strip().split('\n'):
                if line.startswith('export '):
                    var_def = line[7:]
                    if '=' in var_def:
                        key, value = var_def.split('=', 1)
                        value = value.strip('"')
                        tenant_vars[key] = value

            # Cache for session
            _TENANT_CONFIG_CACHE[cache_key] = tenant_vars
            return tenant_vars

        return None
    except Exception:
        return None


def set_resource_markers(tenant_vars):
    """Set environment variables indicating resource availability."""

    # Mark AgentDB as available (but don't connect)
    os.environ['AGENTDB_AVAILABLE'] = 'true'

    # Point to skills cache (but don't load)
    cache_file = Path.home() / '.claude' / 'cache' / 'skills-index.json'
    if cache_file.exists():
        os.environ['SKILLS_CACHE'] = str(cache_file)

    # Point to domain model (but don't read)
    if tenant_vars:
        domain_path = tenant_vars.get('TENANT_DOMAIN_PATH', '')
        if domain_path:
            domain_index = os.path.join(domain_path, 'domain-index.json')
            if os.path.exists(domain_index):
                os.environ['DOMAIN_MODEL_PATH'] = domain_index


def main():
    # Read hook input (may be empty on session start)
    try:
        input_data = json.loads(sys.stdin.read()) if not sys.stdin.isatty() else {}
    except:
        input_data = {}

    # Load tenant configuration (cached)
    tenant_vars = load_tenant_config()

    # Validate provider environment configuration (non-blocking)
    try:
        from pathlib import Path as _Path
        _validator = _Path(__file__).parent / 'validate-config.py'
        if _validator.exists():
            import importlib.util as _ilu
            _spec = _ilu.spec_from_file_location("validate_config", str(_validator))
            _mod = _ilu.module_from_spec(_spec)
            _spec.loader.exec_module(_mod)
            _mod.validate_config()
    except Exception:
        pass  # Config validation is best-effort — never block session start

    # Set resource markers without loading
    set_resource_markers(tenant_vars)

    # Build minimal tenant context message
    if tenant_vars:
        tenant_id = tenant_vars.get('TENANT_ID', 'unknown')
        tenant_project = tenant_vars.get('TENANT_PROJECT', '')
        tenant_namespace = tenant_vars.get('TENANT_NAMESPACE', '')

        guidance = f"""TENANT CONTEXT
Active tenant: {tenant_id}
Project: {tenant_project}
Namespace: {tenant_namespace}

Resources available on-demand:
- AgentDB memory context (use agentdb_loader when needed)
- Skills index (cached at {os.environ.get('SKILLS_CACHE', 'not cached')})
- Domain model (available at {os.environ.get('DOMAIN_MODEL_PATH', 'not set')})

Use workflow commands: /work, /validate, /next
"""
    else:
        guidance = """TENANT CONTEXT
No tenant configuration found. Using defaults.

Resources available on-demand:
- AgentDB memory context (use agentdb_loader when needed)
- Skills index (cached at {os.environ.get('SKILLS_CACHE', 'not cached')})

Use workflow commands: /work, /validate, /next
"""

    # VALIDATION queue — surface issues stranded in VALIDATION before any other prompt
    try:
        import json as _json
        import subprocess as _subprocess
        _jira_skill = os.path.expanduser("~/.claude/skills/jira/search_issues.ts")
        _tenant_project = os.environ.get("TENANT_PROJECT", "${PROJECT_KEY}")
        _jql = (
            f"project = {_tenant_project} AND status = VALIDATION "
            f"AND labels not in (\"step:needs-human\")"
        )
        _val_result = _subprocess.run(
            ["npx", "tsx", _jira_skill,
             json.dumps({"jql": _jql, "fields": ["key", "summary"], "max_results": 5})],
            capture_output=True, text=True, timeout=15
        )
        if _val_result.returncode == 0:
            _val_data = _json.loads(_val_result.stdout)
            _val_issues = _val_data.get("issues", [])
            if _val_issues:
                _count = _val_data.get("total", len(_val_issues))
                _lines = [f"VALIDATION QUEUE ({_count} issue(s) — run /validate before starting new work):"]
                for _iss in _val_issues[:5]:
                    _summary = (_iss.get("fields", {}).get("summary") or "")[:60]
                    _lines.append(f"  /validate {_iss['key']}  — {_summary}")
                if _count > 5:
                    _lines.append("  ... (more in Jira)")
                print("\n".join(_lines) + "\n")
    except Exception:
        pass  # Banner is best-effort — never block session start

    print(guidance, file=sys.stderr)

    # Return minimal result
    result = {"continue": True}
    if tenant_vars:
        result["tenant"] = tenant_vars

    print(json.dumps(result))


if __name__ == "__main__":
    main()