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
                    <button class="tab-btn" data-tab="chat">Chat</button>
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
                    <div class="tab-content" data-tab="chat">
                        ${this.renderChat(node)}
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

        // Setup timeout countdown updater
        const timeoutCountdown = this.panel.querySelector('.interrupt-timeout .timeout-countdown');
        if (timeoutCountdown) {
            const timeoutDiv = this.panel.querySelector('.interrupt-timeout');
            const expiresAt = parseInt(timeoutDiv.dataset.expiresAt);
            this.countdownInterval = setInterval(() => {
                const remainingMs = expiresAt - Date.now();
                if (remainingMs <= 0) {
                    clearInterval(this.countdownInterval);
                    timeoutDiv.innerHTML = '<span class="timeout-label">Timeout expired</span>';
                    timeoutDiv.classList.add('expired');
                } else {
                    const remainingSeconds = Math.floor(remainingMs / 1000);
                    const minutes = Math.floor(remainingSeconds / 60);
                    const seconds = remainingSeconds % 60;
                    timeoutCountdown.textContent = `${minutes}m ${seconds}s`;
                }
            }, 1000);
        }

        // Setup chat send button listener
        const chatSendBtn = this.panel.querySelector(`#node-chat-send-${node.id}`);
        const chatInput = this.panel.querySelector(`#node-chat-input-${node.id}`);
        if (chatSendBtn && chatInput) {
            chatSendBtn.addEventListener('click', () => this.handleSendNodeMessage(node));
            // Also send on Enter (but not Shift+Enter for multi-line)
            chatInput.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    this.handleSendNodeMessage(node);
                }
            });
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

    renderChat(node) {
        // Clear chat messages Map on node switch to prevent cross-node id collisions
        this.chatMessages = new Map();

        // Populate the Map from node.chat_messages
        if (node.chat_messages && node.chat_messages.length > 0) {
            node.chat_messages.forEach(msg => {
                if (msg.id) {
                    this.chatMessages.set(msg.id, msg);
                }
            });
        }

        const isRunning = node.status === 'running';
        const modelName = node.model || 'Unknown Model';

        const messagesHtml = node.chat_messages && node.chat_messages.length > 0
            ? node.chat_messages.map(msg => `
                <div class="node-chat-message node-chat-message-${this.escapeHtml(msg.role)}">
                    <div class="node-chat-message-role">${this.escapeHtml(msg.role)}</div>
                    <div class="node-chat-message-content">${this.escapeHtml(msg.content)}</div>
                    <div class="node-chat-message-timestamp">${new Date(msg.created_at).toLocaleString()}</div>
                </div>
            `).join('')
            : '<p class="empty-state">No chat messages yet</p>';

        return `
            <div class="node-chat-container">
                <div class="node-chat-model">${this.escapeHtml(modelName)}</div>
                <div class="node-chat-messages" id="node-chat-messages-${node.id}">
                    ${messagesHtml}
                </div>
                <div class="node-chat-typing-indicator" id="node-chat-typing-${node.id}" style="display: none;">
                    Agent is typing...
                </div>
                ${isRunning ? `
                    <div class="node-chat-input-container">
                        <textarea
                            id="node-chat-input-${node.id}"
                            class="node-chat-input"
                            placeholder="Type a message..."
                            rows="3"
                        ></textarea>
                        <button
                            id="node-chat-send-${node.id}"
                            class="node-chat-send-btn"
                        >Send</button>
                    </div>
                ` : `
                    <div class="node-chat-readonly-notice">
                        Chat is read-only (node ${this.escapeHtml(node.status)})
                    </div>
                `}
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
                                    <td>${currentVer != null ? currentVer : '<em>missing</em>'}</td>
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
        // Check if this is an interrupt node (vs gate node)
        const nodeType = node.outputs?.node_type;
        if (nodeType === 'interrupt') {
            return this.renderInterruptResume(node);
        }

        // Existing gate approval logic
        const username = localStorage.getItem('dag_username') || '';
        const runId = node.run_id;
        const nodeName = node.node_name;

        // Render gate description if present
        const gateDescription = node.inputs?.description ? `
            <div class="gate-description">
                <h5>Description</h5>
                <p>${this.escapeHtml(node.inputs.description)}</p>
            </div>
        ` : '';

        // Render upstream context if present
        const upstreamContext = (node.upstream_context && node.upstream_context.length > 0) ? `
            <div class="gate-upstream-context">
                <h5>Upstream Artifacts</h5>
                ${node.upstream_context.map(upstream => `
                    <div class="gate-upstream-node">
                        <strong>${this.escapeHtml(upstream.node_name)}</strong>
                        <span class="upstream-status status-${upstream.status}">${upstream.status}</span>
                        ${upstream.artifacts && upstream.artifacts.length > 0 ? `
                            <ul class="upstream-artifacts">
                                ${upstream.artifacts.map(artifact => `
                                    <li>
                                        <span class="artifact-name">${this.escapeHtml(artifact.name)}</span>
                                        <span class="artifact-type">(${this.escapeHtml(artifact.artifact_type)})</span>
                                    </li>
                                `).join('')}
                            </ul>
                        ` : '<p class="no-artifacts">No artifacts</p>'}
                    </div>
                `).join('')}
            </div>
        ` : '';

        return `
            <div class="gate-approval-panel">
                <div class="gate-info">
                    <h4>Gate: ${this.escapeHtml(nodeName)}</h4>
                    <span class="gate-status-badge">Awaiting Approval</span>
                </div>

                ${gateDescription}
                ${upstreamContext}

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
        const timeout = node.outputs?.timeout;
        const startedAt = node.outputs?.started_at;

        // Calculate timeout countdown if available
        let timeoutHtml = '';
        if (timeout && startedAt) {
            const startTime = new Date(startedAt).getTime();
            const timeoutMs = timeout * 1000;
            const expiresAt = startTime + timeoutMs;
            const remainingMs = expiresAt - Date.now();

            if (remainingMs > 0) {
                const remainingSeconds = Math.floor(remainingMs / 1000);
                const minutes = Math.floor(remainingSeconds / 60);
                const seconds = remainingSeconds % 60;
                timeoutHtml = `
                    <div class="interrupt-timeout" data-expires-at="${expiresAt}">
                        <span class="timeout-label">Timeout:</span>
                        <span class="timeout-countdown">${minutes}m ${seconds}s</span>
                    </div>
                `;
            } else {
                timeoutHtml = '<div class="interrupt-timeout expired">Timeout expired</div>';
            }
        }

        return `
            <div class="interrupt-resume-panel">
                <div class="interrupt-header">
                    <div class="interrupt-icon">⏸</div>
                    <div class="interrupt-info">
                        <h4>${this.escapeHtml(nodeName)}</h4>
                        <p class="interrupt-message">${this.escapeHtml(message)}</p>
                        ${timeoutHtml}
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

    async handleSendNodeMessage(node) {
        const chatInput = this.panel.querySelector(`#node-chat-input-${node.id}`);
        const typingIndicator = this.panel.querySelector(`#node-chat-typing-${node.id}`);
        const chatSendBtn = this.panel.querySelector(`#node-chat-send-${node.id}`);

        if (!chatInput || !chatInput.value.trim()) {
            return;
        }

        const content = chatInput.value.trim();

        // Get username from localStorage with fallback chain
        const username = localStorage.getItem('chat_operator_username')
            || localStorage.getItem('dag_username')
            || 'operator';

        // Disable input while sending
        chatInput.disabled = true;
        if (chatSendBtn) chatSendBtn.disabled = true;

        try {
            const response = await fetch(`/api/workflows/${node.run_id}/nodes/${node.id}/chat`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    content: content,
                    operator_username: username,
                }),
            });

            if (!response.ok) {
                if (response.status === 409) {
                    throw new Error('Node is not running');
                } else if (response.status === 429) {
                    throw new Error('Rate limit exceeded');
                } else {
                    const error = await response.json();
                    throw new Error(error.detail || 'Failed to send message');
                }
            }

            const message = await response.json();

            // Save username to localStorage (share identity with workflow chat)
            localStorage.setItem('chat_operator_username', username);

            // Clear input
            chatInput.value = '';

            // Add message to local Map (optimistic UI)
            if (message.id) {
                this.chatMessages.set(message.id, message);
            }

            // Show typing indicator with 30s timeout
            if (typingIndicator) {
                typingIndicator.style.display = 'block';
                // Auto-hide after 30s if no agent response
                if (this.typingTimeout) clearTimeout(this.typingTimeout);
                this.typingTimeout = setTimeout(() => {
                    if (typingIndicator) typingIndicator.style.display = 'none';
                }, 30000);
            }

            // Do NOT append to DOM here — let SSE echo render it (matches workflow chat pattern)
            // This avoids the double-render bug since SSE payload lacks 'id' field for dedupe

        } catch (error) {
            // Show error inline (no modal interruptions)
            this.showNodeChatError(node, error.message);
        } finally {
            // Re-enable input
            chatInput.disabled = false;
            if (chatSendBtn) chatSendBtn.disabled = false;
            chatInput.focus();
        }
    }

    appendChatMessage(payload) {
        // Dedupe check - skip if we already have this message
        if (!this.chatMessages || this.chatMessages.has(payload.id)) {
            return;
        }

        // Add to Map
        this.chatMessages.set(payload.id, payload);

        // Append to DOM
        if (this.currentNode) {
            this.appendChatMessageToDOM(this.currentNode, payload);
        }

        // Hide typing indicator and clear timeout
        const typingIndicator = this.panel?.querySelector(`#node-chat-typing-${this.currentNode.id}`);
        if (typingIndicator) {
            typingIndicator.style.display = 'none';
            if (this.typingTimeout) {
                clearTimeout(this.typingTimeout);
                this.typingTimeout = null;
            }
        }
    }

    appendChatMessageToDOM(node, message) {
        const messagesContainer = this.panel?.querySelector(`#node-chat-messages-${node.id}`);
        if (!messagesContainer) {
            return;
        }

        // Remove empty state if it exists
        const emptyState = messagesContainer.querySelector('.empty-state');
        if (emptyState) {
            emptyState.remove();
        }

        // Create message element
        const messageDiv = document.createElement('div');
        messageDiv.className = `node-chat-message node-chat-message-${this.escapeHtml(message.role)}`;
        messageDiv.innerHTML = `
            <div class="node-chat-message-role">${this.escapeHtml(message.role)}</div>
            <div class="node-chat-message-content">${this.escapeHtml(message.content)}</div>
            <div class="node-chat-message-timestamp">${new Date(message.created_at).toLocaleString()}</div>
        `;

        messagesContainer.appendChild(messageDiv);

        // Scroll to bottom
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
    }

    showNodeChatError(node, message) {
        const chatContainer = this.panel?.querySelector(`#node-chat-messages-${node.id}`);
        if (!chatContainer) return;

        // Remove any existing error
        const existingError = this.panel.querySelector('.node-chat-error');
        if (existingError) existingError.remove();

        // Create and insert error div
        const errorDiv = document.createElement('div');
        errorDiv.className = 'node-chat-error';
        errorDiv.textContent = `Error: ${message}`;
        chatContainer.insertAdjacentElement('afterend', errorDiv);

        // Auto-remove after 5 seconds
        setTimeout(() => errorDiv.remove(), 5000);
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
            // Clear countdown interval if active
            if (this.countdownInterval) {
                clearInterval(this.countdownInterval);
                this.countdownInterval = null;
            }
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
