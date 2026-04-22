/**
 * SearchBar component - Global search with keyboard shortcut support
 */
(function() {
    'use strict';

    // Global state for shortcut listener (installed once across all instances)
    let _globalShortcutInstalled = false;

    // Instance state
    const instances = new WeakMap();

    function _escape(str) {
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    function init(containerEl) {
        if (!containerEl) return;

        // Create instance state
        const state = {
            containerEl: containerEl,
            inputEl: null,
            resultsEl: null,
            debounceTimer: null,
            abortController: null,
            selectedIndex: -1,
            results: []
        };

        instances.set(containerEl, state);

        // Render the search bar HTML
        containerEl.innerHTML = `
            <div class="search-bar">
                <input 
                    type="text" 
                    class="search-input" 
                    placeholder="Search workflows and nodes (press / to focus)"
                    autocomplete="off"
                    aria-label="Search"
                    aria-autocomplete="list"
                    role="combobox"
                    aria-expanded="false"
                    aria-controls="search-results-${Date.now()}"
                    aria-activedescendant=""
                />
                <div class="search-results" id="search-results-${Date.now()}" role="listbox"></div>
            </div>
        `;

        state.inputEl = containerEl.querySelector('.search-input');
        state.resultsEl = containerEl.querySelector('.search-results');

        // Wire up event handlers
        state.inputEl.addEventListener('input', (e) => _onInput(state, e));
        state.inputEl.addEventListener('keydown', (e) => _onKeydown(state, e));
        state.inputEl.addEventListener('blur', () => {
            // Delay to allow click events on results
            setTimeout(() => _hideResults(state), 200);
        });

        // Install global '/' shortcut listener (once)
        if (!_globalShortcutInstalled) {
            _globalShortcutInstalled = true;
            document.addEventListener('keydown', (e) => {
                // Only if '/' pressed, no modifiers, and no input/textarea focused
                if (e.key === '/' && !e.ctrlKey && !e.metaKey && !e.altKey && !e.shiftKey) {
                    const activeEl = document.activeElement;
                    if (activeEl && (activeEl.tagName === 'INPUT' || activeEl.tagName === 'TEXTAREA')) {
                        return;
                    }
                    e.preventDefault();
                    // Focus the first search input on the page
                    const firstSearchInput = document.querySelector('.search-input');
                    if (firstSearchInput) {
                        firstSearchInput.focus();
                    }
                }
            });
        }
    }

    function _onInput(state, e) {
        const query = e.target.value.trim();

        // Clear previous timer
        if (state.debounceTimer) {
            clearTimeout(state.debounceTimer);
        }

        // Hide results if query too short
        if (query.length < 2) {
            _hideResults(state);
            return;
        }

        // Debounce fetch by 250ms
        state.debounceTimer = setTimeout(() => {
            _fetch(state, query);
        }, 250);
    }

    function _fetch(state, query) {
        // Abort previous fetch
        if (state.abortController) {
            state.abortController.abort();
        }

        state.abortController = new AbortController();

        fetch('/api/search?q=' + encodeURIComponent(query), {
            signal: state.abortController.signal
        })
            .then(response => {
                if (!response.ok) {
                    throw new Error('Search unavailable');
                }
                return response.json();
            })
            .then(data => {
                state.results = (data.results || []).slice(0, 10);
                _renderResults(state);
            })
            .catch(err => {
                if (err.name === 'AbortError') {
                    // Fetch was aborted, ignore
                    return;
                }
                // Show error state
                state.results = [];
                _renderError(state);
            });
    }

    function _renderResults(state) {
        if (state.results.length === 0) {
            state.resultsEl.innerHTML = '<div class="search-empty">No matches</div>';
            state.resultsEl.style.display = 'block';
            state.inputEl.setAttribute('aria-expanded', 'true');
            return;
        }

        state.selectedIndex = -1;
        state.inputEl.setAttribute('aria-activedescendant', '');

        const html = state.results.map((result, index) => {
            const id = 'search-result-' + index;
            const label = _escape(result.label || '');
            const subtitle = result.subtitle ? _escape(result.subtitle) : '';
            return `
                <div 
                    class="search-result-item" 
                    id="${id}" 
                    role="option" 
                    data-index="${index}"
                    aria-selected="false"
                >
                    <div class="search-result-label">${label}</div>
                    ${subtitle ? `<div class="search-result-subtitle">${subtitle}</div>` : ''}
                </div>
            `;
        }).join('');

        state.resultsEl.innerHTML = html;
        state.resultsEl.style.display = 'block';
        state.inputEl.setAttribute('aria-expanded', 'true');

        // Add click handlers
        state.resultsEl.querySelectorAll('.search-result-item').forEach((el, index) => {
            el.addEventListener('click', () => {
                _navigate(state, state.results[index]);
            });
        });
    }

    function _renderError(state) {
        state.resultsEl.innerHTML = '<div class="search-empty">Search unavailable</div>';
        state.resultsEl.style.display = 'block';
        state.inputEl.setAttribute('aria-expanded', 'true');
    }

    function _hideResults(state) {
        state.resultsEl.style.display = 'none';
        state.inputEl.setAttribute('aria-expanded', 'false');
        state.inputEl.setAttribute('aria-activedescendant', '');
        state.selectedIndex = -1;
    }

    function _onKeydown(state, e) {
        const isOpen = state.resultsEl.style.display === 'block';

        if (!isOpen) return;

        if (e.key === 'ArrowDown') {
            e.preventDefault();
            _selectNext(state);
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            _selectPrev(state);
        } else if (e.key === 'Enter') {
            e.preventDefault();
            if (state.selectedIndex >= 0 && state.selectedIndex < state.results.length) {
                _navigate(state, state.results[state.selectedIndex]);
            }
        } else if (e.key === 'Escape') {
            e.preventDefault();
            _hideResults(state);
            state.inputEl.blur();
        }
    }

    function _selectNext(state) {
        const items = state.resultsEl.querySelectorAll('.search-result-item');
        if (items.length === 0) return;

        // Clear previous selection
        if (state.selectedIndex >= 0) {
            items[state.selectedIndex].classList.remove('selected');
            items[state.selectedIndex].setAttribute('aria-selected', 'false');
        }

        // Move to next (wrap around)
        state.selectedIndex = (state.selectedIndex + 1) % items.length;

        // Apply new selection
        items[state.selectedIndex].classList.add('selected');
        items[state.selectedIndex].setAttribute('aria-selected', 'true');
        state.inputEl.setAttribute('aria-activedescendant', items[state.selectedIndex].id);
    }

    function _selectPrev(state) {
        const items = state.resultsEl.querySelectorAll('.search-result-item');
        if (items.length === 0) return;

        // Clear previous selection
        if (state.selectedIndex >= 0) {
            items[state.selectedIndex].classList.remove('selected');
            items[state.selectedIndex].setAttribute('aria-selected', 'false');
        }

        // Move to prev (wrap around)
        state.selectedIndex = state.selectedIndex <= 0 ? items.length - 1 : state.selectedIndex - 1;

        // Apply new selection
        items[state.selectedIndex].classList.add('selected');
        items[state.selectedIndex].setAttribute('aria-selected', 'true');
        state.inputEl.setAttribute('aria-activedescendant', items[state.selectedIndex].id);
    }

    function _navigate(state, result) {
        if (!result) return;

        if (result.kind === 'run') {
            // Navigate to workflow detail
            window.location.hash = '/workflow/' + encodeURIComponent(result.run_id);
        } else if (result.kind === 'node') {
            // Navigate to workflow first, then dispatch node-click event
            window.location.hash = '/workflow/' + encodeURIComponent(result.run_id);
            // Dispatch on next tick to let router render first
            setTimeout(() => {
                window.dispatchEvent(new CustomEvent('node-click', {
                    detail: { id: result.run_id + ':' + result.node_id }
                }));
            }, 0);
        }

        _hideResults(state);
        state.inputEl.blur();
    }

    // Export to global
    window.SearchBar = {
        init: init
    };
})();
