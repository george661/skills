#!/usr/bin/env python3
"""
Model Routing Config Loader (v3)

Provider-agnostic routing: resolves command → model alias → provider + model ID + base_url.
Supports any OpenAI-compatible endpoint (Ollama, OpenRouter, Zhipu, etc.) plus AWS Bedrock.

Config files:
  - model-routing.json: providers, models, defaults, command→alias mappings
  - cost-strategy.json: profiles that override command→alias mappings

Usage:
    from load_model_routing import load_routing, resolve_command

    routing = load_routing()
    result = resolve_command(routing, 'implement')
    # → {'alias': 'qwen3-32b', 'provider': 'ollama', 'model': 'qwen3:32b',
    #    'base_url': 'http://localhost:11434/v1', 'is_local': True,
    #    'api_key_env': None, 'cost_input': 0, 'cost_output': 0}
"""

import json
import os
import urllib.request



ROUTING_PATH = os.path.expanduser('~/.claude/config/model-routing.json')

DEFAULT_ROUTING = {
    "version": 3,
    "providers": {
        "bedrock": {"type": "bedrock"}
    },
    "models": {
        "opus": {"provider": "bedrock", "model": "anthropic.claude-opus-4-5-20251101-v1:0"},
        "sonnet": {"provider": "bedrock", "model": "anthropic.claude-sonnet-4-20250514-v1:0"},
        "haiku": {"provider": "bedrock", "model": "anthropic.claude-haiku-4-5-20250514-v1:0"},
    },
    "defaults": {"main": "opus", "subagent": "sonnet", "exploration": "haiku", "fallback": "haiku"},
    "commands": {}
}


def _load_json(path: str, default: dict) -> dict:
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, PermissionError):
        return dict(default)


def load_routing(routing_path: str = ROUTING_PATH) -> dict:
    """Load model routing config with active profile applied."""
    config = _load_json(routing_path, DEFAULT_ROUTING)

    # Ensure required sections
    config.setdefault('providers', DEFAULT_ROUTING['providers'])
    config.setdefault('models', DEFAULT_ROUTING['models'])
    config.setdefault('defaults', DEFAULT_ROUTING['defaults'])
    config.setdefault('commands', {})

    # Apply active profile overrides (profiles live in the same file)
    active = config.get('active_profile')
    profiles = config.get('profiles', {})
    if active and active in profiles and active != 'default':
        overrides = profiles[active].get('overrides', {})
        for cmd, model_alias in overrides.items():
            # Overrides are simple: command → model alias string
            if isinstance(model_alias, str):
                config['commands'].setdefault(cmd, {})['main'] = model_alias
            elif isinstance(model_alias, dict):
                config['commands'].setdefault(cmd, {}).update(model_alias)

    config['_active_profile'] = active or 'default'
    return config


def get_command_alias(config: dict, command: str) -> str:
    """Get the model alias for a command. Follows 'inherit' references."""
    cmd_config = config.get('commands', {}).get(command)
    if cmd_config and isinstance(cmd_config, dict):
        if 'inherit' in cmd_config:
            return get_command_alias(config, cmd_config['inherit'])
        return cmd_config.get('main', config['defaults']['main'])
    return config['defaults']['main']


def get_subagent_aliases(config: dict, command: str) -> dict:
    """Get subagent alias map for a command."""
    cmd_config = config.get('commands', {}).get(command)
    if cmd_config and isinstance(cmd_config, dict):
        if 'inherit' in cmd_config:
            return get_subagent_aliases(config, cmd_config['inherit'])
        return cmd_config.get('subagents', {})
    return {}


def resolve_alias(config: dict, alias: str) -> dict:
    """Resolve a model alias to full provider + model + endpoint info.

    Returns:
        {
            'alias': str,          # e.g. 'qwen3-32b'
            'provider': str,       # e.g. 'ollama'
            'provider_type': str,  # e.g. 'openai' or 'bedrock'
            'model': str,          # e.g. 'qwen3:32b'
            'base_url': str|None,  # e.g. 'http://localhost:11434/v1'
            'api_key_env': str|None, # env var name for API key
            'is_local': bool,
            'cost_input': float,   # per million tokens
            'cost_output': float,  # per million tokens
            'capabilities': list,
        }
    """
    models = config.get('models', {})
    providers = config.get('providers', {})

    model_entry = models.get(alias)
    if not model_entry or not isinstance(model_entry, dict):
        # Legacy v2 compat: bare string model IDs (e.g. "opus": "anthropic.claude-...")
        if isinstance(model_entry, str):
            return {
                'alias': alias,
                'provider': 'bedrock',
                'provider_type': 'bedrock',
                'model': model_entry,
                'base_url': None,
                'api_key_env': None,
                'is_local': False,
                'cost_input': 0,
                'cost_output': 0,
                'capabilities': [],
            }
        # Unknown alias — fall back to defaults.fallback
        fallback = config.get('defaults', {}).get('fallback', 'haiku')
        if fallback != alias:
            return resolve_alias(config, fallback)
        return {
            'alias': alias, 'provider': 'unknown', 'provider_type': 'unknown',
            'model': alias, 'base_url': None, 'api_key_env': None,
            'is_local': False, 'cost_input': 0, 'cost_output': 0, 'capabilities': [],
        }

    provider_name = model_entry.get('provider', 'bedrock')
    provider = providers.get(provider_name, {})
    provider_type = provider.get('type', 'bedrock')

    # Cost: model-level overrides provider-level
    cost_input = model_entry.get('cost_per_million_input', provider.get('cost_per_million_input', 0))
    cost_output = model_entry.get('cost_per_million_output', provider.get('cost_per_million_output', 0))

    return {
        'alias': alias,
        'provider': provider_name,
        'provider_type': provider_type,
        'model': model_entry.get('model', alias),
        'base_url': model_entry.get('base_url', provider.get('base_url')),
        'api_key_env': model_entry.get('api_key_env', provider.get('api_key_env')),
        'is_local': cost_input == 0 and cost_output == 0 and provider_type != 'bedrock',
        'cost_input': cost_input,
        'cost_output': cost_output,
        'capabilities': model_entry.get('capabilities', []),
    }


def resolve_command(config: dict, command: str) -> dict:
    """Resolve a command name to full model routing info."""
    alias = get_command_alias(config, command)
    return resolve_alias(config, alias)


def check_provider_health(config: dict, provider_name: str, timeout: float = 2.0) -> bool:
    """Check if a provider endpoint is reachable.

    Uses the provider's health_check URL if defined, otherwise tries base_url.
    Bedrock is always considered healthy (auth is handled by IAM).
    """
    provider = config.get('providers', {}).get(provider_name, {})
    if provider.get('type') == 'bedrock':
        return True

    health_url = provider.get('health_check', provider.get('base_url'))
    if not health_url:
        return False

    try:
        req = urllib.request.Request(health_url, method='GET')
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def resolve_with_fallback(config: dict, command: str) -> dict:
    """Resolve command to model, falling back if provider is unhealthy."""
    result = resolve_command(config, command)

    if result['provider_type'] != 'bedrock':
        if not check_provider_health(config, result['provider']):
            fallback_alias = config.get('defaults', {}).get('fallback', 'haiku')
            fallback = resolve_alias(config, fallback_alias)
            fallback['_fallback_from'] = result['alias']
            fallback['_fallback_reason'] = f"provider '{result['provider']}' unreachable"
            return fallback

    return result


def get_validation_loop_config(config: dict) -> dict:
    """Legacy: validation loop config. Returns disabled."""
    return {'enabled': False}


def merge_configs(base: dict, tenant: dict) -> dict:
    """Merge base and tenant routing configs. Tenant overrides base."""
    merged = {
        "version": max(base.get("version", 3), tenant.get("version", 3)),
        "providers": {**base.get("providers", {}), **tenant.get("providers", {})},
        "models": {**base.get("models", {}), **tenant.get("models", {})},
        "defaults": {**base.get("defaults", {}), **tenant.get("defaults", {})},
        "commands": {**base.get("commands", {}), **tenant.get("commands", {})},
    }
    return merged


# --- Legacy compatibility (v2) ---

def get_command_tier(config: dict, command: str) -> str:
    """Legacy: get the model alias for a command. Use get_command_alias() instead."""
    return get_command_alias(config, command)

def get_model_id(config: dict, tier: str) -> str:
    """Legacy: resolve alias to model ID string. Use resolve_alias() instead."""
    result = resolve_alias(config, tier)
    return result['model']

def get_local_model(config: dict, role: str) -> str:
    """Legacy: get local model by role. Use resolve_alias() with the alias name instead."""
    # Map old role names to v3 aliases
    role_to_alias = {
        'coding': 'qwen3-32b', 'coding_fast': 'qwen3-8b',
        'coder': 'qwen-coder-32b', 'coder_fast': 'qwen-coder-7b',
        'reasoning': 'deepseek-r1-32b', 'reasoning_fast': 'deepseek-r1-8b',
        'tool_calling': 'glm-flash', 'embedding': 'nomic-embed',
    }
    alias = role_to_alias.get(role, role)
    result = resolve_alias(config, alias)
    return result['model']

def get_local_base_url(config: dict) -> str:
    """Legacy: get Ollama base URL. Use resolve_alias()['base_url'] instead."""
    return config.get('providers', {}).get('ollama', {}).get('base_url', 'http://localhost:11434/v1')

def resolve_tier(config: dict, tier: str) -> dict:
    """Legacy: resolve tier to model info. Use resolve_alias() instead."""
    result = resolve_alias(config, tier)
    return {'model': result['model'], 'is_local': result['is_local'], 'base_url': result['base_url']}

# Back-compat: load_model_routing still works
def load_model_routing(path: str = ROUTING_PATH) -> dict:
    """Legacy: load config without strategy. Use load_routing() instead."""
    return _load_json(path, DEFAULT_ROUTING)
