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
        <article
          key={message.id}
          style={{
            justifySelf: message.role === "user" ? "end" : "stretch",
            maxWidth: message.role === "user" ? "70%" : "100%",
            borderRadius: "1.5rem",
            padding: "1rem 1.1rem",
            background: message.role === "user" ? "#173a2a" : "rgba(255, 255, 255, 0.88)",
            color: message.role === "user" ? "#f7fbf7" : "#14231d",
            border:
              message.role === "user"
                ? "none"
                : "1px solid rgba(20, 35, 29, 0.08)"
          }}
        >
          <div style={{ marginBottom: "0.5rem", fontWeight: 700 }}>
            {message.role === "user" ? "You" : "Polisi"}
          </div>
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
