/**
 * useVersionDrawer.js
 * Hook for managing version drawer state and API calls.
 */

import { useState, useEffect, useCallback } from 'react';
import parseDraftContent from './parseDraftContent.js';

export default function useVersionDrawer(workflowName, currentCanvasYaml) {
  const [isOpen, setIsOpen] = useState(false);
  const [drafts, setDrafts] = useState([]);
  const [hoveredDiff, setHoveredDiff] = useState(null);
  const [hoverTimestamp, setHoverTimestamp] = useState(null);

  // Fetch draft list when drawer opens
  useEffect(() => {
    if (!isOpen) return;

    const fetchDrafts = async () => {
      try {
        const response = await fetch(`/api/workflows/${workflowName}/drafts`);
        if (response.ok) {
          const data = await response.json();
          setDrafts(data);
        }
      } catch (error) {
        console.error('Failed to fetch drafts:', error);
      }
    };

    fetchDrafts();
  }, [isOpen, workflowName]);

  // Fetch diff on hover with debounce
  useEffect(() => {
    if (!hoverTimestamp) {
      setHoveredDiff(null);
      return;
    }

    const timeoutId = setTimeout(async () => {
      try {
        const response = await fetch(`/api/workflows/${workflowName}/drafts/diff`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            from_ts: hoverTimestamp,
            to_content: currentCanvasYaml,
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
  }, [hoverTimestamp, workflowName, currentCanvasYaml]);

  const open = useCallback(() => setIsOpen(true), []);
  const close = useCallback(() => setIsOpen(false), []);
  
  const handleHover = useCallback((timestamp) => {
    setHoverTimestamp(timestamp);
  }, []);

  const handleRestore = useCallback(async (timestamp) => {
    try {
      const response = await fetch(`/api/workflows/${workflowName}/drafts/${timestamp}`);
      if (response.ok) {
        const data = await response.json();
        const nodes = parseDraftContent(data.content);
        return nodes;
      }
    } catch (error) {
      console.error('Failed to restore draft:', error);
    }
    return null;
  }, [workflowName]);

  const handleDelete = useCallback(async (timestamp) => {
    if (!window.confirm('Delete this draft version? This cannot be undone.')) {
      return false;
    }

    try {
      const response = await fetch(`/api/workflows/${workflowName}/drafts/${timestamp}`, {
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
  }, [workflowName]);

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
