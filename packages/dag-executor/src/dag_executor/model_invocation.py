"""Model invocation layer for dag-executor.

Self-contained alternative to base-agents/dispatch-local.sh for completion-mode
prompt nodes. Resolves a ModelTier alias to a concrete provider + endpoint, then
builds a (cmd, env, stdin) triple that the prompt runner can hand to
subprocess.Popen without caring which provider is underneath.

Why a local copy instead of importing base-agents/load_model_routing.py?
  - dag-executor is a standalone Python package. Importing a sibling repo's
    hook script would couple package install to a repo layout and make unit
    tests flaky.
  - We only need the resolution subset: alias -> (provider_type, model, base_url,
    api_key_env). The base-agents loader also handles command->alias routing
    and cost-strategy profiles, which are out of scope for prompt-node dispatch.
  - Reading ~/.claude/config/model-routing.json at runtime keeps configuration
    unified for the operator — one file controls both base-agents and
    dag-executor. Only the loader is duplicated, not the config.

Two invocation shapes:
  - AGENT: prompt runner wraps the prompt in the full Claude Code harness via
    base-agents/dispatch-local.sh. Unchanged from pre-GW-5356 behavior.
  - COMPLETION: bare LLM call — Bedrock via `claude --print --bare
    --allowedTools ""`, or OpenAI-compatible (Ollama, etc.) via a short Python
    shim script that POSTs to /v1/chat/completions and streams the reply on
    stdout. Both are subprocess-based so the runner's Popen loop stays
    provider-agnostic.
"""
from __future__ import annotations

import json
import os
import shlex
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from dag_executor.schema import ModelTier

ROUTING_PATH = Path.home() / ".claude" / "config" / "model-routing.json"

# Fallback used when no routing file is present. Keeps tests hermetic and
# makes a fresh checkout functional without any user config.
_FALLBACK_ROUTING: Dict[str, Any] = {
    "providers": {
        "bedrock": {"type": "bedrock"},
        "ollama": {
            "type": "openai",
            "base_url": "http://localhost:11434/v1",
            "health_check": "http://localhost:11434/api/tags",
        },
    },
    "models": {
        "opus": {"provider": "bedrock", "model": "global.anthropic.claude-opus-4-6-v1"},
        "sonnet": {"provider": "bedrock", "model": "global.anthropic.claude-sonnet-4-6"},
        "haiku": {"provider": "bedrock", "model": "global.anthropic.claude-haiku-4-5"},
        # `local` is a role map rather than a single model. `qwen3-coder:30b`
        # is the canonical fast completion-mode local backend.
        "local": {
            "provider": "ollama",
            "model": "qwen3-coder:30b",
            "base_url": "http://localhost:11434/v1",
        },
    },
}


@dataclass(frozen=True)
class Provider:
    """Provider endpoint metadata."""
    name: str
    type: str  # "bedrock" | "openai"
    base_url: Optional[str]
    api_key_env: Optional[str]
    health_check_url: Optional[str]


@dataclass(frozen=True)
class ModelEndpoint:
    """Resolved model + provider pair for a given ModelTier."""
    alias: str
    provider: Provider
    model: str

    @property
    def is_local(self) -> bool:
        return self.provider.type != "bedrock"


@dataclass(frozen=True)
class Invocation:
    """A built subprocess invocation for one prompt call.

    Runner contract: feed `stdin_text` to the subprocess, read stdout for the
    model reply, surface stderr + returncode on failure.
    """
    cmd: List[str]
    env: Dict[str, str]
    stdin_text: str


def load_routing(path: Path = ROUTING_PATH) -> Dict[str, Any]:
    """Load model-routing.json with fallback to an in-memory default."""
    try:
        return json.loads(path.read_text())  # type: ignore[no-any-return]
    except (FileNotFoundError, json.JSONDecodeError, PermissionError):
        return dict(_FALLBACK_ROUTING)


def resolve_alias(tier: ModelTier, routing: Optional[Dict[str, Any]] = None) -> ModelEndpoint:
    """Resolve a ModelTier to a concrete provider + model endpoint.

    Raises:
        ValueError: if the alias has no usable entry in routing or fallback.
    """
    cfg = routing if routing is not None else load_routing()
    models = cfg.get("models", {})
    providers_cfg = cfg.get("providers", {})

    entry = models.get(tier.value)
    if not isinstance(entry, dict) or "provider" not in entry or "model" not in entry:
        # Try fallback routing — covers the case where ~/.claude/config has an
        # older schema or the tier was never added there.
        fallback_entry = _FALLBACK_ROUTING["models"].get(tier.value)
        if not isinstance(fallback_entry, dict):
            raise ValueError(
                f"Model tier '{tier.value}' is not configured and has no fallback. "
                f"Add it to {ROUTING_PATH} under `models` with `provider` + `model`."
            )
        entry = fallback_entry
        providers_cfg = {**_FALLBACK_ROUTING["providers"], **providers_cfg}

    provider_name = entry["provider"]
    provider_entry = providers_cfg.get(provider_name, _FALLBACK_ROUTING["providers"].get(provider_name, {}))
    provider = Provider(
        name=provider_name,
        type=provider_entry.get("type", "bedrock"),
        base_url=entry.get("base_url") or provider_entry.get("base_url"),
        api_key_env=entry.get("api_key_env") or provider_entry.get("api_key_env"),
        health_check_url=provider_entry.get("health_check") or provider_entry.get("base_url"),
    )
    return ModelEndpoint(alias=tier.value, provider=provider, model=entry["model"])


def check_provider_health(provider: Provider, timeout: float = 2.0) -> bool:
    """Probe a provider's health endpoint.

    Bedrock is always considered healthy (IAM handles auth failures at call
    time — no cheap pre-flight). OpenAI-compatible providers hit
    `health_check_url` with a GET.
    """
    if provider.type == "bedrock":
        return True
    if not provider.health_check_url:
        return False
    try:
        req = urllib.request.Request(provider.health_check_url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return bool(200 <= resp.status < 300)
    except Exception:
        return False


def healthy_alternatives(
    unreachable: Provider,
    routing: Optional[Dict[str, Any]] = None,
) -> List[str]:
    """Return ModelTier values whose provider is currently reachable.

    Used to enrich the startup-failure message so operators can pick a working
    fallback via `--model-override` without hunting through config.
    """
    cfg = routing if routing is not None else load_routing()
    alternatives: List[str] = []
    for tier in ModelTier:
        try:
            endpoint = resolve_alias(tier, cfg)
        except ValueError:
            continue
        if endpoint.provider.name == unreachable.name:
            continue  # same provider; won't help
        if check_provider_health(endpoint.provider):
            alternatives.append(tier.value)
    return alternatives


# ---------------------------------------------------------------------------
# Invocation builders
# ---------------------------------------------------------------------------

def build_agent_invocation(
    tier: ModelTier,
    prompt: str,
    session_id: Optional[str] = None,
) -> Invocation:
    """Build an agent-mode invocation via base-agents/dispatch-local.sh.

    This is the pre-GW-5356 path — wraps the prompt in the full Claude Code
    harness (tools, CLAUDE.md, hooks, skills). Use for nodes that need to read
    files, drive skills, or run tool-using loops.
    """
    dispatch_script = Path.home() / ".claude" / "hooks" / "dispatch-local.sh"
    cmd: List[str] = [str(dispatch_script), "--model", tier.value]
    if session_id is not None:
        cmd.extend(["--session-id", session_id])
    cmd.append("--prompt-stdin")
    return Invocation(cmd=cmd, env=dict(os.environ), stdin_text=prompt)


def build_completion_invocation(
    endpoint: ModelEndpoint,
    prompt: str,
    session_id: Optional[str] = None,
) -> Invocation:
    """Build a completion-mode invocation — bare LLM call, no harness.

    Bedrock tiers go through `claude --print --bare --allowedTools ""` which
    strips hooks, plugin sync, CLAUDE.md auto-discovery, and locks the agent
    out of all tools. The prompt is fed directly on stdin — no command-name
    wrapper, no "Execute /x" boilerplate.

    OpenAI-compatible tiers (Ollama, etc.) go through a short Python shim that
    POSTs to `{base_url}/chat/completions` and prints the assistant reply on
    stdout. Keeping subprocess as the seam means the prompt runner's Popen
    loop doesn't need to branch on provider type.
    """
    if endpoint.provider.type == "bedrock":
        return _build_bedrock_completion(endpoint, prompt, session_id)
    if endpoint.provider.type == "openai":
        return _build_openai_compatible_completion(endpoint, prompt)
    raise ValueError(
        f"Completion mode not implemented for provider type '{endpoint.provider.type}'. "
        f"Supported: bedrock, openai."
    )


def _build_bedrock_completion(
    endpoint: ModelEndpoint,
    prompt: str,
    session_id: Optional[str],
) -> Invocation:
    """Claude CLI in bare mode, no tools, no harness, prompt via stdin."""
    cmd: List[str] = [
        "claude",
        "--print",
        "--bare",
        "--model", endpoint.model,
        "--allowedTools", "",  # lock out all tools — this is a pure completion
        "--input-format", "text",
        "--output-format", "text",
    ]
    if session_id is not None:
        cmd.extend(["--session-id", session_id])
    # Bedrock auth is IAM-driven via AWS_PROFILE/AWS_REGION already in env.
    env = {k: v for k, v in os.environ.items()}
    # Defensively strip any inherited Ollama-masquerade vars from a prior
    # dispatch-local.sh invocation; those would redirect the bedrock call at
    # localhost:11434 and fail mysteriously.
    for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL"):
        env.pop(k, None)
    return Invocation(cmd=cmd, env=env, stdin_text=prompt)


_OPENAI_SHIM = r"""
import json, os, sys, urllib.request
body = {
    "model": os.environ["DAG_COMPLETION_MODEL"],
    "messages": [{"role": "user", "content": sys.stdin.read()}],
    "stream": False,
}
req = urllib.request.Request(
    os.environ["DAG_COMPLETION_BASE_URL"].rstrip("/") + "/chat/completions",
    data=json.dumps(body).encode("utf-8"),
    headers={"Content-Type": "application/json"},
    method="POST",
)
api_key_env = os.environ.get("DAG_COMPLETION_API_KEY_ENV")
if api_key_env:
    key = os.environ.get(api_key_env, "")
    if key:
        req.add_header("Authorization", "Bearer " + key)
with urllib.request.urlopen(req, timeout=600) as resp:
    data = json.loads(resp.read().decode("utf-8"))
content = data["choices"][0]["message"]["content"]
sys.stdout.write(content)
"""


def _build_openai_compatible_completion(
    endpoint: ModelEndpoint,
    prompt: str,
) -> Invocation:
    """OpenAI-compatible /chat/completions via a small stdin/stdout shim."""
    if not endpoint.provider.base_url:
        raise ValueError(
            f"Provider '{endpoint.provider.name}' has no base_url; cannot build "
            f"OpenAI-compatible completion invocation."
        )
    env = {k: v for k, v in os.environ.items()}
    env["DAG_COMPLETION_MODEL"] = endpoint.model
    env["DAG_COMPLETION_BASE_URL"] = endpoint.provider.base_url
    if endpoint.provider.api_key_env:
        env["DAG_COMPLETION_API_KEY_ENV"] = endpoint.provider.api_key_env
    cmd: List[str] = ["python3", "-c", _OPENAI_SHIM]
    return Invocation(cmd=cmd, env=env, stdin_text=prompt)


def preflight_providers(routing: Optional[Dict[str, Any]] = None) -> Dict[str, bool]:
    """Health-check every provider referenced in routing. Used at workflow
    startup to fail loud before executing any prompt node.
    """
    cfg = routing if routing is not None else load_routing()
    provider_status: Dict[str, bool] = {}
    for provider_name, provider_entry in cfg.get("providers", {}).items():
        provider = Provider(
            name=provider_name,
            type=provider_entry.get("type", "bedrock"),
            base_url=provider_entry.get("base_url"),
            api_key_env=provider_entry.get("api_key_env"),
            health_check_url=provider_entry.get("health_check") or provider_entry.get("base_url"),
        )
        provider_status[provider_name] = check_provider_health(provider)
    return provider_status


__all__ = [
    "Provider",
    "ModelEndpoint",
    "Invocation",
    "load_routing",
    "resolve_alias",
    "check_provider_health",
    "healthy_alternatives",
    "build_agent_invocation",
    "build_completion_invocation",
    "preflight_providers",
]


# Silence unused-import warning for shlex — kept in case future invocation
# builders need argument quoting. mypy complains without this reference.
_ = shlex
