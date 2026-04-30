/**
 * NodeScrollBus — pub/sub for DAG↔feed cross-selection.
 *
 * Maintains a monotonic counter and broadcasts { counter, nodeId, source }
 * to every subscriber on trigger(). `source` is 'dag' or 'feed' so each side
 * can ignore its own triggers and avoid feedback loops.
 *
 * Usage:
 *   window.NodeScrollBus.subscribe((nodeId, source) => {
 *       if (source === 'dag') { scrollFeedTo(nodeId); }
 *   });
 *   window.NodeScrollBus.trigger('node-a', 'dag');
 *
 * Use window.NodeScrollBus.clear() in SPA lifecycle cleanup to drop all
 * subscribers and reset the counter.
 */

(function (window) {
    'use strict';

    let counter = 0;
    const subscribers = [];

    function trigger(nodeId, source) {
        if (!nodeId) return;
        counter += 1;
        const evt = { counter, nodeId, source: source || 'unknown' };
        for (const cb of subscribers.slice()) {
            try {
                cb(nodeId, source || 'unknown', evt);
            } catch (e) {
                console.error('NodeScrollBus subscriber threw', e);
            }
        }
    }

    function subscribe(cb) {
        if (typeof cb === 'function') subscribers.push(cb);
    }

    function unsubscribe(cb) {
        const i = subscribers.indexOf(cb);
        if (i >= 0) subscribers.splice(i, 1);
    }

    function clear() {
        subscribers.length = 0;
        counter = 0;
    }

    function getCounter() {
        return counter;
    }

    window.NodeScrollBus = {
        trigger,
        subscribe,
        unsubscribe,
        clear,
        getCounter,
    };
})(window);
