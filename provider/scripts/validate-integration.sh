#!/usr/bin/env bash
# validate-integration.sh — Quick validation helper for Provider SDK integration
# Usage: ./validate-integration.sh [project-dir]

set -euo pipefail

DIR="${1:-.}"

echo "=== Provider Integration Validation ==="
echo "Project: $(cd "$DIR" && pwd)"
echo ""

# Check Node.js
if ! command -v node &> /dev/null; then
  echo "FAIL: Node.js not found. Install Node.js 18+."
  exit 1
fi

NODE_VERSION=$(node -v | sed 's/v//' | cut -d. -f1)
if [ "$NODE_VERSION" -lt 18 ]; then
  echo "FAIL: Node.js $NODE_VERSION found, but 18+ required."
  exit 1
fi
echo "OK: Node.js $(node -v)"

# Check package.json exists
if [ ! -f "$DIR/package.json" ]; then
  echo "FAIL: No package.json found in $DIR"
  exit 1
fi
echo "OK: package.json found"

# Check SDK installed
if node -e "const p = require('$DIR/package.json'); const d = {...(p.dependencies||{}), ...(p.devDependencies||{})}; if (!d['@mission_sciences/provider-sdk']) process.exit(1);" 2>/dev/null; then
  echo "OK: @mission_sciences/provider-sdk in dependencies"
else
  echo "FAIL: @mission_sciences/provider-sdk not in package.json dependencies"
  echo "  Fix: npm install @mission_sciences/provider-sdk"
  exit 1
fi

# Check for framework integration files
FOUND_INTEGRATION=false
for f in "$DIR/src/hooks/usePlatformSession.ts" "$DIR/src/hooks/usePlatformSession.js" \
         "$DIR/src/composables/usePlatformSession.ts" "$DIR/src/composables/usePlatformSession.js" \
         "$DIR/src/session-client.js" "$DIR/src/session-client.ts"; do
  if [ -f "$f" ]; then
    echo "OK: Framework integration found at $f"
    FOUND_INTEGRATION=true
    break
  fi
done

if [ "$FOUND_INTEGRATION" = false ]; then
  echo "WARN: No framework integration file found."
  echo "  Run: npx @mission_sciences/integration-wizard init --dir $DIR"
fi

# Check JWKS endpoint reachability
if command -v curl &> /dev/null; then
  HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "https://api.platform.example.com/.well-known/jwks.json" 2>/dev/null || echo "000")
  if [ "$HTTP_CODE" = "200" ]; then
    echo "OK: JWKS endpoint reachable"
  else
    echo "WARN: JWKS endpoint returned HTTP $HTTP_CODE"
  fi
else
  echo "SKIP: curl not found, cannot check JWKS endpoint"
fi

echo ""
echo "For full verification, run:"
echo "  npx @mission_sciences/integration-wizard verify --dir $DIR"
