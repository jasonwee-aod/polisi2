"use client";

import React from "react";

import { useRouter } from "next/navigation";
import { useEffect, useState, useTransition } from "react";

import {
  AssistantResponse,
  CitationRecord,
  ConversationDetail,
  ConversationMessage,
  ConversationSummary,
  fetchConversationDetail,
  fetchConversations
} from "@/lib/api/client";
import { readChatStream, StreamEvent } from "@/lib/chat/stream";

import { CitationPanel } from "./citation-panel";
import { ConversationSidebar } from "./conversation-sidebar";
import { MessageComposer } from "./message-composer";
import { MessageList } from "./message-list";

const DEFAULT_API_CLIENT = { fetchConversations, fetchConversationDetail };

type ChatShellProps = {
  accessToken: string;
  initialConversationId?: string | null;
  apiBaseUrl?: string;
  apiClient?: {
    fetchConversations(args: { accessToken: string; apiBaseUrl?: string }): Promise<ConversationSummary[]>;
    fetchConversationDetail(
      conversationId: string,
      args: { accessToken: string; apiBaseUrl?: string }
    ): Promise<ConversationDetail>;
  };
  streamChat?: (args: {
    accessToken: string;
    payload: {
      question: string;
      conversation_id?: string | null;
      create_conversation: boolean;
    };
    apiBaseUrl?: string;
    onEvent(event: StreamEvent): void;
  }) => Promise<void>;
  navigate?: (path: string) => void;
};

export function ChatShell({
  accessToken,
  initialConversationId = null,
  apiBaseUrl,
  apiClient = DEFAULT_API_CLIENT,
  streamChat = readChatStream,
  navigate
}: ChatShellProps) {
  const router = useRouter();
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [activeConversationId, setActiveConversationId] = useState<string | null>(
    initialConversationId
  );
  const [messages, setMessages] = useState<ConversationMessage[]>([]);
  const [selectedCitation, setSelectedCitation] = useState<CitationRecord | null>(null);
  const [isLoadingConversation, startConversationTransition] = useTransition();
  const [isStreaming, setIsStreaming] = useState(false);

  useEffect(() => {
    void apiClient
      .fetchConversations({ accessToken, apiBaseUrl })
      .then(setConversations)
      .catch(() => setConversations([]));
  }, [accessToken, apiBaseUrl, apiClient]);

  useEffect(() => {
    if (!activeConversationId) {
      setMessages([]);
      return;
    }
    startConversationTransition(() => {
      void apiClient
        .fetchConversationDetail(activeConversationId, { accessToken, apiBaseUrl })
        .then((detail) => setMessages(detail.messages))
        .catch(() => setMessages([]));
    });
  }, [accessToken, activeConversationId, apiBaseUrl, apiClient]);

  async function handleSubmit(question: string) {
    setIsStreaming(true);
    setSelectedCitation(null);
    setMessages((current) => [
      ...current,
      {
        id: `temp-user-${Date.now()}`,
        role: "user",
        content: question,
        language: null,
        created_at: new Date().toISOString(),
        citations: []
      }
    ]);

    const assistantDraftId = `temp-assistant-${Date.now()}`;
    setMessages((current) => [
      ...current,
      {
        id: assistantDraftId,
        role: "assistant",
        content: "",
        language: null,
        created_at: new Date().toISOString(),
        citations: []
      }
    ]);

    await streamChat({
      accessToken,
      apiBaseUrl,
      payload: {
        question,
        conversation_id: activeConversationId,
        create_conversation: !activeConversationId
      },
      onEvent: (event) => {
        if (event.event === "conversation" && event.conversation_id) {
          setActiveConversationId(event.conversation_id);
          const path = `/chat/${event.conversation_id}`;
          if (navigate) {
            navigate(path);
          } else {
            router.replace(path);
          }
        }
        if (event.event === "message-delta" && event.delta) {
          setMessages((current) =>
            current.map((message) =>
              message.id === assistantDraftId
                ? { ...message, content: `${message.content}${event.delta}` }
                : message
            )
          );
        }
        if (event.event === "message-complete" && event.response) {
          syncFinalAssistantMessage(assistantDraftId, event.response);
        }
      }
    }).finally(async () => {
      setIsStreaming(false);
      try {
        const nextConversations = await apiClient.fetchConversations({ accessToken, apiBaseUrl });
        setConversations(nextConversations);
      } catch {
        // Keep the optimistic list if reload fails.
      }
    });
  }

  function syncFinalAssistantMessage(tempId: string, response: AssistantResponse) {
    setMessages((current) =>
      current.map((message) =>
        message.id === tempId
          ? {
              id: response.message_id,
              role: "assistant",
              content: response.answer,
              language: response.language,
              created_at: new Date().toISOString(),
              citations: response.citations
            }
          : message
      )
    );
  }

  function handleSelectConversation(conversationId: string) {
    setSelectedCitation(null);
    setActiveConversationId(conversationId);
    const path = `/chat/${conversationId}`;
    if (navigate) {
      navigate(path);
      return;
    }
    router.push(path);
  }

  function handleNewConversation() {
    setSelectedCitation(null);
    setActiveConversationId(null);
    setMessages([]);
    if (navigate) {
      navigate("/chat");
      return;
    }
    router.push("/chat");
  }

  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "18rem minmax(0, 1fr) 20rem",
        gap: "1rem",
        alignItems: "start"
      }}
    >
      <ConversationSidebar
        conversations={conversations}
        activeConversationId={activeConversationId}
        onSelect={handleSelectConversation}
        onNewConversation={handleNewConversation}
      />

      <section style={{ display: "grid", gap: "1rem" }}>
        <MessageList messages={messages} onCitationSelect={setSelectedCitation} />
        <MessageComposer disabled={isStreaming || isLoadingConversation} onSubmit={handleSubmit} />
      </section>

      <CitationPanel citation={selectedCitation} onClose={() => setSelectedCitation(null)} />
    </div>
  );
}
