/**
 * dag-node.js
 * Custom DagNode component renderer per node type
 * Uses dashboard CSS variables (--bg-secondary, --text-primary, etc.)
 */

/**
 * Render a DAG node based on its type
 * @param {Object} node - {id, type, data}
 * @returns {string} HTML string for the node
 */
function renderDagNode(node) {
  const { type, data } = node;
  const label = data?.label || node.id;
  
  const baseStyle = `
    background: var(--bg-secondary);
    color: var(--text-primary);
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 12px;
    min-width: 160px;
    font-size: 14px;
  `;
  
  const iconMap = {
    bash: '📟',
    skill: '🛠️',
    command: '⚙️',
    prompt: '💬',
    gate: '🚪',
    interrupt: '⏸️',
  };
  
  const icon = iconMap[type] || '📦';
  const accentColor = getAccentColorForType(type);
  
  return `
    <div class="dag-node" style="${baseStyle} border-left: 4px solid ${accentColor};">
      <div class="dag-node-header" style="display: flex; align-items: center; gap: 8px; margin-bottom: 8px;">
        <span class="dag-node-icon" style="font-size: 18px;">${icon}</span>
        <span class="dag-node-type" style="font-weight: 600; text-transform: uppercase; font-size: 11px; color: var(--text-secondary);">${type}</span>
      </div>
      <div class="dag-node-label" style="font-weight: 500; color: var(--text-primary);">${escapeHtml(label)}</div>
    </div>
  `;
}

/**
 * Get accent color for node type
 * @param {string} type
 * @returns {string} CSS color
 */
function getAccentColorForType(type) {
  const colorMap = {
    bash: 'var(--accent-blue, #3b82f6)',
    skill: 'var(--accent-purple, #8b5cf6)',
    command: 'var(--accent-green, #10b981)',
    prompt: 'var(--accent-yellow, #f59e0b)',
    gate: 'var(--accent-orange, #f97316)',
    interrupt: 'var(--accent-red, #ef4444)',
  };
  return colorMap[type] || 'var(--accent, #6366f1)';
}

/**
 * Escape HTML to prevent XSS
 * @param {string} str
 * @returns {string}
 */
function escapeHtml(str) {
  const div = typeof document !== 'undefined' ? document.createElement('div') : null;
  if (div) {
    div.textContent = str;
    return div.innerHTML;
  }
  // Fallback for Node.js environments
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

// Expose for tests
if (typeof window !== 'undefined') {
  window.__testHooks = window.__testHooks || {};
  window.__testHooks.renderDagNode = renderDagNode;
}

// Export for Node.js tests
if (typeof module !== 'undefined' && module.exports) {
  module.exports = { renderDagNode };
}
