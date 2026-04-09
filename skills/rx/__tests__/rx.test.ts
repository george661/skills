import { describe, it, expect } from 'vitest';
import { parseArgs } from '../rx.js';

describe('parseArgs', () => {
  it('parses --dry-run flag', () => {
    const args = parseArgs(['--dry-run']);
    expect(args.dryRun).toBe(true);
  });

  it('parses --json flag', () => {
    const args = parseArgs(['--json']);
    expect(args.json).toBe(true);
  });

  it('parses --category with value', () => {
    const args = parseArgs(['--category', 'brew']);
    expect(args.category).toBe('brew');
  });

  it('defaults to all false', () => {
    const args = parseArgs([]);
    expect(args.dryRun).toBe(false);
    expect(args.json).toBe(false);
    expect(args.verbose).toBe(false);
    expect(args.category).toBeUndefined();
  });

  it('parses combined flags', () => {
    const args = parseArgs(['--dry-run', '--json', '--verbose', '--category', 'prereqs']);
    expect(args.dryRun).toBe(true);
    expect(args.json).toBe(true);
    expect(args.verbose).toBe(true);
    expect(args.category).toBe('prereqs');
  });
});
