#!/usr/bin/env python3
"""
Command overlay system for tenant-specific command customizations.

This system allows tenants to:
1. Override entire commands with tenant-specific versions
2. Extend base commands with tenant-specific additions
3. Configure which commands are available for their tenant

Overlay sources (in priority order):
1. Routing config commandOverlays section
2. Tenant-specific directory: config/commands/{tenant}/
3. Base commands: .claude/commands/

Usage:
    # Check available overlays for a command
    python load-command-overlays.py list

    # Get effective command content (base + overlay)
    python load-command-overlays.py get <command-name>

    # Sync overlays to commands directory (for local dev)
    python load-command-overlays.py sync
"""

import json
import os
import sys
from pathlib import Path


def find_config_file() -> Path | None:
    """Find the tenant configuration file."""
    if env_path := os.environ.get('APPCONFIG_BACKUP_FILE'):
        path = Path(env_path)
        if path.exists():
            return path
        rel_path = Path.cwd() / env_path
        if rel_path.exists():
            return rel_path

    container_path = Path('/config/routing.json')
    if container_path.exists():
        return container_path

    current = Path.cwd()
    for parent in [current] + list(current.parents):
        if (parent / '.claude' / 'hooks').exists():
            sibling_configs = [
                parent.parent / 'issue-daemon' / 'config' / 'routing.gw.json',
                parent.parent / 'issue-daemon' / 'config' / 'routing.json',
            ]
            for config_path in sibling_configs:
                if config_path.exists():
                    return config_path
            break

    return None


def load_config(config_path: Path) -> dict:
    """Load routing configuration."""
    with open(config_path) as f:
        return json.load(f)


def get_overlay_config(config: dict) -> dict:
    """Extract command overlay configuration from routing config."""
    agent = config.get('agent', {})
    return {
        'tenant': config.get('tenant', 'default'),
        'overlays': agent.get('commandOverlays', {}),
        'disabled': agent.get('disabledCommands', []),
        'aliases': agent.get('commandAliases', {}),
    }


def find_overlay_directory(config_path: Path, tenant: str) -> Path | None:
    """Find tenant-specific command overlay directory."""
    # Check for commands directory in config folder
    config_dir = config_path.parent
    overlay_dirs = [
        config_dir / 'commands' / tenant,
        config_dir / 'commands',
    ]

    for overlay_dir in overlay_dirs:
        if overlay_dir.exists() and overlay_dir.is_dir():
            return overlay_dir

    return None


def list_overlays(config_path: Path, config: dict) -> dict:
    """List all available command overlays."""
    overlay_config = get_overlay_config(config)
    tenant = overlay_config['tenant']

    result = {
        'tenant': tenant,
        'config_overlays': list(overlay_config['overlays'].keys()),
        'disabled_commands': overlay_config['disabled'],
        'aliases': overlay_config['aliases'],
        'file_overlays': [],
    }

    # Check for file-based overlays
    overlay_dir = find_overlay_directory(config_path, tenant)
    if overlay_dir:
        result['overlay_directory'] = str(overlay_dir)
        result['file_overlays'] = [
            f.stem for f in overlay_dir.glob('*.md')
        ]

    return result


def get_command_overlay(command_name: str, config_path: Path, config: dict) -> dict:
    """Get the effective content for a command including any overlays."""
    overlay_config = get_overlay_config(config)
    tenant = overlay_config['tenant']

    result = {
        'command': command_name,
        'tenant': tenant,
        'source': 'base',
        'overlay_type': None,
        'content': None,
    }

    # Check if command is disabled
    if command_name in overlay_config['disabled']:
        result['disabled'] = True
        return result

    # Check for alias
    if command_name in overlay_config['aliases']:
        result['alias_for'] = overlay_config['aliases'][command_name]
        command_name = overlay_config['aliases'][command_name]

    # Check for config-based overlay (inline content or file reference)
    if command_name in overlay_config['overlays']:
        overlay = overlay_config['overlays'][command_name]
        result['overlay_type'] = 'config'

        if isinstance(overlay, str):
            # Direct content
            result['content'] = overlay
            result['source'] = 'config_inline'
        elif isinstance(overlay, dict):
            if 'file' in overlay:
                # File reference
                overlay_file = config_path.parent / overlay['file']
                if overlay_file.exists():
                    result['content'] = overlay_file.read_text()
                    result['source'] = 'config_file'
            elif 'append' in overlay:
                # Append to base command
                result['append'] = overlay['append']
                result['source'] = 'config_append'
            elif 'prepend' in overlay:
                result['prepend'] = overlay['prepend']
                result['source'] = 'config_prepend'

        return result

    # Check for file-based overlay
    overlay_dir = find_overlay_directory(config_path, tenant)
    if overlay_dir:
        overlay_file = overlay_dir / f'{command_name}.md'
        if overlay_file.exists():
            result['content'] = overlay_file.read_text()
            result['source'] = 'file_overlay'
            result['overlay_type'] = 'file'
            return result

    # No overlay found - use base
    result['source'] = 'base'
    return result


def sync_overlays(config_path: Path, config: dict, commands_dir: Path) -> list:
    """Sync overlays to the commands directory (for local development)."""
    overlay_config = get_overlay_config(config)
    tenant = overlay_config['tenant']
    synced = []

    overlay_dir = find_overlay_directory(config_path, tenant)
    if not overlay_dir:
        return synced

    for overlay_file in overlay_dir.glob('*.md'):
        command_name = overlay_file.stem
        target = commands_dir / f'{command_name}.md'

        # Create backup if target exists
        if target.exists():
            backup = commands_dir / f'{command_name}.md.base'
            if not backup.exists():
                backup.write_text(target.read_text())

        # Copy overlay to commands directory
        target.write_text(overlay_file.read_text())
        synced.append(command_name)

    return synced


def main():
    if len(sys.argv) < 2:
        print("Usage: load-command-overlays.py <list|get|sync> [command-name]")
        sys.exit(1)

    action = sys.argv[1]

    config_path = find_config_file()
    if not config_path:
        print("No tenant configuration found", file=sys.stderr)
        sys.exit(1)

    config = load_config(config_path)

    if action == 'list':
        result = list_overlays(config_path, config)
        print(json.dumps(result, indent=2))

    elif action == 'get':
        if len(sys.argv) < 3:
            print("Usage: load-command-overlays.py get <command-name>")
            sys.exit(1)
        command_name = sys.argv[2]
        result = get_command_overlay(command_name, config_path, config)
        print(json.dumps(result, indent=2))

    elif action == 'sync':
        commands_dir = Path(__file__).parent.parent / 'commands'
        synced = sync_overlays(config_path, config, commands_dir)
        print(f"Synced {len(synced)} overlays: {', '.join(synced)}")

    else:
        print(f"Unknown action: {action}")
        sys.exit(1)


if __name__ == '__main__':
    main()
