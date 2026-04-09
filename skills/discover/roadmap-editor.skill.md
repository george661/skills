---
name: discover-roadmap-editor
description: >
  Reads and writes the canonical roadmap JSON. Handles viewing the current roadmap,
  adding new epics, updating status, linking Jira epics, and validating
  schema correctness before committing.
---

# Roadmap Editor Skill

## Roadmap Location

```
${TENANT_ROADMAP_PATH:-${PROJECT_ROOT}/${DOCS_REPO}/initiatives/roadmap.json}
```

Always validate the path exists before reading or writing:
```bash
ROADMAP="${TENANT_ROADMAP_PATH:-${PROJECT_ROOT}/${DOCS_REPO}/initiatives/roadmap.json}"
[ -f "$ROADMAP" ] || { echo "ERROR: Roadmap not found at $ROADMAP"; exit 1; }
```

---

## Schema Reference

The canonical roadmap uses this structure:

```json
{
  "epics": [
    {
      "id": "INI-001",
      "name": "Human-readable initiative name",
      "description": "1-2 sentence summary of the initiative",
      "status": "Proposed | Planned | In Progress | Done | Deferred",
      "priority": "Critical | High | Medium | Low",
      "domain": "sessions | tokens | marketplace | auth | organizations | publishers | platform | infrastructure | general",
      "jira": "PROJ-XXXX | null",
      "brief": "features/YYYY-MM-DD-slug-brief.md | null",
      "subEpics": [],
      "tags": [],
      "created": "YYYY-MM-DD",
      "updated": "YYYY-MM-DD"
    }
  ]
}
```

**Status definitions:**
| Status | Meaning |
|--------|---------|
| `Proposed` | Idea captured, not yet approved for planning |
| `Planned` | Approved, Jira epic exists or will be created |
| `In Progress` | Active development underway |
| `Done` | Delivered and validated |
| `Deferred` | Explicitly postponed, with reason |

---

## Operations

### View Current Roadmap

```python
import json

ROADMAP = "${TENANT_ROADMAP_PATH:-${PROJECT_ROOT}/${DOCS_REPO}/initiatives/roadmap.json}"

data = json.load(open(ROADMAP))
epics = data.get('epics', [])

# Group by status
from collections import defaultdict
by_status = defaultdict(list)
for item in epics:
    by_status[item.get('status', 'Unknown')].append(item)

for status in ['In Progress', 'Planned', 'Proposed', 'Deferred', 'Done']:
    items = by_status.get(status, [])
    if items:
        print(f"\n## {status}")
        for i in items:
            jira = f" [{i['jira']}]" if i.get('jira') else ""
            print(f"  - {i['name']}{jira}")
```

---

### Add New Initiative

```python
import json, datetime

ROADMAP = "${TENANT_ROADMAP_PATH:-${PROJECT_ROOT}/${DOCS_REPO}/initiatives/roadmap.json}"

data = json.load(open(ROADMAP))
epics = data.get('epics', [])

# Generate next ID
existing_ids = [i.get('id', '') for i in epics]
next_num = len([x for x in existing_ids if x.startswith('INI-')]) + 1
new_id = f"INI-{next_num:03d}"

new_initiative = {
    "id": new_id,
    "name": "{NAME}",
    "description": "{DESCRIPTION}",
    "status": "Proposed",
    "priority": "{Critical|High|Medium|Low}",
    "domain": "{DOMAIN}",
    "jira": None,
    "brief": "{BRIEF_PATH_OR_NULL}",
    "subEpics": [],
    "tags": [],
    "created": datetime.date.today().isoformat(),
    "updated": datetime.date.today().isoformat()
}

epics.append(new_initiative)
data['epics'] = epics

with open(ROADMAP, 'w') as f:
    json.dump(data, f, indent=2)
    f.write('\n')

print(f"Added {new_id}: {new_initiative['name']}")
```

---

### Update Existing Initiative

```python
import json, datetime

ROADMAP = "${TENANT_ROADMAP_PATH:-${PROJECT_ROOT}/${DOCS_REPO}/initiatives/roadmap.json}"

data = json.load(open(ROADMAP))

for i in data['epics']:
    if i['id'] == '{TARGET_ID}' or i.get('jira') == '{TARGET_JIRA}':
        # Update fields as needed:
        # i['status'] = 'Planned'
        # i['jira'] = 'PROJ-XXXX'
        # i['brief'] = 'features/YYYY-MM-DD-slug-brief.md'
        i['updated'] = datetime.date.today().isoformat()
        print(f"Updated: {i['name']}")
        break

with open(ROADMAP, 'w') as f:
    json.dump(data, f, indent=2)
    f.write('\n')
```

---

## Validation

Always validate JSON before committing:

```bash
python3 -c "import json; json.load(open('${TENANT_ROADMAP_PATH:-${PROJECT_ROOT}/${DOCS_REPO}/initiatives/roadmap.json}')); print('valid')"
```

If validation fails, show the parse error and do not commit.

---

## Lifecycle Rules

| Event | Roadmap Action |
|-------|---------------|
| New idea captured via `/discover:idea` | Add entry with `status: Proposed` |
| Stakeholder approves brief | Update to `status: Planned` |
| Jira epic created via `/discover:epic` | Set `jira: "PROJ-XXXX"` |
| `/groom` completes | Populate `subEpics` array with child issue keys |
| Epic reaches Done in Jira | Set `status: Done` |
| Initiative explicitly postponed | Set `status: Deferred`, add reason to `description` |

---

## Commit Convention

After any roadmap change, commit with:
```
chore(roadmap): {add|update} {initiative name}
```

Example: `chore(roadmap): add marketplace search initiative (INI-012)`
