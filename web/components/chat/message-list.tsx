"use client";

import React, { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { CitationRecord, ConversationMessage } from "@/lib/api/client";

const THINKING_PHASES = ["Searching documents...", "Thinking...", "Generating..."];

function ThinkingIndicator() {
  const [phaseIndex, setPhaseIndex] = useState(0);
  const [visible, setVisible] = useState(true);

  useEffect(() => {
    const cycle = setInterval(() => {
      setVisible(false);
      setTimeout(() => {
        setPhaseIndex((i) => (i + 1) % THINKING_PHASES.length);
        setVisible(true);
      }, 300);
    }, 1800);
    return () => clearInterval(cycle);
  }, []);

  return (
    <span
      style={{
        fontSize: 14,
        color: "var(--text-tertiary)",
        fontStyle: "italic",
        opacity: visible ? 1 : 0,
        transition: "opacity 0.3s ease",
        display: "inline-block"
      }}
    >
      {THINKING_PHASES[phaseIndex]}
    </span>
  );
}

type MessageListProps = {
  messages: ConversationMessage[];
  isStreaming?: boolean;
  onCitationSelect(citation: CitationRecord): void;
};

export function MessageList({ messages, isStreaming = false, onCitationSelect }: MessageListProps) {
  if (messages.length === 0) {
    return null;
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
      {messages.map((message, index) =>
        message.role === "user" ? (
          <UserMessage key={message.id} message={message} />
        ) : (
          <AssistantMessage
            key={message.id}
            message={message}
            isThinking={isStreaming && index === messages.length - 1 && message.content === ""}
            onCitationSelect={onCitationSelect}
          />
        )
      )}
    </div>
  );
}

function UserMessage({ message }: { message: ConversationMessage }) {
  return (
    <div style={{ display: "flex", justifyContent: "flex-end", alignItems: "flex-end", gap: 12 }}>
      <div
        style={{
          maxWidth: "60%",
          padding: "12px 16px",
          borderRadius: "16px 16px 4px 16px",
          background: "#EDECEA",
          color: "var(--text-primary)",
          fontSize: 15,
          lineHeight: 1.5
        }}
      >
        {message.content}
      </div>
      <div
        style={{
          width: 28,
          height: 28,
          flexShrink: 0,
          borderRadius: "50%",
          background: "var(--accent)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center"
        }}
      >
        <span style={{ color: "var(--text-inverse)", fontSize: 10, fontWeight: 600 }}>ME</span>
      </div>
    </div>
  );
}

function AssistantMessage({
  message,
  isThinking = false,
  onCitationSelect
}: {
  message: ConversationMessage;
  isThinking?: boolean;
  onCitationSelect(citation: CitationRecord): void;
}) {
  const variant = getAssistantVariant(message.content);
  return (
    <div style={{ display: "flex", gap: 12 }}>
      <div
        style={{
          width: 28,
          height: 28,
          flexShrink: 0,
          borderRadius: "50%",
          background: "var(--text-primary)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center"
        }}
      >
        <span style={{ color: "var(--text-inverse)", fontSize: 13, fontWeight: 700 }}>P</span>
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        {variant !== "standard" ? (
          <div
            style={{
              fontSize: 11,
              fontWeight: 600,
              color: "var(--text-tertiary)",
              textTransform: "uppercase",
              letterSpacing: "0.08em",
              marginBottom: 8
            }}
          >
            {assistantVariantLabel(variant)}
          </div>
        ) : null}
        <div className="prose" style={{ fontSize: 15, lineHeight: 1.7, color: "var(--text-primary)" }}>
          {isThinking ? (
            <ThinkingIndicator />
          ) : (
            <MarkdownWithCitations
              content={message.content}
              citations={message.citations}
              onCitationSelect={onCitationSelect}
            />
          )}
        </div>
        {message.citations.length > 0 ? (
          <div style={{ marginTop: 12, display: "flex", flexWrap: "wrap", gap: 6 }}>
            {message.citations.map((citation) => (
              <button
                key={citation.index}
                type="button"
                onClick={() => onCitationSelect(citation)}
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 5,
                  padding: "4px 10px",
                  borderRadius: 20,
                  border: "1px solid var(--border-subtle)",
                  background: "var(--bg-page)",
                  color: "var(--text-secondary)",
                  fontSize: 12,
                  fontWeight: 500,
                  cursor: "pointer"
                }}
              >
                <span style={{ color: "var(--accent)", fontWeight: 700 }}>[{citation.index}]</span>
                {decodeDocTitle(citation.title || citation.agency)}
              </button>
            ))}
          </div>
        ) : null}
      </div>
    </div>
  );
}

// Titles are stored with % stripped from URL-encoding (e.g. "SPI 20KPM" → "SPI KPM").
// Re-insert % before hex pairs and URL-decode to get readable titles.
function decodeDocTitle(raw: string): string {
  try {
    return decodeURIComponent(raw.replace(/ ([0-9A-Fa-f]{2})/g, "%$1"));
  } catch {
    return raw;
  }
}

function MarkdownWithCitations({
  content,
  citations,
  onCitationSelect
}: {
  content: string;
  citations: CitationRecord[];
  onCitationSelect(citation: CitationRecord): void;
}) {
  // Replace citation markers with inline code spans so the whole content
  // renders in one ReactMarkdown call, preserving block-level structure
  // (tables, code blocks, headings). The custom `code` component below
  // intercepts only the cite:n / cite:gk tokens.
  const processed = content
    .replace(/\[(\d+)\]/g, (_, n) => `\`cite:${n}\``)
    .replace(/\[General knowledge\]/g, "`cite:gk`");

  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        code({ children, className }) {
          const text = String(children);
          const citeMatch = /^cite:(\d+)$/.exec(text);
          if (citeMatch) {
            const n = Number(citeMatch[1]);
            const citation = citations.find((c) => c.index === n);
            if (!citation) return <span>[{n}]</span>;
            return (
              <button
                type="button"
                onClick={() => onCitationSelect(citation)}
                aria-label={`Citation ${n}`}
                style={{
                  border: 0,
                  background: "transparent",
                  cursor: "pointer",
                  color: "var(--accent)",
                  fontWeight: 700,
                  verticalAlign: "super",
                  fontSize: "0.8em",
                  padding: "0 0.1rem",
                  textDecoration: "underline"
                }}
              >
                [{n}]
              </button>
            );
          }
          if (text === "cite:gk") {
            return (
              <span
                title="From Claude's training knowledge"
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  padding: "1px 6px",
                  borderRadius: 10,
                  background: "var(--bg-page)",
                  border: "1px solid var(--border-subtle)",
                  color: "var(--text-tertiary)",
                  fontSize: "0.72em",
                  fontWeight: 500,
                  verticalAlign: "super",
                  letterSpacing: "0.02em",
                  whiteSpace: "nowrap"
                }}
              >
                General knowledge
              </span>
            );
          }
          return <code className={className}>{children}</code>;
        }
      }}
    >
      {processed}
    </ReactMarkdown>
  );
}

function getAssistantVariant(content: string): "standard" | "clarification" | "limited" | "general-knowledge" {
  const normalized = content.toLowerCase();
  if (normalized.includes("specific policy") || normalized.includes("jelaskan dasar")) {
    return "clarification";
  }
  if (normalized.includes("support is limited") || normalized.includes("sokongan dokumen")) {
    return "limited";
  }
  if (
    normalized.includes("no indexed government policy documents were found") ||
    normalized.includes("tiada dokumen dasar kerajaan yang diindeks")
  ) {
    return "general-knowledge";
  }
  return "standard";
}

function assistantVariantLabel(variant: ReturnType<typeof getAssistantVariant>): string {
  switch (variant) {
    case "clarification":
      return "Clarification requested";
    case "limited":
      return "Limited indexed support";
    case "general-knowledge":
      return "General knowledge — not from indexed documents";
    default:
      return "";
  }
}
