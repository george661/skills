#!/usr/bin/env python3
"""
Resolve a command name to claude CLI arguments using model-routing.json + cost-strategy.json.

Usage:
    python3 resolve-model.py <command>          # outputs env vars + model flag
    python3 resolve-model.py <command> --json   # outputs JSON
    python3 resolve-model.py <command> --env    # outputs export statements

Examples:
    # Get claude CLI prefix for /implement
    eval $(python3 resolve-model.py implement --env) && claude --model "$CLAUDE_MODEL" -p "/implement PROJ-123"

    # Check what model a command would use
    python3 resolve-model.py work --json
"""

import json
import os
import sys

# Import the routing library (same directory)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from load_model_routing import load_routing, resolve_with_fallback


def resolve_command_env(command: str) -> dict:
    """Resolve a command to environment variables and model for claude CLI."""
    config = load_routing()
    result = resolve_with_fallback(config, command)

    env = {}
    model = result['model']

    if result['provider_type'] != 'bedrock':
        # Local/OpenAI-compatible provider (e.g., Ollama)
        base_url = result.get('base_url') or 'http://localhost:11434'
        env['ANTHROPIC_AUTH_TOKEN'] = 'ollama'
        env['ANTHROPIC_BASE_URL'] = base_url
        env['ANTHROPIC_API_KEY'] = ''
        # Strip provider prefix for claude --model flag
        # e.g., "qwen3-coder:30b" stays as-is for Ollama
        model = result['model']
    else:
        # Bedrock — no extra env vars needed, use the full model ID
        model = result['model']

    return {
        'env': env,
        'model': model,
        'alias': result['alias'],
        'provider': result['provider'],
        'provider_type': result['provider_type'],
        'is_local': result['is_local'],
        'cost_input': result['cost_input'],
        'cost_output': result['cost_output'],
        'fallback_from': result.get('_fallback_from'),
        'fallback_reason': result.get('_fallback_reason'),
    }


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <command> [--json|--env|--shell]", file=sys.stderr)
        sys.exit(1)

    command = sys.argv[1]
    output_format = sys.argv[2] if len(sys.argv) > 2 else '--env'

    result = resolve_command_env(command)

    if output_format == '--json':
        print(json.dumps(result, indent=2))
    elif output_format == '--env':
        # Output export statements for eval
        for k, v in result['env'].items():
            print(f'export {k}="{v}"')
        print(f'export CLAUDE_MODEL="{result["model"]}"')
        print(f'export CLAUDE_PROVIDER="{result["provider_type"]}"')
        print(f'export CLAUDE_IS_LOCAL="{1 if result["is_local"] else 0}"')
    elif output_format == '--shell':
        # Output a single-line env prefix for inline use
        parts = [f'{k}="{v}"' for k, v in result['env'].items()]
        prefix = ' '.join(parts)
        if prefix:
            print(f'{prefix} claude --model "{result["model"]}"')
        else:
            print(f'claude --model "{result["model"]}"')
    elif output_format == '--settings-json':
        # Output a --settings JSON string for claude CLI that overrides
        # CLAUDE_CODE_USE_BEDROCK and injects Ollama env vars.
        # This is the only reliable way to override settings.json env vars.
        if result['is_local']:
            settings = {
                'env': {
                    'CLAUDE_CODE_USE_BEDROCK': '',
                    'ANTHROPIC_AUTH_TOKEN': result['env'].get('ANTHROPIC_AUTH_TOKEN', 'ollama'),
                    'ANTHROPIC_BASE_URL': result['env'].get('ANTHROPIC_BASE_URL', 'http://localhost:11434'),
                    'ANTHROPIC_API_KEY': '',
                }
            }
        else:
            settings = {}
        print(json.dumps(settings))
    else:
        print(f"Unknown format: {output_format}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
