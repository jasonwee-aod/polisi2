import { AssistantResponse, ChatRequestPayload, authHeaders } from "@/lib/api/client";

export type StreamEvent = {
  event: "conversation" | "message-start" | "message-delta" | "message-complete" | "done";
  conversation_id?: string | null;
  message_id?: string | null;
  delta?: string | null;
  response?: AssistantResponse | null;
};

export class RateLimitError extends Error {
  detail: { error: string; message: string; limit: number; used: number };
  constructor(detail: { error: string; message: string; limit: number; used: number }) {
    super(detail.message);
    this.name = "RateLimitError";
    this.detail = detail;
  }
}

type ReadChatStreamOptions = {
  accessToken: string;
  payload: ChatRequestPayload;
  apiBaseUrl?: string;
  signal?: AbortSignal;
  onEvent(event: StreamEvent): void;
};

export async function readChatStream({
  accessToken,
  payload,
  apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL,
  signal,
  onEvent
}: ReadChatStreamOptions): Promise<void> {
  const response = await fetch(`${apiBaseUrl}/api/chat`, {
    method: "POST",
    headers: authHeaders(accessToken),
    body: JSON.stringify(payload),
    signal,
  });

  if (response.status === 429) {
    const body = await response.json().catch(() => ({
      detail: { error: "rate_limit", message: "Rate limit exceeded. Please try again tomorrow.", limit: 0, used: 0 }
    }));
    throw new RateLimitError(body.detail);
  }

  if (!response.ok || !response.body) {
    const body = await response.text().catch(() => "");
    throw new Error(`Chat request failed (${response.status}): ${body}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const segments = buffer.split("\n");
      buffer = segments.pop() ?? "";
      for (const segment of segments) {
        if (!segment.trim()) continue;
        onEvent(JSON.parse(segment) as StreamEvent);
      }
    }
    if (buffer.trim()) {
      onEvent(JSON.parse(buffer) as StreamEvent);
    }
  } finally {
    reader.releaseLock();
  }
}
