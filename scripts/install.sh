#!/bin/bash
#
# Platform Agents - Developer Setup Script
# Installs and configures Claude Code environment with MCP servers
#
# Usage:
#   ./scripts/install.sh              # Interactive setup
#   ./scripts/install.sh --check      # Check current setup status
#   ./scripts/install.sh --uninstall  # Remove configuration
#
# Prerequisites:
#   - Node.js 18+
#   - Git
#   - AWS CLI (for Bedrock access)
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
ENV_EXAMPLE="${REPO_DIR}/.env.example"

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

# Check if command exists
has_command() {
    command -v "$1" &>/dev/null
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

# Merge model routing configs from base and tenant
# Base config provides defaults, tenant config overrides specific commands
install_model_routing() {
    log_section "Installing Model Routing Config"

    local base_config="${REPO_DIR}/config/model-routing.json"
    local tenant_config="${TENANT_CONFIG_DIR:+${TENANT_CONFIG_DIR}/config/model-routing.json}"
    local output_dir="${CLAUDE_DIR}/config"
    local output="${output_dir}/model-routing.json"

    mkdir -p "$output_dir"

    if [[ ! -f "$base_config" ]]; then
        log_warn "Base model routing config not found: ${base_config}"
        return 0
    fi

    if [[ -n "$tenant_config" && -f "$tenant_config" ]]; then
        # Deep merge: tenant commands override base commands
        jq -s '
            .[0] as $base | .[1] as $tenant |
            {
                version: ($tenant.version // $base.version),
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

# Install config files (api-defaults, memory-policy) to ~/.claude/config/
install_config_files() {
    log_section "Installing Config Files"

    local config_src="${REPO_DIR}/config"
    local config_dst="${CLAUDE_DIR}/config"

    mkdir -p "$config_dst"

    local config_count=0

    # Copy JSON config files
    for config_file in "${config_src}"/*.json; do
        if [[ -f "$config_file" ]]; then
            local filename=$(basename "$config_file")
            # Skip model-routing.json (handled by install_model_routing with merge)
            if [[ "$filename" == "model-routing.json" ]]; then
                continue
            fi
            cp "$config_file" "${config_dst}/${filename}"
            log_ok "Installed config: ${filename}"
            ((config_count++))
        fi
    done

    log_ok "Config files installed: ${config_count} files to ${config_dst}"
}

# Install missing brew packages from the merged config
install_brew_packages() {
    if ! ensure_jq; then
        return 1
    fi

    load_brew_packages "$BASE_CONFIG_DIR" "$TENANT_CONFIG_DIR"

    local pkg_count
    pkg_count=$(echo "$BREW_PACKAGES" | jq 'length')

    if [[ "$pkg_count" -eq 0 ]]; then
        return 0
    fi

    log_section "Installing Homebrew Packages"

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
            log_ok "${name}: already installed (${current_version})"
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

    log_ok "Homebrew package check complete"
}

# Check prerequisites
check_prerequisites() {
    log_section "Checking Prerequisites"

    local missing=()

    if ! has_command node; then
        missing+=("node")
    else
        local node_version=$(node -v | sed 's/v//' | cut -d. -f1)
        if [[ $node_version -lt 18 ]]; then
            log_warn "Node.js version $node_version found, 18+ recommended"
        else
            log_ok "Node.js $(node -v)"
        fi
    fi

    if ! has_command npm; then
        missing+=("npm")
    else
        log_ok "npm $(npm -v)"
    fi

    if ! has_command git; then
        missing+=("git")
    else
        log_ok "git $(git --version | cut -d' ' -f3)"
        # Verify SSH access to Bitbucket
        if ssh -T git@bitbucket.org 2>&1 | grep -q "authenticated"; then
            log_ok "Bitbucket SSH access configured"
        else
            log_warn "Bitbucket SSH access not configured"
            log_info "  SSH access is required to clone MCP server repos"
            log_info "  See: https://support.atlassian.com/bitbucket-cloud/docs/set-up-an-ssh-key/"
        fi
    fi

    if ! has_command aws; then
        log_warn "AWS CLI not found - needed for Bedrock access"
    else
        log_ok "AWS CLI $(aws --version | cut -d' ' -f1 | cut -d'/' -f2)"
    fi

    if ! has_command claude; then
        log_warn "Claude Code CLI not found - will be installed"
    else
        log_ok "Claude Code CLI installed"
    fi

    if [[ ${#missing[@]} -gt 0 ]]; then
        log_error "Missing required tools: ${missing[*]}"
        log_error "Please install them first:"
        log_error "  brew install node git  # macOS"
        log_error "  Or visit: https://nodejs.org/"
        exit 1
    fi

    log_ok "All prerequisites met"
}

# Install Claude Code CLI
install_claude_cli() {
    log_section "Installing Claude Code CLI"

    if has_command claude; then
        log_ok "Claude Code CLI already installed"
        return 0
    fi

    log_info "Installing @anthropic-ai/claude-code..."
    npm install -g @anthropic-ai/claude-code

    if has_command claude; then
        log_ok "Claude Code CLI installed successfully"
    else
        log_error "Failed to install Claude Code CLI"
        exit 1
    fi
}

# Create .claude directory structure
setup_claude_directory() {
    log_section "Setting Up Claude Directory"

    mkdir -p "${CLAUDE_DIR}/commands"
    mkdir -p "${CLAUDE_DIR}/hooks"
    mkdir -p "${CLAUDE_DIR}/skills"
    mkdir -p "${CLAUDE_DIR}/workflows"
    mkdir -p "${CLAUDE_DIR}/agents"
    mkdir -p "${CLAUDE_DIR}/teams"
    mkdir -p "${CLAUDE_DIR}/pattern-training"
    mkdir -p "${CLAUDE_DIR}/projects"

    log_ok "Claude directory structure created: ${CLAUDE_DIR}"
}

# Install core MCP servers
install_core_mcp_servers() {
    log_section "Installing Core MCP Servers"

    # claude-flow, ruv-swarm, flow-nexus have been removed
    log_info "Note: claude-flow, ruv-swarm, and flow-nexus MCP servers have been removed"
    log_info "All functionality now uses REST skills and AgentDB for memory"
    log_ok "Core MCP server check complete"
}

# Clone or update MCP server repositories
setup_mcp_repos() {
    log_section "Setting Up MCP Server Repositories"

    # Load paths from .env or use defaults
    if [[ -f "$ENV_FILE" ]]; then
        source "$ENV_FILE"
    fi

    local jira_mcp_path="${JIRA_MCP_PATH:-${REPO_DIR}/mcp-servers/jira-mcp}"
    local bb_mcp_path="${BITBUCKET_MCP_PATH:-${REPO_DIR}/mcp-servers/bitbucket-mcp}"

    # Create mcp-servers directory if using defaults
    if [[ -z "${JIRA_MCP_PATH:-}" ]] || [[ -z "${BITBUCKET_MCP_PATH:-}" ]]; then
        mkdir -p "${REPO_DIR}/mcp-servers"
    fi

    # Clone or update jira-mcp
    log_info "Setting up jira-mcp at ${jira_mcp_path}..."
    if [[ -d "${jira_mcp_path}/.git" ]]; then
        log_info "Repository exists, pulling latest..."
        (cd "$jira_mcp_path" && git pull origin main)
    else
        log_info "Cloning jira-mcp..."
        git clone git@bitbucket.org:your-org/jira-mcp.git "$jira_mcp_path"
    fi
    log_info "Installing dependencies and building..."
    (cd "$jira_mcp_path" && npm install && npm run build)
    log_ok "jira-mcp ready at ${jira_mcp_path}"

    # Clone or update bitbucket-mcp
    log_info "Setting up bitbucket-mcp at ${bb_mcp_path}..."
    if [[ -d "${bb_mcp_path}/.git" ]]; then
        log_info "Repository exists, pulling latest..."
        (cd "$bb_mcp_path" && git pull origin main)
    else
        log_info "Cloning bitbucket-mcp..."
        git clone git@bitbucket.org:your-org/bitbucket-mcp.git "$bb_mcp_path"
    fi
    log_info "Installing dependencies and building..."
    (cd "$bb_mcp_path" && npm install && npm run build)
    log_ok "bitbucket-mcp ready at ${bb_mcp_path}"

    # Export paths for use by setup_project_mcp_servers
    export JIRA_MCP_PATH="$jira_mcp_path"
    export BITBUCKET_MCP_PATH="$bb_mcp_path"
}

# Check if project repos are configured
check_project_repos_configured() {
    if [[ -f "$ENV_FILE" ]]; then
        source "$ENV_FILE"
    fi

    # Check if PROJECT_REPOS is set and at least one repo exists
    if [[ -z "${PROJECT_REPOS:-}" ]]; then
        return 1
    fi

    local project_root="${PROJECT_ROOT:-$(dirname "$REPO_DIR")}"
    # Resolve relative path
    if [[ "$project_root" == ".." || "$project_root" == "../"* ]]; then
        project_root="$(cd "$REPO_DIR" && cd "$project_root" && pwd)"
    fi

    # Check if at least one configured repo exists
    IFS=',' read -ra repos <<< "$PROJECT_REPOS"
    for repo in "${repos[@]}"; do
        repo=$(echo "$repo" | xargs)  # Trim whitespace
        if [[ -d "${project_root}/${repo}/.git" ]]; then
            return 0
        fi
    done

    return 1
}

# Configure project repositories interactively
configure_project_repos() {
    log_section "Configuring Project Repositories"

    # Load existing config
    if [[ -f "$ENV_FILE" ]]; then
        source "$ENV_FILE"
    fi

    echo ""
    log_info "This configures where the project project repositories should be cloned."
    log_info "This is useful for new developers setting up their environment."
    echo ""

    # Project root directory
    local default_root="$(dirname "$REPO_DIR")"
    read -p "Project root directory [${PROJECT_ROOT:-$default_root}]: " input_root
    PROJECT_ROOT="${input_root:-${PROJECT_ROOT:-$default_root}}"

    # Resolve relative paths for display
    local resolved_root="$PROJECT_ROOT"
    if [[ "$resolved_root" == ".." || "$resolved_root" == "../"* ]]; then
        resolved_root="$(cd "$REPO_DIR" && cd "$resolved_root" 2>/dev/null && pwd)" || resolved_root="$PROJECT_ROOT"
    fi
    log_info "Repositories will be cloned to: ${resolved_root}/<repo-name>"

    # Git host
    echo ""
    echo "Git hosting provider:"
    echo "  1) Bitbucket (default)"
    echo "  2) GitHub"
    read -p "Select [1]: " input_host
    case "$input_host" in
        2) PROJECT_GIT_HOST="github" ;;
        *) PROJECT_GIT_HOST="${PROJECT_GIT_HOST:-bitbucket}" ;;
    esac

    # Workspace/Org configuration
    if [[ "$PROJECT_GIT_HOST" == "bitbucket" ]]; then
        read -p "Bitbucket workspace [${VCS_WORKSPACE:-your-org}]: " input_workspace
        VCS_WORKSPACE="${input_workspace:-${VCS_WORKSPACE:-your-org}}"
    else
        read -p "GitHub organization [${PROJECT_GITHUB_ORG:-}]: " input_org
        PROJECT_GITHUB_ORG="${input_org:-${PROJECT_GITHUB_ORG:-}}"
    fi

    # Core repositories
    echo ""
    log_info "Core project repositories (recommended for all developers):"
    echo "  frontend-app      - Frontend marketplace UI"
    echo "  auth-service     - Platform authentication"
    echo "  sdk      - SDK for publishers"
    echo "  project-docs     - Documentation"
    echo "  test-data - Test fixtures"
    echo ""

    local default_repos="lambda-functions,frontend-app,auth-service,sdk,project-docs,test-data"
    read -p "Repositories to clone (comma-sep) [${PROJECT_REPOS:-$default_repos}]: " input_repos
    PROJECT_REPOS="${input_repos:-${PROJECT_REPOS:-$default_repos}}"

    # Optional repositories
    echo ""
    log_info "Optional repositories (not required for most developers):"
    echo "  bootstrap, canary, cli-tool, jwt-demo, odef-spec"
    read -p "Additional repos to clone (comma-sep, or press Enter to skip) [${PROJECT_REPOS_OPTIONAL:-}]: " input_optional
    PROJECT_REPOS_OPTIONAL="${input_optional:-${PROJECT_REPOS_OPTIONAL:-}}"

    # Default branch
    read -p "Default branch [${PROJECT_DEFAULT_BRANCH:-main}]: " input_branch
    PROJECT_DEFAULT_BRANCH="${input_branch:-${PROJECT_DEFAULT_BRANCH:-main}}"

    # Save to .env (append or update)
    log_info "Saving project repository configuration..."

    # Check if these settings exist in .env, if so update, otherwise append
    if [[ -f "$ENV_FILE" ]]; then
        # Create temp file with updated/new values
        local temp_env=$(mktemp)

        # Remove existing PROJECT_* lines (we'll add fresh ones)
        grep -v "^PROJECT_ROOT=" "$ENV_FILE" | \
        grep -v "^PROJECT_GIT_HOST=" | \
        grep -v "^VCS_WORKSPACE=" | \
        grep -v "^PROJECT_GITHUB_ORG=" | \
        grep -v "^PROJECT_REPOS=" | \
        grep -v "^PROJECT_REPOS_OPTIONAL=" | \
        grep -v "^PROJECT_DEFAULT_BRANCH=" > "$temp_env" || true

        mv "$temp_env" "$ENV_FILE"
    fi

    # Append project repo configuration
    cat >> "$ENV_FILE" <<EOF

# Project Repository Configuration
PROJECT_ROOT=${PROJECT_ROOT}
PROJECT_GIT_HOST=${PROJECT_GIT_HOST}
VCS_WORKSPACE=${VCS_WORKSPACE:-}
PROJECT_GITHUB_ORG=${PROJECT_GITHUB_ORG:-}
PROJECT_REPOS=${PROJECT_REPOS}
PROJECT_REPOS_OPTIONAL=${PROJECT_REPOS_OPTIONAL:-}
PROJECT_DEFAULT_BRANCH=${PROJECT_DEFAULT_BRANCH}
EOF

    log_ok "Project repository configuration saved to .env"
}

# Clone project repositories
setup_project_repos() {
    log_section "Setting Up Project Repositories"

    # Load configuration
    if [[ -f "$ENV_FILE" ]]; then
        source "$ENV_FILE"
    fi

    # Check if configuration exists
    if [[ -z "${PROJECT_REPOS:-}" ]]; then
        log_warn "Project repositories not configured"
        echo ""
        read -p "Would you like to configure project repositories now? (y/N): " confirm
        if [[ "$confirm" == "y" || "$confirm" == "Y" ]]; then
            configure_project_repos
            source "$ENV_FILE"
        else
            log_info "Skipping project repository setup"
            log_info "Run './scripts/install.sh --configure-repos' later to set this up"
            return 0
        fi
    fi

    # Resolve project root
    local project_root="${PROJECT_ROOT:-$(dirname "$REPO_DIR")}"
    if [[ "$project_root" == ".." || "$project_root" == "../"* ]]; then
        project_root="$(cd "$REPO_DIR" && cd "$project_root" && pwd)"
    fi

    # Create project root if needed
    if [[ ! -d "$project_root" ]]; then
        log_info "Creating project directory: ${project_root}"
        mkdir -p "$project_root"
    fi

    # Determine git URL prefix
    local git_prefix
    if [[ "$PROJECT_GIT_HOST" == "github" ]]; then
        git_prefix="git@github.com:${PROJECT_GITHUB_ORG}/"
    else
        git_prefix="git@bitbucket.org:${VCS_WORKSPACE}/"
    fi

    # Clone core repositories
    log_info "Cloning repositories to ${project_root}/..."
    echo ""

    IFS=',' read -ra repos <<< "$PROJECT_REPOS"
    local cloned=0
    local skipped=0
    local failed=0

    for repo in "${repos[@]}"; do
        repo=$(echo "$repo" | xargs)  # Trim whitespace
        local repo_path="${project_root}/${repo}"
        local repo_url="${git_prefix}${repo}.git"

        if [[ -d "${repo_path}/.git" ]]; then
            log_ok "${repo}: already exists"
            ((skipped++))
        else
            log_info "Cloning ${repo}..."
            if git clone --branch "${PROJECT_DEFAULT_BRANCH:-main}" "$repo_url" "$repo_path" 2>/dev/null; then
                log_ok "${repo}: cloned"
                ((cloned++))
            else
                log_error "${repo}: failed to clone from ${repo_url}"
                ((failed++))
            fi
        fi
    done

    # Clone optional repositories if configured
    if [[ -n "${PROJECT_REPOS_OPTIONAL:-}" ]]; then
        echo ""
        log_info "Setting up optional repositories..."

        IFS=',' read -ra optional_repos <<< "$PROJECT_REPOS_OPTIONAL"
        for repo in "${optional_repos[@]}"; do
            repo=$(echo "$repo" | xargs)
            local repo_path="${project_root}/${repo}"
            local repo_url="${git_prefix}${repo}.git"

            if [[ -d "${repo_path}/.git" ]]; then
                log_ok "${repo}: already exists"
                ((skipped++))
            else
                log_info "Cloning ${repo}..."
                if git clone --branch "${PROJECT_DEFAULT_BRANCH:-main}" "$repo_url" "$repo_path" 2>/dev/null; then
                    log_ok "${repo}: cloned"
                    ((cloned++))
                else
                    log_warn "${repo}: failed to clone (optional)"
                    ((failed++))
                fi
            fi
        done
    fi

    echo ""
    log_ok "Repository setup complete: ${cloned} cloned, ${skipped} already present, ${failed} failed"

    if [[ $failed -gt 0 ]]; then
        log_warn "Some repositories failed to clone. Check SSH access and repository names."
        log_info "Verify SSH: ssh -T git@bitbucket.org (or github.com)"
    fi
}

# Prompt for credentials and add project-specific MCP servers
setup_project_mcp_servers() {
    log_section "Setting Up Project MCP Servers"

    # Load existing credentials if .env exists
    if [[ -f "$ENV_FILE" ]]; then
        log_info "Loading credentials from ${ENV_FILE}..."
        source "$ENV_FILE"
    fi

    echo ""
    log_info "These MCP servers require credentials for your project's Jira and Bitbucket instances."
    echo ""

    # Jira MCP setup
    echo -e "${CYAN}--- Jira MCP Setup ---${NC}"
    echo "Get API token: https://id.atlassian.com/manage-profile/security/api-tokens"
    echo ""

    read -p "Jira Host (e.g., company.atlassian.net) [${JIRA_HOST:-}]: " input_jira_host
    JIRA_HOST="${input_jira_host:-${JIRA_HOST:-}}"

    read -p "Jira Username (email) [${JIRA_USERNAME:-}]: " input_jira_username
    JIRA_USERNAME="${input_jira_username:-${JIRA_USERNAME:-}}"

    read -sp "Jira API Token [${JIRA_API_TOKEN:+****}]: " input_jira_token
    echo ""
    JIRA_API_TOKEN="${input_jira_token:-${JIRA_API_TOKEN:-}}"

    read -p "Jira Project Keys (comma-sep) [${JIRA_PROJECT_KEYS:-PROJ}]: " input_jira_projects
    JIRA_PROJECT_KEYS="${input_jira_projects:-${JIRA_PROJECT_KEYS:-PROJ}}"

    echo ""
    echo -e "${CYAN}--- Bitbucket MCP Setup ---${NC}"
    echo "Get app password: https://bitbucket.org/account/settings/app-passwords/"
    echo "Required scopes: Repository (read/write), Pull requests (read/write), Pipelines (read)"
    echo ""

    read -p "Bitbucket Username (email) [${BITBUCKET_USERNAME:-}]: " input_bb_username
    BITBUCKET_USERNAME="${input_bb_username:-${BITBUCKET_USERNAME:-}}"

    read -sp "Bitbucket App Password (Token) [${BITBUCKET_TOKEN:+****}]: " input_bb_password
    echo ""
    BITBUCKET_TOKEN="${input_bb_password:-${BITBUCKET_TOKEN:-}}"

    read -p "Bitbucket Workspace [${BITBUCKET_WORKSPACE:-}]: " input_bb_workspace
    BITBUCKET_WORKSPACE="${input_bb_workspace:-${BITBUCKET_WORKSPACE:-}}"

    read -p "Bitbucket Project Key [${BITBUCKET_PROJECT_KEY:-PROJ}]: " input_bb_project
    BITBUCKET_PROJECT_KEY="${input_bb_project:-${BITBUCKET_PROJECT_KEY:-PROJ}}"

    read -p "Bitbucket Repository Slugs (comma-sep) [${BITBUCKET_REPOSITORY_SLUGS:-}]: " input_bb_repos
    BITBUCKET_REPOSITORY_SLUGS="${input_bb_repos:-${BITBUCKET_REPOSITORY_SLUGS:-}}"

    read -p "Default Branch [${BITBUCKET_DEFAULT_BRANCH:-main}]: " input_bb_branch
    BITBUCKET_DEFAULT_BRANCH="${input_bb_branch:-${BITBUCKET_DEFAULT_BRANCH:-main}}"

    # Save credentials to .env
    log_info "Saving credentials to ${ENV_FILE}..."
    cat > "$ENV_FILE" <<EOF
# Platform Agents Environment Configuration
# This file contains credentials - DO NOT COMMIT TO GIT

# Jira Configuration
JIRA_HOST=${JIRA_HOST}
JIRA_USERNAME=${JIRA_USERNAME}
JIRA_API_TOKEN=${JIRA_API_TOKEN}
JIRA_PROJECT_KEYS=${JIRA_PROJECT_KEYS}
JIRA_PROTOCOL=https
JIRA_API_VERSION=2

# Bitbucket Configuration
BITBUCKET_USERNAME=${BITBUCKET_USERNAME}
BITBUCKET_TOKEN=${BITBUCKET_TOKEN}
BITBUCKET_WORKSPACE=${BITBUCKET_WORKSPACE}
BITBUCKET_PROJECT_KEY=${BITBUCKET_PROJECT_KEY}
BITBUCKET_REPOSITORY_SLUGS=${BITBUCKET_REPOSITORY_SLUGS}
BITBUCKET_DEFAULT_BRANCH=${BITBUCKET_DEFAULT_BRANCH}

# AWS Configuration (for Bedrock)
AWS_PROFILE=\${AWS_PROFILE:-default}
AWS_REGION=\${AWS_REGION:-us-east-1}
EOF
    chmod 600 "$ENV_FILE"
    log_ok "Credentials saved"

    # DEPRECATED: MCP server configuration removed - skills now call REST APIs directly
    # Credentials above are still used by REST API skills via .env or ~/.claude/settings.json
    log_ok "Credentials configured for REST API skills"
}

# Copy commands to user's .claude directory
install_commands() {
    log_section "Installing Workflow Commands"

    local commands_src="${REPO_DIR}/.claude/commands"
    local commands_dst="${CLAUDE_DIR}/commands"

    if [[ ! -d "$commands_src" ]]; then
        log_warn "Commands directory not found: ${commands_src}"
        return 1
    fi

    local cmd_count=0
    local group_count=0

    # Copy top-level command files
    for cmd_file in "${commands_src}"/*.md; do
        if [[ -f "$cmd_file" ]]; then
            local filename=$(basename "$cmd_file")
            cp "$cmd_file" "${commands_dst}/${filename}"
            log_ok "Installed command: ${filename%.md}"
            ((cmd_count++))
        fi
    done

    # Copy command group subdirectories (e.g., loop/, metrics/)
    for group_dir in "${commands_src}"/*/; do
        if [[ -d "$group_dir" ]]; then
            local group_name=$(basename "$group_dir")
            local dst_group="${commands_dst}/${group_name}"
            mkdir -p "$dst_group"

            local group_file_count=0
            for cmd_file in "${group_dir}"*.md; do
                if [[ -f "$cmd_file" ]]; then
                    local filename=$(basename "$cmd_file")
                    cp "$cmd_file" "${dst_group}/${filename}"
                    ((group_file_count++))
                fi
            done

            if [[ $group_file_count -gt 0 ]]; then
                log_ok "Installed command group: ${group_name}/ (${group_file_count} commands)"
                ((group_count++))
            fi
        fi
    done

    log_ok "Workflow commands installed: ${cmd_count} commands, ${group_count} groups"
}

# Install hooks
install_hooks() {
    log_section "Installing Hooks"

    # Flat layout: repo keeps hooks in ${REPO_DIR}/hooks (no .claude/ prefix).
    # Legacy tenant repos used ${REPO_DIR}/.claude/hooks; fall back for compat.
    local hooks_src="${REPO_DIR}/hooks"
    if [[ ! -d "$hooks_src" ]]; then
        hooks_src="${REPO_DIR}/.claude/hooks"
    fi
    local hooks_dst="${CLAUDE_DIR}/hooks"

    if [[ ! -d "$hooks_src" ]]; then
        log_warn "Hooks directory not found: ${REPO_DIR}/hooks or ${REPO_DIR}/.claude/hooks"
        return 1
    fi

    # Copy hook files
    for hook_file in "${hooks_src}"/*; do
        if [[ -f "$hook_file" ]]; then
            local filename=$(basename "$hook_file")
            cp "$hook_file" "${hooks_dst}/${filename}"
            chmod +x "${hooks_dst}/${filename}" 2>/dev/null || true
            log_ok "Installed hook: ${filename}"
        fi
    done

    log_ok "Hooks installed"
}

# Install statusline script to ~/.claude/statusline-command.sh
# Referenced by settings.template.json "statusLine.command"
install_statusline() {
    log_section "Installing Statusline"

    local statusline_src="${REPO_DIR}/scripts/statusline-command.sh"
    local statusline_dst="${CLAUDE_DIR}/statusline-command.sh"

    if [[ ! -f "$statusline_src" ]]; then
        log_warn "Statusline script not found: ${statusline_src}"
        return 1
    fi

    cp "$statusline_src" "$statusline_dst"
    chmod +x "$statusline_dst"
    log_ok "Statusline installed: ${statusline_dst}"
}

# Install hook configuration to global settings.json
# This installs the hooks section from settings.template.json to ~/.claude/settings.json
install_global_hook_config() {
    log_section "Installing Global Hook Configuration"

    local TEMPLATE="${REPO_DIR}/.claude/settings.template.json"
    local TARGET="${CLAUDE_DIR}/settings.json"

    if [[ ! -f "$TEMPLATE" ]]; then
        log_warn "Settings template not found: ${TEMPLATE}"
        log_info "Skipping global hook configuration"
        return 0
    fi

    if ! command -v jq &>/dev/null; then
        log_warn "jq not installed - run install_brew_packages first"
        return 1
    fi

    # Create settings.json if it doesn't exist
    if [[ ! -f "$TARGET" ]]; then
        log_info "Creating ${TARGET}"
        echo '{}' > "$TARGET"
    fi

    # Extract hooks section from template
    local HOOKS
    HOOKS=$(jq '.hooks' "$TEMPLATE")

    if [[ "$HOOKS" == "null" || -z "$HOOKS" ]]; then
        log_warn "No hooks found in template"
        return 1
    fi

    # Backup existing settings
    local BACKUP="${TARGET}.backup.$(date +%Y%m%d_%H%M%S)"
    cp "$TARGET" "$BACKUP"
    log_info "Backed up existing settings to ${BACKUP}"

    # Merge hooks into target settings
    local TEMP_FILE
    TEMP_FILE=$(mktemp)
    if jq --argjson hooks "$HOOKS" '.hooks = $hooks' "$TARGET" > "$TEMP_FILE"; then
        mv "$TEMP_FILE" "$TARGET"
        log_ok "Installed hooks to ${TARGET}"
    else
        log_error "Failed to merge hooks into settings"
        rm -f "$TEMP_FILE"
        return 1
    fi

    # Verify hooks were installed
    if jq -e '.hooks.PreToolUse' "$TARGET" &>/dev/null && \
       jq -e '.hooks.PostToolUse' "$TARGET" &>/dev/null && \
       jq -e '.hooks.SessionStart' "$TARGET" &>/dev/null && \
       jq -e '.hooks.SessionEnd' "$TARGET" &>/dev/null; then
        log_ok "Verified: PreToolUse, PostToolUse, SessionStart, SessionEnd hooks present"
    else
        log_warn "Some hook types may be missing - check ${TARGET}"
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

    local hooks_src="${REPO_DIR}/hooks"
    if [[ ! -d "$hooks_src" ]]; then
        hooks_src="${REPO_DIR}/.claude/hooks"
    fi
    local copied=0

    if [[ ! -d "$hooks_src" ]]; then
        log_warn "Hooks source directory not found: ${REPO_DIR}/hooks or ${REPO_DIR}/.claude/hooks"
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
            log_warn "${repo}: repository not found at ${repo_path}"
            continue
        fi

        # Create .claude/hooks directory if it doesn't exist
        mkdir -p "$hooks_dst"

        # Remove symlink if it exists (from previous setup)
        if [[ -L "$hooks_dst" ]]; then
            rm "$hooks_dst"
            mkdir -p "$hooks_dst"
            log_info "${repo}: converted symlink to directory"
        fi

        # Copy hook files
        local repo_copied=0
        for hook_file in "${hooks_src}"/*; do
            if [[ -f "$hook_file" ]]; then
                local filename=$(basename "$hook_file")
                cp "$hook_file" "${hooks_dst}/${filename}"
                chmod +x "${hooks_dst}/${filename}" 2>/dev/null || true
                ((repo_copied++))
            fi
        done

        if [[ $repo_copied -gt 0 ]]; then
            log_ok "${repo}: copied ${repo_copied} hooks"
            ((copied++))
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
                continue  # Skip optional repos that don't exist
            fi

            mkdir -p "$hooks_dst"

            if [[ -L "$hooks_dst" ]]; then
                rm "$hooks_dst"
                mkdir -p "$hooks_dst"
            fi

            local repo_copied=0
            for hook_file in "${hooks_src}"/*; do
                if [[ -f "$hook_file" ]]; then
                    local filename=$(basename "$hook_file")
                    cp "$hook_file" "${hooks_dst}/${filename}"
                    chmod +x "${hooks_dst}/${filename}" 2>/dev/null || true
                    ((repo_copied++))
                fi
            done

            if [[ $repo_copied -gt 0 ]]; then
                log_ok "${repo}: copied ${repo_copied} hooks"
                ((copied++))
            fi
        done
    fi

    echo ""
    log_ok "Project hooks copied to ${copied} repositories"
}

# Install skills (progressive disclosure examples, documentation)
install_skills() {
    log_section "Installing Skills"

    local skills_src="${REPO_DIR}/.claude/skills"
    local skills_dst="${CLAUDE_DIR}/skills"

    if [[ ! -d "$skills_src" ]]; then
        log_warn "Skills directory not found: ${skills_src}"
        return 1
    fi

    mkdir -p "$skills_dst"

    local skill_count=0
    local subdir_count=0

    # Copy top-level skill files
    for skill_file in "${skills_src}"/*.md; do
        if [[ -f "$skill_file" ]]; then
            local filename=$(basename "$skill_file")
            cp "$skill_file" "${skills_dst}/${filename}"
            ((skill_count++))
        fi
    done

    # Copy skill subdirectories (e.g., examples/)
    for subdir in "${skills_src}"/*/; do
        if [[ -d "$subdir" ]]; then
            local dirname=$(basename "$subdir")
            cp -r "$subdir" "${skills_dst}/"
            ((subdir_count++))
        fi
    done

    log_ok "Skills installed: ${skill_count} files, ${subdir_count} directories"
}

# Install utility scripts (cost tracking, metrics, etc.)
install_scripts() {
    log_section "Installing Utility Scripts"

    local scripts_src="${REPO_DIR}/scripts"
    local scripts_dst="${HOME}/.claude/scripts"

    if [[ ! -d "$scripts_src" ]]; then
        log_warn "Scripts directory not found: ${scripts_src}"
        return 0
    fi

    mkdir -p "$scripts_dst"

    local script_count=0

    # Copy Python scripts for cost tracking and metrics
    for script_file in "${scripts_src}"/*.py; do
        if [[ -f "$script_file" ]]; then
            local filename=$(basename "$script_file")
            cp "$script_file" "${scripts_dst}/${filename}"
            chmod +x "${scripts_dst}/${filename}" 2>/dev/null || true
            ((script_count++))
        fi
    done

    # Also copy to project scripts directory if different from global
    local project_scripts="${REPO_DIR}/scripts"
    if [[ "$scripts_dst" != "$project_scripts" ]]; then
        for script_file in "${scripts_src}"/*.py; do
            if [[ -f "$script_file" ]]; then
                local filename=$(basename "$script_file")
                # Skip if already exists in project (tenant override)
                if [[ ! -f "${project_scripts}/${filename}" ]]; then
                    cp "$script_file" "${project_scripts}/${filename}"
                    chmod +x "${project_scripts}/${filename}" 2>/dev/null || true
                fi
            fi
        done
    fi

    if [[ $script_count -gt 0 ]]; then
        log_ok "Utility scripts installed: ${script_count} scripts to ${scripts_dst}"
    else
        log_info "No utility scripts to install"
    fi
}

# Install workflow definitions
install_workflows() {
    log_section "Installing Workflow Definitions"

    local workflows_src="${REPO_DIR}/.claude/workflows"
    local workflows_dst="${CLAUDE_DIR}/workflows"

    if [[ ! -d "$workflows_src" ]]; then
        log_warn "Workflows directory not found: ${workflows_src}"
        return 0
    fi

    mkdir -p "$workflows_dst"

    local workflow_count=0

    # Copy workflow YAML files
    for workflow_file in "${workflows_src}"/*.yaml "${workflows_src}"/*.yml; do
        if [[ -f "$workflow_file" ]]; then
            local filename=$(basename "$workflow_file")
            cp "$workflow_file" "${workflows_dst}/${filename}"
            log_ok "Installed workflow: ${filename%.yaml}"
            ((workflow_count++))
        fi
    done

    # Copy README if exists
    if [[ -f "${workflows_src}/README.md" ]]; then
        cp "${workflows_src}/README.md" "${workflows_dst}/README.md"
        log_ok "Installed workflows README"
    fi

    log_ok "Workflow definitions installed: ${workflow_count} workflows"
}

# Install agent definitions for agent teams
install_agents() {
    log_section "Installing Agent Definitions"

    local agents_src="${REPO_DIR}/.claude/agents"
    local agents_dst="${CLAUDE_DIR}/agents"

    if [[ ! -d "$agents_src" ]]; then
        log_warn "Agents directory not found: ${agents_src}"
        return 0
    fi

    mkdir -p "$agents_dst"

    local agent_count=0

    for agent_file in "${agents_src}"/*.yaml "${agents_src}"/*.yml; do
        if [[ -f "$agent_file" ]]; then
            local filename=$(basename "$agent_file")
            cp "$agent_file" "${agents_dst}/${filename}"
            log_ok "Installed agent: ${filename%.yaml}"
            ((agent_count++))
        fi
    done

    if [[ -f "${agents_src}/README.md" ]]; then
        cp "${agents_src}/README.md" "${agents_dst}/README.md"
    fi

    log_ok "Agent definitions installed: ${agent_count} agents"
}

# Install team compositions for agent teams
install_teams() {
    log_section "Installing Team Definitions"

    local teams_src="${REPO_DIR}/.claude/teams"
    local teams_dst="${CLAUDE_DIR}/teams"

    if [[ ! -d "$teams_src" ]]; then
        log_warn "Teams directory not found: ${teams_src}"
        return 0
    fi

    mkdir -p "$teams_dst"

    local team_count=0

    for team_file in "${teams_src}"/*.yaml "${teams_src}"/*.yml; do
        if [[ -f "$team_file" ]]; then
            local filename=$(basename "$team_file")
            cp "$team_file" "${teams_dst}/${filename}"
            log_ok "Installed team: ${filename%.yaml}"
            ((team_count++))
        fi
    done

    if [[ -f "${teams_src}/README.md" ]]; then
        cp "${teams_src}/README.md" "${teams_dst}/README.md"
    fi

    log_ok "Team definitions installed: ${team_count} teams"
}

# Install plugins (all standard the project plugins)
install_plugins() {
    log_section "Installing Plugins"

    local plugins=(
        "superpowers@superpowers-marketplace"
        "gopls-lsp@claude-plugins-official"
        "ralph-wiggum@claude-plugins-official"
        "frontend-design@claude-plugins-official"
        "ralph-loop@claude-plugins-official"
    )

    for plugin in "${plugins[@]}"; do
        local plugin_name="${plugin%%@*}"
        log_info "Installing $plugin_name plugin..."
        if claude plugins install "$plugin" 2>/dev/null; then
            log_ok "$plugin_name plugin installed"
        else
            log_warn "Could not install $plugin_name plugin (may already be installed)"
        fi
    done

    # Note: episodic-memory replaced by agentdb MCP server
    log_info "Memory features provided by agentdb MCP server (configured separately)"
}

# Install CodeGraphContext (code graph MCP server — pip package: codegraphcontext)
install_codegraphcontext() {
    log_section "Setting Up CodeGraphContext"

    if command -v cgc &>/dev/null; then
        local cgc_version
        cgc_version=$(cgc --version 2>&1 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' || echo "unknown")
        log_ok "CodeGraphContext: already installed (${cgc_version})"
    else
        # Check Python 3.10+ is available
        if ! command -v python3 &>/dev/null; then
            log_warn "python3 not found — CodeGraphContext requires Python 3.10+"
            log_info "  Install Python 3.10+, then run: pip3 install codegraphcontext"
            return 0
        fi

        local py_version
        py_version=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || echo "0.0")
        local py_major py_minor
        py_major=$(echo "$py_version" | cut -d. -f1)
        py_minor=$(echo "$py_version" | cut -d. -f2)
        if [[ "$py_major" -lt 3 ]] || { [[ "$py_major" -eq 3 ]] && [[ "$py_minor" -lt 10 ]]; }; then
            log_warn "Python ${py_version} found — CodeGraphContext requires 3.10+"
            return 0
        fi

        log_info "CodeGraphContext provides code graph analysis for AI assistants."
        log_info "It requires Python 3.10+ and Docker (for Neo4j graph database)."
        echo ""
        read -rp "Install CodeGraphContext? [y/N] " answer
        if [[ ! "$answer" =~ ^[yY] ]]; then
            log_info "Skipped. Install later: pip3 install codegraphcontext tree-sitter-c-sharp"
            return 0
        fi

        log_info "Installing codegraphcontext via pip..."
        if pip3 install codegraphcontext tree-sitter-c-sharp 2>/dev/null; then
            log_ok "codegraphcontext: installed"
        else
            log_warn "Could not install codegraphcontext"
            log_info "  Install manually: pip3 install codegraphcontext tree-sitter-c-sharp"
            return 0
        fi

        # Verify cgc is on PATH after install
        if ! command -v cgc &>/dev/null; then
            log_warn "cgc not found on PATH after install"
            log_info "  You may need to add Python's bin directory to your PATH"
            return 0
        fi
    fi

    # Set up Neo4j Docker container
    if command -v docker &>/dev/null; then
        if ! docker inspect neo4j &>/dev/null 2>&1; then
            log_info "Creating Neo4j Docker container..."
            if docker run -d \
                --name neo4j \
                --restart unless-stopped \
                -p 7474:7474 -p 7687:7687 \
                -e NEO4J_AUTH=neo4j/password \
                -e NEO4J_PLUGINS='["apoc"]' \
                -v neo4j_data:/data \
                neo4j:5-community &>/dev/null; then
                log_ok "Neo4j: container created and started"
                log_info "Waiting for Neo4j to initialize..."
                sleep 10
            else
                log_warn "Neo4j: could not create container"
                log_info "  Create manually: docker run -d --name neo4j --restart unless-stopped -p 7474:7474 -p 7687:7687 -e NEO4J_AUTH=neo4j/password -v neo4j_data:/data neo4j:5-community"
            fi
        else
            # Ensure restart policy
            local neo4j_policy
            neo4j_policy=$(docker inspect neo4j --format '{{.HostConfig.RestartPolicy.Name}}' 2>/dev/null || echo "")
            if [[ "$neo4j_policy" != "unless-stopped" ]]; then
                docker update --restart unless-stopped neo4j &>/dev/null
                log_ok "Neo4j: restart policy set to unless-stopped"
            fi

            # Start Neo4j if not running
            local neo4j_status
            neo4j_status=$(docker ps --filter name=neo4j --format '{{.Status}}' 2>/dev/null || echo "")
            if [[ -z "$neo4j_status" ]]; then
                docker start neo4j &>/dev/null && log_ok "Neo4j: started" || log_warn "Neo4j: could not start"
            else
                log_ok "Neo4j: running"
            fi
        fi
    else
        log_warn "Docker not found — Neo4j requires Docker"
        log_info "  Install Docker, then re-run install.sh"
    fi

    # Configure CGC to use Neo4j
    local cgc_env="$HOME/.codegraphcontext/.env"
    mkdir -p "$HOME/.codegraphcontext"
    if [[ -f "$cgc_env" ]]; then
        # Set database to neo4j if not already
        if grep -q "^DEFAULT_DATABASE=" "$cgc_env"; then
            sed -i.bak 's/^DEFAULT_DATABASE=.*/DEFAULT_DATABASE=neo4j/' "$cgc_env" && rm -f "${cgc_env}.bak"
        else
            echo "DEFAULT_DATABASE=neo4j" >> "$cgc_env"
        fi
    else
        # Create minimal config — cgc config show will populate defaults on next run
        cat > "$cgc_env" << 'CGCEOF'
DEFAULT_DATABASE=neo4j
CGCEOF
    fi

    # Add Neo4j credentials if not present
    if ! grep -q "^NEO4J_URI=" "$cgc_env" 2>/dev/null; then
        cat >> "$cgc_env" << 'CGCEOF'

# Neo4j connection settings
NEO4J_URI=bolt://localhost:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=password
CGCEOF
        log_ok "Neo4j credentials: added to ${cgc_env}"
    else
        log_ok "Neo4j credentials: already configured"
    fi

    # Configure MCP server in ~/.claude.json
    local claude_json="$HOME/.claude.json"
    if [[ ! -f "$claude_json" ]]; then
        echo '{"mcpServers":{}}' | jq . > "$claude_json"
    fi

    local cgc_path
    cgc_path=$(command -v cgc)

    if jq -e '.mcpServers["CodeGraphContext"]' "$claude_json" &>/dev/null; then
        log_ok "CodeGraphContext MCP server: already configured in ~/.claude.json"
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
            log_warn "Could not configure MCP server — add manually to ~/.claude.json"
        fi
    fi

    log_ok "CodeGraphContext setup complete"
}

# Install testing tools (Pact and Hurl)
install_testing_tools() {
    log_section "Installing Testing Tools"

    # Install Pact CLI for contract testing
    log_info "Installing Pact CLI for contract testing..."
    if has_command pact; then
        log_ok "Pact CLI already installed"
    else
        if npm install -g @pact-foundation/pact-cli 2>/dev/null; then
            log_ok "Pact CLI installed"
        else
            log_warn "Could not install Pact CLI globally (may need sudo)"
            log_info "Install manually: npm install -g @pact-foundation/pact-cli"
        fi
    fi

    log_ok "Testing tools installation complete"
}

# Setup agentdb (remote memory service)
setup_agentdb() {
    log_section "Setting Up AgentDB (Remote Memory)"

    local settings_file="${CLAUDE_DIR}/settings.json"
    # TODO: Update to your AgentDB DNS URL when record is created
    local agentdb_url="YOUR_AGENTDB_URL/sse"

    # Check if already configured
    if grep -q '"agentdb"' "$settings_file" 2>/dev/null; then
        log_ok "agentdb: already configured in settings"
        return 0
    fi

    echo ""
    log_info "AgentDB provides persistent memory across Claude sessions."
    log_info "Service URL: ${agentdb_url}"
    echo ""

    # Try to get API key from AWS Secrets Manager
    local api_key=""
    if has_command aws; then
        log_info "Attempting to retrieve API key from AWS Secrets Manager..."
        api_key=$(aws secretsmanager get-secret-value \
            --secret-id agentdb-dev-api-key \
            --region us-east-1 \
            --query 'SecretString' \
            --output text 2>/dev/null | jq -r '.apiKey' 2>/dev/null || echo "")
    fi

    if [[ -z "$api_key" ]]; then
        log_warn "Could not retrieve API key automatically."
        log_info "You need the 'agentdb-dev-read-api-key' IAM policy attached to your user."
        log_info "Or get the key manually: ./scripts/get-api-key.sh (in agentdb repo)"
        echo ""
        read -sp "Enter AgentDB API Key (or press Enter to skip): " input_api_key
        echo ""
        api_key="$input_api_key"
    fi

    if [[ -z "$api_key" ]]; then
        log_warn "Skipping agentdb configuration (no API key)"
        log_info "To add later, run: ./scripts/install.sh --configure-agentdb"
        return 0
    fi

    # Add to settings.json using jq
    if has_command jq; then
        local temp_file=$(mktemp)
        jq --arg url "$agentdb_url" --arg key "$api_key" \
            '.mcpServers["agentdb"] = {
                "url": $url,
                "transport": "sse",
                "headers": { "X-Api-Key": $key }
            }' "$settings_file" > "$temp_file"
        mv "$temp_file" "$settings_file"
        log_ok "agentdb configured in settings.json"
    else
        log_warn "jq not found - please add agentdb manually to ${settings_file}"
        log_info "Configuration:"
        cat <<EOF
    "agentdb": {
      "url": "${agentdb_url}",
      "transport": "sse",
      "headers": {
        "X-Api-Key": "${api_key}"
      }
    }
EOF
    fi

    # Seed anti-patterns after AgentDB setup
    if [[ -f "${REPO_DIR}/scripts/seed-anti-patterns.ts" ]]; then
        log_info "Seeding anti-patterns into AgentDB..."
        npx tsx "${REPO_DIR}/scripts/seed-anti-patterns.ts" 2>/dev/null && \
            log_ok "Anti-patterns seeded" || \
            log_warn "Could not seed anti-patterns (AgentDB may not be reachable)"
    fi
}

# Create or update settings.json
configure_settings() {
    log_section "Configuring Settings"

    local settings_file="${CLAUDE_DIR}/settings.json"
    local settings_template="${REPO_DIR}/templates/settings.json.template"

    # Create settings template if it doesn't exist in repo
    if [[ ! -f "$settings_template" ]]; then
        log_info "Using default settings template"
        mkdir -p "$(dirname "$settings_template")"
        cat > "$settings_template" <<'EOF'
{
  "env": {
    "CLAUDE_CODE_USE_BEDROCK": "1",
    "AWS_DEFAULT_REGION": "us-east-1",
    "AWS_REGION": "us-east-1",
    "ANTHROPIC_MODEL": "global.anthropic.claude-opus-4-6-v1",
    "ANTHROPIC_SMALL_FAST_MODEL": "us.anthropic.claude-haiku-4-5-20251001-v1:0",
    "CLAUDE_CODE_MAX_OUTPUT_TOKENS": "16384",
    "DISABLE_PROMPT_CACHING": "0",
    "ANTHROPIC_MAX_RETRIES": "5",
    "MAX_THINKING_TOKENS": "1024"
  },
  "permissions": {
    "allow": [
      "Bash",
      "WebFetch",
      "Write",
      "Edit",
      "MultiEdit",
      "Read",
      "Glob",
      "Grep",
      "LS",
      "Task",
      "ExitPlanMode",
      "NotebookEdit",
      "TodoWrite",
      "BashOutput",
      "KillBash",
      "mcp__agentdb__*",
      "mcp__chrome-devtools__*",
      "mcp__playwright__*",
      "mcp__contentful-mcp__*",
      "Skill(superpowers:*)"
    ],
    "deny": [
      "Bash(rm -rf /)"
    ]
  },
  "model": "global.anthropic.claude-opus-4-6-v1",
  "enableAllProjectMcpServers": true,
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": []
      },
      {
        "matcher": "Write|Edit|MultiEdit",
        "hooks": []
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "python3 ~/.claude/hooks/post-command.py"
          }
        ]
      },
      {
        "matcher": "Write|Edit|MultiEdit",
        "hooks": []
      },
      {
        "matcher": "SlashCommand",
        "hooks": [
          {
            "type": "command",
            "command": "CLAUDE_HOOK_TYPE=post python3 ~/.claude/hooks/workflow-pattern-trainer.py"
          }
        ]
      }
    ],
    "Stop": [],
    "SessionEnd": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 ~/.claude/hooks/session-history-sync.py"
          }
        ]
      }
    ]
  },
  "enabledPlugins": {
    "superpowers@superpowers-marketplace": true
  },
  "includeCoAuthoredBy": true
}
EOF
    fi

    if [[ -f "$settings_file" ]]; then
        log_warn "Settings file already exists: ${settings_file}"
        read -p "Overwrite? (y/N): " confirm
        if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
            log_info "Keeping existing settings"
            return 0
        fi
        # Backup existing
        cp "$settings_file" "${settings_file}.backup.$(date +%Y%m%d_%H%M%S)"
        log_info "Backed up existing settings"
    fi

    # Copy template
    cp "$settings_template" "$settings_file"
    log_ok "Settings configured"
}

# Copy CLAUDE.md template to user's home for reference
setup_claude_md() {
    log_section "Setting Up Global CLAUDE.md"

    local template="${REPO_DIR}/CLAUDE.md.template"
    local target="${CLAUDE_DIR}/CLAUDE.md"

    if [[ -f "$target" ]]; then
        log_warn "Global CLAUDE.md already exists"
        read -p "Append agents instructions? (y/N): " confirm
        if [[ "$confirm" == "y" || "$confirm" == "Y" ]]; then
            echo "" >> "$target"
            echo "# Platform Agents Integration" >> "$target"
            echo "$(cat "$template")" >> "$target"
            log_ok "Project Agents instructions appended"
        fi
    else
        cp "$template" "$target"
        log_ok "Global CLAUDE.md created"
    fi
}

# Install parent CLAUDE.md to project root
setup_parent_claude_md() {
    log_section "Setting Up Parent CLAUDE.md"

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

    if [[ -f "$target" ]]; then
        # Check if it's managed by agents (has our footer)
        if grep -q "Managed by agents" "$target" 2>/dev/null; then
            log_info "Updating existing parent CLAUDE.md..."
            cp "$target" "${target}.backup.$(date +%Y%m%d_%H%M%S)"
            cp "$template" "$target"
            log_ok "Parent CLAUDE.md updated at ${target}"
        else
            log_warn "Parent CLAUDE.md exists but is not managed by agents"
            read -p "Replace with agents template? Existing will be backed up. (y/N): " confirm
            if [[ "$confirm" == "y" || "$confirm" == "Y" ]]; then
                cp "$target" "${target}.backup.$(date +%Y%m%d_%H%M%S)"
                cp "$template" "$target"
                log_ok "Parent CLAUDE.md replaced at ${target}"
                log_info "Backup saved with .backup.* extension"
            else
                log_info "Keeping existing parent CLAUDE.md"
            fi
        fi
    else
        cp "$template" "$target"
        log_ok "Parent CLAUDE.md created at ${target}"
    fi
}

# Show status of current setup
show_status() {
    log_section "Current Setup Status"

    # Check Claude CLI
    if has_command claude; then
        log_ok "Claude Code CLI: installed"
    else
        log_warn "Claude Code CLI: not installed"
    fi

    # Check MCP servers
    echo ""
    log_info "MCP Servers:"
    if claude mcp list &>/dev/null; then
        claude mcp list
    else
        log_warn "Could not list MCP servers"
    fi

    # Check commands
    echo ""
    log_info "Installed Commands:"
    local cmd_count=0
    for cmd in "${CLAUDE_DIR}/commands"/*.md; do
        if [[ -f "$cmd" ]]; then
            echo "  - $(basename "${cmd%.md}")"
            ((cmd_count++))
        fi
    done
    log_info "Total: ${cmd_count} commands"

    # Check hooks
    echo ""
    log_info "Installed Hooks:"
    local hook_count=0
    for hook in "${CLAUDE_DIR}/hooks"/*.py "${CLAUDE_DIR}/hooks"/*.sh; do
        if [[ -f "$hook" ]]; then
            echo "  - $(basename "$hook")"
            ((hook_count++))
        fi
    done
    log_info "Total: ${hook_count} hooks"

    # Check .env
    echo ""
    if [[ -f "$ENV_FILE" ]]; then
        log_ok "Credentials file: ${ENV_FILE}"
    else
        log_warn "Credentials file: not found (run install.sh to configure)"
    fi
}

# Uninstall
uninstall() {
    log_section "Uninstalling Project Agents Configuration"

    read -p "This will remove the project workflow commands and hooks. Continue? (y/N): " confirm
    if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
        log_info "Aborted"
        exit 0
    fi

    # Remove commands
    for cmd in plan groom work validate audit next bug issue fix-pipeline; do
        rm -f "${CLAUDE_DIR}/commands/${cmd}.md"
    done
    log_ok "Commands removed"

    # Remove hooks
    rm -f "${CLAUDE_DIR}/hooks/workflow-pattern-trainer.py"
    log_ok "Hooks removed"

    # Remove MCP servers
    for mcp in jira-mcp bitbucket-mcp; do
        claude mcp remove "$mcp" 2>/dev/null || true
    done
    log_ok "Project MCP servers removed (core servers retained)"

    log_ok "Uninstall complete"
}

# Show usage
usage() {
    cat <<EOF
Project Agents - Developer Setup Script

Usage:
  ${0##*/}                    Interactive setup
  ${0##*/} --check            Check current setup status
  ${0##*/} --update-commands  Update workflow commands only
  ${0##*/} --configure-repos  Configure and clone project repositories
  ${0##*/} --configure-agentdb Configure agentdb only
  ${0##*/} --uninstall        Remove the project configuration

Options:
  --check              Show current setup status
  --update-commands    Update workflow commands only
  --configure-repos    Configure project repositories (PROJECT_REPOS in .env)
                       and clone any missing repositories
  --configure-agentdb  Configure agentdb remote memory service
  --uninstall          Remove project-specific configuration
  --help               Show this help message

Multi-Repo Setup:
  The install script can clone all the project project repositories for new developers.
  Configure PROJECT_REPOS in .env or use --configure-repos to set up interactively.

  Default repositories:
    lambda-functions, frontend-app, auth-service, sdk, project-docs, test-data

Documentation:
  README.md          Overview and quick start
  docs/MCP-SETUP.md  Detailed MCP server setup

EOF
    exit 0
}

# Wire tokf PreToolUse hook into Claude Code settings
wire_tokf_hook() {
    log_section "Wiring tokf Hook"

    if ! command -v tokf &>/dev/null; then
        log_warn "tokf not installed — skipping hook wiring"
        log_info "  Install via: brew install mpecan/tokf/tokf"
        return 0
    fi

    local tokf_version
    tokf_version=$(tokf --version 2>/dev/null || echo 'unknown')
    log_ok "tokf installed ($tokf_version)"

    # Verify the hook subcommand exists in this version
    if ! tokf hook handle --help &>/dev/null; then
        log_warn "tokf hook command not available in version $tokf_version"
        return 0
    fi

    # Install the Claude Code PreToolUse hook globally (idempotent)
    local install_output
    if install_output=$(tokf hook install --global 2>&1); then
        log_ok "tokf PreToolUse hook registered in ~/.claude/settings.json"
    else
        log_warn "tokf hook install failed:"
        log_warn "  $install_output"
        log_info "  Manual setup: tokf hook install --global"
        return 0
    fi

    # Verify hook is actually in settings.json
    if grep -q 'tokf' "${CLAUDE_DIR}/settings.json" 2>/dev/null; then
        log_ok "tokf hook verified in settings.json"
    else
        log_warn "tokf hook install succeeded but hook not found in settings.json"
        log_info "  Check: grep tokf ~/.claude/settings.json"
    fi

    # Install the project skill filters (npx tsx output compression)
    local tokf_filter_src="${REPO_DIR}/config/tokf-filters"
    local tokf_filter_dest
    tokf_filter_dest="$(tokf info 2>/dev/null | grep '\[user\]' | head -1 | sed 's/.*\] //' | sed 's/ (.*$//')"
    if [[ -d "$tokf_filter_src" ]] && [[ -n "$tokf_filter_dest" ]]; then
        cp -r "$tokf_filter_src"/* "$tokf_filter_dest/" 2>/dev/null || true
        tokf cache clear &>/dev/null || true
        local filter_count
        filter_count=$(find "$tokf_filter_dest/skills" -name '*.toml' 2>/dev/null | wc -l | tr -d ' ')
        log_ok "Installed ${filter_count} tokf filters to ${tokf_filter_dest}/skills/"
    fi
}

# Offer Ollama local model setup
offer_ollama_setup() {
    local ollama_script="${REPO_DIR}/scripts/setup-ollama.sh"
    local alias_script="${REPO_DIR}/scripts/setup-ollama-aliases.sh"
    if [[ ! -x "$ollama_script" ]]; then
        return 0
    fi

    if [[ "$(uname)" != "Darwin" ]]; then
        return 0
    fi

    echo ""
    log_info "Local LLM inference (Ollama) is available for Apple Silicon."
    log_info "This installs coding models (Qwen3-Coder, Qwen2.5-Coder) accessible"
    log_info "via OpenAI-compatible API at localhost:11434/v1 for Claude Code proxy."
    echo ""
    read -rp "  Set up Ollama with local coding models? [y/N] " answer
    if [[ "$answer" =~ ^[yY] ]]; then
        "$ollama_script" --required
        # Create Claude-format model aliases (required for dispatch-local.py)
        if [[ -x "$alias_script" ]]; then
            log_info "Creating Claude Code model aliases..."
            "$alias_script"
        fi
    else
        log_info "Skipped. Run later with: ./scripts/setup-ollama.sh"
    fi
}

# Update commands only
update_commands() {
    log_section "Updating Workflow Commands"
    install_commands
    install_hooks
    install_global_hook_config
    setup_project_hooks
    install_skills
    install_workflows
    install_agents
    install_teams
    install_scripts
    install_model_routing
    install_config_files
    log_ok "Commands, hooks, skills, workflows, agents, teams, and scripts updated"
}

# Configure agentdb only
configure_agentdb_only() {
    log_section "Configuring AgentDB"
    setup_agentdb
    log_ok "AgentDB configuration complete"
}

# Configure and clone project repos only
configure_repos_only() {
    log_section "Configuring Project Repositories"
    configure_project_repos
    setup_project_repos
    log_ok "Project repository configuration complete"
}

# Update tool permissions in settings.json
update_tool_permissions() {
    log_section "Updating Tool Permissions"

    local permissions_script="${REPO_DIR}/scripts/update-permissions.sh"

    if [[ -x "$permissions_script" ]]; then
        "$permissions_script" --claude-dir "$CLAUDE_DIR"
    else
        log_warn "Permissions script not found or not executable: ${permissions_script}"
        log_info "Skipping automatic permission updates"
    fi
}

# Install smart hook loader
install_smart_hooks() {
    log_section "Installing Hook Loader"

    local hooks_dst="${CLAUDE_DIR}/hooks"

    # hook-loader.py is the entrypoint for all hooks in settings.json.
    # It reads manifest.json for per-hook config (timeout, circuit breaker)
    # and delegates to the actual hook file.
    # Claude Code's matcher system handles routing — hook-loader adds
    # circuit breaker (auto-disable after N failures) and time budget.

    # Resolve source location — flat hooks/ preferred, legacy .claude/hooks/ fallback.
    local smart_hooks_src="${BASE_CONFIG_DIR}/hooks"
    if [[ ! -d "$smart_hooks_src" ]]; then
        smart_hooks_src="${BASE_CONFIG_DIR}/.claude/hooks"
    fi

    # Copy hook loader and manifest
    cp "${smart_hooks_src}/hook-loader.py" "${hooks_dst}/"
    chmod +x "${hooks_dst}/hook-loader.py"
    cp "${smart_hooks_src}/manifest.json" "${hooks_dst}/"

    # Copy emergency disable script
    if [[ -f "${smart_hooks_src}/EMERGENCY-DISABLE.sh" ]]; then
        cp "${smart_hooks_src}/EMERGENCY-DISABLE.sh" "${hooks_dst}/"
        chmod +x "${hooks_dst}/EMERGENCY-DISABLE.sh"
    fi

    log_ok "Hook Loader installed with manifest"

    # --- Verify every hook in manifest has a file on disk ---
    log_section "Verifying Hook Installation"

    local missing=0
    local verified=0

    # Extract hook file names from manifest.json
    local hook_files
    hook_files=$(jq -r '.hooks // {} | to_entries[] | .value.file' "${hooks_dst}/manifest.json" 2>/dev/null)

    for hook_file in $hook_files; do
        if [[ -f "${hooks_dst}/${hook_file}" ]]; then
            log_ok "Verified: ${hook_file}"
            verified=$((verified + 1))
        else
            log_warn "MISSING hook file: ${hook_file} (referenced in manifest.json)"
            missing=$((missing + 1))
        fi
    done

    # Also verify hook-loader.py itself
    if [[ -f "${hooks_dst}/hook-loader.py" ]]; then
        log_ok "Verified: hook-loader.py (entrypoint)"
    else
        log_error "MISSING: hook-loader.py — all hooks will fail"
        missing=$((missing + 1))
    fi

    if [[ $missing -gt 0 ]]; then
        log_error "$missing hook file(s) missing — check base-agents/.claude/hooks/"
    else
        log_ok "All $verified hooks verified"
    fi
}

# Main installation
main() {
    echo ""
    echo -e "${CYAN}╔═══════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║   Project Agents - Claude Code Setup Script    ║${NC}"
    echo -e "${CYAN}╚═══════════════════════════════════════════╝${NC}"
    echo ""

    # Migrate legacy PROJECT_ROOT to PROJECT_ROOT
    migrate_project_root_env "$ENV_FILE"

    check_prerequisites
    install_brew_packages
    install_claude_cli
    setup_claude_directory
    install_model_routing
    install_config_files
    install_core_mcp_servers
    # setup_mcp_repos  # DEPRECATED: Skills now call REST APIs directly
    setup_project_repos
    setup_project_mcp_servers
    install_commands
    install_hooks
    install_statusline
    install_global_hook_config
    setup_project_hooks
    install_skills
    install_workflows
    install_agents
    install_teams
    install_scripts
    install_plugins
    install_testing_tools
    install_codegraphcontext
    configure_settings
    setup_agentdb
    setup_claude_md
    setup_parent_claude_md
    update_tool_permissions
    wire_tokf_hook
    offer_ollama_setup
    install_smart_hooks

    log_section "Setup Complete!"
    echo ""
    log_ok "Project Agents environment is ready"
    echo ""
    log_info "Available workflow commands:"
    echo "  /plan <EPIC>      - Create planning document from Epic"
    echo "  /groom <EPIC>     - Create Jira issues from planning doc"
    echo "  /work <ISSUE>     - Implement issue through PR merge"
    echo "  /validate <ISSUE> - Validate deployed changes"
    echo "  /next             - Find next priority issue"
    echo "  /bug <desc>       - Report and create bug issue"
    echo "  /issue <desc>     - Create new issue"
    echo "  /audit <URL>      - Run UI compliance audit"
    echo ""
    log_info "Autonomous workflow (ralph-wiggum plugin):"
    echo "  /ralph-wiggum:ralph-loop \"<prompt>\" --completion-promise \"<text>\""
    echo "  /cancel-ralph     - Stop running ralph loop"
    echo ""
    log_info "PROJ-specific ralph loop:"
    echo "  /ralph-wiggum:ralph-loop \"\$(cat .claude/ralph-prompts/jira-workflow.md)\" \\"
    echo "    --max-iterations 20 --completion-promise \"BACKLOG CLEAR\""
    echo ""
    log_info "Start Claude Code in your project directory:"
    echo "  cd /path/to/your/project"
    echo "  claude"
    echo ""
    log_info "Then try: /next"
    echo ""
}

# Parse arguments
case "${1:-}" in
    --check|--status)
        show_status
        ;;
    --update-commands)
        update_commands
        ;;
    --configure-repos)
        configure_repos_only
        ;;
    --configure-agentdb)
        configure_agentdb_only
        ;;
    --uninstall)
        uninstall
        ;;
    --setup-ollama)
        "${REPO_DIR}/scripts/setup-ollama.sh" "${@:2}"
        # Also create aliases after setup
        if [[ -x "${REPO_DIR}/scripts/setup-ollama-aliases.sh" ]]; then
            "${REPO_DIR}/scripts/setup-ollama-aliases.sh"
        fi
        ;;
    --help|-h)
        usage
        ;;
    *)
        main
        ;;
esac
