#!/usr/bin/env python3
"""
UserPromptSubmit hook: intercepts slash commands (e.g., /work PROJ-730) typed
by the user and routes them to the local Ollama model.

Flow:
  1. User types "/work PROJ-730" in Opus session
  2. This hook fires BEFORE Claude processes the prompt
  3. If local model: runs claude subprocess synchronously, shows progress
  4. If Bedrock: allows through (exit 0, no output)

Key constraints (hard-won through testing):
  - MUST use subprocess.run() — Popen (even with PIPE) hangs
  - MUST use env -i + bash -c wrapper — direct env -i hangs
  - MUST use Bash-only tools — multi-tool combos hang intermittently
  - MUST NOT pass /command prompts — Claude Code expands them (33KB+ context)
  - MUST rephrase as plain text instructions
"""

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from load_model_routing import load_routing, resolve_with_fallback
    ROUTING_AVAILABLE = True
except ImportError:
    ROUTING_AVAILABLE = False

try:
    from checkpoint import load_checkpoint
    CHECKPOINT_AVAILABLE = True
except ImportError:
    CHECKPOINT_AVAILABLE = False

PASS_THROUGH = {"loop:issue", "loop:epic", "loop:backlog"}
SLASH_RE = re.compile(r'^/([a-z][a-z0-9_:-]*)\b(.*)', re.DOTALL)

OLLAMA_API_KEY = (
    "sk-ant-api03-ollama"
    "000000000000000000000000000000000000000000000000000000000000"
    "000000000000000000-00000000AA"
)
OLLAMA_CLAUDE_MODEL = "global.anthropic.claude-sonnet-4-20250514-v1:0"
REPOS_CACHE = os.path.expanduser("~/.claude/config/repos.json")


def _get_project_root() -> str:
    """Resolve project root: $PROJECT_ROOT env var > walk cwd for .env + .claude > cwd."""
    if pr := os.environ.get("PROJECT_ROOT"):
        return pr
    cwd = Path.cwd()
    for parent in [cwd] + list(cwd.parents):
        if (parent / ".env").exists() and (parent / ".claude").exists():
            return str(parent)
    return str(cwd)


PROJECT_ROOT = _get_project_root()


def allow():
    sys.exit(0)


def progress(msg):
    """Print progress directly to terminal, bypassing Claude Code's stderr capture."""
    line = f"[Ollama] {msg}"
    try:
        with open("/dev/tty", "w") as tty:
            # \r + clear-to-end-of-line to avoid garbling with Claude Code's spinner
            tty.write(f"\r\033[K{line}\n")
            tty.flush()
    except OSError:
        # Fallback to stderr if no controlling terminal
        print(line, file=sys.stderr, flush=True)



def main():
    try:
        hook_input = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError):
        allow()

    prompt = hook_input.get("prompt", "").strip()
    if not prompt:
        allow()

    m = SLASH_RE.match(prompt)
    if not m:
        allow()

    cmd_name = m.group(1)

    if cmd_name in PASS_THROUGH:
        allow()

    if "ollama" in os.environ.get("ANTHROPIC_API_KEY", ""):
        allow()

    if not ROUTING_AVAILABLE:
        allow()

    try:
        config = load_routing()
        result = resolve_with_fallback(config, cmd_name)
    except Exception:
        allow()

    if result.get("provider_type") == "bedrock":
        allow()

    # --- Local model: run synchronously with progress ---
    base_url = result.get("base_url") or "http://localhost:11434"
    model = OLLAMA_CLAUDE_MODEL
    actual_model = result.get("model", "qwen3-coder:30b")
    args = m.group(2).strip() if m.group(2) else ""

    rephrased = build_prompt(cmd_name, args)

    # Pass through AWS config so skills can reach SSM/Secrets Manager for creds
    env_vars = {
        "HOME": os.environ.get("HOME", ""),
        "PATH": os.environ.get("PATH", ""),
        "TERM": os.environ.get("TERM", "xterm-256color"),
        "SHELL": os.environ.get("SHELL", "/bin/bash"),
        "ANTHROPIC_API_KEY": OLLAMA_API_KEY,
        "ANTHROPIC_BASE_URL": base_url,
        "CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS": "1",
        "CLAUDE_SUBPROCESS": "1",  # Signal to hooks this is a subprocess
    }
    # Pass AWS env vars so skills can resolve creds from SSM
    for aws_var in ("AWS_PROFILE", "AWS_REGION", "AWS_DEFAULT_REGION",
                    "AWS_CONFIG_FILE", "AWS_SHARED_CREDENTIALS_FILE"):
        val = os.environ.get(aws_var)
        if val:
            env_vars[aws_var] = val

    # Load Jira/Bitbucket creds from project root .env for skill access
    dotenv_path = os.path.join(PROJECT_ROOT, ".env")
    if os.path.isfile(dotenv_path):
        with open(dotenv_path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, _, val = line.partition("=")
                    key = key.strip()
                    val = val.strip().strip("'\"")
                    if key.startswith(("BITBUCKET_", "JIRA_")):
                        env_vars[key] = val

    env_exports = "\n".join(
        f"export {k}={shlex.quote(v)}" for k, v in env_vars.items()
    )

    claude_cmd = (
        f"claude --model {shlex.quote(model)}"
        f" --print {shlex.quote(rephrased)}"
        f" --allowedTools 'Bash,Read,Write,Edit,Glob,Grep,LSP'"
        f" --verbose --output-format stream-json"
    )

    # Write streaming JSON to temp file so we can tail it for progress
    outfile = tempfile.NamedTemporaryFile(
        mode="w", prefix="ollama-", suffix=".jsonl", delete=False
    )
    outpath = outfile.name
    outfile.close()

    # Redirect claude streaming output to temp file
    bash_script = f"{env_exports}\n{claude_cmd} > {shlex.quote(outpath)} 2>&1"

    cmd = [
        "env", "-i",
        f"HOME={env_vars['HOME']}",
        f"PATH={env_vars['PATH']}",
        f"TERM={env_vars['TERM']}",
        f"SHELL={env_vars['SHELL']}",
        "bash", "-c", bash_script,
    ]

    progress(f"/{cmd_name} {args} → {actual_model} via Ollama")
    progress("Running... (this may take several minutes)")

    # Background thread: parse streaming JSON and relay progress to stderr
    stop = threading.Event()
    text_parts = []  # Collect text output for final result

    def stream_progress():
        """Parse stream-json output and show tool calls, key events."""
        last_pos = 0
        last_report = time.time()
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
            if new_data:
                last_report = time.time()
                for line in new_data.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    etype = event.get("type", "")

                    # stream-json format: assistant events contain
                    # content blocks (text + tool_use), not deltas.
                    if etype == "assistant":
                        for block in event.get("message", {}).get("content", []):
                            btype = block.get("type", "")
                            if btype == "text":
                                # Show brief progress of assistant thinking
                                txt = block.get("text", "")
                                if txt.strip():
                                    preview = txt.strip()[:100].split("\n")[0]
                                    progress(f"  {preview}")
                            elif btype == "tool_use":
                                tool_count += 1
                                tool_name = block.get("name", "unknown")
                                tool_input = block.get("input", {})
                                if tool_name == "Bash":
                                    cmd_text = tool_input.get("command", "")[:80]
                                    progress(f"[{tool_count}] Bash: {cmd_text}")
                                elif tool_name == "Read":
                                    progress(f"[{tool_count}] Read: {tool_input.get('file_path', '?')}")
                                elif tool_name == "Write":
                                    progress(f"[{tool_count}] Write: {tool_input.get('file_path', '?')}")
                                elif tool_name == "Edit":
                                    progress(f"[{tool_count}] Edit: {tool_input.get('file_path', '?')}")
                                elif tool_name == "Glob":
                                    progress(f"[{tool_count}] Glob: {tool_input.get('pattern', '?')}")
                                elif tool_name == "Grep":
                                    progress(f"[{tool_count}] Grep: {tool_input.get('pattern', '?')}")
                                elif tool_name == "LSP":
                                    op = tool_input.get("operation", "?")
                                    fp = tool_input.get("filePath", "?")
                                    progress(f"[{tool_count}] LSP {op}: {fp}")
                                else:
                                    progress(f"[{tool_count}] {tool_name}")

                    elif etype == "result":
                        # The result event has the final summary
                        if "result" in event:
                            text_parts.append(event["result"])
            else:
                # No new data — periodic elapsed update
                elapsed = time.time() - last_report
                if elapsed >= 30:
                    total = time.time() - start_time
                    mins = int(total) // 60
                    secs = int(total) % 60
                    progress(f"Still running... ({mins}m {secs}s elapsed)")
                    last_report = time.time()

    tailer = threading.Thread(target=stream_progress, daemon=True)
    tailer.start()

    start_time = time.time()
    returncode = 0
    try:
        proc = subprocess.run(cmd, timeout=1800)
        returncode = proc.returncode
    except subprocess.TimeoutExpired:
        text_parts.append(f"/{cmd_name} timed out after 30 minutes on {actual_model}.")
    except FileNotFoundError:
        text_parts.append("'claude' CLI not found in PATH.")
    except Exception as e:
        text_parts.append(f"Error: {e}")
    finally:
        # Stop tailer and let it finish its current iteration
        stop.set()
        tailer.join(timeout=5)

        # Extract result from the stream file directly (most reliable)
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

        # Keep a debug copy for inspecting stream format
        debug_path = os.path.expanduser("~/.claude/cache/last-ollama-stream.jsonl")
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
    if returncode != 0 and "exit code" not in output:
        output += f"\n[exit code: {returncode}]"

    elapsed = time.time() - start_time
    mins = int(elapsed) // 60
    secs = int(elapsed) % 60
    progress(f"Completed in {mins}m {secs}s")

    # Truncate very long output
    if len(output) > 8000:
        output = output[:3000] + "\n\n...(truncated)...\n\n" + output[-3000:]

    print(json.dumps({
        "decision": "block",
        "reason": (
            f"**/{cmd_name} {args} completed on {actual_model} "
            f"(Ollama, $0 cost, {mins}m {secs}s)**\n\n{output}"
        ),
    }))


def load_repos_cache() -> list:
    """Load cached repo list from ~/.claude/config/repos.json."""
    try:
        with open(REPOS_CACHE, "r") as f:
            data = json.load(f)
            return data.get("repos", [])
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        return []


def get_checkpoint(issue_key: str) -> dict:
    """Load checkpoint for an issue. Returns {} if none found."""
    if not CHECKPOINT_AVAILABLE:
        return {}
    try:
        result = load_checkpoint(issue_key)
        if result.get("found"):
            return result.get("checkpoint", {})
    except Exception:
        pass
    return {}


def build_toolkit() -> str:
    """Build the toolkit reference section."""
    return (
        "\n\nTOOLKIT — Run via Bash (credentials auto-resolve from ~/.claude/settings.json):\n"
        "\n"
        "Jira:\n"
        "  npx tsx ~/.claude/skills/jira/get_issue.ts '{\"issue_key\": \"PROJ-123\"}'\n"
        "  npx tsx ~/.claude/skills/jira/transition_issue.ts '{\"issue_key\": \"PROJ-123\", \"transition_id\": \"21\"}'\n"
        "  npx tsx ~/.claude/skills/jira/add_comment.ts '{\"issue_key\": \"PROJ-123\", \"body\": \"...\"}'\n"
        "\n"
        "Bitbucket:\n"
        "  npx tsx ~/.claude/skills/bitbucket/create_pull_request.ts '{\"repo_slug\": \"REPO\", \"title\": \"TITLE\", \"source_branch\": \"BRANCH\", \"description\": \"DESC\"}'\n"
        "  npx tsx ~/.claude/skills/bitbucket/get_pull_request.ts '{\"repo_slug\": \"REPO\", \"pull_request_id\": NUM}'\n"
        "  npx tsx ~/.claude/skills/bitbucket/merge_pull_request.ts '{\"repo_slug\": \"REPO\", \"pull_request_id\": NUM}'\n"
        "\n"
        "Checkpoints (save progress between phases):\n"
        "  python3 ~/.claude/hooks/checkpoint.py save ISSUE PHASE '{\"key\": \"value\"}'\n"
        "  python3 ~/.claude/hooks/checkpoint.py load ISSUE\n"
        "\n"
        "LSP (use the LSP tool — not Bash):\n"
        "  goToDefinition, findReferences, hover, documentSymbol, workspaceSymbol\n"
        "  Each needs: operation, filePath, line (1-based), character (1-based)\n"
    )


def build_repo_hint(args: str) -> str:
    """Build repository awareness context."""
    if not args:
        return ""
    repos = load_repos_cache()
    if repos:
        repo_list = ", ".join(r["slug"] for r in repos)
    else:
        repo_list = "(run sync-repo-list.sh to populate)"
    return (
        f"\n\nREPOSITORY AWARENESS:\n"
        f"- Monorepo root: {PROJECT_ROOT}/\n"
        f"- Available repos: {repo_list}\n"
        f"- Check the Jira issue to determine which repo the work belongs in\n"
        f"- Use `cd {PROJECT_ROOT}/<repo>` before making changes"
    )


def build_prompt(cmd_name: str, args: str) -> str:
    """Build a checkpoint-aware prompt for the local model.

    Checks checkpoint state and gives focused phase-specific instructions
    instead of dumping the entire workflow doc.
    """
    issue_key = args.split()[0] if args else "PROJ-XXX"
    toolkit = build_toolkit()
    repo_hint = build_repo_hint(args)

    # --- Check checkpoint for /work commands ---
    if cmd_name == "work":
        cp = get_checkpoint(issue_key)
        phase = cp.get("phase", "")
        data = cp.get("data", {})
        branch = data.get("branch", "")

        if phase in ("implementation-complete", "pr-created", "ready-for-review"):
            # Implementation done — resume at PR creation or review
            pr_created = data.get("pr_created", False)
            if pr_created:
                return (
                    f"RESUMING /{cmd_name} for {issue_key} — implementation and PR already exist.\n\n"
                    f"Checkpoint: {phase} | Branch: {branch}\n\n"
                    f"STEPS:\n"
                    f"1. Check if PR exists: npx tsx ~/.claude/skills/bitbucket/list_pull_requests.ts "
                    f"'{{\"repo_slug\": \"<repo>\", \"state\": \"OPEN\"}}' and look for {issue_key}\n"
                    f"2. If PR exists, run /review on it\n"
                    f"3. If no PR, create one via Bitbucket skill\n"
                    f"4. Save checkpoint: python3 ~/.claude/hooks/checkpoint.py save {issue_key} review-complete '{{}}'\n"
                    f"{toolkit}{repo_hint}"
                )
            else:
                return (
                    f"RESUMING /{cmd_name} for {issue_key} — implementation is done, PR needed.\n\n"
                    f"Checkpoint: {phase} | Branch: {branch}\n\n"
                    f"STEPS:\n"
                    f"1. cd to the correct repo and verify the branch: git log --oneline -5\n"
                    f"2. Push if needed: git push -u origin {branch}\n"
                    f"3. Create PR: npx tsx ~/.claude/skills/bitbucket/create_pull_request.ts "
                    f"'{{\"repo_slug\": \"<repo>\", \"title\": \"{issue_key}: <summary>\", "
                    f"\"source_branch\": \"{branch}\", \"description\": \"<description>\"}}'\n"
                    f"4. Comment PR link on Jira: npx tsx ~/.claude/skills/jira/add_comment.ts "
                    f"'{{\"issue_key\": \"{issue_key}\", \"body\": \"PR created: <url>\"}}'\n"
                    f"5. Save checkpoint: python3 ~/.claude/hooks/checkpoint.py save {issue_key} "
                    f"pr-created '{{\"branch\": \"{branch}\", \"pr_created\": true}}'\n"
                    f"{toolkit}{repo_hint}"
                )

        elif phase in ("planning", "phase1-complete", "planned"):
            return (
                f"RESUMING /{cmd_name} for {issue_key} — planning is done, start implementing.\n\n"
                f"Checkpoint: {phase} | Branch: {branch}\n\n"
                f"STEPS:\n"
                f"1. Read the Jira issue: npx tsx ~/.claude/skills/jira/get_issue.ts '{{\"issue_key\": \"{issue_key}\"}}'\n"
                f"2. cd to the worktree/repo and read the implementation plan if one exists\n"
                f"3. Implement with TDD: write test, make it pass, commit\n"
                f"4. Run all tests and linting before pushing\n"
                f"5. Push: git push -u origin {branch or '<branch>'}\n"
                f"6. Create PR: npx tsx ~/.claude/skills/bitbucket/create_pull_request.ts "
                f"'{{\"repo_slug\": \"<repo>\", \"title\": \"{issue_key}: <summary>\", "
                f"\"source_branch\": \"{branch or '<branch>'}\", \"description\": \"...\"}}'\n"
                f"7. Save checkpoint: python3 ~/.claude/hooks/checkpoint.py save {issue_key} "
                f"implementation-complete '{{\"branch\": \"{branch or '<branch>'}\", \"pr_created\": true}}'\n"
                f"{toolkit}{repo_hint}"
            )

        elif phase in ("implementing",):
            return (
                f"RESUMING /{cmd_name} for {issue_key} — implementation was in progress.\n\n"
                f"Checkpoint: {phase} | Branch: {branch}\n\n"
                f"STEPS:\n"
                f"1. cd to the worktree/repo on branch {branch}\n"
                f"2. Check what's already done: git log --oneline -10 && git diff --stat\n"
                f"3. Continue implementation — finish any remaining work\n"
                f"4. Run all tests and linting\n"
                f"5. Commit and push: git push -u origin {branch}\n"
                f"6. Create PR: npx tsx ~/.claude/skills/bitbucket/create_pull_request.ts "
                f"'{{\"repo_slug\": \"<repo>\", \"title\": \"{issue_key}: <summary>\", "
                f"\"source_branch\": \"{branch}\", \"description\": \"...\"}}'\n"
                f"7. Save checkpoint: python3 ~/.claude/hooks/checkpoint.py save {issue_key} "
                f"implementation-complete '{{\"branch\": \"{branch}\", \"pr_created\": true}}'\n"
                f"{toolkit}{repo_hint}"
            )

    # --- Default: fresh start ---
    return (
        f"Execute /{cmd_name} {args}.\n\n"
        f"Read the instructions: cat ~/.claude/commands/{cmd_name}.md\n\n"
        f"Do each phase INLINE — do NOT run slash commands or spawn subprocesses.\n"
        f"Where the instructions say to run a slash command, do that work yourself directly."
        f"{toolkit}{repo_hint}"
    )


if __name__ == "__main__":
    main()
