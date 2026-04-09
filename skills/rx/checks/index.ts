import { Check } from '../types.js';
import { PrereqsCheck } from './prereqs.js';
import { BrewCheck } from './brew.js';
import { ReposCheck } from './repos.js';
import { ClaudeConfigCheck } from './claude-config.js';
import { SkillsCheck } from './skills.js';
import { CommandsCheck } from './commands.js';
import { HooksCheck } from './hooks.js';
import { SupergatewayCheck } from './supergateway.js';
import { PluginsCheck } from './plugins.js';
import { CredentialsCheck } from './credentials.js';
import { WorktreesCheck } from './worktrees.js';
import { TeamsCheck } from './teams.js';
import { PlaywrightCheck } from './playwright.js';

/**
 * All checks in dependency order.
 * Earlier checks must pass before later checks make sense
 * (e.g., node must exist before we can check skills).
 */
export const ALL_CHECKS: Check[] = [
  new PrereqsCheck(),
  new BrewCheck(),
  new ReposCheck(),
  new ClaudeConfigCheck(),
  new SkillsCheck(),
  new CommandsCheck(),
  new HooksCheck(),
  new SupergatewayCheck(),
  new PluginsCheck(),
  new CredentialsCheck(),
  new TeamsCheck(),  // Check for stuck in-process teams
  new WorktreesCheck(),
  new PlaywrightCheck(),
];
