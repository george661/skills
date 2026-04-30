/**
 * DAG Renderer - SVG-based visualization with zoom/pan
 */

/**
 * Calculate new scale for pinch-to-zoom gesture.
 *
 * @param {number} currentDistance - Current distance between touch points
 * @param {number} initialDistance - Initial distance between touch points
 * @param {number} initialScale - Scale at gesture start
 * @returns {number} New scale clamped to [0.5, 3.0]
 */
function calculatePinchZoom(currentDistance, initialDistance, initialScale) {
    if (initialDistance === 0 || initialDistance < 0) {
        return initialScale;
    }
    const ratio = currentDistance / initialDistance;
    const newScale = initialScale * ratio;
    return Math.max(0.5, Math.min(3.0, newScale));
}

// Expose for testing
if (typeof window !== 'undefined') {
    window.__testHooks = window.__testHooks || {};
    window.__testHooks.calculatePinchZoom = calculatePinchZoom;
}

class DAGRenderer {
    constructor(containerId) {
        this.container = document.getElementById(containerId);
        this.svg = null;
        this.g = null;
        this.scale = 1;
        this.translateX = 0;
        this.translateY = 0;
        this.isDragging = false;
        this.lastX = 0;
        this.lastY = 0;
    }

    render(layoutData) {
        if (!this.container) {
            console.error('DAG container not found');
            return;
        }

        // Clear existing content
        this.container.innerHTML = '';

        // Create SVG element
        this.svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        this.svg.style.width = '100%';
        this.svg.style.height = '600px';
        this.svg.style.border = '1px solid var(--border)';
        this.svg.style.borderRadius = 'var(--radius)';
        this.svg.style.background = 'var(--bg-secondary)';
        this.svg.style.touchAction = 'none'; // For pinch-to-zoom

        // Create main group for zoom/pan
        this.g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
        this.svg.appendChild(this.g);

        // Add defs for arrow markers
        const defs = document.createElementNS('http://www.w3.org/2000/svg', 'defs');
        const marker = document.createElementNS('http://www.w3.org/2000/svg', 'marker');
        marker.setAttribute('id', 'arrowhead');
        marker.setAttribute('markerWidth', '10');
        marker.setAttribute('markerHeight', '10');
        marker.setAttribute('refX', '9');
        marker.setAttribute('refY', '3');
        marker.setAttribute('orient', 'auto');
        const polygon = document.createElementNS('http://www.w3.org/2000/svg', 'polygon');
        polygon.setAttribute('points', '0 0, 10 3, 0 6');
        polygon.setAttribute('fill', 'var(--text-secondary)');
        marker.appendChild(polygon);
        defs.appendChild(marker);
        this.svg.appendChild(defs);

        // Render edges first (so they appear behind nodes)
        layoutData.edges.forEach(edge => this.renderEdge(edge, layoutData.nodes));

        // Render nodes
        layoutData.nodes.forEach(node => this.renderNode(node));

        // Append to DOM first so centerView can read real clientWidth/Height.
        // centerView() depends on svg.clientWidth/clientHeight; before the node
        // is attached those are 0 and the view collapses to scale=0 at the
        // origin, leaving the graph invisible. Measure after insertion.
        this.container.appendChild(this.svg);

        // Center the view
        this.centerView(layoutData.nodes);

        // Setup zoom/pan interactions
        this.setupInteractions();
    }

    renderNode(node) {
        const nodeGroup = document.createElementNS('http://www.w3.org/2000/svg', 'g');
        nodeGroup.setAttribute('class', 'dag-node');
        nodeGroup.setAttribute('data-node-name', node.node_name);
        nodeGroup.style.cursor = 'pointer';

        // Node background
        const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
        rect.setAttribute('x', node.x - 100);
        rect.setAttribute('y', node.y - 40);
        rect.setAttribute('width', '200');
        rect.setAttribute('height', '80');
        rect.setAttribute('rx', '8');
        const isResumed = node.cache_hit === 1 && node.status === 'completed';
        const statusClass = isResumed ? 'node-status-resumed' : `node-status-${node.status.replace(/[^a-z-]/g, '')}`;
        const failureClass = node.failure_path ? ' node-status-failure-path' : '';
        const skippedDownstreamClass = (node.failure_path && node.status === 'skipped') ? ' node-status-skipped-downstream' : '';
        rect.setAttribute('class', statusClass + failureClass + skippedDownstreamClass);
        nodeGroup.appendChild(rect);

        // Node name
        const text = document.createElementNS('http://www.w3.org/2000/svg', 'text');
        text.setAttribute('x', node.x);
        text.setAttribute('y', node.y - 10);
        text.setAttribute('text-anchor', 'middle');
        text.setAttribute('font-size', '14');
        text.setAttribute('fill', 'var(--text)');
        text.textContent = node.node_name;
        nodeGroup.appendChild(text);

        // Status text
        const statusText = document.createElementNS('http://www.w3.org/2000/svg', 'text');
        statusText.setAttribute('x', node.x);
        statusText.setAttribute('y', node.y + 10);
        statusText.setAttribute('text-anchor', 'middle');
        statusText.setAttribute('font-size', '12');
        statusText.setAttribute('fill', 'var(--text-secondary)');
        statusText.textContent = isResumed ? '↻ resumed' : node.status;
        nodeGroup.appendChild(statusText);

        // Cost and token display (if available)
        let yOffset = 25;
        if (node.cost) {
            const costText = document.createElementNS('http://www.w3.org/2000/svg', 'text');
            costText.setAttribute('x', node.x);
            costText.setAttribute('y', node.y + yOffset);
            costText.setAttribute('text-anchor', 'middle');
            costText.setAttribute('font-size', '11');
            costText.setAttribute('fill', 'var(--text-secondary)');
            costText.textContent = `$${node.cost.toFixed(4)}`;
            nodeGroup.appendChild(costText);
            yOffset += 12;
        }

        // Token badge (mirror node-detail-panel.js fallback logic)
        // Use breakdown sum when any breakdown field present, else fall back to node.tokens
        const hasBreakdown = node.tokens_input != null || node.tokens_output != null || node.tokens_cache != null;
        const totalTokens = hasBreakdown
            ? (node.tokens_input || 0) + (node.tokens_output || 0) + (node.tokens_cache || 0)
            : (node.tokens || 0);
        if (totalTokens > 0) {
            const tokenText = document.createElementNS('http://www.w3.org/2000/svg', 'text');
            tokenText.setAttribute('x', node.x);
            tokenText.setAttribute('y', node.y + yOffset);
            tokenText.setAttribute('text-anchor', 'middle');
            tokenText.setAttribute('font-size', '10');
            tokenText.setAttribute('fill', 'var(--text-secondary)');
            tokenText.textContent = `${totalTokens.toLocaleString()} tokens`;
            nodeGroup.appendChild(tokenText);
        }

        // Click handler
        nodeGroup.addEventListener('click', () => {
            const event = new CustomEvent('node-click', { detail: node });
            window.dispatchEvent(event);
        });

        this.g.appendChild(nodeGroup);
    }

    renderEdge(edge, nodes) {
        const sourceNode = nodes.find(n => n.node_name === edge.source);
        const targetNode = nodes.find(n => n.node_name === edge.target);

        if (!sourceNode || !targetNode) return;

        // Create edge group to hold path + label
        const edgeGroup = document.createElementNS('http://www.w3.org/2000/svg', 'g');
        edgeGroup.setAttribute('class', 'dag-edge-group');
        edgeGroup.setAttribute('data-edge-id', edge.edge_id || `${edge.source}-${edge.target}`);

        const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        const d = `M ${edge.points[0].x} ${edge.points[0].y} L ${edge.points[1].x} ${edge.points[1].y}`;
        path.setAttribute('d', d);
        path.setAttribute('class', 'dag-edge');
        path.setAttribute('marker-end', 'url(#arrowhead)');
        path.setAttribute('data-source', edge.source);
        path.setAttribute('data-target', edge.target);
        path.setAttribute('data-edge-id', edge.edge_id || `${edge.source}-${edge.target}`);

        // Add failure path class
        if (edge.failure_path) {
            path.classList.add('edge-failure-path');
        }

        // Add tooltip with condition info
        if (edge.condition || edge.default) {
            const title = document.createElementNS('http://www.w3.org/2000/svg', 'title');
            const tooltipText = edge.default
                ? 'Default edge (fallback)'
                : `Condition: ${edge.condition}`;
            title.textContent = tooltipText;
            path.appendChild(title);
        }

        // Animate edge if source node is running
        if (sourceNode.status === 'running') {
            path.classList.add('edge-animated');
        }

        edgeGroup.appendChild(path);

        // Add condition label for conditional edges
        if (edge.condition && !edge.default) {
            const midX = (edge.points[0].x + edge.points[1].x) / 2;
            const midY = (edge.points[0].y + edge.points[1].y) / 2;

            const label = document.createElementNS('http://www.w3.org/2000/svg', 'text');
            label.setAttribute('x', midX);
            label.setAttribute('y', midY - 5);
            label.setAttribute('text-anchor', 'middle');
            label.setAttribute('font-size', '11');
            label.setAttribute('class', 'edge-condition-label');
            label.textContent = edge.condition.length > 30
                ? edge.condition.substring(0, 27) + '...'
                : edge.condition;

            // Add background rect for readability
            const bbox = label.getBBox ? label.getBBox() : { x: midX - 40, y: midY - 15, width: 80, height: 14 };
            const labelBg = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
            labelBg.setAttribute('x', bbox.x - 4);
            labelBg.setAttribute('y', bbox.y - 2);
            labelBg.setAttribute('width', bbox.width + 8);
            labelBg.setAttribute('height', bbox.height + 4);
            labelBg.setAttribute('rx', '3');
            labelBg.setAttribute('class', 'edge-condition-label-bg');

            edgeGroup.appendChild(labelBg);
            edgeGroup.appendChild(label);
        }

        this.g.appendChild(edgeGroup);
    }

    centerView(nodes) {
        if (!nodes || nodes.length === 0) return;

        // Calculate bounding box
        let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
        nodes.forEach(node => {
            minX = Math.min(minX, node.x - 100);
            maxX = Math.max(maxX, node.x + 100);
            minY = Math.min(minY, node.y - 40);
            maxY = Math.max(maxY, node.y + 40);
        });

        const width = maxX - minX;
        const height = maxY - minY;
        const centerX = (minX + maxX) / 2;
        const centerY = (minY + maxY) / 2;

        // Calculate scale to fit. Guard against clientWidth/Height==0 — the
        // SVG may be rendered inside a hidden tab pane (display:none) where
        // layout has never happened. Fall back to the parsed CSS height
        // (set to 600px on the SVG element) so we don't collapse to 0 scale.
        const svgWidth = this.svg.clientWidth || this.svg.parentElement?.clientWidth || 800;
        const svgHeight = this.svg.clientHeight || parseInt(this.svg.style.height, 10) || 600;
        const scaleX = svgWidth / (width + 200);
        const scaleY = svgHeight / (height + 200);
        this.scale = Math.min(scaleX, scaleY, 1);
        if (!isFinite(this.scale) || this.scale <= 0) this.scale = 1;

        // Center translate
        this.translateX = svgWidth / 2 - centerX * this.scale;
        this.translateY = svgHeight / 2 - centerY * this.scale;

        this.updateTransform();
    }

    setupInteractions() {
        // Mouse wheel zoom
        this.svg.addEventListener('wheel', (e) => {
            e.preventDefault();
            const delta = e.deltaY > 0 ? 0.9 : 1.1;
            this.scale *= delta;
            this.scale = Math.max(0.1, Math.min(this.scale, 3));
            this.updateTransform();
        });

        // Mouse drag pan
        this.svg.addEventListener('mousedown', (e) => {
            this.isDragging = true;
            this.lastX = e.clientX;
            this.lastY = e.clientY;
        });

        this.svg.addEventListener('mousemove', (e) => {
            if (!this.isDragging) return;
            const dx = e.clientX - this.lastX;
            const dy = e.clientY - this.lastY;
            this.translateX += dx;
            this.translateY += dy;
            this.lastX = e.clientX;
            this.lastY = e.clientY;
            this.updateTransform();
        });

        this.svg.addEventListener('mouseup', () => {
            this.isDragging = false;
        });

        this.svg.addEventListener('mouseleave', () => {
            this.isDragging = false;
        });

        // Touch pinch-to-zoom
        let initialDistance = 0;
        let initialScale = 1;

        this.svg.addEventListener('touchstart', (e) => {
            if (e.touches.length === 2) {
                const dx = e.touches[0].clientX - e.touches[1].clientX;
                const dy = e.touches[0].clientY - e.touches[1].clientY;
                initialDistance = Math.sqrt(dx * dx + dy * dy);
                initialScale = this.scale;
            }
        });

        this.svg.addEventListener('touchmove', (e) => {
            if (e.touches.length === 2) {
                e.preventDefault();
                const dx = e.touches[0].clientX - e.touches[1].clientX;
                const dy = e.touches[0].clientY - e.touches[1].clientY;
                const distance = Math.sqrt(dx * dx + dy * dy);
                this.scale = calculatePinchZoom(distance, initialDistance, initialScale);
                this.updateTransform();
            }
        });
    }

    updateTransform() {
        this.g.setAttribute('transform', `translate(${this.translateX}, ${this.translateY}) scale(${this.scale})`);
    }

    updateNodeStatus(nodeName, status) {
        const nodeGroup = this.g.querySelector(`[data-node-name="${nodeName}"]`);
        if (nodeGroup) {
            const rect = nodeGroup.querySelector('rect');
            rect.setAttribute('class', `node-status-${status.replace(/[^a-z-]/g, '')}`);

            // Update edge animations only for edges originating from this node
            const edges = this.g.querySelectorAll(`.dag-edge[data-source="${nodeName}"]`);
            edges.forEach(edge => {
                if (status === 'running') {
                    edge.classList.add('edge-animated');
                } else {
                    edge.classList.remove('edge-animated');
                }
            });
        }
    }

    updateRetryProgress(nodeName, retryState) {
        const nodeGroup = this.g.querySelector(`[data-node-name="${nodeName}"]`);
        if (!nodeGroup) return;

        // Find or create retry overlay container
        let overlay = nodeGroup.querySelector('.retry-overlay');
        if (!overlay) {
            overlay = document.createElementNS('http://www.w3.org/2000/svg', 'foreignObject');
            overlay.setAttribute('class', 'retry-overlay');
            // Position below the node card
            const node = this.g.querySelector(`[data-node-name="${nodeName}"] rect`);
            const x = parseFloat(node.getAttribute('x'));
            const y = parseFloat(node.getAttribute('y')) + parseFloat(node.getAttribute('height')) + 5;
            overlay.setAttribute('x', x);
            overlay.setAttribute('y', y);
            overlay.setAttribute('width', '200');
            overlay.setAttribute('height', '60');
            nodeGroup.appendChild(overlay);
        }

        // Compute remaining delay (handle SSE replay edge case)
        const now = Date.now();
        const eventTime = new Date(retryState.timestamp).getTime();
        const elapsed = now - eventTime;
        const remainingMs = Math.max(0, retryState.delay_ms - elapsed);

        // Render retry badge content
        const errorSnippet = (retryState.last_error || '').substring(0, 30);
        const errorText = errorSnippet.length === 30 ? errorSnippet + '...' : errorSnippet;

        overlay.innerHTML = `
            <div xmlns="http://www.w3.org/1999/xhtml" class="retry-overlay-content">
                <span class="retry-badge">Retry ${retryState.attempt}/${retryState.max_attempts}</span>
                <span class="retry-countdown">${(remainingMs / 1000).toFixed(1)}s</span>
                <span class="retry-error-snippet" title="${retryState.last_error || ''}">${errorText}</span>
            </div>
        `;

        // Start countdown timer (update every 100ms)
        if (!overlay.dataset.intervalId) {
            const intervalId = setInterval(() => {
                const now = Date.now();
                const elapsed = now - eventTime;
                const remaining = Math.max(0, retryState.delay_ms - elapsed);
                const countdownSpan = overlay.querySelector('.retry-countdown');
                if (countdownSpan) {
                    countdownSpan.textContent = `${(remaining / 1000).toFixed(1)}s`;
                }
                if (remaining === 0) {
                    clearInterval(intervalId);
                    delete overlay.dataset.intervalId;
                }
            }, 100);
            overlay.dataset.intervalId = intervalId;
        }
    }

    clearRetryProgress(nodeName) {
        const nodeGroup = this.g.querySelector(`[data-node-name="${nodeName}"]`);
        if (!nodeGroup) return;

        const overlay = nodeGroup.querySelector('.retry-overlay');
        if (overlay) {
            // Clear countdown interval
            if (overlay.dataset.intervalId) {
                clearInterval(parseInt(overlay.dataset.intervalId));
                delete overlay.dataset.intervalId;
            }
            overlay.remove();
        }
    }

    updateEdgeHighlights(edgeStates) {
        /**
         * Update edge highlighting based on traversal state.
         * Called from SSE handler when EDGE_TRAVERSED events arrive.
         *
         * Per approved plan v2: Since executor only emits CONDITION_EVALUATED for the
         * winning edge (first-match-wins break), renderer must infer skipped siblings
         * from branch_set_id when EDGE_TRAVERSED fires.
         */
        if (!this.g) return;

        Object.entries(edgeStates).forEach(([edgeId, edgeState]) => {
            const edgeGroup = this.g.querySelector(`[data-edge-id="${edgeId}"]`);
            if (!edgeGroup) return;

            const path = edgeGroup.querySelector('.dag-edge');
            if (!path) return;

            // Remove existing state classes
            path.classList.remove('edge-taken', 'edge-skipped');

            // Apply new state class
            if (edgeState.taken) {
                path.classList.add('edge-taken');
            } else if (edgeState.skipped) {
                path.classList.add('edge-skipped');
            }
        });
    }
}

// Export for use in app.js
window.DAGRenderer = DAGRenderer;
