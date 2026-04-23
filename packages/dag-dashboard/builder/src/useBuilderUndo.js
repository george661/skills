/**
 * useBuilderUndo: snapshot-stack undo/redo hook
 * 
 * Maintains an in-memory history of up to `limit` snapshots (default 50).
 * Snapshots are captured on every atomic edit via `push(nextState)`.
 * 
 * Design:
 * - `state`: current live graph snapshot { nodes, edges }
 * - `push(nextState)`: pushes the *previous* state onto the past stack,
 *   sets current to `nextState`, clears the future stack. Drops oldest
 *   past entry when past length would exceed `limit - 1`.
 * - `undo()`: moves current into future, pops past → current. No-op if past is empty.
 * - `redo()`: moves current into past, pops future → current. No-op if future is empty.
 * - `reset(state)`: replaces current state without pushing history (treats it
 *   as a new session baseline; clears past+future). Used on external setGraph
 *   like loading a DAG from server.
 * 
 * Snapshot storage uses structural identity: hook stores { nodes, edges } references;
 * callers produce new arrays for mutations (standard React immutable-update pattern).
 * 
 * Memory cap: at most `limit` snapshots ≈ 50. Snapshots are shallow refs to
 * React-owned immutable arrays, so ~50 × (2 arrays × pointer-sized refs) — negligible.
 * 
 * @param {object} initialState - initial graph snapshot { nodes, edges }
 * @param {object} [options]
 * @param {number} [options.limit=50] - max snapshots retained
 * @returns {{
 *   state: object,
 *   push: Function,
 *   undo: Function,
 *   redo: Function,
 *   canUndo: boolean,
 *   canRedo: boolean,
 *   reset: Function
 * }}
 */
import { useState, useCallback } from 'react';

export function useBuilderUndo(initialState, { limit = 50 } = {}) {
    const [state, setState] = useState(initialState);
    const [past, setPast] = useState([]);
    const [future, setFuture] = useState([]);

    const push = useCallback((nextState) => {
        // Reference-equality check: same object is a no-op
        if (nextState === state) return;

        setState(nextState);
        setPast(prev => {
            const newPast = [...prev, state];
            // Drop oldest entries if we exceed limit - 1
            // (keeping `limit` total snapshots reachable: past + current)
            if (newPast.length > limit - 1) {
                return newPast.slice(newPast.length - (limit - 1));
            }
            return newPast;
        });
        setFuture([]); // Clear future on new push
    }, [state, limit]);

    const undo = useCallback(() => {
        if (past.length === 0) return;

        const previous = past[past.length - 1];
        const newPast = past.slice(0, -1);

        setPast(newPast);
        setFuture(prev => [...prev, state]);
        setState(previous);
    }, [past, state]);

    const redo = useCallback(() => {
        if (future.length === 0) return;

        const next = future[future.length - 1];
        const newFuture = future.slice(0, -1);

        setFuture(newFuture);
        setPast(prev => [...prev, state]);
        setState(next);
    }, [future, state]);

    const reset = useCallback((newState) => {
        setState(newState);
        setPast([]);
        setFuture([]);
    }, []);

    return {
        state,
        push,
        undo,
        redo,
        canUndo: past.length > 0,
        canRedo: future.length > 0,
        reset,
    };
}
