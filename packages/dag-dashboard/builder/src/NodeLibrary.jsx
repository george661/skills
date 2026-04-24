/**
 * NodeLibrary - Draggable palette of node types, commands, and skills.
 * 
 * This component provides a resizable left panel with three categories:
 * - Node types (6 runner types: bash, command, gate, interrupt, prompt, skill)
 * - Commands (workflow definitions from /api/definitions)
 * - Skills (from /api/skills)
 * 
 * Features:
 * - Live search filtering across all categories
 * - Drag-and-drop using HTML5 DnD (no react-dnd dependency)
 * - Resizable width with localStorage persistence
 * - Toggle visibility with header button
 */

import React from 'react';

// Node types (6 runner types from dag-executor)
const NODE_TYPES = [
    { name: 'bash', description: 'Execute bash script' },
    { name: 'command', description: 'Execute workflow definition' },
    { name: 'gate', description: 'Wait for approval' },
    { name: 'interrupt', description: 'Pause for human input' },
    { name: 'prompt', description: 'Execute LLM prompt' },
    { name: 'skill', description: 'Execute skill function' }
];

const STORAGE_KEY_WIDTH = 'archon-node-library-width';
const DEFAULT_WIDTH = 280;
const MIN_WIDTH = 200;
const MAX_WIDTH = 600;

class NodeLibrary extends React.Component {
    constructor(props) {
        super(props);
        
        const savedWidth = localStorage.getItem(STORAGE_KEY_WIDTH);
        const width = savedWidth ? parseInt(savedWidth, 10) : DEFAULT_WIDTH;
        
        this.state = {
            width: width,
            isResizing: false,
            isVisible: true,
            searchQuery: '',
            commands: [],
            skills: [],
            commandsLoading: true,
            skillsLoading: true
        };
        
        this.resizeHandleRef = React.createRef();
    }
    
    componentDidMount() {
        // Fetch commands
        fetch('/api/definitions')
            .then(res => res.json())
            .then(commands => {
                this.setState({ commands, commandsLoading: false });
            })
            .catch(err => {
                console.error('Failed to fetch commands:', err);
                this.setState({ commandsLoading: false });
            });
        
        // Fetch skills
        fetch('/api/skills')
            .then(res => res.json())
            .then(skills => {
                this.setState({ skills, skillsLoading: false });
            })
            .catch(err => {
                console.error('Failed to fetch skills:', err);
                this.setState({ skillsLoading: false });
            });
    }
    
    handleSearchChange = (e) => {
        this.setState({ searchQuery: e.target.value });
    };
    
    handleToggleVisibility = () => {
        this.setState(prevState => ({ isVisible: !prevState.isVisible }));
    };
    
    handleResizeStart = (e) => {
        e.preventDefault();
        this.setState({ isResizing: true });
        
        document.addEventListener('mousemove', this.handleResizeMove);
        document.addEventListener('mouseup', this.handleResizeEnd);
    };
    
    handleResizeMove = (e) => {
        if (!this.state.isResizing) return;
        
        const newWidth = Math.max(MIN_WIDTH, Math.min(MAX_WIDTH, e.clientX));
        this.setState({ width: newWidth });
    };
    
    handleResizeEnd = () => {
        if (!this.state.isResizing) return;
        
        this.setState({ isResizing: false });
        localStorage.setItem(STORAGE_KEY_WIDTH, this.state.width.toString());
        
        document.removeEventListener('mousemove', this.handleResizeMove);
        document.removeEventListener('mouseup', this.handleResizeEnd);
    };
    
    handleDragStart = (e, kind, payload) => {
        const data = JSON.stringify({ kind, payload });
        e.dataTransfer.setData('application/x-dag-node', data);
        e.dataTransfer.effectAllowed = 'copy';
    };
    
    filterItems = (items) => {
        const query = this.state.searchQuery.toLowerCase();
        if (!query) return items;
        
        return items.filter(item => 
            item.name.toLowerCase().includes(query) ||
            (item.description && item.description.toLowerCase().includes(query))
        );
    };
    
    renderCategory = (title, items, kind) => {
        const filteredItems = this.filterItems(items);
        
        if (filteredItems.length === 0 && this.state.searchQuery) {
            return null; // Hide empty categories when searching
        }
        
        return (
            <section className="node-library-category">
                <h3 className="category-title">{title}</h3>
                <div className="category-items">
                    {filteredItems.length === 0 ? (
                        <div className="empty-message">No items</div>
                    ) : (
                        filteredItems.map((item, idx) => (
                            <div
                                key={idx}
                                className="node-library-item"
                                draggable="true"
                                onDragStart={(e) => this.handleDragStart(e, kind, item)}
                            >
                                <div className="item-name">{item.name}</div>
                                {item.description && (
                                    <div className="item-description">{item.description}</div>
                                )}
                            </div>
                        ))
                    )}
                </div>
            </section>
        );
    };
    
    render() {
        const { width, isVisible, searchQuery, commands, skills, commandsLoading, skillsLoading } = this.state;
        
        if (!isVisible) {
            return (
                <div className="node-library-collapsed">
                    <button 
                        className="toggle-button"
                        onClick={this.handleToggleVisibility}
                        title="Show node library"
                    >
                        ▶
                    </button>
                </div>
            );
        }
        
        return (
            <div 
                className="node-library"
                style={{ width: `${width}px` }}
            >
                <div className="node-library-header">
                    <h2>Node Library</h2>
                    <button 
                        className="toggle-button"
                        onClick={this.handleToggleVisibility}
                        title="Hide node library"
                    >
                        ◀
                    </button>
                </div>
                
                <div className="search-container">
                    <input
                        type="text"
                        className="search-input"
                        placeholder="Search nodes..."
                        value={searchQuery}
                        onChange={this.handleSearchChange}
                    />
                </div>
                
                <div className="categories-container">
                    {this.renderCategory('Node Types', NODE_TYPES, 'node-type')}
                    
                    {commandsLoading ? (
                        <div className="loading">Loading commands...</div>
                    ) : (
                        this.renderCategory('Commands', commands, 'command')
                    )}
                    
                    {skillsLoading ? (
                        <div className="loading">Loading skills...</div>
                    ) : (
                        this.renderCategory('Skills', skills, 'skill')
                    )}
                </div>
                
                <div
                    className="resize-handle"
                    onMouseDown={this.handleResizeStart}
                    title="Drag to resize"
                />
            </div>
        );
    }
}

export default NodeLibrary;
