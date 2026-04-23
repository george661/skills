import React from 'react';
import { dagToYaml } from './dagToYaml.js';

/**
 * YamlCodeView - Read-only YAML preview component
 * Displays serialized DAG as syntax-highlighted YAML
 */
export function YamlCodeView({ dag, viewMode }) {
  if (viewMode === 'hidden') {
    return null;
  }
  
  const yamlText = dagToYaml(dag || []);
  const highlightedContent = highlightYaml(yamlText);
  
  return (
    <section 
      role="region" 
      aria-label="YAML preview"
      className={`yaml-preview yaml-preview--${viewMode}`}
    >
      <pre className="yaml-preview-code">
        {highlightedContent}
      </pre>
    </section>
  );
}

/**
 * Simple YAML syntax highlighter using React elements
 * Wraps tokens in spans with CSS classes for styling
 */
function highlightYaml(text) {
  if (!text) return null;
  
  const lines = text.split('\n');
  const elements = [];
  
  lines.forEach((line, lineIndex) => {
    if (!line) {
      elements.push('\n');
      return;
    }
    
    // Match YAML key: value patterns
    const keyValueMatch = line.match(/^(\s*)([a-z_]+):\s*(.*)$/);
    if (keyValueMatch) {
      const [, indent, key, value] = keyValueMatch;
      elements.push(
        <React.Fragment key={`line-${lineIndex}`}>
          {indent}
          <span className="yaml-key">{key}</span>
          {': '}
          {highlightValue(value)}
          {'\n'}
        </React.Fragment>
      );
      return;
    }
    
    // Match list items (- id: value)
    const listMatch = line.match(/^(\s*-\s+)([a-z_]+):\s*(.*)$/);
    if (listMatch) {
      const [, listPrefix, key, value] = listMatch;
      elements.push(
        <React.Fragment key={`line-${lineIndex}`}>
          {listPrefix}
          <span className="yaml-key">{key}</span>
          {': '}
          {highlightValue(value)}
          {'\n'}
        </React.Fragment>
      );
      return;
    }
    
    // Block scalar indicator (|)
    if (line.match(/:\s*\|$/)) {
      elements.push(
        <React.Fragment key={`line-${lineIndex}`}>
          {line}
          {'\n'}
        </React.Fragment>
      );
      return;
    }
    
    // Default: plain line
    elements.push(
      <React.Fragment key={`line-${lineIndex}`}>
        {line}
        {'\n'}
      </React.Fragment>
    );
  });
  
  return elements;
}

function highlightValue(value) {
  if (!value) return null;
  
  // String values (quoted)
  if (value.match(/^["'].*["']$/)) {
    return <span className="yaml-string">{value}</span>;
  }
  
  // Array/flow sequence
  if (value.match(/^\[.*\]$/)) {
    return <span className="yaml-array">{value}</span>;
  }
  
  // Numbers
  if (value.match(/^\d+$/)) {
    return <span className="yaml-number">{value}</span>;
  }
  
  // Default value
  return value;
}
