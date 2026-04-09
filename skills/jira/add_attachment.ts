#!/usr/bin/env npx tsx
// add_attachment - Upload a file attachment to a Jira issue.
import { jiraUpload } from './jira-client.js';

interface Input {
  issue_key: string;
  file_path: string;
  filename?: string;
}

async function execute(input: Input) {
  if (!input.issue_key || !input.file_path) {
    throw new Error('issue_key and file_path are required');
  }

  const resolvedFilename = input.filename || input.file_path.split('/').pop() || 'attachment';
  return jiraUpload(input.issue_key, input.file_path, resolvedFilename);
}

const input = JSON.parse(process.argv[2] || '{}') as Input;
execute(input)
  .then((r) => console.log(JSON.stringify(r, null, 2)))
  .catch((e) => { console.error(e.message); process.exit(1); });
