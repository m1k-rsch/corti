#!/usr/bin/env node

/**
 * Cortistrate OSS - Stop Hook
 * 
 * Reads the transcript JSONL, extracts the last turn's user+assistant text,
 * sends them to local Cortistrate via /add, then triggers /flush for extraction.
 * 
 * This is the glue layer: the transcript parsing logic is inherited from
 * the official cloud plugin, but the API calls use the OSS local server.
 */

process.on('uncaughtException', () => process.exit(0));
process.on('unhandledRejection', () => process.exit(0));

import { readFileSync, existsSync } from 'fs';
import { getConfig } from './utils/config.js';
import { addMemories, flushSession } from './utils/cortistrate-api.js';
import { debug, setDebugPrefix } from './utils/debug.js';

setDebugPrefix('store');

const CORTISTRATE_SESSION_PREFIX = 'claude-code-live';

try {
  let input = '';
  for await (const chunk of process.stdin) {
    input += chunk;
  }

  const hookInput = JSON.parse(input);
  debug('hookInput keys:', Object.keys(hookInput));
  const transcriptPath = hookInput.transcript_path;

  if (!transcriptPath || !existsSync(transcriptPath)) {
    process.exit(0);
  }

  const config = getConfig();

  // ── read transcript with retry ──────────────────────────────────────────
  // Wait for turn_duration marker which indicates the turn is complete

  async function readTranscriptWithRetry(path, maxRetries = 5, delayMs = 100) {
    for (let attempt = 1; attempt <= maxRetries; attempt++) {
      const content = readFileSync(path, 'utf8');
      const lines = content.trim().split('\n');

      let isComplete = false;
      try {
        const lastLine = JSON.parse(lines[lines.length - 1]);
        isComplete = lastLine.type === 'system' && lastLine.subtype === 'turn_duration';
      } catch {}

      debug(`read attempt ${attempt}: ${lines.length} lines, complete=${isComplete}`);

      if (isComplete) return lines;
      if (attempt < maxRetries) {
        await new Promise(resolve => setTimeout(resolve, delayMs));
      }
    }
    const content = readFileSync(path, 'utf8');
    return content.trim().split('\n');
  }

  const lines = await readTranscriptWithRetry(transcriptPath);

  // ── extract last turn ───────────────────────────────────────────────────
  // A Turn = User message -> Claude responds (may include tool calls)
  // Turn boundary: {"type":"system","subtype":"turn_duration"}

  function extractLastTurn(lines) {
    const turnEndIndex = lines.length;
    let turnStartIndex = 0;

    // Find the last turn_duration marker - content AFTER it is the current turn.
    // In real Claude Code, turn_duration is written AFTER the Stop hook completes,
    // so the marker may not be present yet. In that case, turnStartIndex stays 0
    // and we scan the whole file (which works for single-turn transcripts).
    // If the marker IS present (e.g. retry, or test), we skip past it.
    // Edge case: if the marker is the very last line, turnStartIndex == turnEndIndex
    // and the loop body doesn't execute. In that case, fall back to scanning everything.
    for (let i = lines.length - 1; i >= 0; i--) {
      try {
        const e = JSON.parse(lines[i]);
        if (e.type === 'system' && e.subtype === 'turn_duration') {
          turnStartIndex = i + 1;
          break;
        }
      } catch {}
    }

    // If turn_duration is the last line, there's nothing after it to extract.
    // This happens in test transcripts. Fall back to scanning the whole file
    // minus system lines.
    if (turnStartIndex >= turnEndIndex) {
      turnStartIndex = 0;
    }

    const userTexts = [];
    const assistantTexts = [];

    for (let i = turnStartIndex; i < turnEndIndex; i++) {
      try {
        const e = JSON.parse(lines[i]);
        const content = e.message?.content;

        if (e.type === 'user') {
          if (typeof content === 'string') {
            if (content.trim()) userTexts.push(content);
          } else if (Array.isArray(content)) {
            for (const block of content) {
              if (block.type === 'text' && block.text?.trim()) {
                userTexts.push(block.text);
              }
            }
          }
        }

        if (e.type === 'assistant') {
          if (Array.isArray(content)) {
            for (const block of content) {
              if (block.type === 'text' && block.text?.trim()) {
                assistantTexts.push(block.text);
              }
            }
          } else if (typeof content === 'string' && content.trim()) {
            assistantTexts.push(content);
          }
        }
      } catch {}
    }

    return {
      user: userTexts.join('\n\n'),
      assistant: assistantTexts.join('\n\n'),
    };
  }

  const lastTurn = extractLastTurn(lines);
  const lastUser = lastTurn.user;
  const lastAssistant = lastTurn.assistant;

  debug('extracted:', {
    userLen: lastUser?.length || 0,
    assistantLen: lastAssistant?.length || 0,
  });

  // ── send to Cortistrate ──────────────────────────────────────────────────────
  // Build message pair (same as backfill script)

  const messages = [];
  if (lastUser && lastUser.trim()) {
    messages.push({ content: lastUser, role: 'user' });
  }
  if (lastAssistant && lastAssistant.trim()) {
    messages.push({ content: lastAssistant, role: 'assistant' });
  }

  if (messages.length === 0) {
    debug('no meaningful content to store');
    process.exit(0);
  }

  // Use Claude Code session_id if available, else derive from transcript path
  const sessionId = hookInput.session_id
    ? `${CORTISTRATE_SESSION_PREFIX}-${hookInput.session_id}`
    : `${CORTISTRATE_SESSION_PREFIX}-${transcriptPath.split('/').pop().replace('.jsonl', '')}`;

  const addResult = await addMemories(sessionId, messages);

  if (!addResult.ok) {
    debug('add failed:', addResult.error);
    process.exit(0);  // Silent - don't block Claude Code
  }

  debug('add success:', addResult.data);

  // Flush to trigger boundary detection + episode extraction
  const flushResult = await flushSession(sessionId);

  if (!flushResult.ok) {
    debug('flush failed:', flushResult.error);
    // Data is still buffered; will be extracted on next flush
  } else {
    const status = flushResult.data?.status || '?';
    debug('flush success:', status);
  }

  // Silent success - no systemMessage to keep Claude Code output clean
  process.exit(0);

} catch (e) {
  debug('error:', e.message);
  process.exit(0);
}
