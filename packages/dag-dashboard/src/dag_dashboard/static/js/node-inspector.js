/**
 * Node Inspector - Right-panel form for editing node config
 * Supports all six node types with type-specific and common fields
 */

class NodeInspector {
    constructor({ container, node, allowDestructive, availableNodeIds = [], onChange, onDelete }) {
        this.container = container;
        this.node = node || {};
        this.allowDestructive = allowDestructive;
        this.availableNodeIds = availableNodeIds;
        this.onChange = onChange;
        this.onDelete = onDelete;
        this.errors = {};
        
        this.render();
    }

    escapeHtml(str) {
        if (!str) return '';
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    update(node) {
        this.node = node || {};
        this.errors = {};
        this.render();
    }

    destroy() {
        if (this.container) {
            this.container.innerHTML = '';
        }
    }

    render() {
        const type = this.node.type || 'bash';
        
        // Read-only banner for destructive types
        const isDestructive = ['bash', 'skill', 'command'].includes(type);
        const showBanner = isDestructive && !this.allowDestructive;
        
        this.container.innerHTML = `
            <div class="node-inspector">
                ${showBanner ? `
                    <div class="node-inspector-banner">
                        Read-only — destructive node editing disabled. 
                        Set <code>DAG_DASHBOARD_ALLOW_DESTRUCTIVE_NODES=1</code> to enable.
                    </div>
                ` : ''}
                
                <div class="node-inspector-section">
                    <h3>Common Fields</h3>
                    ${this.renderCommonFields()}
                </div>
                
                <div class="node-inspector-section">
                    <h3>Type-Specific Fields</h3>
                    ${this.renderTypeFields(type)}
                </div>
                
                <div class="node-inspector-actions">
                    <button class="node-inspector-delete" data-node-id="${this.escapeHtml(this.node.id || '')}">
                        Delete Node
                    </button>
                </div>
            </div>
        `;
        
        this.attachEventListeners();
    }

    renderCommonFields() {
        const fields = [
            { name: 'id', label: 'ID', type: 'text', required: true, pattern: '^[a-zA-Z0-9_-]+$' },
            { name: 'name', label: 'Name', type: 'text', required: true },
            { name: 'label', label: 'Label', type: 'text' },
            { name: 'when', label: 'When (condition)', type: 'text' },
            { name: 'timeout', label: 'Timeout (seconds)', type: 'number', min: 0 },
        ];
        
        let html = '';
        
        for (const field of fields) {
            const value = this.node[field.name] || '';
            const error = this.errors[field.name];
            html += this.renderTextField(field, value, error);
        }
        
        // depends_on multi-select
        const dependsOn = this.node.depends_on || [];
        html += `
            <div class="node-inspector-field ${this.errors.depends_on ? 'error' : ''}">
                <label>Depends On</label>
                <select name="depends_on" multiple size="3">
                    ${this.availableNodeIds.map(id => `
                        <option value="${this.escapeHtml(id)}" ${dependsOn.includes(id) ? 'selected' : ''}>
                            ${this.escapeHtml(id)}
                        </option>
                    `).join('')}
                </select>
                ${this.errors.depends_on ? `<span class="error-text">${this.escapeHtml(this.errors.depends_on)}</span>` : ''}
            </div>
        `;
        
        // trigger_rule select
        const triggerRule = this.node.trigger_rule || 'all_success';
        html += `
            <div class="node-inspector-field">
                <label>Trigger Rule</label>
                <select name="trigger_rule">
                    <option value="all_success" ${triggerRule === 'all_success' ? 'selected' : ''}>All Success</option>
                    <option value="any_success" ${triggerRule === 'any_success' ? 'selected' : ''}>Any Success</option>
                    <option value="all_done" ${triggerRule === 'all_done' ? 'selected' : ''}>All Done</option>
                </select>
            </div>
        `;
        
        // checkpoint checkbox
        const checkpoint = this.node.checkpoint || false;
        html += `
            <div class="node-inspector-field">
                <label>
                    <input type="checkbox" name="checkpoint" ${checkpoint ? 'checked' : ''}>
                    Checkpoint
                </label>
            </div>
        `;
        
        return html;
    }

    renderTextField(field, value, error, readonly = false) {
        const attrs = [];
        if (field.required) attrs.push('required');
        if (field.pattern) attrs.push(`pattern="${field.pattern}"`);
        if (field.min !== undefined) attrs.push(`min="${field.min}"`);
        if (readonly) attrs.push('readonly');
        
        return `
            <div class="node-inspector-field ${error ? 'error' : ''}">
                <label>${field.label}${field.required ? ' *' : ''}</label>
                <input 
                    type="${field.type}" 
                    name="${field.name}" 
                    value="${this.escapeHtml(value)}"
                    ${attrs.join(' ')}
                    ${readonly ? 'class="node-inspector-readonly"' : ''}
                >
                ${error ? `<span class="error-text">${this.escapeHtml(error)}</span>` : ''}
            </div>
        `;
    }

    renderTextareaField(field, value, error, readonly = false) {
        return `
            <div class="node-inspector-field ${error ? 'error' : ''}">
                <label>${field.label}${field.required ? ' *' : ''}</label>
                <textarea 
                    name="${field.name}" 
                    rows="5"
                    ${field.required ? 'required' : ''}
                    ${readonly ? 'readonly class="node-inspector-readonly"' : ''}
                >${this.escapeHtml(value)}</textarea>
                ${error ? `<span class="error-text">${this.escapeHtml(error)}</span>` : ''}
            </div>
        `;
    }

    renderTypeFields(type) {
        switch (type) {
            case 'bash': return this.renderBashFields();
            case 'prompt': return this.renderPromptFields();
            case 'skill': return this.renderSkillFields();
            case 'command': return this.renderCommandFields();
            case 'gate': return this.renderGateFields();
            case 'interrupt': return this.renderInterruptFields();
            default: return '<p>Unknown node type</p>';
        }
    }

    renderBashFields() {
        const readonly = !this.allowDestructive;
        let html = '';
        
        html += this.renderTextareaField(
            { name: 'script', label: 'Script', required: true },
            this.node.script || '',
            this.errors.script,
            readonly
        );
        
        html += this.renderTextField(
            { name: 'retry', label: 'Retry Attempts', type: 'number', min: 0 },
            this.node.retry || '',
            this.errors.retry,
            readonly
        );
        
        const onFailure = this.node.on_failure || 'stop';
        html += `
            <div class="node-inspector-field">
                <label>On Failure</label>
                <select name="on_failure" ${readonly ? 'disabled' : ''}>
                    <option value="stop" ${onFailure === 'stop' ? 'selected' : ''}>Stop</option>
                    <option value="continue" ${onFailure === 'continue' ? 'selected' : ''}>Continue</option>
                    <option value="degrade" ${onFailure === 'degrade' ? 'selected' : ''}>Degrade</option>
                </select>
            </div>
        `;
        
        return html;
    }

    renderPromptFields() {
        let html = '';
        
        html += this.renderTextareaField(
            { name: 'prompt', label: 'Prompt', required: false },
            this.node.prompt || '',
            this.errors.prompt
        );
        
        html += this.renderTextField(
            { name: 'prompt_file', label: 'Prompt File', type: 'text' },
            this.node.prompt_file || '',
            this.errors.prompt_file
        );
        
        const model = this.node.model || 'sonnet';
        html += `
            <div class="node-inspector-field">
                <label>Model</label>
                <select name="model">
                    <option value="haiku" ${model === 'haiku' ? 'selected' : ''}>Haiku</option>
                    <option value="sonnet" ${model === 'sonnet' ? 'selected' : ''}>Sonnet</option>
                    <option value="opus" ${model === 'opus' ? 'selected' : ''}>Opus</option>
                </select>
            </div>
        `;
        
        const dispatch = this.node.dispatch || 'inline';
        html += `
            <div class="node-inspector-field">
                <label>Dispatch</label>
                <select name="dispatch">
                    <option value="inline" ${dispatch === 'inline' ? 'selected' : ''}>Inline</option>
                    <option value="agent" ${dispatch === 'agent' ? 'selected' : ''}>Agent</option>
                    <option value="subagent" ${dispatch === 'subagent' ? 'selected' : ''}>Subagent</option>
                </select>
            </div>
        `;
        
        const outputFormat = this.node.output_format || 'text';
        html += `
            <div class="node-inspector-field">
                <label>Output Format</label>
                <select name="output_format">
                    <option value="text" ${outputFormat === 'text' ? 'selected' : ''}>Text</option>
                    <option value="json" ${outputFormat === 'json' ? 'selected' : ''}>JSON</option>
                    <option value="yaml" ${outputFormat === 'yaml' ? 'selected' : ''}>YAML</option>
                </select>
            </div>
        `;
        
        const strictModel = this.node.strict_model || false;
        html += `
            <div class="node-inspector-field">
                <label>
                    <input type="checkbox" name="strict_model" ${strictModel ? 'checked' : ''}>
                    Strict Model (disable canvas override)
                </label>
            </div>
        `;
        
        return html;
    }

    renderSkillFields() {
        const readonly = !this.allowDestructive;
        let html = '';
        
        html += this.renderTextField(
            { name: 'skill', label: 'Skill Path', type: 'text', required: true },
            this.node.skill || '',
            this.errors.skill,
            readonly
        );
        
        html += this.renderTextareaField(
            { name: 'params', label: 'Params (JSON)', required: false },
            JSON.stringify(this.node.params || {}, null, 2),
            this.errors.params,
            readonly
        );
        
        return html;
    }

    renderCommandFields() {
        const readonly = !this.allowDestructive;
        let html = '';
        
        html += this.renderTextField(
            { name: 'command', label: 'Command', type: 'text', required: true },
            this.node.command || '',
            this.errors.command,
            readonly
        );
        
        html += this.renderTextareaField(
            { name: 'args', label: 'Args (JSON array)', required: false },
            JSON.stringify(this.node.args || [], null, 2),
            this.errors.args,
            readonly
        );
        
        return html;
    }

    renderGateFields() {
        let html = '';
        
        html += this.renderTextField(
            { name: 'condition', label: 'Condition', type: 'text', required: true },
            this.node.condition || '',
            this.errors.condition
        );
        
        return html;
    }

    renderInterruptFields() {
        let html = '';
        
        html += this.renderTextareaField(
            { name: 'message', label: 'Message', required: true },
            this.node.message || '',
            this.errors.message
        );
        
        html += this.renderTextField(
            { name: 'resume_key', label: 'Resume Key', type: 'text', required: true },
            this.node.resume_key || '',
            this.errors.resume_key
        );
        
        // channels multi-select
        const channels = this.node.channels || [];
        html += `
            <div class="node-inspector-field">
                <label>Channels</label>
                <select name="channels" multiple size="2">
                    <option value="terminal" ${channels.includes('terminal') ? 'selected' : ''}>Terminal</option>
                    <option value="slack" ${channels.includes('slack') ? 'selected' : ''}>Slack</option>
                </select>
            </div>
        `;
        
        html += this.renderTextField(
            { name: 'timeout', label: 'Interrupt Timeout', type: 'number', min: 0 },
            this.node.timeout || '',
            this.errors.timeout
        );
        
        return html;
    }

    attachEventListeners() {
        // Input change handlers
        const inputs = this.container.querySelectorAll('input, textarea, select');
        inputs.forEach(input => {
            if (input.type === 'checkbox') {
                input.addEventListener('change', (e) => this.handleFieldChange(e));
            } else {
                input.addEventListener('blur', (e) => this.handleFieldChange(e));
            }
        });
        
        // Mutual exclusion for prompt/prompt_file
        const promptInput = this.container.querySelector('[name="prompt"]');
        const promptFileInput = this.container.querySelector('[name="prompt_file"]');
        if (promptInput && promptFileInput) {
            promptInput.addEventListener('input', () => {
                if (promptInput.value.trim()) {
                    promptFileInput.disabled = true;
                } else {
                    promptFileInput.disabled = false;
                }
            });
            promptFileInput.addEventListener('input', () => {
                if (promptFileInput.value.trim()) {
                    promptInput.disabled = true;
                } else {
                    promptInput.disabled = false;
                }
            });
            // Apply initial state
            if (promptInput.value.trim()) {
                promptFileInput.disabled = true;
            } else if (promptFileInput.value.trim()) {
                promptInput.disabled = true;
            }
        }
        
        // Delete button
        const deleteBtn = this.container.querySelector('.node-inspector-delete');
        if (deleteBtn) {
            deleteBtn.addEventListener('click', () => this.handleDelete());
        }
    }

    handleFieldChange(e) {
        const field = e.target.name;
        let value;
        
        if (e.target.type === 'checkbox') {
            value = e.target.checked;
        } else if (e.target.type === 'select-multiple') {
            value = Array.from(e.target.selectedOptions).map(opt => opt.value);
        } else if (e.target.type === 'number') {
            value = e.target.value ? parseFloat(e.target.value) : null;
        } else {
            value = e.target.value;
        }
        
        // Validate field
        const error = this.validateField(field, value);
        if (error) {
            this.errors[field] = error;
            this.render(); // Re-render to show error
            return;
        }
        
        // Clear error and update node
        delete this.errors[field];
        
        // Special handling for JSON fields
        if (field === 'params' || field === 'args') {
            try {
                value = JSON.parse(value || (field === 'args' ? '[]' : '{}'));
            } catch (err) {
                this.errors[field] = 'Invalid JSON';
                this.render();
                return;
            }
        }
        
        this.node[field] = value;
        
        // Call onChange callback
        if (this.onChange) {
            this.onChange(this.node);
        }
    }

    validateField(field, value) {
        // Required field check
        const requiredFields = ['id', 'name'];
        if (requiredFields.includes(field) && !value) {
            return 'This field is required';
        }
        
        // ID pattern check
        if (field === 'id' && value) {
            const pattern = /^[a-zA-Z0-9_-]+$/;
            if (!pattern.test(value)) {
                return 'ID must contain only letters, numbers, underscores, and hyphens';
            }
        }
        
        // Type-specific required fields
        const type = this.node.type || 'bash';
        const typeRequirements = {
            bash: ['script'],
            prompt: [], // prompt OR prompt_file required (checked separately)
            skill: ['skill'],
            command: ['command'],
            gate: ['condition'],
            interrupt: ['message', 'resume_key'],
        };
        
        if (typeRequirements[type] && typeRequirements[type].includes(field) && !value) {
            return 'This field is required';
        }
        
        return null;
    }

    async handleDelete() {
        if (!this.onDelete) return;
        
        const nodeId = this.node.id || 'this node';
        
        // Show confirm dialog
        if (window.showConfirmDialog) {
            const confirmed = await window.showConfirmDialog({
                message: `Delete node "${nodeId}"?`,
                confirmText: 'Delete',
            });
            
            if (confirmed) {
                this.onDelete(nodeId);
            }
        } else {
            // Fallback to native confirm
            if (confirm(`Delete node "${nodeId}"?`)) {
                this.onDelete(nodeId);
            }
        }
    }
}

// Export to window
window.NodeInspector = NodeInspector;
