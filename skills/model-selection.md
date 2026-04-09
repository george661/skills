---
name: model-selection
description: Reference for choosing appropriate model tier for Task tool calls
---

# Model Selection Guide

## Model Tiers

| Model | Cost | Use For |
|-------|------|---------|
| `opus` | $$$$$ | Complex planning, architectural decisions, multi-step reasoning |
| `sonnet` | $$ | Implementation, code review, debugging, moderate complexity |
| `haiku` | $ | Exploration, search, simple analysis, file operations |

## Task Tool Model Parameter

Always pass model parameter to Task tool:

```typescript
Task({
  subagent_type: "Explore",
  model: "haiku",  // <-- ADD THIS
  description: "Search codebase",
  prompt: "Find all files matching..."
})
```

## Model Selection Matrix

| Task Type | Model | Rationale |
|-----------|-------|-----------|
| File exploration | haiku | Simple pattern matching |
| Code search (Grep/Glob) | haiku | No reasoning required |
| Codebase structure analysis | haiku | Aggregation only |
| Code review | sonnet | Requires understanding but not planning |
| Bug investigation | sonnet | Debugging is reasoning-heavy |
| Implementation | sonnet | Code generation benefits from reasoning |
| Test writing | sonnet | Understanding test design |
| Architecture planning | opus | Complex multi-factor decisions |
| Epic planning | opus | Strategic thinking required |
| Complex debugging | opus | Multi-step causal reasoning |

## Platform Command Model Assignments

| Command | Main Agent | Subagent Model |
|---------|------------|----------------|
| /garden | opus | haiku (all analysis) |
| /review | opus | sonnet (code review) |
| /implement | opus | sonnet (TDD) |
| /change | opus | haiku (exploration) |
| /bug | opus | haiku (evidence gathering) |
| /audit | opus | haiku (browser automation) |
| /investigate | opus | haiku (log analysis) |

## Cost Comparison (per 1M tokens)

| Model | Input | Output | Cache Read |
|-------|-------|--------|------------|
| Opus 4.5 | $15 | $75 | $1.50 |
| Sonnet 4.5 | $3 | $15 | $0.30 |
| Haiku 4.5 | $0.80 | $4 | $0.08 |

## Savings Estimate

Moving subagents from Opus to appropriate tiers:

| Change | Savings |
|--------|---------|
| Exploration → Haiku | ~95% |
| Code review → Sonnet | ~80% |
| Implementation → Sonnet | ~80% |
