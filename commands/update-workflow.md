<!-- MODEL_TIER: opus -->
<!-- DISPATCH: false -->

---
description: Update workflow commands and skills using plain English descriptions
arguments:
  - name: description
    description: Plain English description of the desired workflow change
    required: true
---

# Update Workflow: $ARGUMENTS.description

## Overview

Accepts a plain English description of a workflow change, identifies the affected command or skill,
determines ownership (base-agents vs agents), applies the change following the correct submodule
protocol, verifies installation, and updates WORKFLOW.md if the pipeline structure changed.

---

## Phase 0: Parse Intent

Read the canonical workflow reference:

```bash
cat $PROJECT_ROOT/agents/WORKFLOW.md
```

Match the user's description against the command inventory in WORKFLOW.md. Identify:
- Which command(s) or skill(s) are affected
- What type of change is needed (modify existing, create new, remove)
- Whether this affects pipeline structure (new commands, removed commands, new phases)

If the description is ambiguous and could apply to multiple commands, list the candidates and ask
the user to clarify before proceeding.

---

## Phase 1: Determine Ownership

For each affected file, check its location to determine the correct change workflow:

```bash
# Check if file exists in base-agents (project-agnostic)
ls $PROJECT_ROOT/base-agents/.claude/commands/{command}.md 2>/dev/null
ls $PROJECT_ROOT/base-agents/.claude/skills/{skill}/ 2>/dev/null

# Check if file exists in agents (project-specific)
ls $PROJECT_ROOT/agents/.claude/commands/{command}.md 2>/dev/null
ls $PROJECT_ROOT/agents/.claude/skills/{skill}/ 2>/dev/null
```

**Ownership rules:**
- `base-agents/.claude/commands/` -> base-agents change (project-agnostic commands)
- `base-agents/.claude/skills/` -> base-agents change (project-agnostic skills)
- `agents/.claude/commands/` -> agents change (project-specific commands)
- `agents/.claude/skills/` -> agents change (project-specific skills)
- **New file?** Ask: "Is this change project-agnostic (works for any tenant) or project-specific?"
  - Project-agnostic -> base-agents
  - project-specific -> agents

---

## Phase 2: Execute Change

Both paths use a **worktree + PR workflow**. Changes go through review and CI before landing on main.
Direct commits to main are prohibited — the `enforce-worktree.sh` hook will block them.

### Branch Naming

Derive a slug from the description (no Jira key needed for workflow changes):

```bash
SLUG=$(echo "{short description of change}" | tr '[:upper:]' '[:lower:]' | tr ' ' '-' | tr -cd '[:alnum:]-' | cut -c1-40)
BRANCH="workflow-update/${SLUG}"
WORKTREE_DIR="${BRANCH//\//-}"   # e.g. workflow-update-add-branch-sync
```

---

### Path A: base-agents Change

**MANDATORY: Follow the submodule protocol exactly.**

1. **Create worktree from origin/main:**
   ```bash
   cd $PROJECT_ROOT/base-agents
   git fetch origin main
   git worktree add $PROJECT_ROOT/worktrees/base-agents/${WORKTREE_DIR} -b ${BRANCH} origin/main
   ```

2. **Make edits inside the worktree:**
   ```bash
   cd $PROJECT_ROOT/worktrees/base-agents/${WORKTREE_DIR}
   # Edit the target command or skill file here
   ```

3. **Run tests (if applicable):**
   ```bash
   cd $PROJECT_ROOT/worktrees/base-agents/${WORKTREE_DIR}
   # For skills with tests:
   npx vitest run .claude/skills/{integration}/__tests__/ 2>/dev/null || echo "No tests found"
   # For command changes, verify markdown structure:
   grep -c "^##\|^###" .claude/commands/{command}.md
   ```

4. **Commit and push:**
   ```bash
   cd $PROJECT_ROOT/worktrees/base-agents/${WORKTREE_DIR}
   git add -A
   git commit -m "{descriptive commit message}"
   git push -u origin ${BRANCH}
   ```

5. **Create PR:**
   ```bash
   cd $PROJECT_ROOT && npx tsx .claude/skills/vcs/create_pull_request.ts \
     "{\"repo\": \"base-agents\", \"title\": \"{title}\", \"description\": \"{description}\", \"source_branch\": \"${BRANCH}\", \"destination_branch\": \"main\"}"
   ```

6. **Run `/review base-agents <pr_number>`** — inline in this session, do not dispatch.

7. **Run `/resolve-pr`** once CI passes and review is approved.

8. **After merge — update submodule reference in agents:**
   ```bash
   cd $PROJECT_ROOT/agents
   git submodule update --remote base
   git add base
   git commit -m "chore: update base-agents submodule (${SLUG})"
   git push
   ```

9. **Clean up worktree:**
   ```bash
   cd $PROJECT_ROOT/base-agents
   git worktree remove $PROJECT_ROOT/worktrees/base-agents/${WORKTREE_DIR} --force
   git push origin --delete ${BRANCH} 2>/dev/null || true
   ```

10. **Run update.sh to install:**
    ```bash
    cd $PROJECT_ROOT && agents/scripts/update.sh --local --force
    ```

---

### Path B: agents Change

1. **Create worktree from origin/main:**
   ```bash
   cd $PROJECT_ROOT/agents
   git fetch origin main
   git worktree add $PROJECT_ROOT/worktrees/agents/${WORKTREE_DIR} -b ${BRANCH} origin/main
   ```

2. **Make edits inside the worktree:**
   ```bash
   cd $PROJECT_ROOT/worktrees/agents/${WORKTREE_DIR}
   # Edit the target command or skill file here
   ```

3. **Run tests (if applicable):**
   ```bash
   cd $PROJECT_ROOT/worktrees/agents/${WORKTREE_DIR}
   npx vitest run .claude/skills/{integration}/__tests__/ 2>/dev/null || echo "No tests found"
   ```

4. **Commit and push:**
   ```bash
   cd $PROJECT_ROOT/worktrees/agents/${WORKTREE_DIR}
   git add -A
   git commit -m "{descriptive commit message}"
   git push -u origin ${BRANCH}
   ```

5. **Create PR:**
   ```bash
   cd $PROJECT_ROOT && npx tsx .claude/skills/vcs/create_pull_request.ts \
     "{\"repo\": \"agents\", \"title\": \"{title}\", \"description\": \"{description}\", \"source_branch\": \"${BRANCH}\", \"destination_branch\": \"main\"}"
   ```

6. **Run `/review agents <pr_number>`** — inline in this session, do not dispatch.

7. **Run `/resolve-pr`** once CI passes and review is approved.

8. **Clean up worktree:**
   ```bash
   cd $PROJECT_ROOT/agents
   git worktree remove $PROJECT_ROOT/worktrees/agents/${WORKTREE_DIR} --force
   git push origin --delete ${BRANCH} 2>/dev/null || true
   ```

9. **Run update.sh to install:**
   ```bash
   cd $PROJECT_ROOT && agents/scripts/update.sh --local --force
   ```

---

## Phase 3: Verify Installation

Confirm the changed files are installed at `~/.claude/`:

```bash
# For commands:
ls ~/.claude/commands/{command}.md && echo "INSTALLED" || echo "MISSING"

# For skills:
ls ~/.claude/skills/{integration}/{skill}.ts && echo "INSTALLED" || echo "MISSING"
```

If any file is MISSING after `update.sh --local`, investigate the installation script and fix
before proceeding.

---

## Phase 4: Update WORKFLOW.md (if pipeline structure changed)

If the change added, removed, or renamed a command or skill, or modified the pipeline phase
structure:

1. Read current WORKFLOW.md:
   ```bash
   cat $PROJECT_ROOT/agents/WORKFLOW.md
   ```

2. Update the relevant section to reflect the change:
   - Add new command entries with: command name, short description, location, model tier
   - Remove entries for deleted commands
   - Update descriptions for modified commands
   - Update pipeline flow diagrams if phase ordering changed

3. Commit the WORKFLOW.md update:
   ```bash
   cd $PROJECT_ROOT/agents
   git add WORKFLOW.md
   git commit -m "Update WORKFLOW.md to reflect workflow changes"
   git push
   ```

If the change did NOT affect pipeline structure (e.g., internal logic fix, prompt improvement),
skip this phase.

---

## Phase 5: Store Episode in AgentDB

Record the workflow change for pattern learning:

```bash
cd $PROJECT_ROOT && npx tsx .claude/skills/agentdb/reflexion_store_episode.ts '{"session_id": "${TENANT_NAMESPACE}", "task": "update-workflow: $ARGUMENTS.description", "reward": 1.0, "success": true, "critique": "Changed {files_changed}. Ownership: {base-agents|agents}. Pipeline structure changed: {yes|no}."}'
```

---

## Completion

Print summary:

```
/update-workflow complete

Description:    $ARGUMENTS.description
Files changed:  {list of files}
Ownership:      {base-agents | agents}
Installed at:   {~/.claude/ paths}
WORKFLOW.md:    {updated | no change needed}
```
