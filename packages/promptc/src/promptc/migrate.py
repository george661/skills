"""Legacy command format to promptc migration tool.

This module provides best-effort conversion from the legacy YAML frontmatter
command format to the new promptc format. It is a one-way preprocessor that
emits promptc source code to stdout without modifying the original file.

Conversion Rules:
- YAML frontmatter description → {% meta description="..." doc_type="command" /%}
- YAML arguments → {% input name="..." type="string" ... /%} per argument
- <!-- MODEL_TIER: X --> comment → tier="X" attribute on {% meta %}
- $ARGUMENTS.foo → {% $inputs.foo %}
- ## Phase N: Name → {% phase name="Name" %}...{% /phase %}
- Unconvertible sections → preserved with <!-- TODO(promptc-migrate): ... --> comment
"""

import re
from pathlib import Path
from typing import Any, Dict, List, Optional


def _parse_frontmatter(text: str) -> tuple[Optional[Dict[str, Any]], str, List[str]]:
    """Parse YAML frontmatter and return (metadata, body, warnings).

    Returns:
        - metadata dict (or None if no frontmatter)
        - body text after frontmatter
        - list of warning messages for unconvertible sections
    """
    warnings: List[str] = []

    # Check for frontmatter delimiters
    if not text.startswith('---\n') and not text.startswith('---\r\n'):
        return None, text, warnings

    # Find the closing delimiter
    lines = text.split('\n')
    end_idx = -1
    for i in range(1, len(lines)):
        if lines[i].strip() == '---':
            end_idx = i
            break

    if end_idx == -1:
        raise ValueError("Frontmatter not properly closed with '---'")

    frontmatter_lines = lines[1:end_idx]
    body_lines = lines[end_idx + 1:]

    # Parse simple YAML frontmatter manually
    # We only need to handle: description, arguments (list of dicts)
    metadata: Dict[str, Any] = {}
    in_arguments = False
    arguments: List[Dict[str, Any]] = []
    current_arg: Optional[Dict[str, Any]] = None

    for line in frontmatter_lines:
        stripped = line.strip()

        # Skip empty lines
        if not stripped:
            continue

        # Check for top-level key
        if not line.startswith(' ') and not line.startswith('\t'):
            if ':' in line:
                key, value = line.split(':', 1)
                key = key.strip()
                value = value.strip()

                if key == 'arguments':
                    in_arguments = True
                    continue
                else:
                    in_arguments = False
                    # Handle quoted strings
                    if value:
                        # Check for unclosed quotes first
                        if (value.startswith('"') and not value.endswith('"')) or \
                           (value.startswith("'") and not value.endswith("'")):
                            raise ValueError(f"Unclosed quote in frontmatter value: {line}")

                        # Strip matched quotes
                        if (value.startswith('"') and value.endswith('"')) or \
                           (value.startswith("'") and value.endswith("'")):
                            value = value[1:-1]
                        metadata[key] = value
        else:
            # Indented line
            if in_arguments:
                if stripped.startswith('- name:'):
                    # Start a new argument
                    if current_arg:
                        arguments.append(current_arg)
                    current_arg = {}
                    name = stripped.split(':', 1)[1].strip()
                    if name.startswith('"') and name.endswith('"'):
                        name = name[1:-1]
                    current_arg['name'] = name
                elif current_arg is not None:
                    # Parse argument properties
                    if ':' in stripped:
                        key, value = stripped.split(':', 1)
                        key = key.strip()
                        value = value.strip()

                        if value.startswith('"') and value.endswith('"'):
                            value = value[1:-1]

                        # Handle boolean values
                        arg_value: Any
                        if value.lower() in ('true', 'false'):
                            arg_value = value.lower() == 'true'
                        else:
                            arg_value = value

                        current_arg[key] = arg_value

    # Add the last argument if any
    if current_arg:
        arguments.append(current_arg)

    if arguments:
        metadata['arguments'] = arguments

    # Check for unknown keys and warn
    known_keys = {'description', 'arguments'}
    for key in metadata.keys():
        if key not in known_keys:
            warnings.append(f"Unknown frontmatter key '{key}' (preserved in output)")

    return metadata, '\n'.join(body_lines), warnings


def _extract_model_tier(text: str) -> tuple[Optional[str], str]:
    """Extract MODEL_TIER comment and return (tier, text_without_comment)."""
    match = re.search(r'<!--\s*MODEL_TIER:\s*(\w+)\s*-->', text)
    if match:
        tier = match.group(1)
        # Remove the comment from text
        text = re.sub(r'<!--\s*MODEL_TIER:\s*\w+\s*-->\s*', '', text)
        return tier, text
    return None, text


def _convert_arguments_refs(text: str) -> str:
    """Convert $ARGUMENTS.foo to {% $inputs.foo %}."""
    return re.sub(r'\$ARGUMENTS\.(\w+)', r'{% $inputs.\1 %}', text)


def _split_phases(body: str) -> tuple[str, List[tuple[str, str]]]:
    """Split body into preamble and list of (phase_name, phase_body) tuples."""
    lines = body.split('\n')

    preamble_lines: List[str] = []
    phases: List[tuple[str, str]] = []
    current_phase_name: Optional[str] = None
    current_phase_lines: List[str] = []

    phase_pattern = re.compile(r'^##\s+Phase\s+\d+:\s+(.+)$')

    for line in lines:
        match = phase_pattern.match(line)
        if match:
            # Found a phase heading
            if current_phase_name:
                # Save the previous phase
                phases.append((current_phase_name, '\n'.join(current_phase_lines).strip()))

            current_phase_name = match.group(1).strip()
            current_phase_lines = []
        else:
            if current_phase_name:
                current_phase_lines.append(line)
            else:
                preamble_lines.append(line)

    # Save the last phase
    if current_phase_name:
        phases.append((current_phase_name, '\n'.join(current_phase_lines).strip()))

    preamble = '\n'.join(preamble_lines).strip()
    return preamble, phases


def migrate_text(source: str) -> str:
    """Convert legacy command format to promptc format.

    Args:
        source: Legacy command text with YAML frontmatter

    Returns:
        Promptc-formatted text

    Raises:
        ValueError: If frontmatter is malformed
    """
    # Extract MODEL_TIER comment
    tier, source = _extract_model_tier(source)

    # Parse frontmatter
    metadata, body, warnings = _parse_frontmatter(source)

    if metadata is None:
        # No frontmatter, just convert arguments
        body = _convert_arguments_refs(source)
        return body

    # Build output
    output_lines: List[str] = []

    # Build {% meta %} tag
    meta_attrs = []
    if 'description' in metadata:
        desc = metadata['description'].replace('"', '\\"')
        meta_attrs.append(f'description="{desc}"')
    meta_attrs.append('doc_type="command"')
    if tier:
        meta_attrs.append(f'tier="{tier}"')

    output_lines.append("{{% meta {} /%}}".format(' '.join(meta_attrs)))
    output_lines.append("")

    # Build {% input %} tags
    if 'arguments' in metadata:
        for arg in metadata['arguments']:
            input_attrs = []
            input_attrs.append(f'name="{arg["name"]}"')
            input_attrs.append('type="string"')

            if 'required' in arg and arg['required'] is True:
                input_attrs.append('required="true"')
            # Omit required="false" as it's the default

            if 'description' in arg:
                desc = arg['description'].replace('"', '\\"')
                input_attrs.append(f'description="{desc}"')

            output_lines.append("{{% input {} /%}}".format(' '.join(input_attrs)))

        output_lines.append("")

    # Add warnings for unknown keys
    if warnings:
        for warning in warnings:
            output_lines.append(f"<!-- TODO(promptc-migrate): {warning} -->")
        output_lines.append("")

    # Process body: convert arguments and split into phases
    body = _convert_arguments_refs(body)
    preamble, phases = _split_phases(body)

    # Add preamble
    if preamble:
        output_lines.append(preamble)
        output_lines.append("")

    # Add phases
    for phase_name, phase_body in phases:
        output_lines.append("{{% phase name=\"{}\" %}}".format(phase_name))
        output_lines.append("")
        output_lines.append(phase_body)
        output_lines.append("")
        output_lines.append("{% /phase %}")
        output_lines.append("")

    return '\n'.join(output_lines).strip() + '\n'


def migrate_file(path: str) -> str:
    """Migrate a legacy command file and return the promptc output.

    This function NEVER modifies the original file. It only reads and returns
    the converted output.

    Args:
        path: Path to the legacy command file

    Returns:
        Promptc-formatted text

    Raises:
        FileNotFoundError: If file doesn't exist
        ValueError: If frontmatter is malformed
    """
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    source = file_path.read_text()
    return migrate_text(source)
