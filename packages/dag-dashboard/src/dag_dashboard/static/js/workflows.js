/**
 * Workflows page - list and detail views for workflow definitions
 */

async function renderWorkflowsList() {
    document.title = 'Workflows | DAG Dashboard';
    const mainContent = document.getElementById('main-content');
    
    mainContent.innerHTML = `
        <div class="workflows-list-container">
            <h1>Workflows</h1>
            <p class="loading">Loading workflows...</p>
        </div>
    `;

    try {
        const response = await fetch('/api/definitions');
        if (!response.ok) throw new Error('Failed to fetch workflows');
        
        const definitions = await response.json();
        
        // Group by source_dir
        const grouped = {};
        definitions.forEach(def => {
            if (!grouped[def.source_dir]) {
                grouped[def.source_dir] = [];
            }
            grouped[def.source_dir].push(def);
        });

        let html = '<h1>Workflows</h1>';
        
        if (definitions.length === 0) {
            html += '<p class="empty-state">No workflows found. Add YAML files to your workflows directory.</p>';
        } else {
            Object.entries(grouped).forEach(([sourceDir, workflows]) => {
                html += `<div class="workflow-group">
                    <h2 class="source-dir-header">${escapeHtml(sourceDir)}</h2>
                    <div class="workflow-cards">`;
                
                workflows.forEach(wf => {
                    const hasCollision = wf.collisions && wf.collisions.length > 0;
                    const description = escapeHtml(wf.description || '');
                    const inputsCount = Object.keys(wf.inputs || {}).length;
                    const requiredInputs = Object.entries(wf.inputs || {})
                        .filter(([_, spec]) => spec.required)
                        .map(([name, _]) => escapeHtml(name));
                    const inputsSummary = inputsCount > 0
                        ? `${inputsCount} input${inputsCount > 1 ? 's' : ''}${requiredInputs.length > 0 ? ` (required: ${requiredInputs.join(', ')})` : ''}`
                        : 'No inputs';

                    let lastRunBadge = '';
                    if (wf.last_run) {
                        const statusClass = wf.last_run.status === 'success' ? 'badge-success'
                            : wf.last_run.status === 'failed' ? 'badge-error'
                            : wf.last_run.status === 'running' ? 'badge-running'
                            : 'badge-pending';
                        lastRunBadge = `<span class="status-badge ${statusClass}">${escapeHtml(wf.last_run.status)}</span>`;
                    }

                    html += `
                        <div class="workflow-card ${hasCollision ? 'has-collision' : ''}">
                            <h3><a href="#/workflows/${escapeHtml(wf.name)}">${escapeHtml(wf.name)}</a></h3>
                            ${hasCollision ? `<span class="collision-badge" title="Also exists in: ${wf.collisions.map(c => escapeHtml(c)).join(', ')}">⚠️ Shadowed</span>` : ''}
                            ${description ? `<p class="workflow-description">${description}</p>` : ''}
                            <p class="workflow-meta">${inputsSummary}</p>
                            ${lastRunBadge}
                            <p class="workflow-path">${escapeHtml(wf.path)}</p>
                        </div>`;
                });
                
                html += `</div></div>`;
            });
        }

        mainContent.innerHTML = `<div class="workflows-list-container">${html}</div>`;
    } catch (error) {
        mainContent.innerHTML = `
            <div class="workflows-list-container">
                <h1>Workflows</h1>
                <p class="error">Error loading workflows: ${error.message}</p>
            </div>`;
    }
}

async function renderWorkflowDetail(name) {
    document.title = `${name} | DAG Dashboard`;
    const mainContent = document.getElementById('main-content');
    
    mainContent.innerHTML = `
        <div class="workflow-detail-container">
            <p class="loading">Loading workflow...</p>
        </div>
    `;

    try {
        const response = await fetch(`/api/definitions/${name}`);
        if (!response.ok) {
            if (response.status === 404) throw new Error('Workflow not found');
            throw new Error('Failed to fetch workflow');
        }
        
        const definition = await response.json();
        
        let html = `
            <div class="workflow-detail-header">
                <h1>${escapeHtml(definition.name)}</h1>
                <a href="#/workflows" class="back-link">← Back to workflows</a>
            </div>

            <section class="workflow-yaml">
                <h2>YAML Source</h2>
                <pre><code>${escapeHtml(definition.yaml_source)}</code></pre>
            </section>

            <section class="workflow-actions">
                <button onclick="triggerWorkflow('${escapeHtml(name)}')" class="button-primary">Run Workflow</button>
            </section>
        `;

        // Add DAG preview if parsed nodes exist
        if (definition.parsed && definition.parsed.nodes && definition.parsed.nodes.length > 0) {
            html += `
                <section class="workflow-dag">
                    <h2>DAG Preview</h2>
                    <div id="dag-preview-container"></div>
                </section>`;
        }

        // Add Input Schema table
        if (definition.parsed && definition.parsed.inputs) {
            const inputs = definition.parsed.inputs;
            const inputEntries = Object.entries(inputs);
            if (inputEntries.length > 0) {
                html += `
                    <section class="workflow-inputs">
                        <h2>Input Schema</h2>
                        <table class="inputs-table">
                            <thead>
                                <tr>
                                    <th>Name</th>
                                    <th>Type</th>
                                    <th>Required</th>
                                    <th>Default</th>
                                    <th>Pattern</th>
                                </tr>
                            </thead>
                            <tbody>`;
                inputEntries.forEach(([inputName, spec]) => {
                    html += `
                                <tr>
                                    <td>${escapeHtml(inputName)}</td>
                                    <td>${escapeHtml(spec.type || 'string')}</td>
                                    <td>${spec.required ? 'Yes' : 'No'}</td>
                                    <td>${spec.default !== undefined ? escapeHtml(String(spec.default)) : '—'}</td>
                                    <td>${spec.pattern ? escapeHtml(spec.pattern) : '—'}</td>
                                </tr>`;
                });
                html += `
                            </tbody>
                        </table>
                    </section>`;
            }
        }

        mainContent.innerHTML = `<div class="workflow-detail-container">${html}</div>`;

        // Render DAG preview
        if (definition.parsed && definition.parsed.nodes) {
            renderDAGPreview(definition.layout);
        }

        // Fetch and render recent runs
        try {
            const runsResponse = await fetch(`/api/workflows?name=${encodeURIComponent(name)}&limit=10`);
            if (runsResponse.ok) {
                const runs = await runsResponse.json();
                if (runs.length > 0) {
                    let runsHtml = `
                        <section class="workflow-recent-runs">
                            <h2>Recent Runs</h2>
                            <div class="runs-list">`;
                    runs.forEach(run => {
                        const statusClass = run.status === 'success' ? 'badge-success'
                            : run.status === 'failed' ? 'badge-error'
                            : run.status === 'running' ? 'badge-running'
                            : 'badge-pending';
                        const startedAt = run.started_at ? new Date(run.started_at).toLocaleString() : 'N/A';
                        runsHtml += `
                                <div class="run-card">
                                    <span class="status-badge ${statusClass}">${run.status}</span>
                                    <span class="run-time">${startedAt}</span>
                                    <a href="#/workflow/${run.run_id}" class="run-link">View run →</a>
                                </div>`;
                    });
                    runsHtml += `
                            </div>
                        </section>`;

                    // Append to the container
                    const container = document.querySelector('.workflow-detail-container');
                    if (container) {
                        const section = document.createElement('div');
                        section.innerHTML = runsHtml;
                        container.appendChild(section.firstElementChild);
                    }
                }
            }
        } catch (error) {
            console.error('Failed to fetch recent runs:', error);
        }
        
    } catch (error) {
        mainContent.innerHTML = `
            <div class="workflow-detail-container">
                <h1>Error</h1>
                <p class="error">${error.message}</p>
                <a href="#/workflows" class="back-link">← Back to workflows</a>
            </div>`;
    }
}

function renderDAGPreview(layout) {
    // Use existing DAGRenderer to show the graph
    const container = document.getElementById('dag-preview-container');
    if (!container || typeof DAGRenderer === 'undefined') return;

    // Layout is already computed server-side
    if (!layout || !layout.nodes || !layout.edges) {
        container.innerHTML = '<p>No DAG preview available</p>';
        return;
    }

    // Render with DAGRenderer
    const renderer = new DAGRenderer(container, { interactive: false });
    renderer.render(layout.nodes, layout.edges);
}


function triggerWorkflow(name) {
    window.location.hash = "#/workflow-trigger/" + name;
}

async function renderWorkflowTriggerForm(name) {
    document.title = `Run ${name} | DAG Dashboard`;
    const mainContent = document.getElementById('main-content');

    mainContent.innerHTML = `
        <div class="workflow-trigger-container">
            <p class="loading">Loading workflow form...</p>
        </div>
    `;

    try {
        const response = await fetch(`/api/definitions/${name}`);
        if (!response.ok) {
            if (response.status === 404) throw new Error('Workflow not found');
            throw new Error('Failed to fetch workflow');
        }

        const definition = await response.json();
        const inputs = definition.parsed?.inputs || {};
        const inputEntries = Object.entries(inputs);

        let formHtml = `
            <div class="workflow-trigger-header">
                <h1>Run Workflow: ${escapeHtml(definition.name)}</h1>
                <a href="#/workflows/${escapeHtml(name)}" class="back-link">← Back to workflow</a>
            </div>

            <form id="trigger-workflow-form" class="workflow-trigger-form">
                <input type="hidden" name="workflow" value="${escapeHtml(name)}" />
        `;

        // Add input fields
        if (inputEntries.length > 0) {
            formHtml += '<section class="form-section"><h2>Workflow Inputs</h2>';
            inputEntries.forEach(([inputName, spec]) => {
                const isRequired = spec.required;
                const inputType = spec.type || 'string';
                const defaultValue = spec.default !== undefined ? escapeHtml(String(spec.default)) : '';
                const pattern = spec.pattern || '';

                formHtml += `
                    <div class="form-field">
                        <label for="input-${escapeHtml(inputName)}">
                            ${escapeHtml(inputName)}
                            ${isRequired ? '<span class="required">*</span>' : ''}
                        </label>
                        <input
                            type="text"
                            id="input-${escapeHtml(inputName)}"
                            name="${escapeHtml(inputName)}"
                            value="${defaultValue}"
                            ${isRequired ? 'required' : ''}
                            ${pattern ? `pattern="${escapeHtml(pattern)}"` : ''}
                        />
                        ${spec.description ? `<p class="field-description">${escapeHtml(spec.description)}</p>` : ''}
                    </div>
                `;
            });
            formHtml += '</section>';
        }

        // Add model override dropdown
        formHtml += `
            <section class="form-section">
                <h2>Model Override</h2>
                <div class="form-field">
                    <label for="model_override">Model</label>
                    <select id="model_override" name="model_override">
                        <option value="">Default (from workflow config)</option>
                        <option value="opus">Claude Opus</option>
                        <option value="sonnet">Claude Sonnet</option>
                        <option value="local">Local Model</option>
                    </select>
                    <p class="field-description">Override the default model for this run</p>
                </div>
            </section>
        `;

        // Add submit button
        formHtml += `
            <div class="form-actions">
                <button type="submit" class="button-primary">Run Workflow</button>
                <a href="#/workflows/${escapeHtml(name)}" class="button-secondary">Cancel</a>
            </div>
            </form>
        `;

        mainContent.innerHTML = `<div class="workflow-trigger-container">${formHtml}</div>`;

        // Attach form submit handler
        const form = document.getElementById('trigger-workflow-form');
        form.addEventListener('submit', async (e) => {
            e.preventDefault();

            const formData = new FormData(form);
            const workflow = formData.get('workflow');
            const model_override = formData.get('model_override') || undefined;

            // Collect workflow inputs
            const workflowInputs = {};
            inputEntries.forEach(([inputName, _]) => {
                const value = formData.get(inputName);
                if (value) {
                    workflowInputs[inputName] = value;
                }
            });

            // Prepare trigger payload
            const payload = {
                workflow: workflow,
                inputs: workflowInputs,
                source: "ui"
            };

            if (model_override) {
                payload.model_override = model_override;
            }

            try {
                const triggerResponse = await fetch('/api/trigger', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify(payload)
                });

                if (!triggerResponse.ok) {
                    throw new Error('Failed to trigger workflow');
                }

                const result = await triggerResponse.json();
                if (result.run_id) {
                    window.location.hash = `#/workflow/${result.run_id}`;
                } else {
                    throw new Error('No run_id returned from trigger endpoint');
                }
            } catch (error) {
                alert(`Error triggering workflow: ${error.message}`);
            }
        });

    } catch (error) {
        mainContent.innerHTML = `
            <div class="workflow-trigger-container">
                <h1>Error</h1>
                <p class="error">${error.message}</p>
                <a href="#/workflows" class="back-link">← Back to workflows</a>
            </div>`;
    }
}

// Export for route registration
window.renderWorkflowsList = renderWorkflowsList;
window.renderWorkflowDetail = renderWorkflowDetail;
window.renderWorkflowTriggerForm = renderWorkflowTriggerForm;
