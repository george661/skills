#!/usr/bin/env bash
# sync-repo-list.sh — Scan ~/dev/gw/ for git repos and cache as JSON
#
# Writes ~/.claude/config/repos.json with repo metadata for use by
# route-user-prompt.py and other hooks.
#
# Usage: ./sync-repo-list.sh          (runs automatically at SessionStart)
# Output: ~/.claude/config/repos.json

set -euo pipefail

PROJECT_ROOT="${HOME}/dev/gw"
CACHE_FILE="${HOME}/.claude/config/repos.json"

mkdir -p "$(dirname "$CACHE_FILE")"

# Build JSON array of repos
repos="[]"
for dir in "${PROJECT_ROOT}"/*/; do
  [ -d "$dir" ] || continue
  name="$(basename "$dir")"

  # Skip non-repo dirs
  [ -d "${dir}.git" ] || [ -f "${dir}.git" ] || continue

  # Skip worktrees/scripts dirs
  [[ "$name" == "worktrees" || "$name" == "scripts" || "$name" == "node_modules" ]] && continue

  # Get current branch
  branch="$(git -C "$dir" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")"

  # Detect language from common files
  lang="unknown"
  [ -f "${dir}package.json" ] && lang="typescript"
  [ -f "${dir}go.mod" ] && lang="go"
  [ -f "${dir}pyproject.toml" ] || [ -f "${dir}setup.py" ] && lang="python"
  [ -f "${dir}Cargo.toml" ] && lang="rust"

  # Get description from package.json if available
  desc=""
  if [ -f "${dir}package.json" ]; then
    desc="$(python3 -c "import json; print(json.load(open('${dir}package.json')).get('description',''))" 2>/dev/null || true)"
  fi

  repos="$(echo "$repos" | python3 -c "
import json, sys
repos = json.load(sys.stdin)
repos.append({
    'slug': '${name}',
    'path': '${dir%/}',
    'branch': '${branch}',
    'language': '${lang}',
    'description': '''${desc}'''
})
print(json.dumps(repos))
")"
done

# Write cache with timestamp
python3 -c "
import json, sys
from datetime import datetime, timezone
repos = json.loads('''${repos}''')
cache = {
    'synced_at': datetime.now(timezone.utc).isoformat(),
    'project_root': '${PROJECT_ROOT}',
    'repo_count': len(repos),
    'repos': sorted(repos, key=lambda r: r['slug'])
}
with open('${CACHE_FILE}', 'w') as f:
    json.dump(cache, f, indent=2)
print(f'[repo-sync] {len(repos)} repos cached to ${CACHE_FILE}', file=sys.stderr)
"
