# DAG Dashboard Builder Bundle

Feature-flagged React bundle for the DAG Builder UI.

## Overview

This directory contains the React/React Flow/dagre bundle that powers the `/#/builder/*` routes in the DAG Dashboard. The bundle is built with esbuild and mounted only when the `DAG_DASHBOARD_BUILDER_ENABLED` feature flag is true.

**Current status:** Task 4 (GW-5242) — placeholder component that proves the bundle loads. Task 5+ (GW-5243 onward) will port Archon components (WorkflowCanvas, DagNodeComponent, etc.).

## Build

```bash
cd packages/dag-dashboard/builder
npm ci
npm run build
```

Output: `../src/dag_dashboard/static/js/builder/builder.js`

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
