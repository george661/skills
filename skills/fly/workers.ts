#!/usr/bin/env npx tsx
// workers - List registered Concourse workers.
import { flyExecJson, getFlyTarget } from './fly-client.js';

interface Worker {
  name: string;
  state: string;
  containers: number;
  platform: string;
  tags: string[];
  team: string;
  version: string;
}

async function execute() {
  const workers = flyExecJson<Worker[]>(['workers']);
  return {
    target: getFlyTarget(),
    count: workers.length,
    workers,
  };
}

execute().then(r => console.log(JSON.stringify(r, null, 2))).catch(e => { console.error(e.message); process.exit(1); });
