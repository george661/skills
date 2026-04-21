/**
 * ArtifactList — workflow-aggregated artifact panel.
 *
 * Call ArtifactList.render(containerId, runId) to populate an element
 * with a grouped list of artifacts produced by every node in a run.
 * PR / commit / branch / file artifacts get linkified.
 */
const ArtifactList = {
    async render(containerId, runId) {
        const container = document.getElementById(containerId);
        if (!container) return;
        container.innerHTML = '<div class="loading">Loading artifacts…</div>';

        try {
            const resp = await fetch(`/api/workflows/${encodeURIComponent(runId)}/artifacts`);
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            const body = await resp.json();
            this._render(container, body.artifacts || []);
        } catch (err) {
            container.innerHTML = `<div class="error-state">Failed to load artifacts: ${this._escape(err.message)}</div>`;
        }
    },

    _render(container, artifacts) {
        if (artifacts.length === 0) {
            container.innerHTML = '<div class="empty-state">No artifacts produced by this run.</div>';
            return;
        }

        const groups = { pr: [], commit: [], branch: [], file: [], other: [] };
        for (const a of artifacts) {
            const bucket = groups[a.artifact_type] ? a.artifact_type : 'other';
            groups[bucket].push(a);
        }

        const sections = [];
        for (const [type, items] of Object.entries(groups)) {
            if (!items.length) continue;
            sections.push(`
                <section class="artifact-group">
                    <h4>${this._escape(type)} (${items.length})</h4>
                    <ul class="artifact-items">
                        ${items.map(a => this._renderItem(a)).join('')}
                    </ul>
                </section>
            `);
        }

        container.innerHTML = `
            <div class="run-artifacts-section">
                <h3>Artifacts</h3>
                ${sections.join('')}
            </div>
        `;
    },

    _renderItem(a) {
        const label = a.url
            ? `<a href="${this._escape(a.url)}" target="_blank" rel="noopener noreferrer">${this._escape(a.name)}</a>`
            : this._escape(a.name);
        const node = a.node_name ? `<span class="artifact-node">${this._escape(a.node_name)}</span>` : '';
        const path = a.path ? `<span class="artifact-path">${this._escape(a.path)}</span>` : '';
        return `<li class="artifact-item">${label} ${node} ${path}</li>`;
    },

    _escape(s) {
        if (s == null) return '';
        return String(s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    },
};

window.ArtifactList = ArtifactList;
