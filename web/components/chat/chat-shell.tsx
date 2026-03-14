"use client";

import React from "react";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, useTransition } from "react";

import {
  AssistantResponse,
  CitationRecord,
  ConversationDetail,
  ConversationMessage,
  ConversationSummary,
  FileAttachment,
  SkillInfo,
  deleteConversation,
  fetchConversationDetail,
  fetchConversationFeedback,
  fetchConversations,
  fetchSkills,
  submitFeedback,
  updateConversation,
} from "@/lib/api/client";
import { RateLimitError, readChatStream, StreamEvent } from "@/lib/chat/stream";

import { CitationPanel } from "./citation-panel";
import { ConversationSidebar } from "./conversation-sidebar";
import { MessageComposer } from "./message-composer";
import { MessageList } from "./message-list";

const DEFAULT_API_CLIENT = { fetchConversations, fetchConversationDetail };

const SUGGESTION_CHIPS = [
  "Draft a speech",
  "Create a research report",
  "Brainstorm a policy idea"
];

type ChatShellProps = {
  accessToken: string;
  initialConversationId?: string | null;
  userEmail?: string | null;
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
      skill?: string | null;
      attachments?: FileAttachment[];
    };
    apiBaseUrl?: string;
    signal?: AbortSignal;
    onEvent(event: StreamEvent): void;
  }) => Promise<void>;
  navigate?: (path: string) => void;
};

export function ChatShell({
  accessToken,
  initialConversationId = null,
  userEmail,
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
  const abortRef = useRef<AbortController | null>(null);
  const [skills, setSkills] = useState<SkillInfo[]>([]);
  const [selectedSkill, setSelectedSkill] = useState<string | null>(null);
  const [feedbackRatings, setFeedbackRatings] = useState<Record<string, number>>({});

  useEffect(() => {
    void apiClient
      .fetchConversations({ accessToken, apiBaseUrl })
      .then(setConversations)
      .catch(() => setConversations([]));
  }, [accessToken, apiBaseUrl, apiClient]);

  useEffect(() => {
    void fetchSkills({ apiBaseUrl }).then(setSkills).catch(() => setSkills([]));
  }, [apiBaseUrl]);

  useEffect(() => {
    if (!activeConversationId) {
      setMessages([]);
      setFeedbackRatings({});
      return;
    }
    startConversationTransition(() => {
      void apiClient
        .fetchConversationDetail(activeConversationId, { accessToken, apiBaseUrl })
        .then((detail) => setMessages(detail.messages))
        .catch(() => setMessages([]));
      void fetchConversationFeedback({
        accessToken, conversationId: activeConversationId, apiBaseUrl,
      }).then(setFeedbackRatings).catch(() => setFeedbackRatings({}));
    });
  }, [accessToken, activeConversationId, apiBaseUrl, apiClient]);

  async function handleSubmit(question: string, attachments?: FileAttachment[]) {
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

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      await streamChat({
        accessToken,
        apiBaseUrl,
        signal: controller.signal,
        payload: {
          question,
          conversation_id: activeConversationId,
          create_conversation: !activeConversationId,
          skill: selectedSkill,
          attachments: attachments?.length ? attachments : undefined,
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
      });
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") {
        // User clicked stop — keep whatever partial content we have
      } else {
        const rateLimitMessage =
          error instanceof RateLimitError
            ? `**Daily limit reached.** ${error.detail.message}\n\nYour free tier allows ${error.detail.limit} ${error.detail.error === "daily_request_limit" ? "requests" : "tokens"} per day. Usage resets at midnight.`
            : "Something went wrong. Please try again.";

        setMessages((current) =>
          current.map((message) =>
            message.id === assistantDraftId
              ? { ...message, content: message.content || rateLimitMessage }
              : message
          )
        );
      }
    } finally {
      abortRef.current = null;
      setIsStreaming(false);
      try {
        const nextConversations = await apiClient.fetchConversations({ accessToken, apiBaseUrl });
        setConversations(nextConversations);
      } catch {
        // Keep the optimistic list if reload fails.
      }
    }
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

  function handleFeedback(messageId: string, rating: 1 | -1) {
    // Optimistic update
    setFeedbackRatings((prev) => ({ ...prev, [messageId]: rating }));
    void submitFeedback({ accessToken, messageId, rating, apiBaseUrl });
  }

  function handleStop() {
    abortRef.current?.abort();
  }

  function handleNewConversation() {
    setSelectedCitation(null);
    setActiveConversationId(null);
    setMessages([]);
    setSelectedSkill(null);
    if (navigate) {
      navigate("/chat");
      return;
    }
    router.push("/chat");
  }

  function handleRenameConversation(conversationId: string, newTitle: string) {
    // Optimistic update
    setConversations((prev) =>
      prev.map((c) => (c.id === conversationId ? { ...c, title: newTitle } : c))
    );
    // Persist to API
    void updateConversation(conversationId, { title: newTitle }, { accessToken, apiBaseUrl });
  }

  function handleDeleteConversation(conversationId: string) {
    // Optimistic update
    setConversations((prev) => prev.filter((c) => c.id !== conversationId));
    // If the deleted conversation is the active one, navigate away
    if (activeConversationId === conversationId) {
      setActiveConversationId(null);
      setMessages([]);
      setSelectedCitation(null);
      if (navigate) {
        navigate("/chat");
      } else {
        router.push("/chat");
      }
    }
    // Persist to API
    void deleteConversation(conversationId, { accessToken, apiBaseUrl });
  }

  function handlePinConversation(conversationId: string, pinned: boolean) {
    // Optimistic update: toggle pinned and re-sort (pinned first)
    setConversations((prev) => {
      const updated = prev.map((c) =>
        c.id === conversationId ? { ...c, pinned } : c
      );
      // Sort: pinned first, then by updated_at descending
      return updated.sort((a, b) => {
        if (a.pinned && !b.pinned) return -1;
        if (!a.pinned && b.pinned) return 1;
        return new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime();
      });
    });
    // Persist to API
    void updateConversation(conversationId, { pinned }, { accessToken, apiBaseUrl });
  }

  const showWelcome = !activeConversationId && messages.length === 0;

  return (
    <div
      style={{
        display: "flex",
        height: "100%",
        overflow: "hidden",
        background: "var(--bg-page)"
      }}
    >
      {/* Sidebar */}
      <ConversationSidebar
        conversations={conversations}
        activeConversationId={activeConversationId}
        onSelect={handleSelectConversation}
        onNewConversation={handleNewConversation}
        onRename={handleRenameConversation}
        onDelete={handleDeleteConversation}
        onPin={handlePinConversation}
        userEmail={userEmail}
      />

      {/* Main area */}
      <div
        style={{
          flex: 1,
          minWidth: 0,
          display: "flex",
          flexDirection: "column",
          background: "var(--bg-surface)"
        }}
      >
        {/* Welcome state or message thread */}
        {showWelcome ? (
          <div
            style={{
              flex: 1,
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              justifyContent: "center",
              padding: "32px 40px"
            }}
          >
            <div
              style={{
                width: "100%",
                maxWidth: 680,
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                gap: 24
              }}
            >
              <h1
                style={{
                  fontSize: 32,
                  fontWeight: 700,
                  letterSpacing: -1,
                  margin: 0,
                  color: "var(--text-primary)"
                }}
              >
                What can I help with?
              </h1>
              <div
                style={{ display: "flex", flexWrap: "wrap", gap: 12, justifyContent: "center" }}
              >
                {SUGGESTION_CHIPS.map((chip) => (
                  <button
                    key={chip}
                    type="button"
                    onClick={() => void handleSubmit(chip)}
                    disabled={isStreaming}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 8,
                      padding: "12px 18px",
                      borderRadius: 12,
                      border: "1px solid var(--border-subtle)",
                      background: "var(--bg-surface)",
                      boxShadow: "0 2px 12px rgba(26,25,24,0.03)",
                      fontSize: 14,
                      fontWeight: 500,
                      color: "var(--text-primary)",
                      cursor: isStreaming ? "not-allowed" : "pointer"
                    }}
                  >
                    {chip}
                  </button>
                ))}
              </div>
            </div>
          </div>
        ) : (
          <div style={{ flex: 1, minHeight: 0, overflow: "auto", padding: "32px 40px" }}>
            <div style={{ maxWidth: 720, margin: "0 auto" }}>
              <MessageList
                messages={messages}
                isStreaming={isStreaming}
                onCitationSelect={setSelectedCitation}
                feedbackRatings={feedbackRatings}
                onFeedback={handleFeedback}
              />
            </div>
          </div>
        )}

        {/* Input section — always visible */}
        <div
          style={{
            flexShrink: 0,
            padding: "0 24px 24px",
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            gap: 8
          }}
        >
          <div style={{ width: "100%", maxWidth: 680 }}>
            <MessageComposer
              disabled={isLoadingConversation}
              isStreaming={isStreaming}
              onSubmit={handleSubmit}
              onStop={handleStop}
              skills={skills}
              selectedSkill={selectedSkill}
              onSkillSelect={setSelectedSkill}
            />
          </div>
          <span
            style={{
              fontSize: 12,
              color: "var(--text-tertiary)",
              textAlign: "center"
            }}
          >
            Polisi.ai can make mistakes. Check important info.
          </span>
        </div>
      </div>

      {/* Citation panel */}
      {selectedCitation ? (
        <CitationPanel citation={selectedCitation} onClose={() => setSelectedCitation(null)} />
      ) : null}
    </div>
  );
}
