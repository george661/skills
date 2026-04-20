/**
 * Node Detail Panel - Slide-out panel for node execution details
 */

class NodeDetailPanel {
    constructor() {
        this.panel = null;
        this.currentNode = null;
        this.init();
    }

    init() {
        // Listen for node-click events
        window.addEventListener('node-click', (e) => {
            this.show(e.detail);
        });
    }

    async show(node) {
        this.currentNode = node;

        // Fetch full node details
        const response = await fetch(`/api/workflows/${node.id.split(':')[0]}/nodes/${node.id}`);
        const nodeDetails = await response.json();

        this.render(nodeDetails);
    }

    render(node) {
        // Remove existing panel if any
        if (this.panel) {
            this.panel.remove();
        }

        // Check if retry history exists for this node
        const retryHistory = window.retryHistoryStore && window.retryHistoryStore[node.node_name];
        const hasRetryHistory = retryHistory && retryHistory.length > 0;

        // Create panel
        this.panel = document.createElement('div');
        this.panel.className = 'node-detail-panel';
        const isInterrupted = node.status === 'interrupted';
        this.panel.innerHTML = `
            <div class="panel-header">
                <h3>${this.escapeHtml(node.node_name)}</h3>
                <button class="panel-close-btn" aria-label="Close panel">×</button>
            </div>
            <div class="panel-content">
                <div class="panel-tabs">
                    ${isInterrupted ? '<button class="tab-btn active" data-tab="approval">Approval</button>' : ''}
                    <button class="tab-btn ${!isInterrupted ? 'active' : ''}" data-tab="config">Config</button>
                    <button class="tab-btn" data-tab="logs">Logs</button>
                    <button class="tab-btn" data-tab="output">Output</button>
                    <button class="tab-btn" data-tab="artifacts">Artifacts</button>
                    ${node.content_hash ? '<button class="tab-btn" data-tab="checkpoint">Checkpoint</button>' : ''}
                    ${node.error ? '<button class="tab-btn error-tab" data-tab="error">Error</button>' : ''}
                    ${hasRetryHistory ? '<button class="tab-btn" data-tab="retry-history">Retry History</button>' : ''}
                </div>
                <div class="panel-body">
                    ${isInterrupted ? `
                        <div class="tab-content active" data-tab="approval">
                            ${this.renderApproval(node)}
                        </div>
                    ` : ''}
                    <div class="tab-content ${!isInterrupted ? 'active' : ''}" data-tab="config">
                        ${this.renderConfig(node)}
                    </div>
                    <div class="tab-content" data-tab="logs">
                        ${this.renderLogs(node)}
                    </div>
                    <div class="tab-content" data-tab="output">
                        ${this.renderOutput(node)}
                    </div>
                    <div class="tab-content" data-tab="artifacts">
                        ${this.renderArtifacts(node)}
                    </div>
                    ${node.content_hash ? `
                        <div class="tab-content" data-tab="checkpoint">
                            ${this.renderCheckpoint(node)}
                        </div>
                    ` : ''}
                    ${node.error ? `
                        <div class="tab-content" data-tab="error">
                            ${this.renderError(node)}
                        </div>
                    ` : ''}
                    ${hasRetryHistory ? `
                        <div class="tab-content" data-tab="retry-history">
                            ${this.renderRetryHistory(node, retryHistory)}
                        </div>
                    ` : ''}
                </div>
            </div>
        `;

        document.body.appendChild(this.panel);

        // Animate in
        setTimeout(() => {
            this.panel.classList.add('visible');
        }, 10);

        // Setup event listeners
        this.panel.querySelector('.panel-close-btn').addEventListener('click', () => this.hide());
        this.panel.querySelectorAll('.tab-btn').forEach(btn => {
            btn.addEventListener('click', (e) => this.switchTab(e.target.dataset.tab));
        });

        // Setup gate approval button listeners
        const approveBtn = this.panel.querySelector('.gate-btn-approve');
        const rejectBtn = this.panel.querySelector('.gate-btn-reject');
        if (approveBtn) {
            approveBtn.addEventListener('click', () => this.handleGateDecision('approve', node));
        }
        if (rejectBtn) {
            rejectBtn.addEventListener('click', () => this.handleGateDecision('reject', node));
        }

        // Click outside to close
        this.panel.addEventListener('click', (e) => {
            if (e.target === this.panel) {
                this.hide();
            }
        });
    }

    renderConfig(node) {
        const duration = node.started_at && node.finished_at 
            ? this.calculateDuration(node.started_at, node.finished_at)
            : 'N/A';

        return `
            <div class="config-section">
                <div class="config-item">
                    <span class="config-label">Status:</span>
                    <span class="config-value status-${node.status}">${this.escapeHtml(node.status)}</span>
                </div>
                <div class="config-item">
                    <span class="config-label">Duration:</span>
                    <span class="config-value">${duration}</span>
                </div>
                ${node.model ? `
                    <div class="config-item">
                        <span class="config-label">Model:</span>
                        <span class="config-value">${this.escapeHtml(node.model)}</span>
                    </div>
                ` : ''}
                ${(node.tokens_input != null || node.tokens_output != null || node.tokens_cache != null) ? `
                    <div class="config-item">
                        <span class="config-label">Tokens (Input):</span>
                        <span class="config-value">${(node.tokens_input || 0).toLocaleString()}</span>
                    </div>
                    <div class="config-item">
                        <span class="config-label">Tokens (Output):</span>
                        <span class="config-value">${(node.tokens_output || 0).toLocaleString()}</span>
                    </div>
                    <div class="config-item">
                        <span class="config-label">Tokens (Cache):</span>
                        <span class="config-value">${(node.tokens_cache || 0).toLocaleString()}</span>
                    </div>
                    <div class="config-item">
                        <span class="config-label">Total Tokens:</span>
                        <span class="config-value">${((node.tokens_input || 0) + (node.tokens_output || 0) + (node.tokens_cache || 0)).toLocaleString()}</span>
                    </div>
                ` : node.tokens ? `
                    <div class="config-item">
                        <span class="config-label">Tokens:</span>
                        <span class="config-value">${node.tokens.toLocaleString()}</span>
                    </div>
                ` : ''}
                ${node.cost ? `
                    <div class="config-item">
                        <span class="config-label">Cost:</span>
                        <span class="config-value">$${node.cost.toFixed(4)}</span>
                    </div>
                ` : ''}
                ${node.inputs ? `
                    <div class="config-item">
                        <span class="config-label">Inputs:</span>
                        <pre class="json-viewer">${JSON.stringify(node.inputs, null, 2)}</pre>
                    </div>
                ` : ''}
            </div>
        `;
    }

    renderLogs(node) {
        if (!node.chat_messages || node.chat_messages.length === 0) {
            return '<p class="empty-state">No logs available</p>';
        }

        return `
            <div class="logs-container">
                ${node.chat_messages.map(msg => `
                    <div class="log-entry">
                        <div class="log-role">${this.escapeHtml(msg.role)}</div>
                        <div class="log-content">${this.escapeHtml(msg.content)}</div>
                    </div>
                `).join('')}
            </div>
        `;
    }

    renderOutput(node) {
        if (!node.outputs) {
            return '<p class="empty-state">No output available</p>';
        }

        return `
            <pre class="json-viewer">${JSON.stringify(node.outputs, null, 2)}</pre>
        `;
    }

    renderArtifacts(node) {
        if (!node.artifacts || node.artifacts.length === 0) {
            return '<p class="empty-state">No artifacts</p>';
        }

        return `
            <div class="artifacts-list">
                ${node.artifacts.map(artifact => `
                    <div class="artifact-item">
                        <div class="artifact-name">
                            ${artifact.url ?
                                `<a href="${this.escapeHtml(artifact.url)}" target="_blank" rel="noopener noreferrer">${this.escapeHtml(artifact.name)}</a>` :
                                this.escapeHtml(artifact.name)
                            }
                        </div>
                        <div class="artifact-type">${this.escapeHtml(artifact.artifact_type)}</div>
                        ${artifact.path ? `<div class="artifact-path">${this.escapeHtml(artifact.path)}</div>` : ''}
                    </div>
                `).join('')}
            </div>
        `;
    }

    renderCheckpoint(node) {
        if (!node.content_hash) {
            return '<p class="empty-state">No checkpoint data</p>';
        }

        // Initially render a loading state, then fetch checkpoint comparison data
        setTimeout(() => this.loadCheckpointData(node), 0);

        return `
            <div class="checkpoint-container">
                <div class="checkpoint-hash">
                    <label>Content Hash:</label>
                    <div class="content-hash-display" title="${this.escapeHtml(node.content_hash)}">
                        ${this.escapeHtml(node.content_hash.substring(0, 16))}...
                        <button class="copy-hash-btn" data-hash="${this.escapeHtml(node.content_hash)}" title="Copy full hash">📋</button>
                    </div>
                </div>
                <div class="checkpoint-versions" id="checkpoint-versions-${node.id}">
                    <p>Loading version comparison...</p>
                </div>
            </div>
        `;
    }

    async loadCheckpointData(node) {
        try {
            const response = await fetch(`/api/workflows/${node.run_id}/nodes/${node.id}/checkpoint`);
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }
            const data = await response.json();

            const container = document.getElementById(`checkpoint-versions-${node.id}`);
            if (!container) return;  // Panel was closed

            const hashedMismatches = data.mismatches && data.mismatches.length > 0;

            container.innerHTML = `
                <h4>Input Versions</h4>
                ${hashedMismatches ? '<p class="checkpoint-warning">⚠️ Version mismatches detected - re-execution may be triggered on resume</p>' : ''}
                <table class="checkpoint-table">
                    <thead>
                        <tr>
                            <th>Channel Key</th>
                            <th>Checkpoint Version</th>
                            <th>Current Version</th>
                            <th>Status</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${Object.entries(data.input_versions || {}).map(([key, checkpointVer]) => {
                            const currentVer = data.current_versions[key];
                            const mismatch = data.mismatches.find(m => m.channel_key === key);
                            const status = mismatch ? mismatch.status : 'match';
                            const statusClass = status === 'match' ? 'version-match' : status === 'mismatch' ? 'version-mismatch' : 'version-missing';

                            return `
                                <tr class="${statusClass}">
                                    <td>${this.escapeHtml(key)}</td>
                                    <td>${checkpointVer}</td>
                                    <td>${currentVer !== undefined ? currentVer : '<em>missing</em>'}</td>
                                    <td><span class="status-badge status-${status}">${status}</span></td>
                                </tr>
                            `;
                        }).join('')}
                        ${data.mismatches.filter(m => m.status === 'extra').map(m => `
                            <tr class="version-extra">
                                <td>${this.escapeHtml(m.channel_key)}</td>
                                <td><em>not in checkpoint</em></td>
                                <td>${m.current_version}</td>
                                <td><span class="status-badge status-extra">extra</span></td>
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
            `;

            // Add copy hash button handler
            container.closest('.checkpoint-container').querySelector('.copy-hash-btn')?.addEventListener('click', (e) => {
                const hash = e.target.dataset.hash;
                navigator.clipboard.writeText(hash);
                e.target.textContent = '✓';
                setTimeout(() => { e.target.textContent = '📋'; }, 1500);
            });

        } catch (err) {
            const container = document.getElementById(`checkpoint-versions-${node.id}`);
            if (container) {
                container.innerHTML = `<p class="error-state">Failed to load checkpoint comparison: ${this.escapeHtml(err.message)}</p>`;
            }
        }
    }

    renderApproval(node) {
        const username = localStorage.getItem('dag_username') || '';
        const runId = node.run_id;
        const nodeName = node.node_name;

        return `
            <div class="gate-approval-panel">
                <div class="gate-info">
                    <h4>Gate: ${this.escapeHtml(nodeName)}</h4>
                    <span class="gate-status-badge">Awaiting Approval</span>
                </div>

                <div class="gate-form" data-run-id="${runId}" data-node-name="${nodeName}">
                    <div class="form-group">
                        <label for="gate-username">Your Name</label>
                        <input
                            type="text"
                            id="gate-username"
                            class="gate-username"
                            value="${this.escapeHtml(username)}"
                            placeholder="Your name"
                        />
                    </div>

                    <div class="form-group">
                        <label for="gate-comment">Comment (optional)</label>
                        <textarea
                            id="gate-comment"
                            class="gate-comment"
                            placeholder="Add a comment..."
                            maxlength="1000"
                        ></textarea>
                    </div>

                    <div class="gate-actions">
                        <button class="gate-btn gate-btn-approve" data-action="approve">
                            ✓ Approve
                        </button>
                        <button class="gate-btn gate-btn-reject" data-action="reject">
                            ✗ Reject
                        </button>
                    </div>

                    <div class="gate-feedback hidden"></div>
                </div>
            </div>
        `;
    }

    renderError(node) {
        const logTail = node.chat_messages && node.chat_messages.length > 0 ?
            node.chat_messages.slice(-20).map(msg => `[${msg.role}] ${msg.content}`).join('\n') :
            'No log messages available';

        return `
            <div class="error-container">
                <pre class="error-text">${this.escapeHtml(node.error)}</pre>
                <details style="margin-top: 1rem;">
                    <summary style="cursor: pointer; font-weight: 600; margin-bottom: 0.5rem;">Last 20 log lines</summary>
                    <pre class="error-text">${this.escapeHtml(logTail)}</pre>
                </details>
            </div>
        `;
    }

    async handleGateDecision(action, node) {
        const usernameInput = this.panel.querySelector('.gate-username');
        const commentInput = this.panel.querySelector('.gate-comment');
        const feedback = this.panel.querySelector('.gate-feedback');
        const approveBtn = this.panel.querySelector('.gate-btn-approve');
        const rejectBtn = this.panel.querySelector('.gate-btn-reject');

        const username = usernameInput.value.trim();
        const comment = commentInput.value.trim();

        // Save username to localStorage
        if (username) {
            localStorage.setItem('dag_username', username);
        }

        // Show loading state
        approveBtn.disabled = true;
        rejectBtn.disabled = true;
        feedback.textContent = 'Processing...';
        feedback.className = 'gate-feedback';
        feedback.classList.remove('hidden');

        try {
            const runId = node.run_id;
            const nodeName = node.node_name;
            const response = await fetch(`/api/workflows/${runId}/gates/${nodeName}/${action}`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    decided_by: username || null,
                    comment: comment || null,
                }),
            });

            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.detail || 'Failed to process gate decision');
            }

            const result = await response.json();

            // Show success feedback
            feedback.textContent = `Gate ${action}d successfully by ${result.decided_by}`;
            feedback.classList.add('success');

            // Refresh the workflow view after 1 second
            setTimeout(() => {
                this.hide();
                // Trigger workflow refresh if available
                if (window.app && window.app.refreshCurrentView) {
                    window.app.refreshCurrentView();
                }
            }, 1000);

        } catch (error) {
            // Show error feedback
            feedback.textContent = `Error: ${error.message}`;
            feedback.classList.add('error');
            approveBtn.disabled = false;
            rejectBtn.disabled = false;
        }
    }

    switchTab(tabName) {
        // Update tab buttons
        this.panel.querySelectorAll('.tab-btn').forEach(btn => {
            if (btn.dataset.tab === tabName) {
                btn.classList.add('active');
            } else {
                btn.classList.remove('active');
            }
        });

        // Update tab content
        this.panel.querySelectorAll('.tab-content').forEach(content => {
            if (content.dataset.tab === tabName) {
                content.classList.add('active');
            } else {
                content.classList.remove('active');
            }
        });
    }

    hide() {
        if (this.panel) {
            this.panel.classList.remove('visible');
            setTimeout(() => {
                this.panel.remove();
                this.panel = null;
            }, 300);
        }
    }

    calculateDuration(startedAt, finishedAt) {
        const start = new Date(startedAt);
        const end = new Date(finishedAt);
        const durationMs = end - start;
        const seconds = Math.floor(durationMs / 1000);
        const minutes = Math.floor(seconds / 60);
        
        if (minutes > 0) {
            return `${minutes}m ${seconds % 60}s`;
        }
        return `${seconds}s`;
    }

    renderRetryHistory(node, retryHistory) {
        if (!retryHistory || retryHistory.length === 0) {
            return '<p class="empty-state">No retry attempts recorded for this node.</p>';
        }

        const rows = retryHistory.map((retry, index) => `
            <div class="retry-history-item">
                <div class="retry-attempt">
                    <strong>Attempt ${retry.attempt}/${retry.max_attempts}</strong>
                </div>
                <div class="retry-delay">
                    Delay: ${(retry.delay_ms / 1000).toFixed(1)}s
                </div>
                <div class="retry-error">
                    ${this.escapeHtml(retry.last_error || 'No error message')}
                </div>
                <div class="retry-timestamp">
                    ${new Date(retry.timestamp).toLocaleString()}
                </div>
            </div>
        `).join('');

        return `
            <div class="retry-history-list">
                <h4>Retry Attempts (${retryHistory.length})</h4>
                ${rows}
            </div>
        `;
    }

    escapeHtml(unsafe) {
        if (unsafe === null || unsafe === undefined) return '';
        return String(unsafe)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }
}

// Initialize on load
window.addEventListener('DOMContentLoaded', () => {
    window.nodeDetailPanel = new NodeDetailPanel();
});
