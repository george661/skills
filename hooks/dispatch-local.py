#!/usr/bin/env python3
"""
dispatch-local.py — Single source of truth for dispatching commands to local Ollama model.

Called by:
  1. route-slash-command.py (hook) — when intercepting Skill/SlashCommand
  2. /work orchestrator (via Bash) — when dispatching sub-commands

Usage:
  python3 ~/.claude/hooks/dispatch-local.py <command-name> <args...>

Output: result to stdout, progress to /dev/tty
"""

import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

# --- Constants ---
OLLAMA_API_KEY = (
    "sk-ant-api03-ollama"
    "000000000000000000000000000000000000000000000000000000000000"
    "000000000000000000-00000000AA"
)
OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_MODEL = "global.anthropic.claude-sonnet-4-20250514-v1:0"
def _get_project_root() -> str:
    """Resolve project root from environment or tenant env file, with dynamic fallback."""
    for k in ("WORKSPACE_ROOT", "PROJECT_ROOT"):
        v = os.environ.get(k, "").rstrip("/")
        if v:
            return v
    try:
        with open("/tmp/tenant.env") as _f:
            for _l in _f:
                _l = _l.strip()
                for _prefix in ("export WORKSPACE_ROOT=", "WORKSPACE_ROOT=",
                                "export PROJECT_ROOT=", "PROJECT_ROOT="):
                    if _l.startswith(_prefix):
                        _v = _l[len(_prefix):].strip().strip('"\'').rstrip("/")
                        if _v:
                            return _v
    except OSError:
        pass
    # Walk up from cwd looking for a directory that contains sdk/ (project workspace marker)
    d = Path.cwd()
    while d != d.parent:
        if (d / "sdk").is_dir():
            return str(d)
        d = d.parent
    # Last resort: probe common workspace layouts under $HOME
    home = Path.home()
    for rel in ("dev/gw", "projects/gw", "${TENANT_NAMESPACE}"):
        candidate = home / rel
        if (candidate / "sdk").is_dir():
            return str(candidate)
    return str(home / "dev" / "${TENANT_NAMESPACE}")  # best-guess default


PROJECT_ROOT = _get_project_root()
# DOTENV_PATH: prefer TENANT_DOTENV_PATH from tenant env, fall back to $PROJECT_ROOT/.env
DOTENV_PATH = (
    os.environ.get("TENANT_DOTENV_PATH", "").strip()
    or os.path.join(PROJECT_ROOT, ".env")
)
TENANT_ENV_PATH = "/tmp/tenant.env"


def _load_tenant_env() -> dict[str, str]:
    """Load tenant env vars from /tmp/tenant.env (written by load-tenant-config.py at session start)."""
    values = {}
    try:
        with open(TENANT_ENV_PATH) as f:
            for line in f:
                line = line.strip()
                if line.startswith("export ") and "=" in line:
                    kv = line[len("export "):]
                    key, _, val = kv.partition("=")
                    values[key.strip()] = val.strip().strip('"')
    except OSError:
        pass
    return values


TENANT_ENV = _load_tenant_env()


def progress(msg):
    """Print progress to terminal."""
    line = f"[Ollama] {msg}"
    try:
        with open("/dev/tty", "w") as tty:
            tty.write(f"\r\033[K{line}\n")
            tty.flush()
    except OSError:
        print(line, file=sys.stderr, flush=True)


def _extract_infra_requirements(plan_text: str) -> str:
    """
    Scan plan text for infra patterns the implement model commonly skips.
    Returns a formatted bullet block if anything found, else empty string.
    """
    import re
    lines = []

    # os.Getenv("VAR") calls → env var must be in variables.tf + all tfvars files
    env_vars = re.findall(r'os\.Getenv\(["\']([A-Z_][A-Z0-9_]*)["\']', plan_text)
    if env_vars:
        unique_vars = sorted(set(env_vars))
        lines.append(
            "Env vars that MUST be added to variables.tf AND every tfvars file: "
            + ", ".join(unique_vars)
        )

    # Explicit tfvars filenames mentioned — every one must be touched
    tfvars_files = re.findall(r'\b([\w.-]+\.tfvars)\b', plan_text)
    if tfvars_files:
        unique_tvars = sorted(set(tfvars_files))
        lines.append(
            "Tfvars files named in plan — ALL must be updated: "
            + ", ".join(unique_tvars)
        )

    # IAM policy change — add GSI reminder
    if re.search(
        r'\b(iam_policy|aws_iam|IAM policy|lambda.*execution.*policy|policy.*lambda)\b',
        plan_text, re.IGNORECASE
    ):
        lines.append(
            'IAM policy change required — include BOTH table_arn AND'
            ' "${table_arn}/index/*" for any DynamoDB GSI access'
        )
    elif re.search(r'\b(DynamoDB|dynamo_db|GSI|global.secondary)\b', plan_text, re.IGNORECASE):
        lines.append(
            'DynamoDB access detected — if IAM change needed, add both'
            ' table_arn and "${table_arn}/index/*" for GSI queries'
        )

    return "\n".join(f"- {l}" for l in lines) + "\n" if lines else ""


def enrich_prompt(command_name, args):
    """Build command-specific context to append to the prompt."""
    extra = ""
    issue_key = args.split()[0] if args.strip() else ""

    if command_name == "fix-pr" and issue_key:
        # Parse optional repo and pr_number from args: "PROJ-123 my-repo 49"
        parts = args.split()
        repo = parts[1] if len(parts) > 1 else ""
        pr_number = parts[2] if len(parts) > 2 else ""

        # Fallback to checkpoint if not provided as args
        if not repo or not pr_number:
            try:
                cp_result = subprocess.run(
                    ["python3", os.path.expanduser("~/.claude/hooks/checkpoint.py"),
                     "load", issue_key],
                    capture_output=True, text=True, timeout=10, cwd=PROJECT_ROOT
                )
                if cp_result.returncode == 0:
                    cp = json.loads(cp_result.stdout)
                    if cp.get("found"):
                        data = cp.get("checkpoint", {}).get("data", {})
                        repo = repo or data.get("repo", "")
                        pr_number = pr_number or data.get("pr_number", "")
            except Exception:
                pass

        if repo and pr_number:
            extra += f"\n\nPR CONTEXT (pre-fetched):\n- Repo: {repo}\n- PR number: {pr_number}\n"

            # Pre-fetch worktree path so the model doesn't waste time searching
            worktree_path = os.path.join(PROJECT_ROOT, "worktrees", f"{repo}-{issue_key}")
            if os.path.isdir(worktree_path):
                extra += f"- Worktree: {worktree_path}\n"

                # Pre-fetch changed files for validation tier classification
                try:
                    diff_result = subprocess.run(
                        ["git", "diff", "--name-only", "origin/main"],
                        capture_output=True, text=True, timeout=10, cwd=worktree_path
                    )
                    if diff_result.returncode == 0 and diff_result.stdout.strip():
                        changed = diff_result.stdout.strip()
                        extra += f"\nCHANGED FILES (use for validation tier classification):\n{changed}\n"
                except Exception:
                    pass

            try:
                comments_result = subprocess.run(
                    ["npx", "tsx",
                     os.path.expanduser("~/.claude/skills/bitbucket/list_pull_request_comments.ts"),
                     json.dumps({"repo_slug": repo, "pull_request_id": int(pr_number)})],
                    capture_output=True, text=True, timeout=30, cwd=PROJECT_ROOT
                )
                if comments_result.returncode == 0 and comments_result.stdout.strip():
                    comments_text = comments_result.stdout.strip()
                    if len(comments_text) > 4000:
                        comments_text = comments_text[:4000] + "\n...(truncated)"
                    extra += f"\nPR REVIEW COMMENTS (address each one):\n{comments_text}\n"
            except Exception:
                pass

    if command_name == "resolve-pr" and issue_key:
        # resolve-pr only takes issue key — pre-fetch repo + PR from checkpoint or Bitbucket
        parts = args.split()
        repo = parts[1] if len(parts) > 1 else ""
        pr_number = parts[2] if len(parts) > 2 else ""

        if not repo or not pr_number:
            try:
                cp_result = subprocess.run(
                    ["python3", os.path.expanduser("~/.claude/hooks/checkpoint.py"),
                     "load", issue_key],
                    capture_output=True, text=True, timeout=10, cwd=PROJECT_ROOT
                )
                if cp_result.returncode == 0:
                    cp = json.loads(cp_result.stdout)
                    if cp.get("found"):
                        for phase_data in reversed(cp.get("checkpoints", [])):
                            data = phase_data.get("data", {})
                            repo = repo or data.get("repo", "")
                            pr_number = pr_number or str(data.get("pr_number", ""))
                            if repo and pr_number:
                                break
            except Exception:
                pass

        # If checkpoint didn't have it, try scanning Bitbucket for open PRs on the repo
        if repo and not pr_number:
            try:
                pr_list = subprocess.run(
                    ["npx", "tsx",
                     os.path.expanduser("~/.claude/skills/bitbucket/list_pull_requests.ts"),
                     json.dumps({"repo_slug": repo, "state": "OPEN"})],
                    capture_output=True, text=True, timeout=30, cwd=PROJECT_ROOT
                )
                if pr_list.returncode == 0:
                    prs = json.loads(pr_list.stdout)
                    for pr in prs.get("values", []):
                        if issue_key.lower() in (pr.get("source", {}).get("branch", {}).get("name", "") or "").lower():
                            pr_number = str(pr["id"])
                            break
            except Exception:
                pass

        if repo and pr_number:
            _ws = TENANT_ENV.get("WORKSPACE_ROOT", PROJECT_ROOT).rstrip("/")
            extra += (
                f"\n\nPR CONTEXT (pre-fetched — use these values, do NOT search for them):\n"
                f"- Repo: {repo}\n"
                f"- PR number: {pr_number}\n"
                f"- Merge command: cd {_ws} && npx tsx ~/.claude/skills/bitbucket/merge_pull_request.ts "
                f"'{{\"repo_slug\": \"{repo}\", \"pull_request_id\": {pr_number}}}'\n"
                f"- Worktree path: {_ws}/worktrees/{repo}-{issue_key}\n"
            )

    if command_name == "implement":
        extra += (
            "\n\nCRITICAL REMINDERS:\n"
            "- ALWAYS create .gitignore before npm install (include node_modules/, dist/, .env, *.log, coverage/)\n"
            "- NEVER commit node_modules/ — verify with: git ls-files --cached | grep node_modules\n"
            "- NEVER modify go.mod Go version — if go mod tidy changes it, revert: git checkout go.mod\n"
            "- NEVER stage files not listed in the plan's 'Files to Change' — run git status\n"
            "  before staging and remove any unplanned files before committing\n"
            "- Run pre-push guardrails from the implement.md instructions before pushing\n"
        )

        # Auto-detect worktree path and plan context for /implement
        if issue_key:
            worktree_path = ""
            repo = ""
            branch = ""
            workspace_root = TENANT_ENV.get("WORKSPACE_ROOT", "").rstrip("/") or PROJECT_ROOT

            # 1. Try checkpoint
            try:
                cp_result = subprocess.run(
                    ["python3", os.path.expanduser("~/.claude/hooks/checkpoint.py"),
                     "load", issue_key],
                    capture_output=True, text=True, timeout=10, cwd=workspace_root
                )
                if cp_result.returncode == 0:
                    cp = json.loads(cp_result.stdout)
                    if cp.get("found"):
                        for phase_data in reversed(cp.get("checkpoints", [])):
                            data = phase_data.get("data", {})
                            worktree_path = worktree_path or data.get("worktree", "")
                            repo = repo or data.get("repo", "")
                            branch = branch or data.get("branch", "")
                            if worktree_path:
                                break
            except Exception:
                pass

            # 2. Scan worktrees/{repo}/PROJ-XXX-name (two-level) then top-level fallback
            if not worktree_path:
                worktrees_dir = os.path.join(workspace_root, "worktrees")
                if os.path.isdir(worktrees_dir):
                    # Check top level first (legacy single-level layout)
                    for entry in os.listdir(worktrees_dir):
                        if issue_key in entry:
                            candidate = os.path.join(worktrees_dir, entry)
                            if os.path.isdir(candidate):
                                worktree_path = candidate
                                break
                    # Then check one level deeper: worktrees/{repo}/{branch}
                    if not worktree_path:
                        for repo_dir in os.listdir(worktrees_dir):
                            repo_subdir = os.path.join(worktrees_dir, repo_dir)
                            if not os.path.isdir(repo_subdir):
                                continue
                            for entry in os.listdir(repo_subdir):
                                if issue_key in entry:
                                    candidate = os.path.join(repo_subdir, entry)
                                    if os.path.isdir(candidate):
                                        worktree_path = candidate
                                        repo = repo or repo_dir
                                        break
                            if worktree_path:
                                break

            # 3. Read .agent-context.json from worktree
            if worktree_path and os.path.isdir(worktree_path):
                ctx_file = os.path.join(worktree_path, ".agent-context.json")
                if os.path.isfile(ctx_file):
                    try:
                        with open(ctx_file) as f:
                            ctx = json.loads(f.read())
                        repo = repo or ctx.get("repo", "")
                        branch = branch or ctx.get("branch", "")
                    except Exception:
                        pass

                extra += (
                    f"\n\nWORKTREE CONTEXT (pre-fetched — cd here FIRST):\n"
                    f"- Worktree: {worktree_path}\n"
                    f"- Repo: {repo}\n"
                    f"- Branch: {branch}\n"
                )

            # 4. Read plan review findings from Jira comments
            # Include both the APPROVED verdict AND any prior review with investigation leads
            # (e.g., NEEDS_FIXES comments contain root cause leads the implement agent should use)
            if issue_key:
                try:
                    jira_result = subprocess.run(
                        ["npx", "tsx",
                         os.path.expanduser("~/.claude/skills/jira/get_issue.ts"),
                         json.dumps({"issue_key": issue_key, "fields": "comment"})],
                        capture_output=True, text=True, timeout=30, cwd=workspace_root
                    )
                    if jira_result.returncode == 0:
                        jira_data = json.loads(jira_result.stdout)
                        comments = jira_data.get("fields", {}).get("comment", {}).get("comments", [])

                        review_findings = []
                        revised_plan = ""

                        for comment in comments:
                            body = comment.get("body", {})
                            text = ""
                            if isinstance(body, dict):
                                for block in body.get("content", []):
                                    for inline in block.get("content", []):
                                        text += inline.get("text", "")

                            # Capture review findings (Critical/Warning leads from any verdict)
                            if "Implementation Plan Review" in text and "Findings" in text:
                                review_findings.append(text)

                            # Capture the latest revised plan
                            if "REVISED IMPLEMENTATION PLAN" in text:
                                revised_plan = text

                        # Include revised plan if available
                        if revised_plan and len(revised_plan) < 4000:
                            extra += f"\n\nREVISED PLAN (from Jira — follow this):\n{revised_plan}\n"
                        elif review_findings:
                            # Fall back to latest APPROVED review
                            for text in reversed(review_findings):
                                if "Verdict: APPROVED" in text and len(text) < 4000:
                                    extra += f"\n\nPLAN REVIEW (from Jira — use this as the plan):\n{text}\n"
                                    break

                        # Always include review findings with investigation leads
                        # (these contain root cause hypotheses the implement agent should start from)
                        for text in review_findings:
                            if "Critical" in text and "Verdict: APPROVED" not in text and len(text) < 3000:
                                extra += f"\n\nREVIEW FINDINGS (investigation leads — start from these):\n{text}\n"
                                break

                        # 5. Extract infra requirements from plan text so model can't miss them
                        plan_text = revised_plan
                        if not plan_text:
                            for t in reversed(review_findings):
                                if "Verdict: APPROVED" in t:
                                    plan_text = t
                                    break
                        if plan_text:
                            infra_block = _extract_infra_requirements(plan_text)
                            if infra_block:
                                extra += (
                                    "\n\nINFRA REQUIREMENTS (extracted from plan — implement ALL of these):\n"
                                    + infra_block
                                )
                except Exception:
                    pass

    if command_name in ("validate-deploy-status", "validate-run-tests",
                         "validate-collect-evidence"):
        # Pre-fetch issue context so local model doesn't waste tokens re-fetching
        # NOTE: validate-evaluate and validate-transition run inline on Opus — no enrichment needed
        if issue_key:
            # deploy-status only needs status+labels; run-tests/collect-evidence need full issue
            fields = "summary,status,labels" if command_name == "validate-deploy-status" else "status,labels,description,comment"
            try:
                issue_result = subprocess.run(
                    ["npx", "tsx",
                     os.path.expanduser("~/.claude/skills/jira/get_issue.ts"),
                     json.dumps({"issue_key": issue_key, "fields": fields})],
                    capture_output=True, text=True, timeout=30, cwd=PROJECT_ROOT
                )
                if issue_result.returncode == 0 and issue_result.stdout.strip():
                    issue_text = issue_result.stdout.strip()
                    if len(issue_text) > 4000:
                        issue_text = issue_text[:4000] + "\n...(truncated)"
                    extra += f"\nISSUE CONTEXT (pre-fetched):\n{issue_text}\n"
            except Exception:
                pass

        # --- Load Phase 0.6 visual impact checkpoint ---
        # The Opus orchestrator saves has_visual_effects + ui_paths after reading the issue
        # description. We use this to drive Playwright coverage for ALL repos (not just UI repos).
        ui_paths: list = []
        has_visual_effects = True  # default: assume visual unless checkpoint says otherwise
        if issue_key and command_name in ("validate-run-tests", "validate-collect-evidence"):
            try:
                cp_result = subprocess.run(
                    ["python3", os.path.expanduser("~/.claude/hooks/checkpoint.py"),
                     "load", issue_key],
                    capture_output=True, text=True, timeout=10, cwd=PROJECT_ROOT
                )
                if cp_result.returncode == 0:
                    cp = json.loads(cp_result.stdout)
                    if cp.get("found"):
                        for phase_data in cp.get("checkpoints", []):
                            data = phase_data.get("data", {})
                            if "has_visual_effects" in data:
                                has_visual_effects = data["has_visual_effects"]
                            if "ui_paths" in data:
                                ui_paths = data["ui_paths"]
            except Exception:
                pass

        # --- Embedded instructions per sub-command (primary instruction delivery) ---
        # Local models follow short imperative prompts better than long .md reference docs.
        # The .md files still exist for human reference. These blocks are the contract.

        # Extract args beyond issue_key for phases that receive repo/env_url
        extra_args = args.split() if args else []
        repo_arg = extra_args[1] if len(extra_args) > 1 else ""
        env_url_arg = extra_args[2] if len(extra_args) > 2 else TENANT_ENV.get("TENANT_APP_URL_DEV", "")

        _dev_url = TENANT_ENV.get("TENANT_APP_URL_DEV", "(not configured)")
        _demo_url = TENANT_ENV.get("TENANT_APP_URL_DEMO", "(not configured)")
        _prod_url = TENANT_ENV.get("TENANT_APP_URL_PROD", "(not configured)")

        if command_name == "validate-deploy-status":
            extra += f"""
YOUR TASK: Check if {issue_key} code is deployed to the target environment.

STEPS:
1. From the ISSUE CONTEXT above, find the repository:
   a. Look for a label starting with `repo-` (e.g., repo-lambda-functions → repo is lambda-functions)
   b. If NO repo-* label exists, parse the repo name from square brackets in the issue title
      (e.g., "[lambda-functions] Fix X" → repo is lambda-functions)
   c. If neither works, STOP and output DEPLOY_STATUS: UNKNOWN
2. Check the Concourse pipeline for that repo:
   ```bash
   cd {PROJECT_ROOT} && npx tsx ~/.claude/skills/fly/list_builds.ts '{{"pipeline": "<repo>", "count": 5}}'
   ```
   Look for the most recent build. Status "succeeded" = deployed.
3. Determine environment from env-* labels on the issue (default: dev).
   - dev → {_dev_url}
   - demo → {_demo_url}
   - prod → {_prod_url}

OUTPUT FORMAT (the orchestrator parses these exact lines — you MUST include them):
```
DEPLOY_STATUS: DEPLOYED | FAILED | IN_PROGRESS | UNKNOWN
REPO: <repo-name>
PIPELINE: <pipeline-name>
BUILD_ID: <id>
BUILD_STATUS: <status>
ENV_URL: <full URL>
```
"""

        elif command_name == "validate-run-tests":
            # Build the Playwright block: always include when has_visual_effects is true
            _env = env_url_arg.split("//")[-1].split(".")[0] if env_url_arg else "dev"
            if has_visual_effects:
                _paths_to_check = ui_paths if ui_paths else ["(infer from issue description)"]
                _paths_display = "\n   ".join(f"- {p}" for p in _paths_to_check)
                playwright_block = f"""
   - PLAYWRIGHT (required — has_visual_effects=true): Visit these pages with authenticated browser:
   {_paths_display}
     ```bash
     # Get auth token first
     TOKEN=$(node ~/.claude/skills/cognito-srp-token.js "$EMAIL" "$PASSWORD" {_env})
     # Console check — detects JS errors on authenticated pages
     cd {PROJECT_ROOT} && npx tsx ~/.claude/skills/playwright/console-check.ts \
       '{{"url": "{env_url_arg}<path>", "auth": {{"env": "{_env}", "role": "admin"}}, "failOnError": true}}'
     # Screenshot — captures visual state of the page
     cd {PROJECT_ROOT} && npx tsx ~/.claude/skills/playwright/screenshot.ts \
       '{{"url": "{env_url_arg}<path>", "outputPath": "/tmp/validate-{issue_key}-<name>.png", "auth": {{"env": "{_env}", "role": "admin"}}}}'
     ```
     CRITICAL: Check `authRedirectDetected` in output — if true, mark criterion FAIL (login page ≠ evidence)."""
            else:
                playwright_block = "\n   - (Playwright skipped — has_visual_effects=false for this issue)"

            extra += f"""
YOUR TASK: Run validation tests for {issue_key} against {env_url_arg}.
Repository: {repo_arg}

VISUAL IMPACT: has_visual_effects={has_visual_effects}, ui_paths={ui_paths}

STEPS:
1. From the ISSUE CONTEXT above, extract the **Validation Criteria** from the description
   or comments. Each criterion is a testable assertion.
1.5. ALWAYS obtain an auth token before testing API or UI endpoints:
   ```bash
   if [ ! -f $WORKSPACE_ROOT/e2e-tests/tests/fixtures/testData.json ]; then
     cd $WORKSPACE_ROOT/e2e-tests && npm install --silent && npm run test-data:download
   fi
   CREDS=$(cat $WORKSPACE_ROOT/e2e-tests/tests/fixtures/testData.json | jq -r '[.[] | select(.role == "org_admin")][0] | "\\(.email) \\(.password) \\(.orgId)"')
   EMAIL=$(echo "$CREDS" | awk '{{print $1}}')
   PASSWORD=$(echo "$CREDS" | awk '{{print $2}}')
   ORG_ID=$(echo "$CREDS" | awk '{{print $3}}')
   TOKEN=$(node ~/.claude/skills/cognito-srp-token.js "$EMAIL" "$PASSWORD" {_env})
   ```
2. For each criterion, run a test:{playwright_block}
   - API criteria: curl with Bearer token: curl -s -w '\\nHTTP %{{http_code}}' -H "Authorization: Bearer $TOKEN" -H "X-Organization-Id: $ORG_ID" {env_url_arg}/api/<path>
   - Infrastructure criteria: use AWS CLI
3. Write ALL results to /tmp/validate-{issue_key}-test-results.txt

OUTPUT FORMAT (the orchestrator parses these exact lines — you MUST include them):
```
TEST_RESULTS_START
CRITERION: <criterion text from Jira>
RESULT: PASS | FAIL
EVIDENCE: <what you observed — HTTP status, response body snippet, screenshot path, error>
AUTHENTICATED: true | false
---
TEST_RESULTS_END
PASSED: <N>
FAILED: <M>
TOTAL: <N+M>
AUTH_STATUS: AUTHENTICATED | AUTH_FAILED | AUTH_NOT_REQUIRED
```

Write this same block to /tmp/validate-{issue_key}-test-results.txt.
"""

        elif command_name == "validate-collect-evidence":
            _env = env_url_arg.split("//")[-1].split(".")[0] if env_url_arg else "dev"
            if has_visual_effects:
                _paths_to_check = ui_paths if ui_paths else ["(infer from issue description)"]
                _paths_display = "\n   ".join(f"- {p}" for p in _paths_to_check)
                playwright_block = f"""
2. PLAYWRIGHT SCREENSHOTS (required — has_visual_effects=true): For EACH of these pages:
   {_paths_display}
   Collect authenticated screenshots AND console errors:
   ```bash
   cd {PROJECT_ROOT} && npx tsx ~/.claude/skills/playwright/screenshot.ts \
     '{{"url": "{env_url_arg}<path>", "outputPath": "/tmp/validate-{issue_key}-<name>.png", "auth": {{"env": "{_env}", "role": "admin"}}}}'
   cd {PROJECT_ROOT} && npx tsx ~/.claude/skills/playwright/console-check.ts \
     '{{"url": "{env_url_arg}<path>", "auth": {{"env": "{_env}", "role": "admin"}}, "failOnError": false}}'
   ```
   CRITICAL: Check `authRedirectDetected` in output — if true, mark EVIDENCE_QUALITY INSUFFICIENT.
   Do NOT accept a login page screenshot as evidence of the feature working."""
            else:
                playwright_block = "\n2. (Playwright screenshots skipped — has_visual_effects=false for this issue)"

            extra += f"""
YOUR TASK: Collect evidence artifacts for {issue_key} validation report.
Repository: {repo_arg}, Environment: {env_url_arg}

VISUAL IMPACT: has_visual_effects={has_visual_effects}, ui_paths={ui_paths}

STEPS:
1. Collect build logs:
   ```bash
   cd {PROJECT_ROOT} && npx tsx ~/.claude/skills/fly/list_builds.ts '{{"pipeline": "{repo_arg}", "count": 1}}'
   ```
{playwright_block}
3. If API repo (lambda-functions) or any backend with API endpoints: capture API responses with curl (use auth token from testData.json via cognito-srp-token.js)
4. If infra repo (core-infra): capture relevant CloudWatch logs
5. Write manifest to /tmp/validate-{issue_key}-evidence.txt

EVIDENCE QUALITY RULES:
- INSUFFICIENT: code snippets, unit test counts, PR merge confirmation, OR screenshots of login pages
- SUFFICIENT: at least one authenticated runtime artifact (screenshot, curl with 200, CloudWatch log)
- STRONG: multiple authenticated artifacts covering happy path and error cases

OUTPUT FORMAT (the orchestrator parses these exact lines — you MUST include them):
```
EVIDENCE_START
TYPE: screenshot | api_response | log | build_log
PATH: /tmp/validate-{issue_key}-<name>.<ext>
DESCRIPTION: <what this evidence shows>
AUTHENTICATED: true | false
---
EVIDENCE_END
ARTIFACT_COUNT: <N>
RUNTIME_EVIDENCE_COUNT: <N>
AUTHENTICATED_EVIDENCE_COUNT: <N>
EVIDENCE_QUALITY: STRONG | SUFFICIENT | INSUFFICIENT
AUTH_STATUS: AUTHENTICATED | AUTH_FAILED | AUTH_NOT_REQUIRED
```

Write this same block to /tmp/validate-{issue_key}-evidence.txt.
"""

    if command_name == "create-implementation-plan" and issue_key:
        # Resolve effective project root from tenant config (overrides hardcoded PROJECT_ROOT)
        workspace_root = TENANT_ENV.get("WORKSPACE_ROOT", "").rstrip("/") or PROJECT_ROOT

        # Pre-fetch issue labels to detect target repo without trusting description text
        repo = ""
        try:
            issue_result = subprocess.run(
                ["npx", "tsx", os.path.expanduser("~/.claude/skills/jira/get_issue.ts"),
                 json.dumps({"issue_key": issue_key, "fields": "labels,summary"})],
                capture_output=True, text=True, timeout=30, cwd=workspace_root
            )
            if issue_result.returncode == 0:
                issue_data = json.loads(issue_result.stdout)
                labels = issue_data.get("fields", {}).get("labels", [])
                for label in labels:
                    if label.startswith("repo-"):
                        repo = label[len("repo-"):]
                        break
        except Exception:
            pass

        if repo:
            extra += f"\n\nTARGET REPO (from Jira label): {repo}\n"
            repo_path = os.path.join(workspace_root, repo)

            if repo == "e2e-tests" and os.path.isdir(repo_path):
                # Pre-fetch actual POM and journey directories — prevents wrong path in plan
                pages_dir = os.path.join(repo_path, "pages")
                journeys_dir = os.path.join(repo_path, "tests", "journeys")
                try:
                    if os.path.isdir(pages_dir):
                        pages = sorted(os.listdir(pages_dir))
                        extra += (
                            f"\nACTUAL pages/ DIRECTORY ({len(pages)} files"
                            " — use these exact paths in plan):\n"
                            + "\n".join(f"  pages/{p}" for p in pages[:30]) + "\n"
                            + "NOTE: POM files live in pages/ — never tests/page-objects/ or similar.\n"
                        )
                    if os.path.isdir(journeys_dir):
                        journeys = sorted(os.listdir(journeys_dir))
                        extra += (
                            f"\nACTUAL tests/journeys/ DOMAINS:\n"
                            + "\n".join(f"  tests/journeys/{j}" for j in journeys) + "\n"
                        )
                except Exception:
                    pass

            elif repo == "lambda-functions" and os.path.isdir(repo_path):
                functions_dir = os.path.join(repo_path, "functions")
                try:
                    if os.path.isdir(functions_dir):
                        fns = sorted(
                            f for f in os.listdir(functions_dir)
                            if os.path.isdir(os.path.join(functions_dir, f))
                        )
                        extra += (
                            f"\nACTUAL functions/ DIRECTORY ({len(fns)} functions):\n"
                            + "\n".join(f"  functions/{f}" for f in fns) + "\n"
                        )
                        # tfvars per function — exposes exact env count before plan is written
                        tfvars_lines = []
                        for fn_name in fns:
                            tf_dir = os.path.join(functions_dir, fn_name, "terraform")
                            if os.path.isdir(tf_dir):
                                tvars = sorted(
                                    f for f in os.listdir(tf_dir) if f.endswith(".tfvars")
                                )
                                if tvars:
                                    tfvars_lines.append(
                                        f"  {fn_name}: {len(tvars)} tfvars"
                                        f" ({', '.join(tvars)})"
                                    )
                        if tfvars_lines:
                            extra += (
                                "\nTFVARS COUNT PER FUNCTION"
                                " (plan MUST address ALL envs for each affected function):\n"
                                + "\n".join(tfvars_lines) + "\n"
                            )
                except Exception:
                    pass

                extra += (
                    "\n\nINFRA COMPLETENESS (MANDATORY for lambda-functions plans):\n"
                    "- If Go code calls os.Getenv(\"VAR\"), add that var to:"
                    " variables.tf AND every tfvars file listed above\n"
                    "- DynamoDB IAM: policy needs BOTH table_arn AND"
                    " \"${table_arn}/index/*\" for any GSI queries\n"
                    "- Before writing 'add X to all envs', grep each env's existing"
                    " tfvars to verify what's already present\n"
                    "- 'Files to Change' in plan MUST list each tfvars file explicitly"
                    " (not 'all environments')\n"
                )

            elif repo in ("core-infra", "bootstrap") and os.path.isdir(repo_path):
                tf_envs_dir = os.path.join(repo_path, "terraform", "environments")
                try:
                    if os.path.isdir(tf_envs_dir):
                        envs = sorted(os.listdir(tf_envs_dir))
                        extra += (
                            f"\nACTUAL terraform/environments/ ({len(envs)} envs):"
                            f" {', '.join(envs)}\n"
                            f"NOTE: Plan must address ALL {len(envs)} environments"
                            " unless issue explicitly scopes to fewer.\n"
                        )
                except Exception:
                    pass

                extra += (
                    "\n\nINFRA COMPLETENESS (MANDATORY for core-infra plans):\n"
                    "- Before writing 'add X to all envs', grep each env's main.tf —"
                    " some may already have the change\n"
                    "- DynamoDB IAM: policy needs BOTH table ARN AND"
                    " index ARN (\"${table_arn}/index/*\") for any GSI queries\n"
                    "- 'Files to Change' in plan MUST list each environment file explicitly\n"
                )

            elif repo == "frontend-app" and os.path.isdir(repo_path):
                src_dir = os.path.join(repo_path, "src")
                try:
                    for sub in ("pages", "components", "store", "types"):
                        sub_dir = os.path.join(src_dir, sub)
                        if os.path.isdir(sub_dir):
                            entries = sorted(os.listdir(sub_dir))
                            extra += (
                                f"\nACTUAL src/{sub}/ ({len(entries)} items):\n"
                                + "\n".join(f"  src/{sub}/{e}" for e in entries[:20]) + "\n"
                            )
                except Exception:
                    pass

    # Global CI infrastructure context — injected into ALL dispatched commands
    # Reads TENANT_CI_PROVIDER from tenant config (default: concourse)
    ci_provider = os.environ.get("TENANT_CI_PROVIDER") or TENANT_ENV.get("TENANT_CI_PROVIDER", "concourse")
    if ci_provider == "concourse":
        extra += (
            "\n\nCI INFRASTRUCTURE (CRITICAL):\n"
            "- CI is **Concourse**, NOT Bitbucket Pipelines. NEVER look for pipelines on Bitbucket.\n"
            "- Pipeline names match repo names (e.g., frontend-app, lambda-functions, core-infra).\n"
            f"- Check CI status: cd {PROJECT_ROOT} && npx tsx ~/.claude/skills/fly/wait_for_build.ts "
            "'{{\"pipeline\": \"<repo>\", \"timeout_seconds\": 60}}'\n"
            "- Get build logs: npx tsx ~/.claude/skills/fly/watch_build.ts '{\"build_id\": <id>}'\n"
            "- List builds: npx tsx ~/.claude/skills/fly/list_builds.ts '{\"pipeline\": \"<repo>\"}'\n"
        )
    elif ci_provider == "github-actions":
        extra += (
            "\n\nCI INFRASTRUCTURE (CRITICAL):\n"
            "- CI is **GitHub Actions**. Check workflow runs via `gh run list` and `gh run view`.\n"
            "- Do NOT look for Bitbucket Pipelines or Concourse builds.\n"
        )
    elif ci_provider == "bitbucket-pipelines":
        extra += (
            "\n\nCI INFRASTRUCTURE (CRITICAL):\n"
            "- CI is **Bitbucket Pipelines**. Check pipeline status via Bitbucket API.\n"
        )

    return extra


def _prefetch_worktree_map(worktree_path):
    """Build a lightweight directory map of the worktree so the model knows where to find things."""
    if not worktree_path or not os.path.isdir(worktree_path):
        return ""

    parts = []

    # Changed files relative to main (the most important signal)
    try:
        diff_result = subprocess.run(
            ["git", "diff", "--name-only", "origin/main"],
            capture_output=True, text=True, timeout=10, cwd=worktree_path
        )
        changed = diff_result.stdout.strip().splitlines() if diff_result.returncode == 0 else []
    except Exception:
        changed = []

    if changed:
        parts.append("CHANGED FILES (vs origin/main):\n" + "\n".join(f"  {f}" for f in changed))

    # Directory tree (depth 2, dirs only for structure; files only at depth 1)
    tree_lines = []
    try:
        for entry in sorted(os.listdir(worktree_path)):
            full = os.path.join(worktree_path, entry)
            if entry.startswith(".") or entry == "node_modules":
                continue
            if os.path.isfile(full):
                size = os.path.getsize(full)
                lines = 0
                if size < 500_000:
                    try:
                        with open(full, "rb") as fh:
                            lines = sum(1 for _ in fh)
                    except OSError:
                        pass
                tree_lines.append(f"  {entry}  ({lines} lines)" if lines else f"  {entry}")
            elif os.path.isdir(full):
                sub_count = 0
                try:
                    sub_count = len([e for e in os.listdir(full)
                                     if not e.startswith(".")])
                except OSError:
                    pass
                tree_lines.append(f"  {entry}/  ({sub_count} items)")
    except OSError:
        pass

    if tree_lines:
        parts.append("DIRECTORY LAYOUT:\n" + "\n".join(tree_lines))

    # Key structural files — just names + first few lines (signatures only)
    for fname in ("go.mod", "package.json", "Makefile", "tsconfig.json"):
        fpath = os.path.join(worktree_path, fname)
        if os.path.isfile(fpath):
            try:
                with open(fpath) as fh:
                    head = "".join(fh.readline() for _ in range(5))
                parts.append(f"{fname} (first 5 lines):\n{head.rstrip()}")
            except OSError:
                pass

    if not parts:
        return ""

    return (
        "\n\nWORKTREE MAP (use this to plan file reads — do NOT re-read changed files you already have):\n"
        + "\n\n".join(parts)
        + "\n"
    )


def build_env():
    """Build clean environment for the subprocess."""
    env = {
        "HOME": os.environ.get("HOME", ""),
        "PATH": os.environ.get("PATH", ""),
        "TERM": os.environ.get("TERM", "xterm-256color"),
        "SHELL": os.environ.get("SHELL", "/bin/bash"),
        "ANTHROPIC_API_KEY": OLLAMA_API_KEY,
        "ANTHROPIC_BASE_URL": OLLAMA_BASE_URL,
        "CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS": "1",
        "CLAUDE_SUBPROCESS": "1",
    }

    # AWS credentials (needed for SSM fallback in skills)
    for var in ("AWS_PROFILE", "AWS_REGION", "AWS_DEFAULT_REGION",
                "AWS_CONFIG_FILE", "AWS_SHARED_CREDENTIALS_FILE"):
        val = os.environ.get(var)
        if val:
            env[var] = val
    env.setdefault("AWS_REGION", "us-east-1")
    env.setdefault("AWS_DEFAULT_REGION", "us-east-1")

    # Tenant env vars (needed for AgentDB session_id consistency across dispatches)
    for key in ("TENANT_NAMESPACE", "TENANT_PROJECT", "TENANT_CI_PROVIDER"):
        val = os.environ.get(key) or TENANT_ENV.get(key)
        if val:
            env[key] = val

    # Workspace path vars (needed so $WORKSPACE_ROOT/$PROJECT_ROOT expand in command files)
    for key in ("PROJECT_ROOT", "DOCS_REPO"):
        val = os.environ.get(key) or TENANT_ENV.get(key)
        if val:
            env[key] = val

    # Jira/Bitbucket creds from .env (optimization to skip SSM)
    if os.path.isfile(DOTENV_PATH):
        try:
            with open(DOTENV_PATH) as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        key, _, val = line.partition("=")
                        key = key.strip()
                        val = val.strip().strip("'\"")
                        if key.startswith(("BITBUCKET_", "JIRA_")):
                            env[key] = val
        except OSError:
            pass

    return env


def run(command_name, args):
    """Dispatch command to local Ollama model."""
    enrichment = enrich_prompt(command_name, args)

    # Build lightweight worktree map for commands that work in worktrees
    worktree_map = ""
    if command_name in ("implement", "create-implementation-plan", "fix-pr"):
        issue_key = args.split()[0] if args.strip() else ""
        if issue_key:
            workspace_root = TENANT_ENV.get("WORKSPACE_ROOT", "").rstrip("/") or PROJECT_ROOT
            wt_path = ""
            worktrees_dir = os.path.join(workspace_root, "worktrees")
            if os.path.isdir(worktrees_dir):
                for entry in os.listdir(worktrees_dir):
                    if issue_key in entry:
                        candidate = os.path.join(worktrees_dir, entry)
                        if os.path.isdir(candidate):
                            wt_path = candidate
                            break
                # Check one level deeper: worktrees/{repo}/{branch}
                if not wt_path:
                    for repo_dir in os.listdir(worktrees_dir):
                        repo_subdir = os.path.join(worktrees_dir, repo_dir)
                        if not os.path.isdir(repo_subdir):
                            continue
                        for entry in os.listdir(repo_subdir):
                            if issue_key in entry:
                                candidate = os.path.join(repo_subdir, entry)
                                if os.path.isdir(candidate):
                                    wt_path = candidate
                                    break
                        if wt_path:
                            break
            worktree_map = _prefetch_worktree_map(wt_path)

    prompt = (
        f"Execute /{command_name} {args}.\n\n"
        f"Read the instructions: cat ~/.claude/commands/{command_name}.md\n\n"
        f"Do each phase INLINE — do NOT run slash commands or spawn subprocesses.\n"
        f"Where the instructions say to run a slash command, do that work yourself directly.\n\n"
        f"CONTEXT BUDGET (CRITICAL — you have ~250k tokens total, including all tool results):\n"
        f"- NEVER re-read a file you already read earlier in this session\n"
        f"- When reading files, use offset+limit to read only the section you need (e.g., offset=50 limit=30)\n"
        f"- Do NOT read entire files over 100 lines — read the specific section you need\n"
        f"- Do NOT fetch Jira issues or PR data that is already in the pre-fetched context below\n"
        f"- Prefer Grep to find specific code over Read to scan entire files\n"
        f"- Keep Bash command output concise: pipe through | head -50 or | tail -20 when appropriate\n\n"
        f"EFFICIENCY RULES:\n"
        f"- Do NOT call ToolSearch — you already have Bash, Read, Write, Edit, Glob, Grep, LSP.\n"
        f"- Do NOT use sleep or poll loops. If a command runs, wait for it to finish.\n"
        f"- Do NOT use `git push --set-upstream` if the branch already tracks a remote.\n"
        f"- Use the WORKTREE MAP below to plan reads — only read the specific files you need."
        f"{enrichment}"
        f"{worktree_map}"
    )

    env = build_env()

    # Build export block for bash -c
    exports = "\n".join(f"export {k}={shlex.quote(v)}" for k, v in env.items())
    # --bare: skip CLAUDE.md auto-discovery, hooks, LSP, plugins (saves ~16k tokens)
    # --settings: restore just the tokf PreToolUse:Bash hook for output compression
    dispatch_settings = os.path.join(os.path.dirname(__file__), "dispatch-settings.json")
    settings_flag = f" --settings {shlex.quote(dispatch_settings)}" if os.path.isfile(dispatch_settings) else ""
    claude_cmd = (
        f"claude --model {shlex.quote(OLLAMA_MODEL)}"
        f" --bare{settings_flag}"
        f" --print {shlex.quote(prompt)}"
        f" --allowedTools 'Bash,Read,Write,Edit,Glob,Grep,LSP'"
        f" --verbose --output-format stream-json"
    )

    outfile = tempfile.NamedTemporaryFile(
        mode="w", prefix="ollama-cmd-", suffix=".jsonl", delete=False
    )
    outpath = outfile.name
    outfile.close()

    bash_script = f"{exports}\n{claude_cmd} > {shlex.quote(outpath)} 2>&1"
    cmd = [
        "env", "-i",
        f"HOME={env['HOME']}",
        f"PATH={env['PATH']}",
        f"TERM={env['TERM']}",
        f"SHELL={env['SHELL']}",
        "bash", "-c", bash_script,
    ]

    # Background progress thread
    stop = threading.Event()
    text_parts = []

    def stream_progress():
        last_pos = 0
        tool_count = 0
        while not stop.is_set():
            stop.wait(3)
            try:
                with open(outpath, "r") as f:
                    f.seek(last_pos)
                    new_data = f.read()
                    last_pos = f.tell()
            except OSError:
                continue
            if not new_data:
                continue
            for line in new_data.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                etype = event.get("type", "")
                if etype == "assistant":
                    for block in event.get("message", {}).get("content", []):
                        btype = block.get("type", "")
                        if btype == "text":
                            txt = block.get("text", "").strip()
                            if txt:
                                progress(f"  {txt[:100].split(chr(10))[0]}")
                        elif btype == "tool_use":
                            tool_count += 1
                            name = block.get("name", "?")
                            inp = block.get("input", {})
                            if name == "Bash":
                                progress(f"[{tool_count}] Bash: {inp.get('command', '')[:80]}")
                            elif name in ("Read", "Write", "Edit"):
                                progress(f"[{tool_count}] {name}: {inp.get('file_path', '?')}")
                            else:
                                progress(f"[{tool_count}] {name}")
                elif etype == "result":
                    if "result" in event:
                        text_parts.append(event["result"])

    tailer = threading.Thread(target=stream_progress, daemon=True)
    tailer.start()
    start_time = time.time()

    try:
        subprocess.run(cmd, timeout=1800)
    except subprocess.TimeoutExpired:
        text_parts.append(f"/{command_name} timed out after 30 minutes.")
    except Exception as e:
        text_parts.append(f"Error: {e}")
    finally:
        stop.set()
        tailer.join(timeout=5)
        # Extract result from stream file
        try:
            with open(outpath, "r") as f:
                for raw_line in f:
                    raw_line = raw_line.strip()
                    if not raw_line:
                        continue
                    try:
                        evt = json.loads(raw_line)
                        if evt.get("type") == "result" and "result" in evt:
                            text_parts.append(evt["result"])
                    except json.JSONDecodeError:
                        continue
        except OSError:
            pass
        # Debug copy
        debug_path = os.path.expanduser("~/.claude/cache/last-ollama-dispatch.jsonl")
        try:
            os.makedirs(os.path.dirname(debug_path), exist_ok=True)
            shutil.copy2(outpath, debug_path)
        except OSError:
            pass
        try:
            os.unlink(outpath)
        except OSError:
            pass

    output = text_parts[-1].strip() if text_parts else "(no output)"
    elapsed = time.time() - start_time
    mins = int(elapsed) // 60
    secs = int(elapsed) % 60

    if len(output) > 8000:
        output = output[:3000] + "\n\n...(truncated)...\n\n" + output[-3000:]

    progress(f"Completed in {mins}m {secs}s")
    return output, mins, secs


def main():
    if len(sys.argv) < 2:
        print("Usage: dispatch-local.py <command-name> [args...]", file=sys.stderr)
        sys.exit(1)

    command_name = sys.argv[1]
    args = " ".join(sys.argv[2:])

    progress(f"/{command_name} {args} → Ollama (local model)")
    progress("Running... (this may take several minutes)")

    output, mins, secs = run(command_name, args)
    print(output)


if __name__ == "__main__":
    main()
