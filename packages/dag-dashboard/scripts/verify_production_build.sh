#!/usr/bin/env bash
set -euo pipefail

echo "=== DAG Dashboard Production Build Verification ==="

# Create temp directory
TMPDIR=$(mktemp -d)
trap "rm -rf $TMPDIR" EXIT

echo "1. Installing package from source..."
cd "$(dirname "$0")/.."
pip install -q . --target="$TMPDIR/site-packages" --upgrade

# Add to Python path
export PYTHONPATH="$TMPDIR/site-packages:${PYTHONPATH:-}"

echo "2. Verifying CLI command..."
python -m dag_dashboard --help > /dev/null

echo "3. Checking static asset packaging..."
python -c "
import importlib.resources
pkg = importlib.resources.files('dag_dashboard')
index_file = pkg / 'static' / 'index.html'
assert index_file.is_file(), 'index.html not found in package'
css_file = pkg / 'static' / 'css' / 'styles.css'
assert css_file.is_file(), 'styles.css not found in package'
js_file = pkg / 'static' / 'js' / 'app.js'
assert js_file.is_file(), 'app.js not found in package'
print('✓ All static assets packaged correctly')
"

echo "4. Starting server and testing HTTP endpoints..."
# Start server in background
python -m dag_dashboard --port 18765 > /dev/null 2>&1 &
SERVER_PID=$!
trap "kill $SERVER_PID 2>/dev/null || true; rm -rf $TMPDIR" EXIT

# Wait for server to start
for i in {1..10}; do
    if curl -s http://localhost:18765/health > /dev/null 2>&1; then
        break
    fi
    sleep 0.5
done

# Test /health endpoint
HEALTH=$(curl -s http://localhost:18765/health)
if ! echo "$HEALTH" | grep -q '"status":"healthy"'; then
    echo "❌ /health endpoint returned unexpected response: $HEALTH"
    exit 1
fi
echo "✓ /health endpoint OK"

# Test / endpoint returns HTML
HTML=$(curl -s http://localhost:18765/)
if ! echo "$HTML" | grep -q '<html'; then
    echo "❌ / endpoint did not return HTML"
    exit 1
fi
echo "✓ / endpoint serves HTML"

# Test static CSS
CSS=$(curl -s http://localhost:18765/css/styles.css)
if ! echo "$CSS" | grep -q 'node-status'; then
    echo "❌ /css/styles.css did not return CSS"
    exit 1
fi
echo "✓ /css/styles.css served"

# Test static JS
JS=$(curl -s http://localhost:18765/js/app.js)
if ! echo "$JS" | grep -q 'DAGRenderer'; then
    echo "❌ /js/app.js did not return JavaScript"
    exit 1
fi
echo "✓ /js/app.js served"

echo ""
echo "=== All production build checks passed ✓ ==="
