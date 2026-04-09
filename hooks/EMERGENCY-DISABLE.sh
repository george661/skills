#!/bin/bash

# Emergency hook disable script - makes all hooks return approve
# Use when hooks are causing performance issues

HOOK_DIR="$HOME/.claude/hooks"

echo "🚨 EMERGENCY HOOK DISABLE 🚨"
echo "Creating stub hooks that just approve everything..."

# Python stub
cat > /tmp/stub_hook.py << 'EOF'
#!/usr/bin/env python3
import json
import sys
print(json.dumps({"decision": "approve"}))
EOF

# Shell stub
cat > /tmp/stub_hook.sh << 'EOF'
#!/bin/bash
echo '{"decision": "approve"}'
EOF

# Replace all Python hooks
for hook in "$HOOK_DIR"/*.py "$HOOK_DIR"/safety/*.py; do
    if [[ -f "$hook" ]]; then
        cp /tmp/stub_hook.py "$hook"
        chmod +x "$hook"
        echo "  ✓ Disabled: $(basename "$hook")"
    fi
done

# Replace all Shell hooks
for hook in "$HOOK_DIR"/*.sh "$HOOK_DIR"/safety/*.sh; do
    if [[ -f "$hook" ]] && [[ "$(basename "$hook")" != "EMERGENCY-DISABLE.sh" ]]; then
        cp /tmp/stub_hook.sh "$hook"
        chmod +x "$hook"
        echo "  ✓ Disabled: $(basename "$hook")"
    fi
done

rm /tmp/stub_hook.py /tmp/stub_hook.sh

echo ""
echo "✅ All hooks disabled - they will just approve everything"
echo ""
echo "To restore: reinstall with base-agents/scripts/install.sh"