/**
 * VirtualizedLogList — windowed renderer for long log streams (AC-5, GW-5423).
 *
 * Wraps a scroll container and renders only the rows currently in view plus
 * a pad above/below so scrolling feels smooth. Below the activation threshold
 * (default 200) the list falls back to rendering every row, keeping small
 * streams easy to debug in DevTools.
 *
 * Usage:
 *   const list = new VirtualizedLogList({
 *     container: el,                 // scroll container (already styled)
 *     rowHeight: 18,                 // px per row; must match CSS line-height
 *     threshold: 200,                // activate windowing above this row count
 *     renderRow: (row, i) => '<div>…</div>',  // returns innerHTML for one row
 *   });
 *   list.setRows(arrayOfRows);        // replaces the whole list
 *   list.appendRow(row);              // O(1) append
 *   list.scrollToBottom();            // force jump to tail
 *   list.isNearBottom();              // → boolean (within ROW_NEAR_BOTTOM_PX)
 *   list.destroy();                   // release scroll listener
 *
 * Contract: the consumer owns the scroll container's outer markup (including
 * any "Jump to bottom" affordance); this class only manages the inner row
 * content.
 */
(function (window) {
    'use strict';

    const DEFAULT_THRESHOLD = 200;
    const DEFAULT_ROW_HEIGHT = 18;
    const DEFAULT_OVERSCAN = 20;
    const NEAR_BOTTOM_PX = 50;

    class VirtualizedLogList {
        constructor(opts) {
            if (!opts || !opts.container) {
                throw new Error('VirtualizedLogList: container is required');
            }
            this.container = opts.container;
            this.rowHeight = opts.rowHeight || DEFAULT_ROW_HEIGHT;
            this.threshold = opts.threshold || DEFAULT_THRESHOLD;
            this.overscan = opts.overscan || DEFAULT_OVERSCAN;
            this.renderRow = opts.renderRow || ((row) => `<div>${String(row)}</div>`);

            this.rows = [];
            this.container.classList.add('virtualized-log-list');

            // Inner structure: spacer-before + window + spacer-after. Spacers
            // reserve scroll height for rows not currently in the DOM.
            this.container.innerHTML = `
                <div class="virtualized-log-list__spacer-top"></div>
                <div class="virtualized-log-list__window"></div>
                <div class="virtualized-log-list__spacer-bottom"></div>
            `;
            this.spacerTop = this.container.querySelector('.virtualized-log-list__spacer-top');
            this.windowEl = this.container.querySelector('.virtualized-log-list__window');
            this.spacerBottom = this.container.querySelector('.virtualized-log-list__spacer-bottom');

            this._onScroll = this._onScroll.bind(this);
            this.container.addEventListener('scroll', this._onScroll);
        }

        setRows(rows) {
            this.rows = Array.isArray(rows) ? rows.slice() : [];
            this._render();
        }

        appendRow(row) {
            const wasNearBottom = this.isNearBottom();
            this.rows.push(row);
            this._render();
            if (wasNearBottom) this.scrollToBottom();
        }

        get length() {
            return this.rows.length;
        }

        isNearBottom() {
            const c = this.container;
            return (c.scrollHeight - c.scrollTop - c.clientHeight) < NEAR_BOTTOM_PX;
        }

        scrollToBottom() {
            this.container.scrollTop = this.container.scrollHeight;
        }

        destroy() {
            this.container.removeEventListener('scroll', this._onScroll);
            this.container.innerHTML = '';
            this.rows = [];
        }

        _onScroll() {
            // Virtualize only above threshold; below it we render everything
            // once in _render(), so scrolling needs no extra work.
            if (this.rows.length <= this.threshold) return;
            this._render();
        }

        _render() {
            if (this.rows.length <= this.threshold) {
                // Naive path: render every row, zero spacers. Keeps small
                // streams easy to inspect in DevTools.
                this.spacerTop.style.height = '0px';
                this.spacerBottom.style.height = '0px';
                this.windowEl.innerHTML = this.rows
                    .map((r, i) => this.renderRow(r, i))
                    .join('');
                return;
            }

            // Virtualized path: compute the visible window from scroll position.
            const viewportHeight = this.container.clientHeight || 400;
            const scrollTop = this.container.scrollTop;
            const firstVisible = Math.max(0, Math.floor(scrollTop / this.rowHeight) - this.overscan);
            const visibleCount = Math.ceil(viewportHeight / this.rowHeight) + (this.overscan * 2);
            const lastVisible = Math.min(this.rows.length, firstVisible + visibleCount);

            this.spacerTop.style.height = `${firstVisible * this.rowHeight}px`;
            this.spacerBottom.style.height = `${(this.rows.length - lastVisible) * this.rowHeight}px`;

            const windowRows = this.rows.slice(firstVisible, lastVisible);
            this.windowEl.innerHTML = windowRows
                .map((r, i) => this.renderRow(r, firstVisible + i))
                .join('');
        }
    }

    window.VirtualizedLogList = VirtualizedLogList;
})(window);
