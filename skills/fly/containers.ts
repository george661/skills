#!/usr/bin/env npx tsx
// containers - List active containers across all Concourse workers.
import { flyExecJson, getFlyTarget } from './fly-client.js';

interface Container {
  id: string;
  worker_name: string;
  type: string;
  pipeline_name: string;
  job_name: string;
  build_name: string;
  build_id: number;
  step_name: string;
  attempt: string;
}

async function execute() {
  const containers = flyExecJson<Container[]>(['containers']);
  return {
    target: getFlyTarget(),
    count: containers.length,
    containers,
  };
}

execute().then(r => console.log(JSON.stringify(r, null, 2))).catch(e => { console.error(e.message); process.exit(1); });
