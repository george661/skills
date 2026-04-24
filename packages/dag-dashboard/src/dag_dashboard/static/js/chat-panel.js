/**
 * ChatPanel - Per-workflow chat UI component
 * Displays a chat interface for a specific workflow run with SSE live updates
 * Can also display conversation-wide history (read-only mode)
 */
class ChatPanel {
  constructor(containerId, runIdOrOptions) {
    this.containerId = containerId;
    this.container = document.getElementById(containerId);
    this.messages = new Map(); // dedupe by message id
    this.isNearBottom = true;

    // Support two constructor signatures:
    // new ChatPanel(containerId, runId) - existing run mode
    // new ChatPanel(containerId, { mode: 'conversation', conversationId }) - new conversation mode
    if (typeof runIdOrOptions === 'string') {
      this.mode = 'run';
      this.runId = runIdOrOptions;
      this.conversationId = null;
    } else if (typeof runIdOrOptions === 'object') {
      this.mode = runIdOrOptions.mode || 'run';
      this.runId = runIdOrOptions.runId || null;
      this.conversationId = runIdOrOptions.conversationId || null;
    } else {
      throw new Error('Invalid constructor arguments');
    }

    if (!this.container) {
      throw new Error(`Container #${containerId} not found`);
    }
  }

  /**
   * Render the chat panel UI
   */
  render() {
    const uniqueId = this.mode === 'conversation' ? this.conversationId : this.runId;
    const isReadOnly = this.mode === 'conversation';

    // Render input form only if not in read-only conversation mode
    const inputFormHtml = isReadOnly
      ? `<div class="chat-read-only-hint">
           <p>Read-only view across runs — send messages from the originating run</p>
         </div>`
      : `<form class="chat-input-form" id="chat-form-${uniqueId}">
           <textarea
             class="chat-input"
             id="chat-input-${uniqueId}"
             placeholder="Type a message... (Cmd/Ctrl+Enter to send)"
             rows="3"
           ></textarea>
           <button type="submit" class="chat-send-btn">Send</button>
           <p class="chat-input-hint">Limit: 10 messages per minute</p>
         </form>`;

    this.container.innerHTML = `
      <div class="chat-panel">
        <div class="chat-header">
          <h3>Chat</h3>
        </div>
        <div class="chat-messages" id="chat-messages-${uniqueId}">
          <div class="chat-empty-state">No messages yet</div>
        </div>
        ${inputFormHtml}
      </div>
    `;

    this.messagesContainer = document.getElementById(`chat-messages-${uniqueId}`);

    if (!isReadOnly) {
      this.form = document.getElementById(`chat-form-${uniqueId}`);
      this.input = document.getElementById(`chat-input-${uniqueId}`);
      this._attachEventListeners();
    }

    this._setupScrollTracking();
    this._loadHistory();
  }

  /**
   * Load chat history from backend
   */
  async _loadHistory() {
    try {
      // Route to the correct endpoint based on mode
      const url = this.mode === 'conversation'
        ? `/api/conversations/${this.conversationId}/messages?limit=50`
        : `/api/workflows/${this.runId}/chat/history?limit=50`;

      const response = await fetch(url);
      if (!response.ok) {
        console.error('Failed to load chat history:', response.status);
        return;
      }

      // Backend returns bare JSON array (List[Dict]), not wrapped object
      const messages = await response.json();

      // Render messages in chronological order
      for (const msg of messages) {
        // Store in messages map for dedupe
        if (msg.id) {
          // Only render if not already displayed
          if (!this.messages.has(msg.id)) {
            this.messages.set(msg.id, msg);
            this.renderMessage(msg);
          }
        } else {
          this.renderMessage(msg);
        }
      }
    } catch (error) {
      console.error('Failed to load chat history:', error);
    }
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
    // Get or prompt for operator username
    let operatorUsername = localStorage.getItem('chat_operator_username');
    if (!operatorUsername) {
      operatorUsername = prompt('Enter your username for chat:');
      if (!operatorUsername) {
        throw new Error('Username is required to send messages');
      }
      localStorage.setItem('chat_operator_username', operatorUsername);
    }

    const response = await fetch(`/api/workflows/${this.runId}/chat`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        content,
        operator_username: operatorUsername
      }),
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
    
    const timestamp = msg.created_at ? new Date(msg.created_at).toLocaleTimeString() : '';
    const timestampHtml = timestamp ? `<span class="chat-message-time">${this._escapeHtml(timestamp)}</span>` : '';
    
    // Sanitize all content - markdown for agent, plain text for operator
    let contentHtml;
    if (msg.role === 'agent' && typeof marked !== 'undefined' && typeof DOMPurify !== 'undefined') {
      contentHtml = DOMPurify.sanitize(marked.parse(msg.content));
    } else if (msg.role === 'operator' && typeof DOMPurify !== 'undefined') {
      contentHtml = DOMPurify.sanitize(this._escapeHtml(msg.content));
    } else {
      contentHtml = this._escapeHtml(msg.content);
    }

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
