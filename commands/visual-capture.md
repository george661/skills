---
description: Capture visual screenshots across all theme/viewport/auth permutations using Playwright
arguments:
  - name: options
    description: "Optional flags: --auth=lo|li --theme=light|dark --viewport=desktop|mobile --pages=1,2,3"
    required: false
---

# Visual Capture: $ARGUMENTS.options

## Purpose

Capture screenshots of the running dev server across all visual permutations for design review and QA. Uses Playwright for reliable, isolated browser contexts (no contention with Chrome DevTools MCP).

## Prerequisites

1. Dev server running (`npm run dev` in the SPA repository)
2. Playwright installed (`npm install -D playwright && npx playwright install chromium`)
3. A `visual-audit/capture.ts` script in the project root

## Usage

```bash
# All 8 permutations (lo/li × light/dark × desktop/mobile)
npx tsx visual-audit/capture.ts

# Specific permutation
npx tsx visual-audit/capture.ts --auth=lo --theme=dark --viewport=desktop

# Specific pages only (1=landing, 2=apps-grid, 3=apps-list, 4=datasets, 5=app-detail, 6=dataset-detail, 7=keyword-filter)
npx tsx visual-audit/capture.ts --auth=lo --theme=light --viewport=mobile --pages=1,2

# Custom base URL
npx tsx visual-audit/capture.ts --base-url=https://dev.example.com
```

## Permutations

| Auth | Theme | Viewport | Prefix |
|------|-------|----------|--------|
| Logged Out | Dark | Desktop 1280×800 | `lo-dark-desktop` |
| Logged Out | Dark | Mobile 390×844 | `lo-dark-mobile` |
| Logged Out | Light | Desktop 1280×800 | `lo-light-desktop` |
| Logged Out | Light | Mobile 390×844 | `lo-light-mobile` |
| Logged In | Dark | Desktop 1280×800 | `li-dark-desktop` |
| Logged In | Dark | Mobile 390×844 | `li-dark-mobile` |
| Logged In | Light | Desktop 1280×800 | `li-light-desktop` |
| Logged In | Light | Mobile 390×844 | `li-light-mobile` |

## Pages Captured Per Permutation

| # | Page | Path |
|---|------|------|
| 1 | Landing | `/` |
| 2 | Applications (grid) | `/marketplace/applications` |
| 3 | Applications (list) | `/marketplace/applications?view=list` |
| 4 | Datasets (grid) | `/marketplace/datasets` |
| 5 | Application detail | Click first app from grid |
| 6 | Dataset detail | Click first dataset from grid |
| 7 | Keyword filter | Click a keyword pill on apps page |

## Output

Screenshots saved to `visual-audit/` with naming: `{auth}-{theme}-{viewport}-{page#}-{name}.png`

Example: `lo-dark-desktop-01-landing.png`

## Execution

```bash
# 1. Ensure dev server is running
cd $PROJECT_ROOT/worktrees/frontend-app/{branch}
npm run dev &

# 2. Run capture
npx tsx visual-audit/capture.ts $ARGUMENTS.options

# 3. Review screenshots
ls -la visual-audit/*.png
```

## Key Design Decisions

- **Playwright over Puppeteer**: Matches e2e-tests tech stack, better browser context isolation
- **Isolated browser contexts**: Each permutation gets its own BrowserContext with independent localStorage, colorScheme, and viewport - no contention
- **Theme via localStorage**: Sets `app-theme` key (used by ThemeProvider) + Playwright `colorScheme` emulation for consistent results
- **Auth via localStorage**: Sets mock `app-storage` auth state for logged-in captures
- **`waitUntil: 'load'`**: Avoids Vite HMR websocket keeping `networkidle` from resolving
