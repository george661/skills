<!-- MODEL_TIER: sonnet -->
---
description: >
  Create and maintain black-and-white component wireframes in the design catalog.
  Reads from diagram outputs and domain model. Updates the atomic design catalog.
  Enforces design system consistency using desloppify and design-principles skills.
arguments:
  - name: prompt
    description: What to wireframe. Reads from session state if available.
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

**Announce:** "Running /design:wireframe — creating atomic design wireframes."

---

## Phase 0: Session + Interview

Load session state. If diagram phase output exists, extract:
- Screen/flow inventory from diagrams
- Bounded contexts and entities involved
- Failure modes to represent as error states

If no prior session: run full interview.

---

## Phase 1: Read Design Catalog

**MANDATORY before generating any wireframe.**

```bash
# Read the catalog README for component inventory and conventions
cat "${DESIGN_CATALOG_PATH}/README.md"

# Read atomic design foundations
cat "${DESIGN_CATALOG_PATH}/00-foundations/"*.md 2>/dev/null | head -200

# Read existing atoms
ls "${DESIGN_CATALOG_PATH}/01-atoms/"

# Read existing molecules
ls "${DESIGN_CATALOG_PATH}/02-molecules/"

# Read existing organisms
ls "${DESIGN_CATALOG_PATH}/03-organisms/"
```

Build a component availability matrix:
- What components already exist at each atomic level?
- Which can be directly reused for the screens to be wireframed?
- Which need extension vs. new creation?

---

## Phase 2: Screen Inventory

From session state (diagrams phase) or interview output, produce:

```markdown
| Screen ID | Route | Description | States Needed | New Components |
|---|---|---|---|---|
| marketplace-search | /?q= | Search results page | loading, empty, results, error | SearchFacets |
| session-confirm | /sessions/confirm | Token purchase confirmation | default, insufficient-tokens, confirming | TokenConfirmModal |
```

Every screen needs these states wireframed:
- **Default** (normal, loaded with data)
- **Loading** (skeleton/spinner)
- **Empty** (no results / no data)
- **Error** (network error, server error)
- Additional states from failure modes in interview

---

## Phase 3: Generate Wireframes (sonnet)

For each screen × state combination:

### Wireframe HTML Conventions

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=1280">
  <title>[Screen Name] — [State]</title>
  <style>
    /* BLACK AND WHITE ONLY — no color, no shadows */
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: monospace;
      color: #000;
      background: #fff;
      width: 1280px;
      padding: 24px;
    }

    /* Component annotation style */
    .component-label {
      font-size: 10px;
      color: #666;
      border: 1px dashed #999;
      padding: 2px 4px;
      position: absolute;
      top: -14px;
      left: 0;
      white-space: nowrap;
    }
    .component-wrapper { position: relative; }

    /* Layout primitives */
    .sidebar { width: 240px; border-right: 1px solid #000; padding: 16px; }
    .main-content { flex: 1; padding: 24px; }
    .layout { display: flex; min-height: 100vh; }
    .header { border-bottom: 1px solid #000; padding: 16px 24px; display: flex; align-items: center; }

    /* Interactive element placeholders */
    button { border: 2px solid #000; padding: 8px 16px; cursor: pointer; background: #000; color: #fff; font-family: monospace; }
    button.secondary { background: #fff; color: #000; }
    input, select { border: 1px solid #000; padding: 8px; font-family: monospace; width: 100%; }
    .card { border: 1px solid #000; padding: 16px; margin-bottom: 8px; }
    .skeleton { background: #ddd; height: 16px; margin-bottom: 8px; }
  </style>
</head>
<body>
  <!--
    SCREEN: [Screen Name]
    STATE: [State Name]
    ROUTE: [URL route]
    SESSION: [session_id]
    COMPONENTS USED: [comma-separated list]
    NEW COMPONENTS NEEDED: [comma-separated list or "none"]
  -->

  <!-- [AppLayout] -->
  <div class="layout">
    <!-- [Sidebar nav="marketplace"] -->
    <nav class="sidebar">
      <!-- annotated sidebar content -->
    </nav>

    <!-- [MainContent] -->
    <main class="main-content">
      <!-- [PageHeader title="..."] -->
      <div class="header">
        <h1 style="font-family: monospace">[Page Title]</h1>
      </div>

      <!-- Screen-specific content with [ComponentName] annotations -->
    </main>
  </div>
</body>
</html>
```

**Annotation rules:**
- Every component is annotated with `<!-- [ComponentName props] -->`
- Annotations show atomic level: `[Atom:Button primary]`, `[Molecule:SearchBar]`, `[Organism:ProductCard]`
- Layout grid lines are shown with borders (not backgrounds)
- Spacing values are shown in comments (e.g., `<!-- 24px gap -->`)
- Content placeholders use obvious dummy text: "Application Name", "120 tokens", "2 hours"

---

## Phase 4: Design Catalog Updates

For each **new** component identified in the wireframes, add or update the catalog:

```bash
# Determine atomic level and update the appropriate catalog section
# Atoms: single-responsibility, no composition
# Molecules: 2-3 atoms combined
# Organisms: complex, context-aware sections
# Templates: full-page layouts
```

Create or update the catalog entry at `$DESIGN_CATALOG_PATH/{level}/{component-name}.md`:

```markdown
# ComponentName

**Level:** Atom / Molecule / Organism
**Status:** new (needs implementation) | existing | extended

## Purpose
One sentence: what does this component do?

## Variants / States
- `default` — normal presentation
- `loading` — skeleton state
- `empty` — no content
- `error` — failure state

## Props
| Prop | Type | Required | Description |
|------|------|----------|-------------|
| title | string | yes | ... |

## Usage
```tsx
<ComponentName title="..." />
```

## Wireframe Reference
Sessions that introduced this component: {session_id}

## Design Rules
- Rule 1
- Rule 2
```

---

## Phase 5: Dual Review

**Load skill:** `design/dual-review.skill.md`

**Wireframe-specific adversarial checks:**
- Is every wireframe state (loading, empty, error) shown?
- Are any new components being created when an existing component could be reused?
- Does the layout deviate from established page templates without justification?
- Is the information hierarchy consistent with existing screens?

**Wireframe-specific architect checks:**
- Are atomic design levels respected (no atoms directly composing organisms)?
- Is state management placement documented (local vs. context vs. server)?
- Are accessibility requirements documented (ARIA roles, keyboard navigation)?
- Does the design catalog get updated — not just the wireframe?

---

## Phase 6: Confidence Check

**Load skill:** `design/design-confidence.skill.md`

For `wireframe` phase, Check 3 (Output Completeness) requires:
- All screens from screen inventory have wireframes
- All states (loading, empty, error, default) for each screen
- Design catalog updated for new components

---

## Phase 7: Write Outputs

```bash
# Write wireframe files
for each screen in screen_inventory:
  for each state:
    write "${DESIGN_DOCS_PATH}/sessions/${SESSION_ID}/wireframes/${screen_id}-${state}.html"
    write "${DESIGN_WIREFRAMES_PATH}/${screen_id}-${state}.html"  # canonical copy

# Update design catalog
for each new_component:
  write "${DESIGN_CATALOG_PATH}/{level}/{component-name}.md"

# Write human-readable summary
write "${DESIGN_DOCS_PATH}/sessions/${SESSION_ID}/wireframe.md"

# Update session state
update "${DESIGN_DOCS_PATH}/sessions/${SESSION_ID}/state.json"
```

```bash
cd "${PROJECT_ROOT}"
git add "${DESIGN_DOCS_PATH}/sessions/${SESSION_ID}/" \
        "${DESIGN_WIREFRAMES_PATH}/" \
        "${DESIGN_CATALOG_PATH}/"
git commit -m "design(${SESSION_ID}): complete wireframe phase — {N} screens, {M} catalog updates"
```

---

## Phase 8: Show Results

Display:
1. Screen inventory table with states covered
2. New components added to catalog
3. Component reuse summary (existing vs. new)
4. Confidence score
5. Links to wireframe files
