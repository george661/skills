import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { mkdtempSync, rmSync, writeFileSync } from 'fs';
import { join } from 'path';
import { tmpdir } from 'os';

describe('rx-client', () => {
  let tmpDir: string;

  beforeEach(() => {
    tmpDir = mkdtempSync(join(tmpdir(), 'rx-test-'));
  });

  afterEach(() => {
    rmSync(tmpDir, { recursive: true });
  });

  describe('loadJsonConfig', () => {
    it('loads valid JSON file', async () => {
      const { loadJsonConfig } = await import('../rx-client.js');
      const filePath = join(tmpDir, 'test.json');
      writeFileSync(filePath, '{"key": "value"}');
      const result = loadJsonConfig(filePath);
      expect(result).toEqual({ key: 'value' });
    });

    it('returns null for missing file', async () => {
      const { loadJsonConfig } = await import('../rx-client.js');
      const result = loadJsonConfig(join(tmpDir, 'nonexistent.json'));
      expect(result).toBeNull();
    });

    it('returns null for invalid JSON', async () => {
      const { loadJsonConfig } = await import('../rx-client.js');
      const filePath = join(tmpDir, 'bad.json');
      writeFileSync(filePath, 'not json');
      const result = loadJsonConfig(filePath);
      expect(result).toBeNull();
    });
  });

  describe('exec', () => {
    it('returns ok:true for successful commands', async () => {
      const { exec } = await import('../rx-client.js');
      const result = exec('echo hello');
      expect(result.ok).toBe(true);
      expect(result.stdout).toBe('hello');
    });

    it('returns ok:false for failed commands', async () => {
      const { exec } = await import('../rx-client.js');
      const result = exec('false');
      expect(result.ok).toBe(false);
    });
  });

  describe('generateRunId', () => {
    it('starts with rx-', async () => {
      const { generateRunId } = await import('../rx-client.js');
      expect(generateRunId()).toMatch(/^rx-\d+$/);
    });
  });
});
