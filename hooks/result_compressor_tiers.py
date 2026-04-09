#!/usr/bin/env python3
"""
Tier-aware threshold helpers for result-compressor.py.

Reads the active command from ~/.claude/.active-command and determines
the model tier from ~/.claude/config/model-routing.json. Returns
appropriate compression thresholds for each tier.
"""

import json
import os

TIER_THRESHOLDS = {
    "haiku":  {"max_array": 10, "max_total": 4000},
    "sonnet": {"max_array": 15, "max_total": 6000},
    "opus":   {"max_array": 20, "max_total": 8000},
}

ACTIVE_COMMAND_FILE = os.path.expanduser('~/.claude/.active-command')
MODEL_ROUTING_FILE = os.path.expanduser('~/.claude/config/model-routing.json')


def get_tier_thresholds(tier: str) -> dict:
    """Get compression thresholds for a model tier.

    Returns opus thresholds for unknown tiers.
    """
    return TIER_THRESHOLDS.get(tier, TIER_THRESHOLDS['opus'])


def get_active_tier(config: dict = None, active_command_path: str = ACTIVE_COMMAND_FILE) -> str:
    """Determine the active model tier.

    Reads the active command name from the tracking file, then looks up
    its tier in the model routing config. Returns 'opus' as fallback.
    """
    # Read active command
    command_name = ''
    try:
        with open(active_command_path, 'r') as f:
            command_name = f.read().strip()
    except (FileNotFoundError, OSError):
        return 'opus'

    if not command_name:
        return 'opus'

    # Load config if not provided
    if config is None:
        try:
            with open(MODEL_ROUTING_FILE, 'r') as f:
                config = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return 'opus'

    # Look up command tier
    cmd_config = config.get('commands', {}).get(command_name)
    if cmd_config and isinstance(cmd_config, dict):
        return cmd_config.get('main', config.get('defaults', {}).get('main', 'opus'))

    return config.get('defaults', {}).get('main', 'opus')
