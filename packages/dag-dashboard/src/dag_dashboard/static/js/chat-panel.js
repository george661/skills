/**
 * ChatPanel — unified conversation feed.
 *
 * Two modes:
 *   'run'          — a workflow's live run-detail page. Renders user/agent
 *                    chat turns, progress cards (one per node), and a terminal
 *                    banner when the workflow ends. Accepts SSE workflow
 *                    events via handleWorkflowEvent().
 *   'conversation' — cross-run conversation view. Renders user/agent only;
 *                    other message types are filtered out.
 *
 * Progress cards are delegated to WorkflowProgressCard instances (one per
 * nodeId) maintained in a Map so subsequent events route back to the
 * existing card instead of creating a duplicate.
 */
class ChatPanel {
  constructor(containerId, runIdOrOptions) {
    this.containerId = containerId;
    this.container = document.getElementById(containerId);
    this.messages = new Map(); // dedupe chat messages by id
    this.isNearBottom = true;

    // Constructor signatures:
    //   new ChatPanel(containerId, runId) — run mode (back-compat)
    //   new ChatPanel(containerId, { mode, runId, conversationId }) — explicit
    if (typeof runIdOrOptions === 'string') {
      this.mode = 'run';
      this.runId = runIdOrOptions;
      this.conversationId = null;
    } else if (typeof runIdOrOptions === 'object' && runIdOrOptions !== null) {
      this.mode = runIdOrOptions.mode || 'run';
      this.runId = runIdOrOptions.runId || null;
      this.conversationId = runIdOrOptions.conversationId || null;
    } else {
      throw new Error('Invalid constructor arguments');
    }

    if (!this.container) {
      throw new Error(`Container #${containerId} not found`);
    }

    // Per-node progress cards keyed by nodeId — used by handleWorkflowEvent
    // to route follow-up events to an existing card.
    this.cards = new Map();
    // Mutable state shared with EventToMessages for out-of-order folding.
    this._eventState = window.EventToMessages
      ? window.EventToMessages.createState()
      : { seenNodes: new Set(), pendingChannels: {} };
    // NodeScrollBus subscription (run mode only).
    this._scrollSubscription = null;
    // Bound terminal banner flag.
    this._terminalShown = false;
  }

  render() {
    const uniqueId = this.mode === 'conversation' ? this.conversationId : this.runId;
    const isReadOnly = this.mode === 'conversation';

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
      <div class="chat-panel chat-panel--${this.mode}">
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
      this._subscribeToScrollBus();
    }

    this._setupScrollTracking();
    this._loadHistory();
  }

  _subscribeToScrollBus() {
    if (this.mode !== 'run' || !window.NodeScrollBus) return;
    this._scrollSubscription = (nodeId, source) => {
      if (source === 'feed') return; // ignore self-triggers
      const card = this.cards.get(nodeId);
      if (card) card.scrollIntoViewAndFlash();
    };
    window.NodeScrollBus.subscribe(this._scrollSubscription);
  }

  async _loadHistory() {
    try {
      const url = this.mode === 'conversation'
        ? `/api/conversations/${this.conversationId}/messages?limit=50`
        : `/api/workflows/${this.runId}/chat/history?limit=50`;

      const response = await fetch(url);
      if (!response.ok) {
        console.error('Failed to load chat history:', response.status);
        return;
      }

      const messages = await response.json();
      for (const msg of messages) {
        if (msg.id) {
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

  _attachEventListeners() {
    this.form.addEventListener('submit', (e) => {
      e.preventDefault();
      this._handleSendMessage();
    });

    this.input.addEventListener('keydown', (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
        e.preventDefault();
        this._handleSendMessage();
      }
    });
  }

  _setupScrollTracking() {
    this.messagesContainer.addEventListener('scroll', () => {
      const threshold = 100;
      const scrollBottom = this.messagesContainer.scrollHeight -
                          this.messagesContainer.scrollTop -
                          this.messagesContainer.clientHeight;
      this.isNearBottom = scrollBottom < threshold;
    });
  }

  _scrollToBottomIfNeeded() {
    if (this.isNearBottom) {
      this.messagesContainer.scrollTop = this.messagesContainer.scrollHeight;
    }
  }

  async _handleSendMessage() {
    const content = this.input.value.trim();
    if (!content) return;

    this.input.disabled = true;
    this.form.querySelector('.chat-send-btn').disabled = true;

    try {
      await this.sendMessage(content);
      this.input.value = '';
    } catch (error) {
      console.error('Failed to send message:', error);
      if (error.status === 429) {
        this._showRateLimitWarning();
      } else {
        alert(`Failed to send message: ${error.message}`);
      }
    } finally {
      this.input.disabled = false;
      this.form.querySelector('.chat-send-btn').disabled = false;
      this.input.focus();
    }
  }

  _showRateLimitWarning() {
    const warningDiv = document.createElement('div');
    warningDiv.className = 'chat-rate-limit-warning';
    warningDiv.textContent = 'Rate limit exceeded. Please wait a moment before sending another message.';
    this.form.insertAdjacentElement('beforebegin', warningDiv);
    setTimeout(() => { warningDiv.remove(); }, 5000);
  }

  async sendMessage(content) {
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
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content, operator_username: operatorUsername }),
    });

    if (!response.ok) {
      const error = new Error(`HTTP ${response.status}`);
      error.status = response.status;
      throw error;
    }

    return response.json();
  }

  /**
   * Handle an SSE chat_message event (back-compat name).
   */
  handleSSEMessage(payload) {
    if (payload.id && this.messages.has(payload.id)) return;
    if (payload.id) this.messages.set(payload.id, payload);
    this.renderMessage(payload);
  }

  /**
   * Handle an SSE workflow event (run mode only).
   * `payload` is the normalized shape from setupLiveUpdates:
   *   { event_type, node_id, model, dispatch, duration_ms, timestamp, metadata }
   * Conversation mode filters everything out.
   */
  handleWorkflowEvent(payload) {
    if (this.mode !== 'run') return;
    if (!window.EventToMessages) return;
    const messages = window.EventToMessages.eventToMessages(payload, this._eventState);
    for (const msg of messages) {
      this._dispatchWorkflowMessage(msg);
    }
  }

  _dispatchWorkflowMessage(msg) {
    if (msg.type === 'progress_card') {
      const card = this._ensureCard(msg.nodeId, msg.payload);
      card.handleEvent(msg);
      this._scrollToBottomIfNeeded();
    } else if (msg.type === 'terminal') {
      this._renderTerminalBanner(msg.status);
    }
  }

  _ensureCard(nodeId, payload) {
    let card = this.cards.get(nodeId);
    if (card) return card;

    const empty = this.messagesContainer.querySelector('.chat-empty-state');
    if (empty) empty.remove();

    const meta = (payload && payload.metadata) || {};
    card = new window.WorkflowProgressCard({
      runId: this.runId,
      nodeId,
      model: payload ? (payload.model || meta.model || '') : '',
      dispatch: payload ? (payload.dispatch || meta.dispatch || '') : '',
    });
    this.cards.set(nodeId, card);
    card.mount(this.messagesContainer);
    return card;
  }

  _renderTerminalBanner(status) {
    if (this._terminalShown) return;
    this._terminalShown = true;
    const banner = document.createElement('div');
    banner.className = `chat-terminal-banner chat-terminal-banner--${status}`;
    banner.textContent = `Workflow ${status}`;
    this.messagesContainer.appendChild(banner);
    this._scrollToBottomIfNeeded();
  }

  /**
   * Render a chat message (user/agent/operator). In conversation mode,
   * anything that isn't a chat turn is filtered out — no progress cards
   * ever render in the conversation view.
   */
  renderMessage(msg) {
    const type = msg.type || msg.role;
    if (this.mode === 'conversation') {
      if (type !== 'user' && type !== 'agent' && type !== 'operator') return;
    }

    const empty = this.messagesContainer.querySelector('.chat-empty-state');
    if (empty) empty.remove();

    if (type === 'progress_card' || type === 'terminal') {
      // Defensive: these go through _dispatchWorkflowMessage in run mode
      // and are filtered out in conversation mode above.
      return;
    }
    return this._renderChatTurn(msg);
  }

  _renderChatTurn(msg) {
    const messageDiv = document.createElement('div');
    const role = msg.role || msg.type || 'agent';
    messageDiv.className = `chat-message chat-message-${this._escapeHtml(role)}`;

    const timestamp = msg.created_at ? new Date(msg.created_at).toLocaleTimeString() : '';
    const timestampHtml = timestamp ? `<span class="chat-message-time">${this._escapeHtml(timestamp)}</span>` : '';

    let contentHtml;
    if (role === 'agent' && typeof marked !== 'undefined' && typeof DOMPurify !== 'undefined') {
      contentHtml = DOMPurify.sanitize(marked.parse(msg.content));
    } else if (role === 'operator' && typeof DOMPurify !== 'undefined') {
      contentHtml = DOMPurify.sanitize(this._escapeHtml(msg.content));
    } else {
      contentHtml = this._escapeHtml(msg.content);
    }

    messageDiv.innerHTML = `
      <div class="chat-message-header">
        <span class="chat-message-role">${this._escapeHtml(role)}</span>
        ${timestampHtml}
      </div>
      <div class="chat-message-content">${contentHtml}</div>
    `;

    this.messagesContainer.appendChild(messageDiv);
    if (this.isNearBottom) {
      this.messagesContainer.scrollTop = this.messagesContainer.scrollHeight;
    }
  }

  _escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text == null ? '' : text;
    return div.innerHTML;
  }

  destroy() {
    if (this._scrollSubscription && window.NodeScrollBus) {
      window.NodeScrollBus.unsubscribe(this._scrollSubscription);
      this._scrollSubscription = null;
    }
    for (const card of this.cards.values()) {
      try { card.destroy(); } catch (_) { /* best-effort */ }
    }
    this.cards.clear();
    if (this.container) this.container.innerHTML = '';
    this.messages.clear();
  }
}

// Expose on window so renderRunDetail (`new window.ChatPanel(...)`) + the
// conversation view can instantiate without a module import.
if (typeof window !== 'undefined') {
    window.ChatPanel = ChatPanel;
}
