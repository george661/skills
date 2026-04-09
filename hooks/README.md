# Smart Hook Loader

A performance-safe hook system that prevents cascade failures and maintains fast agent response times.

## Quick Start

```bash
# Install the Smart Hook Loader
cd agents
./scripts/install.sh

# If hooks cause performance issues, emergency disable them
~/.claude/hooks/EMERGENCY-DISABLE.sh
```

## Problem This Solves

The previous hook system had 50+ hooks running on every tool call, causing:
- 30+ minute delays when agents spawned subagents
- Cascade failures from hooks calling other hooks
- No way to selectively disable problematic hooks
- Performance degradation over time

## Architecture

The Smart Hook Loader provides:

- **Single entry point**: `hook-loader.py` handles all hook decisions
- **Manifest-driven**: `manifest.json` defines when hooks should run
- **Circuit breakers**: Hooks automatically disabled after 3 failures
- **Time budgets**: 50ms total time limit for all hooks per operation
- **Agent depth protection**: Most hooks only run in the main agent (depth 0)
- **Selective loading**: Hooks only loaded when their triggers match

## How It Works

1. Claude Code calls `hook-loader.py` for each tool use
2. Hook loader checks `manifest.json` for applicable hooks
3. Only loads and runs hooks whose triggers match the current context
4. Tracks failures and disables problematic hooks
5. Enforces strict time budgets to prevent slowdowns

## Configuration

Edit `manifest.json` to control which hooks run:

```json
{
  "profiles": {
    "safety": {
      "enabled": true,  // Enable/disable entire profile
      "hooks": {
        "block-dangerous-commands": {
          "file": "safety/block-dangerous-commands.py",
          "events": ["PreToolUse:Bash"],
          "triggers": {
            "patterns": ["rm -rf /", "sudo rm", "dd if=/dev/zero"],
            "max_agent_depth": 0  // Only in main agent
          }
        }
      }
    }
  }
}
```

### Profile Structure

- **profiles**: Named collections of related hooks
- **enabled**: Master switch for the entire profile
- **hooks**: Individual hook configurations
  - **file**: Path to hook implementation
  - **events**: When to run (e.g., `PreToolUse:Bash`)
  - **triggers**: Conditions that must match
    - **patterns**: Text patterns to match in tool input
    - **max_agent_depth**: Maximum agent depth (0 = main only)

## Adding New Hooks

1. Create hook file in `safety/` or `available/`:
```python
#!/usr/bin/env python3
import json
import sys

def handle_hook(data):
    # Your logic here
    return {"decision": "approve"}

if __name__ == "__main__":
    data = json.load(sys.stdin)
    result = handle_hook(data)
    json.dump(result, sys.stdout)
```

2. Add entry to `manifest.json`:
```json
{
  "my-new-hook": {
    "file": "available/my-new-hook.py",
    "events": ["PreToolUse:Edit"],
    "triggers": {
      "patterns": ["password", "secret"],
      "max_agent_depth": 1
    }
  }
}
```

3. Set `enabled: true` in the profile

4. Test with integration tests:
```bash
python3 .claude/hooks/tests/test_integration.py
```

## Performance Safeguards

### Circuit Breakers
- Hooks that fail 3 times are disabled for the session
- Failure state tracked in memory (not persisted)
- Automatic recovery on next session

### Time Budgets
- 50ms total budget for all hooks per operation
- Individual hooks get proportional share
- Hooks that exceed budget are killed and disabled

### Agent Depth Protection
- Most hooks only run at depth 0 (main agent)
- Prevents exponential slowdown with nested agents
- Configurable per hook via `max_agent_depth`

### Thread Safety
- Concurrent execution safe
- No shared mutable state between hook calls
- Each hook runs in isolated process

## Emergency Recovery

If hooks cause severe performance issues:

```bash
# This replaces all hooks with no-op stubs
~/.claude/hooks/EMERGENCY-DISABLE.sh

# To re-enable, reinstall
cd agents
./scripts/install.sh
```

The emergency disable script:
- Backs up current hooks to `~/.claude/hooks.backup/`
- Replaces all hooks with stubs that just approve
- Provides immediate relief from hook-related issues

## Testing

### Unit Tests
```bash
# Test the hook loader logic
python3 .claude/hooks/tests/test_hook_loader.py

# Test dangerous command blocking
python3 .claude/hooks/tests/test_block_dangerous.py
```

### Integration Tests
```bash
# Test full system integration
python3 .claude/hooks/tests/test_integration.py
```

### Performance Tests
The integration test includes performance benchmarks:
- Measures average hook execution time
- Warns if hooks take >100ms on average
- Tests with various event types and inputs

## Default Hooks

The system ships with 4 essential safety hooks:

1. **block-dangerous-commands**: Prevents `rm -rf /` and similar
2. **prevent-key-exposure**: Blocks accidental API key commits
3. **limit-file-operations**: Caps file operations per session
4. **warn-large-deletions**: Warns before large file deletions

All other hooks start disabled and must be explicitly enabled.

## Monitoring

Check hook performance:
```bash
# View recent hook executions
tail -f ~/.claude/hooks/performance.log

# Check for disabled hooks
grep "DISABLED" ~/.claude/hooks/performance.log

# Count hook invocations
grep "PreToolUse" ~/.claude/hooks/performance.log | wc -l
```

## Troubleshooting

### Hooks not running
1. Check if profile is enabled in `manifest.json`
2. Verify hook file exists and is executable
3. Check trigger patterns match your use case
4. Review `~/.claude/hooks/performance.log` for errors

### Performance issues
1. Run `EMERGENCY-DISABLE.sh` immediately
2. Check `performance.log` for slow hooks
3. Reduce number of enabled hooks
4. Increase `max_agent_depth` to skip subagents

### Hook failures
1. Check hook implementation for bugs
2. Review error messages in `performance.log`
3. Test hook in isolation with mock data
4. Consider disabling until fixed

## Migration from Old System

The old hook system is automatically disabled when the Smart Hook Loader is installed. Your existing hooks are preserved in `available/` but not active by default.

To migrate a specific hook:
1. Copy it to `available/` if not already there
2. Add appropriate entry to `manifest.json`
3. Test thoroughly before enabling
4. Monitor performance after enabling

## Best Practices

1. **Start minimal**: Enable only essential safety hooks
2. **Test thoroughly**: Use integration tests before enabling
3. **Monitor performance**: Check logs regularly
4. **Use triggers wisely**: Be specific to avoid false positives
5. **Respect depth limits**: Don't run heavy hooks in subagents
6. **Handle errors gracefully**: Always return valid JSON
7. **Keep hooks focused**: One hook = one responsibility
8. **Document triggers**: Explain why patterns were chosen

## Future Improvements

Planned enhancements:
- Hook composition (combine multiple hooks)
- Async hook execution for non-blocking operations
- Hook marketplace for sharing useful hooks
- Performance profiling dashboard
- A/B testing for hook effectiveness
- Machine learning for trigger optimization

## Support

For issues or questions:
1. Check this README first
2. Review `~/.claude/hooks/performance.log`
3. Run integration tests to diagnose
4. Use `EMERGENCY-DISABLE.sh` if needed
5. Report bugs to agents repository