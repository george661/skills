#!/bin/bash
#
# Platform Agents - Update Script
# Updates local installation while preserving existing configuration
#
# ┌─────────────────────────────────────────────────────────────────────────┐
# │ CRITICAL ARCHITECTURE - READ THIS FIRST                                 │
# │                                                                         │
# │ All hooks, commands, and skills are installed to ~/.claude/             │
# │ (the user's home directory), NOT to individual repository folders.      │
# │                                                                         │
# │ Individual repos like frontend-app, auth-service do NOT get .claude/               │
# │ folders. Claude Code's hook system is designed to use a single          │
# │ global ~/.claude/ directory that applies to ALL sessions.               │
# │                                                                         │
# │ Update locations:                                                       │
# │   ~/.claude/hooks/     ← Hook scripts (Python, shell)                   │
# │   ~/.claude/commands/  ← Workflow commands (markdown)                   │
# │   ~/.claude/skills/    ← REST skills and utilities                      │
# │   ~/.claude/settings.json ← Hook configurations, MCP servers            │
# │                                                                         │
# │ Source of truth: base-agents/.claude/                                   │
# │ Tenant overrides: agents/.claude/ (merged on top of base)            │
# └─────────────────────────────────────────────────────────────────────────┘
#
# Usage:
#   ./scripts/update.sh              # Full update (pull + install)
#   ./scripts/update.sh --local      # Update without git pull
#   ./scripts/update.sh --dry-run    # Show what would be updated
#   ./scripts/update.sh --rx          # Run post-update rx verification
#
# This script:
#   - Preserves .env credentials
#   - Pulls latest from main branch
#   - Updates commands, hooks, and plugins
#   - Backs up existing settings before overwriting
#

set -euo pipefail

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
BASE_AGENTS_ROOT="$REPO_DIR/base"
BASE_CONFIG_DIR="$BASE_AGENTS_ROOT"
TENANT_CONFIG_DIR="$REPO_DIR"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# Logging functions
log_info() { echo -e "${BLUE}[INFO]${NC} $*"; }
log_ok() { echo -e "${GREEN}[OK]${NC} $*"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }
log_section() { echo -e "\n${CYAN}=== $* ===${NC}\n"; }

# Default paths
CLAUDE_DIR="${HOME}/.claude"
ENV_FILE="${REPO_DIR}/.env"
BACKUP_DIR="${REPO_DIR}/.backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

# Bootstrap jq - needed to parse brew-packages.json
ensure_jq() {
    if command -v jq &>/dev/null; then
        return 0
    fi

    log_info "jq is required but not installed"

    if [[ "$(uname)" != "Darwin" ]]; then
        log_error "jq not found. Install it: apt-get install jq (Linux)"
        return 1
    fi

    if ! command -v brew &>/dev/null; then
        log_error "jq not found and Homebrew not available. Install jq manually."
        return 1
    fi

    log_info "Installing jq via Homebrew..."
    if brew install jq 2>/dev/null; then
        log_ok "jq installed"
        return 0
    else
        log_error "Failed to install jq via Homebrew"
        return 1
    fi
}

# Load and merge brew package configs from base and tenant
# Sets BREW_PACKAGES variable with merged JSON array
load_brew_packages() {
    local base_dir="${1:-}"
    local tenant_dir="${2:-}"
    local base_config="${base_dir}/config/brew-packages.json"
    local tenant_config="${tenant_dir:+${tenant_dir}/config/brew-packages.json}"

    BREW_PACKAGES="[]"

    if [[ ! -f "$base_config" ]]; then
        log_warn "Base brew package config not found: ${base_config}"
        return 0
    fi

    BREW_PACKAGES=$(cat "$base_config")

    # Merge tenant config on top (last-write-wins by name)
    if [[ -n "$tenant_config" && -f "$tenant_config" ]]; then
        BREW_PACKAGES=$(jq -s '
            .[0] as $base | .[1] as $tenant |
            ($tenant | map({(.name): .}) | add // {}) as $overrides |
            [$base[] | if $overrides[.name] then $overrides[.name] else . end] +
            [$tenant[] | select(.name as $n | $base | map(.name) | index($n) | not)]
        ' <(echo "$BREW_PACKAGES") <(cat "$tenant_config"))
        log_info "Merged tenant brew package overrides"
    fi
}

# Ensure Ollama is running and required models are pulled
setup_ollama_models() {
    log_section "Setting Up Ollama Local Models"

    local models_config="${REPO_DIR}/config/ollama-models.json"
    if [[ ! -f "$models_config" ]]; then
        log_warn "ollama-models.json not found, skipping"
        return 0
    fi

    # Check ollama is installed
    if ! command -v ollama &>/dev/null; then
        log_warn "Ollama not installed. Install via: brew install ollama"
        return 0
    fi
    log_ok "Ollama installed: $(ollama --version 2>/dev/null | head -1)"

    # Check ollama is running
    if ! curl -sf --max-time 1 "http://localhost:11434/api/tags" >/dev/null 2>&1; then
        log_info "Starting Ollama..."
        ollama serve &>/dev/null &
        sleep 2
        if ! curl -sf --max-time 2 "http://localhost:11434/api/tags" >/dev/null 2>&1; then
            log_warn "Could not start Ollama. Start manually: ollama serve"
            return 0
        fi
    fi
    log_ok "Ollama running"

    # Get list of currently installed models
    local installed_models
    installed_models=$(ollama list 2>/dev/null | awk 'NR>1 {print $1}')

    # Pull required models from config
    local required_models
    required_models=$(jq -r '
        [.models[][] | select(.required == true)] | .[].name
    ' "$models_config" 2>/dev/null)

    local pulled=0
    local already=0
    while IFS= read -r model; do
        [[ -z "$model" ]] && continue
        if echo "$installed_models" | grep -q "^${model}$"; then
            log_ok "$model: installed"
            ((already++))
        else
            if [[ "$DRY_RUN" == true ]]; then
                log_info "[DRY-RUN] Would pull: $model"
            else
                log_info "Pulling $model (this may take a few minutes)..."
                if ollama pull "$model" 2>&1 | tail -1; then
                    log_ok "$model: pulled"
                    ((pulled++))
                else
                    log_warn "$model: pull failed"
                fi
            fi
        fi
    done <<< "$required_models"

    log_ok "Ollama models: ${already} ready, ${pulled} pulled"
}

# Update brew packages from the merged config
update_brew_packages() {
    if [[ "$DRY_RUN" == true ]]; then
        log_info "[DRY-RUN] Would check/update Homebrew packages from config"
        return 0
    fi

    if ! ensure_jq; then
        return 1
    fi

    load_brew_packages "$BASE_CONFIG_DIR" "$TENANT_CONFIG_DIR"

    local pkg_count
    pkg_count=$(echo "$BREW_PACKAGES" | jq 'length')

    if [[ "$pkg_count" -eq 0 ]]; then
        return 0
    fi

    log_section "Updating Homebrew Packages"

    if [[ "$(uname)" != "Darwin" ]]; then
        log_info "Not macOS - skipping Homebrew package management"
        return 0
    fi

    if ! command -v brew &>/dev/null; then
        log_warn "Homebrew not installed - cannot manage packages"
        return 1
    fi

    local i=0
    while [[ $i -lt $pkg_count ]]; do
        local name required description version_command
        name=$(echo "$BREW_PACKAGES" | jq -r ".[$i].name")
        required=$(echo "$BREW_PACKAGES" | jq -r ".[$i].required")
        description=$(echo "$BREW_PACKAGES" | jq -r ".[$i].description")
        version_command=$(echo "$BREW_PACKAGES" | jq -r ".[$i].version_command")

        if command -v "$name" &>/dev/null; then
            local current_version
            current_version=$(eval "$version_command" 2>/dev/null | head -n1 || echo "unknown")
            log_ok "${name}: installed (${current_version})"

            # Skip brew upgrade if already installed (avoids slow index refresh)
            log_ok "${name}: up to date (skipping upgrade check)"
        else
            log_info "Installing ${name} - ${description}..."
            if brew install "$name" 2>/dev/null; then
                log_ok "${name}: installed"
            else
                if [[ "$required" == "true" ]]; then
                    log_error "Failed to install required package: ${name}"
                    return 1
                else
                    log_warn "Could not install optional package: ${name}"
                    log_info "  Install manually: brew install ${name}"
                fi
            fi
        fi

        i=$((i + 1))
    done

    log_ok "Homebrew package update complete"
}

# Options
DRY_RUN=false
LOCAL_ONLY=false
FORCE=false
SYNC_REPOS_ONLY=false
RUN_RX=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --local)
            LOCAL_ONLY=true
            shift
            ;;
        --force)
            FORCE=true
            shift
            ;;
        --sync-repos)
            SYNC_REPOS_ONLY=true
            shift
            ;;
        --rx)
            RUN_RX=true
            shift
            ;;
        --help|-h)
            cat <<EOF
Project Agents - Update Script

Usage:
  ${0##*/}              Full update (pull latest + reinstall)
  ${0##*/} --local      Update without git pull (use current files)
  ${0##*/} --dry-run    Show what would be updated without making changes
  ${0##*/} --force      Skip confirmation prompts
  ${0##*/} --sync-repos Sync project repositories only (git pull all repos)
  ${0##*/} --rx         Run post-update rx verification

Options:
  --dry-run     Preview changes without applying them
  --local       Skip git pull, update from current local files
  --force       Don't prompt for confirmation
  --sync-repos  Only sync project repositories (skip other updates)
  --rx          Run post-update rx verification (off by default)
  --help        Show this help message

What gets updated:
  - Project repos (frontend-app, lambda-functions, etc.) - git pull on each
  - MCP server repos (jira, bitbucket) - git pull + rebuild
  - Workflow commands (.claude/commands/*.md)
  - Hook files (.claude/hooks/*)
  - Hook configurations in settings.json (new hooks merged)
  - Plugins (superpowers)
  - MCP server checks

What is preserved:
  - .env credentials file
  - Existing MCP server configurations
  - Custom modifications to settings.json (backed up)

Multi-Repo Setup:
  If PROJECT_REPOS is configured in .env, the update script will sync all
  project repositories. Configure with: ./scripts/install.sh --configure-repos

EOF
            exit 0
            ;;
        *)
            log_error "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Check if we're in a git repo
check_git_repo() {
    if [[ ! -d "${REPO_DIR}/.git" ]]; then
        log_error "Not a git repository: ${REPO_DIR}"
        log_error "Please run this script from the agents repository"
        exit 1
    fi
}

# Create backup directory
create_backup_dir() {
    mkdir -p "${BACKUP_DIR}/${TIMESTAMP}"
    log_ok "Backup directory: ${BACKUP_DIR}/${TIMESTAMP}"
}

# Check for uncommitted changes
check_uncommitted_changes() {
    log_section "Checking Repository Status"

    cd "$REPO_DIR"

    if [[ -n "$(git status --porcelain)" ]]; then
        log_warn "Uncommitted changes detected:"
        git status --short
        echo ""

        if [[ "$FORCE" != true ]]; then
            read -p "Continue anyway? Local changes may be overwritten. (y/N): " confirm
            if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
                log_info "Aborted. Please commit or stash your changes first."
                exit 0
            fi
        fi
    else
        log_ok "Working directory clean"
    fi
}

# Backup existing configuration
backup_existing_config() {
    log_section "Backing Up Existing Configuration"

    local backup_path="${BACKUP_DIR}/${TIMESTAMP}"

    # Backup .env if exists
    if [[ -f "$ENV_FILE" ]]; then
        if [[ "$DRY_RUN" == true ]]; then
            log_info "[DRY-RUN] Would backup: ${ENV_FILE}"
        else
            cp "$ENV_FILE" "${backup_path}/.env"
            log_ok "Backed up .env"
        fi
    fi

    # Backup settings.json if exists
    local settings_file="${CLAUDE_DIR}/settings.json"
    if [[ -f "$settings_file" ]]; then
        if [[ "$DRY_RUN" == true ]]; then
            log_info "[DRY-RUN] Would backup: ${settings_file}"
        else
            cp "$settings_file" "${backup_path}/settings.json"
            log_ok "Backed up settings.json"
        fi
    fi

    # Backup commands
    if [[ -d "${CLAUDE_DIR}/commands" ]]; then
        if [[ "$DRY_RUN" == true ]]; then
            log_info "[DRY-RUN] Would backup: ${CLAUDE_DIR}/commands/"
        else
            cp -r "${CLAUDE_DIR}/commands" "${backup_path}/"
            log_ok "Backed up commands directory"
        fi
    fi

    # Backup hooks
    if [[ -d "${CLAUDE_DIR}/hooks" ]]; then
        if [[ "$DRY_RUN" == true ]]; then
            log_info "[DRY-RUN] Would backup: ${CLAUDE_DIR}/hooks/"
        else
            cp -r "${CLAUDE_DIR}/hooks" "${backup_path}/"
            log_ok "Backed up hooks directory"
        fi
    fi

    # Backup workflows
    if [[ -d "${CLAUDE_DIR}/workflows" ]]; then
        if [[ "$DRY_RUN" == true ]]; then
            log_info "[DRY-RUN] Would backup: ${CLAUDE_DIR}/workflows/"
        else
            cp -r "${CLAUDE_DIR}/workflows" "${backup_path}/"
            log_ok "Backed up workflows directory"
        fi
    fi

    if [[ "$DRY_RUN" != true ]]; then
        log_ok "Backups saved to: ${backup_path}"
    fi
}

# Pull latest from main
pull_latest() {
    log_section "Pulling Latest Changes"

    if [[ "$LOCAL_ONLY" == true ]]; then
        log_info "Skipping git pull (--local mode)"
        return 0
    fi

    cd "$REPO_DIR"

    # Get current branch
    local current_branch=$(git branch --show-current)

    if [[ "$current_branch" != "main" ]]; then
        log_warn "Currently on branch: ${current_branch}"
        if [[ "$FORCE" != true ]]; then
            read -p "Switch to main and pull? (y/N): " confirm
            if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
                log_info "Staying on ${current_branch}"
            else
                if [[ "$DRY_RUN" == true ]]; then
                    log_info "[DRY-RUN] Would: git checkout main"
                else
                    git checkout main
                fi
            fi
        fi
    fi

    if [[ "$DRY_RUN" == true ]]; then
        log_info "[DRY-RUN] Would: git pull origin main"
        git fetch origin main --dry-run 2>&1 || true
    else
        log_info "Fetching and pulling from origin/main..."
        git fetch origin main
        git pull origin main
        log_ok "Repository updated"
    fi
}

# Update base-agents submodule
update_base_agents_submodule() {
    log_section "Updating Base Agents Submodule"

    cd "$REPO_DIR"

    if [[ "$DRY_RUN" == true ]]; then
        log_info "[DRY-RUN] Would: git submodule update --recursive"
        return 0
    fi

    if [[ ! -d "$BASE_AGENTS_ROOT/.git" ]] && [[ ! -f "$BASE_AGENTS_ROOT/.git" ]]; then
        log_info "Initializing base-agents submodule..."
        git submodule update --init --recursive
        log_ok "base-agents submodule initialized"
    else
        log_info "Updating base-agents submodule..."
        git submodule update --recursive
        log_ok "base-agents submodule updated"
    fi

    # Verify base-agents has required directories
    if [[ ! -d "$BASE_AGENTS_ROOT/.claude" ]]; then
        log_warn "base-agents/.claude directory not found"
        log_warn "Submodule may not be properly initialized"
    else
        log_ok "base-agents ready at ${BASE_AGENTS_ROOT}"
    fi
}

# Update MCP server repositories
update_mcp_repos() {
    log_section "Updating MCP Server Repositories"

    # Load paths from .env or use defaults
    if [[ -f "$ENV_FILE" ]]; then
        source "$ENV_FILE"
    fi

    local jira_path="${JIRA_MCP_PATH:-${REPO_DIR}/mcp-servers/jira}"
    local bb_path="${BITBUCKET_MCP_PATH:-${REPO_DIR}/mcp-servers/bitbucket}"

    for mcp_info in "jira:${jira_path}" "bitbucket:${bb_path}"; do
        local name="${mcp_info%%:*}"
        local path="${mcp_info#*:}"

        if [[ ! -d "${path}/.git" ]]; then
            log_warn "${name}: not found at ${path}"
            log_info "  Run install.sh to clone, or set path in .env"
            continue
        fi

        if [[ "$DRY_RUN" == true ]]; then
            log_info "[DRY-RUN] Would update: ${name} at ${path}"
            continue
        fi

        log_info "Updating ${name}..."
        (
            cd "$path"
            git pull origin main
            npm install
            npm run build
        )
        log_ok "${name}: updated and rebuilt"
    done
}

# Check if project repos are configured
check_project_repos_configured() {
    if [[ -f "$ENV_FILE" ]]; then
        source "$ENV_FILE"
    fi

    # Check if PROJECT_REPOS is set
    if [[ -z "${PROJECT_REPOS:-}" ]]; then
        return 1
    fi

    return 0
}

# Sync project repositories (pull latest)
sync_project_repos() {
    log_section "Syncing Project Repositories"

    # Load configuration
    if [[ -f "$ENV_FILE" ]]; then
        source "$ENV_FILE"
    fi

    # Check if repos are configured
    if [[ -z "${PROJECT_REPOS:-}" ]]; then
        log_warn "Project repositories not configured in .env"
        echo ""
        log_info "Multi-repo setup allows you to manage all project repositories together."
        log_info "To configure, run: ./scripts/install.sh --configure-repos"
        echo ""

        if [[ "$FORCE" != true ]]; then
            read -rp "Would you like to configure project repositories now? (y/N): " confirm
            if [[ "$confirm" == "y" || "$confirm" == "Y" ]]; then
                # Run install.sh configure-repos
                "${SCRIPT_DIR}/install.sh" --configure-repos
                return $?
            fi
        fi

        log_info "Skipping project repository sync"
        return 0
    fi

    # Resolve project root
    local project_root="${PROJECT_ROOT:-$(dirname "$REPO_DIR")}"
    if [[ "$project_root" == ".." || "$project_root" == "../"* ]]; then
        project_root="$(cd "$REPO_DIR" && cd "$project_root" && pwd)"
    fi

    log_info "Project root: ${project_root}"
    echo ""

    # Combine core and optional repos
    local all_repos="$PROJECT_REPOS"
    if [[ -n "${PROJECT_REPOS_OPTIONAL:-}" ]]; then
        all_repos="${all_repos},${PROJECT_REPOS_OPTIONAL}"
    fi

    IFS=',' read -ra repos <<< "$all_repos"
    local updated=0
    local skipped=0
    local missing=0

    for repo in "${repos[@]}"; do
        repo=$(echo "$repo" | xargs)  # Trim whitespace
        local repo_path="${project_root}/${repo}"

        if [[ ! -d "${repo_path}/.git" ]]; then
            log_warn "${repo}: not found at ${repo_path}"
            ((missing++)) || true
            continue
        fi

        if [[ "$DRY_RUN" == true ]]; then
            log_info "[DRY-RUN] Would sync: ${repo}"
            continue
        fi

        # Get current branch
        local current_branch
        current_branch=$(cd "$repo_path" && git branch --show-current 2>/dev/null || echo "unknown")

        # Check for uncommitted changes
        if [[ -n "$(cd "$repo_path" && git status --porcelain 2>/dev/null)" ]]; then
            log_warn "${repo}: has uncommitted changes (skipping pull)"
            ((skipped++)) || true
            continue
        fi

        log_info "Syncing ${repo} (${current_branch})..."
        if (cd "$repo_path" && git fetch origin && git pull origin "$current_branch" 2>/dev/null); then
            log_ok "${repo}: synced"
            ((updated++)) || true
        else
            log_warn "${repo}: pull failed (may need manual intervention)"
            ((skipped++)) || true
        fi
    done

    echo ""
    if [[ "$DRY_RUN" != true ]]; then
        log_ok "Project repos: ${updated} synced, ${skipped} skipped, ${missing} not found"
    fi

    if [[ $missing -gt 0 ]]; then
        log_info "To clone missing repositories: ./scripts/install.sh --configure-repos"
    fi
}

# Validate Docs centralized documentation structure
validate_gw_docs() {
    log_section "Validating Docs Configuration"

    # Load environment
    if [[ -f "$ENV_FILE" ]]; then
        source "$ENV_FILE"
    fi

    # Determine TENANT_DOCS_PATH
    local docs_path="${TENANT_DOCS_PATH:-}"
    if [[ -z "$docs_path" ]]; then
        local project_root="${PROJECT_ROOT:-$(dirname "$REPO_DIR")}"
        docs_path="${project_root}/project-docs"
    fi

    # Verify project-docs path exists
    if [[ ! -d "$docs_path" ]]; then
        log_warn "TENANT_DOCS_PATH points to non-existent directory: ${docs_path}"
        log_info "Skipping project-docs validation..."
        return 0
    fi

    log_ok "project-docs directory: ${docs_path}"

    # Verify all required directories exist
    local missing_dirs=()
    local required_dirs=(
        "initiatives"
        "designs"
        "implementations"
        "technical"
        "tools"
        "runbooks"
        "patterns"
        "release-notes"
        "repositories"
    )

    for dir in "${required_dirs[@]}"; do
        if [[ ! -d "${docs_path}/${dir}" ]]; then
            missing_dirs+=("$dir")
        fi
    done

    if [[ ${#missing_dirs[@]} -ne 0 ]]; then
        log_warn "Missing project-docs directories: ${missing_dirs[*]}"
        log_info "Run: cd ${docs_path} && mkdir -p ${missing_dirs[*]}"
    else
        log_ok "All project-docs directories present"
    fi

    # Verify config file exists
    local config_file="${REPO_DIR}/config/project-docs-categories.yaml"
    if [[ ! -f "$config_file" ]]; then
        log_warn "config/project-docs-categories.yaml not found"
    else
        log_ok "config/project-docs-categories.yaml present"
    fi

    # Check for file naming consistency in project-docs
    log_info "Checking file naming conventions in project-docs..."
    local invalid_files
    invalid_files=$(find "$docs_path" -name "*.md" -type f 2>/dev/null | \
        grep -vE "[0-9]{4}-[0-9]{2}-[0-9]{2}-" | \
        grep -v "index.md" | \
        grep -v "README.md" | \
        grep -v "CLAUDE.md" | \
        grep -v "TESTING.md" | \
        grep -v "VALIDATION.md" | \
        head -5 || true)

    if [[ -n "$invalid_files" ]]; then
        log_warn "Some files don't follow YYYY-MM-DD naming convention:"
        echo "$invalid_files" | sed 's/^/    - /'
    else
        log_ok "File naming conventions followed"
    fi

    # Verify repository structure has required files
    log_info "Checking repository CLAUDE.md, TESTING.md, VALIDATION.md..."
    local repos_with_issues=()
    local project_root="${PROJECT_ROOT:-$(dirname "$REPO_DIR")}"

    for repo_dir in lambda-functions frontend-app auth-service e2e-tests sdk agents canary; do
        local repo_path="${project_root}/${repo_dir}"
        if [[ -d "$repo_path" ]]; then
            for file in CLAUDE.md TESTING.md VALIDATION.md; do
                if [[ ! -f "${repo_path}/${file}" ]]; then
                    repos_with_issues+=("${repo_dir} missing ${file}")
                fi
            done
        fi
    done

    if [[ ${#repos_with_issues[@]} -ne 0 ]]; then
        log_warn "Repositories missing required files:"
        printf '%s\n' "${repos_with_issues[@]}" | sed 's/^/    - /'
    else
        log_ok "All repositories have required files"
    fi

    # Ensure DESIGN_* vars are in .env (add if missing)
    if [[ -f "$ENV_FILE" ]] && ! grep -q "DESIGN_DOCS_PATH" "$ENV_FILE" 2>/dev/null; then
        local project_root="${PROJECT_ROOT:-$(dirname "$REPO_DIR")}"
        cat >> "$ENV_FILE" << EOF

# Design Workflow Configuration (added by update.sh)
DESIGN_DOCS_PATH=${docs_path}/designs
DESIGN_SPA_PATH=${project_root}/frontend-app
DESIGN_WIREFRAMES_PATH=${project_root}/frontend-app/docs/wireframes
DESIGN_CATALOG_PATH=${project_root}/frontend-app/docs/design-catalog
DESIGN_DIAGRAMS_PATH=${docs_path}/designs
DESIGN_CML_PATH=${docs_path}/domain
EOF
        log_info "Added DESIGN_* configuration to .env"
    else
        log_ok "DESIGN_* configuration already in .env"
    fi

    # Ensure TENANT_* discovery vars are in .env (add if missing)
    if [[ -f "$ENV_FILE" ]] && ! grep -q "TENANT_ROADMAP_PATH" "$ENV_FILE" 2>/dev/null; then
        cat >> "$ENV_FILE" << EOF

# Discovery Workflow Configuration (added by update.sh)
TENANT_ROADMAP_PATH=${docs_path}/initiatives/roadmap.json
TENANT_DOCS_PATH=${docs_path}
TENANT_DOMAIN_PATH=${docs_path}/domain
TENANT_PROJECT=YOUR-PROJECT-KEY
EOF
        log_info "Added TENANT_* discovery configuration to .env"
    else
        log_ok "TENANT_ROADMAP_PATH already in .env"
    fi

    log_ok "PROJ-Docs validation complete"
}

# Update commands
update_commands() {
    log_section "Updating Workflow Commands"

    local commands_src="$BASE_AGENTS_ROOT/.claude/commands"
    local commands_dst="${CLAUDE_DIR}/commands"

    if [[ ! -d "$commands_src" ]]; then
        log_warn "Commands source directory not found: ${commands_src}"
        return 1
    fi

    mkdir -p "$commands_dst"

    local updated=0
    local added=0
    local groups_updated=0

    # Update top-level command files from base-agents
    for cmd_file in "${commands_src}"/*.md; do
        if [[ -f "$cmd_file" ]]; then
            local filename=$(basename "$cmd_file")
            local dst_file="${commands_dst}/${filename}"

            if [[ "$DRY_RUN" == true ]]; then
                if [[ -f "$dst_file" ]]; then
                    if ! diff -q "$cmd_file" "$dst_file" &>/dev/null; then
                        log_info "[DRY-RUN] Would update: ${filename}"
                        ((updated++)) || true
                    fi
                else
                    log_info "[DRY-RUN] Would add: ${filename}"
                    ((added++)) || true
                fi
            else
                if [[ -f "$dst_file" ]]; then
                    if ! diff -q "$cmd_file" "$dst_file" &>/dev/null; then
                        cp "$cmd_file" "$dst_file"
                        log_ok "Updated: ${filename%.md}"
                        ((updated++)) || true
                    fi
                else
                    cp "$cmd_file" "$dst_file"
                    log_ok "Added: ${filename%.md}"
                    ((added++)) || true
                fi
            fi
        fi
    done

    # Update command group subdirectories from base-agents (e.g., loop/, metrics/)
    for group_dir in "${commands_src}"/*/; do
        if [[ -d "$group_dir" ]]; then
            local group_name=$(basename "$group_dir")
            local dst_group="${commands_dst}/${group_name}"

            if [[ "$DRY_RUN" == true ]]; then
                log_info "[DRY-RUN] Would sync command group: ${group_name}/"
                ((groups_updated++)) || true
            else
                mkdir -p "$dst_group"
                local group_files_updated=0

                for cmd_file in "${group_dir}"*.md; do
                    if [[ -f "$cmd_file" ]]; then
                        local filename=$(basename "$cmd_file")
                        local dst_file="${dst_group}/${filename}"

                        if [[ ! -f "$dst_file" ]] || ! diff -q "$cmd_file" "$dst_file" &>/dev/null; then
                            cp "$cmd_file" "$dst_file"
                            ((group_files_updated++)) || true
                        fi
                    fi
                done

                if [[ $group_files_updated -gt 0 ]]; then
                    log_ok "Updated command group: ${group_name}/ (${group_files_updated} files)"
                    ((groups_updated++)) || true
                fi
            fi
        fi
    done

    # Apply project-specific command overrides
    local base_commands="${REPO_DIR}/.claude/commands"
    if [[ -d "$base_commands" ]] && [[ "$DRY_RUN" != true ]]; then
        for cmd_file in "${base_commands}"/*.md; do
            if [[ -f "$cmd_file" ]]; then
                local filename=$(basename "$cmd_file")
                cp "$cmd_file" "${commands_dst}/${filename}"
                log_info "Applied the project override: ${filename%.md}"
            fi
        done

        # Apply the project command group overrides
        for group_dir in "${base_commands}"/*/; do
            if [[ -d "$group_dir" ]]; then
                local group_name=$(basename "$group_dir")
                local dst_group="${commands_dst}/${group_name}"
                mkdir -p "$dst_group"

                for cmd_file in "${group_dir}"*.md; do
                    if [[ -f "$cmd_file" ]]; then
                        local filename=$(basename "$cmd_file")
                        cp "$cmd_file" "${dst_group}/${filename}"
                    fi
                done
            fi
        done
    fi

    # Remove deprecated claude-flow commands (may exist in base-agents source)
    if [[ "$DRY_RUN" != true ]]; then
        rm -f "${commands_dst}/claude-flow-integration.md" 2>/dev/null || true
    fi

    if [[ $updated -eq 0 && $added -eq 0 && $groups_updated -eq 0 ]]; then
        log_ok "All commands up to date"
    else
        log_ok "Commands: ${updated} updated, ${added} added, ${groups_updated} groups synced"
    fi
}

# Update hooks
update_hooks() {
    log_section "Updating Hooks"

    local hooks_src="$BASE_AGENTS_ROOT/.claude/hooks"
    local hooks_dst="${CLAUDE_DIR}/hooks"

    if [[ ! -d "$hooks_src" ]]; then
        log_warn "Hooks source directory not found: ${hooks_src}"
        return 1
    fi

    mkdir -p "$hooks_dst"

    local updated=0
    local added=0

    # Update hooks from base-agents
    for hook_file in "${hooks_src}"/*; do
        if [[ -f "$hook_file" ]]; then
            local filename=$(basename "$hook_file")
            local dst_file="${hooks_dst}/${filename}"

            if [[ "$DRY_RUN" == true ]]; then
                if [[ -f "$dst_file" ]]; then
                    if ! diff -q "$hook_file" "$dst_file" &>/dev/null; then
                        log_info "[DRY-RUN] Would update: ${filename}"
                        ((updated++)) || true
                    fi
                else
                    log_info "[DRY-RUN] Would add: ${filename}"
                    ((added++)) || true
                fi
            else
                if [[ -f "$dst_file" ]]; then
                    if ! diff -q "$hook_file" "$dst_file" &>/dev/null; then
                        cp "$hook_file" "$dst_file"
                        chmod +x "$dst_file" 2>/dev/null || true
                        log_ok "Updated: ${filename}"
                        ((updated++)) || true
                    fi
                else
                    cp "$hook_file" "$dst_file"
                    chmod +x "$dst_file" 2>/dev/null || true
                    log_ok "Added: ${filename}"
                    ((added++)) || true
                fi
            fi
        fi
    done

    # Apply project-specific hook overrides
    local base_hooks="${REPO_DIR}/.claude/hooks"
    if [[ -d "$base_hooks" ]] && [[ "$DRY_RUN" != true ]]; then
        for hook_file in "${base_hooks}"/*; do
            if [[ -f "$hook_file" ]]; then
                local filename=$(basename "$hook_file")
                cp "$hook_file" "${hooks_dst}/${filename}"
                chmod +x "${hooks_dst}/${filename}" 2>/dev/null || true
                log_info "Applied the project hook: ${filename}"
            fi
        done
    fi

    if [[ $updated -eq 0 && $added -eq 0 ]]; then
        log_ok "All hooks up to date"
    else
        log_ok "Hooks: ${updated} updated, ${added} added"
    fi
}

# NOTE: setup_project_hooks() was REMOVED
# Hooks should ONLY be installed to ~/.claude/hooks/ (done by update_hooks())
# Individual repos do NOT get .claude/ folders - they all use the global ~/.claude/
#
# See architecture documentation at the top of this file.
setup_project_hooks() {
    # This function is now a no-op but kept for backwards compatibility
    # All hooks are installed to ~/.claude/hooks/ by update_hooks()
    log_info "Note: Hooks are installed to ~/.claude/hooks/ (shared by all repos)"
}

update_statusline() {
    log_section "Updating Statusline"

    local statusline_src="$BASE_AGENTS_ROOT/.claude/statusline-command.sh"
    local statusline_dst="${CLAUDE_DIR}/statusline-command.sh"

    if [[ ! -f "$statusline_src" ]]; then
        log_warn "Statusline script not found: ${statusline_src}"
        return 1
    fi

    if [[ "$DRY_RUN" == true ]]; then
        if [[ -f "$statusline_dst" ]]; then
            if ! diff -q "$statusline_src" "$statusline_dst" &>/dev/null; then
                log_info "[DRY-RUN] Would update: statusline-command.sh"
            else
                log_info "[DRY-RUN] Statusline unchanged"
            fi
        else
            log_info "[DRY-RUN] Would install: statusline-command.sh"
        fi
        return 0
    fi

    cp "$statusline_src" "$statusline_dst"
    chmod +x "$statusline_dst"
    log_ok "Statusline updated: ${statusline_dst}"
}

# Update workflows
update_workflows() {
    log_section "Updating Workflows"

    local workflows_src="${REPO_DIR}/.claude/workflows"
    local workflows_dst="${CLAUDE_DIR}/workflows"

    if [[ ! -d "$workflows_src" ]]; then
        log_warn "Workflows source directory not found: ${workflows_src}"
        return 0
    fi

    mkdir -p "$workflows_dst"

    local updated=0
    local added=0

    # Update workflow YAML files
    for workflow_file in "${workflows_src}"/*.yaml "${workflows_src}"/*.yml; do
        if [[ -f "$workflow_file" ]]; then
            local filename=$(basename "$workflow_file")
            local dst_file="${workflows_dst}/${filename}"

            if [[ "$DRY_RUN" == true ]]; then
                if [[ -f "$dst_file" ]]; then
                    if ! diff -q "$workflow_file" "$dst_file" &>/dev/null; then
                        log_info "[DRY-RUN] Would update: ${filename}"
                        ((updated++)) || true
                    fi
                else
                    log_info "[DRY-RUN] Would add: ${filename}"
                    ((added++)) || true
                fi
            else
                if [[ -f "$dst_file" ]]; then
                    if ! diff -q "$workflow_file" "$dst_file" &>/dev/null; then
                        cp "$workflow_file" "$dst_file"
                        log_ok "Updated: ${filename%.yaml}"
                        ((updated++)) || true
                    fi
                else
                    cp "$workflow_file" "$dst_file"
                    log_ok "Added: ${filename%.yaml}"
                    ((added++)) || true
                fi
            fi
        fi
    done

    # Update README if exists
    local readme_src="${workflows_src}/README.md"
    local readme_dst="${workflows_dst}/README.md"
    if [[ -f "$readme_src" ]]; then
        if [[ "$DRY_RUN" == true ]]; then
            if [[ -f "$readme_dst" ]] && ! diff -q "$readme_src" "$readme_dst" &>/dev/null; then
                log_info "[DRY-RUN] Would update: README.md"
            fi
        else
            if [[ ! -f "$readme_dst" ]] || ! diff -q "$readme_src" "$readme_dst" &>/dev/null; then
                cp "$readme_src" "$readme_dst"
                log_ok "Updated: README.md"
            fi
        fi
    fi

    if [[ $updated -eq 0 && $added -eq 0 ]]; then
        log_ok "All workflows up to date"
    else
        log_ok "Workflows: ${updated} updated, ${added} added"
    fi
}

# Update skills
update_skills() {
    log_section "Updating Skills"

    local skills_src="$BASE_AGENTS_ROOT/.claude/skills"
    local skills_dst="${CLAUDE_DIR}/skills"

    if [[ ! -d "$skills_src" ]]; then
        log_warn "Skills source directory not found: ${skills_src}"
        return 0
    fi

    mkdir -p "$skills_dst"

    if [[ "$DRY_RUN" == true ]]; then
        log_info "[DRY-RUN] Would sync skills from base-agents"
    else
        cp -r "$skills_src"/* "$skills_dst/" 2>/dev/null || true

        # Apply project-specific skill overrides
        local base_skills="${REPO_DIR}/.claude/skills"
        if [[ -d "$base_skills" ]]; then
            cp -r "$base_skills"/* "$skills_dst/" 2>/dev/null || true
            log_info "Applied the project skill overrides"
        fi

        # Remove deprecated claude-flow skills (may exist in base-agents source)
        rm -rf "${skills_dst}/claude-flow" "${skills_dst}/examples/claude-flow" 2>/dev/null || true

        log_ok "Skills updated"
    fi
}

# Generate skills cache for fast session startup
generate_skills_cache() {
    log_section "Refreshing Skills Cache"

    local cache_builder="${CLAUDE_DIR}/hooks/skills-cache-builder.py"

    if [[ ! -f "$cache_builder" ]]; then
        log_warn "Skills cache builder not found: ${cache_builder}"
        return 1
    fi

    # Run the cache builder
    if python3 "$cache_builder" &>/dev/null; then
        log_ok "Skills cache refreshed successfully"
    else
        log_warn "Failed to refresh skills cache (non-fatal)"
    fi
}

# Create/update symlinks from project root to global skills (REST executable skills)
# This enables project-relative paths like .claude/skills/jira/search_issues.ts
symlink_skills_to_project() {
    log_section "Updating Skills Symlinks in Project Root"

    # Load configuration
    if [[ -f "$ENV_FILE" ]]; then
        source "$ENV_FILE"
    fi

    # Resolve project root
    local project_root="${PROJECT_ROOT:-$(dirname "$REPO_DIR")}"
    if [[ "$project_root" == ".." || "$project_root" == "../"* ]]; then
        project_root="$(cd "$REPO_DIR" && cd "$project_root" && pwd)"
    fi

    local project_skills="${project_root}/.claude/skills"
    local global_skills="${CLAUDE_DIR}/skills"

    # REST skill directories to symlink
    local skill_dirs=("jira" "bitbucket" "agentdb" "slack" "cml" "concourse" "fly" "playwright")

    if [[ "$DRY_RUN" == true ]]; then
        log_info "[DRY-RUN] Would create/update symlinks in ${project_skills}:"
        for skill_dir in "${skill_dirs[@]}"; do
            log_info "  ${skill_dir} -> ${global_skills}/${skill_dir}"
        done
        return 0
    fi

    # Create project .claude/skills directory if needed
    mkdir -p "$project_skills"

    local linked=0
    local skipped=0

    for skill_dir in "${skill_dirs[@]}"; do
        local src="${global_skills}/${skill_dir}"
        local dst="${project_skills}/${skill_dir}"

        if [[ ! -d "$src" ]]; then
            log_warn "${skill_dir}: source not found at ${src}"
            continue
        fi

        if [[ -L "$dst" ]]; then
            # Already a symlink - check if it points to the right place
            local current_target=$(readlink "$dst")
            if [[ "$current_target" == "$src" ]]; then
                log_ok "${skill_dir}: symlink up to date"
                ((skipped++)) || true
            else
                # Symlink exists but points elsewhere - update it
                rm "$dst"
                ln -s "$src" "$dst"
                log_ok "${skill_dir}: symlink updated"
                ((linked++)) || true
            fi
        elif [[ -d "$dst" ]]; then
            # Directory exists (not a symlink) - warn and skip
            log_warn "${skill_dir}: directory exists at ${dst} (not a symlink, skipping)"
            ((skipped++)) || true
        else
            # Create new symlink
            ln -s "$src" "$dst"
            log_ok "${skill_dir}: symlink created"
            ((linked++)) || true
        fi
    done

    log_ok "Skills symlinks: ${linked} updated, ${skipped} unchanged"
}

# Update project-root .claude/ directory with config templates and rx files
# Seeds credentials.json, settings.json if missing; always syncs rx and repositories.json.
update_project_claude_dir() {
    log_section "Updating Project Root .claude/ Directory"

    # Load configuration
    if [[ -f "$ENV_FILE" ]]; then
        source "$ENV_FILE"
    fi

    # Resolve project root
    local project_root="${PROJECT_ROOT:-$(dirname "$REPO_DIR")}"
    if [[ "$project_root" == ".." || "$project_root" == "../"* ]]; then
        project_root="$(cd "$REPO_DIR" && cd "$project_root" && pwd)"
    fi

    local project_claude="${project_root}/.claude"
    mkdir -p "${project_claude}/commands" "${project_claude}/skills"

    if [[ "$DRY_RUN" == true ]]; then
        log_info "[DRY-RUN] Would update project root .claude/ directory at ${project_claude}"
        return 0
    fi

    # --- Seed credentials.json (only if missing) ---
    local creds_file="${project_claude}/credentials.json"
    local creds_template="${REPO_DIR}/templates/project-credentials.json"
    if [[ ! -f "$creds_file" ]]; then
        if [[ -f "$creds_template" ]]; then
            cp "$creds_template" "$creds_file"
            log_ok "credentials.json: seeded template (fill in your values)"
        else
            log_warn "credentials.json template not found: ${creds_template}"
        fi
    else
        log_ok "credentials.json: already exists"
    fi

    # --- Seed settings.json (only if missing) ---
    local settings_file="${project_claude}/settings.json"
    local settings_template="${REPO_DIR}/templates/project-settings.json"
    if [[ ! -f "$settings_file" ]]; then
        if [[ -f "$settings_template" ]]; then
            cp "$settings_template" "$settings_file"
            log_ok "settings.json: seeded template"
        else
            log_warn "settings.json template not found: ${settings_template}"
        fi
    else
        log_ok "settings.json: already exists"
    fi

    # --- Copy repositories.json (always update) ---
    local repos_src="${REPO_DIR}/config/repositories.json"
    local repos_dst="${project_claude}/repositories.json"
    if [[ -f "$repos_src" ]]; then
        cp "$repos_src" "$repos_dst"
        log_ok "repositories.json: updated from config"
    else
        log_warn "repositories.json source not found: ${repos_src}"
    fi

    # --- Sync rx command to project root ---
    local rx_cmd_src="${REPO_DIR}/.claude/commands/rx.md"
    local rx_cmd_dst="${project_claude}/commands/rx.md"
    if [[ -f "$rx_cmd_src" ]]; then
        cp "$rx_cmd_src" "$rx_cmd_dst"
        log_ok "commands/rx.md: installed"
    fi

    # --- Sync rx skill to project root ---
    local rx_skill_src="${REPO_DIR}/.claude/skills/rx"
    local rx_skill_dst="${project_claude}/skills/rx"
    if [[ -d "$rx_skill_src" ]]; then
        mkdir -p "$rx_skill_dst"
        cp -r "$rx_skill_src"/* "$rx_skill_dst/" 2>/dev/null || true
        log_ok "skills/rx: installed"
    fi

    log_ok "Project root .claude/ directory updated"
}

# Update hook configurations in settings.json
update_hook_configs() {
    log_section "Updating Hook Configurations"

    local settings_file="${CLAUDE_DIR}/settings.json"
    local template_file="${REPO_DIR}/base/.claude/settings.template.json"

    if [[ ! -f "$template_file" ]]; then
        log_warn "Hook configuration template not found: ${template_file}"
        return 1
    fi

    if [[ ! -f "$settings_file" ]]; then
        log_warn "User settings not found. Run install.sh for initial setup."
        return 1
    fi

    if ! command -v jq &>/dev/null; then
        log_warn "jq not installed - run update_brew_packages first"
        return 1
    fi

    # Backup existing hooks before modification
    local backup_file="${settings_file}.hooks-backup.${TIMESTAMP}"
    cp "$settings_file" "$backup_file"
    log_info "Backed up existing hooks to: ${backup_file}"

    if [[ "$DRY_RUN" == true ]]; then
        log_info "[DRY-RUN] Would merge all template keys into settings"
        return 0
    fi

    # Merge all template keys into settings:
    # - hooks, statusLine, extraKnownMarketplaces: template takes precedence
    # - env: template defaults, existing user values preserved (user overrides win)
    # - permissions: use template if not already set
    # - includeCoAuthoredBy: set from template if not present
    local merged_settings
    merged_settings=$(jq --argjson template "$(cat "$template_file")" '
        # Hooks: template takes precedence
        .hooks = ($template.hooks // {})
        # StatusLine: template takes precedence
        | if $template.statusLine then .statusLine = $template.statusLine else . end
        # Env: merge (template defaults, existing overrides preserved)
        | .env = (($template.env // {}) * (.env // {}))
        # Permissions: use template if current is empty or missing; always enforce defaultMode from template
        | if ((.permissions // {}) | length) == 0 then .permissions = ($template.permissions // {}) else . end
        | if $template.permissions.defaultMode then .permissions.defaultMode = $template.permissions.defaultMode else . end
        # ExtraKnownMarketplaces: merge (both sources preserved)
        | .extraKnownMarketplaces = (($template.extraKnownMarketplaces // {}) * (.extraKnownMarketplaces // {}))
        # includeCoAuthoredBy: set from template if not present (use explicit null check - jq // treats false as absent)
        | .includeCoAuthoredBy = (if (.includeCoAuthoredBy != null) then .includeCoAuthoredBy else ($template.includeCoAuthoredBy // false) end)
        # Permission prompt skip flags: always set from template when present
        | if $template.skipDangerousModePermissionPrompt != null then .skipDangerousModePermissionPrompt = $template.skipDangerousModePermissionPrompt else . end
        | if $template.skipAutoPermissionPrompt != null then .skipAutoPermissionPrompt = $template.skipAutoPermissionPrompt else . end
    ' "$settings_file")

    # Write merged settings to temp file first
    local temp_file=$(mktemp)
    echo "$merged_settings" > "$temp_file"

    # Validate and apply
    if jq empty "$temp_file" 2>/dev/null; then
        mv "$temp_file" "$settings_file"

        # Verify hook types installed
        local installed_hooks=0
        for hook_type in SessionStart PreToolUse PostToolUse SessionEnd; do
            if jq -e ".hooks.${hook_type}" "$settings_file" &>/dev/null; then
                log_ok "Hook type present: ${hook_type}"
                ((installed_hooks++)) || true
            else
                log_warn "Hook type missing: ${hook_type}"
            fi
        done

        log_ok "Settings merged: ${installed_hooks} hook types installed"
    else
        log_error "Generated invalid JSON - settings not updated"
        rm -f "$temp_file"
        return 1
    fi
}

# Update plugins in settings.json (non-interactive, removes stale plugins)
update_plugins() {
    log_section "Updating Plugins"

    local settings_file="${CLAUDE_DIR}/settings.json"

    if [[ ! -f "$settings_file" ]]; then
        log_warn "Settings file not found. Run install.sh for initial setup."
        return 0
    fi

    if [[ "$DRY_RUN" == true ]]; then
        log_info "[DRY-RUN] Would update plugins in settings.json"
        return 0
    fi

    # Load plugin list from config/plugins.json (single source of truth)
    local plugins_config="${REPO_DIR}/config/plugins.json"
    local plugins=()

    if [[ -f "$plugins_config" ]] && command -v jq &>/dev/null; then
        while IFS= read -r plugin_id; do
            plugins+=("$plugin_id")
        done < <(jq -r '.[] | "\(.name)@\(.marketplace)"' "$plugins_config")
        log_info "Loaded ${#plugins[@]} plugins from config/plugins.json"
    else
        # Fallback: hardcoded list if config file or jq unavailable
        plugins=(
            "superpowers@claude-plugins-official"
            "context7@claude-plugins-official"
            "code-review@claude-plugins-official"
            "impeccable@impeccable"
            "ralph-loop@claude-plugins-official"
            "ralph-wiggum@claude-plugins-official"
            "concourse-ci@netresearch-claude-code-marketplace"
            "gopls-lsp@claude-plugins-official"
            "typescript-lsp@claude-plugins-official"
        )
        log_warn "Using fallback plugin list (config/plugins.json not found or jq unavailable)"
    fi

    # Ensure enabledPlugins object exists
    local temp_file
    temp_file=$(mktemp)
    jq '.enabledPlugins //= {}' "$settings_file" > "$temp_file"
    mv "$temp_file" "$settings_file"

    # Remove stale plugins (not in canonical list, not local marketplace)
    local current_plugins
    current_plugins=$(jq -r '.enabledPlugins // {} | keys[]' "$settings_file" 2>/dev/null)

    while IFS= read -r existing; do
        [[ -z "$existing" ]] && continue
        # Keep local marketplace plugins (e.g., lsp@agents-local)
        if [[ "$existing" == *"-local" ]]; then
            log_ok "${existing}: kept (local marketplace)"
            continue
        fi
        local found=false
        for plugin in "${plugins[@]}"; do
            if [[ "$existing" == "$plugin" ]]; then
                found=true
                break
            fi
        done
        if [[ "$found" == false ]]; then
            log_warn "Removing stale plugin: ${existing}"
            temp_file=$(mktemp)
            jq --arg p "$existing" 'del(.enabledPlugins[$p])' "$settings_file" > "$temp_file"
            if jq empty "$temp_file" 2>/dev/null; then
                mv "$temp_file" "$settings_file"
            else
                rm -f "$temp_file"
            fi
        fi
    done <<< "$current_plugins"

    # Ensure canonical plugins are enabled
    for plugin in "${plugins[@]}"; do
        if jq -e ".enabledPlugins[\"${plugin}\"]" "$settings_file" &>/dev/null; then
            log_ok "${plugin}: enabled"
        else
            temp_file=$(mktemp)
            jq --arg p "$plugin" '.enabledPlugins[$p] = true' "$settings_file" > "$temp_file"
            if jq empty "$temp_file" 2>/dev/null; then
                mv "$temp_file" "$settings_file"
                log_ok "${plugin}: added"
            else
                rm -f "$temp_file"
            fi
        fi
    done

    log_ok "Plugins updated"
}

# Update testing tools (Pact, Hurl)
update_testing_tools() {
    log_section "Checking Testing Tools"

    if [[ "$DRY_RUN" == true ]]; then
        log_info "[DRY-RUN] Would check/update testing tools:"
        log_info "  - @pact-foundation/pact-cli (npm)"
        return 0
    fi

    # Check/update Pact CLI
    if command -v pact &> /dev/null; then
        local current_version
        current_version=$(pact --version 2>/dev/null | head -n1 || echo "unknown")
        log_ok "Pact CLI: installed ($current_version)"

        # Check for updates
        log_info "Checking for Pact CLI updates..."
        if npm update -g @pact-foundation/pact-cli 2>/dev/null; then
            log_ok "Pact CLI: up to date"
        fi
    else
        log_warn "Pact CLI: not installed, installing..."
        if npm install -g @pact-foundation/pact-cli 2>/dev/null; then
            log_ok "Pact CLI: installed"
        else
            log_warn "Could not install Pact CLI"
            log_info "  To install manually: npm install -g @pact-foundation/pact-cli"
        fi
    fi
}

# Update tokf filters for fly and terraform commands
update_tokf() {
    log_section "Updating Tokf Filters"

    if ! command -v tokf &>/dev/null; then
        log_warn "tokf not installed - skipping filter update"
        return 0
    fi

    local tokf_src="${REPO_DIR}/tokf/filters"

    if [[ ! -d "$tokf_src" ]]; then
        log_warn "Tokf filter source not found: ${tokf_src}"
        return 0
    fi

    if [[ "$DRY_RUN" == true ]]; then
        log_info "[DRY-RUN] Would update tokf filters"
        return 0
    fi

    # Determine user-level filter directory (macOS vs Linux)
    local tokf_dst
    if [[ "$(uname)" == "Darwin" ]]; then
        tokf_dst="${HOME}/Library/Application Support/tokf/filters"
    else
        tokf_dst="${HOME}/.config/tokf/filters"
    fi

    # Copy filter directories preserving structure
    local updated=0
    local unchanged=0
    while IFS= read -r -d '' filter_file; do
        local rel_path="${filter_file#"${tokf_src}/"}"
        local dest_file="${tokf_dst}/${rel_path}"
        local dest_dir
        dest_dir="$(dirname "$dest_file")"
        mkdir -p "$dest_dir"

        if [[ ! -f "$dest_file" ]] || ! diff -q "$filter_file" "$dest_file" &>/dev/null; then
            cp "$filter_file" "$dest_file"
            updated=$((updated + 1))
        else
            unchanged=$((unchanged + 1))
        fi
    done < <(find "$tokf_src" -name '*.toml' -print0)

    if [[ $updated -gt 0 ]]; then
        log_ok "Updated ${updated} tokf filters (${unchanged} unchanged)"
    else
        log_ok "All ${unchanged} tokf filters up to date"
    fi
}

# Install e2e-config.json to ~/.claude/, resolving testDir to an absolute path
install_e2e_config() {
    log_section "Installing e2e-config.json"

    local src="${REPO_DIR}/.claude/e2e-config.json"
    local dst="${CLAUDE_DIR}/e2e-config.json"

    if [[ ! -f "$src" ]]; then
        log_warn "e2e-config.json source not found: ${src}"
        return 0
    fi

    if [[ "$DRY_RUN" == true ]]; then
        log_info "[DRY-RUN] Would install e2e-config.json to ${dst}"
        return 0
    fi

    if ! command -v jq &>/dev/null; then
        log_warn "jq not installed - cannot install e2e-config.json"
        return 0
    fi

    # Resolve testDir: replace leading ../ with the absolute project_root path
    local project_root="${PROJECT_ROOT:-}"
    if [[ -z "$project_root" ]] && [[ -f "$ENV_FILE" ]]; then
        project_root=$(grep -E '^PROJECT_ROOT=' "$ENV_FILE" | cut -d= -f2- | tr -d '"' | tr -d "'")
    fi
    if [[ -z "$project_root" ]]; then
        project_root="$(dirname "$REPO_DIR")"
    fi

    local test_dir_rel
    test_dir_rel=$(jq -r '.e2e.testDir' "$src")
    local test_dir_abs
    if [[ "$test_dir_rel" == ../* ]]; then
        test_dir_abs="${project_root}/${test_dir_rel#../}"
    else
        test_dir_abs="$test_dir_rel"
    fi

    jq --arg testDir "$test_dir_abs" '.e2e.testDir = $testDir' "$src" > "$dst"
    log_ok "e2e-config.json: installed to ${dst} (testDir → ${test_dir_abs})"
}

# Install Playwright browser binaries
install_playwright() {
    log_section "Installing Playwright"

    if ! command -v npx &>/dev/null; then
        log_warn "npx not available - skipping Playwright install"
        log_info "  Install Node.js first, then re-run update.sh"
        return 0
    fi

    if [[ "$DRY_RUN" == true ]]; then
        log_info "[DRY-RUN] Would install Playwright Chromium browser"
        return 0
    fi

    # Install Chromium browser binary
    if npx playwright install chromium 2>/dev/null; then
        log_ok "Chromium browser installed"
    else
        log_warn "Failed to install Chromium browser"
        log_info "  Run manually: npx playwright install chromium"
    fi
}

# Update CodeGraphContext (code graph MCP server)
update_codegraphcontext() {
    log_section "Checking CodeGraphContext"

    if [[ "$DRY_RUN" == true ]]; then
        log_info "[DRY-RUN] Would check CodeGraphContext and Neo4j"
        return 0
    fi

    if ! command -v cgc &>/dev/null; then
        log_warn "CodeGraphContext: not installed (pip install codegraphcontext)"
        return 0
    fi

    local cgc_version
    cgc_version=$(cgc --version 2>&1 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' || echo "unknown")
    log_ok "CodeGraphContext: installed (${cgc_version})"

    # Ensure Neo4j container survives reboots
    if command -v docker &>/dev/null; then
        local neo4j_policy
        neo4j_policy=$(docker inspect neo4j --format '{{.HostConfig.RestartPolicy.Name}}' 2>/dev/null || echo "")
        if [[ "$neo4j_policy" == "no" ]] || [[ -z "$neo4j_policy" ]]; then
            if docker inspect neo4j &>/dev/null; then
                docker update --restart unless-stopped neo4j &>/dev/null
                log_ok "Neo4j: restart policy set to unless-stopped"
            fi
        elif [[ "$neo4j_policy" == "unless-stopped" ]]; then
            log_ok "Neo4j: restart policy already set correctly"
        fi

        # Start Neo4j if not running
        local neo4j_status
        neo4j_status=$(docker ps --filter name=neo4j --format '{{.Status}}' 2>/dev/null || echo "")
        if [[ -z "$neo4j_status" ]]; then
            docker start neo4j &>/dev/null && log_ok "Neo4j: started" || log_warn "Neo4j: could not start"
        else
            log_ok "Neo4j: running (${neo4j_status})"
        fi
    fi

    # Verify CGC MCP server is configured in ~/.claude.json
    local claude_json="$HOME/.claude.json"
    local cgc_path
    cgc_path=$(command -v cgc)

    if [[ -f "$claude_json" ]]; then
        if jq -e '.mcpServers["CodeGraphContext"]' "$claude_json" &>/dev/null; then
            log_ok "CodeGraphContext MCP server: configured in ~/.claude.json"
        else
            local temp_file
            temp_file=$(mktemp)
            jq --arg cgc "$cgc_path" '.mcpServers["CodeGraphContext"] = {"command": $cgc, "args": ["mcp", "start"], "type": "stdio"}' \
                "$claude_json" > "$temp_file"
            if jq empty "$temp_file" 2>/dev/null; then
                mv "$temp_file" "$claude_json"
                log_ok "CodeGraphContext MCP server: added to ~/.claude.json"
            else
                rm -f "$temp_file"
                log_warn "CodeGraphContext MCP server: could not update ~/.claude.json"
            fi
        fi
    fi
}

# Old commented-out update_codegraphcontext (FalkorDB-specific, replaced above)
# _update_codegraphcontext_falkordb() {
#     log_section "Checking CodeGraphContext"
# 
#     if [[ "$DRY_RUN" == true ]]; then
#         log_info "[DRY-RUN] Would check/update CodeGraphContext (pip)"
#         return 0
#     fi
# 
#     if ! command -v python3 &>/dev/null; then
#         log_warn "python3 not found - skipping CodeGraphContext update"
#         return 0
#     fi
# 
#     if command -v cgc &>/dev/null; then
#         local current_version
#         current_version=$(cgc --version 2>&1 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' || echo "unknown")
#         log_ok "CodeGraphContext: installed (${current_version})"
# 
#         # Check for updates
#         log_info "Checking for CodeGraphContext updates..."
#         if pip3 install --upgrade codegraphcontext 2>/dev/null | grep -q "Successfully installed"; then
#             local new_version
#             new_version=$(cgc --version 2>&1 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' || echo "unknown")
#             log_ok "CodeGraphContext: updated to ${new_version}"
# 
#             # Re-check FalkorDB binary after update (may have been overwritten)
#             if [[ "$(uname)" == "Darwin" ]] && [[ "$(uname -m)" == "arm64" ]]; then
#                 local falkordb_so
#                 falkordb_so=$(python3 -c "
# import importlib.util
# spec = importlib.util.find_spec('redislite')
# if spec and spec.submodule_search_locations:
#     import os
#     print(os.path.join(spec.submodule_search_locations[0], 'bin', 'falkordb.so'))
# " 2>/dev/null)
# 
#                 if [[ -n "$falkordb_so" ]] && [[ -f "$falkordb_so" ]]; then
#                     local file_type
#                     file_type=$(file "$falkordb_so" 2>/dev/null)
#                     if echo "$file_type" | grep -q "ELF"; then
#                         log_info "Re-applying FalkorDB macOS ARM64 binary fix..."
#                         local download_url="https://github.com/FalkorDB/FalkorDB/releases/download/v4.16.2/falkordb-macos-arm64v8.so"
#                         if curl -L -o "${falkordb_so}" "$download_url" 2>/dev/null; then
#                             log_ok "FalkorDB macOS ARM64 binary restored"
#                         else
#                             log_warn "Could not download FalkorDB macOS binary"
#                         fi
#                     fi
#                 fi
#             fi
#         else
#             log_ok "CodeGraphContext: up to date"
#         fi
#     else
#         log_warn "CodeGraphContext: not installed, installing..."
#         if pip3 install codegraphcontext 2>/dev/null; then
#             log_ok "CodeGraphContext: installed"
#         else
#             log_warn "Could not install CodeGraphContext"
#             log_info "  To install manually: pip3 install codegraphcontext"
#         fi
#     fi
# 
#     # Verify MCP server is configured
#     local claude_json="$HOME/.claude.json"
#     if [[ -f "$claude_json" ]] && grep -q '"CodeGraphContext"' "$claude_json" 2>/dev/null; then
#         log_ok "CodeGraphContext MCP server: configured"
#     else
#         if command -v claude &>/dev/null && command -v cgc &>/dev/null; then
#             log_info "Adding CodeGraphContext MCP server to Claude Code..."
#             if claude mcp add -s user CodeGraphContext -- cgc mcp start 2>/dev/null; then
#                 log_ok "CodeGraphContext MCP server: configured"
#             else
#                 log_warn "Could not configure MCP server automatically"
#                 log_info "  Add manually: claude mcp add -s user CodeGraphContext -- cgc mcp start"
#             fi
#         else
#             log_warn "CodeGraphContext MCP server: not configured (claude or cgc not found)"
#         fi
#     fi
# }

# Update supergateway - shared MCP server instances
update_supergateway() {
    log_section "Updating Supergateway"

    local sg_src="${REPO_DIR}/supergateway"
    local sg_dst="${CLAUDE_DIR}/supergateway"

    if [[ ! -d "$sg_src" ]]; then
        log_warn "Supergateway source not found: ${sg_src}"
        return 0
    fi

    if [[ "$DRY_RUN" == true ]]; then
        log_info "[DRY-RUN] Would update supergateway config and scripts"
        log_info "[DRY-RUN] Would restart supergateway instances"
        return 0
    fi

    # Create runtime directories if needed
    mkdir -p "${sg_dst}/pids" "${sg_dst}/logs"

    # Check for config changes
    local config_changed=false
    if [[ ! -f "${sg_dst}/config.json" ]] || ! diff -q "${sg_src}/config.json" "${sg_dst}/config.json" &>/dev/null; then
        config_changed=true
    fi

    # Update config and scripts
    cp "${sg_src}/config.json" "${sg_dst}/config.json"
    for script in start.sh stop.sh status.sh; do
        cp "${sg_src}/${script}" "${sg_dst}/${script}"
        chmod +x "${sg_dst}/${script}"
    done

    # Update launchd plist if on macOS
    if [[ "$(uname)" == "Darwin" ]]; then
        local plist_name="com.gw.supergateway"
        local plist_dst="${HOME}/Library/LaunchAgents/${plist_name}.plist"
        local plist_src="${sg_src}/${plist_name}.plist"

        if [[ -f "$plist_src" ]]; then
            local current_path
            current_path=$(echo "$PATH")

            # Regenerate plist with current paths
            sed -e "s|__SUPERGATEWAY_DIR__|${sg_dst}|g" \
                -e "s|__LOG_DIR__|${sg_dst}/logs|g" \
                -e "s|__PATH__|${current_path}|g" \
                "$plist_src" > "$plist_dst"

            log_ok "Launchd plist updated"
        fi
    fi

    # Restart if config changed or servers aren't running
    if [[ "$config_changed" == true ]]; then
        log_info "Config changed, restarting supergateway instances..."
        "${sg_dst}/stop.sh" 2>/dev/null || true
        sleep 1
        "${sg_dst}/start.sh" || log_warn "Some instances failed to start"
    else
        # Just make sure they're running
        "${sg_dst}/start.sh" || log_warn "Some instances failed to start"
    fi

    # Ensure MCP configs point to SSE
    _update_mcp_for_supergateway_update

    log_ok "Supergateway updated"
}

# Install or update the report launchd jobs (daily-report, loop-metrics, weekly-report)
install_report_plists() {
    log_section "Installing Report Launchd Jobs"

    if [[ "$DRY_RUN" == true ]]; then
        log_info "[DRY-RUN] Would install com.base.{daily-report,loop-metrics,weekly-report} launchd jobs"
        return 0
    fi

    # Load env
    if [[ -f "$ENV_FILE" ]]; then
        source "$ENV_FILE"
    fi

    local project_root="${PROJECT_ROOT:-$(dirname "$REPO_DIR")}"

    # Ensure DAILY_REPORTS_* vars are in .env (add if missing)
    if [[ -f "$ENV_FILE" ]] && ! grep -q "DAILY_REPORTS_PATH" "$ENV_FILE" 2>/dev/null; then
        cat >> "$ENV_FILE" << EOF

# Daily Report Configuration (added by update.sh)
DAILY_REPORTS_PATH=${project_root}/daily-reports
DAILY_REPORTS_TIMEZONE=America/New_York
PIPELINE_AWS_PROFILE=${AWS_PROFILE_DEV}
EOF
        source "$ENV_FILE"
        log_info "Added DAILY_REPORTS_* configuration to .env"
    else
        log_ok "DAILY_REPORTS_* configuration already in .env"
    fi

    local daily_reports_path="${DAILY_REPORTS_PATH:-${project_root}/daily-reports}"
    local daily_reports_timezone="${DAILY_REPORTS_TIMEZONE:-America/New_York}"
    local tenant_namespace="${TENANT_NAMESPACE:-default}"

    # Create reports directories
    mkdir -p "${daily_reports_path}/insights"
    log_ok "Daily reports directory: ${daily_reports_path}"

    if [[ "$(uname)" != "Darwin" ]]; then
        log_warn "Non-macOS system: launchd plists not installed. Run skills manually:"
        log_info "  npx tsx ${CLAUDE_DIR}/skills/daily-report/generate.ts"
        log_info "  npx tsx ${CLAUDE_DIR}/skills/weekly-report/generate.ts"
        log_info "  npx tsx ${CLAUDE_DIR}/skills/report-insights/generate.ts"
        return 0
    fi

    mkdir -p "${HOME}/Library/LaunchAgents"

    local plists=("com.base.daily-report" "com.base.loop-metrics" "com.base.weekly-report")

    for plist_name in "${plists[@]}"; do
        local plist_src="${BASE_AGENTS_ROOT}/launchd/${plist_name}.plist"
        local plist_dst="${HOME}/Library/LaunchAgents/${plist_name}.plist"

        if [[ ! -f "$plist_src" ]]; then
            log_warn "Plist template not found: ${plist_src}"
            continue
        fi

        sed -e "s|__PROJECT_ROOT__|${project_root}|g" \
            -e "s|__CLAUDE_DIR__|${CLAUDE_DIR}|g" \
            -e "s|__DAILY_REPORTS_PATH__|${daily_reports_path}|g" \
            -e "s|__DAILY_REPORTS_TIMEZONE__|${daily_reports_timezone}|g" \
            -e "s|__TENANT_NAMESPACE__|${tenant_namespace}|g" \
            -e "s|__PATH__|${PATH}|g" \
            "$plist_src" > "$plist_dst"

        launchctl bootout "gui/$(id -u)/${plist_name}" 2>/dev/null || true
        launchctl bootstrap "gui/$(id -u)" "$plist_dst" 2>/dev/null || \
            launchctl load "$plist_dst" 2>/dev/null || \
            log_warn "Could not load ${plist_name} (may need manual load)"

        log_ok "Installed: ${plist_name}"
    done

    log_info "  Reports: ${daily_reports_path}"
    log_info "  To run now: npx tsx ${CLAUDE_DIR}/skills/daily-report/generate.ts"
    log_ok "Report launchd jobs installed"
}

# Update MCP configs to point to supergateway SSE endpoints
_update_mcp_for_supergateway_update() {
    local sg_config="${CLAUDE_DIR}/supergateway/config.json"
    local claude_json="${HOME}/.claude.json"

    if [[ ! -f "$sg_config" ]]; then
        return 0
    fi

    if ! command -v jq &>/dev/null; then
        return 0
    fi

    local server_names
    server_names=$(jq -r '.servers | keys[]' "$sg_config")

    for name in $server_names; do
        local port scope
        port=$(jq -r ".servers[\"${name}\"].port" "$sg_config")
        scope=$(jq -r ".servers[\"${name}\"].scope" "$sg_config")
        local sse_url="http://localhost:${port}/sse"

        if [[ "$scope" == "user" && -f "$claude_json" ]]; then
            # Check if already configured as SSE
            local current_type
            current_type=$(jq -r ".mcpServers[\"${name}\"].type // \"\"" "$claude_json" 2>/dev/null)

            if [[ "$current_type" != "sse" ]]; then
                local temp_file
                temp_file=$(mktemp)
                jq ".mcpServers[\"${name}\"] = {\"type\": \"sse\", \"url\": \"${sse_url}\"}" \
                    "$claude_json" > "$temp_file"
                if jq empty "$temp_file" 2>/dev/null; then
                    mv "$temp_file" "$claude_json"
                    log_ok "${name}: updated to SSE (${sse_url})"
                else
                    rm -f "$temp_file"
                fi
            else
                log_ok "${name}: already configured as SSE"
            fi
        fi
    done

    # Configure per-session stdio MCP servers (not shared via supergateway)
    # Prefer stdio over supergateway SSE: stdio gives each session its own
    # process, avoids the supergateway SSE reconnection crash bug, and
    # eliminates shared-state conflicts between concurrent sessions.
    if [[ -f "$claude_json" ]]; then
        local current_cd_exists
        current_cd_exists=$(jq -r '.mcpServers["chrome-devtools"] // empty' "$claude_json" 2>/dev/null)

        if [[ -n "$current_cd_exists" ]]; then
            local temp_file
            temp_file=$(mktemp)
            jq 'del(.mcpServers["chrome-devtools"])' "$claude_json" > "$temp_file"
            if jq empty "$temp_file" 2>/dev/null; then
                mv "$temp_file" "$claude_json"
                log_ok "chrome-devtools: removed (replaced by Playwright)"
            else
                rm -f "$temp_file"
            fi
        fi
    fi
}

# Check MCP servers by reading settings file directly (avoids interactive CLI)
update_mcp_servers() {
    log_section "Checking MCP Servers"

    local settings_file="${CLAUDE_DIR}/settings.json"
    local missing_servers=()

    if [[ "$DRY_RUN" == true ]]; then
        log_info "[DRY-RUN] Would verify MCP servers in settings"
        log_info "  - agentdb"
    # REMOVED: log_info "  - CodeGraphContext (checked in ~/.claude.json)"
        log_info "  (Project MCP servers preserved: jira, bitbucket)"
        return 0
    fi

    # Check settings.json for MCP server configs (avoids interactive claude mcp commands)
    if [[ -f "$settings_file" ]]; then
        if grep -q '"agentdb"' "$settings_file" 2>/dev/null; then
            log_ok "agentdb: configured"
        else
            log_warn "agentdb: not found"
            missing_servers+=("agentdb")
        fi

        if grep -q '"test-data"' "$settings_file" 2>/dev/null; then
            log_ok "test-data: configured"
        else
            log_warn "test-data: not configured (run install.sh to set up)"
        fi

        # Check project MCP servers
        if grep -q '"jira"' "$settings_file" 2>/dev/null; then
            log_ok "jira: configured"
        fi
        if grep -q '"bitbucket"' "$settings_file" 2>/dev/null; then
            log_ok "bitbucket: configured"
        fi
    else
        log_warn "Settings file not found"
        missing_servers+=("agentdb")
    fi

    # CodeGraphContext removed — was causing performance issues

    # Provide manual instructions for missing servers
    if [[ ${#missing_servers[@]} -gt 0 ]]; then
        echo ""
        log_info "To add missing MCP servers, run:"
        for server in "${missing_servers[@]}"; do
            case "$server" in
                agentdb)
                    echo "  ./scripts/install.sh --configure-agentdb"
                    ;;
                codegraphcontext)
    # REMOVED: echo "  claude mcp add -s user CodeGraphContext -- cgc mcp start"
                    ;;
            esac
        done
    fi
}

# Update tool permissions in settings.json
update_tool_permissions() {
    log_section "Updating Tool Permissions"

    local permissions_script="${REPO_DIR}/scripts/update-permissions.sh"

    if [[ "$DRY_RUN" == true ]]; then
        log_info "[DRY-RUN] Would run: ${permissions_script} --dry-run"
        if [[ -x "$permissions_script" ]]; then
            "$permissions_script" --claude-dir "$CLAUDE_DIR" --dry-run
        else
            log_warn "Permissions script not found or not executable: ${permissions_script}"
        fi
        return 0
    fi

    if [[ -x "$permissions_script" ]]; then
        "$permissions_script" --claude-dir "$CLAUDE_DIR"
    else
        log_warn "Permissions script not found or not executable: ${permissions_script}"
        log_info "Skipping automatic permission updates"
    fi
}

# Update parent CLAUDE.md in project root
update_parent_claude_md() {
    log_section "Updating Parent CLAUDE.md"

    # Load configuration
    if [[ -f "$ENV_FILE" ]]; then
        source "$ENV_FILE"
    fi

    # Resolve project root
    local project_root="${PROJECT_ROOT:-$(dirname "$REPO_DIR")}"
    if [[ "$project_root" == ".." || "$project_root" == "../"* ]]; then
        project_root="$(cd "$REPO_DIR" && cd "$project_root" && pwd)"
    fi

    local template="${REPO_DIR}/templates/parent-CLAUDE.md"
    local target="${project_root}/CLAUDE.md"

    if [[ ! -f "$template" ]]; then
        log_warn "Parent CLAUDE.md template not found: ${template}"
        return 1
    fi

    if [[ "$DRY_RUN" == true ]]; then
        if [[ -f "$target" ]]; then
            if grep -q "Managed by agents" "$target" 2>/dev/null; then
                if ! diff -q "$template" "$target" &>/dev/null; then
                    log_info "[DRY-RUN] Would update: ${target}"
                else
                    log_info "[DRY-RUN] Parent CLAUDE.md already up to date"
                fi
            else
                log_info "[DRY-RUN] Parent CLAUDE.md exists but not managed by agents"
            fi
        else
            log_info "[DRY-RUN] Would create: ${target}"
        fi
        return 0
    fi

    if [[ -f "$target" ]]; then
        # Check if it's managed by agents (has our footer)
        if grep -q "Managed by agents" "$target" 2>/dev/null; then
            if ! diff -q "$template" "$target" &>/dev/null; then
                cp "$target" "${target}.backup.${TIMESTAMP}"
                cp "$template" "$target"
                log_ok "Parent CLAUDE.md updated"
            else
                log_ok "Parent CLAUDE.md already up to date"
            fi
        else
            log_warn "Parent CLAUDE.md exists but is not managed by agents"
            log_info "Run install.sh to convert to managed template"
        fi
    else
        cp "$template" "$target"
        log_ok "Parent CLAUDE.md created at ${target}"
    fi
}

# Show version info
show_version_info() {
    log_section "Version Information"

    cd "$REPO_DIR"

    local commit_hash=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
    local commit_date=$(git log -1 --format=%ci 2>/dev/null || echo "unknown")
    local branch=$(git branch --show-current 2>/dev/null || echo "unknown")

    echo "  Repository: agents"
    echo "  Branch: ${branch}"
    echo "  Commit: ${commit_hash}"
    echo "  Date: ${commit_date}"
}

# Clean up old backups (keep last 10)
cleanup_old_backups() {
    # Source the shared cleanup function
    source "${REPO_DIR}/scripts/cleanup-backups.sh"
    cleanup_old_backups "${BACKUP_DIR}" 10
}

# Update model routing config (deep merge base + tenant)
update_model_routing() {
    log_section "Updating Model Routing Config"

    local base_config="${BASE_AGENTS_ROOT}/config/model-routing.json"
    local tenant_config="${REPO_DIR}/config/model-routing.json"
    local output_dir="${CLAUDE_DIR}/config"
    local output="${output_dir}/model-routing.json"

    mkdir -p "$output_dir"

    if [[ ! -f "$base_config" ]]; then
        log_warn "Base model routing config not found: ${base_config}"
        return 0
    fi

    if ! command -v jq &>/dev/null; then
        log_warn "jq not installed - cannot merge model routing config"
        return 1
    fi

    if [[ "$DRY_RUN" == true ]]; then
        if [[ -f "$tenant_config" ]]; then
            log_info "[DRY-RUN] Would deep merge model routing: base + tenant -> ${output}"
        else
            log_info "[DRY-RUN] Would install model routing (base only) -> ${output}"
        fi
        return 0
    fi

    if [[ -f "$tenant_config" ]]; then
        # Deep merge: tenant overrides base for models, defaults, commands
        jq -s '
            .[0] as $base | .[1] as $tenant |
            {
                version: ($tenant.version // $base.version),
                providers: ($base.providers // {} | . * ($tenant.providers // {})),
                models: ($base.models * ($tenant.models // {})),
                defaults: ($base.defaults * ($tenant.defaults // {})),
                commands: ($base.commands * ($tenant.commands // {}))
            }
        ' "$base_config" "$tenant_config" > "$output"
        log_ok "Model routing config merged (base + tenant) -> ${output}"
    else
        cp "$base_config" "$output"
        log_ok "Model routing config installed (base only) -> ${output}"
    fi
}

# Update dispatch routing config (install base default, then overlay tenant override)
update_dispatch_routing() {
    log_section "Updating Dispatch Routing Config"

    local base_default="${BASE_AGENTS_ROOT}/config/dispatch-routing.default.json"
    local tenant_config="${REPO_DIR}/config/dispatch-routing.json"
    local config_dst="${CLAUDE_DIR}/config"

    mkdir -p "$config_dst"

    if [[ ! -f "$base_default" ]]; then
        log_warn "Base dispatch routing default not found: ${base_default}"
        return 0
    fi

    if [[ "$DRY_RUN" == true ]]; then
        log_info "[DRY-RUN] Would install dispatch routing default -> ${config_dst}/dispatch-routing.default.json"
        if [[ -f "$tenant_config" ]]; then
            log_info "[DRY-RUN] Would install tenant dispatch routing override -> ${config_dst}/dispatch-routing.json"
        fi
        return 0
    fi

    cp "$base_default" "${config_dst}/dispatch-routing.default.json"
    log_ok "Dispatch routing default installed -> ${config_dst}/dispatch-routing.default.json"

    if [[ -f "$tenant_config" ]]; then
        cp "$tenant_config" "${config_dst}/dispatch-routing.json"
        log_ok "Dispatch routing tenant override installed -> ${config_dst}/dispatch-routing.json"
    fi
}

# Update config files (api-defaults, memory-policy, model-pricing, etc.)
update_config_files() {
    log_section "Updating Config Files"

    local base_config_src="${BASE_AGENTS_ROOT}/config"
    local config_dst="${CLAUDE_DIR}/config"

    mkdir -p "$config_dst"

    if [[ ! -d "$base_config_src" ]]; then
        log_warn "Base config directory not found: ${base_config_src}"
        return 0
    fi

    local config_count=0

    for config_file in "${base_config_src}"/*.json; do
        if [[ -f "$config_file" ]]; then
            local filename=$(basename "$config_file")
            # Skip model-routing.json (handled by update_model_routing with merge)
            if [[ "$filename" == "model-routing.json" ]]; then
                continue
            fi
            # Skip brew-packages.json (handled by update_brew_packages)
            if [[ "$filename" == "brew-packages.json" ]]; then
                continue
            fi
            # Skip dispatch-routing.default.json (handled by update_dispatch_routing)
            if [[ "$filename" == "dispatch-routing.default.json" ]]; then
                continue
            fi

            if [[ "$DRY_RUN" == true ]]; then
                log_info "[DRY-RUN] Would install config: ${filename}"
            else
                cp "$config_file" "${config_dst}/${filename}"
                log_ok "Installed config: ${filename}"
            fi
            config_count=$((config_count + 1))
        fi
    done

    log_ok "Config files updated: ${config_count} files to ${config_dst}"
}

# Sync repos only mode
sync_repos_only_main() {
    echo ""
    echo -e "${CYAN}╔═══════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║   Project Agents - Sync Project Repositories   ║${NC}"
    echo -e "${CYAN}╚═══════════════════════════════════════════╝${NC}"
    echo ""

    if [[ "$DRY_RUN" == true ]]; then
        echo -e "${YELLOW}Running in DRY-RUN mode - no changes will be made${NC}"
        echo ""
    fi

    sync_project_repos

    log_section "Sync Complete!"
    echo ""
}

# Main update flow
main() {
    echo ""
    echo -e "${CYAN}╔═══════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║   Project Agents - Update Script               ║${NC}"
    echo -e "${CYAN}╚═══════════════════════════════════════════╝${NC}"
    echo ""

    if [[ "$DRY_RUN" == true ]]; then
        echo -e "${YELLOW}Running in DRY-RUN mode - no changes will be made${NC}"
        echo ""
    fi

    check_git_repo

    if [[ "$DRY_RUN" != true ]]; then
        create_backup_dir
    fi

    check_uncommitted_changes
    backup_existing_config
    pull_latest
    update_base_agents_submodule
    update_brew_packages
    setup_ollama_models
    sync_project_repos
    validate_gw_docs
    # update_mcp_repos  # DEPRECATED: Skills now call REST APIs directly
    update_commands
    update_hooks
    update_statusline
    setup_project_hooks
    update_workflows
    update_skills
    generate_skills_cache
    symlink_skills_to_project
    update_project_claude_dir
    update_hook_configs
    update_model_routing
    update_dispatch_routing
    update_config_files
    update_plugins
    update_testing_tools
    install_playwright
    install_e2e_config
    update_codegraphcontext
    update_supergateway
    install_report_plists
    update_tokf
    update_mcp_servers
    update_tool_permissions
    update_parent_claude_md

    if [[ "$DRY_RUN" != true ]]; then
        cleanup_old_backups
    fi

    show_version_info

    # Index repositories in CodeGraphContext (if available)
    if command -v cgc &>/dev/null; then
      echo "Indexing repositories in CodeGraphContext..."
      if [ -f "$HOME/.claude/skills/index-repos/index.ts" ]; then
        npx tsx "$HOME/.claude/skills/index-repos/index.ts" 2>/dev/null || echo "  CGC indexing failed (non-blocking)"
      else
        echo "  index-repos skill not found, skipping CGC indexing"
      fi
    else
      echo "CGC not installed, skipping repo indexing"
    fi

    # --- Post-Update Verification (rx) ---
    if [[ "$RUN_RX" != true ]]; then
      log_section "Post-Update Verification"
      log_info "Skipped. Use --rx to run, or ./scripts/rx.sh to verify manually."
    else
      log_section "Post-Update Verification"
      log_info "Running rx to verify update..."

      RX_SCRIPT="${CLAUDE_DIR}/skills/rx/rx.ts"
      if [[ -f "$RX_SCRIPT" ]]; then
        RX_OUTPUT=$(npx tsx "$RX_SCRIPT" --json 2>/dev/null || true)

        if [[ -n "$RX_OUTPUT" ]]; then
          TOTAL=$(echo "$RX_OUTPUT" | jq -r '.summary.total // 0')
          PASS=$(echo "$RX_OUTPUT" | jq -r '.summary.pass // 0')
          FIXED=$(echo "$RX_OUTPUT" | jq -r '.summary.fixed // 0')
          FAIL=$(echo "$RX_OUTPUT" | jq -r '.summary.fail // 0')

          if [[ "$FAIL" -eq 0 ]]; then
            log_ok "All ${TOTAL} checks passed (${PASS} pass, ${FIXED} fixed)"
          else
            log_warn "${FAIL} checks failed out of ${TOTAL}. Run ./scripts/rx.sh for details."
          fi
        else
          log_warn "rx verification returned empty output. Run ./scripts/rx.sh manually."
        fi
      else
        log_info "rx skill not yet installed. Run ./scripts/rx.sh after installation to verify."
      fi
    fi

    log_section "Update Complete!"

    if [[ "$DRY_RUN" == true ]]; then
        echo ""
        log_info "This was a dry run. Run without --dry-run to apply changes."
    else
        echo ""
        log_ok "Project Agents environment has been updated"
        echo ""
        log_info "Preserved:"
        echo "  - .env credentials"
        echo "  - MCP server configurations"
        echo "  - Backups at: ${BACKUP_DIR}/${TIMESTAMP}"
        echo ""
        log_info "To restore previous configuration:"
        echo "  cp ${BACKUP_DIR}/${TIMESTAMP}/* ${CLAUDE_DIR}/"
    fi
    echo ""
}

# Run main or sync-repos mode
if [[ "$SYNC_REPOS_ONLY" == true ]]; then
    sync_repos_only_main
else
    main
fi
