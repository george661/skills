# dag-dashboard Playwright e2e

End-to-end tests for the dashboard SPA and React builder.

## Local use

```bash
cd packages/dag-dashboard/e2e
npm ci
npm run install:browsers        # one-time: downloads chromium
npm test                         # runs all specs
npm run test:ui                  # interactive mode
```

The Playwright config launches `python -m dag_dashboard` against a temp DB with
`DAG_DASHBOARD_BUILDER_ENABLED=true` on port `8123` (override with
`DAG_DASHBOARD_E2E_PORT`). The server must be importable — run
`./scripts/setup-venv.sh && source .venv/bin/activate` from the repo root first
if you haven't set up the venv.

## What's covered

- `dashboard.spec.ts` — smoke for the 5 vanilla-JS routes (`/`, `/history`,
  `/workflows`, `/checkpoints`, `/settings`): heading renders, no console errors.
- `builder.spec.ts` — the React canvas: drop, undo/redo keyboard, YAML-view
  toggle, input-guard for Cmd+S, view-mode buttons, unsaved indicator.

## CI

The `playwright-e2e` job in `.github/workflows/ci.yml` runs the full suite on
every push/PR with chromium-only. Traces are retained on failure.
