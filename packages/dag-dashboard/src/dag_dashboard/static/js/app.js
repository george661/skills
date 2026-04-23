/**
 * DAG Dashboard SPA - Router and State Management
 */

// Security: HTML escaping helper to prevent XSS
function escapeHtml(unsafe) {
    if (unsafe === null || unsafe === undefined) return '';
    return String(unsafe)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

// State Store (simple pub/sub pattern)
class Store {
    constructor() {
        this.state = {
            workflows: [],
            selectedWorkflow: null,
            nodeStates: {},
            connected: false
        };
        this.listeners = [];
    }

    getState() {
        return this.state;
    }

    setState(updates) {
        this.state = { ...this.state, ...updates };
        this.notify();
    }

    subscribe(listener) {
        this.listeners.push(listener);
        return () => {
            this.listeners = this.listeners.filter(l => l !== listener);
        };
    }

    notify() {
        this.listeners.forEach(listener => listener(this.state));
    }
}

// Global store instance
const store = new Store();

// Router
class Router {
    constructor() {
        this.routes = {};
        this.currentRoute = null;
        
        // Listen for hash changes
        window.addEventListener('hashchange', () => this.handleRoute());
        
        // Handle initial route
        this.handleRoute();
    }

    register(path, handler) {
        this.routes[path] = handler;
    }

    handleRoute() {
        const hash = window.location.hash.slice(1) || '/';
        const [path, ...params] = hash.split('/').filter(Boolean);
        const route = '/' + path;

        // Update active nav link
        document.querySelectorAll('.nav-link, .mobile-nav-link').forEach(link => {
            const linkRoute = link.dataset.route;
            if (linkRoute === route || (route === '/' && linkRoute === '/')) {
                link.classList.add('active');
            } else {
                link.classList.remove('active');
            }
        });

        // Handle parameterized routes
        if (hash.startsWith('/workflows/')) {
            const name = hash.split('/')[2];
            if (name) {
                this.currentRoute = '/workflows/:name';
                if (this.routes['/workflows/:name']) {
                    this.routes['/workflows/:name'](name);
                }
                return;
            }
        }

        if (hash.startsWith('/workflow-trigger/')) {
            const name = hash.split('/')[2];
            if (name) {
                this.currentRoute = '/workflow-trigger/:name';
                if (this.routes['/workflow-trigger/:name']) {
                    this.routes['/workflow-trigger/:name'](name);
                }
                return;
            }
        }

        if (hash.startsWith('/workflow/')) {
            const runId = hash.split('/')[2];
            this.currentRoute = '/workflow/:runId';
            if (this.routes['/workflow/:runId']) {
                this.routes['/workflow/:runId'](runId);
            }
            return;
        }

        // Handle checkpoint routes
        if (hash.startsWith('/checkpoints/compare/')) {
            const parts = hash.split('/').filter(Boolean);
            if (parts.length >= 5) {
                const workflow = parts[2];
                const runIdA = parts[3];
                const runIdB = parts[4];
                this.currentRoute = '/checkpoints/compare/:wf/:runIdA/:runIdB';
                if (this.routes['/checkpoints/compare/:wf/:runIdA/:runIdB']) {
                    this.routes['/checkpoints/compare/:wf/:runIdA/:runIdB'](workflow, runIdA, runIdB);
                }
                return;
            }
        } else if (hash.startsWith('/checkpoints/')) {
            const parts = hash.split('?')[0].split('/').filter(Boolean);
            if (parts.length === 3) {
                const workflow = parts[1];
                const runId = parts[2];
                this.currentRoute = '/checkpoints/:wf/:runId';
                if (this.routes['/checkpoints/:wf/:runId']) {
                    this.routes['/checkpoints/:wf/:runId'](workflow, runId);
                }
                return;
            } else if (parts.length === 2) {
                const workflow = parts[1];
                this.currentRoute = '/checkpoints/:wf';
                if (this.routes['/checkpoints/:wf']) {
                    this.routes['/checkpoints/:wf'](workflow);
                }
                return;
            }
        }

        // Handle static routes
        const handler = this.routes[route] || this.routes['/'];
        if (handler) {
            this.currentRoute = route;
            handler();
        }
    }

    navigate(path) {
        window.location.hash = path;
    }
}

// Route handlers
async function renderDashboard() {
    const container = document.getElementById('route-container');

    // Fetch status summary
    let statusSummary = { running: 0, completed: 0, failed: 0, pending: 0, cancelled: 0 };
    try {
        const response = await fetch('/api/workflows/summary');
        if (response.ok) {
            statusSummary = await response.json();
        }
    } catch (error) {
        console.error('Failed to load status summary:', error);
    }

    // Fetch running workflows
    let runningWorkflows = [];
    try {
        const response = await fetch('/api/workflows?status=running&limit=10');
        if (response.ok) {
            const data = await response.json();
            runningWorkflows = data.items || [];
        }
    } catch (error) {
        console.error('Failed to load running workflows:', error);
    }

    // Render status summary cards
    const summaryCards = `
        <div class="status-summary">
            <div class="status-card status-card-running" data-status="running">
                <div class="status-card-count">${statusSummary.running}</div>
                <div class="status-card-label">Running</div>
            </div>
            <div class="status-card status-card-completed" data-status="completed">
                <div class="status-card-count">${statusSummary.completed}</div>
                <div class="status-card-label">Completed</div>
            </div>
            <div class="status-card status-card-failed" data-status="failed">
                <div class="status-card-count">${statusSummary.failed}</div>
                <div class="status-card-label">Failed</div>
            </div>
            <div class="status-card status-card-pending" data-status="pending">
                <div class="status-card-count">${statusSummary.pending}</div>
                <div class="status-card-label">Pending</div>
            </div>
            <div class="status-card status-card-cancelled" data-status="cancelled">
                <div class="status-card-count">${statusSummary.cancelled}</div>
                <div class="status-card-label">Cancelled</div>
            </div>
        </div>
    `;

    // Render active workflows section
    let activeWorkflowsHTML = '';
    if (runningWorkflows.length > 0) {
        const workflowCards = runningWorkflows.map(wf => `
            <div class="workflow-card">
                <div class="workflow-title">${escapeHtml(wf.workflow_name)}</div>
                <span class="workflow-status ${escapeHtml(wf.status)}">${escapeHtml(wf.status)}</span>
                <div style="margin-top: 0.5rem; color: var(--text-secondary); font-size: 0.875rem;">
                    ${wf.started_at ? new Date(wf.started_at).toLocaleString() : 'No start time'}
                </div>
            </div>
        `).join('');

        activeWorkflowsHTML = `
            <h3 style="margin-top: 2rem; margin-bottom: 1rem;">Active Workflows</h3>
            <div class="workflow-list">
                ${workflowCards}
            </div>
        `;
    } else {
        activeWorkflowsHTML = `
            <h3 style="margin-top: 2rem; margin-bottom: 1rem;">Active Workflows</h3>
            <div class="empty-state" style="padding: 2rem 1rem;">
                <div class="empty-state-icon">📊</div>
                <div class="empty-state-text">No active workflows</div>
            </div>
        `;
    }

    container.innerHTML = `
        <h2 style="margin-bottom: 1.5rem;">Dashboard</h2>
        ${summaryCards}
        ${activeWorkflowsHTML}
    `;

    // Add click handlers to status cards
    document.querySelectorAll('.status-card').forEach(card => {
        card.addEventListener('click', () => {
            const status = card.dataset.status;
            window.location.hash = `/history?status=${status}`;
        });
    });
}

async function renderHistory() {
    const container = document.getElementById('route-container');

    // Parse query parameters
    const hash = window.location.hash.slice(1);
    const urlParams = new URLSearchParams(hash.split('?')[1] || '');
    const currentStatus = urlParams.get('status') || '';
    const currentName = urlParams.get('name') || '';
    const currentPage = parseInt(urlParams.get('page') || '0');
    const currentSort = urlParams.get('sort') || 'started_at';
    const currentStartDate = urlParams.get('start_date') || '';
    const currentEndDate = urlParams.get('end_date') || '';
    const groupByParent = urlParams.get('group') === 'parent';
    const expandedParam = urlParams.get('expanded') || '';
    const expandedSet = new Set(expandedParam ? expandedParam.split(',').filter(Boolean) : []);
    const limit = 20;
    const offset = currentPage * limit;

    // Build API query
    const apiParams = new URLSearchParams({
        limit: limit.toString(),
        offset: offset.toString(),
        sort_by: currentSort
    });
    if (currentStatus) apiParams.set('status', currentStatus);
    if (currentName) apiParams.set('name', currentName);
    if (currentStartDate) apiParams.set('started_after', currentStartDate);
    if (currentEndDate) apiParams.set('started_before', currentEndDate);
    if (groupByParent) apiParams.set('group_by', 'parent');

    // Fetch workflows
    let workflows = [];
    let total = 0;
    try {
        const response = await fetch(`/api/workflows?${apiParams}`);
        if (response.ok) {
            const data = await response.json();
            workflows = data.items || [];
            total = data.total || 0;
        }
    } catch (error) {
        console.error('Failed to load workflows:', error);
    }

    // Calculate pagination
    const totalPages = Math.ceil(total / limit);
    const hasPrev = currentPage > 0;
    const hasNext = currentPage < totalPages - 1;

    // Render filters
    const filtersHTML = `
        <div class="history-filters">
            <div class="filter-group">
                <label for="status-filter">Status:</label>
                <select id="status-filter" class="filter-select">
                    <option value="">All</option>
                    <option value="running" ${currentStatus === 'running' ? 'selected' : ''}>Running</option>
                    <option value="completed" ${currentStatus === 'completed' ? 'selected' : ''}>Completed</option>
                    <option value="failed" ${currentStatus === 'failed' ? 'selected' : ''}>Failed</option>
                    <option value="pending" ${currentStatus === 'pending' ? 'selected' : ''}>Pending</option>
                    <option value="cancelled" ${currentStatus === 'cancelled' ? 'selected' : ''}>Cancelled</option>
                </select>
            </div>
            <div class="filter-group">
                <label for="name-filter">Name:</label>
                <input type="text" id="name-filter" class="filter-input" placeholder="Filter by name..." value="${escapeHtml(currentName)}">
            </div>
            <div class="filter-group">
                <label for="start-date-filter">Start Date:</label>
                <input type="date" id="start-date-filter" class="filter-input" value="${escapeHtml(currentStartDate)}">
            </div>
            <div class="filter-group">
                <label for="end-date-filter">End Date:</label>
                <input type="date" id="end-date-filter" class="filter-input" value="${escapeHtml(currentEndDate)}">
            </div>
            <div class="filter-group">
                <label for="sort-filter">Sort by:</label>
                <select id="sort-filter" class="filter-select">
                    <option value="started_at" ${currentSort === 'started_at' ? 'selected' : ''}>Start Time</option>
                    <option value="finished_at" ${currentSort === 'finished_at' ? 'selected' : ''}>Finish Time</option>
                    <option value="duration" ${currentSort === 'duration' ? 'selected' : ''}>Duration</option>
                </select>
            </div>
            <div class="filter-group">
                <label class="group-toggle">
                    <input type="checkbox" id="group-toggle" ${groupByParent ? 'checked' : ''}>
                    Group by parent
                </label>
            </div>
        </div>
    `;

    // Render table
    let tableHTML = '';
    if (workflows.length > 0) {
        // renderRow builds a single tr. For grouped mode the parent row gets a
        // chevron + child count and its children render immediately after it
        // (indented) when the parent is in the expanded set.
        const renderRow = (wf, opts = {}) => {
            const { isChild = false, childCount = 0, hasChildren = false, expanded = false } = opts;
            const startTime = wf.started_at ? new Date(wf.started_at).toLocaleString() : 'N/A';
            const duration = wf.finished_at && wf.started_at
                ? Math.round((new Date(wf.finished_at) - new Date(wf.started_at)) / 1000) + 's'
                : 'N/A';
            const source = wf.trigger_source || 'manual';
            const displayStatus = !isChild && wf.aggregate_status ? wf.aggregate_status : wf.status;
            const chevron = hasChildren
                ? `<span class="chevron ${expanded ? 'expanded' : ''}" data-parent-id="${escapeHtml(wf.id)}">▶</span>`
                : '';
            const countBadge = hasChildren
                ? `<span class="child-count-badge">${childCount}</span>`
                : '';
            const rowClass = isChild ? 'history-row child-row' : 'history-row';
            return `
                <tr class="${rowClass}" data-run-id="${escapeHtml(wf.id)}">
                    <td class="history-cell">${chevron}${escapeHtml(wf.workflow_name)}${countBadge}</td>
                    <td class="history-cell"><span class="workflow-status ${escapeHtml(displayStatus)}">${escapeHtml(displayStatus)}</span></td>
                    <td class="history-cell">${startTime}</td>
                    <td class="history-cell">${duration}</td>
                    <td class="history-cell"><span class="trigger-source-badge">${escapeHtml(source)}</span></td>
                </tr>
            `;
        };

        let rows;
        if (groupByParent) {
            rows = workflows.map(wf => {
                const children = wf.children || [];
                const expanded = expandedSet.has(wf.id);
                const parentRow = renderRow(wf, {
                    hasChildren: children.length > 0,
                    childCount: children.length,
                    expanded,
                });
                if (expanded && children.length > 0) {
                    const childRows = children.map(c => renderRow(c, { isChild: true })).join('');
                    return parentRow + childRows;
                }
                return parentRow;
            }).join('');
        } else {
            rows = workflows.map(wf => renderRow(wf)).join('');
        }

        tableHTML = `
            <table class="history-table">
                <thead>
                    <tr>
                        <th class="history-header">Workflow Name</th>
                        <th class="history-header">Status</th>
                        <th class="history-header">Started At</th>
                        <th class="history-header">Duration</th>
                        <th class="history-header">Source</th>
                    </tr>
                </thead>
                <tbody>
                    ${rows}
                </tbody>
            </table>
        `;
    } else {
        tableHTML = `
            <div class="empty-state">
                <div class="empty-state-icon">📜</div>
                <div class="empty-state-text">No workflows found</div>
            </div>
        `;
    }

    // Render pagination
    const paginationHTML = total > 0 ? `
        <div class="pagination">
            <button class="pagination-btn" id="prev-page" ${!hasPrev ? 'disabled' : ''}>← Previous</button>
            <span class="pagination-info">Page ${currentPage + 1} of ${totalPages} (${total} total)</span>
            <button class="pagination-btn" id="next-page" ${!hasNext ? 'disabled' : ''}>Next →</button>
        </div>
    ` : '';

    container.innerHTML = `
        <h2 style="margin-bottom: 1.5rem;">Workflow History</h2>
        ${filtersHTML}
        ${tableHTML}
        ${paginationHTML}
    `;

    // Add event listeners for filters
    const statusFilter = document.getElementById('status-filter');
    const nameFilter = document.getElementById('name-filter');
    const startDateFilter = document.getElementById('start-date-filter');
    const endDateFilter = document.getElementById('end-date-filter');
    const sortFilter = document.getElementById('sort-filter');

    const groupToggle = document.getElementById('group-toggle');

    const applyFilters = () => {
        const params = new URLSearchParams();
        if (statusFilter.value) params.set('status', statusFilter.value);
        if (nameFilter.value) params.set('name', nameFilter.value);
        if (startDateFilter.value) params.set('start_date', startDateFilter.value);
        if (endDateFilter.value) params.set('end_date', endDateFilter.value);
        if (sortFilter.value !== 'started_at') params.set('sort', sortFilter.value);
        if (groupToggle && groupToggle.checked) {
            params.set('group', 'parent');
            if (expandedSet.size > 0) {
                params.set('expanded', Array.from(expandedSet).join(','));
            }
        }
        params.set('page', '0');
        window.location.hash = `/history?${params}`;
    };

    statusFilter.addEventListener('change', applyFilters);
    startDateFilter.addEventListener('change', applyFilters);
    endDateFilter.addEventListener('change', applyFilters);
    sortFilter.addEventListener('change', applyFilters);
    if (groupToggle) {
        groupToggle.addEventListener('change', () => {
            // Clear expanded state when toggling off to keep URL tidy.
            if (!groupToggle.checked) {
                expandedSet.clear();
            }
            applyFilters();
        });
    }

    // Debounce name filter input
    let nameFilterTimeout;
    nameFilter.addEventListener('input', () => {
        clearTimeout(nameFilterTimeout);
        nameFilterTimeout = setTimeout(applyFilters, 500);
    });

    // Chevron click toggles the parent's id in the expanded set and updates URL.
    // Stops propagation so clicking a chevron doesn't also trigger the row-click
    // navigation handler below.
    document.querySelectorAll('.chevron').forEach(chevron => {
        chevron.addEventListener('click', (e) => {
            e.stopPropagation();
            const parentId = chevron.dataset.parentId;
            if (!parentId) return;
            if (expandedSet.has(parentId)) {
                expandedSet.delete(parentId);
            } else {
                expandedSet.add(parentId);
            }
            const params = new URLSearchParams(urlParams);
            if (expandedSet.size > 0) {
                params.set('expanded', Array.from(expandedSet).join(','));
            } else {
                params.delete('expanded');
            }
            window.location.hash = `/history?${params}`;
        });
    });

    // Pagination handlers
    document.getElementById('prev-page')?.addEventListener('click', () => {
        if (hasPrev) {
            urlParams.set('page', (currentPage - 1).toString());
            window.location.hash = `/history?${urlParams}`;
        }
    });

    document.getElementById('next-page')?.addEventListener('click', () => {
        if (hasNext) {
            urlParams.set('page', (currentPage + 1).toString());
            window.location.hash = `/history?${urlParams}`;
        }
    });

    // Row click to navigate
    document.querySelectorAll('.history-row').forEach(row => {
        row.addEventListener('click', () => {
            const runId = row.dataset.runId;
            window.location.hash = `/workflow/${runId}`;
        });
    });
}

function renderTotals(totals) {
    const container = document.getElementById('totals-container');
    if (!container) return;

    const {
        cost = 0,
        tokens_input = 0,
        tokens_output = 0,
        tokens_cache = 0,
        total_tokens = 0,
        failed_nodes = 0,
        skipped_nodes = 0
    } = totals;

    container.innerHTML = `
        <div class="workflow-totals">
            <div class="totals-item">
                <div class="totals-label">Total Cost</div>
                <div class="totals-value">$${cost.toFixed(4)}</div>
            </div>
            <div class="totals-item">
                <div class="totals-label">Total Tokens</div>
                <div class="totals-value">${total_tokens.toLocaleString()}</div>
                <div class="totals-breakdown">
                    ${tokens_input.toLocaleString()} in /
                    ${tokens_output.toLocaleString()} out /
                    ${tokens_cache.toLocaleString()} cache
                </div>
            </div>
            <div class="totals-item">
                <div class="totals-label">Failed Nodes</div>
                <div class="totals-value">${failed_nodes}</div>
            </div>
            <div class="totals-item">
                <div class="totals-label">Skipped Nodes</div>
                <div class="totals-value">${skipped_nodes}</div>
            </div>
        </div>
    `;
}

function renderFailureBanner(run, nodes) {
    const container = document.getElementById('totals-container');
    if (!container) return;

    // Find the first failed node
    const failedNode = nodes.find(n => n.status === 'failed');
    if (!failedNode) return;

    // Get error message excerpt (first 100 chars)
    const errorExcerpt = failedNode.error
        ? (failedNode.error.length > 100
            ? failedNode.error.substring(0, 97) + '...'
            : failedNode.error)
        : 'No error message available';

    const banner = document.createElement('div');
    banner.className = 'workflow-failure-banner';
    banner.innerHTML = `
        <div class="workflow-failure-banner-icon">!</div>
        <div class="workflow-failure-banner-content">
            <div class="workflow-failure-banner-title">
                Workflow Failed at ${escapeHtml(failedNode.node_name)}
            </div>
            <div class="workflow-failure-banner-message">
                ${escapeHtml(errorExcerpt)}
            </div>
        </div>
    `;

    // Insert before totals
    container.parentNode.insertBefore(banner, container);
}

async function renderWorkflowDetail(runId) {
    const container = document.getElementById('route-container');

    container.innerHTML = `
        <div>
            <a href="#/" style="color: var(--primary); text-decoration: none; display: inline-block; margin-bottom: 1rem;">
                ← Back to Dashboard
            </a>
            <div id="cancel-button-container" class="cancel-button-container"></div>
            <div id="retry-button-container" class="retry-button-container"></div>
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 1.5rem;">
                <h2 style="margin: 0;">Workflow Detail</h2>
                <button id="rerun-button" class="btn btn-secondary" style="display: none;">
                    Re-run
                </button>
            </div>
            <div id="executing-banner" class="executing-banner" style="display: none;">
                <div class="executing-content">
                    <span class="executing-label">Currently Executing:</span>
                    <span id="executing-node-name"></span>
                    <span id="executing-model" class="executing-model"></span>
                    <span id="executing-timer" class="executing-timer">0s</span>
                </div>
            </div>
            <div id="totals-container"></div>
            <div id="dag-container"></div>
            <div id="channel-state-container" style="margin-top: 1rem;"></div>
            <div style="margin-top: 1.5rem; padding: 1rem; background: var(--bg-card); border-radius: var(--radius); border: 1px solid var(--border);">
                <h3 style="margin-bottom: 1rem;">State Changes Timeline</h3>
                <div id="state-diff-timeline-container"></div>
            </div>
            <section id="chat-container" class="chat-section"></section>
            <div id="run-artifacts-container" style="margin-top: 1rem;"></div>
            <div style="margin-top: 1rem; padding: 1rem; background: var(--bg-card); border-radius: var(--radius); border: 1px solid var(--border);">
                <h3 style="margin-bottom: 0.5rem;">Run ID:</h3>
                <code style="color: var(--text-secondary);">${escapeHtml(runId)}</code>
            </div>
        </div>
    `;

    // Fetch workflow data (includes totals) and layout data
    try {
        const [workflowResp, layoutResp] = await Promise.all([
            fetch(`/api/workflows/${runId}`),
            fetch(`/api/workflows/${runId}/layout`)
        ]);

        if (!workflowResp.ok || !layoutResp.ok) {
            throw new Error('Failed to fetch workflow data');
        }

        const workflowData = await workflowResp.json();
        const layoutData = await layoutResp.json();

        // Show Re-run button for terminal states
        if (workflowData.run && ['completed', 'failed', 'cancelled'].includes(workflowData.run.status)) {
            const rerunButton = document.getElementById('rerun-button');
            if (rerunButton) {
                rerunButton.style.display = 'inline-block';
                rerunButton.addEventListener('click', () => {
                    if (window.showRerunModal) {
                        window.showRerunModal(runId);
                    }
                });
            }
        }

        // Render cancel button if workflow is running
        const cancelButtonContainer = document.getElementById('cancel-button-container');
        if (cancelButtonContainer && window.renderCancelButton) {
            window.renderCancelButton(cancelButtonContainer, runId, workflowData.run?.status);
        }

        // Render retry button if workflow is failed
        const retryButtonContainer = document.getElementById('retry-button-container');
        if (retryButtonContainer && window.renderRetryButton) {
            window.renderRetryButton(retryButtonContainer, runId, workflowData.run?.status);
        }

        // Render totals strip
        if (workflowData.totals) {
            renderTotals(workflowData.totals);
        }

        // Render failure banner if workflow failed
        if (workflowData.run && workflowData.run.status === 'failed') {
            renderFailureBanner(workflowData.run, layoutData.nodes);
        }

        // Render model override banner if present
        if (workflowData.run && workflowData.run.inputs) {
            let parsedInputs;
            try {
                parsedInputs = typeof workflowData.run.inputs === 'string'
                    ? JSON.parse(workflowData.run.inputs)
                    : workflowData.run.inputs;
            } catch (e) {
                parsedInputs = null;
            }

            if (parsedInputs && parsedInputs.__model_override__) {
                const banner = document.createElement('div');
                banner.className = 'model-override-banner';
                banner.innerHTML = `
                    Running with model override: <strong>${escapeHtml(parsedInputs.__model_override__)}</strong>
                `;

                // Insert before the executing-banner or dag-container
                const executingBanner = document.getElementById('executing-banner');
                const dagContainer = document.getElementById('dag-container');
                const insertBefore = executingBanner || dagContainer;
                if (insertBefore && insertBefore.parentNode) {
                    insertBefore.parentNode.insertBefore(banner, insertBefore);
                }
            }
        }

        // Render DAG
        const dagRenderer = new window.DAGRenderer('dag-container');
        dagRenderer.render(layoutData);

        // Render state diff timeline
        const timelineContainer = document.getElementById('state-diff-timeline-container');
        if (timelineContainer && window.renderStateDiffTimeline) {
            window.renderStateDiffTimeline(timelineContainer, runId);
        }

        // Setup currently executing banner
        setupExecutingBanner(layoutData.nodes);

        // Initialize channel state panel
        const channelPanel = new window.ChannelStatePanel('channel-state-container');

        // Initialize chat panel
        const chatPanel = new window.ChatPanel('chat-container', runId);
        chatPanel.render();

        // Render workflow-aggregated artifacts
        if (window.ArtifactList) {
            window.ArtifactList.render('run-artifacts-container', runId);
        }

        // Connect to SSE for live updates
        setupLiveUpdates(runId, dagRenderer, layoutData.nodes, channelPanel, chatPanel);

    } catch (error) {
        console.error('Error loading workflow detail:', error);
        container.innerHTML += `
            <div style="padding: 1rem; background: var(--error); color: white; border-radius: var(--radius); margin-top: 1rem;">
                Error loading workflow: ${escapeHtml(error.message)}
            </div>
        `;
    }
}

function setupExecutingBanner(nodes) {
    const banner = document.getElementById('executing-banner');
    const nodeNameEl = document.getElementById('executing-node-name');
    const modelEl = document.getElementById('executing-model');
    const timerEl = document.getElementById('executing-timer');

    // Find running node
    const runningNode = nodes.find(n => n.status === 'running');

    if (runningNode) {
        banner.style.display = 'block';
        nodeNameEl.textContent = runningNode.node_name;
        modelEl.textContent = runningNode.model || '';

        // Start live timer
        const startTime = new Date(runningNode.started_at);
        let animationId;

        const updateTimer = () => {
            const elapsed = Math.floor((Date.now() - startTime) / 1000);
            const minutes = Math.floor(elapsed / 60);
            const seconds = elapsed % 60;
            timerEl.textContent = minutes > 0 ? `${minutes}m ${seconds}s` : `${seconds}s`;
            animationId = requestAnimationFrame(updateTimer);
        };

        updateTimer();

        // Store animationId for cleanup
        banner.dataset.animationId = animationId;
    } else {
        banner.style.display = 'none';
    }
}

function setupLiveUpdates(runId, dagRenderer, nodes, channelPanel, chatPanel) {
    // Store retry history per node for the Retry History tab
    const retryHistoryStore = {};

    // Subscribe to per-run SSE stream for live events (node_progress, node_update, etc.)
    const eventSource = new EventSource(`/api/workflows/${runId}/events`);

    eventSource.onmessage = (event) => {
        try {
            const evt = JSON.parse(event.data);

            // SSE shape-detection: handle both persisted (string payload) and live (object payload) events
            const isPersisted = typeof evt.payload === 'string';
            const payload = isPersisted ? JSON.parse(evt.payload) : evt;
            const eventType = isPersisted ? evt.event_type : evt.type;

            // Route chat_message events to appropriate panel
            if (eventType === 'chat_message') {
                // If payload has node_id and node detail panel is open for that node, route to node panel
                if (payload.node_id && window.nodeDetailPanel?.currentNode?.id === payload.node_id) {
                    window.nodeDetailPanel.appendChatMessage(payload);
                } else if (chatPanel) {
                    // Otherwise route to workflow chat panel
                    chatPanel.handleSSEMessage(payload);
                }
            } else if (eventType === 'node_progress' && payload.metadata && payload.metadata.attempt != null) {
                // This is a retry event (not a token-stream event)
                const nodeName = payload.node_id;
                const meta = payload.metadata;
                const retryState = {
                    attempt: meta.attempt,
                    max_attempts: meta.max_attempts,
                    delay_ms: meta.delay_ms,
                    last_error: meta.last_error,
                    timestamp: evt.created_at || payload.timestamp
                };

                // Accumulate retry history
                if (!retryHistoryStore[nodeName]) {
                    retryHistoryStore[nodeName] = [];
                }
                retryHistoryStore[nodeName].push(retryState);

                // Update retry overlay on the DAG
                if (dagRenderer.updateRetryProgress) {
                    dagRenderer.updateRetryProgress(nodeName, retryState);
                }
            } else if (eventType === 'node_update') {
                // Update node status
                const nodeName = payload.node_id;
                const status = payload.metadata?.status || payload.status;
                if (dagRenderer.updateNodeStatus) {
                    dagRenderer.updateNodeStatus(nodeName, status);
                }
            } else if (eventType === 'node_completed' || eventType === 'node_failed') {
                // Clear retry overlay when node finishes
                const nodeName = payload.node_id;
                if (dagRenderer.clearRetryProgress) {
                    dagRenderer.clearRetryProgress(nodeName);
                }
            } else if (eventType === 'workflow_completed' || eventType === 'workflow_failed' || eventType === 'workflow_cancelled') {
                // Hide cancel button when workflow reaches terminal state
                const cancelButtonContainer = document.getElementById('cancel-button-container');
                if (cancelButtonContainer && window.hideCancelButton) {
                    window.hideCancelButton(cancelButtonContainer);
                }

                // Show retry button if workflow failed
                if (eventType === 'workflow_failed') {
                    const retryButtonContainer = document.getElementById('retry-button-container');
                    if (retryButtonContainer && window.renderRetryButton) {
                        window.renderRetryButton(retryButtonContainer, runId, 'failed');
                    }
                }
            }
        } catch (error) {
            console.error('Error parsing SSE event:', error, event.data);
        }
    };

    eventSource.onerror = (error) => {
        console.error('SSE connection error:', error);
        eventSource.close();
    };

    // Expose retry history store for node detail panel
    window.retryHistoryStore = retryHistoryStore;

    // Poll periodically for updates (layout and channel states)
    const pollInterval = setInterval(async () => {
        try {
            // Fetch both layout and channel states in parallel
            const [layoutResp, channelsResp] = await Promise.all([
                fetch(`/api/workflows/${runId}/layout`),
                fetch(`/api/workflows/${runId}/channels`)
            ]);

            if (!layoutResp.ok) {
                clearInterval(pollInterval);
                return;
            }

            const layoutData = await layoutResp.json();

            // Update node statuses in the DAG
            layoutData.nodes.forEach(node => {
                dagRenderer.updateNodeStatus(node.node_name, node.status);
            });

            // Update executing banner
            setupExecutingBanner(layoutData.nodes);

            // Refresh state diff timeline
            const timelineContainer = document.getElementById('state-diff-timeline-container');
            if (timelineContainer && window.renderStateDiffTimeline) {
                window.renderStateDiffTimeline(timelineContainer, runId);
            }

            // Update channel state panel
            if (channelsResp.ok) {
                const channelsData = await channelsResp.json();
                if (channelPanel && channelsData.channels) {
                    channelPanel.update(channelsData.channels);
                }
            }

        } catch (error) {
            console.error('Error polling for updates:', error);
        }
    }, 2000); // Poll every 2 seconds

    // Cleanup on route change
    window.addEventListener('hashchange', () => {
        clearInterval(pollInterval);
        eventSource.close();
        delete window.retryHistoryStore;
        if (chatPanel) {
            chatPanel.destroy();
        }
    }, { once: true });
}

// Gate Indicator - Pulsing notification for pending gates
class GateIndicator {
    constructor() {
        this.indicator = document.getElementById('gate-indicator');
        this.pollInterval = null;
        this.init();
    }

    init() {
        // Start polling for pending gates
        this.poll();
        this.pollInterval = setInterval(() => this.poll(), 5000); // Poll every 5 seconds
    }

    async poll() {
        try {
            const response = await fetch('/api/gates/pending');
            if (!response.ok) return;

            const data = await response.json();
            this.update(data.count, data.gates);
        } catch (error) {
            console.error('Error polling pending gates:', error);
        }
    }

    update(count, gates) {
        if (count > 0) {
            this.indicator.textContent = count;
            this.indicator.classList.remove('hidden');

            // Add click handler to navigate to first pending gate
            if (gates && gates.length > 0) {
                this.indicator.onclick = () => {
                    const firstGate = gates[0];
                    window.location.hash = `/workflow/${firstGate.run_id}`;
                };
            }
        } else {
            this.indicator.classList.add('hidden');
            this.indicator.onclick = null;
        }
    }

    stop() {
        if (this.pollInterval) {
            clearInterval(this.pollInterval);
        }
    }
}

// Initialize gate indicator
const gateIndicator = new GateIndicator();

// Initialize search bars
if (window.SearchBar) {
    const desktopContainer = document.getElementById('search-bar-container-desktop');
    const mobileContainer = document.getElementById('search-bar-container-mobile');
    if (desktopContainer) SearchBar.init(desktopContainer);
    if (mobileContainer) SearchBar.init(mobileContainer);
}

// Initialize router
const router = new Router();
router.register('/', renderDashboard);
router.register('/history', renderHistory);
router.register('/workflows', window.renderWorkflowsList);
router.register('/workflows/:name', window.renderWorkflowDetail);
router.register('/workflow-trigger/:name', window.renderWorkflowTriggerForm);
router.register('/workflow/:runId', renderWorkflowDetail);
router.register('/checkpoints', renderCheckpointWorkflows);
router.register('/checkpoints/:wf', renderCheckpointRuns);
router.register('/checkpoints/:wf/:runId', renderCheckpointRunDetail);
router.register('/checkpoints/compare/:wf/:runIdA/:runIdB', renderCheckpointCompare);
router.register('/settings', function () {
    if (typeof window.renderSettings === 'function') {
        window.renderSettings();
    }
});

// Inspector demo route (off-nav, for testing until canvas lands)
router.register('/inspector-demo', async function () {
    const container = document.getElementById('route-container');
    container.innerHTML = '<div id="inspector-mount"></div>';

    // Fetch config to get allow_destructive_nodes
    let allowDestructive = false;
    try {
        const configResp = await fetch('/api/config');
        if (configResp.ok) {
            const config = await configResp.json();
            allowDestructive = config.allow_destructive_nodes || false;
        }
    } catch (err) {
        console.warn('Failed to fetch config:', err);
    }

    // Sample node for testing
    const sampleNode = {
        id: 'sample-node',
        name: 'Sample Node',
        type: 'bash',
        script: '#!/bin/bash\necho "Hello, world!"',
        retry: 3,
        on_failure: 'stop',
        depends_on: [],
        trigger_rule: 'all_success',
        timeout: 300,
        label: 'sample',
        checkpoint: false,
    };

    const availableNodeIds = ['node-1', 'node-2', 'sample-node'];

    const inspector = new window.NodeInspector({
        container: document.getElementById('inspector-mount'),
        node: sampleNode,
        allowDestructive: allowDestructive,
        availableNodeIds: availableNodeIds,
        onChange: (updatedNode) => {
            console.log('Node updated:', updatedNode);
        },
        onDelete: (nodeId) => {
            console.log('Node deleted:', nodeId);
        },
    });
});

// Builder feature flag handling
if (window.DAG_DASHBOARD_BUILDER_ENABLED) {
    // Unhide builder nav links
    document.querySelectorAll('[data-route="/builder"]').forEach(link => {
        link.classList.remove('hidden');
    });

    // Register builder route with lazy loading
    router.register('/builder', function () {
        const container = document.getElementById('route-container');
        if (!container) return;

        // Check if builder bundle is already loaded
        if (window.DAGDashboardBuilder) {
            window.DAGDashboardBuilder.mount(container);
            return;
        }

        // Load validation scripts first, then builder bundle
        // This ensures window.DAGDashboardValidation is available when toolbar mounts
        function loadValidationScripts(callback) {
            const scripts = [
                '/js/builder/validation-rules.js',
                '/js/builder/use-builder-validation.js',
                '/js/builder/validation-panel.js'
            ];

            let loadedCount = 0;

            function loadNext() {
                if (loadedCount >= scripts.length) {
                    callback();
                    return;
                }

                const script = document.createElement('script');
                script.src = scripts[loadedCount];
                script.onload = () => {
                    loadedCount++;
                    loadNext();
                };
                script.onerror = () => {
                    console.warn('Failed to load validation script:', scripts[loadedCount]);
                    loadedCount++;
                    loadNext();
                };
                document.head.appendChild(script);
            }

            loadNext();
        }

        // Load validation scripts, then builder bundle
        loadValidationScripts(() => {
            const script = document.createElement('script');
            script.src = '/js/builder/builder.js';
            script.onload = () => {
                if (window.DAGDashboardBuilder) {
                    window.DAGDashboardBuilder.mount(container);
                } else {
                    container.innerHTML = '<div class="error">Builder bundle loaded but not initialized</div>';
                }
            };
            script.onerror = () => {
                container.innerHTML = '<div class="error">Failed to load builder bundle</div>';
            };
            document.head.appendChild(script);
        });
    });
}

// Mobile menu toggle
document.getElementById('mobile-menu-toggle')?.addEventListener('click', () => {
    const mobileNav = document.getElementById('mobile-nav');
    mobileNav?.classList.toggle('hidden');
});

// Subscribe to state changes
store.subscribe((state) => {
    // Re-render current route when state changes
    router.handleRoute();
});
