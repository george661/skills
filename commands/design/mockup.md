<!-- MODEL_TIER: opus -->
---
description: >
  Generate React component mockups that realize wireframes using the actual frontend-app
  design system. Creates components as close to final implementation as possible,
  with realistic mock data. Identifies DRY refactor opportunities.
arguments:
  - name: prompt
    description: What to mockup. Reads wireframes from session state if available.
    required: true
  - name: --session
    description: Existing session ID to continue from (optional)
    required: false
agent-invokeable: true
---

> **Skill references:**
> - [design/interview](.claude/skills/design/interview.skill.md)
> - [design/dual-review](.claude/skills/design/dual-review.skill.md)
> - [design/design-confidence](.claude/skills/design/design-confidence.skill.md)
> - [design/session-state](.claude/skills/design/session-state.skill.md)
> - [design/output-format](.claude/skills/design/output-format.skill.md)
> - [design-principles](.claude/skills/design-principles/SKILL.md)
> - [desloppify](.claude/skills/desloppify/SKILL.md)
> - [mockups](.claude/skills/mockups.md)

**Announce:** "Running /design:mockup — generating React components from wireframes."

---

## Phase 0: Session + Input

Load session state. If wireframe phase complete, use its outputs as primary input.
Read the component list, screen inventory, and catalog updates from wireframe phase.

If no prior session: run interview.

---

## Phase 1: MANDATORY — Read frontend-app Source

**Do not generate any React code until you have read these files.**

```typescript
// AppLayout — top-level layout pattern
Read({ file_path: "${DESIGN_SPA_PATH}/src/components/layouts/AppLayout.tsx" })

// Navigation
Read({ file_path: "${DESIGN_SPA_PATH}/src/components/navigation/Sidebar.tsx" })
Read({ file_path: "${DESIGN_SPA_PATH}/src/components/navigation/Header.tsx" })

// Design tokens
Read({ file_path: "${DESIGN_SPA_PATH}/src/index.css" })

// An existing page for structural patterns
Read({ file_path: "${DESIGN_SPA_PATH}/src/pages/marketplace/MarketplacePage.tsx" })

// Existing component from catalog — most relevant to this prompt
// (determine which to read based on wireframe component list)
```

Also read:
```bash
# Component library inventory
ls "${DESIGN_SPA_PATH}/src/components/"
cat "${DESIGN_SPA_PATH}/package.json" | grep -A5 '"dependencies"'
```

Build a complete inventory of:
- Existing components that can be used as-is
- Existing components that can be extended
- Components that must be created new

**Any component created new when an existing one could suffice is a defect.**

---

## Phase 2: DRY Analysis

Before generating any component, check for refactor opportunities:

```bash
# Search for components with similar responsibilities
grep -r "similar-pattern" "${DESIGN_SPA_PATH}/src/components/" --include="*.tsx" -l

# Check for prop-drilling patterns that could be consolidated
grep -r "SessionCard\|ApplicationCard\|DatasetCard" "${DESIGN_SPA_PATH}/src/" -l
```

Produce a DRY analysis table:
```
| New Component Needed | Existing Similar | Recommendation |
|---|---|---|
| SearchFacets | ApplicationFilters | Generalize ApplicationFilters → Facets component |
| TokenBalanceWidget | TokenDisplay (inline) | Extract TokenDisplay into standalone widget |
```

**Refactor first.** If two components can be consolidated, design the consolidated version.
Document the refactor as a separate concern in the session state (for future /work issue).

---

## Phase 3: Generate React Components (opus)

For each component in the wireframe component list:

### File Structure Convention

Match the EXACT file structure used in frontend-app:

```
src/
├── components/
│   └── {level}/         ← atoms, molecules, organisms, templates
│       └── {ComponentName}/
│           ├── index.tsx          ← Component implementation
│           ├── {ComponentName}.test.tsx   ← Unit tests (basic render tests)
│           └── types.ts           ← Local types if needed
├── pages/
│   └── {domain}/
│       └── {PageName}.tsx         ← Page component
└── __fixtures__/
    └── {domain}/
        └── {ComponentName}.fixtures.ts  ← Mock data
```

### React Component Template

```tsx
// src/components/{level}/{ComponentName}/index.tsx
// Follow the EXACT patterns observed in existing frontend-app components

import React from 'react';
// Import ONLY from libraries already in frontend-app's package.json
// Import existing atomic components
// NEVER add new npm dependencies in mockup phase

// Types inline or in ./types.ts
interface {ComponentName}Props {
  // Props derived from wireframe annotations
}

export function {ComponentName}({ ...props }: {ComponentName}Props) {
  // Use existing design tokens (CSS variables from index.css)
  // Use cn() for conditional classes if Tailwind (match existing pattern)
  // Match exact className patterns from existing components
  return (
    <div>
      {/* Component implementation */}
    </div>
  );
}

export default {ComponentName};
```

### Mock Data Template

```typescript
// src/__fixtures__/{domain}/{ComponentName}.fixtures.ts

export const {componentName}Default = {
  // Realistic data — not "string", not "test", not single characters
  // Use realistic values: actual product names, reasonable numbers, real date formats
};

export const {componentName}Loading = {
  // Loading state data
};

export const {componentName}Empty = {
  // Empty state data
};

export const {componentName}Error = {
  // Error state — include error message text
};

// Edge cases
export const {componentName}LongTitle = {
  // 100+ character strings to test text truncation
};

export const {componentName}MaxValues = {
  // Maximum values (token balances, large numbers)
};
```

### States Required

Every component must have implementations for:
- **Default** — normal, loaded state
- **Loading** — use existing skeleton patterns from frontend-app
- **Empty** — no data state with helpful messaging
- **Error** — error boundary or inline error with recovery action

---

## Phase 4: Design Principles Check

**Load skill:** `design-principles/SKILL.md`

Review generated components against design principles:
- Design direction consistency (Precision & Density for marketplace/admin)
- Typography hierarchy correct
- Spacing consistent with existing tokens
- Interactive states (hover, focus, disabled) implemented

Apply any corrections.

---

## Phase 5: Dual Review

**Load skill:** `design/dual-review.skill.md`

**Mockup-specific adversarial checks:**
- Does any component import libraries not in frontend-app's existing package.json?
- Are any components identical or near-identical to existing components (copy-paste)?
- Is mock data realistic, or does it use placeholder text that would mask real problems?
- Do all 4 states (default, loading, empty, error) have implementations?
- Is the component using hardcoded colors instead of design tokens?

**Mockup-specific architect checks:**
- Does component composition respect atomic design levels?
- Is state management correctly placed (useState vs. useContext vs. React Query)?
- Are components self-contained enough for standalone demo without full app context?
- Are TypeScript types complete (no `any`, no missing props)?
- Do component filenames/exports follow the exact conventions in frontend-app?

---

## Phase 6: Confidence Check

**Load skill:** `design/design-confidence.skill.md`

For `mockup` phase, Check 3 (Output Completeness) requires:
- All components from wireframe list have React implementations
- All states implemented (default, loading, empty, error)
- Mock data covers edge cases
- DRY analysis documented (even if no refactors applied yet)

---

## Phase 7: Write Outputs

```bash
# Write component files to session directory
mkdir -p "${DESIGN_DOCS_PATH}/sessions/${SESSION_ID}/mockups"
# Write .tsx and .fixtures.ts files

# Write human-readable summary
# "${DESIGN_DOCS_PATH}/sessions/${SESSION_ID}/mockup.md"

# Update session state
# "${DESIGN_DOCS_PATH}/sessions/${SESSION_ID}/state.json"
```

```bash
cd "${PROJECT_ROOT}"
git add "${DESIGN_DOCS_PATH}/sessions/${SESSION_ID}/"
git commit -m "design(${SESSION_ID}): complete mockup phase — {N} components"
```

---

## Phase 8: Show Results

Display:
1. Component inventory table (component | level | new vs. existing | states)
2. DRY analysis findings
3. Refactor opportunities identified (with suggested Jira issue titles)
4. Confidence score
5. Sample component code (the most interesting new component)
6. Note: "These components are in session directory. To integrate into frontend-app, create a Jira issue."
