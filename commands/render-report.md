---
description: "Render a report markdown file to HTML and open in browser."
model_tier: haiku
dispatch: true
---

# /render-report

Renders report markdown files to HTML using `marked` (no pandoc required) and
opens the result in the browser.

## Usage

    /render-report                                  # pick from unrendered reports
    /render-report daily-reports/2026-03-25.md      # render specific file
    /render-report daily-reports/insights/2026-W13.md

## Steps

Run:

```bash
npx tsx ~/.claude/skills/render-report/render.ts [path]
```

## Interactive flow (no path given)

1. Lists all `.md` files under `$DAILY_REPORTS_PATH` (including `insights/`)
   that have no matching `.html` sibling, sorted newest first.
2. If one file: `Render 2026-W13.md? [y/N]`
3. If multiple: numbered list — pick an index, a range (`1-3`), or `all`.
4. Writes `.html` alongside the `.md` and opens it with `open` (macOS) or
   `xdg-open` (Linux).

No pandoc installation required. CSS styling is identical to the retired
`render.sh` (Inter font, 800px max-width, table styles).
