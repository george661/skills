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
                    ${node.error ? '<button class="tab-btn error-tab" data-tab="error">Error</button>' : ''}
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
                    ${node.error ? `
                        <div class="tab-content" data-tab="error">
                            ${this.renderError(node)}
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

        // Setup interrupt resume button listeners
        const resumeBtn = this.panel.querySelector('.interrupt-btn-resume');
        const cancelBtn = this.panel.querySelector('.interrupt-btn-cancel');
        if (resumeBtn) {
            resumeBtn.addEventListener('click', () => this.handleInterruptResume(node));
            // Load workflow state on details open
            const stateDetails = this.panel.querySelector('.interrupt-state-section details');
            if (stateDetails) {
                stateDetails.addEventListener('toggle', (e) => {
                    if (e.target.open) {
                        this.loadWorkflowState(node);
                    }
                });
            }
        }
        if (cancelBtn) {
            cancelBtn.addEventListener('click', () => this.hide());
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

    renderApproval(node) {
        // Check if this is an interrupt node (vs gate node)
        const nodeType = node.outputs?.node_type;
        if (nodeType === 'interrupt') {
            return this.renderInterruptResume(node);
        }

        // Existing gate approval logic
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

    renderInterruptResume(node) {
        const username = localStorage.getItem('dag_username') || '';
        const runId = node.run_id;
        const nodeName = node.node_name;
        const message = node.outputs?.message || 'Workflow paused';
        const resumeKey = node.outputs?.resume_key || 'resume_value';
        const channels = node.outputs?.channels || ['terminal'];

        return `
            <div class="interrupt-resume-panel">
                <div class="interrupt-header">
                    <div class="interrupt-icon">⏸</div>
                    <div class="interrupt-info">
                        <h4>${this.escapeHtml(nodeName)}</h4>
                        <p class="interrupt-message">${this.escapeHtml(message)}</p>
                    </div>
                </div>

                <div class="interrupt-channels">
                    ${channels.map(ch => `<span class="channel-badge">${this.escapeHtml(ch)}</span>`).join('')}
                </div>

                <div class="interrupt-form" data-run-id="${runId}" data-node-name="${nodeName}" data-resume-key="${this.escapeHtml(resumeKey)}">
                    <div class="form-group">
                        <label for="interrupt-username">Your Name</label>
                        <input
                            type="text"
                            id="interrupt-username"
                            class="interrupt-username"
                            value="${this.escapeHtml(username)}"
                            placeholder="Your name"
                        />
                    </div>

                    <div class="form-group">
                        <label for="interrupt-resume-value">
                            Resume Value (${this.escapeHtml(resumeKey)})
                            <span class="field-hint">Supports JSON, string, or number</span>
                        </label>
                        <textarea
                            id="interrupt-resume-value"
                            class="interrupt-resume-value"
                            placeholder='{"approved": true}'
                            rows="3"
                        ></textarea>
                    </div>

                    <div class="form-group">
                        <label for="interrupt-comment">Comment (optional)</label>
                        <textarea
                            id="interrupt-comment"
                            class="interrupt-comment"
                            placeholder="Add a comment..."
                            maxlength="1000"
                            rows="2"
                        ></textarea>
                    </div>

                    <div class="interrupt-state-section">
                        <details>
                            <summary class="state-summary">View Workflow State Snapshot</summary>
                            <div class="state-viewer" id="interrupt-state-viewer">
                                <div class="loading">Loading state...</div>
                            </div>
                        </details>
                    </div>

                    <div class="interrupt-actions">
                        <button class="interrupt-btn interrupt-btn-resume" data-action="resume">
                            ▶ Resume
                        </button>
                        <button class="interrupt-btn interrupt-btn-cancel">
                            Cancel
                        </button>
                    </div>

                    <div class="interrupt-feedback hidden"></div>
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

    async handleInterruptResume(node) {
        const usernameInput = this.panel.querySelector('.interrupt-username');
        const valueInput = this.panel.querySelector('.interrupt-resume-value');
        const commentInput = this.panel.querySelector('.interrupt-comment');
        const feedback = this.panel.querySelector('.interrupt-feedback');
        const resumeBtn = this.panel.querySelector('.interrupt-btn-resume');
        const cancelBtn = this.panel.querySelector('.interrupt-btn-cancel');
        const form = this.panel.querySelector('.interrupt-form');
        const resumeKey = form.dataset.resumeKey;

        const username = usernameInput.value.trim();
        const valueStr = valueInput.value.trim();
        const comment = commentInput.value.trim();

        // Parse resume value (JSON, number, or string)
        let resumeValue;
        try {
            // Try parsing as JSON first
            resumeValue = JSON.parse(valueStr);
        } catch {
            // If not JSON, check if it's a number
            if (!isNaN(valueStr) && valueStr !== '') {
                resumeValue = Number(valueStr);
            } else {
                // Otherwise treat as string
                resumeValue = valueStr;
            }
        }

        // Save username to localStorage
        if (username) {
            localStorage.setItem('dag_username', username);
        }

        // Show loading state
        resumeBtn.disabled = true;
        cancelBtn.disabled = true;
        feedback.textContent = 'Resuming workflow...';
        feedback.className = 'interrupt-feedback';
        feedback.classList.remove('hidden');

        try {
            const runId = node.run_id;
            const nodeName = node.node_name;
            const response = await fetch(`/api/workflows/${runId}/interrupts/${nodeName}/resume`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    resume_value: resumeValue,
                    decided_by: username || null,
                    comment: comment || null,
                }),
            });

            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.detail || 'Failed to resume workflow');
            }

            const result = await response.json();

            // Show success feedback
            feedback.textContent = `Workflow resumed successfully by ${result.decided_by}`;
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
            resumeBtn.disabled = false;
            cancelBtn.disabled = false;
        }
    }

    async loadWorkflowState(node) {
        const stateViewer = this.panel.querySelector('#interrupt-state-viewer');
        if (!stateViewer) return;

        try {
            const runId = node.run_id;
            const nodeName = node.node_name;
            const response = await fetch(`/api/workflows/${runId}/nodes/${nodeName}/interrupt`);

            if (!response.ok) {
                throw new Error('Failed to load workflow state');
            }

            const data = await response.json();
            const workflowState = data.workflow_state || {};

            // Render workflow state as formatted JSON
            stateViewer.innerHTML = `<pre class="state-json">${JSON.stringify(workflowState, null, 2)}</pre>`;
        } catch (error) {
            stateViewer.innerHTML = `<div class="error">Error loading state: ${error.message}</div>`;
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
