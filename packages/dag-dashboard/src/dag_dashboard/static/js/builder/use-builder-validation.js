/**
 * use-builder-validation.js - Hook for running client-side validation on canvas state
 * 
 * Classical React hook (ES5, no imports) that runs validation rules and aggregates results.
 */

(function() {
  'use strict';
  
  // Ensure React is available
  if (typeof React === 'undefined' || typeof React.useState === 'undefined') {
    console.error('useBuilderValidation: React hooks not available');
    return;
  }
  
  /**
   * useBuilderValidation - Run validation rules on canvas state
   * 
   * @param {Object} canvasState - Shape: { nodes: [{id, type, depends_on, ...}] }
   * @returns {Object} { errors: ValidationIssue[], warnings: ValidationIssue[], errorsByNode: Map<nodeId, ValidationIssue[]> }
   */
  function useBuilderValidation(canvasState) {
    var useState = React.useState;
    var useEffect = React.useEffect;
    var useMemo = React.useMemo;
    
    // Get validation rules from global namespace
    var rules = (window.DAGDashboardValidation && window.DAGDashboardValidation.rules) || {};
    
    // Memoize validation results to avoid recalculating on every render
    var validationResults = useMemo(function() {
      var allErrors = [];
      var allWarnings = [];
      
      if (!canvasState || !canvasState.nodes) {
        return { errors: allErrors, warnings: allWarnings, errorsByNode: new Map() };
      }
      
      // Run each validation rule
      if (rules.requiredFields) {
        allErrors = allErrors.concat(rules.requiredFields(canvasState));
      }
      
      if (rules.uniqueNodeIds) {
        allErrors = allErrors.concat(rules.uniqueNodeIds(canvasState));
      }
      
      if (rules.detectCycles) {
        allErrors = allErrors.concat(rules.detectCycles(canvasState));
      }
      
      if (rules.referenceIntegrity) {
        allErrors = allErrors.concat(rules.referenceIntegrity(canvasState));
      }
      
      // Group errors by node_id for quick lookup
      var errorsByNode = new Map();
      for (var i = 0; i < allErrors.length; i++) {
        var error = allErrors[i];
        if (error.node_id) {
          if (!errorsByNode.has(error.node_id)) {
            errorsByNode.set(error.node_id, []);
          }
          errorsByNode.get(error.node_id).push(error);
        }
      }
      
      return {
        errors: allErrors,
        warnings: allWarnings,
        errorsByNode: errorsByNode
      };
    }, [canvasState, rules]);
    
    return validationResults;
  }
  
  // Export to global namespace
  if (typeof window !== 'undefined') {
    window.DAGDashboardValidation = window.DAGDashboardValidation || {};
    window.DAGDashboardValidation.useBuilderValidation = useBuilderValidation;
  }
})();
