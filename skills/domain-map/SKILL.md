---
name: domain-map
description: Regenerate, validate, or diff the CML domain model from source code. Hybrid merge preserves strategic annotations while updating tactical elements.
---

# Domain Map Regeneration Skill

## Purpose

Maintain the single-source-of-truth CML domain model at `${PROJECT_ROOT}/${DOCS_REPO}/domain/general-wisdom.cml` by scanning source code and merging discoveries with existing CML.

## Usage

- `/domain-map` — Full regeneration with hybrid merge
- `/domain-map validate` — Report drift between CML and source code (no modifications)
- `/domain-map diff` — Show what changed since last generation

## Source Code Locations

| Source | Path | What to Extract |
|--------|------|----------------|
| Go models | `api-service/pkg/models/*.go` | Struct names, fields, Go types, json tags, enum constants |
| TS types | `frontend-app/src/types/*.ts` | Interface/type names, fields, TS types |
| Auth models | `auth-service/lambda/*/main.go` | Auth-specific structs (User, Org, Invitation in auth context) |
| SDK types | `sdk/src/**/*.ts` | SDK-specific interfaces (SessionData, SDKConfig) |

## Discovery Process

### Step 1: Scan Go Structs

For each `.go` file in `api-service/pkg/models/`:

1. Extract all `type X struct` definitions
2. For each struct, extract fields:
   - Field name (Go identifier)
   - Go type (string, int64, float64, bool, time.Time, []string, map types, pointer types)
   - JSON tag value (from `json:"tagName"` — use this as the CML field name)
3. Extract all `type X string` constant groups (these become CML enum ValueObjects)
4. Map Go types to CML types:

| Go Type | CML Type |
|---------|----------|
| `string` | `String` |
| `int` | `int` |
| `int64` | `Long` |
| `float64` | `Double` |
| `bool` | `boolean` |
| `time.Time` | `String` (ISO 8601 datetime) |
| `[]string` | `List<String>` |
| `map[string]interface{}` | `String` (serialized JSON metadata) |
| `*T` | nullable `T` (same CML type, note optionality in comment) |

### Step 2: Scan TypeScript Types

For each `.ts` file in `frontend-app/src/types/`:

1. Extract all `export interface X` and `export type X = { ... }` definitions
2. Extract field names and TS types
3. Cross-reference with Go structs by name similarity
4. Flag mismatches:
   - Entity in TS but not Go → `// FRONTEND-ONLY: {name}`
   - Entity in Go but not TS → `// BACKEND-ONLY: {name}`
   - Field type mismatch → `// TYPE-MISMATCH: Go={goType} TS={tsType}`

### Step 3: Map to Bounded Contexts

Use the existing CML assignment. New entities map based on:
- File name patterns (e.g., `payout_*.go` → PublishingContext)
- Import relationships
- Existing aggregate groupings

## Merge Rules

### ALWAYS Preserve (never auto-modify)

These are strategic/VDAD elements maintained by humans:

- `ContextMap` relationships (upstream/downstream, ACL, OHS, etc.)
- `domainVisionStatement` on any element
- `responsibilities` lists
- `businessModel` and `evolution` attributes
- `Stakeholders` block (entire section)
- `ValueRegister` blocks (entire sections)
- `Domain` and `Subdomain` definitions
- Comments starting with `/* MANUAL:` or `// MANUAL:`

### ALWAYS Update

These are tactical elements derived from source code:

- Entity fields (add new fields, flag removed fields)
- New entities discovered in source code
- Enum ValueObject values when Go constants change
- Field type changes when Go types change

### Flagging Convention

| Situation | Action |
|-----------|--------|
| New entity not in CML | Add with `// AUTO-DISCOVERED: not yet assigned to aggregate` |
| Entity in CML but not in source | Add `// POSSIBLY-REMOVED: verify before deleting` |
| Field in CML but not in source | Add `// FIELD-REMOVED?` inline |
| New field in source not in CML | Add with `// NEW-FIELD` inline |
| Type mismatch Go vs TS | Add `// TYPE-MISMATCH: Go={type} TS={type}` inline |

## Mermaid Regeneration

After updating the CML, regenerate `${PROJECT_ROOT}/${DOCS_REPO}/domain/README.md`:

1. Parse the updated CML for bounded contexts and relationships
2. Generate Mermaid flowchart for context map (upstream/downstream arrows with relationship types as edge labels)
3. Generate Mermaid class diagrams per bounded context (one diagram per BC showing aggregates → entities → key fields)
4. Generate Mermaid quadrant chart for stakeholder map (influence vs interest)
5. Generate VDAD summary table (businessModel, evolution, subdomain type, core values per context)
6. Include legend explaining notation

## Validate Subcommand

When running `/domain-map validate`:

1. Scan source code (Steps 1-3 above)
2. Compare against existing CML without modifying it
3. Report:
   - Entities in source but missing from CML
   - Entities in CML but missing from source
   - Fields added/removed/changed
   - Go↔TS cross-validation mismatches
   - Bounded contexts with no changes vs those with drift

## Diff Subcommand

When running `/domain-map diff`:

1. Run `git diff` on `domain/general-wisdom.cml`
2. Summarize changes in human-readable format
3. Group by bounded context

## Output

After any regeneration, report to the user:

```
Domain Map Regeneration Summary
================================
Entities added:       N
Entities flagged:     N (possibly removed)
Fields added:         N
Fields flagged:       N (possibly removed)
Type mismatches:      N (Go vs TS)
Contexts modified:    [list]
Contexts unchanged:   [list]
```

## Pre-requisites

- Run from `${PROJECT_ROOT}` (the monorepo root)
- `api-service`, `frontend-app`, `auth-service` directories must be present
- Existing `${PROJECT_ROOT}/${DOCS_REPO}/domain/${DOMAIN_CML_FILE}` must exist

## Related

- CML syntax: `/cml` skill
- Design doc: `${PROJECT_ROOT}/${DOCS_REPO}/plans/2026-02-25-domain-map-design.md`
- Visual diagrams: `${PROJECT_ROOT}/${DOCS_REPO}/domain/README.md`
