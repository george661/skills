import { useEffect, useRef, useState, useCallback } from 'react';

/**
 * useAutosave hook - debounced autosave with .current pointer management
 * 
 * @param {Object} options
 * @param {string} options.workflowName - Workflow name
 * @param {Function} options.getDag - Function that returns current DAG
 * @param {Function} [options.onLoad] - Callback when draft is loaded on bootstrap
 * @param {number} [options.delayMs=30000] - Debounce delay in milliseconds
 * @param {Function} [options.fetch=window.fetch] - Fetch function (injectable for testing)
 * @param {Function} [options.setTimer=setTimeout] - Timer setter (injectable for testing)
 * @param {Function} [options.clearTimer=clearTimeout] - Timer clearer (injectable for testing)
 * @returns {Object} { status, forceSave, lastSavedAt, currentTimestamp, markDirty }
 */
export function useAutosave({
    workflowName,
    getDag,
    onLoad,
    delayMs = 30000,
    fetch = window.fetch,
    setTimer = setTimeout,
    clearTimer = clearTimeout
}) {
    const [status, setStatus] = useState('idle');
    const [currentTimestamp, setCurrentTimestamp] = useState(null);
    const [lastSavedAt, setLastSavedAt] = useState(null);

    const timerRef = useRef(null);
    const lastDagHashRef = useRef(null);
    const autosaveRef = useRef(null);

    // Bootstrap: load or create draft
    useEffect(() => {
        const bootstrap = async () => {
            try {
                // Try to load current draft pointer
                const currentResponse = await fetch(`/api/workflows/${workflowName}/drafts/current`);
                
                if (currentResponse.ok) {
                    // Load existing draft
                    const { timestamp } = await currentResponse.json();
                    setCurrentTimestamp(timestamp);
                    
                    const draftResponse = await fetch(`/api/workflows/${workflowName}/drafts/${timestamp}`);
                    if (draftResponse.ok) {
                        const { content } = await draftResponse.json();
                        const parsed = JSON.parse(content);
                        if (onLoad) {
                            onLoad(parsed.nodes || []);
                        }
                        lastDagHashRef.current = JSON.stringify(parsed.nodes || []);
                    }
                } else if (currentResponse.status === 404) {
                    // Create new draft
                    const createResponse = await fetch(
                        `/api/workflows/${workflowName}/drafts`,
                        {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ content: JSON.stringify({ nodes: [] }) })
                        }
                    );
                    
                    if (createResponse.ok) {
                        const { timestamp } = await createResponse.json();
                        setCurrentTimestamp(timestamp);

                        // Set .current pointer
                        await fetch(
                            `/api/workflows/${workflowName}/drafts/current`,
                            {
                                method: 'PUT',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({ timestamp })
                            }
                        );

                        // Signal bootstrap-complete to the consumer with an empty DAG
                        // so the builder can flip out of its "Loading..." state.
                        if (onLoad) {
                            onLoad([]);
                        }
                        lastDagHashRef.current = JSON.stringify([]);
                    }
                }
            } catch (err) {
                console.error('Bootstrap failed:', err);
                setStatus('error');
            }
        };
        
        bootstrap();
    }, [workflowName, fetch, onLoad]);

    // Autosave logic - store in ref for stable reference
    autosaveRef.current = async () => {
        if (!currentTimestamp) return;

        try {
            setStatus('saving');
            const dag = getDag();
            const content = JSON.stringify({ nodes: dag });

            await fetch(
                `/api/workflows/${workflowName}/drafts/${currentTimestamp}`,
                {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ content })
                }
            );

            lastDagHashRef.current = JSON.stringify(dag);
            setLastSavedAt(Date.now());
            setStatus('saved');
        } catch (err) {
            console.error('Autosave failed:', err);
            setStatus('error');
        }
    };

    // Mark dirty and schedule autosave
    const markDirty = useCallback(() => {
        const dag = getDag();
        const currentHash = JSON.stringify(dag);

        // Check if dag actually changed
        if (currentHash === lastDagHashRef.current) {
            return;
        }

        // Clear existing timer
        if (timerRef.current !== null) {
            clearTimer(timerRef.current);
        }

        setStatus('unsaved');

        // Schedule new autosave
        timerRef.current = setTimer(() => {
            autosaveRef.current();
            timerRef.current = null;
        }, delayMs);
    }, [getDag, clearTimer, setTimer, delayMs]);

    // Force save - create new timestamp
    const forceSave = useCallback(async () => {
        // Cancel any pending autosave
        if (timerRef.current !== null) {
            clearTimer(timerRef.current);
            timerRef.current = null;
        }

        try {
            setStatus('saving');
            const dag = getDag();
            const content = JSON.stringify({ nodes: dag });

            // Create new draft with new timestamp
            const createResponse = await fetch(
                `/api/workflows/${workflowName}/drafts`,
                {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ content })
                }
            );

            if (createResponse.ok) {
                const { timestamp } = await createResponse.json();

                // Update .current pointer
                await fetch(
                    `/api/workflows/${workflowName}/drafts/current`,
                    {
                        method: 'PUT',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ timestamp })
                    }
                );

                setCurrentTimestamp(timestamp);
                lastDagHashRef.current = JSON.stringify(dag);
                setLastSavedAt(Date.now());
                setStatus('saved');
            }
        } catch (err) {
            console.error('Force save failed:', err);
            setStatus('error');
        }
    }, [getDag, clearTimer, fetch, workflowName]);

    // Cleanup timer on unmount
    useEffect(() => {
        return () => {
            if (timerRef.current !== null) {
                clearTimer(timerRef.current);
            }
        };
    }, [clearTimer]);

    return {
        status,
        forceSave,
        lastSavedAt,
        currentTimestamp,
        markDirty
    };
}
