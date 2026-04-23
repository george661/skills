# DAG Dashboard Builder Bundle

Feature-flagged React bundle for the DAG Builder UI.

## Overview

This directory contains the React/React Flow/dagre bundle that powers the `/#/builder/*` routes in the DAG Dashboard. The bundle is built with esbuild and mounted only when the `DAG_DASHBOARD_BUILDER_ENABLED` feature flag is true.

**Current status:** Task 5 (GW-5243) — WorkflowCanvas + DagNode components render the canvas. Node library and inspector wiring land in later Tier B tasks.

## Build

```bash
cd packages/dag-dashboard/builder
npm ci --legacy-peer-deps
npm run build
```

Output: `../src/dag_dashboard/static/js/builder/builder.js`

Note: `--legacy-peer-deps` is required because `react-test-renderer@18.3.1`
(dev-only) sits outside `@xyflow/react@12.3.2`'s peer-dep range. React
itself is within range; only the test renderer trips npm's strict peer
resolver.

## Tests

```bash
cd packages/dag-dashboard/builder
npm test
```

`npm test` runs a two-step pipeline:
1. `npm run test:build` — esbuild transforms `tests/*.test.mjs` (JSX + ESM)
   into `tests/.build/` with node builtins and vendored deps externalised.
2. `node --test tests/.build/*.test.mjs` — runs the ESM output under
   Node's built-in test runner.

The hook (`useCanvasState`) is exercised under `react-test-renderer`,
which does not need a DOM. `<WorkflowCanvas>` itself (thin React Flow
wrapper) is not unit-tested — full render-level coverage will come with
a later Playwright E2E task.

### Why not vitest

esbuild is already a devDep, the test surface is 12 tests across three
files, and vitest would add ~25–30 MB to CI install for features we
don't use here. If the suite grows large enough to need watch mode,
parallel execution, or coverage reporting, revisit the choice.

## Bundle Size

Target: ≤300 kB gzipped (PRP-PLAT-008 estimates ~170 kB).

Measured (after initial build):
```bash
gzip -c ../src/dag_dashboard/static/js/builder/builder.js | wc -c
```

(Document actual size in PR description.)

## Dependencies

- **react** 18.3.1
- **react-dom** 18.3.1
- **@xyflow/react** 12.3.2
- **dagre** 0.8.5
- **esbuild** 0.21.5 (build-only)

All pinned to exact versions for reproducible builds.

## CI

The `.github/workflows/ci.yml` `builder-bundle` job builds the bundle on every PR and asserts the output exists and is non-empty.

## User Documentation

For user-facing documentation on using the Builder UI (feature flags, drafts lifecycle, keyboard shortcuts, CLI reference), see the **[Builder UI section](../README.md#builder-ui)** in the main dag-dashboard README.
