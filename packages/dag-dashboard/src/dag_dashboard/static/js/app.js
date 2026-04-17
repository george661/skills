/**
 * DAG Dashboard SPA - Router and State Management
 */

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
        if (hash.startsWith('/workflow/')) {
            const runId = hash.split('/')[2];
            this.currentRoute = '/workflow/:runId';
            if (this.routes['/workflow/:runId']) {
                this.routes['/workflow/:runId'](runId);
            }
            return;
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
function renderDashboard() {
    const container = document.getElementById('route-container');
    const state = store.getState();
    
    if (state.workflows.length === 0) {
        container.innerHTML = `
            <div class="empty-state">
                <div class="empty-state-icon">📊</div>
                <div class="empty-state-text">No workflows yet</div>
            </div>
        `;
        return;
    }
    
    const workflowCards = state.workflows.map(wf => `
        <div class="workflow-card">
            <div class="workflow-title">${wf.run_id || wf.id}</div>
            <span class="workflow-status ${wf.status}">${wf.status}</span>
            <div style="margin-top: 0.5rem; color: var(--text-secondary); font-size: 0.875rem;">
                ${wf.started_at ? new Date(wf.started_at).toLocaleString() : 'No start time'}
            </div>
        </div>
    `).join('');
    
    container.innerHTML = `
        <h2 style="margin-bottom: 1.5rem;">Active Workflows</h2>
        <div class="workflow-list">
            ${workflowCards}
        </div>
    `;
}

function renderHistory() {
    const container = document.getElementById('route-container');
    const state = store.getState();
    
    container.innerHTML = `
        <h2 style="margin-bottom: 1.5rem;">Workflow History</h2>
        <div class="empty-state">
            <div class="empty-state-icon">📜</div>
            <div class="empty-state-text">History view - Coming soon</div>
        </div>
    `;
}

function renderWorkflowDetail(runId) {
    const container = document.getElementById('route-container');
    const state = store.getState();
    
    container.innerHTML = `
        <div>
            <a href="#/" style="color: var(--primary); text-decoration: none; display: inline-block; margin-bottom: 1rem;">
                ← Back to Dashboard
            </a>
            <h2 style="margin-bottom: 1.5rem;">Workflow Detail</h2>
            <div class="workflow-card">
                <div class="workflow-title">Run ID: ${runId}</div>
                <div style="margin-top: 0.5rem; color: var(--text-secondary);">
                    Details will be populated from API
                </div>
            </div>
        </div>
    `;
}

// Initialize router
const router = new Router();
router.register('/', renderDashboard);
router.register('/history', renderHistory);
router.register('/workflow/:runId', renderWorkflowDetail);

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

// Fetch initial data
async function loadWorkflows() {
    try {
        const response = await fetch('/api/workflows');
        if (response.ok) {
            const workflows = await response.json();
            store.setState({ workflows });
        }
    } catch (error) {
        console.error('Failed to load workflows:', error);
    }
}

// Load data on startup
loadWorkflows();
