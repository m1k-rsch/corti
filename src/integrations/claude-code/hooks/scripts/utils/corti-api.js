/**
 * Cortistrate OSS API client
 * 
 * Bridges the legacy cloud plugin's API surface to the local Cortistrate OSS server.
 * 
 * Cloud API -> OSS API mapping:
 *   POST /api/v1/memories/search  -> POST /api/v1/memory/search
 *   POST /api/v1/memories/group   -> POST /api/v1/memory/add
 *   POST /api/v1/memories/get     -> POST /api/v1/memory/get
 *   (implicit async)              -> POST /api/v1/memory/flush  (explicit)
 * 
 * Scoping changes:
 *   group_id, user_id, Bearer token  ->  app_id, project_id, user_id, agent_id (no auth)
 * 
 * sender_id mapping (matches backfill_claude_code.py):
 *   user messages  -> sender_id = "default"
 *   assistant msgs -> sender_id = "pc-claude-code"
 */

import { getConfig } from './config.js';
import { debug, setDebugPrefix } from './debug.js';

setDebugPrefix('CortistrateAPI');
const TIMEOUT_MS = 30000;

// ── helpers ──────────────────────────────────────────────────────────────────

async function postJSON(url, body, timeoutMs = TIMEOUT_MS) {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: controller.signal,
    });
    clearTimeout(timeoutId);
    const text = await response.text();
    let data;
    try { data = JSON.parse(text); } catch { data = null; }
    if (!response.ok) {
      return { ok: false, status: response.status, error: data || text };
    }
    return { ok: true, status: response.status, data: data?.data ?? data };
  } catch (error) {
    clearTimeout(timeoutId);
    if (error.name === 'AbortError') {
      return { ok: false, status: 0, error: `timeout after ${timeoutMs}ms` };
    }
    return { ok: false, status: 0, error: error.message };
  }
}

function buildScope() {
  const config = getConfig();
  return {
    app_id: config.appId,
    project_id: config.projectId,
    user_id: config.userId,
  };
}

// ── search ───────────────────────────────────────────────────────────────────

/**
 * Search memories from local Cortistrate OSS.
 * @param {string} query - Search query text
 * @param {Object} options
 * @param {number} options.topK - Max results (default: 10)
 * @param {string} options.retrieveMethod - keyword|vector|hybrid|agentic (default: 'hybrid')
 * @returns {Promise<Object>} Envelope { ok, data?, error? }
 */
export async function searchMemories(query, options = {}) {
  const config = getConfig();
  const { topK = 10, retrieveMethod = 'hybrid' } = options;
  const body = {
    query,
    method: retrieveMethod,
    top_k: topK,
    ...buildScope(),
  };
  debug('searchMemories', { url: `${config.baseUrl}/api/v1/memory/search`, body });
  return postJSON(`${config.baseUrl}/api/v1/memory/search`, body);
}

/**
 * Transform OSS search response to plugin memory format.
 * OSS returns: { data: { episodes: [{ id, user_id, session_id, timestamp, sender_ids, summary, subject, episode, type, score }] } }
 */
export function transformSearchResults(response) {
  const episodes = response?.data?.episodes;
  if (!Array.isArray(episodes)) return [];
  return episodes
    .map(ep => ({
      text: ep.episode || ep.summary || '',
      subject: ep.subject || '',
      timestamp: ep.timestamp || new Date().toISOString(),
      score: ep.score || 0,
      senderIds: ep.sender_ids || [],
      sessionId: ep.session_id || '',
    }))
    .filter(m => m.text)
    .sort((a, b) => b.score - a.score);
}

// ── add (store) ──────────────────────────────────────────────────────────────

/**
 * Add messages to Cortistrate OSS.
 * Sends user+assistant as a pair, matching the backfill script's approach.
 * 
 * @param {string} sessionId - Cortistrate session ID
 * @param {Array<{content: string, role: string, timestamp?: number}>} messages
 * @returns {Promise<Object>} Envelope { ok, data?, error? }
 */
export async function addMemories(sessionId, messages) {
  const config = getConfig();
  const formatted = messages.map(m => ({
    sender_id: m.role === 'assistant' ? config.agentId : config.userId,
    sender_name: m.role === 'assistant' ? 'pc-claude-code' : 'user',
    role: m.role,
    timestamp: m.timestamp || Date.now(),
    content: m.content,
  }));
  const body = {
    session_id: sessionId,
    messages: formatted,
    ...buildScope(),
  };
  debug('addMemories', { url: `${config.baseUrl}/api/v1/memory/add`, msgCount: formatted.length });
  return postJSON(`${config.baseUrl}/api/v1/memory/add`, body);
}

/**
 * Flush a session to trigger extraction (episode/atomic_fact/foresight).
 * @param {string} sessionId
 * @returns {Promise<Object>} Envelope { ok, data?, error? }
 */
export async function flushSession(sessionId) {
  const config = getConfig();
  const body = {
    session_id: sessionId,
    ...buildScope(),
  };
  debug('flushSession', { url: `${config.baseUrl}/api/v1/memory/flush`, body });
  return postJSON(`${config.baseUrl}/api/v1/memory/flush`, body, 120000);
}

// ── get (recent memories) ────────────────────────────────────────────────────

/**
 * Get recent memories from Cortistrate OSS (newest first).
 * @param {Object} options
 * @param {number} options.pageSize - Results per page (default: 100)
 * @returns {Promise<Object>} Envelope { ok, data?, error? }
 */
export async function getMemories(options = {}) {
  const config = getConfig();
  const { pageSize = 100 } = options;
  const body = {
    memory_type: 'episode',
    page: 1,
    page_size: pageSize,
    ...buildScope(),
  };
  debug('getMemories', { url: `${config.baseUrl}/api/v1/memory/get`, body });
  return postJSON(`${config.baseUrl}/api/v1/memory/get`, body);
}

/**
 * Transform OSS get response to simple format.
 */
export function transformGetMemoriesResults(response) {
  const episodes = response?.data?.episodes;
  if (!Array.isArray(episodes)) return [];
  return episodes
    .map(ep => ({
      text: ep.episode || ep.summary || '',
      subject: ep.subject || '',
      timestamp: ep.timestamp || new Date().toISOString(),
      sessionId: ep.session_id || '',
    }))
    .filter(m => m.text)
    .sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp));
}
