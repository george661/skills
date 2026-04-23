/**
 * useToolbarActions.js
 * 
 * Hook that wraps fetch calls to workflow API endpoints.
 * Returns save, publish, run, validate functions + loading states.
 */

import { useState, useRef } from 'react';

export default function useToolbarActions(workflowName) {
  const [isSaving, setIsSaving] = useState(false);
  const [isPublishing, setIsPublishing] = useState(false);
  const [isRunning, setIsRunning] = useState(false);
  const [isValidating, setIsValidating] = useState(false);
  const [lastError, setLastError] = useState(null);
  
  const lastSavedTimestampRef = useRef(null);

  const saveDraft = async (yaml) => {
    setIsSaving(true);
    setLastError(null);
    
    try {
      const response = await fetch(`/api/workflows/${workflowName}/drafts`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ yaml }),
      });
      
      if (!response.ok) {
        throw new Error(`Save failed: ${response.status}`);
      }
      
      const data = await response.json();
      lastSavedTimestampRef.current = data.timestamp;
      
      return data;
    } catch (error) {
      setLastError(error.message);
      throw error;
    } finally {
      setIsSaving(false);
    }
  };

  const publishDraft = async () => {
    if (!lastSavedTimestampRef.current) {
      throw new Error('No saved draft to publish');
    }
    
    setIsPublishing(true);
    setLastError(null);
    
    try {
      const response = await fetch(
        `/api/workflows/${workflowName}/drafts/${lastSavedTimestampRef.current}/publish`,
        { method: 'POST' }
      );
      
      if (!response.ok) {
        throw new Error(`Publish failed: ${response.status}`);
      }
      
      return await response.json();
    } catch (error) {
      setLastError(error.message);
      throw error;
    } finally {
      setIsPublishing(false);
    }
  };

  const runWorkflow = async (yaml, inputs = {}) => {
    setIsRunning(true);
    setLastError(null);
    
    try {
      // Step 1: Save draft
      await saveDraft(yaml);
      
      // Step 2: Publish
      await publishDraft();
      
      // Step 3: Trigger run
      const response = await fetch('/api/trigger', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workflow: workflowName, inputs }),
      });
      
      if (!response.ok) {
        throw new Error(`Run failed: ${response.status}`);
      }
      
      const data = await response.json();
      
      // Step 4: Navigate to run detail
      if (data.run_id) {
        window.location.hash = `#/workflow/${data.run_id}`;
      }
      
      return data;
    } catch (error) {
      setLastError(error.message);
      throw error;
    } finally {
      setIsRunning(false);
    }
  };

  const validateWorkflow = async (yaml) => {
    setIsValidating(true);
    setLastError(null);
    
    try {
      const response = await fetch('/api/workflows/validate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ yaml }),
      });
      
      if (!response.ok) {
        throw new Error(`Validate failed: ${response.status}`);
      }
      
      return await response.json();
    } catch (error) {
      setLastError(error.message);
      throw error;
    } finally {
      setIsValidating(false);
    }
  };

  return {
    saveDraft,
    publishDraft,
    runWorkflow,
    validateWorkflow,
    lastSavedTimestamp: lastSavedTimestampRef.current,
    isSaving,
    isPublishing,
    isRunning,
    isValidating,
    lastError,
  };
}
