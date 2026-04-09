#!/usr/bin/env python3
"""
Cost Projection Model — Compares annual spend across routing profiles.

Models token usage per command type, applies pricing from model-routing.json,
and projects annual cost for each cost-strategy profile.

Usage:
  python3 scripts/cost_projection.py                # Full comparison
  python3 scripts/cost_projection.py --json          # JSON output
  python3 scripts/cost_projection.py --weekly         # Weekly breakdown
"""

import json
import sys
from pathlib import Path

CONFIG_DIR = Path(__file__).parent.parent / "config"

# ── Estimated token usage per command invocation ──
# Based on typical prompt sizes + completion lengths observed in profiling.
# Format: (avg_input_tokens, avg_output_tokens, avg_cache_read_tokens)
COMMAND_TOKEN_PROFILES = {
    # /work is an orchestrator that calls sub-commands inline.
    # Its token usage IS the sum of its sub-commands (plan + implement + review
    # + fix-pr + resolve-pr). Do NOT count sub-commands separately when /work
    # is invoked — the sub-command entries below are for standalone use only.
    #
    # Estimated /work total: ~800K input, 50K output, 5M cache read across all phases.
    "work":                     (800_000, 50_000, 5_000_000),
    # Epic lifecycle (standalone, not sub-commands of /work)
    "plan":                     (300_000, 10_000, 2_000_000),
    "groom":                    (300_000, 10_000, 2_000_000),
    # Standalone invocations (when NOT called via /work)
    "review":                   (200_000,  8_000, 3_000_000),
    "implement":                (100_000, 12_000, 1_500_000),
    "create-implementation-plan": (150_000, 8_000, 1_000_000),
    "fix-pr":                   ( 80_000, 10_000, 1_000_000),
    "fix-plan":                 ( 80_000,  8_000,   800_000),
    "fix-groom":                ( 80_000,  8_000,   800_000),
    "fix-pipeline":             ( 60_000,  6_000,   500_000),
    "resolve-pr":               (100_000,  5_000, 1_200_000),
    "deploy-bypass":            ( 50_000,  3_000,   500_000),
    "consolidate-prs":          ( 80_000,  6_000,   800_000),
    # Creation commands
    "issue":                    ( 30_000,  4_000,   200_000),
    "bug":                      ( 30_000,  4_000,   200_000),
    "change":                   ( 30_000,  4_000,   200_000),
    "update-docs":              ( 40_000,  5_000,   300_000),
    "release-notes":            ( 40_000,  5_000,   300_000),
    # Quick/light commands
    "next":                     ( 10_000,  1_000,   100_000),
    "validate":                 ( 40_000,  3_000,   500_000),
    "validate-issue":           ( 30_000,  2_000,   300_000),
    "validate-plan":            ( 40_000,  3_000,   400_000),
    "validate-groom":           ( 40_000,  3_000,   400_000),
    "validate-all":             ( 50_000,  4_000,   600_000),
    # Garden/analysis
    "garden":                   ( 20_000,  2_000,   200_000),
    "garden-cache":             ( 15_000,  1_500,   150_000),
    "garden-relevancy":         ( 20_000,  2_000,   200_000),
    "garden-accuracy":          ( 20_000,  2_000,   200_000),
    "garden-readiness":         ( 20_000,  2_000,   200_000),
    "sequence":                 ( 30_000,  3_000,   300_000),
    "sequence-json":            ( 30_000,  3_000,   300_000),
    "investigate":              ( 50_000,  5_000,   400_000),
    "audit":                    ( 40_000,  4_000,   300_000),
    # Utility
    "cleanup-worktrees":        ( 10_000,  1_000,    50_000),
    "reclaim":                  ( 10_000,  1_000,    50_000),
    # Metrics
    "metrics:report":           ( 10_000,  2_000,   100_000),
    "metrics:baseline":         ( 10_000,  1_500,   100_000),
    "metrics:current":          ( 10_000,  1_500,   100_000),
    "metrics:compare":          ( 15_000,  2_000,   150_000),
    "metrics:before-after":     ( 15_000,  2_000,   150_000),
    "metrics:models":           ( 10_000,  1_500,   100_000),
}

# ── Estimated daily invocations per command (team of 1 developer) ──
# Daily invocations per command.
# /work includes its sub-commands inline, so standalone counts for
# implement, review, fix-pr, create-implementation-plan, resolve-pr
# only count invocations OUTSIDE of /work.
DAILY_INVOCATIONS = {
    "work": 3,                          # 3 issues/day via orchestrator
    "plan": 0.5,                        # epic planning (standalone)
    "groom": 0.5,                       # epic grooming (standalone)
    "review": 1,                        # standalone reviews (not via /work)
    "implement": 2,                     # standalone impl (not via /work)
    "create-implementation-plan": 1,    # standalone planning (not via /work)
    "fix-pr": 1,                        # standalone PR fixes (not via /work)
    "fix-plan": 0.5,
    "fix-groom": 0.5,
    "fix-pipeline": 1,
    "resolve-pr": 0.5,                  # standalone merges (not via /work)
    "deploy-bypass": 0.2,
    "consolidate-prs": 0.3,
    "issue": 2,
    "bug": 1,
    "change": 1,
    "update-docs": 1,
    "release-notes": 0.3,
    "next": 5,
    "validate": 4,
    "validate-issue": 2,
    "validate-plan": 1,
    "validate-groom": 1,
    "validate-all": 0.5,
    "garden": 1,
    "garden-cache": 0.5,
    "garden-relevancy": 0.5,
    "garden-accuracy": 0.5,
    "garden-readiness": 0.5,
    "sequence": 1,
    "sequence-json": 1,
    "investigate": 0.5,
    "audit": 0.3,
    "cleanup-worktrees": 0.2,
    "reclaim": 0.2,
    "metrics:report": 0.3,
    "metrics:baseline": 0.1,
    "metrics:current": 0.2,
    "metrics:compare": 0.2,
    "metrics:before-after": 0.1,
    "metrics:models": 0.1,
}

WORKING_DAYS_PER_YEAR = 250


def load_config():
    """Load model-routing.json and cost-strategy.json."""
    with open(CONFIG_DIR / "model-routing.json") as f:
        routing = json.load(f)
    with open(CONFIG_DIR / "cost-strategy.json") as f:
        strategy = json.load(f)
    return routing, strategy


def get_model_pricing(routing: dict, model_key: str) -> dict:
    """Get pricing for a model key. Returns per-million-token rates."""
    models = routing.get("models", {})
    model_info = models.get(model_key, {})

    # Local models are free
    provider_name = model_info.get("provider", "")
    if provider_name == "ollama":
        return {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "is_local": True}

    return {
        "input": model_info.get("cost_per_million_input", 0),
        "output": model_info.get("cost_per_million_output", 0),
        "cache_read": model_info.get("cost_per_million_input", 0) * 0.1,  # cache read ~10% of input
        "cache_write": model_info.get("cost_per_million_input", 0) * 1.25,  # cache write ~125% of input
        "is_local": False,
    }


def resolve_model_for_command(command: str, routing: dict, strategy: dict, profile_name: str) -> str:
    """Resolve which model a command uses under a given profile."""
    profile = strategy.get("profiles", {}).get(profile_name, {})
    overrides = profile.get("overrides", {})

    # Check profile override first
    if command in overrides:
        return overrides[command].get("main", "opus")

    # Fall back to model-routing.json command defaults
    commands = routing.get("commands", {})
    if command in commands:
        cmd_config = commands[command]
        if "inherit" in cmd_config:
            inherited = commands.get(cmd_config["inherit"], {})
            return inherited.get("main", "opus")
        return cmd_config.get("main", "opus")

    # Global default
    return routing.get("defaults", {}).get("main", "opus")


def calculate_command_cost(command: str, pricing: dict, tokens: tuple) -> float:
    """Calculate cost for a single command invocation."""
    input_t, output_t, cache_read_t = tokens
    cache_write_t = int(input_t * 0.15)  # ~15% of input becomes cache writes

    cost = (
        (input_t / 1_000_000) * pricing["input"]
        + (output_t / 1_000_000) * pricing["output"]
        + (cache_read_t / 1_000_000) * pricing["cache_read"]
        + (cache_write_t / 1_000_000) * pricing["cache_write"]
    )
    return cost


def project_profile(routing: dict, strategy: dict, profile_name: str) -> dict:
    """Project annual cost for a profile."""
    results = {
        "profile": profile_name,
        "commands": {},
        "total_daily": 0,
        "total_annual": 0,
        "local_invocations_daily": 0,
        "cloud_invocations_daily": 0,
        "total_invocations_daily": 0,
    }

    for command, tokens in COMMAND_TOKEN_PROFILES.items():
        daily_count = DAILY_INVOCATIONS.get(command, 0)
        if daily_count == 0:
            continue

        model_key = resolve_model_for_command(command, routing, strategy, profile_name)
        pricing = get_model_pricing(routing, model_key)
        per_invocation_cost = calculate_command_cost(command, pricing, tokens)
        daily_cost = per_invocation_cost * daily_count
        annual_cost = daily_cost * WORKING_DAYS_PER_YEAR

        is_local = pricing.get("is_local", False)

        results["commands"][command] = {
            "model": model_key,
            "is_local": is_local,
            "per_invocation": round(per_invocation_cost, 4),
            "daily_count": daily_count,
            "daily_cost": round(daily_cost, 4),
            "annual_cost": round(annual_cost, 2),
        }

        results["total_daily"] += daily_cost
        results["total_annual"] += annual_cost
        results["total_invocations_daily"] += daily_count
        if is_local:
            results["local_invocations_daily"] += daily_count
        else:
            results["cloud_invocations_daily"] += daily_count

    results["total_daily"] = round(results["total_daily"], 2)
    results["total_annual"] = round(results["total_annual"], 2)
    results["local_pct"] = round(
        results["local_invocations_daily"] / max(results["total_invocations_daily"], 1) * 100, 1
    )

    return results


def print_comparison(routing, strategy, weekly=False):
    """Print comparison table across all profiles."""
    profiles = ["current", "cost_optimized", "quality_optimized", "speed_optimized"]
    all_results = {}

    for p in profiles:
        all_results[p] = project_profile(routing, strategy, p)

    # Header
    print("=" * 100)
    print("COST PROJECTION MODEL — Annual Spend by Profile")
    print(f"Assumptions: 1 developer, {WORKING_DAYS_PER_YEAR} working days/year")
    print("=" * 100)

    # Summary table
    print(f"\n{'Profile':<22} {'Annual':>10} {'Daily':>8} {'Local%':>7} {'Cloud/day':>10} {'Local/day':>10}")
    print("-" * 70)
    for p in profiles:
        r = all_results[p]
        print(f"{p:<22} ${r['total_annual']:>8,.0f}  ${r['total_daily']:>6.2f}  {r['local_pct']:>5.1f}%  "
              f"{r['cloud_invocations_daily']:>8.1f}  {r['local_invocations_daily']:>8.1f}")

    # Savings vs current
    baseline_annual = all_results["current"]["total_annual"]
    print(f"\n{'Profile':<22} {'vs current':>12} {'Savings':>10}")
    print("-" * 46)
    for p in profiles:
        if p == "current":
            continue
        savings = baseline_annual - all_results[p]["total_annual"]
        pct = (savings / baseline_annual * 100) if baseline_annual > 0 else 0
        print(f"{p:<22} {pct:>+10.1f}%  ${savings:>8,.0f}")

    # Top 10 most expensive commands per profile
    for p in profiles:
        r = all_results[p]
        sorted_cmds = sorted(r["commands"].items(), key=lambda x: x[1]["annual_cost"], reverse=True)
        print(f"\n--- Top 10 Commands: {p} ---")
        print(f"{'Command':<30} {'Model':<20} {'$/invoke':>8} {'x/day':>6} {'$/year':>10} {'Local':>6}")
        print("-" * 82)
        for cmd, data in sorted_cmds[:10]:
            local_str = "YES" if data["is_local"] else ""
            print(f"{cmd:<30} {data['model']:<20} ${data['per_invocation']:>6.4f} {data['daily_count']:>5.1f} "
                  f"${data['annual_cost']:>8.2f} {local_str:>6}")

    # Weekly view
    if weekly:
        print(f"\n{'='*60}")
        print("WEEKLY BREAKDOWN")
        print(f"{'='*60}")
        for p in profiles:
            r = all_results[p]
            weekly_cost = r["total_daily"] * 5
            print(f"{p:<22} ${weekly_cost:>8.2f}/week")


def main():
    routing, strategy = load_config()

    if "--json" in sys.argv:
        profiles = ["current", "cost_optimized", "quality_optimized", "speed_optimized"]
        results = {p: project_profile(routing, strategy, p) for p in profiles}
        print(json.dumps(results, indent=2))
    else:
        weekly = "--weekly" in sys.argv
        print_comparison(routing, strategy, weekly=weekly)


if __name__ == "__main__":
    main()
