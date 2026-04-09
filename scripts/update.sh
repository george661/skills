#!/bin/bash
#
# Platform Agents - Update Script
# Updates local installation while preserving existing configuration
#
# Usage:
#   ./scripts/update.sh              # Full update (pull + install)
#   ./scripts/update.sh --local      # Update without git pull
#   ./scripts/update.sh --dry-run    # Show what would be updated
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
BASE_CONFIG_DIR="$REPO_DIR"
TENANT_CONFIG_DIR=""

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

# Migrate PROJECT_ROOT to PROJECT_ROOT in .env files
# This handles backwards compatibility with older configurations
migrate_project_root_env() {
    local env_file="$1"

    if [[ ! -f "$env_file" ]]; then
        return 0
    fi

    # Check if PROJECT_ROOT exists but PROJECT_ROOT doesn't
    if grep -q "^PROJECT_ROOT=" "$env_file" && ! grep -q "^PROJECT_ROOT=" "$env_file"; then
        log_info "Migrating PROJECT_ROOT to PROJECT_ROOT in $(basename "$env_file")..."

        # Get the value of PROJECT_ROOT
        local old_value
        old_value=$(grep "^PROJECT_ROOT=" "$env_file" | cut -d'=' -f2-)

        # Replace PROJECT_ROOT with PROJECT_ROOT
        if [[ "$(uname)" == "Darwin" ]]; then
            sed -i '' 's/^PROJECT_ROOT=/PROJECT_ROOT=/' "$env_file"
        else
            sed -i 's/^PROJECT_ROOT=/PROJECT_ROOT=/' "$env_file"
        fi

        log_ok "Migrated PROJECT_ROOT to PROJECT_ROOT (value: ${old_value})"
    fi
}

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

            log_info "Checking for ${name} updates..."
            brew upgrade "$name" 2>/dev/null || log_ok "${name}: up to date"
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

        ((i++))
    done

    log_ok "Homebrew package update complete"
}

# Merge required .env keys without data loss
# Usage: merge_env_keys <env_file> <key=value> [key=value ...]
# Only adds keys that don't exist; preserves existing values
merge_env_keys() {
    local env_file="$1"
    shift

    if [[ ! -f "$env_file" ]]; then
        log_warn "No .env file found at ${env_file} - skipping merge"
        return 0
    fi

    local added_count=0
    local section_header=""

    for entry in "$@"; do
        local key="${entry%%=*}"
        local value="${entry#*=}"
        local comment="${entry##*#}"

        # Check if key already exists
        if ! grep -q "^${key}=" "$env_file"; then
            # Add key with value
            if [[ "$DRY_RUN" == true ]]; then
                log_info "[DRY-RUN] Would add: ${key}=${value}"
            else
                # Add a newline before if file doesn't end with one
                if [[ -s "$env_file" ]] && [[ $(tail -c1 "$env_file" | wc -l) -eq 0 ]]; then
                    echo "" >> "$env_file"
                fi
                echo "${key}=${value}" >> "$env_file"
                log_ok "Added missing key: ${key}"
            fi
            ((added_count++)) || true
        fi
    done

    if [[ $added_count -eq 0 ]]; then
        log_info "All required .env keys already present"
    else
        log_ok "Added ${added_count} missing key(s) to .env"
    fi
}

# Update .env with required AgentDB configuration
update_env_agentdb() {
    local env_file="$1"
    local tenant="${2:-hooks}"

    log_section "Checking AgentDB Configuration"

    if [[ ! -f "$env_file" ]]; then
        log_warn "No .env file at ${env_file}"
        return 0
    fi

    # Get API key from settings.json or AWS
    local api_key=""
    local settings_file="${CLAUDE_DIR}/settings.json"

    if [[ -f "$settings_file" ]]; then
        api_key=$(jq -r '.credentials.agentdb.apiKey // empty' "$settings_file" 2>/dev/null)
    fi

    if [[ -z "$api_key" ]]; then
        # Try AWS Secrets Manager
        api_key=$(AWS_PROFILE=${AWS_PROFILE:-dev-profile} aws secretsmanager get-secret-value \
            --secret-id agentdb-dev-api-key \
            --query SecretString --output text 2>/dev/null | jq -r '.apiKey // empty' 2>/dev/null || true)
    fi

    if [[ -z "$api_key" ]]; then
        log_warn "Could not retrieve AgentDB API key - skipping"
        return 0
    fi

    # TODO: Update AGENTDB_URL to your AgentDB DNS when record is created
    merge_env_keys "$env_file" \
        "AGENTDB_API_KEY=${api_key}" \
        "AGENTDB_URL=YOUR_AGENTDB_URL" \
        "TENANT_NAMESPACE=${tenant}"

    # Seed anti-patterns after AgentDB env setup
    if [[ -f "${REPO_DIR}/scripts/seed-anti-patterns.ts" ]]; then
        log_info "Seeding anti-patterns into AgentDB..."
        npx tsx "${REPO_DIR}/scripts/seed-anti-patterns.ts" 2>/dev/null && \
            log_ok "Anti-patterns seeded" || \
            log_warn "Could not seed anti-patterns (AgentDB may not be reachable)"
    fi
}

# Options
DRY_RUN=false
LOCAL_ONLY=false
FORCE=false
SYNC_REPOS_ONLY=false

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
        --help|-h)
            cat <<EOF
Project Agents - Update Script

Usage:
  ${0##*/}              Full update (pull latest + reinstall)
  ${0##*/} --local      Update without git pull (use current files)
  ${0##*/} --dry-run    Show what would be updated without making changes
  ${0##*/} --force      Skip confirmation prompts
  ${0##*/} --sync-repos Sync project repositories only (git pull all repos)

Options:
  --dry-run     Preview changes without applying them
  --local       Skip git pull, update from current local files
  --force       Don't prompt for confirmation
  --sync-repos  Only sync project repositories (skip other updates)
  --help        Show this help message

What gets updated:
  - Project repos (frontend-app, lambda-functions, etc.) - git pull on each
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

# Update MCP server repositories
update_mcp_repos() {
    log_section "Updating MCP Server Repositories"

    # Load paths from .env or use defaults
    if [[ -f "$ENV_FILE" ]]; then
        source "$ENV_FILE"
    fi

    local jira_path="${JIRA_MCP_PATH:-${REPO_DIR}/mcp-servers/jira-mcp}"
    local bb_path="${BITBUCKET_MCP_PATH:-${REPO_DIR}/mcp-servers/bitbucket-mcp}"

    for mcp_info in "jira-mcp:${jira_path}" "bitbucket-mcp:${bb_path}"; do
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

# Update commands
update_commands() {
    log_section "Updating Workflow Commands"

    local commands_src="${REPO_DIR}/.claude/commands"
    local commands_dst="${CLAUDE_DIR}/commands"

    if [[ ! -d "$commands_src" ]]; then
        log_warn "Commands source directory not found: ${commands_src}"
        return 1
    fi

    mkdir -p "$commands_dst"

    local updated=0
    local added=0
    local groups_updated=0

    # Update top-level command files
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

    # Update command group subdirectories (e.g., loop/, metrics/)
    for group_dir in "${commands_src}"/*/; do
        if [[ -d "$group_dir" ]]; then
            local group_name=$(basename "$group_dir")
            local dst_group="${commands_dst}/${group_name}"

            if [[ "$DRY_RUN" == true ]]; then
                if [[ -d "$dst_group" ]]; then
                    log_info "[DRY-RUN] Would update command group: ${group_name}/"
                else
                    log_info "[DRY-RUN] Would add command group: ${group_name}/"
                fi
                ((groups_updated++)) || true
            else
                mkdir -p "$dst_group"
                local group_files_updated=0

                for cmd_file in "${group_dir}"*.md; do
                    if [[ -f "$cmd_file" ]]; then
                        local filename=$(basename "$cmd_file")
                        local dst_file="${dst_group}/${filename}"

                        if [[ -f "$dst_file" ]]; then
                            if ! diff -q "$cmd_file" "$dst_file" &>/dev/null; then
                                cp "$cmd_file" "$dst_file"
                                ((group_files_updated++)) || true
                            fi
                        else
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

    if [[ $updated -eq 0 && $added -eq 0 && $groups_updated -eq 0 ]]; then
        log_ok "All commands up to date"
    else
        log_ok "Commands: ${updated} updated, ${added} added, ${groups_updated} groups synced"
    fi
}

# Update hooks
update_hooks() {
    log_section "Updating Hooks"

    local hooks_src="${REPO_DIR}/.claude/hooks"
    local hooks_dst="${CLAUDE_DIR}/hooks"

    if [[ ! -d "$hooks_src" ]]; then
        log_warn "Hooks source directory not found: ${hooks_src}"
        return 1
    fi

    mkdir -p "$hooks_dst"

    local updated=0
    local added=0

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

    if [[ $updated -eq 0 && $added -eq 0 ]]; then
        log_ok "All hooks up to date"
    else
        log_ok "Hooks: ${updated} updated, ${added} added"
    fi
}

# Copy hooks to each project's .claude/hooks directory
# This allows commands using relative paths like "python3 .claude/hooks/checkpoint.py" to work
setup_project_hooks() {
    log_section "Copying Hooks to Project Directories"

    # Load configuration
    if [[ -f "$ENV_FILE" ]]; then
        source "$ENV_FILE"
    fi

    # Check if configuration exists
    if [[ -z "${PROJECT_REPOS:-}" ]]; then
        log_warn "Project repositories not configured, skipping project hooks"
        return 0
    fi

    # Resolve project root
    local project_root="${PROJECT_ROOT:-$(dirname "$REPO_DIR")}"
    if [[ "$project_root" == ".." || "$project_root" == "../"* ]]; then
        project_root="$(cd "$REPO_DIR" && cd "$project_root" && pwd)"
    fi

    local hooks_src="${REPO_DIR}/.claude/hooks"
    local copied=0
    local updated=0

    if [[ ! -d "$hooks_src" ]]; then
        log_warn "Hooks source directory not found: ${hooks_src}"
        return 1
    fi

    # Process core repositories
    IFS=',' read -ra repos <<< "$PROJECT_REPOS"
    for repo in "${repos[@]}"; do
        repo=$(echo "$repo" | xargs)  # Trim whitespace
        local repo_path="${project_root}/${repo}"
        local claude_dir="${repo_path}/.claude"
        local hooks_dst="${claude_dir}/hooks"

        if [[ ! -d "$repo_path" ]]; then
            continue  # Skip repos that don't exist
        fi

        # Create .claude/hooks directory if it doesn't exist
        if [[ "$DRY_RUN" == true ]]; then
            if [[ ! -d "$hooks_dst" ]]; then
                log_info "[DRY-RUN] Would create ${repo}/.claude/hooks"
            fi
        else
            # Remove symlink if it exists (from previous setup)
            if [[ -L "$hooks_dst" ]]; then
                rm "$hooks_dst"
                log_info "${repo}: converted symlink to directory"
            fi
            mkdir -p "$hooks_dst"
        fi

        # Copy hook files
        local repo_updated=0
        local repo_added=0
        for hook_file in "${hooks_src}"/*; do
            if [[ -f "$hook_file" ]]; then
                local filename=$(basename "$hook_file")
                local dst_file="${hooks_dst}/${filename}"

                if [[ "$DRY_RUN" == true ]]; then
                    if [[ -f "$dst_file" ]]; then
                        if ! diff -q "$hook_file" "$dst_file" &>/dev/null; then
                            log_info "[DRY-RUN] Would update: ${repo}/${filename}"
                            ((repo_updated++)) || true
                        fi
                    else
                        log_info "[DRY-RUN] Would add: ${repo}/${filename}"
                        ((repo_added++)) || true
                    fi
                else
                    if [[ -f "$dst_file" ]]; then
                        if ! diff -q "$hook_file" "$dst_file" &>/dev/null; then
                            cp "$hook_file" "$dst_file"
                            chmod +x "$dst_file" 2>/dev/null || true
                            ((repo_updated++)) || true
                        fi
                    else
                        cp "$hook_file" "$dst_file"
                        chmod +x "$dst_file" 2>/dev/null || true
                        ((repo_added++)) || true
                    fi
                fi
            fi
        done

        if [[ $repo_updated -gt 0 || $repo_added -gt 0 ]]; then
            log_ok "${repo}: ${repo_updated} updated, ${repo_added} added"
            ((copied++)) || true
        fi
    done

    # Process optional repositories if configured
    if [[ -n "${PROJECT_REPOS_OPTIONAL:-}" ]]; then
        IFS=',' read -ra optional_repos <<< "$PROJECT_REPOS_OPTIONAL"
        for repo in "${optional_repos[@]}"; do
            repo=$(echo "$repo" | xargs)
            local repo_path="${project_root}/${repo}"
            local claude_dir="${repo_path}/.claude"
            local hooks_dst="${claude_dir}/hooks"

            if [[ ! -d "$repo_path" ]]; then
                continue
            fi

            if [[ "$DRY_RUN" != true ]]; then
                if [[ -L "$hooks_dst" ]]; then
                    rm "$hooks_dst"
                fi
                mkdir -p "$hooks_dst"
            fi

            local repo_updated=0
            local repo_added=0
            for hook_file in "${hooks_src}"/*; do
                if [[ -f "$hook_file" ]]; then
                    local filename=$(basename "$hook_file")
                    local dst_file="${hooks_dst}/${filename}"

                    if [[ "$DRY_RUN" != true ]]; then
                        if [[ -f "$dst_file" ]]; then
                            if ! diff -q "$hook_file" "$dst_file" &>/dev/null; then
                                cp "$hook_file" "$dst_file"
                                chmod +x "$dst_file" 2>/dev/null || true
                                ((repo_updated++)) || true
                            fi
                        else
                            cp "$hook_file" "$dst_file"
                            chmod +x "$dst_file" 2>/dev/null || true
                            ((repo_added++)) || true
                        fi
                    fi
                fi
            done

            if [[ $repo_updated -gt 0 || $repo_added -gt 0 ]]; then
                log_ok "${repo}: ${repo_updated} updated, ${repo_added} added"
                ((copied++)) || true
            fi
        done
    fi

    if [[ $copied -eq 0 ]]; then
        log_ok "All project hooks up to date"
    else
        log_ok "Project hooks updated in ${copied} repositories"
    fi
}

# Update Claude Flow workflows
update_workflows() {
    log_section "Updating Claude Flow Workflows"

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

# Update agent definitions
update_agents() {
    log_section "Updating Agent Definitions"

    local agents_src="${REPO_DIR}/.claude/agents"
    local agents_dst="${CLAUDE_DIR}/agents"

    if [[ ! -d "$agents_src" ]]; then
        log_warn "Agents source directory not found: ${agents_src}"
        return 0
    fi

    mkdir -p "$agents_dst"

    local updated=0
    local added=0

    # Update agent YAML files
    for agent_file in "${agents_src}"/*.yaml "${agents_src}"/*.yml; do
        if [[ -f "$agent_file" ]]; then
            local filename=$(basename "$agent_file")
            local dst_file="${agents_dst}/${filename}"

            if [[ "$DRY_RUN" == true ]]; then
                if [[ -f "$dst_file" ]]; then
                    if ! diff -q "$agent_file" "$dst_file" &>/dev/null; then
                        log_info "[DRY-RUN] Would update: ${filename}"
                        ((updated++)) || true
                    fi
                else
                    log_info "[DRY-RUN] Would add: ${filename}"
                    ((added++)) || true
                fi
            else
                if [[ -f "$dst_file" ]]; then
                    if ! diff -q "$agent_file" "$dst_file" &>/dev/null; then
                        cp "$agent_file" "$dst_file"
                        log_ok "Updated: ${filename%.yaml}"
                        ((updated++)) || true
                    fi
                else
                    cp "$agent_file" "$dst_file"
                    log_ok "Added: ${filename%.yaml}"
                    ((added++)) || true
                fi
            fi
        fi
    done

    # Update README if exists
    local readme_src="${agents_src}/README.md"
    local readme_dst="${agents_dst}/README.md"
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
        log_ok "All agent definitions up to date"
    else
        log_ok "Agents: ${updated} updated, ${added} added"
    fi
}

# Update team definitions
update_teams() {
    log_section "Updating Team Definitions"

    local teams_src="${REPO_DIR}/.claude/teams"
    local teams_dst="${CLAUDE_DIR}/teams"

    if [[ ! -d "$teams_src" ]]; then
        log_warn "Teams source directory not found: ${teams_src}"
        return 0
    fi

    mkdir -p "$teams_dst"

    local updated=0
    local added=0

    # Update team YAML files
    for team_file in "${teams_src}"/*.yaml "${teams_src}"/*.yml; do
        if [[ -f "$team_file" ]]; then
            local filename=$(basename "$team_file")
            local dst_file="${teams_dst}/${filename}"

            if [[ "$DRY_RUN" == true ]]; then
                if [[ -f "$dst_file" ]]; then
                    if ! diff -q "$team_file" "$dst_file" &>/dev/null; then
                        log_info "[DRY-RUN] Would update: ${filename}"
                        ((updated++)) || true
                    fi
                else
                    log_info "[DRY-RUN] Would add: ${filename}"
                    ((added++)) || true
                fi
            else
                if [[ -f "$dst_file" ]]; then
                    if ! diff -q "$team_file" "$dst_file" &>/dev/null; then
                        cp "$team_file" "$dst_file"
                        log_ok "Updated: ${filename%.yaml}"
                        ((updated++)) || true
                    fi
                else
                    cp "$team_file" "$dst_file"
                    log_ok "Added: ${filename%.yaml}"
                    ((added++)) || true
                fi
            fi
        fi
    done

    # Update README if exists
    local readme_src="${teams_src}/README.md"
    local readme_dst="${teams_dst}/README.md"
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
        log_ok "All team definitions up to date"
    else
        log_ok "Teams: ${updated} updated, ${added} added"
    fi
}

# Update skills
update_skills() {
    log_section "Updating Skills"

    local skills_src="${REPO_DIR}/.claude/skills"
    local skills_dst="${CLAUDE_DIR}/skills"

    if [[ ! -d "$skills_src" ]]; then
        log_warn "Skills source directory not found: ${skills_src}"
        return 0
    fi

    mkdir -p "$skills_dst"

    local updated=0
    local added=0
    local subdirs_updated=0

    # Update top-level skill files
    for skill_file in "${skills_src}"/*.md; do
        if [[ -f "$skill_file" ]]; then
            local filename=$(basename "$skill_file")
            local dst_file="${skills_dst}/${filename}"

            if [[ "$DRY_RUN" == true ]]; then
                if [[ -f "$dst_file" ]]; then
                    if ! diff -q "$skill_file" "$dst_file" &>/dev/null; then
                        log_info "[DRY-RUN] Would update skill: ${filename}"
                        ((updated++)) || true
                    fi
                else
                    log_info "[DRY-RUN] Would add skill: ${filename}"
                    ((added++)) || true
                fi
            else
                if [[ -f "$dst_file" ]]; then
                    if ! diff -q "$skill_file" "$dst_file" &>/dev/null; then
                        cp "$skill_file" "$dst_file"
                        log_ok "Updated skill: ${filename}"
                        ((updated++)) || true
                    fi
                else
                    cp "$skill_file" "$dst_file"
                    log_ok "Added skill: ${filename}"
                    ((added++)) || true
                fi
            fi
        fi
    done

    # Update skill subdirectories (e.g., examples/)
    for subdir in "${skills_src}"/*/; do
        if [[ -d "$subdir" ]]; then
            local dirname=$(basename "$subdir")
            local dst_subdir="${skills_dst}/${dirname}"

            if [[ "$DRY_RUN" == true ]]; then
                log_info "[DRY-RUN] Would sync skill directory: ${dirname}/"
                ((subdirs_updated++)) || true
            else
                # Sync the subdirectory
                if [[ -d "$dst_subdir" ]]; then
                    # Update existing files
                    local subdir_files_updated=0
                    for file in "${subdir}"*; do
                        if [[ -f "$file" ]]; then
                            local fname=$(basename "$file")
                            local dst_file="${dst_subdir}/${fname}"
                            if [[ ! -f "$dst_file" ]] || ! diff -q "$file" "$dst_file" &>/dev/null; then
                                cp "$file" "$dst_file"
                                ((subdir_files_updated++)) || true
                            fi
                        fi
                    done
                    if [[ $subdir_files_updated -gt 0 ]]; then
                        log_ok "Updated skill directory: ${dirname}/ (${subdir_files_updated} files)"
                        ((subdirs_updated++)) || true
                    fi
                else
                    cp -r "$subdir" "$skills_dst/"
                    log_ok "Added skill directory: ${dirname}/"
                    ((subdirs_updated++)) || true
                fi
            fi
        fi
    done

    if [[ $updated -eq 0 && $added -eq 0 && $subdirs_updated -eq 0 ]]; then
        log_ok "All skills up to date"
    else
        log_ok "Skills: ${updated} updated, ${added} added, ${subdirs_updated} directories synced"
    fi
}

# Update utility scripts (cost tracking, metrics, etc.)
update_scripts() {
    log_section "Updating Utility Scripts"

    local scripts_src="${REPO_DIR}/scripts"
    local scripts_dst="${HOME}/.claude/scripts"

    if [[ ! -d "$scripts_src" ]]; then
        log_warn "Scripts source directory not found: ${scripts_src}"
        return 0
    fi

    mkdir -p "$scripts_dst"

    local updated=0
    local added=0

    # Update Python scripts for cost tracking and metrics
    for script_file in "${scripts_src}"/*.py; do
        if [[ -f "$script_file" ]]; then
            local filename=$(basename "$script_file")
            local dst_file="${scripts_dst}/${filename}"

            if [[ "$DRY_RUN" == true ]]; then
                if [[ -f "$dst_file" ]]; then
                    if ! diff -q "$script_file" "$dst_file" &>/dev/null; then
                        log_info "[DRY-RUN] Would update script: ${filename}"
                        ((updated++)) || true
                    fi
                else
                    log_info "[DRY-RUN] Would add script: ${filename}"
                    ((added++)) || true
                fi
            else
                if [[ -f "$dst_file" ]]; then
                    if ! diff -q "$script_file" "$dst_file" &>/dev/null; then
                        cp "$script_file" "$dst_file"
                        chmod +x "$dst_file" 2>/dev/null || true
                        log_ok "Updated script: ${filename}"
                        ((updated++)) || true
                    fi
                else
                    cp "$script_file" "$dst_file"
                    chmod +x "$dst_file" 2>/dev/null || true
                    log_ok "Added script: ${filename}"
                    ((added++)) || true
                fi
            fi
        fi
    done

    if [[ $updated -eq 0 && $added -eq 0 ]]; then
        log_ok "All utility scripts up to date"
    else
        log_ok "Scripts: ${updated} updated, ${added} added"
    fi
}

# Update hook configurations in settings.json
# Merges hooks from settings.template.json, preserving user-added hooks
#
# BEHAVIORAL DIFFERENCE: install vs update
#   - install.sh: Replaces all hooks with template hooks (clean slate)
#   - update.sh:  Merges template hooks while preserving user-added hook types
#                 Template hooks always take precedence for hook types defined in template,
#                 but user-added hooks for types NOT in template are preserved.
#
update_hook_configs() {
    log_section "Updating Hook Configurations"

    local settings_file="${CLAUDE_DIR}/settings.json"
    local template_file="${REPO_DIR}/.claude/settings.template.json"
    local backup_file="${BACKUP_DIR}/${TIMESTAMP}/settings.json.hooks.backup"

    if [[ ! -f "$template_file" ]]; then
        log_warn "Settings template not found: ${template_file}"
        log_info "Skipping hook configuration update"
        return 0
    fi

    if [[ ! -f "$settings_file" ]]; then
        log_warn "User settings not found. Run install.sh for initial setup."
        return 1
    fi

    if ! command -v jq &>/dev/null; then
        log_warn "jq not installed - run update_brew_packages first"
        return 1
    fi

    # Get hooks from template
    local template_hooks
    template_hooks=$(jq '.hooks // {}' "$template_file")

    if [[ "$template_hooks" == "{}" || "$template_hooks" == "null" ]]; then
        log_warn "No hooks found in template"
        return 0
    fi

    # Get current hooks from settings
    local current_hooks
    current_hooks=$(jq '.hooks // {}' "$settings_file")

    if [[ "$DRY_RUN" == true ]]; then
        log_info "[DRY-RUN] Would merge hooks from template into settings"
        log_info "[DRY-RUN] Template hooks: $(echo "$template_hooks" | jq -r 'keys | join(", ")')"
        log_info "[DRY-RUN] Current hooks: $(echo "$current_hooks" | jq -r 'keys | join(", ")')"
        return 0
    fi

    # Backup existing hooks
    mkdir -p "$(dirname "$backup_file")"
    echo "$current_hooks" > "$backup_file"
    log_info "Backed up existing hooks to ${backup_file}"

    # Deep merge: template hooks take precedence, but preserve user hooks not in template
    # This means: for each hook type, use template version; keep user hooks for types not in template
    local temp_file
    temp_file=$(mktemp)

    # Merge strategy: template hooks override, user hooks for non-template types preserved
    #
    # jq expression breakdown:
    #   $template_hooks * (...)  - Start with all template hooks, then merge in...
    #   $current_hooks | to_entries | map(select(...)) | from_entries
    #     - Convert current hooks to key-value pairs
    #     - Filter to keep only entries where the key does NOT exist in template_hooks
    #     - Convert back to object
    #
    # Result: "Use all template hooks, plus any user hooks that aren't in the template"
    # This preserves user customizations for hook types not defined in the template,
    # while ensuring template-defined hooks are always updated to latest version.
    #
    if jq --argjson template_hooks "$template_hooks" --argjson current_hooks "$current_hooks" '
        .hooks = ($template_hooks * ($current_hooks | to_entries | map(select(.key as $k | $template_hooks | has($k) | not)) | from_entries))
    ' "$settings_file" > "$temp_file"; then
        # Validate JSON
        if jq empty "$temp_file" 2>/dev/null; then
            mv "$temp_file" "$settings_file"
            log_ok "Hook configurations updated"

            # Show what was updated
            local updated_types
            updated_types=$(echo "$template_hooks" | jq -r 'keys | join(", ")')
            log_info "Updated hook types: ${updated_types}"
        else
            log_error "Generated invalid JSON - settings not updated"
            rm -f "$temp_file"
            return 1
        fi
    else
        log_error "Failed to merge hooks"
        rm -f "$temp_file"
        return 1
    fi
}

# Update plugins
update_plugins() {
    log_section "Checking Plugins"

    # Plugin installation via CLI launches interactive mode, so we just verify settings
    local settings_file="${CLAUDE_DIR}/settings.json"

    local plugins=(
        "superpowers@superpowers-marketplace"
        "gopls-lsp@claude-plugins-official"
        "ralph-wiggum@claude-plugins-official"
        "frontend-design@claude-plugins-official"
        "ralph-loop@claude-plugins-official"
    )

    if [[ "$DRY_RUN" == true ]]; then
        log_info "[DRY-RUN] Would verify plugins in settings.json"
        for plugin in "${plugins[@]}"; do
            local plugin_name="${plugin%%@*}"
            log_info "  - $plugin_name"
        done
        return 0
    fi

    # Check if plugins are enabled in settings.json
    if [[ -f "$settings_file" ]]; then
        for plugin in "${plugins[@]}"; do
            local plugin_name="${plugin%%@*}"
            if grep -q "$plugin" "$settings_file" 2>/dev/null; then
                log_ok "$plugin_name plugin: enabled in settings"
            else
                log_warn "$plugin_name plugin: not found in settings, installing..."
                if claude plugins install "$plugin" 2>/dev/null; then
                    log_ok "$plugin_name plugin installed"
                else
                    log_warn "Could not install $plugin_name plugin"
                    log_info "  To install manually: claude plugins install $plugin"
                fi
            fi
        done

        # Note: episodic-memory replaced by agentdb MCP server
        if grep -q '"agentdb"' "$settings_file" 2>/dev/null; then
            log_ok "agentdb: configured in settings"
        else
            log_warn "agentdb: not found in settings"
            log_info "  Memory features provided by agentdb MCP server"
        fi
    else
        log_warn "Settings file not found. Run install.sh for initial setup."
    fi
}

# Update CodeGraphContext (code graph MCP server — pip package: codegraphcontext)
update_codegraphcontext() {
    log_section "Checking CodeGraphContext"

    if [[ "$DRY_RUN" == true ]]; then
        log_info "[DRY-RUN] Would check/update CodeGraphContext (pip) and Neo4j"
        return 0
    fi

    if ! command -v cgc &>/dev/null; then
        log_warn "CodeGraphContext: not installed"
        log_info "  Install: pip3 install codegraphcontext tree-sitter-c-sharp"
        return 0
    fi

    local cgc_version
    cgc_version=$(cgc --version 2>&1 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' || echo "unknown")
    log_ok "CodeGraphContext: installed (${cgc_version})"

    # Check for updates via pip
    if command -v pip3 &>/dev/null; then
        log_info "Checking for CodeGraphContext updates..."
        if pip3 install --upgrade codegraphcontext tree-sitter-c-sharp 2>/dev/null | grep -q "Successfully installed"; then
            local new_version
            new_version=$(cgc --version 2>&1 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' || echo "unknown")
            log_ok "CodeGraphContext: updated to ${new_version}"
        else
            log_ok "CodeGraphContext: up to date"
        fi
    fi

    # Ensure Neo4j container is running with correct restart policy
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
        if docker inspect neo4j &>/dev/null 2>&1; then
            local neo4j_status
            neo4j_status=$(docker ps --filter name=neo4j --format '{{.Status}}' 2>/dev/null || echo "")
            if [[ -z "$neo4j_status" ]]; then
                docker start neo4j &>/dev/null && log_ok "Neo4j: started" || log_warn "Neo4j: could not start"
            else
                log_ok "Neo4j: running (${neo4j_status})"
            fi
        fi
    fi

    # Verify MCP server is configured in ~/.claude.json
    local claude_json="$HOME/.claude.json"
    local cgc_path
    cgc_path=$(command -v cgc)

    if [[ -f "$claude_json" ]]; then
        if jq -e '.mcpServers["CodeGraphContext"]' "$claude_json" &>/dev/null; then
            log_ok "CodeGraphContext MCP server: configured"
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
            fi
        fi
    fi
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

# Check MCP servers by reading settings file directly (avoids interactive CLI)
update_mcp_servers() {
    log_section "Checking MCP Servers"

    local settings_file="${CLAUDE_DIR}/settings.json"
    local missing_servers=()

    if [[ "$DRY_RUN" == true ]]; then
        log_info "[DRY-RUN] Would verify MCP servers in settings"
        log_info "  - agentdb"
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
    else
        log_warn "Settings file not found"
        missing_servers+=("agentdb")
    fi

    # Provide manual instructions for missing servers
    if [[ ${#missing_servers[@]} -gt 0 ]]; then
        echo ""
        log_info "To add missing MCP servers, run:"
        for server in "${missing_servers[@]}"; do
            case "$server" in
                agentdb)
                    echo "  ./scripts/install.sh --configure-agentdb"
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

# Clean up old backups (keep last 5)
cleanup_old_backups() {
    if [[ -d "$BACKUP_DIR" ]]; then
        local backup_count=$(ls -1 "$BACKUP_DIR" 2>/dev/null | wc -l)
        if [[ $backup_count -gt 5 ]]; then
            log_info "Cleaning up old backups (keeping last 5)..."
            ls -1t "$BACKUP_DIR" | tail -n +6 | while read dir; do
                rm -rf "${BACKUP_DIR}/${dir}"
            done
            log_ok "Old backups cleaned"
        fi
    fi
}

# Update smart hook loader
update_smart_hooks() {
    log_section "Updating Smart Hook Loader"

    # Update hook loader
    cp "${BASE_CONFIG_DIR}/.claude/hooks/hook-loader.py" "${HOME}/.claude/hooks/"
    chmod +x "${HOME}/.claude/hooks/hook-loader.py"

    # Update manifest
    cp "${BASE_CONFIG_DIR}/.claude/hooks/manifest.json" "${HOME}/.claude/hooks/"

    # Update safety hooks
    mkdir -p "${HOME}/.claude/hooks/safety"
    for hook in block-dangerous-commands.py; do
        if [[ -f "${BASE_CONFIG_DIR}/.claude/hooks/safety/${hook}" ]]; then
            cp "${BASE_CONFIG_DIR}/.claude/hooks/safety/${hook}" "${HOME}/.claude/hooks/safety/"
            chmod +x "${HOME}/.claude/hooks/safety/${hook}"
        fi
    done

    # Update emergency disable script
    cp "${BASE_CONFIG_DIR}/.claude/hooks/EMERGENCY-DISABLE.sh" "${HOME}/.claude/hooks/"
    chmod +x "${HOME}/.claude/hooks/EMERGENCY-DISABLE.sh"

    log_ok "Smart Hook Loader updated"
}

# Update Ollama model aliases (if Ollama is installed)
update_ollama_aliases() {
    if [[ "$(uname)" != "Darwin" ]]; then
        return 0
    fi

    if ! command -v ollama &>/dev/null; then
        return 0
    fi

    local alias_script="${REPO_DIR}/scripts/setup-ollama-aliases.sh"
    if [[ ! -x "$alias_script" ]]; then
        return 0
    fi

    # Only run if Ollama is running (don't start it just for aliases)
    if ! curl -sf http://localhost:11434/api/tags &>/dev/null; then
        log_info "Ollama not running — skipping alias update (run setup-ollama-aliases.sh manually)"
        return 0
    fi

    if [[ "$DRY_RUN" == true ]]; then
        log_info "[DRY RUN] Would update Ollama model aliases"
        return 0
    fi

    log_section "Updating Ollama Model Aliases"
    "$alias_script"
    log_ok "Ollama model aliases updated"
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

    # Migrate legacy PROJECT_ROOT to PROJECT_ROOT
    if [[ "$DRY_RUN" != true ]]; then
        migrate_project_root_env "$ENV_FILE"
    fi

    # Detect tenant from existing TENANT_NAMESPACE in .env, JIRA_PROJECT_KEYS, or repo path
    local tenant="hooks"
    if [[ -f "$ENV_FILE" ]]; then
        tenant=$(grep "^TENANT_NAMESPACE=" "$ENV_FILE" 2>/dev/null | cut -d'=' -f2 || true)
        if [[ -z "$tenant" ]]; then
            # Try to infer from JIRA_PROJECT_KEYS
            local jira_keys=$(grep "^JIRA_PROJECT_KEYS=" "$ENV_FILE" 2>/dev/null | cut -d'=' -f2 || true)
            if [[ -n "$jira_keys" ]]; then
                # Use first project key as tenant namespace (lowercase)
                tenant=$(echo "$jira_keys" | cut -d',' -f1 | tr '[:upper:]' '[:lower:]')
            elif [[ "$jira_keys" == *"${PROJECT_KEY}"* ]]; then
                tenant="${TENANT_NAMESPACE}"
            fi
        fi
    fi
    # Fall back to path-based detection
    if [[ -z "$tenant" || "$tenant" == "hooks" ]]; then
        if [[ -n "${TENANT_NAMESPACE:-}" ]]; then
            tenant="${TENANT_NAMESPACE}"
        else
            tenant="default"
        fi
    fi

    # Update .env with AgentDB configuration
    update_env_agentdb "$ENV_FILE" "$tenant"

    check_git_repo

    if [[ "$DRY_RUN" != true ]]; then
        create_backup_dir
    fi

    check_uncommitted_changes
    backup_existing_config
    pull_latest
    update_brew_packages
    sync_project_repos
    # update_mcp_repos  # DEPRECATED: Skills now call REST APIs directly
    update_commands
    update_hooks
    setup_project_hooks
    update_workflows
    update_agents
    update_teams
    update_skills
    update_scripts
    update_hook_configs
    update_plugins
    update_testing_tools
    update_codegraphcontext
    update_mcp_servers
    update_tool_permissions
    update_parent_claude_md
    update_smart_hooks
    update_ollama_aliases

    if [[ "$DRY_RUN" != true ]]; then
        cleanup_old_backups
    fi

    show_version_info

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
