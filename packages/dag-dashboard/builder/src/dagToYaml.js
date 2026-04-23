/**
 * dagToYaml.js
 * 
 * Minimal hand-rolled YAML emitter: converts DAG + metadata to YAML string.
 * No external library in production bundle - keeps bundle size small.
 */

export default function dagToYaml({ name, description, provider, model, dag }) {
  const indent = '  ';
  let yaml = '';
  
  // Top-level metadata
  yaml += `name: ${quoteIfNeeded(name)}\n`;
  yaml += `description: ${quoteIfNeeded(description)}\n`;
  yaml += `provider: ${quoteIfNeeded(provider)}\n`;
  yaml += `model: ${quoteIfNeeded(model)}\n`;
  
  // Nodes array
  yaml += 'nodes:\n';
  
  if (dag.length === 0) {
    yaml += `${indent}[]\n`;
  } else {
    dag.forEach((node) => {
      yaml += `${indent}- id: ${quoteIfNeeded(node.id)}\n`;
      yaml += `${indent}${indent}type: ${quoteIfNeeded(node.type)}\n`;
      
      // depends_on array
      if (node.depends_on && node.depends_on.length > 0) {
        yaml += `${indent}${indent}depends_on:\n`;
        node.depends_on.forEach((dep) => {
          yaml += `${indent}${indent}${indent}- ${quoteIfNeeded(dep)}\n`;
        });
      } else {
        yaml += `${indent}${indent}depends_on: []\n`;
      }
      
      // Include other node properties (prompt, script, etc.)
      Object.keys(node).forEach((key) => {
        if (!['id', 'type', 'depends_on'].includes(key)) {
          const value = node[key];
          if (typeof value === 'string') {
            yaml += `${indent}${indent}${key}: ${quoteIfNeeded(value)}\n`;
          } else if (typeof value === 'object' && value !== null) {
            yaml += `${indent}${indent}${key}: ${JSON.stringify(value)}\n`;
          } else {
            yaml += `${indent}${indent}${key}: ${value}\n`;
          }
        }
      });
    });
  }
  
  return yaml;
}

function quoteIfNeeded(str) {
  if (str === null || str === undefined) {
    return '""';
  }
  
  const s = String(str);
  
  // Quote if contains special chars, starts with special chars, or is multi-line
  if (
    s.includes(':') ||
    s.includes('#') ||
    s.includes('\n') ||
    s.includes('"') ||
    s.startsWith('-') ||
    s.startsWith('[') ||
    s.startsWith('{') ||
    s.trim() !== s
  ) {
    // Escape double quotes and wrap in quotes
    return `"${s.replace(/"/g, '\\"')}"`;
  }
  
  return s;
}
