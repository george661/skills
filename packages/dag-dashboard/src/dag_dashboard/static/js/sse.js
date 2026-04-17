/**
 * SSE (Server-Sent Events) connection with auto-reconnect and reconciliation
 */

class SSEConnection {
    constructor(url, store) {
        this.url = url;
        this.store = store;
        this.eventSource = null;
        this.reconnectDelay = 1000; // Start at 1 second
        this.maxReconnectDelay = 30000; // Max 30 seconds
        this.reconnectAttempts = 0;
        this.connected = false;
        
        this.connect();
    }

    connect() {
        console.log('[SSE] Connecting to', this.url);
        
        try {
            this.eventSource = new EventSource(this.url);
            
            this.eventSource.onopen = () => {
                console.log('[SSE] Connected');
                this.connected = true;
                this.reconnectDelay = 1000; // Reset backoff
                this.reconnectAttempts = 0;
                this.store.setState({ connected: true });
            };
            
            this.eventSource.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    this.handleEvent(data);
                } catch (error) {
                    console.error('[SSE] Failed to parse event:', error);
                }
            };
            
            this.eventSource.onerror = (error) => {
                console.error('[SSE] Connection error:', error);
                this.connected = false;
                this.store.setState({ connected: false });
                this.eventSource?.close();
                this.scheduleReconnect();
            };
        } catch (error) {
            console.error('[SSE] Failed to create EventSource:', error);
            this.scheduleReconnect();
        }
    }

    handleEvent(data) {
        console.log('[SSE] Received event:', data);
        
        // Handle different event types
        if (data.type === 'workflow_update') {
            this.updateWorkflow(data.payload);
        } else if (data.type === 'node_update') {
            this.updateNodeState(data.payload);
        } else if (data.type === 'heartbeat') {
            // Heartbeat - connection is alive
            console.log('[SSE] Heartbeat received');
        }
    }

    updateWorkflow(payload) {
        const state = this.store.getState();
        const workflows = state.workflows.map(wf => 
            wf.run_id === payload.run_id ? { ...wf, ...payload } : wf
        );
        
        // If workflow not in list, add it
        if (!workflows.find(wf => wf.run_id === payload.run_id)) {
            workflows.push(payload);
        }
        
        this.store.setState({ workflows });
    }

    updateNodeState(payload) {
        const state = this.store.getState();
        const nodeStates = {
            ...state.nodeStates,
            [payload.node_id]: payload
        };
        this.store.setState({ nodeStates });
    }

    scheduleReconnect() {
        this.reconnectAttempts++;
        const delay = Math.min(
            this.reconnectDelay * Math.pow(2, this.reconnectAttempts - 1),
            this.maxReconnectDelay
        );
        
        console.log(`[SSE] Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts})`);
        
        setTimeout(() => {
            this.reconcileState().then(() => {
                this.connect();
            });
        }, delay);
    }

    async reconcileState() {
        // Fetch current state from REST API to sync after disconnect
        console.log('[SSE] Reconciling state via REST API');
        
        try {
            const response = await fetch('/api/workflows');
            if (response.ok) {
                const workflows = await response.json();
                this.store.setState({ workflows });
                console.log('[SSE] State reconciled');
            }
        } catch (error) {
            console.error('[SSE] Failed to reconcile state:', error);
        }
    }

    disconnect() {
        if (this.eventSource) {
            console.log('[SSE] Disconnecting');
            this.eventSource.close();
            this.eventSource = null;
            this.connected = false;
            this.store.setState({ connected: false });
        }
    }
}

// Initialize SSE connection when store is available
if (typeof store !== 'undefined') {
    const sseConnection = new SSEConnection('/api/events', store);
    
    // Cleanup on page unload
    window.addEventListener('beforeunload', () => {
        sseConnection.disconnect();
    });
}
