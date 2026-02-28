"use client";

import React from "react";

import { ConversationSummary } from "@/lib/api/client";

type ConversationSidebarProps = {
  conversations: ConversationSummary[];
  activeConversationId?: string | null;
  onSelect(conversationId: string): void;
  onNewConversation(): void;
};

export function ConversationSidebar({
  conversations,
  activeConversationId,
  onSelect,
  onNewConversation
}: ConversationSidebarProps) {
  return (
    <aside
      style={{
        display: "grid",
        gap: "0.85rem",
        padding: "1rem",
        borderRadius: "1.5rem",
        border: "1px solid rgba(20, 35, 29, 0.08)",
        background: "rgba(255, 255, 255, 0.82)"
      }}
    >
      <button type="button" onClick={onNewConversation} style={primaryButton}>
        New chat
      </button>
      <div style={{ display: "grid", gap: "0.5rem" }}>
        {conversations.length === 0 ? (
          <p style={{ margin: 0, color: "#4f6a5f", lineHeight: 1.6 }}>
            No conversations yet. Start with a direct BM or English policy question.
          </p>
        ) : (
          conversations.map((conversation) => {
            const isActive = conversation.id === activeConversationId;
            return (
              <button
                key={conversation.id}
                type="button"
                onClick={() => onSelect(conversation.id)}
                style={{
                  textAlign: "left",
                  borderRadius: "1rem",
                  border: isActive
                    ? "1px solid rgba(23, 58, 42, 0.35)"
                    : "1px solid rgba(20, 35, 29, 0.08)",
                  background: isActive ? "rgba(232, 240, 233, 0.95)" : "#f8faf5",
                  padding: "0.85rem",
                  cursor: "pointer"
                }}
              >
                <strong style={{ display: "block", marginBottom: "0.2rem" }}>
                  {conversation.title ?? "Untitled conversation"}
                </strong>
                <span style={{ color: "#4f6a5f", fontSize: "0.92rem" }}>
                  {new Date(conversation.updated_at).toLocaleString()}
                </span>
              </button>
            );
          })
        )}
      </div>
    </aside>
  );
}

const primaryButton = {
  border: 0,
  borderRadius: "999px",
  padding: "0.8rem 1rem",
  background: "#173a2a",
  color: "#f7fbf7",
  fontWeight: 700,
  cursor: "pointer"
} satisfies React.CSSProperties;
