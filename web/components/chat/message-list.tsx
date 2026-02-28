"use client";

import React from "react";

import { CitationRecord, ConversationMessage } from "@/lib/api/client";

type MessageListProps = {
  messages: ConversationMessage[];
  onCitationSelect(citation: CitationRecord): void;
};

export function MessageList({ messages, onCitationSelect }: MessageListProps) {
  if (messages.length === 0) {
    return (
      <div
        style={{
          display: "grid",
          gap: "0.75rem",
          padding: "1.2rem",
          borderRadius: "1.5rem",
          border: "1px dashed rgba(20, 35, 29, 0.18)",
          background: "rgba(248, 250, 245, 0.8)"
        }}
      >
        <strong>New conversation</strong>
        <p style={{ margin: 0, color: "#4f6a5f", lineHeight: 1.7 }}>
          Ask a direct question and the answer will stream into this thread. Clarifications,
          limited-support replies, and no-information responses will appear here as part of the
          same conversation.
        </p>
      </div>
    );
  }

  return (
    <div style={{ display: "grid", gap: "1rem" }}>
      {messages.map((message) => (
        <article key={message.id} style={messageCardStyle(message)}>
          <div style={{ marginBottom: "0.5rem", fontWeight: 700 }}>
            {message.role === "user" ? "You" : "Polisi"}
          </div>
          {message.role === "assistant" && getAssistantVariant(message.content) !== "standard" ? (
            <div
              style={{
                marginBottom: "0.45rem",
                textTransform: "uppercase",
                letterSpacing: "0.08em",
                fontSize: "0.78rem",
                fontWeight: 700,
                color: "#4f6a5f"
              }}
            >
              {assistantVariantLabel(getAssistantVariant(message.content))}
            </div>
          ) : null}
          <p style={{ margin: 0, lineHeight: 1.75 }}>{renderAnswer(message, onCitationSelect)}</p>
          {message.role === "assistant" && message.citations.length > 0 ? (
            <div style={{ marginTop: "0.75rem", color: "#4f6a5f", fontSize: "0.92rem" }}>
              {message.citations.length} source{message.citations.length === 1 ? "" : "s"} available
            </div>
          ) : null}
        </article>
      ))}
    </div>
  );
}

function messageCardStyle(message: ConversationMessage): React.CSSProperties {
  const assistantVariant = message.role === "assistant" ? getAssistantVariant(message.content) : "standard";
  return {
    justifySelf: message.role === "user" ? "end" : "stretch",
    maxWidth: message.role === "user" ? "70%" : "100%",
    borderRadius: "1.5rem",
    padding: "1rem 1.1rem",
    background:
      message.role === "user"
        ? "#173a2a"
        : assistantVariant === "limited"
          ? "rgba(250, 246, 234, 0.95)"
          : assistantVariant === "no-info"
            ? "rgba(246, 242, 242, 0.95)"
            : "rgba(255, 255, 255, 0.88)",
    color: message.role === "user" ? "#f7fbf7" : "#14231d",
    border:
      message.role === "user"
        ? "none"
        : "1px solid rgba(20, 35, 29, 0.08)"
  };
}

function getAssistantVariant(content: string): "standard" | "clarification" | "limited" | "no-info" {
  const normalized = content.toLowerCase();
  if (normalized.includes("specific policy") || normalized.includes("jelaskan dasar")) {
    return "clarification";
  }
  if (normalized.includes("support is limited") || normalized.includes("sokongan dokumen")) {
    return "limited";
  }
  if (normalized.includes("could not find enough support") || normalized.includes("tidak menemui maklumat")) {
    return "no-info";
  }
  return "standard";
}

function assistantVariantLabel(variant: ReturnType<typeof getAssistantVariant>): string {
  switch (variant) {
    case "clarification":
      return "Clarification requested";
    case "limited":
      return "Limited support";
    case "no-info":
      return "No indexed support";
    default:
      return "";
  }
}

function renderAnswer(
  message: ConversationMessage,
  onCitationSelect: (citation: CitationRecord) => void
): Array<string | JSX.Element> {
  const parts = message.content.split(/(\[\d+\])/g);
  return parts.map((part, index) => {
    const match = /^\[(\d+)\]$/.exec(part);
    if (!match) {
      return part;
    }
    const citation = message.citations.find((item) => item.index === Number(match[1]));
    if (!citation) {
      return part;
    }
    return (
      <button
        key={`${message.id}-${citation.index}-${index}`}
        type="button"
        onClick={() => onCitationSelect(citation)}
        aria-label={`Citation ${citation.index}`}
        style={{
          border: 0,
          background: "transparent",
          cursor: "pointer",
          color: "#173a2a",
          fontWeight: 700,
          verticalAlign: "super",
          fontSize: "0.8em",
          padding: "0 0.1rem",
          textDecoration: "underline"
        }}
      >
        [{citation.index}]
      </button>
    );
  });
}
