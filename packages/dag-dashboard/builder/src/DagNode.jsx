/**
 * Custom React Flow node renderer. One component handles all six
 * dag-executor node types (bash, skill, command, prompt, gate, interrupt);
 * type is read from `data.node_type`. Colors accent a left border so the
 * node type is scannable even in a dense graph.
 *
 * Styling uses the dashboard's CSS custom properties (`var(--*)`) — no
 * Tailwind, matching the existing dashboard convention.
 *
 * The `readOnly` prop dims the card via opacity < 1. A future task
 * (PRP-PLAT-008 FR-8, wiring `builder.allow_destructive_nodes`) will
 * reuse this prop to lock type-specific field editing for bash/skill/
 * command nodes — the surface is here now so that change is a prop
 * flip, not a refactor.
 */
import React from 'react';
import { Handle, Position } from '@xyflow/react';

const ACCENTS = {
    bash: '#2563eb',      // --primary (blue)
    skill: '#7c3aed',     // violet
    command: '#0891b2',   // cyan
    prompt: '#059669',    // emerald
    gate: '#d97706',      // amber
    interrupt: '#dc2626', // red
};

const ICONS = {
    bash: '$',
    skill: '⚙',
    command: '▶',
    prompt: '✎',
    gate: '◆',
    interrupt: '⏸',
};

export function DagNode({ data, selected, readOnly = false }) {
    const nodeType = (data && data.node_type) || 'bash';
    const accent = ACCENTS[nodeType] || ACCENTS.bash;
    const icon = ICONS[nodeType] || '•';
    const name = (data && data.name) || (data && data.id) || '';
    const summary = (data && data.summary) || '';

    const baseStyle = {
        background: 'var(--bg-secondary)',
        color: 'var(--text-primary)',
        border: '1px solid var(--border)',
        borderLeft: `3px solid ${accent}`,
        borderRadius: 'var(--radius, 4px)',
        padding: '8px 12px',
        minWidth: '180px',
        fontFamily: 'system-ui, -apple-system, sans-serif',
        fontSize: '13px',
        opacity: readOnly ? 0.6 : 1,
        boxShadow: selected ? '0 0 0 2px var(--primary, #2563eb)' : 'none',
        cursor: readOnly ? 'not-allowed' : 'default',
    };

    const headerStyle = {
        display: 'flex',
        alignItems: 'center',
        gap: '6px',
        fontWeight: 600,
    };

    const typeStyle = {
        color: accent,
        fontSize: '11px',
        textTransform: 'uppercase',
        letterSpacing: '0.5px',
    };

    const summaryStyle = {
        marginTop: '4px',
        color: 'var(--text-secondary)',
        fontSize: '11px',
        fontFamily: 'ui-monospace, SFMono-Regular, monospace',
        whiteSpace: 'nowrap',
        overflow: 'hidden',
        textOverflow: 'ellipsis',
    };

    return (
        <div
            style={baseStyle}
            data-node-type={nodeType}
            data-readonly={readOnly ? 'true' : 'false'}
        >
            <Handle type="target" position={Position.Top} />
            <div style={headerStyle}>
                <span aria-hidden="true">{icon}</span>
                <span>{name}</span>
            </div>
            <div style={typeStyle}>{nodeType}</div>
            {summary ? <div style={summaryStyle}>{summary}</div> : null}
            <Handle type="source" position={Position.Bottom} />
        </div>
    );
}

// Each entry must be a distinct reference so React Flow can accept a
// per-type readOnly prop later; for now all 6 types render the same way.
export function makeNodeTypes({ readOnly = false } = {}) {
    const render = (props) => <DagNode {...props} readOnly={readOnly} />;
    return {
        bash: render,
        skill: render,
        command: render,
        prompt: render,
        gate: render,
        interrupt: render,
    };
}
