#!/bin/bash
# Memory Optimizer Hook
# Checks system memory usage when thresholds are exceeded
# Usage: Pre-task (check) and Post-task (cleanup)
# Note: Cloud memory operations require AgentDB REST skills

set -euo pipefail

HOOK_TYPE="${1:-pre}"
MEMORY_THRESHOLD_HIGH=80
MEMORY_THRESHOLD_MEDIUM=70
LOG_DIR="${HOME}/.claude/memory-optimization"
LOG_FILE="${LOG_DIR}/memory-optimizer.log"

mkdir -p "$LOG_DIR"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG_FILE"
}

get_memory_usage() {
    # Check system memory usage
    local memory_pct=0

    if [[ "$(uname)" == "Darwin" ]]; then
        # macOS: Use vm_stat
        local pages_free pages_active pages_inactive pages_wired page_size total_pages
        page_size=$(pagesize)
        pages_free=$(vm_stat | awk '/Pages free/ {gsub(/\./, "", $3); print $3}')
        pages_active=$(vm_stat | awk '/Pages active/ {gsub(/\./, "", $3); print $3}')
        pages_inactive=$(vm_stat | awk '/Pages inactive/ {gsub(/\./, "", $3); print $3}')
        pages_wired=$(vm_stat | awk '/Pages wired down/ {gsub(/\./, "", $4); print $4}')

        local used=$((pages_active + pages_wired))
        local total=$((pages_free + pages_active + pages_inactive + pages_wired))

        if [[ $total -gt 0 ]]; then
            memory_pct=$((used * 100 / total))
        fi
    else
        # Linux: Use /proc/meminfo
        local mem_total mem_available
        mem_total=$(grep MemTotal /proc/meminfo | awk '{print $2}')
        mem_available=$(grep MemAvailable /proc/meminfo | awk '{print $2}')

        if [[ $mem_total -gt 0 ]]; then
            memory_pct=$(( (mem_total - mem_available) * 100 / mem_total ))
        fi
    fi

    echo "$memory_pct"
}

cleanup_temp_memory() {
    log "Temporary memory cleanup skipped - use AgentDB REST skills for cloud memory operations"
    # Cloud memory operations require AgentDB REST skills:
    # npx tsx .claude/skills/agentdb/list_keys.ts '{"namespace": "${TENANT_NAMESPACE}-temp"}'
    # npx tsx .claude/skills/agentdb/delete.ts '{"namespace": "${TENANT_NAMESPACE}-temp", "key": "..."}'
}

archive_completed() {
    log "Archive operation skipped - use AgentDB REST skills for cloud memory operations"
    # Cloud memory archiving requires AgentDB REST skills:
    # npx tsx .claude/skills/agentdb/list_keys.ts '{"namespace": "${TENANT_NAMESPACE}"}'
    # npx tsx .claude/skills/agentdb/retrieve.ts '{"namespace": "${TENANT_NAMESPACE}", "key": "..."}'
    # npx tsx .claude/skills/agentdb/store.ts '{"namespace": "${TENANT_NAMESPACE}-archive", "key": "...", "value": ...}'
    # npx tsx .claude/skills/agentdb/delete.ts '{"namespace": "${TENANT_NAMESPACE}", "key": "..."}'
}

compress_memory() {
    log "Memory compression skipped - use AgentDB REST skills for cloud memory operations"
    # Cloud memory compression would require custom AgentDB operations
}

pre_task_check() {
    local memory_usage
    memory_usage=$(get_memory_usage)

    log "Pre-task memory check: ${memory_usage}%"

    if [[ $memory_usage -gt $MEMORY_THRESHOLD_HIGH ]]; then
        log "WARNING: Memory usage ${memory_usage}% exceeds ${MEMORY_THRESHOLD_HIGH}% - running cleanup"
        echo "{\"status\": \"warning\", \"message\": \"Memory at ${memory_usage}%. Running cleanup...\", \"continue\": true}"

        cleanup_temp_memory
        archive_completed
        compress_memory

        local new_usage
        new_usage=$(get_memory_usage)
        log "Post-cleanup memory: ${new_usage}%"
        echo "{\"status\": \"cleaned\", \"before\": $memory_usage, \"after\": $new_usage, \"continue\": true}"
    elif [[ $memory_usage -gt $MEMORY_THRESHOLD_MEDIUM ]]; then
        log "INFO: Memory usage ${memory_usage}% approaching threshold"
        echo "{\"status\": \"ok\", \"message\": \"Memory at ${memory_usage}% - consider cleanup after task\", \"continue\": true}"
    else
        echo "{\"status\": \"ok\", \"message\": \"Memory healthy at ${memory_usage}%\", \"continue\": true}"
    fi
}

post_task_cleanup() {
    local memory_usage
    memory_usage=$(get_memory_usage)

    log "Post-task memory check: ${memory_usage}%"

    if [[ $memory_usage -gt $MEMORY_THRESHOLD_MEDIUM ]]; then
        log "Running post-task cleanup at ${memory_usage}%"
        archive_completed

        if [[ $memory_usage -gt $MEMORY_THRESHOLD_HIGH ]]; then
            cleanup_temp_memory
            compress_memory
        fi

        local new_usage
        new_usage=$(get_memory_usage)
        log "Post-cleanup memory: ${new_usage}%"
        echo "{\"status\": \"cleaned\", \"before\": $memory_usage, \"after\": $new_usage, \"continue\": true}"
    else
        echo "{\"status\": \"ok\", \"memory\": $memory_usage, \"continue\": true}"
    fi
}

case "$HOOK_TYPE" in
    pre|pre-task)
        pre_task_check
        ;;
    post|post-task)
        post_task_cleanup
        ;;
    check)
        echo "{\"memory_usage\": $(get_memory_usage), \"threshold_high\": $MEMORY_THRESHOLD_HIGH, \"threshold_medium\": $MEMORY_THRESHOLD_MEDIUM}"
        ;;
    cleanup)
        cleanup_temp_memory
        archive_completed
        compress_memory
        echo "{\"status\": \"cleanup_complete\"}"
        ;;
    *)
        echo "Usage: $0 {pre|post|check|cleanup}"
        exit 1
        ;;
esac
