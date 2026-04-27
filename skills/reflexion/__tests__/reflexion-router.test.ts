import { describe, it, expect, afterEach } from 'vitest';
import { resolveReflexionProvider, translateParams } from '../reflexion-router.js';

describe('resolveReflexionProvider', () => {
  const origEnv = process.env.REFLEXION_PROVIDER;

  afterEach(() => {
    if (origEnv === undefined) {
      delete process.env.REFLEXION_PROVIDER;
    } else {
      process.env.REFLEXION_PROVIDER = origEnv;
    }
  });

  it('returns agentdb when REFLEXION_PROVIDER is unset', () => {
    delete process.env.REFLEXION_PROVIDER;
    expect(resolveReflexionProvider()).toBe('agentdb');
  });

  it('returns provider value when REFLEXION_PROVIDER is set', () => {
    process.env.REFLEXION_PROVIDER = 'agentdb';
    expect(resolveReflexionProvider()).toBe('agentdb');
  });

  it('returns explicit override when both env and explicit are set', () => {
    process.env.REFLEXION_PROVIDER = 'agentdb';
    expect(resolveReflexionProvider('agentdb')).toBe('agentdb');
  });

  it('throws when invalid provider pinecone is provided', () => {
    expect(() => resolveReflexionProvider('pinecone')).toThrow(/Invalid reflexion provider.*pinecone/);
  });
});

describe('translateParams', () => {
  it('agentdb provider passes through params unchanged for reflexion_retrieve', () => {
    const params = { session_id: 'test', task: 'my-task', k: 5 };
    expect(translateParams('agentdb', 'reflexion_retrieve', params)).toEqual({
      session_id: 'test',
      task: 'my-task',
      k: 5,
    });
  });

  it('agentdb provider passes through params unchanged for reflexion_store', () => {
    const params = {
      session_id: 'test',
      task: 'my-task',
      input: { foo: 'bar' },
      output: 'result',
      reward: 1,
      success: true,
    };
    expect(translateParams('agentdb', 'reflexion_store', params)).toEqual({
      session_id: 'test',
      task: 'my-task',
      input: { foo: 'bar' },
      output: 'result',
      reward: 1,
      success: true,
    });
  });
});
