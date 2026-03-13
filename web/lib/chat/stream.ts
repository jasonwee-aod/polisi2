import { AssistantResponse, ChatRequestPayload, authHeaders } from "@/lib/api/client";

export type StreamEvent = {
  event: "conversation" | "message-start" | "message-delta" | "message-complete" | "done";
  conversation_id?: string | null;
  message_id?: string | null;
  delta?: string | null;
  response?: AssistantResponse | null;
};

type ReadChatStreamOptions = {
  accessToken: string;
  payload: ChatRequestPayload;
  apiBaseUrl?: string;
  onEvent(event: StreamEvent): void;
};

export async function readChatStream({
  accessToken,
  payload,
  apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL,
  onEvent
}: ReadChatStreamOptions): Promise<void> {
  const response = await fetch(`${apiBaseUrl}/api/chat`, {
    method: "POST",
    headers: authHeaders(accessToken),
    body: JSON.stringify(payload)
  });

  if (!response.ok || !response.body) {
    const body = await response.text().catch(() => "");
    throw new Error(`Chat request failed (${response.status}): ${body}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) {
      break;
    }
    buffer += decoder.decode(value, { stream: true });
    const segments = buffer.split("\n");
    buffer = segments.pop() ?? "";
    for (const segment of segments) {
      if (!segment.trim()) {
        continue;
      }
      onEvent(JSON.parse(segment) as StreamEvent);
    }
  }

  if (buffer.trim()) {
    onEvent(JSON.parse(buffer) as StreamEvent);
  }
}
