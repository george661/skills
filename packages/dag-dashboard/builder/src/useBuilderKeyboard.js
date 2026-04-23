/**
 * useBuilderKeyboard: keyboard shortcut registry hook
 * 
 * Registers keyboard shortcuts and attaches a keydown listener to the specified target.
 * Shortcuts are normalised strings like "mod+s", "mod+z", "mod+shift+z", "delete".
 * "mod" maps to metaKey on macOS, ctrlKey elsewhere.
 * 
 * Behavior:
 * - event.preventDefault() is called when a matching handler fires
 * - Handlers receive the raw KeyboardEvent
 * - Ignores keys when event.target is an <input>, <textarea>, or contenteditable element
 *   (otherwise Cmd+S inside a text field would trap the user)
 * - Listener cleanup on unmount/disable is strict to avoid leaks
 * 
 * @param {object} shortcuts - map of shortcut keys to handlers: { [key]: handler }
 * @param {object} [options]
 * @param {object} [options.target] - event target (default: document, but tests can override)
 * @param {boolean} [options.enabled=true] - whether shortcuts are active
 * @param {boolean} [options.isMac] - override platform detection (for testing)
 */
import { useEffect } from 'react';

/**
 * Normalise a keyboard event to a shortcut key string
 */
function normaliseKey(event, isMac) {
    const parts = [];
    
    const modPressed = isMac ? event.metaKey : event.ctrlKey;
    if (modPressed) parts.push('mod');
    if (event.shiftKey) parts.push('shift');
    
    let key = event.key.toLowerCase();
    // Special case: Enter should stay as 'enter' not lowercase 'enter'
    if (event.key === 'Enter') key = 'enter';
    // Special case: Delete
    if (event.key === 'Delete' || event.key === 'Backspace') key = 'delete';
    
    parts.push(key);
    return parts.join('+');
}

/**
 * Check if the event target is a text-editing element
 */
function isTextInput(target) {
    if (!target) return false;
    const tagName = target.tagName;
    if (tagName === 'INPUT' || tagName === 'TEXTAREA') return true;
    if (target.isContentEditable) return true;
    return false;
}

export function useBuilderKeyboard(shortcuts, { target = null, enabled = true, isMac = null } = {}) {
    useEffect(() => {
        if (!enabled) return;
        
        // Detect platform if not overridden
        const platformIsMac = isMac !== null ? isMac : (typeof navigator !== 'undefined' && /Mac|iPhone|iPad|iPod/.test(navigator.platform));
        
        // Use document if no target specified
        const eventTarget = target || (typeof document !== 'undefined' ? document : null);
        if (!eventTarget) return;
        
        const handler = (event) => {
            // Suppress shortcuts inside text-editing elements
            if (isTextInput(event.target)) return;
            
            const key = normaliseKey(event, platformIsMac);
            const callback = shortcuts[key];
            
            if (callback) {
                event.preventDefault();
                callback(event);
            }
        };
        
        eventTarget.addEventListener('keydown', handler);
        
        return () => {
            eventTarget.removeEventListener('keydown', handler);
        };
    }, [shortcuts, target, enabled, isMac]);
}
