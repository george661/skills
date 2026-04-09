---
name: domain-context.skill
description: Domain model lookups, alignment checks, and bounded context identification
---

# Domain Context Skill

## Availability

Check `TENANT_DOMAIN_PATH` is set and `$TENANT_DOMAIN_PATH/$TENANT_DOMAIN_INDEX` exists.
If not available, skip all domain checks silently — this is an opt-in feature.

## Quick Lookup Commands

### List all bounded contexts with vision

```bash
python3 -c "
import json, os
idx_path = os.path.join(os.environ.get('TENANT_DOMAIN_PATH',''), os.environ.get('TENANT_DOMAIN_INDEX','domain-index.json'))
idx = json.load(open(idx_path))
for name, ctx in idx['contexts'].items():
    print(f'{name}: {ctx[\"vision\"][:80]}...')
"
```

### Get context details (aggregates, commands, events, flows)

```bash
python3 -c "
import json, os
idx_path = os.path.join(os.environ.get('TENANT_DOMAIN_PATH',''), os.environ.get('TENANT_DOMAIN_INDEX','domain-index.json'))
idx = json.load(open(idx_path))
ctx_name = '<ContextName>'  # Replace with target context
ctx = idx['contexts'].get(ctx_name, {})
print(f'Context: {ctx_name}')
print(f'Implements: {ctx.get(\"implements\", \"N/A\")}')
print(f'Vision: {ctx.get(\"vision\", \"N/A\")}')
print(f'Aggregates: {[a[\"name\"] for a in ctx.get(\"aggregates\", [])]}')
print(f'Commands: {[c[\"name\"] for c in ctx.get(\"commands\", [])]}')
print(f'Events: {[e[\"name\"] for e in ctx.get(\"events\", [])]}')
print(f'Flows: {[f[\"name\"] for f in ctx.get(\"flows\", [])]}')
"
```

### Find which context owns a specific entity

```bash
python3 -c "
import json, os
idx_path = os.path.join(os.environ.get('TENANT_DOMAIN_PATH',''), os.environ.get('TENANT_DOMAIN_INDEX','domain-index.json'))
idx = json.load(open(idx_path))
entity = '<EntityName>'  # Replace with target entity
for name, ctx in idx['contexts'].items():
    for agg in ctx.get('aggregates', []):
        if entity.lower() in agg['name'].lower():
            print(f'{entity} found in {name} as aggregate: {agg[\"name\"]}')
        for ent in agg.get('entities', []):
            if entity.lower() in ent.lower():
                print(f'{entity} found in {name}.{agg[\"name\"]} as entity: {ent}')
"
```

### Trace a command/event across contexts

```bash
python3 -c "
import json, os
idx_path = os.path.join(os.environ.get('TENANT_DOMAIN_PATH',''), os.environ.get('TENANT_DOMAIN_INDEX','domain-index.json'))
idx = json.load(open(idx_path))
term = '<CommandOrEvent>'  # Replace with search term
for name, ctx in idx['contexts'].items():
    for cmd in ctx.get('commands', []):
        if term.lower() in cmd['name'].lower():
            print(f'Command: {cmd[\"name\"]} in {name}')
    for evt in ctx.get('events', []):
        if term.lower() in evt['name'].lower():
            print(f'Event: {evt[\"name\"]} in {name}')
    for flow in ctx.get('flows', []):
        if term.lower() in flow['name'].lower():
            print(f'Flow: {flow[\"name\"]} in {name}')
"
```

### List ContextMap relationships

```bash
python3 -c "
import json, os
idx_path = os.path.join(os.environ.get('TENANT_DOMAIN_PATH',''), os.environ.get('TENANT_DOMAIN_INDEX','domain-index.json'))
idx = json.load(open(idx_path))
for rel in idx.get('contextMap', {}).get('relationships', []):
    print(f'{rel[\"upstream\"]} --[{rel[\"type\"]}]--> {rel[\"downstream\"]}')
"
```

## Repository-to-Context Mapping

Tenants SHOULD document repository-to-context mapping in their routing config under `agent.docs.repoContextMap`.
Fallback: infer from the domain-index.json `implements` field on each context.

Example repoContextMap:
```json
{
  "api-service": ["SessionManagementContext", "TokenLedgerContext", "MarketplaceContext"],
  "auth-service": ["AuthenticationContext"],
  "frontend-app": ["MarketplaceContext"],
  "publisher-sdk": ["PublisherIntegrationContext"]
}
```

## Alignment Procedures

### Planning Phase
- Identify affected bounded contexts from epic/issue description
- Cross-reference aggregates and flows in domain-index.json
- Document alignment in PRP under "Domain Alignment" section

### Grooming Phase
- Map each issue to a bounded context
- Add `domain:{ContextName}` label to Jira issues
- Flag cross-context issues for splitting into separate issues

### Implementation Phase
- Verify repository matches the target bounded context
- Check entity/aggregate placement against CML model
- Ensure naming follows CML conventions for the context

### Review Phase
- Check changes stay within context boundaries
- Verify no cross-context coupling introduced
- Validate naming conventions match CML model

### Debugging Phase
- Use contexts as system boundaries for investigation
- Trace cross-context failures via CML flows
- Check ContextMap relationships for integration issues

## CML Maintenance

After implementation, check if CML model needs updating:
- New entities or aggregates were created → update CML
- New commands or events were added → update CML
- Context boundaries shifted → update CML + ContextMap
- Run `/domain-map validate` to detect drift
- Run `/domain-map` to regenerate if drift detected

## Related Skills

- CML skills: `.claude/skills/cml/*.skill.md`
- Domain map: `.claude/skills/domain-map/`
- Architecture review: `.claude/skills/review-architecture.md`
