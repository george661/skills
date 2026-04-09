#!/usr/bin/env python3
"""
Result Compressor Hook

Compresses large MCP tool results to reduce context consumption.
Based on Anthropic's "Code Execution with MCP" article recommendations.

Usage:
  - PostToolUse hook for mcp__* tools
  - Reads tool result from stdin (JSON)
  - Outputs compressed result or passes through if under threshold
"""

import json
import sys
import os
from datetime import datetime

# Configuration - tier-aware thresholds
try:
    from result_compressor_tiers import get_active_tier, get_tier_thresholds
    _tier = get_active_tier()
    _thresholds = get_tier_thresholds(_tier)
    MAX_RESULT_CHARS = int(os.environ.get('RESULT_COMPRESS_MAX_CHARS', _thresholds['max_total']))
    MAX_ARRAY_ITEMS = int(os.environ.get('RESULT_COMPRESS_MAX_ITEMS', _thresholds['max_array']))
except ImportError:
    MAX_RESULT_CHARS = int(os.environ.get('RESULT_COMPRESS_MAX_CHARS', 8000))
    MAX_ARRAY_ITEMS = int(os.environ.get('RESULT_COMPRESS_MAX_ITEMS', 20))
SUMMARY_ENABLED = os.environ.get('RESULT_COMPRESS_SUMMARY', 'true').lower() == 'true'
LOG_FILE = os.path.expanduser('~/.claude/result-compression.log')


def log(message: str):
    """Append to compression log for metrics tracking."""
    try:
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        with open(LOG_FILE, 'a') as f:
            f.write(f"{datetime.now().isoformat()} - {message}\n")
    except Exception:
        pass  # Don't fail on logging errors


def get_size_str(size: int) -> str:
    """Human-readable size string."""
    if size < 1000:
        return f"{size} chars"
    elif size < 1000000:
        return f"{size // 1000}K chars"
    else:
        return f"{size // 1000000}M chars"


def truncate_string(s: str, max_len: int) -> str:
    """Truncate string with indicator."""
    if len(s) <= max_len:
        return s
    return s[:max_len] + f"\n... [TRUNCATED: {get_size_str(len(s))} total]"


def compress_array(arr: list, max_items: int, context: str = "") -> dict:
    """Compress large arrays to sample + metadata."""
    if len(arr) <= max_items:
        return arr

    return {
        "_compressed": True,
        "_type": "array",
        "_total": len(arr),
        "_showing": max_items,
        "_context": context,
        "sample": arr[:max_items],
        "_note": f"Showing first {max_items} of {len(arr)} items. Use pagination or filtering for more."
    }


def compress_object(obj: dict, max_chars: int, path: str = "") -> dict:
    """Recursively compress object fields."""
    result = {}

    for key, value in obj.items():
        field_path = f"{path}.{key}" if path else key

        if isinstance(value, str) and len(value) > max_chars // 4:
            # Truncate long strings
            result[key] = truncate_string(value, max_chars // 4)
        elif isinstance(value, list):
            # Compress arrays
            result[key] = compress_array(value, MAX_ARRAY_ITEMS, field_path)
        elif isinstance(value, dict):
            # Recurse into nested objects
            result[key] = compress_object(value, max_chars // 2, field_path)
        else:
            result[key] = value

    return result


def compress_result(tool_name: str, result: any) -> dict:
    """Main compression logic based on tool type."""
    original_size = len(json.dumps(result)) if result else 0

    if original_size <= MAX_RESULT_CHARS:
        return {"compressed": False, "result": result}

    compressed = None

    # Handle common patterns
    if isinstance(result, dict):
        # Jira search_issues pattern
        if 'issues' in result and isinstance(result['issues'], list):
            compressed = {
                **result,
                'issues': compress_array(result['issues'], MAX_ARRAY_ITEMS, 'issues'),
                '_compression': {
                    'original_size': get_size_str(original_size),
                    'tool': tool_name
                }
            }

        # Bitbucket list patterns (PRs, pipelines, branches)
        elif 'values' in result and isinstance(result['values'], list):
            compressed = {
                **result,
                'values': compress_array(result['values'], MAX_ARRAY_ITEMS, 'values'),
                '_compression': {
                    'original_size': get_size_str(original_size),
                    'tool': tool_name
                }
            }

        # Memory search pattern
        elif 'results' in result and isinstance(result['results'], list):
            compressed = {
                **result,
                'results': compress_array(result['results'], MAX_ARRAY_ITEMS, 'results'),
                '_compression': {
                    'original_size': get_size_str(original_size),
                    'tool': tool_name
                }
            }

        # Generic object compression
        else:
            compressed = compress_object(result, MAX_RESULT_CHARS)
            compressed['_compression'] = {
                'original_size': get_size_str(original_size),
                'tool': tool_name
            }

    elif isinstance(result, list):
        compressed = compress_array(result, MAX_ARRAY_ITEMS, 'root')

    elif isinstance(result, str):
        compressed = truncate_string(result, MAX_RESULT_CHARS)

    else:
        compressed = result

    compressed_size = len(json.dumps(compressed)) if compressed else 0
    savings = original_size - compressed_size
    savings_pct = (savings / original_size * 100) if original_size > 0 else 0

    log(f"Compressed {tool_name}: {get_size_str(original_size)} -> {get_size_str(compressed_size)} ({savings_pct:.1f}% reduction)")

    return {
        "compressed": True,
        "result": compressed,
        "original_size": original_size,
        "compressed_size": compressed_size,
        "savings_pct": round(savings_pct, 1)
    }


def main():
    """Process stdin and output compressed result."""
    try:
        # Read tool result from stdin
        input_data = sys.stdin.read()
        if not input_data.strip():
            return

        data = json.loads(input_data)

        # Extract tool name and result
        tool_name = data.get('tool_name', 'unknown')
        tool_result = data.get('tool_result', data.get('result', data))

        # Only process MCP tools
        if not tool_name.startswith('mcp__'):
            print(json.dumps(data))
            return

        # Compress if needed
        compression = compress_result(tool_name, tool_result)

        if compression['compressed']:
            # Output compressed result
            output = {
                **data,
                'tool_result': compression['result'],
                '_compressed': True,
                '_savings': f"{compression['savings_pct']}%"
            }
            print(json.dumps(output))
        else:
            # Pass through unchanged
            print(json.dumps(data))

    except json.JSONDecodeError:
        # Pass through non-JSON input
        print(input_data)
    except Exception as e:
        log(f"Error: {e}")
        # Pass through on error
        if 'input_data' in locals():
            print(input_data)


if __name__ == '__main__':
    main()
