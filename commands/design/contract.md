<!-- MODEL_TIER: sonnet -->
---
description: >
  Maintain and establish data contracts (Pact tests) between frontend-app and lambda-functions.
  Evaluates type alignment between frontend TypeScript types and backend Go models.
  Maintains type-alignment.json. Generates or updates Pact consumer tests.
arguments:
  - name: prompt
    description: What contracts to establish/verify. Reads from session state if available.
    required: true
  - name: --session
    description: Existing session ID to continue from (optional)
    required: false
  - name: --audit
    description: Audit existing contracts without session context (standalone mode)
    required: false
agent-invokeable: true
---

> **Skill references:**
> - [design/interview](.claude/skills/design/interview.skill.md)
> - [design/dual-review](.claude/skills/design/dual-review.skill.md)
> - [design/design-confidence](.claude/skills/design/design-confidence.skill.md)
> - [design/session-state](.claude/skills/design/session-state.skill.md)
> - [design/output-format](.claude/skills/design/output-format.skill.md)
> - [pact-testing](.claude/skills/pact-testing.skill.md)

**Announce:** "Running /design:contract — establishing data contracts and verifying type alignment."

---

## Phase 0: Session + Interview

**If `--audit` flag:** Skip session/interview. Audit ALL existing contracts for inconsistencies.
**If session exists (from mockup phase):** Load session, use mockup component types as input.
**Otherwise:** Run interview, focusing on Q5 (integration points) and Q7 (constraints).

---

## Phase 1: Load Type Alignment Matrix

```bash
TYPE_ALIGNMENT="${DESIGN_DOCS_PATH}/type-alignment.json"

if [ -f "$TYPE_ALIGNMENT" ]; then
  cat "$TYPE_ALIGNMENT"
else
  # Create initial matrix by scanning known types
  echo '{"last_updated": "", "types": {}}' > "$TYPE_ALIGNMENT"
fi
```

---

## Phase 2: Identify Types in Scope

From session state (mockup phase) or from `--audit` mode:

### Session Mode
- Read mockup fixtures files for type shapes
- Read component props interfaces from mockup phase outputs
- Cross-reference against API calls made in components (fetch calls, React Query hooks)

### Audit Mode
- Scan all TypeScript types in `${DESIGN_SPA_PATH}/src/types/`
- Scan all Go models in Go common library path
- Scan all existing Pact contracts in `${DESIGN_SPA_PATH}/pact/consumers/`

Produce a type scope inventory:
```
| Type Name | Source | Go Model Path | TS Type Path | Current Alignment |
|---|---|---|---|---|
| ApplicationSession | mockup | go-common/models/application_session.go | frontend-app/src/types/session.ts | unknown |
| TokenBalance | audit | go-common/models/token.go | frontend-app/src/types/token.ts | aligned |
```

---

## Phase 3: Alignment Analysis (sonnet)

For each type in scope:

### 3.1 — Read Go Model

```bash
cat "${PROJECT_ROOT}/go-common/models/${type_file}.go" 2>/dev/null || \
  grep -r "type ${TypeName} struct" "${PROJECT_ROOT}/go-common/" -l | head -3
```

Extract:
- All fields with their JSON tags (camelCase expected)
- Optional fields (pointer types in Go = optional)
- Embedded structs

### 3.2 — Read TypeScript Interface

```bash
grep -n "${TypeName}" "${DESIGN_SPA_PATH}/src/types/"*.ts | head -5
cat "${DESIGN_SPA_PATH}/src/types/${type_file}.ts"
```

Extract:
- All interface fields
- Optional fields (`?:`)
- Union types

### 3.3 — Alignment Check

Compare field by field:

| Check | Pass | Fail |
|-------|------|------|
| Field names match (Go JSON tag = TS field name) | camelCase consistent | snake_case in Go JSON tag |
| Field types match | Go `string` = TS `string` | Go `int64` ≠ TS `string` |
| Optional fields consistent | `*string` in Go = `string \| undefined` in TS | `*string` in Go = `string` (required!) in TS |
| No extra fields in TS (that Go doesn't return) | — | Client expects field server never sends |
| No missing required fields in TS (that Go sends) | — | Client misses field server always sends |

Produce per-type alignment report:
```json
{
  "TypeName": {
    "alignment_status": "aligned | misaligned | missing-go | missing-ts",
    "misalignments": [
      {
        "field": "sessionId",
        "go_json_tag": "session_id",
        "ts_field": "sessionId",
        "issue": "Go JSON tag is snake_case, should be camelCase",
        "fix": "Change `json:\"session_id\"` to `json:\"sessionId\"` in Go model"
      }
    ]
  }
}
```

---

## Phase 4: Generate/Update Pact Tests

For each API interaction identified (from mockup's API calls or interview Q5):

### Read existing Pact tests first

```bash
ls "${DESIGN_SPA_PATH}/pact/consumers/" 2>/dev/null
cat "${DESIGN_SPA_PATH}/pact/consumers/sessions.pact.spec.ts" 2>/dev/null | head -100
```

### Generate Pact consumer test

Follow patterns from existing Pact tests exactly. Use `pact-testing.skill.md`.

```typescript
// ${SESSION_DIR}/contracts/${service}.pact.spec.ts
import { PactV3, MatchersV3 } from '@pact-foundation/pact';
const { like, string, integer, boolean, eachLike } = MatchersV3;

const provider = new PactV3({
  consumer: 'frontend-app',
  provider: 'lambda-functions-{domain}',
  dir: path.resolve(__dirname, '../pacts'),
});

describe('{Type} API Contract', () => {
  it('returns {TypeName} on GET /{route}', async () => {
    await provider
      .uponReceiving('a request for {TypeName}')
      .withRequest({
        method: 'GET',
        path: '/{route}',
        headers: { Authorization: like('Bearer token') },
      })
      .willRespondWith({
        status: 200,
        body: {
          // Use MatchersV3 — never hardcode exact values
          // Field names MUST match Go JSON tags (camelCase)
          fieldName: string('example-value'),
          numericField: integer(42),
          optionalField: like('optional-value'),
        },
      });

    // Actual fetch call using the type
  });
});
```

**Rules for Pact tests:**
- Field names in `willRespondWith` MUST match Go JSON tags exactly
- Optional fields must be wrapped in `like()` — never required
- Arrays use `eachLike([...])` — not `like([...])`
- Dates/times use `datetime()` matcher with ISO 8601
- Token amounts use `decimal()` for precision

---

## Phase 5: Type Alignment Remediation Plan

For each misaligned type, produce a remediation entry:

```json
{
  "type": "ApplicationSession",
  "priority": "high | medium | low",
  "misalignments": 2,
  "remediation": {
    "go_changes": ["Change json tag session_id → sessionId in go-common/models/application_session.go"],
    "ts_changes": ["Update interface field expiresAt to number (not string) in frontend-app/src/types/session.ts"],
    "pact_changes": ["Update sessions.pact.spec.ts with aligned field names"],
    "suggested_issue": "Align ApplicationSession type across go-common and frontend-app"
  }
}
```

**This phase does NOT make the fixes** — it identifies them and documents them for Jira issues.
The contract phase is a discovery and documentation phase, not an implementation phase.

---

## Phase 6: Dual Review

**Load skill:** `design/dual-review.skill.md`

**Contract-specific adversarial checks:**
- Are Pact contracts over-specified? (Requiring exact values instead of matchers = brittle)
- Do contracts cover only what the consumer actually uses? (Not every server field)
- Are there contracts for interactions that don't exist in the current codebase?
- Is the `type-alignment.json` complete — or are there types obviously missing from it?

**Contract-specific architect checks:**
- Do field names in Pact tests match the actual JSON tags in Go models?
- Are backward-compatible vs. breaking changes correctly identified in remediation plan?
- Is the migration path for misaligned types in the correct order (backend first)?
- Do new Pact tests exercise the actual failure modes from the interview?

---

## Phase 7: Confidence Check

**Load skill:** `design/design-confidence.skill.md`

For `contract` phase, Check 3 (Output Completeness) requires:
- All types from mockup phase analyzed
- `type-alignment.json` updated for all types in scope
- Pact tests generated for all API interactions identified
- Remediation plan produced for all misalignments

---

## Phase 8: Write Outputs

```bash
# Write Pact test files
"${DESIGN_DOCS_PATH}/sessions/${SESSION_ID}/contracts/${service}.pact.spec.ts"

# Update type-alignment.json
"${DESIGN_DOCS_PATH}/type-alignment.json"

# Write human-readable summary
"${DESIGN_DOCS_PATH}/sessions/${SESSION_ID}/contract.md"

# Update session state
"${DESIGN_DOCS_PATH}/sessions/${SESSION_ID}/state.json"

# Write design-complete summary (final phase)
"${DESIGN_DOCS_PATH}/sessions/${SESSION_ID}/design-complete.md"
```

```bash
cd "${PROJECT_ROOT}"
git add "${DESIGN_DOCS_PATH}/sessions/${SESSION_ID}/" \
        "${DESIGN_DOCS_PATH}/type-alignment.json"
git commit -m "design(${SESSION_ID}): complete contract phase — design session complete"
```

---

## Phase 9: Show Results

Display:
1. Type alignment matrix (all types analyzed)
2. Misalignment count by severity (blocker | warning)
3. Generated Pact tests summary
4. Remediation plan (list of suggested Jira issues to create)
5. Confidence score
6. Design session complete summary (full phase journey)

Ask: "Would you like to create Jira issues for the misalignment remediation items?"
If yes: suggest titles and descriptions for `/issue` commands.
