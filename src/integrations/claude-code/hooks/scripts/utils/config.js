/**
 * Configuration loader for Cortistrate OSS plugin
 * Reads settings from .env file and environment variables
 * 
 * Unlike the cloud plugin, this connects to a LOCAL Cortistrate server.
 * No API key needed - localhost is trusted.
 * 
 * Scoping (matches backfill + Hermes config):
 *   app_id      = shared-agent-memory
 *   project_id  = default
 *   user_id     = default (shared user track across all agents)
 *   agent_id    = pc-claude-code
 */

import { readFileSync, existsSync } from 'fs';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';

// Load .env file from plugin root
const __dirname = dirname(fileURLToPath(import.meta.url));
const envPath = resolve(__dirname, '../../../.env');

if (existsSync(envPath)) {
  const envContent = readFileSync(envPath, 'utf8');
  for (const line of envContent.split('\n')) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('#')) continue;
    const [key, ...valueParts] = trimmed.split('=');
    if (key && valueParts.length > 0) {
      const value = valueParts.join('=').replace(/^["']|["']$/g, '');
      if (!process.env[key]) {
        process.env[key] = value;
      }
    }
  }
}

const DEFAULT_BASE_URL = 'http://127.0.0.1:5473';
const DEFAULT_APP_ID = 'shared-agent-memory';
const DEFAULT_PROJECT_ID = 'default';
const DEFAULT_USER_ID = 'default';
const DEFAULT_AGENT_ID = 'pc-claude-code';

export function getConfig() {
  const baseUrl = process.env.CORTISTRATE_BASE_URL || DEFAULT_BASE_URL;
  return {
    baseUrl,
    appId: process.env.CORTISTRATE_APP_ID || DEFAULT_APP_ID,
    projectId: process.env.CORTISTRATE_PROJECT_ID || DEFAULT_PROJECT_ID,
    userId: process.env.CORTISTRATE_USER_ID || DEFAULT_USER_ID,
    agentId: process.env.CORTISTRATE_AGENT_ID || DEFAULT_AGENT_ID,
    // Always "configured" for local OSS - no API key needed
    isConfigured: true,
  };
}
