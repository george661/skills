/**
 * VersionDrawer.jsx
 * Side drawer for browsing and restoring draft versions.
 */

import React from 'react';

export default function VersionDrawer({
  isOpen,
  drafts,
  hoveredDiff,
  onClose,
  onRestore,
  onDelete,
  onHover,
}) {
  if (!isOpen) return null;

  const formatTimestamp = (ts) => {
    // YYYYMMDDTHHMMSS_uuuuuuZ -> YYYY-MM-DD HH:MM:SS
    const date = ts.slice(0, 8);
    const time = ts.slice(9, 15);
    return `${date.slice(0, 4)}-${date.slice(4, 6)}-${date.slice(6, 8)} ${time.slice(0, 2)}:${time.slice(2, 4)}:${time.slice(4, 6)}`;
  };

  return (
    <div className="version-drawer open" style={{
      position: 'fixed',
      right: 0,
      top: 0,
      bottom: 0,
      width: '400px',
      backgroundColor: '#fff',
      borderLeft: '1px solid #ccc',
      display: 'flex',
      flexDirection: 'column',
      zIndex: 1000,
    }}>
      <div style={{ padding: '16px', borderBottom: '1px solid #ccc', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h3 style={{ margin: 0 }}>Version History</h3>
        <button onClick={onClose} style={{ border: 'none', background: 'none', fontSize: '20px', cursor: 'pointer' }}>×</button>
      </div>

      <div style={{ flex: 1, overflowY: 'auto', padding: '8px' }}>
        {drafts.length === 0 && (
          <div style={{ padding: '16px', textAlign: 'center', color: '#999' }}>
            No versions yet
          </div>
        )}

        {drafts.map(draft => (
          <div
            key={draft.timestamp}
            className="draft-row"
            onMouseEnter={() => onHover(draft.timestamp)}
            onMouseLeave={() => onHover(null)}
            style={{
              padding: '12px',
              marginBottom: '8px',
              border: '1px solid #e0e0e0',
              borderRadius: '4px',
              cursor: 'pointer',
              backgroundColor: '#f9f9f9',
            }}
          >
            <div style={{ fontSize: '12px', color: '#666', marginBottom: '4px' }}>
              {formatTimestamp(draft.timestamp)}
            </div>
            <div style={{ fontSize: '11px', color: '#999', marginBottom: '8px' }}>
              {draft.publisher || '—'} • {draft.size_bytes} bytes
            </div>
            <div style={{ display: 'flex', gap: '8px' }}>
              <button
                onClick={() => onRestore(draft.timestamp)}
                style={{
                  padding: '4px 8px',
                  fontSize: '12px',
                  border: '1px solid #007bff',
                  backgroundColor: '#007bff',
                  color: '#fff',
                  borderRadius: '3px',
                  cursor: 'pointer',
                }}
                title="Restore"
              >
                Restore
              </button>
              <button
                onClick={() => onDelete(draft.timestamp)}
                style={{
                  padding: '4px 8px',
                  fontSize: '12px',
                  border: '1px solid #dc3545',
                  backgroundColor: '#dc3545',
                  color: '#fff',
                  borderRadius: '3px',
                  cursor: 'pointer',
                }}
                title="Delete"
              >
                Delete
              </button>
            </div>
          </div>
        ))}
      </div>

      {hoveredDiff && (
        <div style={{
          borderTop: '1px solid #ccc',
          padding: '12px',
          maxHeight: '200px',
          overflowY: 'auto',
          backgroundColor: '#f5f5f5',
          fontSize: '11px',
          fontFamily: 'monospace',
        }}>
          <div style={{ fontWeight: 'bold', marginBottom: '8px' }}>Changes:</div>
          {hoveredDiff.first_change_line && (
            <div style={{ marginBottom: '4px', color: '#666' }}>
              {hoveredDiff.first_change_line}
            </div>
          )}
          <pre style={{ margin: 0, whiteSpace: 'pre-wrap', fontSize: '10px' }}>
            {hoveredDiff.unified_diff}
          </pre>
        </div>
      )}
    </div>
  );
}
