/**
 * API client for the assistant backend.
 *
 * Two endpoints are exposed by the FastAPI server:
 *   - GET  /api/health
 *   - GET  /api/assistants
 *   - POST /api/chat (SSE stream)
 *
 * The chat endpoint returns Server-Sent Events. We can't use the native
 * `EventSource` API because it only supports GET — we use `fetch` with a
 * streaming body reader and parse the SSE text protocol ourselves.
 */

export type AssistantInfo = {
  name: string;
  title: string;
  description: string;
};

export type AssistantsResponse = {
  assistants: AssistantInfo[];
  default: string;
  current_name: string;
};

export type HealthResponse = {
  status: "ok";
  openai: boolean;
  ado: boolean;
  app_name: string;
};

/** Events coming back from the /api/chat stream. */
export type ChatEvent =
  | { type: "session"; conversation_id: string }
  | { type: "token"; text: string }
  | { type: "tool_start"; id: string; name: string; args: string | object }
  | { type: "tool_end"; id: string; name: string; output: string }
  | { type: "done" }
  | { type: "error"; message: string };

const API_BASE = "";

async function fetchJson<T>(path: string): Promise<T> {
  const resp = await fetch(API_BASE + path, { headers: { Accept: "application/json" } });
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText} fetching ${path}`);
  return (await resp.json()) as T;
}

export function getHealth(): Promise<HealthResponse> {
  return fetchJson<HealthResponse>("/api/health");
}

export function getAssistants(): Promise<AssistantsResponse> {
  return fetchJson<AssistantsResponse>("/api/assistants");
}

/**
 * Stream a chat response from the backend. Calls the supplied callbacks
 * as each SSE event arrives. Returns a promise that resolves when the
 * stream completes or errors.
 */
export async function streamChat(
  body: { assistant?: string; conversation_id?: string | null; message: string },
  onEvent: (event: ChatEvent) => void,
): Promise<void> {
  const resp = await fetch(API_BASE + "/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify(body),
  });

  if (!resp.ok || !resp.body) {
    const text = await resp.text().catch(() => "<no body>");
    throw new Error(`chat request failed: ${resp.status} ${resp.statusText} — ${text}`);
  }

  const reader = resp.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  // SSE records are separated by a blank line. We accumulate buffer
  // until we have a full record, then dispatch it.
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let idx: number;
    while ((idx = buffer.indexOf("\n\n")) >= 0) {
      const rawRecord = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      const event = parseSseRecord(rawRecord);
      if (event) onEvent(event);
    }
  }
  // leftover — flush any final record
  if (buffer.trim().length > 0) {
    const event = parseSseRecord(buffer);
    if (event) onEvent(event);
  }
}

function parseSseRecord(raw: string): ChatEvent | null {
  const lines = raw.split("\n");
  let eventName = "";
  const dataLines: string[] = [];
  for (const line of lines) {
    if (line.startsWith("event:")) {
      eventName = line.slice(6).trim();
    } else if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).trimStart());
    }
  }
  if (!eventName) return null;
  const dataStr = dataLines.join("\n");
  let data: any = dataStr;
  if (dataStr.length > 0) {
    try {
      data = JSON.parse(dataStr);
    } catch {
      // not JSON; keep raw string
    }
  } else {
    data = {};
  }
  return { type: eventName, ...(data as object) } as ChatEvent;
}
