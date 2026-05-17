/**
 * Pending workspace changes UI component.
 * 
 * Displays pending workspace edits (modified and new files) with per-file
 * and bulk actions. Piggybacks on app.js pollInterval (3s) for refresh.
 */

window.PendingChanges = (function() {
    'use strict';

    // Active mount state
    let state = {
        runId: null,
        container: null,
        toastTimeout: null
    };

    /**
     * Mount pending changes section for a run.
     * Does initial fetch but does NOT start polling (app.js calls refresh).
     */
    function mount(container, runId) {
        if (!container || !runId) return;
        
        state.container = container;
        state.runId = runId;
        
        // Initial fetch
        refresh(container);
    }

    /**
     * Refresh pending changes data and re-render.
     * Called by app.js pollInterval every 3s.
     */
    async function refresh(container) {
        if (!container || !state.runId) return;
        
        try {
            const resp = await fetch(`/api/runs/${state.runId}/pending-changes`);
            if (!resp.ok) {
                console.error('Failed to fetch pending changes:', resp.status);
                container.setAttribute('hidden', '');
                return;
            }
            
            const data = await resp.json();
            render(container, data.changes);
        } catch (err) {
            console.error('Error fetching pending changes:', err);
            container.setAttribute('hidden', '');
        }
    }

    /**
     * Unmount: clear container and reset state.
     */
    function unmount(container) {
        if (container) {
            container.innerHTML = '';
            container.setAttribute('hidden', '');
        }
        if (state.toastTimeout) {
            clearTimeout(state.toastTimeout);
            state.toastTimeout = null;
        }
        state.runId = null;
        state.container = null;
    }

    /**
     * Render the pending changes UI.
     */
    function render(container, changes) {
        if (!changes || changes.length === 0) {
            container.setAttribute('hidden', '');
            container.innerHTML = '';
            return;
        }

        container.removeAttribute('hidden');

        const html = `
            <div class="pending-changes-header">
                <h3>Pending workspace changes</h3>
                <div class="pending-changes-bulk-actions">
                    <button class="pending-changes-bulk-btn" data-action="apply-all">Apply all</button>
                    <button class="pending-changes-bulk-btn" data-action="discard-all">Discard all</button>
                </div>
            </div>
            <div class="pending-changes-list">
                ${changes.map(change => renderChange(change)).join('')}
            </div>
        `;

        container.innerHTML = html;

        // Attach event listeners
        container.querySelectorAll('.pending-changes-apply-btn').forEach(btn => {
            btn.addEventListener('click', () => handleApply(btn.dataset.workspacePath, changes));
        });
        container.querySelectorAll('.pending-changes-discard-btn').forEach(btn => {
            btn.addEventListener('click', () => handleDiscard(btn.dataset.workspacePath));
        });
        container.querySelectorAll('.pending-changes-commit-btn').forEach(btn => {
            btn.addEventListener('click', () => handleApplyCommit(btn.dataset.workspacePath, changes));
        });
        container.querySelectorAll('[data-action="apply-all"]').forEach(btn => {
            btn.addEventListener('click', () => handleApplyAll(changes));
        });
        container.querySelectorAll('[data-action="discard-all"]').forEach(btn => {
            btn.addEventListener('click', () => handleDiscardAll(changes));
        });
    }

    /**
     * Render a single change as a <details> element.
     */
    function renderChange(change) {
        const sourcePath = change.source_path || 'new file (no manifest entry)';
        const diffLines = change.diff ? change.diff.split('\n').length : 0;
        const kindLabel = change.kind === 'modified' ? 'Modified' : 'New';

        const diffHtml = change.diff ? renderDiff(change.diff) : '<p class="pending-changes-no-diff">New file (no diff)</p>';

        return `
            <details class="pending-changes-row" data-workspace-path="${escapeHtml(change.workspace_path)}">
                <summary class="pending-changes-summary">
                    <span class="pending-changes-kind-badge pending-changes-kind-${change.kind}">${kindLabel}</span>
                    <span class="pending-changes-path">${escapeHtml(change.workspace_path)}</span>
                    <span class="pending-changes-source">${escapeHtml(sourcePath)}</span>
                </summary>
                <div class="pending-changes-content">
                    <div class="pending-changes-diff-container">
                        ${diffHtml}
                    </div>
                    <div class="pending-changes-actions">
                        <button class="pending-changes-discard-btn" data-workspace-path="${escapeHtml(change.workspace_path)}">Discard</button>
                        <button class="pending-changes-apply-btn" data-workspace-path="${escapeHtml(change.workspace_path)}">Apply to source</button>
                        <button class="pending-changes-commit-btn" data-workspace-path="${escapeHtml(change.workspace_path)}">Apply + commit</button>
                    </div>
                </div>
            </details>
        `;
    }

    /**
     * Render unified diff with per-line color coding.
     */
    function renderDiff(diff) {
        const lines = diff.split('\n');
        const htmlLines = lines.map(line => {
            let className = 'diff-context';
            if (line.startsWith('+') && !line.startsWith('+++')) {
                className = 'diff-add';
            } else if (line.startsWith('-') && !line.startsWith('---')) {
                className = 'diff-del';
            } else if (line.startsWith('@@')) {
                className = 'diff-hunk';
            } else if (line.startsWith('+++') || line.startsWith('---')) {
                className = 'diff-fileheader';
            }
            return `<span class="${className}">${escapeHtml(line)}</span>`;
        });
        return `<pre class="pending-changes-diff">${htmlLines.join('\n')}</pre>`;
    }

    /**
     * Handle apply action (with modal for new files).
     */
    async function handleApply(workspacePath, changes) {
        const change = changes.find(c => c.workspace_path === workspacePath);
        if (!change) return;

        let targetPath = null;

        // For new files, prompt for target path
        if (change.kind === 'new') {
            const suggested = change.suggested_target_path || '';
            targetPath = prompt(`Target path for new file "${workspacePath}":`, suggested);
            if (!targetPath) {
                return; // Cancelled
            }
        }

        // Confirmation modal for large diffs
        if (change.diff && change.diff.split('\n').length > 50) {
            const confirmed = window.ConfirmDialog ? 
                await window.ConfirmDialog.confirm({
                    title: 'Large diff',
                    message: `This change has ${change.diff.split('\n').length} lines. Apply anyway?`,
                    confirmLabel: 'Apply',
                    cancelLabel: 'Cancel'
                }) :
                confirm(`This change has ${change.diff.split('\n').length} lines. Apply anyway?`);
            
            if (!confirmed) return;
        }

        try {
            const body = {
                workspace_path: workspacePath,
                action: 'apply'
            };
            if (targetPath) {
                body.target_path = targetPath;
            }

            const resp = await fetch(`/api/runs/${state.runId}/pending-changes/apply`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(body)
            });

            if (!resp.ok) {
                const errData = await resp.json();
                showToast(`Apply failed: ${errData.detail || resp.statusText}`, 'error');
                return;
            }

            const result = await resp.json();
            if (result.applied) {
                showToast(`Applied to ${result.source_path}`, 'success');
                // Trigger refresh
                if (state.container) {
                    refresh(state.container);
                }
            } else {
                showToast(`Apply failed: ${result.error || 'Unknown error'}`, 'error');
            }
        } catch (err) {
            console.error('Apply error:', err);
            showToast('Apply failed: Network error', 'error');
        }
    }

    /**
     * Handle apply + commit action.
     */
    async function handleApplyCommit(workspacePath, changes) {
        const change = changes.find(c => c.workspace_path === workspacePath);
        if (!change) return;

        let targetPath = null;

        // For new files, prompt for target path
        if (change.kind === 'new') {
            const suggested = change.suggested_target_path || '';
            targetPath = prompt(`Target path for new file "${workspacePath}":`, suggested);
            if (!targetPath) {
                return; // Cancelled
            }
        }

        // Confirmation modal for large diffs
        if (change.diff && change.diff.split('\n').length > 50) {
            const confirmed = window.ConfirmDialog ?
                await window.ConfirmDialog.confirm({
                    title: 'Large diff',
                    message: `This change has ${change.diff.split('\n').length} lines. Apply and commit anyway?`,
                    confirmLabel: 'Apply + commit',
                    cancelLabel: 'Cancel'
                }) :
                confirm(`This change has ${change.diff.split('\n').length} lines. Apply and commit anyway?`);

            if (!confirmed) return;
        }

        try {
            const body = {
                workspace_path: workspacePath,
                action: 'apply',
                commit: true
            };
            if (targetPath) {
                body.target_path = targetPath;
            }

            const resp = await fetch(`/api/runs/${state.runId}/pending-changes/apply`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(body)
            });

            if (!resp.ok) {
                const errData = await resp.json();
                showToast(`Apply + commit failed: ${errData.detail || resp.statusText}`, 'error');
                return;
            }

            const result = await resp.json();
            if (result.applied) {
                if (result.commit_sha) {
                    // Success: committed to source
                    const shortSha = result.commit_sha.substring(0, 7);
                    showToast(`Committed ${shortSha} to source`, 'success');

                    // Show push-manually message
                    const sourceDir = result.source_path.split('/').slice(0, -1).join('/');
                    setTimeout(() => {
                        showToast(`Now push manually from ${sourceDir}/`, 'info');
                    }, 2000);
                } else if (result.error) {
                    // Partial success: file applied but commit failed
                    showToast(`Applied to ${result.source_path}; commit failed: ${result.error}`, 'warning');
                } else {
                    // Applied but no commit (shouldn't happen with commit=true)
                    showToast(`Applied to ${result.source_path}`, 'success');
                }
                // Trigger refresh
                if (state.container) {
                    refresh(state.container);
                }
            } else {
                showToast(`Apply + commit failed: ${result.error || 'Unknown error'}`, 'error');
            }
        } catch (err) {
            console.error('Apply + commit error:', err);
            showToast('Apply + commit failed: Network error', 'error');
        }
    }

    /**
     * Handle discard action.
     */
    async function handleDiscard(workspacePath) {
        const confirmed = window.ConfirmDialog ?
            await window.ConfirmDialog.confirm({
                title: 'Discard change',
                message: `Discard changes to "${workspacePath}"?`,
                confirmLabel: 'Discard',
                cancelLabel: 'Cancel'
            }) :
            confirm(`Discard changes to "${workspacePath}"?`);

        if (!confirmed) return;

        try {
            const resp = await fetch(`/api/runs/${state.runId}/pending-changes/apply`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    workspace_path: workspacePath,
                    action: 'discard'
                })
            });

            if (!resp.ok) {
                const errData = await resp.json();
                showToast(`Discard failed: ${errData.detail || resp.statusText}`, 'error');
                return;
            }

            showToast('Change discarded', 'success');
            if (state.container) {
                refresh(state.container);
            }
        } catch (err) {
            console.error('Discard error:', err);
            showToast('Discard failed: Network error', 'error');
        }
    }

    /**
     * Handle apply-all bulk action.
     */
    async function handleApplyAll(changes) {
        const confirmed = window.ConfirmDialog ?
            await window.ConfirmDialog.confirm({
                title: 'Apply all changes',
                message: `Apply ${changes.length} pending change(s)?`,
                confirmLabel: 'Apply all',
                cancelLabel: 'Cancel'
            }) :
            confirm(`Apply ${changes.length} pending change(s)?`);

        if (!confirmed) return;

        // Apply each in sequence (simple approach)
        for (const change of changes) {
            // Skip new files in bulk apply (need target paths)
            if (change.kind === 'new') {
                showToast(`Skipped new file: ${change.workspace_path} (needs target path)`, 'info');
                continue;
            }
            await handleApply(change.workspace_path, changes);
        }
    }

    /**
     * Handle discard-all bulk action.
     */
    async function handleDiscardAll(changes) {
        const confirmed = window.ConfirmDialog ?
            await window.ConfirmDialog.confirm({
                title: 'Discard all changes',
                message: `Discard ${changes.length} pending change(s)?`,
                confirmLabel: 'Discard all',
                cancelLabel: 'Cancel'
            }) :
            confirm(`Discard ${changes.length} pending change(s)?`);

        if (!confirmed) return;

        for (const change of changes) {
            await handleDiscard(change.workspace_path);
        }
    }

    /**
     * Show inline toast notification.
     */
    function showToast(message, type = 'info') {
        if (!state.container) return;

        // Remove existing toast
        const existing = state.container.querySelector('.pending-changes-toast');
        if (existing) existing.remove();

        const toast = document.createElement('div');
        toast.className = `pending-changes-toast pending-changes-toast-${type}`;
        toast.textContent = message;
        state.container.appendChild(toast);

        // Auto-dismiss after 3s
        if (state.toastTimeout) clearTimeout(state.toastTimeout);
        state.toastTimeout = setTimeout(() => {
            toast.remove();
            state.toastTimeout = null;
        }, 3000);
    }

    /**
     * Escape HTML entities.
     */
    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    return {
        mount,
        refresh,
        unmount
    };
})();
