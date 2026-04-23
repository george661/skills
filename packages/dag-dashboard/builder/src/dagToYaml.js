/**
 * dagToYaml - Pure DAG to YAML serializer
 * Zero dependencies, pydantic-schema-compatible output
 */

export function dagToYaml(dag) {
  if (!dag || dag.length === 0) {
    return '';
  }

  const lines = ['nodes:'];
  
  dag.forEach(node => {
    lines.push('  - id: ' + quoteIfNeeded(node.id));
    
    // Canonical field order: id, name, type, <type-specific fields>, depends_on
    if (node.name) {
      lines.push('    name: ' + quoteIfNeeded(node.name));
    }
    
    lines.push('    type: ' + node.type);
    
    // Type-specific fields
    if (node.type === 'bash' && node.script) {
      lines.push(...serializeMultilineField('script', node.script, 4));
    }
    if (node.type === 'skill' && node.skill) {
      lines.push('    skill: ' + quoteIfNeeded(node.skill));
    }
    if (node.type === 'command' && node.command) {
      lines.push('    command: ' + quoteIfNeeded(node.command));
    }
    if (node.type === 'prompt' && node.prompt) {
      lines.push(...serializeMultilineField('prompt', node.prompt, 4));
    }
    if (node.type === 'gate' && node.condition) {
      lines.push('    condition: ' + quoteIfNeeded(node.condition));
    }
    if (node.type === 'interrupt' && node.message) {
      lines.push('    message: ' + quoteIfNeeded(node.message));
    }
    
    // depends_on as flow sequence
    if (node.depends_on && node.depends_on.length > 0) {
      lines.push('    depends_on: [' + node.depends_on.join(', ') + ']');
    }
  });
  
  return lines.join('\n') + '\n';
}

function quoteIfNeeded(str) {
  if (!str) return '""';
  
  // Quote if contains special YAML chars
  if (str.includes(':') || str.includes('#') || str.match(/^\s/) || str.match(/\s$/)) {
    return '"' + str.replace(/"/g, '\\"') + '"';
  }
  
  return str;
}

function serializeMultilineField(fieldName, value, indent) {
  const lines = [];
  const indentStr = ' '.repeat(indent);
  
  if (value.includes('\n')) {
    // Use block scalar for multiline
    lines.push(indentStr + fieldName + ': |');
    const contentLines = value.split('\n');
    contentLines.forEach(line => {
      lines.push(indentStr + '  ' + line);
    });
  } else {
    // Single line
    lines.push(indentStr + fieldName + ': ' + quoteIfNeeded(value));
  }
  
  return lines;
}
