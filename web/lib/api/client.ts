export type CitationRecord = {
  index: number;
  document_id?: string | null;
  title: string;
  agency: string;
  source_url: string;
  excerpt: string;
  published_at?: string | null;
  chunk_index?: number | null;
};

export type AssistantResponse = {
  conversation_id: string;
  message_id: string;
  language: "ms" | "en";
  answer: string;
  citations: CitationRecord[];
  kind: "answer" | "clarification" | "limited-support" | "no-information";
};

export type ConversationSummary = {
  id: string;
  title: string | null;
  language: "ms" | "en" | null;
  created_at: string;
  updated_at: string;
  message_count: number;
};

export type ConversationMessage = {
  id: string;
  role: "system" | "user" | "assistant";
  content: string;
  language: "ms" | "en" | null;
  created_at: string;
  citations: CitationRecord[];
};

export type ConversationDetail = {
  id: string;
  title: string | null;
  language: "ms" | "en" | null;
  created_at: string;
  updated_at: string;
  messages: ConversationMessage[];
};

type ApiRequestOptions = {
  accessToken: string;
  apiBaseUrl?: string;
};

export type ChatRequestPayload = {
  question: string;
  conversation_id?: string | null;
  create_conversation: boolean;
};

export async function fetchConversations({
  accessToken,
  apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL
}: ApiRequestOptions): Promise<ConversationSummary[]> {
  const response = await fetch(`${apiBaseUrl}/api/conversations`, {
    headers: authHeaders(accessToken),
    cache: "no-store"
  });
  if (!response.ok) {
    throw new Error("Failed to load conversations");
  }
  return (await response.json()) as ConversationSummary[];
}

export async function fetchConversationDetail(
  conversationId: string,
  {
    accessToken,
    apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL
  }: ApiRequestOptions
): Promise<ConversationDetail> {
  const response = await fetch(`${apiBaseUrl}/api/conversations/${conversationId}`, {
    headers: authHeaders(accessToken),
    cache: "no-store"
  });
  if (!response.ok) {
    throw new Error("Failed to load conversation");
  }
  return (await response.json()) as ConversationDetail;
}

export function authHeaders(accessToken: string): HeadersInit {
  return {
    Authorization: `Bearer ${accessToken}`,
    "Content-Type": "application/json"
  };
}
