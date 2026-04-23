/**
 * Settings page — form UI for GET/PUT /api/settings and POST /api/settings/slack/test.
 *
 * Sections: Slack, Trigger, Dashboard, Events.
 * Secret fields show the masked value returned by GET and are read-only until
 * the user clicks "Edit", at which point the input clears and becomes editable.
 * On Save, fields untouched by the user are omitted from the PUT body so the
 * existing stored secret is preserved.
 */
(function () {
    'use strict';

    const SECTIONS = [
        {
            id: 'slack',
            title: 'Slack Notifications',
            fields: [
                { key: 'slack_enabled', label: 'Enable Slack notifications', type: 'checkbox' },
                { key: 'slack_webhook_url', label: 'Webhook URL', type: 'text', secret: true, placeholder: 'https://hooks.slack.com/services/...' },
                { key: 'slack_bot_token', label: 'Bot token', type: 'text', secret: true, placeholder: 'xoxb-...' },
                { key: 'slack_channel_id', label: 'Channel ID', type: 'text', placeholder: 'C01234ABCDE' },
            ],
        },
        {
            id: 'trigger',
            title: 'Trigger Endpoint',
            fields: [
                { key: 'trigger_enabled', label: 'Enable webhook trigger', type: 'checkbox' },
                { key: 'trigger_secret', label: 'HMAC secret (min 16 chars)', type: 'text', secret: true },
                { key: 'trigger_rate_limit_per_min', label: 'Rate limit per minute', type: 'number', min: 1, max: 1000 },
            ],
        },
        {
            id: 'dashboard',
            title: 'Dashboard',
            fields: [
                { key: 'dashboard_url', label: 'Public dashboard URL', type: 'text', placeholder: 'http://127.0.0.1:8100' },
                { key: 'max_sse_connections', label: 'Max SSE connections', type: 'number', min: 1, max: 500 },
            ],
        },
        {
            id: 'events',
            title: 'Events & Workflows',
            fields: [
                { key: 'workflows_dir', label: 'Workflows directory', type: 'text', placeholder: 'workflows' },
                { key: 'node_log_line_cap', label: 'Node log line cap', type: 'number', min: 1, max: 10000000, placeholder: '50000' },
            ],
        },
        {
            id: 'builder',
            title: 'Builder',
            fields: [
                { key: 'allow_destructive_nodes', label: 'Allow editing bash/skill/command node fields', type: 'checkbox', help: 'Keep OFF unless you trust everyone with dashboard access. When enabled, users can edit bash commands, skill references, and command node fields in the workflow builder.' },
            ],
        },
    ];

    function escapeHtml(unsafe) {
        if (unsafe === null || unsafe === undefined) return '';
        return String(unsafe)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#039;');
    }

    function findField(key) {
        for (const section of SECTIONS) {
            const field = section.fields.find(f => f.key === key);
            if (field) return field;
        }
        return null;
    }

    async function fetchSettings() {
        const response = await fetch('/api/settings');
        if (!response.ok) throw new Error(`GET /api/settings returned ${response.status}`);
        const data = await response.json();
        return data.settings || {};
    }

    function renderFieldRow(field, setting) {
        const isSecret = Boolean(field.secret && setting && setting.is_secret);
        const rawValue = setting && 'value' in setting ? setting.value : '';
        const source = setting && setting.source ? setting.source : 'default';

        const fieldId = `settings-field-${field.key}`;
        const errorId = `settings-error-${field.key}`;

        let inputHtml;
        if (field.type === 'checkbox') {
            inputHtml = `<input type="checkbox" id="${fieldId}" class="settings-input settings-input-checkbox"
                data-key="${escapeHtml(field.key)}" ${rawValue ? 'checked' : ''}>`;
        } else if (field.type === 'number') {
            inputHtml = `<input type="number" id="${fieldId}" class="settings-input settings-input-number filter-input"
                data-key="${escapeHtml(field.key)}"
                value="${rawValue !== null && rawValue !== undefined ? escapeHtml(rawValue) : ''}"
                ${field.min !== undefined ? `min="${field.min}"` : ''}
                ${field.max !== undefined ? `max="${field.max}"` : ''}>`;
        } else if (isSecret) {
            // Secret field: show masked, read-only until Edit is clicked.
            inputHtml = `
                <input type="text" id="${fieldId}"
                       class="settings-input settings-input-text settings-input-masked filter-input"
                       data-key="${escapeHtml(field.key)}"
                       data-masked="true"
                       value="${escapeHtml(rawValue || '')}"
                       placeholder="${escapeHtml(field.placeholder || '')}"
                       readonly>
                <button type="button" class="btn btn-sm btn-secondary settings-edit-btn"
                        data-target="${fieldId}">Edit</button>
            `;
        } else {
            inputHtml = `<input type="text" id="${fieldId}" class="settings-input settings-input-text filter-input"
                data-key="${escapeHtml(field.key)}"
                value="${escapeHtml(rawValue !== null && rawValue !== undefined ? rawValue : '')}"
                placeholder="${escapeHtml(field.placeholder || '')}">`;
        }

        const sourceBadge = `<span class="settings-source settings-source-${escapeHtml(source)}">${escapeHtml(source)}</span>`;
        const helpText = field.help ? `<div class="settings-help-text">${escapeHtml(field.help)}</div>` : '';

        return `
            <div class="settings-field" data-field="${escapeHtml(field.key)}">
                <label for="${fieldId}" class="settings-label">${escapeHtml(field.label)}</label>
                ${helpText}
                <div class="settings-field-control">${inputHtml}</div>
                <div class="settings-field-meta">${sourceBadge}</div>
                <div id="${errorId}" class="settings-error" role="alert" aria-live="polite"></div>
            </div>
        `;
    }

    function renderSection(section, settings) {
        const rows = section.fields.map(f => renderFieldRow(f, settings[f.key])).join('');
        const slackTestButton = section.id === 'slack'
            ? `<div class="settings-section-actions">
                 <button type="button" class="btn btn-secondary" id="settings-test-slack">
                     Send test Slack notification
                 </button>
                 <span id="settings-test-slack-result" class="settings-test-result" role="status" aria-live="polite"></span>
               </div>`
            : '';
        return `
            <fieldset class="settings-fieldset" data-section="${section.id}">
                <legend class="settings-legend">${escapeHtml(section.title)}</legend>
                ${rows}
                ${slackTestButton}
            </fieldset>
        `;
    }

    function clearErrors(root) {
        root.querySelectorAll('.settings-error').forEach(el => { el.textContent = ''; });
        const banner = root.querySelector('#settings-banner');
        if (banner) {
            banner.textContent = '';
            banner.className = 'settings-banner';
        }
    }

    function setBanner(root, kind, message) {
        const banner = root.querySelector('#settings-banner');
        if (!banner) return;
        banner.textContent = message;
        banner.className = `settings-banner settings-banner-${kind}`;
    }

    function renderErrors(root, errors) {
        clearErrors(root);
        if (!Array.isArray(errors)) {
            setBanner(root, 'error', typeof errors === 'string' ? errors : 'Validation failed');
            return;
        }
        let generic = [];
        for (const err of errors) {
            const target = root.querySelector(`#settings-error-${CSS.escape(err.key)}`);
            if (target) {
                target.textContent = err.detail || 'Invalid value';
            } else {
                generic.push(`${err.key}: ${err.detail}`);
            }
        }
        if (generic.length) {
            setBanner(root, 'error', generic.join(' • '));
        } else {
            setBanner(root, 'error', 'Fix the highlighted fields and try again.');
        }
    }

    function collectUpdates(root) {
        const updates = {};
        root.querySelectorAll('.settings-input').forEach(input => {
            const key = input.dataset.key;
            if (!key) return;
            const field = findField(key);
            if (!field) return;

            if (field.type === 'checkbox') {
                updates[key] = input.checked;
                return;
            }

            // For masked secret inputs, only include if the user cleared the masked state.
            if (field.secret && input.dataset.masked === 'true') {
                return;
            }

            const rawVal = input.value;
            if (field.type === 'number') {
                if (rawVal === '') return;
                const n = Number(rawVal);
                if (Number.isFinite(n)) updates[key] = n;
                return;
            }
            updates[key] = rawVal;
        });
        return updates;
    }

    async function testSlack(root) {
        const resultEl = root.querySelector('#settings-test-slack-result');
        if (resultEl) {
            resultEl.textContent = 'Sending…';
            resultEl.className = 'settings-test-result settings-test-result-pending';
        }
        try {
            const response = await fetch('/api/settings/slack/test', { method: 'POST' });
            const data = await response.json();
            if (resultEl) {
                if (data.ok) {
                    resultEl.textContent = 'Sent. Check your Slack channel.';
                    resultEl.className = 'settings-test-result settings-test-result-ok';
                } else {
                    resultEl.textContent = `Failed: ${data.error || 'unknown error'}`;
                    resultEl.className = 'settings-test-result settings-test-result-error';
                }
            }
        } catch (err) {
            if (resultEl) {
                resultEl.textContent = `Failed: ${err && err.message ? err.message : 'network error'}`;
                resultEl.className = 'settings-test-result settings-test-result-error';
            }
        }
    }

    async function save(root) {
        clearErrors(root);
        const updates = collectUpdates(root);
        const saveBtn = root.querySelector('#settings-save');
        if (saveBtn) saveBtn.disabled = true;
        try {
            const response = await fetch('/api/settings', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ updates }),
            });
            if (!response.ok) {
                let detailErrors = null;
                try {
                    const body = await response.json();
                    if (body && body.detail && Array.isArray(body.detail.errors)) {
                        detailErrors = body.detail.errors;
                    } else if (body && body.detail) {
                        detailErrors = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail);
                    }
                } catch (_) { /* ignore */ }
                renderErrors(root, detailErrors || `Request failed with status ${response.status}`);
                return;
            }
            setBanner(root, 'success', 'Settings saved.');
            // Refresh the form with the server's masked view.
            await mount(root);
        } catch (err) {
            setBanner(root, 'error', err && err.message ? err.message : 'Network error');
        } finally {
            if (saveBtn) saveBtn.disabled = false;
        }
    }

    async function mount(container) {
        container.innerHTML = `
            <div class="settings-page">
                <h2 class="settings-title">Settings</h2>
                <div id="settings-banner" class="settings-banner" role="status" aria-live="polite"></div>
                <div class="settings-loading">Loading…</div>
            </div>
        `;
        let settings;
        try {
            settings = await fetchSettings();
        } catch (err) {
            container.innerHTML = `
                <div class="settings-page">
                    <h2 class="settings-title">Settings</h2>
                    <div class="settings-banner settings-banner-error">
                        ${escapeHtml(err && err.message ? err.message : 'Failed to load settings')}
                    </div>
                </div>
            `;
            return;
        }

        const sectionsHtml = SECTIONS.map(s => renderSection(s, settings)).join('');
        container.innerHTML = `
            <div class="settings-page">
                <h2 class="settings-title">Settings</h2>
                <div id="settings-banner" class="settings-banner" role="status" aria-live="polite"></div>
                <form class="settings-form" id="settings-form" novalidate>
                    ${sectionsHtml}
                    <div class="settings-actions">
                        <button type="submit" class="btn btn-primary" id="settings-save">Save</button>
                    </div>
                </form>
            </div>
        `;

        const form = container.querySelector('#settings-form');
        form.addEventListener('submit', e => { e.preventDefault(); save(container); });

        container.querySelectorAll('.settings-edit-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const targetId = btn.dataset.target;
                const input = container.querySelector(`#${CSS.escape(targetId)}`);
                if (!input) return;
                input.value = '';
                input.readOnly = false;
                input.dataset.masked = 'false';
                input.focus();
                btn.remove();
            });
        });

        const testBtn = container.querySelector('#settings-test-slack');
        if (testBtn) {
            testBtn.addEventListener('click', () => testSlack(container));
        }
    }

    window.renderSettings = function () {
        const container = document.getElementById('route-container');
        if (!container) return;
        mount(container);
    };
})();
