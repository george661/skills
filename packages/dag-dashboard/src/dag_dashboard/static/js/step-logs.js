/**
 * StepLogs - Node execution log viewer with live tail and historical modes
 * Displays stdout/stderr log lines with auto-scroll, pause-on-scroll, and stream filtering
 */
class StepLogs {
  constructor(container, { runId, nodeId, nodeStatus }) {
    this.container = container;
    this.runId = runId;
    this.nodeId = nodeId;
    this.nodeStatus = nodeStatus; // 'running', 'completed', 'failed', etc.
    
    this.lines = []; // Array of {sequence, stream, line, timestamp}
    this.streamFilter = 'all'; // 'all', 'stdout', 'stderr'
    this.autoScroll = true;
    this.pausedByScroll = false;
    this.eventSource = null;
    
    if (!this.container) {
      throw new Error('StepLogs: container is required');
    }
  }

  /**
   * Render the log viewer UI
   */
  render() {
    // Sanitize nodeId for the list's DOM id. node_name can legitimately
    // contain `:` (when composite), `.`, or spaces, any of which break
    // `getElementById` / `querySelector` lookups.
    this._safeId = String(this.nodeId || '').replace(/[^a-zA-Z0-9_-]/g, '-');
    this.container.innerHTML = `
      <div class="step-logs">
        <div class="step-logs-toolbar">
          <div class="step-logs-filters">
            <button class="filter-btn ${this.streamFilter === 'all' ? 'active' : ''}" data-stream="all">All</button>
            <button class="filter-btn ${this.streamFilter === 'stdout' ? 'active' : ''}" data-stream="stdout">stdout</button>
            <button class="filter-btn ${this.streamFilter === 'stderr' ? 'active' : ''}" data-stream="stderr">stderr</button>
          </div>
          <div class="step-logs-status">
            ${this.nodeStatus === 'running' ? '<span class="follow-badge">Following</span>' : ''}
            <span class="log-count">${this.lines.length} lines</span>
          </div>
        </div>
        <div class="step-logs-list" id="step-logs-list-${this._safeId}">
          <div class="step-logs-empty">Loading logs…</div>
        </div>
      </div>
    `;

    this.logsList = document.getElementById(`step-logs-list-${this._safeId}`);

    this._attachEventListeners();
    this._loadHistoricalLogs();

    // Subscribe to live updates if node is running
    if (this.nodeStatus === 'running') {
      this._subscribeSSE();
    }
  }

  /**
   * Attach event listeners for stream filter buttons and scroll detection
   */
  _attachEventListeners() {
    // Stream filter buttons
    const filterButtons = this.container.querySelectorAll('.filter-btn');
    filterButtons.forEach(btn => {
      btn.addEventListener('click', (e) => {
        this._setStreamFilter(e.target.dataset.stream);
      });
    });

    // Scroll tracking for pause-on-scroll-up
    this.logsList.addEventListener('scroll', () => {
      this._onScroll();
    });
  }

  /**
   * Load historical logs from REST endpoint
   */
  async _loadHistoricalLogs() {
    try {
      const response = await fetch(
        `/api/workflows/${this.runId}/nodes/${encodeURIComponent(this.nodeId)}/logs?limit=500&offset=0&stream=all`
      );

      if (!response.ok) {
        console.error('Failed to load historical logs:', response.status);
        if (this.logsList) {
          this.logsList.innerHTML = `<div class="step-logs-empty">Failed to load logs (${response.status})</div>`;
        }
        return;
      }

      const data = await response.json();

      if (data.lines && data.lines.length > 0) {
        data.lines.forEach(line => this._appendLine(line));
      } else if (this.logsList) {
        // Differentiate between "logs still coming" and "this node doesn't
        // produce log lines." Prompt/agent nodes used to fall into the
        // latter; that's now fixed at the emitter, but a terminal bash
        // node with zero stdout is legitimate.
        const msg = this.nodeStatus === 'running'
          ? 'Waiting for first log line…'
          : 'No log output was captured for this node.';
        this.logsList.innerHTML = `<div class="step-logs-empty">${msg}</div>`;
      }
    } catch (error) {
      console.error('Failed to load historical logs:', error);
      if (this.logsList) {
        this.logsList.innerHTML = `<div class="step-logs-empty">Failed to load logs: ${this._escapeHtml(String(error.message || error))}</div>`;
      }
    }
  }

  /**
   * Subscribe to SSE for live log updates
   */
  _subscribeSSE() {
    this.eventSource = new EventSource(`/api/workflows/${this.runId}/events`);
    
    this.eventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        
        // Filter for node_log_line events for this node
        if (data.event_type === 'node_log_line' && data.node_id === this.nodeId) {
          const metadata = data.metadata || {};
          this._appendLine({
            sequence: metadata.sequence,
            stream: metadata.stream,
            line: metadata.line,
            timestamp: data.timestamp
          });
        }
      } catch (error) {
        console.error('Error parsing SSE event:', error);
      }
    };

    this.eventSource.onerror = (error) => {
      console.error('SSE error:', error);
      // EventSource will auto-reconnect
    };
  }

  /**
   * Append a log line to the list
   */
  _appendLine(logLine) {
    // Dedupe by sequence (if lines arrive out of order or duplicate)
    const existing = this.lines.find(l => l.sequence === logLine.sequence);
    if (existing) return;

    // Insert in sequence order
    const insertIndex = this.lines.findIndex(l => l.sequence > logLine.sequence);
    if (insertIndex === -1) {
      this.lines.push(logLine);
    } else {
      this.lines.splice(insertIndex, 0, logLine);
    }

    // Re-render if it affects the visible lines
    this._renderLines();

    // Auto-scroll if enabled
    if (this.autoScroll && !this.pausedByScroll) {
      this.logsList.scrollTop = this.logsList.scrollHeight;
    }
  }

  /**
   * Render all lines (with stream filter applied)
   */
  _renderLines() {
    const filteredLines = this.lines.filter(line => {
      if (this.streamFilter === 'all') return true;
      return line.stream === this.streamFilter;
    });

    if (filteredLines.length === 0) {
      this.logsList.innerHTML = '<div class="step-logs-empty">No logs match the filter</div>';
      return;
    }

    this.logsList.innerHTML = filteredLines.map(line => `
      <div class="log-line log-line-${line.stream}" data-sequence="${line.sequence}">
        <span class="log-stream">[${line.stream}]</span>
        <span class="log-text">${this._escapeHtml(line.line)}</span>
      </div>
    `).join('');

    // Update count badge
    const countBadge = this.container.querySelector('.log-count');
    if (countBadge) {
      countBadge.textContent = `${filteredLines.length} lines`;
    }
  }

  /**
   * Handle scroll events - pause auto-scroll if user scrolls up
   */
  _onScroll() {
    const container = this.logsList;
    const isAtBottom = (container.scrollHeight - container.scrollTop - container.clientHeight) < 50;
    
    if (!isAtBottom && this.autoScroll) {
      this.pausedByScroll = true;
      this._showResumeButton();
    } else if (isAtBottom && this.pausedByScroll) {
      this.pausedByScroll = false;
      this._hideResumeButton();
    }
  }

  /**
   * Show "Resume follow" button
   */
  _showResumeButton() {
    const statusDiv = this.container.querySelector('.step-logs-status');
    if (!statusDiv.querySelector('.resume-follow-btn')) {
      const btn = document.createElement('button');
      btn.className = 'resume-follow-btn';
      btn.textContent = 'Resume follow';
      btn.onclick = () => this._resumeFollow();
      statusDiv.insertBefore(btn, statusDiv.firstChild);
    }
  }

  /**
   * Hide "Resume follow" button
   */
  _hideResumeButton() {
    const btn = this.container.querySelector('.resume-follow-btn');
    if (btn) btn.remove();
  }

  /**
   * Resume auto-scroll
   */
  _resumeFollow() {
    this.pausedByScroll = false;
    this.autoScroll = true;
    this.logsList.scrollTop = this.logsList.scrollHeight;
    this._hideResumeButton();
  }

  /**
   * Set stream filter
   */
  _setStreamFilter(stream) {
    this.streamFilter = stream;
    
    // Update button states
    this.container.querySelectorAll('.filter-btn').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.stream === stream);
    });

    // Re-render with new filter
    this._renderLines();
  }

  /**
   * Escape HTML entities
   */
  _escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  /**
   * Clean up resources
   */
  destroy() {
    if (this.eventSource) {
      this.eventSource.close();
      this.eventSource = null;
    }
  }
}

// Export for use in other modules
if (typeof window !== 'undefined') {
  window.StepLogs = StepLogs;
}
