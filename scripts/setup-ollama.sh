#!/bin/bash
#
# Ollama Setup Script for Apple Silicon Macs
# Installs Ollama, configures for optimal Metal GPU performance,
# and pulls best-in-class open source coding/reasoning models.
#
# Designed for: Mac M3 Max 48GB (works on any Apple Silicon)
#
# Models pulled (from config/ollama-models.json):
#   Coding:    qwen3-coder:30b (primary), qwen2.5-coder:7b (fast), gemma4:26b (experimental)
#   Embedding: nomic-embed-text
#
# Integration: Exposes OpenAI-compatible API at http://localhost:11434/v1
#              for Claude Code proxy inference via model-routing.json
#
# Usage:
#   ./scripts/setup-ollama.sh                # Full interactive setup
#   ./scripts/setup-ollama.sh --required     # Only required models (non-interactive)
#   ./scripts/setup-ollama.sh --all          # All models including optional
#   ./scripts/setup-ollama.sh --check        # Check status only
#   ./scripts/setup-ollama.sh --update       # Update Ollama + refresh models
#   ./scripts/setup-ollama.sh --configure    # Only write config (no model pulls)
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
CONFIG_FILE="${REPO_DIR}/config/ollama-models.json"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m'

log_info()    { echo -e "${BLUE}[INFO]${NC} $*"; }
log_ok()      { echo -e "${GREEN}[OK]${NC} $*"; }
log_warn()    { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error()   { echo -e "${RED}[ERROR]${NC} $*" >&2; }
log_section() { echo -e "\n${CYAN}${BOLD}=== $* ===${NC}\n"; }

# ─── Hardware Detection ───────────────────────────────────────────────────────

detect_hardware() {
    if [[ "$(uname)" != "Darwin" ]]; then
        log_error "This script is designed for macOS with Apple Silicon."
        exit 1
    fi

    CHIP=$(sysctl -n machdep.cpu.brand_string 2>/dev/null || echo "Unknown")
    RAM_BYTES=$(sysctl -n hw.memsize 2>/dev/null || echo "0")
    RAM_GB=$((RAM_BYTES / 1073741824))
    CORES=$(sysctl -n hw.ncpu 2>/dev/null || echo "0")
    PERF_CORES=$(system_profiler SPHardwareDataType 2>/dev/null | grep "Total Number of Cores" | sed 's/.*: //' || echo "unknown")

    if ! sysctl -n machdep.cpu.brand_string 2>/dev/null | grep -qi "apple"; then
        log_error "Apple Silicon required. Detected: ${CHIP}"
        exit 1
    fi

    log_section "Hardware Detected"
    echo -e "  Chip:     ${BOLD}${CHIP}${NC}"
    echo -e "  RAM:      ${BOLD}${RAM_GB} GB${NC}"
    echo -e "  Cores:    ${BOLD}${PERF_CORES}${NC}"
    echo ""

    if [[ $RAM_GB -lt 16 ]]; then
        log_error "Minimum 16GB RAM required. Detected: ${RAM_GB}GB"
        exit 1
    elif [[ $RAM_GB -lt 32 ]]; then
        log_warn "32GB+ recommended for 32B models. Will pull 8B variants only."
        MODEL_TIER="small"
    else
        MODEL_TIER="full"
    fi
}

# ─── Ollama Install / Update ─────────────────────────────────────────────────

install_or_update_ollama() {
    log_section "Ollama Installation"

    if command -v ollama &>/dev/null; then
        local current_version
        current_version=$(ollama --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' || echo "unknown")
        log_info "Ollama installed: v${current_version}"

        # Check for updates via Homebrew
        if command -v brew &>/dev/null; then
            local latest_version
            latest_version=$(brew info ollama --json=v2 2>/dev/null | jq -r '.formulae[0].versions.stable // "unknown"' 2>/dev/null || echo "unknown")

            if [[ "$current_version" != "$latest_version" && "$latest_version" != "unknown" ]]; then
                log_info "Update available: v${current_version} -> v${latest_version}"
                log_info "Upgrading Ollama via Homebrew..."
                brew upgrade ollama 2>/dev/null || brew install ollama
                log_ok "Ollama upgraded to v${latest_version}"
            else
                log_ok "Ollama is up to date (v${current_version})"
            fi
        fi
    else
        log_info "Installing Ollama..."
        if command -v brew &>/dev/null; then
            brew install ollama
        else
            log_error "Homebrew not found. Install from: https://ollama.com/download/mac"
            exit 1
        fi

        if ! command -v ollama &>/dev/null; then
            log_error "Ollama installation failed."
            exit 1
        fi
        log_ok "Ollama installed successfully"
    fi
}

# ─── Ollama Service Management ───────────────────────────────────────────────

ensure_ollama_running() {
    log_section "Starting Ollama Service"

    # Check if already running
    if curl -sf http://localhost:11434/api/tags &>/dev/null; then
        log_ok "Ollama service is already running"
        return 0
    fi

    # Stop any stale processes
    if pgrep -x "ollama" &>/dev/null; then
        log_info "Stopping stale Ollama process..."
        pkill -x ollama 2>/dev/null || true
        sleep 2
    fi

    # Start via app or service
    if [[ -d "/Applications/Ollama.app" ]]; then
        log_info "Starting Ollama.app..."
        open -a Ollama
    elif command -v brew &>/dev/null; then
        log_info "Starting via brew services..."
        brew services start ollama 2>/dev/null || ollama serve &>/dev/null &
    else
        log_info "Starting ollama serve..."
        ollama serve &>/dev/null &
    fi

    # Wait for service to be ready
    local attempts=0
    local max_attempts=20
    while ! curl -sf http://localhost:11434/api/tags &>/dev/null; do
        attempts=$((attempts + 1))
        if [[ $attempts -ge $max_attempts ]]; then
            log_error "Ollama failed to start after ${max_attempts} attempts."
            log_error "Try manually: ollama serve"
            exit 1
        fi
        printf "  Waiting for Ollama... (%d/%d)\r" "$attempts" "$max_attempts"
        sleep 2
    done
    echo ""
    log_ok "Ollama service is running"
}

# ─── Environment Configuration ───────────────────────────────────────────────

configure_environment() {
    log_section "Configuring Environment"

    # Read performance config from JSON
    if [[ ! -f "$CONFIG_FILE" ]]; then
        log_warn "Config file not found: ${CONFIG_FILE}"
        log_info "Using default configuration"
        return
    fi

    # Create launchd override for Ollama environment variables
    local plist_dir="${HOME}/Library/LaunchAgents"
    local env_plist="${plist_dir}/com.ollama.env.plist"
    mkdir -p "$plist_dir"

    # Extract env vars from config
    local env_vars
    env_vars=$(jq -r '.performance.apple_silicon.env | to_entries[] | "\(.key)=\(.value)"' "$CONFIG_FILE" 2>/dev/null)

    if [[ -z "$env_vars" ]]; then
        log_warn "No performance config found in ${CONFIG_FILE}"
        return
    fi

    # Write to shell profile (zsh is default on modern macOS)
    local shell_rc="${HOME}/.zshrc"
    [[ -f "${HOME}/.bash_profile" && ! -f "$shell_rc" ]] && shell_rc="${HOME}/.bash_profile"

    # Remove old Ollama config block if present
    if [[ -f "$shell_rc" ]]; then
        sed -i '' '/# --- Ollama Configuration (managed by base-agents) ---/,/# --- End Ollama Configuration ---/d' "$shell_rc" 2>/dev/null || true
    fi

    {
        echo ""
        echo "# --- Ollama Configuration (managed by base-agents) ---"
        echo "$env_vars" | while IFS='=' read -r key val; do
            echo "export ${key}=\"${val}\""
        done
        echo "export OLLAMA_HOST=\"127.0.0.1:11434\""
        echo "# --- End Ollama Configuration ---"
    } >> "$shell_rc"

    # Also export for current session
    while IFS='=' read -r key val; do
        export "${key}=${val}"
    done <<< "$env_vars"
    export OLLAMA_HOST="127.0.0.1:11434"

    log_ok "Environment configured in ${shell_rc}"
    log_info "Env vars: OLLAMA_FLASH_ATTENTION, OLLAMA_KV_CACHE_TYPE, OLLAMA_NUM_PARALLEL, OLLAMA_MAX_LOADED_MODELS"
}

# ─── Model Management ────────────────────────────────────────────────────────

pull_model() {
    local model_name="$1"
    local model_desc="$2"
    local model_size="$3"

    # Check if already pulled
    if ollama list 2>/dev/null | grep -q "^${model_name}"; then
        log_ok "Already pulled: ${model_name} ${DIM}(${model_desc})${NC}"
        return 0
    fi

    echo -e "  ${BLUE}Pulling${NC} ${BOLD}${model_name}${NC} ${DIM}(~${model_size}GB - ${model_desc})${NC}"
    if ollama pull "$model_name" 2>&1; then
        log_ok "Pulled: ${model_name}"
        return 0
    else
        log_warn "Failed to pull: ${model_name} - skipping"
        return 1
    fi
}

pull_models() {
    local mode="${1:-interactive}"

    if [[ ! -f "$CONFIG_FILE" ]]; then
        log_error "Model config not found: ${CONFIG_FILE}"
        exit 1
    fi

    log_section "Pulling Models"

    local pulled=0
    local failed=0
    local skipped=0

    # Process each category
    for category in coding reasoning embedding general; do
        local count
        count=$(jq -r ".models.${category} | length" "$CONFIG_FILE" 2>/dev/null || echo "0")
        [[ "$count" -eq 0 ]] && continue

        local category_upper
        category_upper=$(echo "$category" | tr '[:lower:]' '[:upper:]')
        echo -e "\n  ${CYAN}${BOLD}${category_upper} MODELS${NC}"

        for i in $(seq 0 $((count - 1))); do
            local name desc size_gb ram_req required tier
            name=$(jq -r ".models.${category}[$i].name" "$CONFIG_FILE")
            desc=$(jq -r ".models.${category}[$i].description" "$CONFIG_FILE")
            size_gb=$(jq -r ".models.${category}[$i].size_gb" "$CONFIG_FILE")
            ram_req=$(jq -r ".models.${category}[$i].ram_required_gb" "$CONFIG_FILE")
            required=$(jq -r ".models.${category}[$i].required" "$CONFIG_FILE")
            tier=$(jq -r ".models.${category}[$i].tier" "$CONFIG_FILE")

            # Cloud models don't need local RAM, just register
            if [[ "$tier" == "cloud" ]]; then
                if [[ "$mode" == "required" && "$required" == "false" ]]; then
                    ((skipped++))
                    continue
                fi
                if [[ "$mode" == "interactive" && "$required" == "false" ]]; then
                    echo ""
                    read -rp "  Register ${name}? ${desc} [y/N] " answer
                    if [[ ! "$answer" =~ ^[yY] ]]; then
                        ((skipped++))
                        continue
                    fi
                fi
                echo -e "  ${BLUE}Registering${NC} ${BOLD}${name}${NC} ${DIM}(cloud model - no local download)${NC}"
                if pull_model "$name" "$desc" "0"; then
                    ((pulled++))
                else
                    log_warn "Cloud model ${name} registration skipped (may need API key)"
                    ((skipped++))
                fi
                continue
            fi

            # Skip models that exceed RAM
            if [[ $ram_req -gt $RAM_GB ]]; then
                log_warn "Skipping ${name} (needs ${ram_req}GB, have ${RAM_GB}GB)"
                ((skipped++))
                continue
            fi

            # For small tier (< 32GB RAM), skip 32B+ models
            if [[ "$MODEL_TIER" == "small" && "$tier" == "primary" ]]; then
                log_warn "Skipping ${name} (insufficient RAM for primary tier)"
                ((skipped++))
                continue
            fi

            # Handle optional models based on mode
            if [[ "$required" == "false" ]]; then
                case "$mode" in
                    required)
                        ((skipped++))
                        continue
                        ;;
                    interactive)
                        echo ""
                        read -rp "  Pull ${name} (~${size_gb}GB)? ${desc} [y/N] " answer
                        if [[ ! "$answer" =~ ^[yY] ]]; then
                            ((skipped++))
                            continue
                        fi
                        ;;
                    all)
                        ;; # pull everything
                esac
            fi

            if pull_model "$name" "$desc" "$size_gb"; then
                ((pulled++))
            else
                ((failed++))
            fi
        done
    done

    echo ""
    log_section "Model Pull Summary"
    echo -e "  Pulled:  ${GREEN}${pulled}${NC}"
    echo -e "  Skipped: ${YELLOW}${skipped}${NC}"
    echo -e "  Failed:  ${RED}${failed}${NC}"
}

# ─── Model Routing Integration ───────────────────────────────────────────────

install_model_routing() {
    log_section "Updating Model Routing Config"

    local routing_config="${REPO_DIR}/config/model-routing.json"
    if [[ ! -f "$routing_config" ]]; then
        log_warn "model-routing.json not found at ${routing_config}"
        return
    fi

    # Check if local models section already exists
    if jq -e '.models.local' "$routing_config" &>/dev/null; then
        log_ok "Local model routing already configured"
        return
    fi

    # Add local model configuration to routing
    local tmp_file
    tmp_file=$(mktemp)

    jq --arg coding "$(jq -r '.proxy.default_coding_model' "$CONFIG_FILE")" \
       --arg fast "$(jq -r '.proxy.default_fast_model' "$CONFIG_FILE")" \
       --arg embedding "$(jq -r '.proxy.default_embedding_model' "$CONFIG_FILE")" \
       --arg base_url "$(jq -r '.proxy.openai_compat_url' "$CONFIG_FILE")" \
       '
       .models.local = {
         "coding": $coding,
         "fast": $fast,
         "embedding": $embedding,
         "base_url": $base_url
       } |
       .defaults.local_coding = "local.coding" |
       .defaults.local_fast = "local.fast"
       ' "$routing_config" > "$tmp_file"

    mv "$tmp_file" "$routing_config"
    log_ok "Added local model routing to model-routing.json"
    log_info "Local models accessible via OpenAI-compatible API at http://localhost:11434/v1"
}

# ─── Status Check ────────────────────────────────────────────────────────────

check_status() {
    log_section "Ollama Status"

    # Installation
    if command -v ollama &>/dev/null; then
        local version
        version=$(ollama --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' || echo "unknown")
        log_ok "Installed: v${version}"
    else
        log_error "Not installed"
        return 1
    fi

    # Service
    if curl -sf http://localhost:11434/api/tags &>/dev/null; then
        log_ok "Service: running"
    else
        log_warn "Service: not running"
    fi

    # Models
    echo ""
    echo -e "  ${BOLD}Installed Models:${NC}"
    if ollama list 2>/dev/null | tail -n +2 | while read -r line; do
        echo "    $line"
    done; then
        true
    else
        echo "    (none or service not running)"
    fi

    # Running models
    echo ""
    echo -e "  ${BOLD}Running Models:${NC}"
    if ollama ps 2>/dev/null | tail -n +2 | while read -r line; do
        echo "    $line"
    done; then
        true
    else
        echo "    (none)"
    fi

    # Config
    echo ""
    echo -e "  ${BOLD}Environment:${NC}"
    for var in OLLAMA_HOST OLLAMA_FLASH_ATTENTION OLLAMA_KV_CACHE_TYPE OLLAMA_NUM_PARALLEL OLLAMA_MAX_LOADED_MODELS OLLAMA_KEEP_ALIVE; do
        local val="${!var:-unset}"
        echo "    ${var}=${val}"
    done

    # OpenAI compat endpoint
    echo ""
    if curl -sf http://localhost:11434/v1/models &>/dev/null; then
        log_ok "OpenAI-compatible API: http://localhost:11434/v1"
    else
        log_warn "OpenAI-compatible API: not responding"
    fi
}

# ─── Cleanup Old Config ──────────────────────────────────────────────────────

cleanup_legacy() {
    # Remove old Ollama config artifacts from previous script versions
    local legacy_files=(
        "${HOME}/.ollama/models.json"
        "${HOME}/ollama-models"
        "${HOME}/ollama-env"
    )

    for f in "${legacy_files[@]}"; do
        if [[ -e "$f" ]]; then
            log_info "Removing legacy: ${f}"
            rm -rf "$f"
        fi
    done

    # Clean old .bash_profile entries
    if [[ -f "${HOME}/.bash_profile" ]]; then
        if grep -q "OLLAMA_METAL=1" "${HOME}/.bash_profile" 2>/dev/null; then
            log_info "Cleaning legacy OLLAMA_METAL from .bash_profile (Metal is automatic now)"
            sed -i '' '/# Ollama Performance Configuration/,/export OLLAMA_METAL=1/d' "${HOME}/.bash_profile" 2>/dev/null || true
        fi
    fi
}

# ─── Main ─────────────────────────────────────────────────────────────────────

usage() {
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  --required     Pull only required models (non-interactive)"
    echo "  --all          Pull all models including optional"
    echo "  --check        Check current status only"
    echo "  --update       Update Ollama and refresh models"
    echo "  --configure    Only write config (no model pulls)"
    echo "  --help         Show this help"
    echo ""
    echo "Models pulled (from config/ollama-models.json):"
    echo "  Coding:    qwen3-coder:30b (primary), qwen2.5-coder:7b (fast), gemma4:26b (experimental)"
    echo "  Embedding: nomic-embed-text"
    echo ""
    echo "After setup, models are available via:"
    echo "  CLI:  ollama run qwen3:32b"
    echo "  API:  curl http://localhost:11434/v1/chat/completions"
}

main() {
    local mode="interactive"

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --required) mode="required" ;;
            --all)      mode="all" ;;
            --check)    detect_hardware; check_status; exit 0 ;;
            --update)   mode="update" ;;
            --configure) mode="configure" ;;
            --help|-h)  usage; exit 0 ;;
            *)
                log_error "Unknown option: $1"
                usage
                exit 1
                ;;
        esac
        shift
    done

    echo -e "${BOLD}"
    echo "  ┌──────────────────────────────────────────────────────────────┐"
    echo "  │  Ollama Setup for Apple Silicon                             │"
    echo "  │  Coding: Qwen3-Coder 30B, Qwen2.5-Coder 7B, Gemma4 26B    │"
    echo "  │  Embedding: nomic-embed-text                                │"
    echo "  │  API: OpenAI-compatible at localhost:11434/v1               │"
    echo "  └──────────────────────────────────────────────────────────────┘"
    echo -e "${NC}"

    detect_hardware
    cleanup_legacy
    install_or_update_ollama
    configure_environment

    if [[ "$mode" != "configure" ]]; then
        ensure_ollama_running
        pull_models "$mode"
        install_model_routing
    fi

    echo ""
    log_section "Setup Complete"
    echo -e "  ${BOLD}Quick Start:${NC}"
    echo -e "    ollama run qwen3:32b              ${DIM}# Best coding model${NC}"
    echo -e "    ollama run qwen2.5-coder:32b      ${DIM}# Purpose-built coder${NC}"
    echo -e "    ollama run deepseek-r1:32b        ${DIM}# Reasoning model${NC}"
    echo ""
    echo -e "  ${BOLD}OpenAI-Compatible API:${NC}"
    echo -e "    curl http://localhost:11434/v1/chat/completions \\"
    echo -e "      -H 'Content-Type: application/json' \\"
    echo -e "      -d '{\"model\": \"qwen3:32b\", \"messages\": [{\"role\": \"user\", \"content\": \"Hello\"}]}'"
    echo ""
    echo -e "  ${BOLD}Claude Code Integration:${NC}"
    echo -e "    Model routing config updated at: ${REPO_DIR}/config/model-routing.json"
    echo -e "    Local models accessible under ${BOLD}models.local${NC} key"
    echo ""

    if [[ "$mode" != "configure" ]]; then
        echo -e "  ${BOLD}Installed Models:${NC}"
        ollama list 2>/dev/null || true
    fi

    echo ""
    echo -e "  ${DIM}Restart your shell or run: source ~/.zshrc${NC}"
}

main "$@"
