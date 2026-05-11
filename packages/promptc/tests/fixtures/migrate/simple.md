<!-- MODEL_TIER: local -->
---
description: A simple test command
arguments:
  - name: issue
    description: Issue key
    required: true
  - name: optional_arg
    description: Optional argument
---

# Test Command

This is a test using $ARGUMENTS.issue and $ARGUMENTS.optional_arg.

## Phase 1: Setup

Do some setup work.

## Phase 2: Execute

Run the $ARGUMENTS.issue task.
