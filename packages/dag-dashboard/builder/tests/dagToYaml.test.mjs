/**
 * dagToYaml.test.mjs
 * 
 * Tests the DAG→YAML serializer. Uses js-yaml to validate parsability.
 */

import { describe, it } from 'node:test';
import assert from 'node:assert';
import yaml from 'js-yaml';
import dagToYaml from '../src/dagToYaml.js';

describe('dagToYaml', () => {
  it('minimal_dag', () => {
    const result = dagToYaml({
      name: 'test-workflow',
      description: 'Test description',
      provider: 'openai',
      model: 'gpt-4',
      dag: [],
    });
    
    assert.ok(typeof result === 'string', 'Should return a string');
    assert.ok(result.length > 0, 'Should not be empty');
    
    // Parse with js-yaml to verify it's valid YAML
    const parsed = yaml.load(result);
    assert.strictEqual(parsed.name, 'test-workflow');
    assert.strictEqual(parsed.description, 'Test description');
    assert.strictEqual(parsed.provider, 'openai');
    assert.strictEqual(parsed.model, 'gpt-4');
    assert.ok(Array.isArray(parsed.nodes), 'Should have nodes array');
  });

  it('dag_with_edges', () => {
    const result = dagToYaml({
      name: 'test-workflow',
      description: 'Test with edges',
      provider: 'openai',
      model: 'gpt-4',
      dag: [
        { id: 'node1', type: 'prompt', depends_on: [] },
        { id: 'node2', type: 'bash', depends_on: ['node1'] },
      ],
    });
    
    const parsed = yaml.load(result);
    assert.strictEqual(parsed.nodes.length, 2);
    assert.strictEqual(parsed.nodes[0].id, 'node1');
    assert.strictEqual(parsed.nodes[1].id, 'node2');
    assert.ok(Array.isArray(parsed.nodes[1].depends_on), 'Should have depends_on array');
    assert.strictEqual(parsed.nodes[1].depends_on[0], 'node1');
  });
});
