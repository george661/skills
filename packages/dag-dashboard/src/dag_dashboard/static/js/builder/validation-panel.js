/**
 * validation-panel.js - Collapsible validation panel showing errors and warnings
 * 
 * Classical React component (ES5, no imports) for builder integration.
 * Displays validation issues with click-to-focus on nodes.
 */

(function() {
  'use strict';
  
  // Ensure React is available (loaded via builder bundle)
  if (typeof React === 'undefined') {
    console.error('ValidationPanel: React not loaded');
    return;
  }
  
  var Component = React.Component;
  var createElement = React.createElement;
  
  /**
   * ValidationPanel - Collapsible panel displaying errors and warnings
   * 
   * Props:
   *   - errors: ValidationIssue[] - List of error issues
   *   - warnings: ValidationIssue[] - List of warning issues
   *   - onIssueClick: (nodeId: string) => void - Callback when issue is clicked
   */
  var ValidationPanel = (function(_super) {
    // Extend React.Component
    function ValidationPanel(props) {
      _super.call(this, props);
      this.state = {
        collapsed: false
      };
      
      this.toggleCollapse = this.toggleCollapse.bind(this);
      this.handleIssueClick = this.handleIssueClick.bind(this);
    }
    
    // Set up prototype chain
    if (_super) {
      ValidationPanel.prototype = Object.create(_super.prototype);
      ValidationPanel.prototype.constructor = ValidationPanel;
    }
    
    ValidationPanel.prototype.toggleCollapse = function() {
      this.setState({ collapsed: !this.state.collapsed });
    };
    
    ValidationPanel.prototype.handleIssueClick = function(issue) {
      if (issue.node_id && this.props.onIssueClick) {
        this.props.onIssueClick(issue.node_id);
      }
    };
    
    ValidationPanel.prototype.render = function() {
      var errors = this.props.errors || [];
      var warnings = this.props.warnings || [];
      var collapsed = this.state.collapsed;
      
      var totalIssues = errors.length + warnings.length;
      
      if (totalIssues === 0) {
        return null; // Don't render if no issues
      }
      
      // Panel header
      var headerText = totalIssues + ' issue' + (totalIssues > 1 ? 's' : '') + ' found';
      if (errors.length > 0 && warnings.length > 0) {
        headerText = errors.length + ' error' + (errors.length > 1 ? 's' : '') + ', ' + 
                     warnings.length + ' warning' + (warnings.length > 1 ? 's' : '');
      } else if (errors.length > 0) {
        headerText = errors.length + ' error' + (errors.length > 1 ? 's' : '');
      } else {
        headerText = warnings.length + ' warning' + (warnings.length > 1 ? 's' : '');
      }
      
      var toggleIcon = collapsed ? '▶' : '▼';
      
      return createElement('div', {
        className: 'validation-panel',
        style: {
          position: 'fixed',
          bottom: 0,
          left: 0,
          right: 0,
          backgroundColor: '#fff',
          borderTop: '2px solid ' + (errors.length > 0 ? '#dc3545' : '#ffc107'),
          boxShadow: '0 -2px 10px rgba(0,0,0,0.1)',
          zIndex: 1000,
          maxHeight: collapsed ? '50px' : '300px',
          transition: 'max-height 0.3s ease'
        }
      }, [
        // Header
        createElement('div', {
          key: 'header',
          onClick: this.toggleCollapse,
          style: {
            padding: '12px 20px',
            cursor: 'pointer',
            fontWeight: 'bold',
            backgroundColor: errors.length > 0 ? '#f8d7da' : '#fff3cd',
            color: errors.length > 0 ? '#721c24' : '#856404',
            userSelect: 'none'
          }
        }, [
          createElement('span', { key: 'icon', style: { marginRight: '8px' } }, toggleIcon),
          createElement('span', { key: 'text' }, headerText)
        ]),
        
        // Issues list
        !collapsed && createElement('div', {
          key: 'issues',
          style: {
            padding: '10px 20px',
            maxHeight: '250px',
            overflowY: 'auto'
          }
        }, [
          // Errors
          errors.length > 0 && createElement('div', { key: 'errors', style: { marginBottom: '10px' } },
            errors.map(function(issue, idx) {
              return createElement('div', {
                key: 'error-' + idx,
                onClick: function() { this.handleIssueClick(issue); }.bind(this),
                style: {
                  padding: '8px 12px',
                  marginBottom: '6px',
                  backgroundColor: '#f8d7da',
                  border: '1px solid #f5c6cb',
                  borderRadius: '4px',
                  cursor: issue.node_id ? 'pointer' : 'default',
                  color: '#721c24'
                }
              }, [
                createElement('strong', { key: 'severity', style: { color: '#dc3545' } }, 'ERROR: '),
                createElement('span', { key: 'message' }, issue.message),
                issue.node_id && createElement('span', {
                  key: 'node',
                  style: { marginLeft: '8px', fontSize: '0.9em', color: '#666' }
                }, '(node: ' + issue.node_id + ')')
              ]);
            }.bind(this))
          ),
          
          // Warnings
          warnings.length > 0 && createElement('div', { key: 'warnings' },
            warnings.map(function(issue, idx) {
              return createElement('div', {
                key: 'warning-' + idx,
                onClick: function() { this.handleIssueClick(issue); }.bind(this),
                style: {
                  padding: '8px 12px',
                  marginBottom: '6px',
                  backgroundColor: '#fff3cd',
                  border: '1px solid '#ffeaa7',
                  borderRadius: '4px',
                  cursor: issue.node_id ? 'pointer' : 'default',
                  color: '#856404'
                }
              }, [
                createElement('strong', { key: 'severity', style: { color: '#ffc107' } }, 'WARNING: '),
                createElement('span', { key: 'message' }, issue.message),
                issue.node_id && createElement('span', {
                  key: 'node',
                  style: { marginLeft: '8px', fontSize: '0.9em', color: '#666' }
                }, '(node: ' + issue.node_id + ')')
              ]);
            }.bind(this))
          )
        ])
      ]);
    };
    
    return ValidationPanel;
  })(Component);
  
  // Export to global namespace
  if (typeof window !== 'undefined') {
    window.DAGDashboardValidation = window.DAGDashboardValidation || {};
    window.DAGDashboardValidation.ValidationPanel = ValidationPanel;
  }
})();
