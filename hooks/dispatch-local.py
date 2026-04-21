#!/usr/bin/env python3
"""
dispatch-local.py — Tenant-agnostic dispatcher for Claude Code subprocess execution.

Two modes:

  1. Command mode (legacy):
       dispatch-local.py <command-name> [args...]
     Reads ~/.claude/commands/<command-name>.md and builds an enriched prompt.
     Routes through model-routing.json to pick Ollama vs Bedrock.

  2. Raw-prompt mode (used by dag-executor PromptRunner):
       dispatch-local.py --model <tier> --prompt-stdin
       dispatch-local.py --model <tier> --file <path>
       dispatch-local.py --model <tier> -- <prompt text>
     <tier> is one of: opus, sonnet, haiku, local (or any alias in model-routing.json).
     No command-file lookup, no enrichment. Prompt is passed straight through.

Output: final text to stdout, progress to /dev/tty.
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
# Sentinel API key used when routing through an OpenAI-compatible local endpoint (Ollama).
# Claude Code rejects empty API keys even when the endpoint ignores auth, so we pass a constant.
LOCAL_API_KEY_SENTINEL = (
    "sk-ant-api03-ollama"
    "000000000000000000000000000000000000000000000000000000000000"
    "000000000000000000-00000000AA"
)

# Claude Code will reject arbitrary model IDs; this canonical alias is what
# setup-ollama-aliases.sh points at whichever local model is active. The Ollama
# server resolves the alias to the real model via its own alias table.
LOCAL_MODEL_ALIAS_DEFAULT = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"


def _resolve_actual_model(command_name: str = "implement") -> dict:
    """Resolve the command → model routing entry from model-routing.json.

    Returns a dict with keys: alias, model, provider, base_url, is_local.
    Falls back to a Bedrock sonnet default if routing can't be loaded.
    """
    try:
        _dir = os.path.dirname(os.path.abspath(__file__))
        if _dir not in sys.path:
            sys.path.insert(0, _dir)
        from load_model_routing import load_routing, get_command_alias, resolve_alias
        config = load_routing()
        alias = get_command_alias(config, command_name)
        return resolve_alias(config, alias)
    except Exception:
        return {
            "alias": "sonnet",
            "model": "global.anthropic.claude-sonnet-4-6",
            "provider": "bedrock",
            "provider_type": "bedrock",
            "base_url": None,
            "is_local": False,
            "api_key_env": None,
        }


def _get_project_root() -> str:
    """Resolve project root from environment or tenant env file."""
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
    # No tenant hints — fall back to the current working directory.
    return str(Path.cwd())


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

    return "\n".join(f"- {line}" for line in lines) + "\n" if lines else ""


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
            _ci_provider_note = (
                os.environ.get("TENANT_CI_PROVIDER")
                or TENANT_ENV.get("TENANT_CI_PROVIDER", "(not configured)")
            )
            extra += f"""
YOUR TASK: Check if {issue_key} code is deployed to the target environment.

STEPS:
1. From the ISSUE CONTEXT above, find the repository:
   a. Look for a label starting with `repo-` (e.g., repo-my-service → repo is my-service)
   b. If NO repo-* label exists, parse the repo name from square brackets in the issue title
      (e.g., "[my-service] Fix X" → repo is my-service)
   c. If neither works, STOP and output DEPLOY_STATUS: UNKNOWN
2. Check the tenant's CI pipeline for that repo. CI provider for this tenant: {_ci_provider_note}.
   Use whatever CI skill is installed under ~/.claude/skills/ (fly, github-actions, bitbucket, etc.).
   Look for the most recent build on the main branch. Status "succeeded"/"success" = deployed.
3. Determine environment from env-* labels on the issue (default: dev).
   - dev  → {_dev_url}
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
            _paths_to_check = ui_paths if ui_paths else ["(infer from issue description)"]
            _paths_display = "\n     ".join(f"- {p}" for p in _paths_to_check)
            if has_visual_effects:
                playwright_block = f"""
   - UI CRITERIA (has_visual_effects=true): Visit these paths with an authenticated browser:
     {_paths_display}
     Use the tenant's Playwright skill to take a screenshot and a console-error scan for each path.
     Look up the skill under ~/.claude/skills/ (e.g. playwright/screenshot.ts, playwright/console-check.ts)
     or whatever screenshot skill the tenant has wired up. Save each screenshot to
     /tmp/validate-{issue_key}-<name>.png.
     If the page redirects to a login screen, mark the criterion FAIL — a login screenshot is NOT evidence."""
            else:
                playwright_block = "\n   - (UI screenshots skipped — has_visual_effects=false for this issue)"

            extra += f"""
YOUR TASK: Run validation tests for {issue_key} against {env_url_arg}.
Repository: {repo_arg}

VISUAL IMPACT: has_visual_effects={has_visual_effects}, ui_paths={ui_paths}

STEPS:
1. From the ISSUE CONTEXT above, extract the **Validation Criteria** from the description
   or comments. Each criterion is a testable assertion.
2. Obtain an auth token if API/UI criteria require one. The tenant should have an auth skill
   under ~/.claude/skills/ (e.g. an SRP/OIDC/JWT helper). If there is no auth skill, mark
   AUTHENTICATED: false and note AUTH_NOT_REQUIRED or AUTH_UNAVAILABLE in the output.
3. For each criterion, run a test:{playwright_block}
   - API criteria: curl with the auth token if one is available
     (e.g. curl -s -w '\\nHTTP %{{http_code}}' -H "Authorization: Bearer $TOKEN" {env_url_arg}/api/<path>)
   - Infrastructure criteria: use the appropriate cloud CLI (aws, gcloud, az, kubectl, etc.)
4. Write ALL results to /tmp/validate-{issue_key}-test-results.txt

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
            _paths_to_check = ui_paths if ui_paths else ["(infer from issue description)"]
            _paths_display = "\n   ".join(f"- {p}" for p in _paths_to_check)
            if has_visual_effects:
                playwright_block = f"""
2. UI SCREENSHOTS (has_visual_effects=true): For each of these paths, capture an authenticated
   screenshot AND a console-error scan using the tenant's Playwright skill:
   {_paths_display}
   Save screenshots as /tmp/validate-{issue_key}-<name>.png. Do NOT accept a login-page screenshot
   as evidence — if the page redirects to login, mark EVIDENCE_QUALITY INSUFFICIENT."""
            else:
                playwright_block = "\n2. (UI screenshots skipped — has_visual_effects=false for this issue)"

            extra += f"""
YOUR TASK: Collect evidence artifacts for {issue_key} validation report.
Repository: {repo_arg}, Environment: {env_url_arg}

VISUAL IMPACT: has_visual_effects={has_visual_effects}, ui_paths={ui_paths}

STEPS:
1. Collect the most recent CI build log for the repo using whatever CI skill the tenant has
   under ~/.claude/skills/ (fly, github-actions, bitbucket, etc.).
{playwright_block}
3. For API-producing repos: capture a few example API responses with curl + auth token.
4. For infra repos: capture relevant cloud-provider logs (CloudWatch, Stackdriver, Azure Monitor).
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
            # Tenant-agnostic: produce a shallow layout summary for the plan author.
            # Tenant-specific repo hints (e.g. Terraform tfvars conventions, Next.js layouts)
            # should be provided via $PROJECT_ROOT/.claude/repo-hints/<repo>.md; the model
            # is instructed to read them below.
            if os.path.isdir(repo_path):
                try:
                    top_entries = sorted(
                        e for e in os.listdir(repo_path)
                        if not e.startswith(".") and e != "node_modules"
                    )[:30]
                    extra += (
                        f"\nREPO LAYOUT ({repo_path}, top {len(top_entries)} entries):\n"
                        + "\n".join(f"  {e}" for e in top_entries) + "\n"
                    )
                except OSError:
                    pass

                hint_path = os.path.join(
                    workspace_root, ".claude", "repo-hints", f"{repo}.md"
                )
                if os.path.isfile(hint_path):
                    extra += (
                        f"\nREPO HINTS: Read {hint_path} for tenant-specific conventions"
                        " (directory layout, infra completeness rules, etc.) before writing the plan.\n"
                    )

    # Global CI infrastructure context — injected into ALL dispatched commands.
    # TENANT_CI_PROVIDER comes from the tenant env (load-tenant-config.py writes it to
    # /tmp/tenant.env at session start). If unset, we skip the CI block entirely rather
    # than baking in a default that might be wrong for this tenant.
    ci_provider = os.environ.get("TENANT_CI_PROVIDER") or TENANT_ENV.get("TENANT_CI_PROVIDER", "")
    if ci_provider == "concourse":
        extra += (
            "\n\nCI INFRASTRUCTURE:\n"
            "- CI is **Concourse**. Pipeline names typically match repo names.\n"
            f"- List builds: cd {PROJECT_ROOT} && npx tsx ~/.claude/skills/fly/list_builds.ts "
            "'{{\"pipeline\": \"<repo>\"}}'\n"
            f"- Wait for build: cd {PROJECT_ROOT} && npx tsx ~/.claude/skills/fly/wait_for_build.ts "
            "'{{\"pipeline\": \"<repo>\", \"timeout_seconds\": 60}}'\n"
            "- Get build logs: npx tsx ~/.claude/skills/fly/watch_build.ts '{\"build_id\": <id>}'\n"
        )
    elif ci_provider == "github-actions":
        extra += (
            "\n\nCI INFRASTRUCTURE:\n"
            "- CI is **GitHub Actions**. Check workflow runs via `gh run list` and `gh run view`.\n"
        )
    elif ci_provider == "bitbucket-pipelines":
        extra += (
            "\n\nCI INFRASTRUCTURE:\n"
            "- CI is **Bitbucket Pipelines**. Check pipeline status via the Bitbucket skill"
            " under ~/.claude/skills/bitbucket/.\n"
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


def build_env(resolution: dict | None = None):
    """Build clean environment for the subprocess.

    resolution is a routing entry from load_model_routing.resolve_alias(). When it
    points at an OpenAI-compatible local provider (e.g. Ollama) we set
    ANTHROPIC_BASE_URL + a sentinel API key so Claude Code routes requests there;
    otherwise we leave Claude Code's default Bedrock/Anthropic auth path alone.
    """
    env = {
        "HOME": os.environ.get("HOME", ""),
        "PATH": os.environ.get("PATH", ""),
        "TERM": os.environ.get("TERM", "xterm-256color"),
        "SHELL": os.environ.get("SHELL", "/bin/bash"),
        "CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS": "1",
        "CLAUDE_SUBPROCESS": "1",
    }

    is_local = bool(resolution and resolution.get("is_local"))
    if is_local:
        base_url = resolution.get("base_url") or "http://localhost:11434"
        # Claude Code expects the Anthropic-style base URL without /v1 suffix.
        if base_url.endswith("/v1"):
            base_url = base_url[:-3]
        env["ANTHROPIC_API_KEY"] = LOCAL_API_KEY_SENTINEL
        env["ANTHROPIC_BASE_URL"] = base_url
    else:
        # Bedrock or remote Anthropic — propagate any already-set auth without overriding.
        for var in ("ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL",
                    "CLAUDE_CODE_USE_BEDROCK", "AWS_BEARER_TOKEN_BEDROCK"):
            val = os.environ.get(var)
            if val:
                env[var] = val

    # AWS credentials (needed for Bedrock auth and SSM fallback in skills)
    for var in ("AWS_PROFILE", "AWS_REGION", "AWS_DEFAULT_REGION",
                "AWS_CONFIG_FILE", "AWS_SHARED_CREDENTIALS_FILE"):
        val = os.environ.get(var)
        if val:
            env[var] = val
    env.setdefault("AWS_REGION", "us-east-1")
    env.setdefault("AWS_DEFAULT_REGION", "us-east-1")

    # Tenant env vars (needed for AgentDB session_id consistency across dispatches)
    for key in ("TENANT_NAMESPACE", "TENANT_PROJECT", "TENANT_CI_PROVIDER",
                "TENANT_DOTENV_PATH"):
        val = os.environ.get(key) or TENANT_ENV.get(key)
        if val:
            env[key] = val

    # Workspace path vars (needed so $WORKSPACE_ROOT/$PROJECT_ROOT expand in command files)
    for key in ("WORKSPACE_ROOT", "PROJECT_ROOT", "DOCS_REPO"):
        val = os.environ.get(key) or TENANT_ENV.get(key)
        if val:
            env[key] = val

    # VCS / issue-tracker creds from tenant .env (optimization to skip SSM lookups).
    # Pass through anything with a tenant-integration prefix, not just GW's Jira/Bitbucket.
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
                        if key.startswith((
                            "BITBUCKET_", "JIRA_", "GITHUB_", "GITLAB_",
                            "SLACK_", "LINEAR_", "CONCOURSE_", "FLY_",
                        )):
                            env[key] = val
        except OSError:
            pass

    return env


def _build_command_prompt(command_name: str, args: str) -> str:
    """Build the full enriched prompt for command mode."""
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

    return (
        f"Execute /{command_name} {args}.\n\n"
        f"Read the instructions: cat ~/.claude/commands/{command_name}.md\n\n"
        f"Do each phase INLINE — do NOT run slash commands or spawn subprocesses.\n"
        f"Where the instructions say to run a slash command, do that work yourself directly.\n\n"
        f"CONTEXT BUDGET (CRITICAL — you have ~250k tokens total, including all tool results):\n"
        f"- NEVER re-read a file you already read earlier in this session\n"
        f"- When reading files, use offset+limit to read only the section you need (e.g., offset=50 limit=30)\n"
        f"- Do NOT read entire files over 100 lines — read the specific section you need\n"
        f"- Do NOT fetch issue/PR data that is already in the pre-fetched context below\n"
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


def run(prompt: str, resolution: dict, label: str = "prompt",
        timeout_seconds: int = 1800) -> tuple[str, int, int]:
    """Execute a prompt via `claude --print` against the resolved model.

    Args:
        prompt: Full prompt text to send to the model.
        resolution: Routing dict from load_model_routing.resolve_alias(). Used for
            model id, base_url, and is_local selection.
        label: Short identifier for progress output and timeout messages.
        timeout_seconds: Hard wall-clock timeout for the subprocess.

    Returns:
        (output, minutes, seconds)
    """
    model_id = resolution.get("model") or LOCAL_MODEL_ALIAS_DEFAULT
    # Claude Code rejects arbitrary non-Claude model IDs. If routing pointed at
    # Ollama, swap in the canonical alias (Ollama resolves it back to the real model).
    if resolution.get("is_local"):
        model_id = LOCAL_MODEL_ALIAS_DEFAULT

    env = build_env(resolution)

    # Build export block for bash -c
    exports = "\n".join(f"export {k}={shlex.quote(v)}" for k, v in env.items())
    # --bare: skip CLAUDE.md auto-discovery, hooks, LSP, plugins (saves ~16k tokens)
    # --settings: restore just the tokf PreToolUse:Bash hook for output compression
    dispatch_settings = os.path.join(os.path.dirname(__file__), "dispatch-settings.json")
    settings_flag = f" --settings {shlex.quote(dispatch_settings)}" if os.path.isfile(dispatch_settings) else ""
    claude_cmd = (
        f"claude --model {shlex.quote(model_id)}"
        f" --bare{settings_flag}"
        f" --print {shlex.quote(prompt)}"
        f" --allowedTools 'Bash,Read,Write,Edit,Glob,Grep,LSP'"
        f" --verbose --output-format stream-json"
    )

    outfile = tempfile.NamedTemporaryFile(
        mode="w", prefix=f"dispatch-{label}-", suffix=".jsonl", delete=False
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
        subprocess.run(cmd, timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        text_parts.append(
            f"{label} timed out after {timeout_seconds // 60} minutes."
        )
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
        debug_path = os.path.expanduser("~/.claude/cache/last-dispatch.jsonl")
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


USAGE = """\
Usage:
  dispatch-local.py <command-name> [command-args...]
      Enriched command mode. Reads ~/.claude/commands/<command-name>.md and routes
      through model-routing.json to pick the target model.

  dispatch-local.py --model <tier> [--prompt-stdin | --file <path> | -- <prompt>]
      Raw-prompt mode. No enrichment. <tier> is a model-routing alias
      (opus, sonnet, haiku, local, or any user-defined alias). Prompt is supplied
      via stdin, a file, or the remaining argv after `--`.
"""


def _parse_raw_mode(argv: list[str]) -> tuple[str, str]:
    """Parse argv for raw-prompt mode. Returns (tier, prompt)."""
    try:
        model_idx = argv.index("--model")
        tier = argv[model_idx + 1]
    except (ValueError, IndexError):
        print("--model <tier> is required in raw-prompt mode.", file=sys.stderr)
        print(USAGE, file=sys.stderr)
        sys.exit(2)

    if "--prompt-stdin" in argv:
        prompt = sys.stdin.read()
    elif "--file" in argv:
        fi = argv.index("--file")
        try:
            path = argv[fi + 1]
        except IndexError:
            print("--file requires a path argument.", file=sys.stderr)
            sys.exit(2)
        try:
            with open(path) as f:
                prompt = f.read()
        except OSError as e:
            print(f"Cannot read prompt file {path}: {e}", file=sys.stderr)
            sys.exit(2)
    elif "--" in argv:
        di = argv.index("--")
        prompt = " ".join(argv[di + 1:])
    else:
        # No source flag — consume stdin if it's not a tty.
        if sys.stdin.isatty():
            print("No prompt source. Use --prompt-stdin, --file, or -- <prompt>.",
                  file=sys.stderr)
            sys.exit(2)
        prompt = sys.stdin.read()

    if not prompt.strip():
        print("Empty prompt.", file=sys.stderr)
        sys.exit(2)

    return tier, prompt


def main():
    argv = sys.argv[1:]
    if not argv:
        print(USAGE, file=sys.stderr)
        sys.exit(1)

    # Raw-prompt mode: --model appears anywhere in argv.
    if "--model" in argv:
        tier, prompt = _parse_raw_mode(argv)
        try:
            _dir = os.path.dirname(os.path.abspath(__file__))
            if _dir not in sys.path:
                sys.path.insert(0, _dir)
            from load_model_routing import load_routing, resolve_alias
            resolution = resolve_alias(load_routing(), tier)
        except Exception:
            # Fallback: treat tier as a literal model id.
            resolution = {
                "alias": tier,
                "model": tier,
                "provider": "unknown",
                "provider_type": "unknown",
                "base_url": None,
                "is_local": tier == "local",
                "api_key_env": None,
            }
        label = f"raw:{tier}"
        progress(f"{label} → {resolution.get('model', tier)}")
        output, _mins, _secs = run(prompt, resolution, label=label)
        print(output)
        return

    # Command mode.
    command_name = argv[0]
    args = " ".join(argv[1:])
    resolution = _resolve_actual_model(command_name)
    progress(
        f"/{command_name} {args} → {resolution.get('model', '?')}"
        f" ({resolution.get('provider', '?')})"
    )
    progress("Running... (this may take several minutes)")

    prompt = _build_command_prompt(command_name, args)
    output, _mins, _secs = run(prompt, resolution, label=f"cmd:{command_name}")
    print(output)


if __name__ == "__main__":
    main()
