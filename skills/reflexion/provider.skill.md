---
name: reflexion-provider
description: Reflexion/knowledge-store provider abstraction - unified interface that auto-routes to AgentDB, Pinecone, or Chroma
---

# Reflexion Provider Abstraction

Unified reflexion skills in `~/.claude/skills/reflexion/` that auto-detect the provider and delegate to `agentdb/`, `pinecone/`, or `chroma/` backends. **Commands should ONLY call `reflexion/*` skills — never call provider-specific skills directly.**

## How It Works

```
reflexion/reflexion_retrieve.ts  ──►  reflexion-router.ts  ──►  agentdb/reflexion_retrieve_relevant.ts
                                              │                         OR
                                              └──────►  pinecone/reflexion_retrieve.ts (future)

reflexion/reflexion_store.ts     ──►  reflexion-router.ts  ──►  agentdb/reflexion_store_episode.ts
                                              │                         OR
                                              └──────►  pinecone/reflexion_store.ts (future)
```

The router resolves the provider via:
1. Explicit `provider` field in input
2. `REFLEXION_PROVIDER` environment variable
3. Default: agentdb

## Unified Interface

All reflexion skills use **provider-agnostic parameter names**. The router translates automatically:

| Unified Skill | AgentDB Backend | Pinecone Backend (future) |
|--------------|----------------|---------------------------|
| `reflexion_retrieve` | `agentdb/reflexion_retrieve_relevant.ts` | `pinecone/reflexion_retrieve.ts` |
| `reflexion_store` | `agentdb/reflexion_store_episode.ts` | `pinecone/reflexion_store.ts` |

### Parameter Translation

**AgentDB provider:** Passthrough (no translation needed)
- `session_id`, `task`, `k` (retrieve)
- `session_id`, `task`, `input`, `output`, `reward`, `success`, `critique` (store)

**Future providers (Pinecone, Chroma):** Will implement their own param mappings as needed.

## Available Reflexion Skills

### Retrieve Relevant Episodes

```bash
# Default provider (agentdb)
npx tsx ~/.claude/skills/reflexion/reflexion_retrieve.ts '{"session_id": "gw", "task": "impl-plan-GW-5047", "k": 1}'

# Explicit provider override
REFLEXION_PROVIDER=pinecone npx tsx ~/.claude/skills/reflexion/reflexion_retrieve.ts '{"session_id": "gw", "task": "impl-plan-GW-5047", "k": 1}'

# Provider in params
npx tsx ~/.claude/skills/reflexion/reflexion_retrieve.ts '{"provider": "agentdb", "session_id": "gw", "task": "impl-plan-GW-5047", "k": 1}'
```

### Store Episode

```bash
# Default provider (agentdb)
npx tsx ~/.claude/skills/reflexion/reflexion_store.ts '{
  "session_id": "gw",
  "task": "impl-plan-GW-5047",
  "input": {"issue_key": "GW-5047"},
  "output": "Plan created",
  "reward": 0.8,
  "success": true,
  "critique": "Well-scoped plan following router patterns"
}'

# Explicit provider override
REFLEXION_PROVIDER=pinecone npx tsx ~/.claude/skills/reflexion/reflexion_store.ts '{...}'
```

## Provider Configuration

Set the default provider via environment variable:

```bash
export REFLEXION_PROVIDER=agentdb   # default
export REFLEXION_PROVIDER=pinecone  # use pinecone
export REFLEXION_PROVIDER=chroma    # use chroma
```

Or pass explicitly in each call:

```bash
npx tsx ~/.claude/skills/reflexion/reflexion_retrieve.ts '{"provider": "pinecone", "session_id": "...", "task": "...", "k": 5}'
```

## Migration from Direct AgentDB Calls

**Old (agentdb-specific):**
```bash
npx tsx ~/.claude/skills/agentdb/reflexion_retrieve_relevant.ts '{"session_id": "gw", "task": "impl-plan-GW-5047", "k": 1}'
npx tsx ~/.claude/skills/agentdb/reflexion_store_episode.ts '{"session_id": "gw", "task": "...", ...}'
```

**New (provider-agnostic):**
```bash
npx tsx ~/.claude/skills/reflexion/reflexion_retrieve.ts '{"session_id": "gw", "task": "impl-plan-GW-5047", "k": 1}'
npx tsx ~/.claude/skills/reflexion/reflexion_store.ts '{"session_id": "gw", "task": "...", ...}'
```

The new interface is **100% compatible** with existing calls — just replace the path.

## Design Rationale

This abstraction allows:
- **Provider swapping** without changing workflow YAMLs (change env var only)
- **Multi-provider support** for different tenants or workloads
- **Unified testing** — mock the router, not individual providers
- **Future extensibility** — add new providers (e.g., Weaviate) without touching commands

See `reflexion-router.ts` for implementation details.
