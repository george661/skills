import { test } from 'node:test';
import assert from 'node:assert/strict';
import { dagToYaml } from '../src/dagToYaml.js';

test('dagToYaml([]) returns empty string or blank line', () => {
  const result = dagToYaml([]);
  assert.ok(result === '' || result === '\n', 'Empty DAG should return empty string or single newline');
});

test('Single bash node with script', () => {
  const dag = [
    {
      id: 'foo',
      type: 'bash',
      script: 'echo hello'
    }
  ];
  const yaml = dagToYaml(dag);
  assert.match(yaml, /nodes:/, 'Should contain nodes key');
  assert.match(yaml, /- id: foo/, 'Should contain node id');
  assert.match(yaml, /type: bash/, 'Should contain node type');
  assert.match(yaml, /script:/, 'Should contain script field');
});

test('Skill node with skill field renders unquoted when no special chars', () => {
  const dag = [
    {
      id: 'skill1',
      type: 'skill',
      skill: 'jira/get_issue'
    }
  ];
  const yaml = dagToYaml(dag);
  assert.match(yaml, /skill: jira\/get_issue/, 'Skill should be unquoted');
});

test('Multiline script uses block scalar', () => {
  const dag = [
    {
      id: 'multi',
      type: 'bash',
      script: 'echo line1\necho line2\necho line3'
    }
  ];
  const yaml = dagToYaml(dag);
  assert.match(yaml, /script: \|/, 'Should use pipe block scalar for multiline');
  assert.match(yaml, /echo line1/, 'Should contain first line');
  assert.match(yaml, /echo line2/, 'Should contain second line');
});

test('depends_on renders as flow sequence', () => {
  const dag = [
    {
      id: 'a',
      type: 'bash',
      script: 'echo a'
    },
    {
      id: 'b',
      type: 'bash',
      script: 'echo b',
      depends_on: ['a']
    }
  ];
  const yaml = dagToYaml(dag);
  assert.match(yaml, /depends_on: \[a\]/, 'Should use flow sequence for depends_on');
});

test('All six node types serialize without error', () => {
  const types = ['bash', 'skill', 'command', 'prompt', 'gate', 'interrupt'];
  types.forEach(type => {
    const dag = [
      {
        id: `node_${type}`,
        type: type,
        ...(type === 'bash' ? { script: 'echo test' } : {}),
        ...(type === 'skill' ? { skill: 'test/skill' } : {}),
        ...(type === 'command' ? { command: 'test_command' } : {}),
        ...(type === 'prompt' ? { prompt: 'test prompt' } : {}),
        ...(type === 'gate' ? { condition: 'true' } : {}),
        ...(type === 'interrupt' ? { message: 'paused' } : {})
      }
    ];
    const yaml = dagToYaml(dag);
    assert.ok(yaml.length > 0, `Type ${type} should serialize`);
    assert.match(yaml, new RegExp(`type: ${type}`), `Should contain type ${type}`);
  });
});

test('Deterministic output - same input produces identical output', () => {
  const dag = [
    {
      id: 'b',
      type: 'bash',
      script: 'echo b'
    },
    {
      id: 'a',
      type: 'bash',
      script: 'echo a',
      depends_on: ['b']
    }
  ];
  const yaml1 = dagToYaml(dag);
  const yaml2 = dagToYaml(dag);
  assert.equal(yaml1, yaml2, 'Same input should produce byte-identical output');
});

test('Round-trip compatibility - output is valid YAML', () => {
  const dag = [
    {
      id: 'test',
      type: 'bash',
      script: 'echo hello',
      name: 'Test Node',
      depends_on: ['dep1']
    }
  ];
  const yaml = dagToYaml(dag);
  // Check basic YAML structure
  assert.match(yaml, /^nodes:/, 'Should start with nodes key');
  assert.match(yaml, /\n  - id:/, 'Should have proper indentation');
  assert.doesNotMatch(yaml, /\t/, 'Should not contain tabs');
  // Actual Python round-trip will be tested in pytest
});
