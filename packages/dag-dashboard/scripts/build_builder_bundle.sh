#!/usr/bin/env bash
# Build the React + React Flow builder bundle

set -e

cd "$(dirname "$0")/../builder"
npm ci
npm run build

# Verify output exists
if [ ! -s "../src/dag_dashboard/static/js/builder/builder.js" ]; then
    echo "ERROR: Bundle build failed — builder.js is missing or empty"
    exit 1
fi

echo "Builder bundle built successfully"
