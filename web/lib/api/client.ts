export type CitationRecord = {
  index: number;
  document_id?: string | null;
  title: string;
  agency: string;
  source_url: string | null;
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
  pinned?: boolean;
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

export type FileAttachment = {
  filename: string;
  content_type: string;
  data: string; // base64
};

export type ChatRequestPayload = {
  question: string;
  conversation_id?: string | null;
  create_conversation: boolean;
  skill?: string | null;
  attachments?: FileAttachment[];
};

export type SkillInfo = {
  id: string;
  name: string;
  name_ms: string;
  description: string;
  description_ms: string;
  icon: string;
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

export async function fetchSkills({
  apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL
}: { apiBaseUrl?: string } = {}): Promise<SkillInfo[]> {
  const response = await fetch(`${apiBaseUrl}/api/skills`, {
    cache: "no-store"
  });
  if (!response.ok) {
    return [];
  }
  return (await response.json()) as SkillInfo[];
}

export async function submitFeedback({
  accessToken,
  messageId,
  rating,
  apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL
}: {
  accessToken: string;
  messageId: string;
  rating: 1 | -1;
  apiBaseUrl?: string;
}): Promise<void> {
  await fetch(`${apiBaseUrl}/api/feedback`, {
    method: "POST",
    headers: authHeaders(accessToken),
    body: JSON.stringify({ message_id: messageId, rating }),
  });
}

export async function fetchConversationFeedback({
  accessToken,
  conversationId,
  apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL
}: {
  accessToken: string;
  conversationId: string;
  apiBaseUrl?: string;
}): Promise<Record<string, number>> {
  const response = await fetch(
    `${apiBaseUrl}/api/feedback/conversation/${conversationId}`,
    { headers: authHeaders(accessToken), cache: "no-store" }
  );
  if (!response.ok) return {};
  const data = await response.json();
  return data.ratings ?? {};
}

export async function updateConversation(
  conversationId: string,
  updates: { title?: string; pinned?: boolean },
  {
    accessToken,
    apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL
  }: ApiRequestOptions
): Promise<void> {
  const response = await fetch(`${apiBaseUrl}/api/conversations/${conversationId}`, {
    method: "PATCH",
    headers: authHeaders(accessToken),
    body: JSON.stringify(updates)
  });
  if (!response.ok) {
    throw new Error("Failed to update conversation");
  }
}

export async function deleteConversation(
  conversationId: string,
  {
    accessToken,
    apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL
  }: ApiRequestOptions
): Promise<void> {
  const response = await fetch(`${apiBaseUrl}/api/conversations/${conversationId}`, {
    method: "DELETE",
    headers: authHeaders(accessToken)
  });
  if (!response.ok) {
    throw new Error("Failed to delete conversation");
  }
}

export function authHeaders(accessToken: string): HeadersInit {
  return {
    Authorization: `Bearer ${accessToken}`,
    "Content-Type": "application/json"
  };
}
