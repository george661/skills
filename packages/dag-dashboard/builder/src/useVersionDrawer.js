/**
 * useVersionDrawer.js
 * Hook for managing version drawer state and API calls.
 */

import { useState, useEffect, useCallback } from 'react';
import parseDraftContent from './parseDraftContent.js';

export default function useVersionDrawer(workflowName, currentCanvasJson, options = {}) {
  const { fetch: fetchImpl = fetch, confirm: confirmImpl = (msg) => window.confirm(msg) } = options;
  const [isOpen, setIsOpen] = useState(false);
  const [drafts, setDrafts] = useState([]);
  const [hoveredDiff, setHoveredDiff] = useState(null);
  const [hoverTimestamp, setHoverTimestamp] = useState(null);
  const [snapshotCanvasJson, setSnapshotCanvasJson] = useState(null);

  // Fetch draft list when drawer opens
  useEffect(() => {
    if (!isOpen) return;

    const fetchDrafts = async () => {
      try {
        const response = await fetchImpl(`/api/workflows/${workflowName}/drafts`);
        if (response.ok) {
          const data = await response.json();
          setDrafts(data);
        }
      } catch (error) {
        console.error('Failed to fetch drafts:', error);
      }
    };

    fetchDrafts();
  }, [isOpen, workflowName, fetchImpl]);

  // Fetch diff on hover with debounce
  // Note: currentCanvasJson is NOT in deps to prevent debounce thrash on every DAG edit
  useEffect(() => {
    if (!hoverTimestamp) {
      setHoveredDiff(null);
      setSnapshotCanvasJson(null);
      return;
    }

    // Snapshot currentCanvasJson at hover start to prevent using stale value
    if (!snapshotCanvasJson) {
      setSnapshotCanvasJson(currentCanvasJson);
    }

    const timeoutId = setTimeout(async () => {
      try {
        const response = await fetchImpl(`/api/workflows/${workflowName}/drafts/diff`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            from_ts: hoverTimestamp,
            to_content: snapshotCanvasJson || currentCanvasJson,
          }),
        });
        if (response.ok) {
          const data = await response.json();
          setHoveredDiff(data);
        }
      } catch (error) {
        console.error('Failed to fetch diff:', error);
      }
    }, 300); // 300ms debounce

    return () => clearTimeout(timeoutId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hoverTimestamp, workflowName, fetchImpl, snapshotCanvasJson]);

  const open = useCallback(() => setIsOpen(true), []);
  const close = useCallback(() => setIsOpen(false), []);
  
  const handleHover = useCallback((timestamp) => {
    setHoverTimestamp(timestamp);
  }, []);

  const handleRestore = useCallback(async (timestamp) => {
    try {
      const response = await fetchImpl(`/api/workflows/${workflowName}/drafts/${timestamp}`);
      if (response.ok) {
        const data = await response.json();
        const nodes = parseDraftContent(data.content);
        return nodes;
      } else {
        const errorMsg = `Failed to restore draft: HTTP ${response.status}`;
        console.error(errorMsg);
        alert(errorMsg); // Visible error feedback to user
        return null;
      }
    } catch (error) {
      const errorMsg = `Failed to restore draft: ${error.message}`;
      console.error(errorMsg);
      alert(errorMsg);
      return null;
    }
  }, [workflowName, fetchImpl]);

  const handleDelete = useCallback(async (timestamp) => {
    if (!confirmImpl('Delete this draft version? This cannot be undone.')) {
      return false;
    }

    try {
      const response = await fetchImpl(`/api/workflows/${workflowName}/drafts/${timestamp}`, {
        method: 'DELETE',
      });
      if (response.ok) {
        // Remove from list
        setDrafts(prev => prev.filter(d => d.timestamp !== timestamp));
        return true;
      }
    } catch (error) {
      console.error('Failed to delete draft:', error);
    }
    return false;
  }, [workflowName, fetchImpl, confirmImpl]);

  return {
    isOpen,
    drafts,
    hoveredDiff,
    open,
    close,
    handleHover,
    handleRestore,
    handleDelete,
  };
}
