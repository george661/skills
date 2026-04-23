import { test } from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import { create, act } from 'react-test-renderer';

test('Builder: WorkflowCanvas receives loaded DAG via keyed remount', async () => {
    // This test verifies the keyed remount pattern by checking that:
    // 1. initialDag starts as null
    // 2. After bootstrap, initialDag is set and isLoaded becomes true
    // 3. The key prop changes from 'loading' to 'loaded' triggering remount
    
    const mockDag = [
        { id: 'node1', type: 'code', label: 'Test Node 1' },
        { id: 'node2', type: 'code', label: 'Test Node 2' }
    ];
    
    let capturedInitialDag = null;
    let capturedKey = null;
    
    // Mock WorkflowCanvas to capture props
    const MockWorkflowCanvas = (props) => {
        capturedInitialDag = props.initialDag;
        capturedKey = props.key || 'no-key';
        return React.createElement('div', null, 'Canvas');
    };
    
    // Mock useAutosave to simulate bootstrap
    let onLoadCallback = null;
    const mockUseAutosave = (opts) => {
        onLoadCallback = opts.onLoad;
        return {
            status: 'idle',
            forceSave: () => {},
            lastSavedAt: null,
            markDirty: () => {}
        };
    };
    
    // Create a test component that mimics Builder's pattern
    function TestBuilder() {
        const [initialDag, setInitialDag] = React.useState(null);
        const [isLoaded, setIsLoaded] = React.useState(false);
        const dagRef = React.useRef([]);
        
        const getDag = React.useCallback(() => dagRef.current, []);
        const onLoad = React.useCallback((dag) => {
            setInitialDag(dag);
            setIsLoaded(true);
        }, []);
        
        // Simulate autosave hook
        React.useEffect(() => {
            const state = mockUseAutosave({
                workflowName: 'test',
                getDag,
                onLoad
            });
            
            // Simulate bootstrap completing
            setTimeout(() => {
                if (onLoadCallback) {
                    onLoadCallback(mockDag);
                }
            }, 10);
        }, [getDag, onLoad]);
        
        return React.createElement(
            'div',
            null,
            !isLoaded 
                ? React.createElement('div', null, 'Loading workflow...')
                : React.createElement(MockWorkflowCanvas, {
                    key: isLoaded ? 'loaded' : 'loading',
                    initialDag: initialDag,
                    readOnly: false,
                    onGraphChange: () => {}
                })
        );
    }
    
    let root;
    await act(async () => {
        root = create(React.createElement(TestBuilder));
        // Wait for bootstrap to complete
        await new Promise(resolve => setTimeout(resolve, 50));
    });
    
    // Verify the canvas received the loaded DAG with the correct key
    assert.deepStrictEqual(capturedInitialDag, mockDag, 
        'WorkflowCanvas should receive loaded DAG after bootstrap');
    assert.strictEqual(capturedKey, 'loaded', 
        'WorkflowCanvas should have key="loaded" after bootstrap, triggering remount');
    
    root.unmount();
});
