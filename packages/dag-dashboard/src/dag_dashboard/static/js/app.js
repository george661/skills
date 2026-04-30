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

        if (hash.startsWith('/conversations/')) {
            const conversationId = hash.split('/')[2];
            this.currentRoute = '/conversations/:id';
            if (this.routes['/conversations/:id']) {
                this.routes['/conversations/:id'](conversationId);
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

// Stale-render guard: async renderers capture the hash on entry and bail
// before writing to #route-container if the user has navigated away. Without
// this, an in-flight fetch from a prior route can land after the new route's
// renderer has already painted and clobber its DOM.
function renderStillActive(hashAtEntry) {
    return (window.location.hash.slice(1) || '/') === (hashAtEntry || '/');
}

// Route handlers
async function renderDashboard() {
    const container = document.getElementById('route-container');
    const hashAtEntry = window.location.hash.slice(1) || '/';

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
            <div class="workflow-card workflow-card-link" style="position: relative;">
                <a href="#/workflow/${escapeHtml(wf.id)}" style="text-decoration: none; color: inherit; display: block;">
                    <div class="workflow-title">${escapeHtml(wf.workflow_name)}</div>
                    <span class="workflow-status ${escapeHtml(wf.status)}">${escapeHtml(wf.status)}</span>
                    <div style="margin-top: 0.5rem; color: var(--text-secondary); font-size: 0.875rem;">
                        ${wf.started_at ? new Date(wf.started_at).toLocaleString() : 'No start time'}
                    </div>
                    <div style="margin-top: 0.5rem; color: var(--text-secondary); font-size: 0.75rem; font-family: monospace;">
                        ${escapeHtml(wf.id.slice(0, 8))}…
                    </div>
                </a>
                <button
                    class="card-cancel-button"
                    data-run-id="${escapeHtml(wf.id)}"
                    title="Cancel this run"
                    style="position: absolute; top: 0.5rem; right: 0.5rem; background: transparent; border: 1px solid var(--border); color: var(--text-secondary); border-radius: 0.25rem; padding: 0.15rem 0.5rem; font-size: 0.75rem; cursor: pointer;">
                    Cancel
                </button>
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

    if (!renderStillActive(hashAtEntry)) return;
    container.innerHTML = `
        <h2 style="margin-bottom: 1.5rem;">Dashboard</h2>
        ${summaryCards}
        ${activeWorkflowsHTML}
    `;

    // Wire inline Cancel buttons on active-workflow cards (bypass navigating
    // into the run detail page for a one-off stuck run).
    document.querySelectorAll('.card-cancel-button').forEach(btn => {
        btn.addEventListener('click', async (e) => {
            e.preventDefault();
            e.stopPropagation();
            const runId = btn.dataset.runId;
            if (!runId) return;
            if (!window.confirm(`Cancel run ${runId.slice(0, 8)}…? The running process will be terminated.`)) {
                return;
            }
            btn.disabled = true;
            btn.textContent = 'Cancelling…';
            try {
                const resp = await fetch(`/api/workflows/${runId}/cancel`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                });
                if (!resp.ok) {
                    const body = await resp.text();
                    throw new Error(`HTTP ${resp.status}: ${body.slice(0, 200)}`);
                }
                // Re-render the dashboard to drop this card from Active Workflows
                renderDashboard();
            } catch (err) {
                btn.disabled = false;
                btn.textContent = 'Cancel';
                alert(`Failed to cancel run: ${err.message}`);
            }
        });
    });

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
    const hashAtEntry = window.location.hash.slice(1) || '/';

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

    if (!renderStillActive(hashAtEntry)) return;
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

    // Row click navigates to the run-detail page. Rendering already stamps
    // data-run-id on every <tr>; just wire the handler once.
    document.querySelectorAll('tr.history-row[data-run-id]').forEach(row => {
        row.style.cursor = 'pointer';
        row.addEventListener('click', () => {
            const runId = row.dataset.runId;
            if (runId) window.location.hash = `/workflow/${runId}`;
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

// Module-level active lifecycle for force-remount on runId change (AC-8)
let activeLifecycle = null;

async function renderRunDetail(runId) {
    // Destroy previous lifecycle if re-entering
    if (activeLifecycle) {
        activeLifecycle.destroy();
        activeLifecycle = null;
    }

    const container = document.getElementById('route-container');

    // No tabs. Archon-style: the run-detail page is a single three-column
    // view (DAG + state rail + live trace). Per-node drill-down happens via
    // the slide-out NodeDetailPanel triggered by clicking a DAG node — it
    // already carries structured StepLogs / retry history / artifacts, so
    // the dedicated Logs tab was redundant. The trace rail scrolls to the
    // clicked node's card too so both surfaces respond to the click.

    container.innerHTML = `
        <div class="run-detail">
            <!-- Header -->
            <div class="run-detail-header">
                <a href="#/" class="run-detail-back" title="Back">
                    &larr;
                </a>
                <h2 id="run-detail-title" class="run-detail-title">Workflow Run</h2>
                <span id="run-detail-status" class="run-detail-status-badge"></span>
                <div class="run-detail-header-spacer"></div>
                <span id="run-detail-elapsed" class="run-detail-elapsed"></span>
                <div id="cancel-button-container" class="cancel-button-container"></div>
                <div id="retry-button-container" class="retry-button-container"></div>
                <button id="rerun-button" class="btn btn-secondary" style="display: none;">Re-run</button>
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
            <!-- GW-5422: Two-pane layout with ResizableSplit (DAG | unified feed).
                 State channels/timeline/artifacts moved to slide-over panel. -->
            <div class="run-pane-split">
                <div class="run-pane-left">
                    <div class="run-graph-canvas">
                        <div id="dag-container"></div>
                    </div>
                    <button id="state-slideover-toggle" class="btn btn-secondary state-slideover-toggle-btn">
                        View State
                    </button>
                </div>
                <div class="run-pane-right">
                    <div class="unified-feed-header">
                        <h3 class="run-side-heading">Workflow Progress</h3>
                    </div>
                    <div id="workflow-progress-card-container" class="workflow-progress-card-container"></div>
                    <div id="run-chat-section" class="run-chat-section">
                        <div class="run-chat-section-head">
                            <h3 class="run-side-heading" style="margin: 0;">Talk to orchestrator</h3>
                            <span class="run-chat-section-hint">Ask questions or provide direction. Messages are visible to the workflow.</span>
                        </div>
                        <div id="workflow-chat-container" class="workflow-chat-container"></div>
                    </div>
                </div>
            </div>
            <!-- State slideover (eager mount - containers exist in DOM from page load) -->
            <div id="state-slideover-mount"></div>
            <div class="run-detail-id-strip">
                <span class="run-detail-id-label">Run ID:</span>
                <code>${escapeHtml(runId)}</code>
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

        // Normalize layoutData so the rest of the code (DAGRenderer) doesn't
        // need to guard against an empty run whose snapshot hasn't been
        // persisted yet (trigger→spawn races, fresh fixtures).
        if (!layoutData.nodes) layoutData.nodes = [];
        if (!layoutData.edges) layoutData.edges = [];

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

        // Populate tabbed-layout header bits (title / status badge / elapsed).
        const run = workflowData.run || {};
        const titleEl = document.getElementById('run-detail-title');
        if (titleEl) titleEl.textContent = run.workflow_name || 'Workflow Run';
        const statusEl = document.getElementById('run-detail-status');
        if (statusEl && run.status) {
            statusEl.textContent = run.status;
            statusEl.classList.add(run.status);
        }
        const elapsedEl = document.getElementById('run-detail-elapsed');
        if (elapsedEl && run.started_at) {
            const start = new Date(run.started_at).getTime();
            const end = run.finished_at ? new Date(run.finished_at).getTime() : Date.now();
            const secs = Math.max(0, Math.round((end - start) / 1000));
            const mm = Math.floor(secs / 60);
            const ss = secs % 60;
            elapsedEl.textContent = mm > 0 ? `${mm}m ${ss}s` : `${ss}s`;
        }

        // Render totals strip
        if (workflowData.totals) {
            renderTotals(workflowData.totals);
        }

        // Surface conversation context — link to conversation view + sibling runs
        if (workflowData.run && workflowData.run.conversation_id) {
            const convId = workflowData.run.conversation_id;
            let siblingRuns = [];
            try {
                const convResp = await fetch(`/api/conversations/${convId}`);
                if (convResp.ok) {
                    const data = await convResp.json();
                    siblingRuns = (data.runs || []).filter(r => r.id !== runId);
                }
            } catch (_) {
                /* non-fatal */
            }
            const siblingMarkup = siblingRuns.length > 0
                ? `<div style="margin-top: 0.5rem; font-size: 0.875rem;">
                     <span style="color: var(--text-secondary);">Other runs in this conversation: </span>
                     ${siblingRuns.slice(0, 5).map(r =>
                        `<a href="#/workflow/${escapeHtml(r.id)}" style="color: var(--primary); text-decoration: none; margin-right: 0.75rem;">
                            ${escapeHtml(r.workflow_name)} <small>(${escapeHtml(r.status)})</small>
                         </a>`
                     ).join('')}
                   </div>`
                : '';
            const banner = document.createElement('div');
            banner.className = 'conversation-context-banner';
            banner.style.cssText = 'margin-bottom: 1rem; padding: 0.75rem 1rem; background: var(--bg-card); border: 1px solid var(--border); border-radius: var(--radius);';
            banner.innerHTML = `
                <div>
                    <strong>💬 Conversation:</strong>
                    <a href="#/conversations/${escapeHtml(convId)}" style="color: var(--primary); text-decoration: none; margin-left: 0.5rem;">
                        view full conversation →
                    </a>
                    <code style="margin-left: 0.75rem; font-size: 0.75rem; color: var(--text-secondary);">${escapeHtml(convId.slice(0, 12))}…</code>
                </div>
                ${siblingMarkup}
            `;
            const dagContainer = document.getElementById('dag-container');
            if (dagContainer && dagContainer.parentNode) {
                dagContainer.parentNode.insertBefore(banner, dagContainer);
            }
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

        // Mount state slideover (eager mount - containers in DOM from page load)
        if (window.StateSlideover) {
            window.StateSlideover.mount('state-slideover-mount');
        }

        // Initialize channel state panel (now inside slideover)
        const channelPanel = new window.ChannelStatePanel('channel-state-container');

        // Initialize WorkflowProgressCard (unified feed replacing TracePanel)
        let progressCard = null;
        if (window.WorkflowProgressCard) {
            progressCard = new window.WorkflowProgressCard('workflow-progress-card-container', runId);

            // Setup cross-selection with DAG via NodeScrollBus
            const nodeScrollBus = window.NodeScrollBus ? window.NodeScrollBus.getInstance() : null;
            if (nodeScrollBus) {
                nodeScrollBus.subscribe((nodeId, source) => {
                    if (source === 'dag' && progressCard) {
                        progressCard.scrollToNode(nodeId);
                    }
                });

                // Wire DAG node clicks to bus
                if (dagRenderer && typeof dagRenderer.container !== 'undefined') {
                    dagRenderer.container.addEventListener('click', (e) => {
                        const group = e.target.closest('.dag-node');
                        if (!group) return;
                        const nodeName = group.getAttribute('data-node-name');
                        if (nodeName) nodeScrollBus.notifyNodeClicked(nodeName);
                    });
                }
            }
        }

        // Keep tracePanel stub for backward compatibility (will be removed in future PR)
        const tracePanel = progressCard || { handleSSEMessage: () => {}, destroy: () => {} };
        // Mount a real ChatPanel under the trace so users can talk to the
        // orchestrator without leaving the run page. Escalated-card buttons
        // scroll this into view via the 'trace-chat-request' CustomEvent.
        let chatPanel;
        if (window.ChatPanel) {
            try {
                chatPanel = new window.ChatPanel('workflow-chat-container', runId);
                if (typeof chatPanel.render === 'function') chatPanel.render();
            } catch (err) {
                console.warn('ChatPanel failed to mount:', err);
                chatPanel = { handleSSEMessage: () => {}, destroy: () => {} };
            }
        } else {
            chatPanel = { handleSSEMessage: () => {}, destroy: () => {} };
        }

        // Escalated-card "Talk to orchestrator" button → scroll + focus.
        window.addEventListener('trace-chat-request', (ev) => {
            const sec = document.getElementById('run-chat-section');
            if (sec) {
                sec.scrollIntoView({ behavior: 'smooth', block: 'center' });
                sec.classList.add('run-chat-section-flash');
                setTimeout(() => sec.classList.remove('run-chat-section-flash'), 1500);
            }
            // Optionally prefill with a useful seed mentioning the node+error.
            // Keep it a single line — the server's ChatMessageRequest
            // validator rejects newlines + a handful of shell metacharacters,
            // so we strip them client-side to avoid an HTTP 422.
            const input = document.querySelector('#workflow-chat-container textarea, #workflow-chat-container input[type=text]');
            if (input && !input.value && ev.detail) {
                const err = (ev.detail.error || 'no-error').toString();
                const safe = (s) => String(s)
                    .replace(/\s+/g, ' ')
                    .replace(/[`$();|&<>\\]/g, '')
                    .replace(/:/g, '-')
                    .trim();
                const seed = `Node ${safe(ev.detail.nodeId)} escalated - ${safe(err).slice(0, 240)}. How should I proceed?`;
                input.value = seed;
                input.focus();
            }
        });

        // Render workflow-aggregated artifacts
        if (window.ArtifactList) {
            window.ArtifactList.render('run-artifacts-container', runId);
        }

        // Initialize resizable split for the new two-pane layout (GW-5422)
        const splitContainer = document.querySelector('.run-pane-split');
        let resizableSplit = null;
        if (splitContainer && window.ResizableSplit) {
            resizableSplit = new window.ResizableSplit(splitContainer, {
                defaultSplit: 60,
                minSplit: 20,
                maxSplit: 80,
                storageKey: 'dag-dashboard.run-detail.split',
                mobileBreakpoint: 1024
            });
        }

        // Wire up state slideover toggle button
        const slideoverToggleBtn = document.getElementById('state-slideover-toggle');
        if (slideoverToggleBtn && window.StateSlideover) {
            slideoverToggleBtn.addEventListener('click', () => {
                window.StateSlideover.toggle();
            });
        }

        // Connect to SSE for live updates
        const lifecycle = setupLiveUpdates(runId, dagRenderer, layoutData.nodes, channelPanel, chatPanel, resizableSplit, tracePanel);
        activeLifecycle = lifecycle;

    } catch (error) {
        console.error('Error loading workflow detail:', error);
        // Use insertAdjacentHTML — re-serializing innerHTML would destroy the
        // click listeners already attached to the tab buttons.
        container.insertAdjacentHTML('beforeend', `
            <div style="padding: 1rem; background: var(--error); color: white; border-radius: var(--radius); margin-top: 1rem;">
                Error loading workflow: ${escapeHtml(error.message)}
            </div>
        `);
    }
}

async function renderConversationsList() {
    const container = document.getElementById('route-container');
    container.innerHTML = `
        <h2 style="margin-bottom: 1.5rem;">Conversations</h2>
        <div id="conversations-content">
            <div class="loading-spinner">Loading conversations…</div>
        </div>
    `;

    let conversations = [];
    try {
        const resp = await fetch('/api/conversations');
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        conversations = await resp.json();
    } catch (err) {
        document.getElementById('conversations-content').innerHTML =
            `<div class="error-message">Failed to load conversations: ${escapeHtml(err.message)}</div>`;
        return;
    }

    const content = document.getElementById('conversations-content');
    if (!conversations || conversations.length === 0) {
        content.innerHTML = `
            <div class="empty-state" style="padding: 2rem 1rem;">
                <div class="empty-state-icon">💬</div>
                <div class="empty-state-text">
                    No conversations yet. Run a workflow that emits chat messages to start one.
                </div>
            </div>`;
        return;
    }

    const fmt = (ts) => ts ? new Date(ts).toLocaleString() : '—';
    const rows = conversations.map(c => {
        const latest = c.latest_message_at || c.latest_started_at || c.created_at;
        return `
            <tr class="history-row" data-conversation-id="${escapeHtml(c.id)}" style="cursor: pointer;">
                <td class="history-cell">${escapeHtml(c.latest_workflow_name || '—')}</td>
                <td class="history-cell"><span class="workflow-status ${c.closed_at ? 'completed' : 'running'}">${c.closed_at ? 'closed' : 'open'}</span></td>
                <td class="history-cell">${fmt(latest)}</td>
                <td class="history-cell">${c.run_count}</td>
                <td class="history-cell">${c.message_count}</td>
                <td class="history-cell"><code style="font-size: 0.75rem; color: var(--text-secondary);">${escapeHtml(c.id.slice(0, 8))}…</code></td>
            </tr>`;
    }).join('');

    content.innerHTML = `
        <table class="history-table">
            <thead>
                <tr>
                    <th class="history-header">Workflow</th>
                    <th class="history-header">State</th>
                    <th class="history-header">Last Activity</th>
                    <th class="history-header">Runs</th>
                    <th class="history-header">Messages</th>
                    <th class="history-header">ID</th>
                </tr>
            </thead>
            <tbody>${rows}</tbody>
        </table>`;

    document.querySelectorAll('tr.history-row[data-conversation-id]').forEach(row => {
        row.addEventListener('click', () => {
            const id = row.dataset.conversationId;
            if (id) window.location.hash = `/conversations/${id}`;
        });
    });
}

async function renderConversationDetail(conversationId) {
    const container = document.getElementById('route-container');

    container.innerHTML = `
        <div>
            <a href="#/" style="color: var(--primary); text-decoration: none; display: inline-block; margin-bottom: 1rem;">
                ← Back to Dashboard
            </a>
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 1.5rem;">
                <h2 style="margin: 0;">Conversation View</h2>
            </div>
            <div style="margin-bottom: 1rem; padding: 1rem; background: var(--bg-card); border-radius: var(--radius); border: 1px solid var(--border);">
                <h3 style="margin-bottom: 0.5rem;">Conversation ID:</h3>
                <code style="color: var(--text-secondary);">${escapeHtml(conversationId)}</code>
            </div>
            <section id="chat-container" class="chat-section"></section>
        </div>
    `;

    try {
        // Initialize chat panel in conversation mode
        const chatPanel = new window.ChatPanel('chat-container', {
            mode: 'conversation',
            conversationId: conversationId
        });
        chatPanel.render();

    } catch (error) {
        console.error('Error loading conversation:', error);
        container.innerHTML += `
            <div style="padding: 1rem; background: var(--error); color: white; border-radius: var(--radius); margin-top: 1rem;">
                Error loading conversation: ${escapeHtml(error.message)}
            </div>
        `;
    }
}

function setupExecutingBanner(nodes) {
    const banner = document.getElementById('executing-banner');
    const nodeNameEl = document.getElementById('executing-node-name');
    const modelEl = document.getElementById('executing-model');
    const timerEl = document.getElementById('executing-timer');

    // Cancel existing animation frame if present (prevent leak on re-render)
    if (banner && banner.dataset.animationId) {
        const oldId = parseInt(banner.dataset.animationId, 10);
        if (!isNaN(oldId)) {
            cancelAnimationFrame(oldId);
        }
        delete banner.dataset.animationId;
    }

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

function setupLiveUpdates(runId, dagRenderer, nodes, channelPanel, chatPanel, resizableSplit, tracePanel) {
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

            // Forward every event to the live trace panel. The panel knows
            // which event_types it cares about; unknown ones are dropped.
            // We normalize to the NDJSON shape (event_type + node_id + metadata
            // at the top level) so persisted and live events look identical.
            if (tracePanel) {
                try {
                    tracePanel.handleEvent({
                        event_type: eventType,
                        node_id: payload.node_id,
                        model: payload.model,
                        dispatch: payload.dispatch,
                        duration_ms: payload.duration_ms,
                        timestamp: payload.timestamp || evt.created_at,
                        metadata: payload.metadata || payload,
                    });
                } catch (e) {
                    console.warn('trace panel event handling failed', e);
                }
            }

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

            // Re-render the whole DAG when node topology changes (e.g. the
            // initial layout returned 0 nodes because node_executions wasn't
            // populated yet, or new conditionally-routed nodes showed up).
            // updateNodeStatus is a no-op for unknown nodes, so without this
            // the graph stays blank for the lifetime of the page.
            const renderedNodeCount =
                (dagRenderer.g && dagRenderer.g.querySelectorAll('.dag-node').length) || 0;
            if (renderedNodeCount !== layoutData.nodes.length) {
                dagRenderer.render(layoutData);
            } else {
                layoutData.nodes.forEach(node => {
                    dagRenderer.updateNodeStatus(node.node_name, node.status);
                });
            }

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

    // Create lifecycle object for cleanup (AC-8: force remount on runId change)
    const lifecycle = {
        destroy: () => {
            // Clear interval
            clearInterval(pollInterval);

            // Close EventSource
            eventSource.close();

            // Clean up retry history
            delete window.retryHistoryStore;

            // Destroy chat panel
            if (chatPanel) {
                chatPanel.destroy();
            }

            // Destroy resizable split
            if (resizableSplit) {
                resizableSplit.destroy();
            }

            // Destroy trace panel (clears per-node + banner timers so SPA
            // navigation between runs doesn't leak intervals).
            if (tracePanel && typeof tracePanel.destroy === 'function') {
                tracePanel.destroy();
            }

            // Cancel executing banner animation frame (fix existing leak)
            const banner = document.getElementById('executing-banner');
            if (banner && banner.dataset.animationId) {
                const animationId = parseInt(banner.dataset.animationId, 10);
                if (!isNaN(animationId)) {
                    cancelAnimationFrame(animationId);
                }
                delete banner.dataset.animationId;
            }
        }
    };

    // Cleanup on route change (hashchange away from this run)
    window.addEventListener('hashchange', () => {
        lifecycle.destroy();
    }, { once: true });

    return lifecycle;
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
router.register('/workflow/:runId', renderRunDetail);
router.register('/conversations', renderConversationsList);
router.register('/conversations/:id', renderConversationDetail);
router.register('/checkpoints', renderCheckpointWorkflows);
router.register('/checkpoints/:wf', renderCheckpointRuns);
router.register('/checkpoints/:wf/:runId', renderCheckpointRunDetail);
router.register('/checkpoints/compare/:wf/:runIdA/:runIdB', renderCheckpointCompare);
router.register('/settings', function () {
    if (typeof window.renderSettings === 'function') {
        window.renderSettings();
    }
});

// Note: the Router constructor calls handleRoute() before any routes are
// registered, so a deep-link like /#/workflows or /#/builder/demo initially
// matches no handler. A single redispatch at the bottom of this file (after
// *all* routes — including the feature-flagged builder route — register)
// handles every deep-link uniformly.

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

    // Register builder route with lazy loading. Deep-link redispatch is handled
    // by a single handleRoute() call at the bottom of this file, after every
    // route (including this one) is registered.

    router.register('/builder', function () {
        const container = document.getElementById('route-container');
        if (!container) return;

        // Bare /#/builder with no workflow context — show a picker. A
        // ?workflow=<name> query param is the legacy way to pass the workflow
        // (still used by Playwright fixtures), so only show the picker when
        // BOTH hash path and query string lack a workflow name.
        const hashPath = (window.location.hash.slice(1) || '/').split('?')[0];
        const legacyWorkflow = new URLSearchParams(window.location.search).get('workflow');
        if (hashPath === '/builder' && !legacyWorkflow) {
            container.innerHTML = `
                <div style="padding: 2rem;">
                    <h2>Open a workflow in the builder</h2>
                    <p>Pick a workflow from the <a href="#/workflows">Workflows</a> list and
                    click <strong>Edit in Builder</strong> to open it here.</p>
                </div>`;
            return;
        }

        // Check if builder bundle is already loaded
        if (window.DAGDashboardBuilder) {
            window.DAGDashboardBuilder.mount(container);
            return;
        }

        // Load scripts sequentially: builder bundle first (ships React + exposes it on window),
        // THEN the classical-React validation scripts which need window.React to register
        // window.DAGDashboardValidation.useBuilderValidation and .ValidationPanel. Finally,
        // mount the builder.
        function loadScriptSeq(srcs, onDone) {
            let i = 0;
            function next() {
                if (i >= srcs.length) { onDone(); return; }
                const s = document.createElement('script');
                s.src = srcs[i];
                s.onload = () => { i++; next(); };
                s.onerror = () => {
                    console.warn('Failed to load script:', srcs[i]);
                    i++; next();
                };
                document.head.appendChild(s);
            }
            next();
        }

        loadScriptSeq(
            [
                '/js/builder/builder.js',
                '/js/builder/validation-rules.js',
                '/js/builder/use-builder-validation.js',
                '/js/builder/validation-panel.js',
            ],
            () => {
                if (window.DAGDashboardBuilder) {
                    window.DAGDashboardBuilder.mount(container);
                } else {
                    container.innerHTML = '<div class="error">Builder bundle loaded but not initialized</div>';
                }
            }
        );
    });

}

// The Router constructor calls handleRoute() before any routes are registered,
// so `router.currentRoute` is null when that dispatch found no handler. Only
// redispatch in that case — otherwise we risk firing renderDashboard twice in
// parallel with the subsequent hashchange-driven render (the second one's
// async fetch can land after the real renderer and clobber #route-container).
if (router.currentRoute === null) {
    router.handleRoute();
}

// Mobile menu toggle
document.getElementById('mobile-menu-toggle')?.addEventListener('click', () => {
    const mobileNav = document.getElementById('mobile-nav');
    mobileNav?.classList.toggle('hidden');
});

// Theme toggle — inline head-script applied the initial theme to avoid FOUC.
// This just wires the header button and persists the user's choice.
(function setupThemeToggle() {
    const btn = document.getElementById('theme-toggle');
    if (!btn) return;
    const iconSpan = btn.querySelector('.theme-toggle-icon');
    const renderIcon = () => {
        const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
        if (iconSpan) iconSpan.textContent = isDark ? '☀️' : '🌙';
        btn.setAttribute('aria-pressed', isDark ? 'true' : 'false');
    };
    renderIcon();
    btn.addEventListener('click', () => {
        const next = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
        document.documentElement.setAttribute('data-theme', next);
        try {
            localStorage.setItem('dag-dashboard-theme', next);
        } catch (_) { /* ignore */ }
        renderIcon();
    });
})();

// Subscribe to state changes
store.subscribe((state) => {
    // Re-render current route when state changes
    router.handleRoute();
});
