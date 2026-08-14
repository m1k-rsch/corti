/**
 * TS client for the local Corti OSS `/api/v1/memory/*` endpoints.
 * Mirrors `src/integrations/hermes/_client.py` and
 * `src/integrations/claude-code/hooks/scripts/utils/corti-api.js`.
 */

export interface CortiConfig {
  baseUrl: string;
  appId: string;
  projectId: string;
  userId: string;
  agentId: string;
}

export interface Episode {
  id: string;
  session_id: string;
  timestamp: string;
  sender_ids: string[];
  summary: string;
  subject: string;
  episode: string;
  type: string;
  score: number;
}

interface Envelope<T> {
  ok: boolean;
  status: number;
  data?: T;
  error?: unknown;
}

const DEFAULT_TIMEOUT_MS = 30_000;
const FLUSH_TIMEOUT_MS = 120_000;
const ADD_BATCH_SIZE = 20;

export class CortiClient {
  private readonly cfg: CortiConfig;

  constructor(cfg: CortiConfig) {
    this.cfg = cfg;
  }

  private scope(): Record<string, string> {
    return {
      app_id: this.cfg.appId,
      project_id: this.cfg.projectId,
      user_id: this.cfg.userId,
    };
  }

  private async post<T>(path: string, body: Record<string, unknown>, timeoutMs = DEFAULT_TIMEOUT_MS): Promise<Envelope<T>> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const res = await fetch(`${this.cfg.baseUrl}${path}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        signal: controller.signal,
      });
      const text = await res.text();
      let parsed: unknown;
      try {
        parsed = JSON.parse(text);
      } catch {
        parsed = null;
      }
      if (!res.ok) return { ok: false, status: res.status, error: parsed ?? text };
      const envelope = parsed as { data?: unknown } | null;
      return { ok: true, status: res.status, data: (envelope?.data ?? parsed) as T };
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      return { ok: false, status: 0, error: controller.signal.aborted ? `timeout after ${timeoutMs}ms` : message };
    } finally {
      clearTimeout(timer);
    }
  }

  /** POST /api/v1/memory/search */
  async search(query: string, opts: { topK?: number; method?: string } = {}): Promise<Envelope<{ episodes: Episode[] }>> {
    return this.post("/api/v1/memory/search", {
      query,
      method: opts.method ?? "hybrid",
      top_k: opts.topK ?? 8,
      ...this.scope(),
    });
  }

  /** POST /api/v1/memory/get — recent memories, newest first */
  async recent(pageSize = 10): Promise<Envelope<{ memories?: Episode[]; episodes?: Episode[]; items?: Episode[] }>> {
    return this.post("/api/v1/memory/get", {
      memory_type: "episode",
      page: 1,
      page_size: pageSize,
      sort_by: "timestamp",
      sort_order: "desc",
      ...this.scope(),
    });
  }

  /** POST /api/v1/memory/add — messages chunked into batches */
  async add(
    sessionId: string,
    messages: ReadonlyArray<{ role: "user" | "assistant"; content: string; timestamp?: number }>,
  ): Promise<Envelope<unknown>> {
    const formatted = messages.map((m) => ({
      sender_id: m.role === "assistant" ? this.cfg.agentId : this.cfg.userId,
      sender_name: m.role === "assistant" ? this.cfg.agentId : "user",
      role: m.role,
      timestamp: m.timestamp ?? Date.now(),
      content: m.content,
    }));
    let last: Envelope<unknown> = { ok: true, status: 0 };
    for (let i = 0; i < formatted.length; i += ADD_BATCH_SIZE) {
      last = await this.post("/api/v1/memory/add", {
        session_id: sessionId,
        messages: formatted.slice(i, i + ADD_BATCH_SIZE),
        ...this.scope(),
      });
      if (!last.ok) return last;
    }
    return last;
  }

  /** POST /api/v1/memory/flush — trigger extraction for one session */
  async flush(sessionId: string): Promise<Envelope<unknown>> {
    return this.post("/api/v1/memory/flush", {
      session_id: sessionId,
      ...this.scope(),
    }, FLUSH_TIMEOUT_MS);
  }
}
