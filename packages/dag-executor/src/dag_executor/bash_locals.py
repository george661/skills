"""Bash script tokenizer for extracting local variable declarations."""

import re
from typing import Set


def extract_bash_locals(script: str) -> Set[str]:
    """
    Extract bash local variable names from a script.
    
    Covers common declaration patterns:
    - Simple assignment: name=value
    - For loops: for name in ...
    - While read: while read name
    - Read builtin: read name, read -r var1 var2
    - jq --arg declarations: jq --arg var_name "$source"
    
    Returns names declared in the script. False negatives (missed locals)
    are acceptable; false positives (declaring non-locals) must be zero.
    """
    locals_set: Set[str] = set()
    
    # Pattern 1: Simple assignment (name=value at line start or after whitespace)
    # Matches: foo=bar, FOO_BAR=baz, status=$(...)
    assignment_pattern = r'(?:^|\s)([A-Za-z_][A-Za-z0-9_]*)='
    for match in re.finditer(assignment_pattern, script, re.MULTILINE):
        locals_set.add(match.group(1))
    
    # Pattern 1b: jq --arg / --argjson variable_name "$source"
    # jq's `--arg` and `--argjson` both bind a filter-local name; references
    # inside the filter (e.g. `$name`) must stay literal so jq can expand them.
    jq_arg_pattern = r'--arg(?:json)?\s+([A-Za-z_][A-Za-z0-9_]*)\s+'
    for match in re.finditer(jq_arg_pattern, script):
        locals_set.add(match.group(1))
    
    # Pattern 2: For loop variable (for name in ...)
    for_pattern = r'\bfor\s+([A-Za-z_][A-Za-z0-9_]*)\s+in\b'
    for match in re.finditer(for_pattern, script):
        locals_set.add(match.group(1))

    # Pattern 2b: C-style for loop — for ((name=expr; ...; ...))
    # Captures the initializer variable; `((name=expr))` also matches as a
    # standalone arithmetic expression which is fine (same variable kind).
    c_for_pattern = r'\bfor\s+\(\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*='
    for match in re.finditer(c_for_pattern, script):
        locals_set.add(match.group(1))
    
    # Pattern 3: While read (while read name)
    while_read_pattern = r'\bwhile\s+read\s+([A-Za-z_][A-Za-z0-9_]*)'
    for match in re.finditer(while_read_pattern, script):
        locals_set.add(match.group(1))
    
    # Pattern 4: Read builtin (read name, read -r var1 var2)
    # Captures all variable names after read, optionally with -r flag
    read_pattern = r'\bread\s+(?:-r\s+)?([A-Za-z_][A-Za-z0-9_]*(?:\s+[A-Za-z_][A-Za-z0-9_]*)*)'
    for match in re.finditer(read_pattern, script):
        # Split multiple vars (e.g., "read -r var1 var2")
        vars_str = match.group(1)
        for var in vars_str.split():
            if re.match(r'^[A-Za-z_][A-Za-z0-9_]*$', var):
                locals_set.add(var)
    
    return locals_set
