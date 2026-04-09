#!/usr/bin/env npx tsx
// validate_pipeline - Validate a Concourse pipeline YAML configuration file.
import { flyExec, getFlyTarget } from './fly-client.js';

interface Input {
  pipeline_file: string;
}

async function execute(input: Input) {
  if (!input.pipeline_file) {
    throw new Error('pipeline_file is required');
  }

  try {
    const output = flyExec(['validate-pipeline', '-c', input.pipeline_file]);
    return {
      valid: true,
      target: getFlyTarget(),
      pipeline_file: input.pipeline_file,
      message: output || 'Pipeline configuration is valid.',
    };
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    const errors = message
      .split('\n')
      .filter((line: string) => line.trim().length > 0);
    return {
      valid: false,
      target: getFlyTarget(),
      pipeline_file: input.pipeline_file,
      errors,
    };
  }
}

const input = JSON.parse(process.argv[2] || '{}') as Input;
execute(input).then(r => console.log(JSON.stringify(r, null, 2))).catch(e => { console.error(e.message); process.exit(1); });
