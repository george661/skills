/**
 * ChatPanel - Per-workflow chat UI component
 * Displays a chat interface for a specific workflow run with SSE live updates
 */
class ChatPanel {
  constructor(containerId, runId) {
    this.containerId = containerId;
    this.runId = runId;
    this.container = document.getElementById(containerId);
    this.messages = new Map(); // dedupe by message id
    this.isNearBottom = true;
    
    if (!this.container) {
      throw new Error(`Container #${containerId} not found`);
    }
  }

  /**
   * Render the chat panel UI
   */
  render() {
    this.container.innerHTML = `
      <div class="chat-panel">
        <div class="chat-header">
          <h3>Chat</h3>
        </div>
        <div class="chat-messages" id="chat-messages-${this.runId}">
          <div class="chat-empty-state">No messages yet</div>
        </div>
        <form class="chat-input-form" id="chat-form-${this.runId}">
          <textarea 
            class="chat-input" 
            id="chat-input-${this.runId}"
            placeholder="Type a message... (Cmd/Ctrl+Enter to send)"
            rows="3"
          ></textarea>
          <button type="submit" class="chat-send-btn">Send</button>
        </form>
      </div>
    `;

    this.messagesContainer = document.getElementById(`chat-messages-${this.runId}`);
    this.form = document.getElementById(`chat-form-${this.runId}`);
    this.input = document.getElementById(`chat-input-${this.runId}`);

    this._attachEventListeners();
    this._setupScrollTracking();
  }

  /**
   * Attach event listeners for form submission and keyboard shortcuts
   */
  _attachEventListeners() {
    // Form submission
    this.form.addEventListener('submit', (e) => {
      e.preventDefault();
      this._handleSendMessage();
    });

    // Cmd/Ctrl+Enter to send
    this.input.addEventListener('keydown', (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
        e.preventDefault();
        this._handleSendMessage();
      }
    });
  }

  /**
   * Track when user is near bottom for auto-scroll behavior
   */
  _setupScrollTracking() {
    this.messagesContainer.addEventListener('scroll', () => {
      const threshold = 100;
      const scrollBottom = this.messagesContainer.scrollHeight - 
                          this.messagesContainer.scrollTop - 
                          this.messagesContainer.clientHeight;
      this.isNearBottom = scrollBottom < threshold;
    });
  }

  /**
   * Handle sending a message
   */
  async _handleSendMessage() {
    const content = this.input.value.trim();
    if (!content) return;

    // Disable input while sending
    this.input.disabled = true;
    this.form.querySelector('.chat-send-btn').disabled = true;

    try {
      await this.sendMessage(content);
      this.input.value = '';
    } catch (error) {
      console.error('Failed to send message:', error);
      
      // Show 429 rate limit warning inline
      if (error.status === 429) {
        this._showRateLimitWarning();
      } else {
        alert(`Failed to send message: ${error.message}`);
      }
    } finally {
      // Re-enable input
      this.input.disabled = false;
      this.form.querySelector('.chat-send-btn').disabled = false;
      this.input.focus();
    }
  }

  /**
   * Show inline rate limit warning
   */
  _showRateLimitWarning() {
    const warningDiv = document.createElement('div');
    warningDiv.className = 'chat-rate-limit-warning';
    warningDiv.textContent = 'Rate limit exceeded. Please wait a moment before sending another message.';
    
    this.form.insertAdjacentElement('beforebegin', warningDiv);
    
    // Auto-remove after 5 seconds
    setTimeout(() => {
      warningDiv.remove();
    }, 5000);
  }

  /**
   * Send a message to the backend
   */
  async sendMessage(content) {
    const response = await fetch(`/api/runs/${this.runId}/chat`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ content }),
    });

    if (!response.ok) {
      const error = new Error(`HTTP ${response.status}`);
      error.status = response.status;
      throw error;
    }

    return response.json();
  }

  /**
   * Handle SSE message event
   * @param {Object} payload - Chat message payload
   */
  handleSSEMessage(payload) {
    // Dedupe by message id
    if (payload.id && this.messages.has(payload.id)) {
      return;
    }

    if (payload.id) {
      this.messages.set(payload.id, payload);
    }

    this.renderMessage(payload);
  }

  /**
   * Render a single chat message
   * @param {Object} msg - Message object with role, content, timestamp
   */
  renderMessage(msg) {
    // Remove empty state if present
    const emptyState = this.messagesContainer.querySelector('.chat-empty-state');
    if (emptyState) {
      emptyState.remove();
    }

    const messageDiv = document.createElement('div');
    messageDiv.className = `chat-message chat-message-${this._escapeHtml(msg.role)}`;
    
    const timestamp = msg.timestamp ? new Date(msg.timestamp).toLocaleTimeString() : '';
    const timestampHtml = timestamp ? `<span class="chat-message-time">${this._escapeHtml(timestamp)}</span>` : '';
    
    // Use escapeHtml for non-markdown fields, marked.parse() for agent message content
    const contentHtml = msg.role === 'agent' && typeof marked !== 'undefined'
      ? marked.parse(msg.content)
      : this._escapeHtml(msg.content);

    messageDiv.innerHTML = `
      <div class="chat-message-header">
        <span class="chat-message-role">${this._escapeHtml(msg.role)}</span>
        ${timestampHtml}
      </div>
      <div class="chat-message-content">${contentHtml}</div>
    `;

    this.messagesContainer.appendChild(messageDiv);

    // Auto-scroll only if user is near bottom
    if (this.isNearBottom) {
      this.messagesContainer.scrollTop = this.messagesContainer.scrollHeight;
    }
  }

  /**
   * Escape HTML to prevent XSS
   */
  _escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  /**
   * Destroy the chat panel and clean up resources
   */
  destroy() {
    if (this.container) {
      this.container.innerHTML = '';
    }
    this.messages.clear();
  }
}
