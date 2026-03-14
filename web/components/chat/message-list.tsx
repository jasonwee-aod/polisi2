"use client";

import React, { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { CitationRecord, ConversationMessage } from "@/lib/api/client";

/**
 * Pipeline stage indicator — progresses through stages based on elapsed time.
 * Mimics the real backend pipeline: search → analyse → fetch data → write.
 */
const PIPELINE_STAGES = [
  { label: "Searching documents", delay: 0 },
  { label: "Analysing relevance", delay: 2500 },
  { label: "Fetching live data", delay: 5000 },
  { label: "Writing response", delay: 8000 },
];

function ThinkingIndicator() {
  const [stageIndex, setStageIndex] = useState(0);
  const [dots, setDots] = useState(1);

  useEffect(() => {
    // Progress through stages based on elapsed time
    const timers = PIPELINE_STAGES.slice(1).map((stage, i) =>
      setTimeout(() => setStageIndex(i + 1), stage.delay)
    );
    return () => timers.forEach(clearTimeout);
  }, []);

  useEffect(() => {
    const interval = setInterval(() => {
      setDots((d) => (d % 3) + 1);
    }, 400);
    return () => clearInterval(interval);
  }, []);

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 8,
        fontSize: 14,
        color: "var(--text-tertiary)",
      }}
    >
      {/* Animated spinner */}
      <svg width="16" height="16" viewBox="0 0 16 16" style={{ animation: "spin 1s linear infinite" }}>
        <circle cx="8" cy="8" r="6" fill="none" stroke="var(--border-subtle)" strokeWidth="2" />
        <path d="M8 2a6 6 0 0 1 6 6" fill="none" stroke="var(--accent)" strokeWidth="2" strokeLinecap="round" />
      </svg>
      <span>
        {PIPELINE_STAGES[stageIndex].label}
        {".".repeat(dots)}
      </span>
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}

type MessageListProps = {
  messages: ConversationMessage[];
  isStreaming?: boolean;
  onCitationSelect(citation: CitationRecord): void;
  feedbackRatings?: Record<string, number>;
  onFeedback?(messageId: string, rating: 1 | -1): void;
};

export function MessageList({
  messages,
  isStreaming = false,
  onCitationSelect,
  feedbackRatings = {},
  onFeedback,
}: MessageListProps) {
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
            currentRating={feedbackRatings[message.id] ?? null}
            onFeedback={onFeedback}
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
  onCitationSelect,
  currentRating,
  onFeedback,
}: {
  message: ConversationMessage;
  isThinking?: boolean;
  onCitationSelect(citation: CitationRecord): void;
  currentRating: number | null;
  onFeedback?(messageId: string, rating: 1 | -1): void;
}) {
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
        {!isThinking && message.content && onFeedback ? (
          <FeedbackButtons
            messageId={message.id}
            currentRating={currentRating}
            onFeedback={onFeedback}
          />
        ) : null}
      </div>
    </div>
  );
}

function FeedbackButtons({
  messageId,
  currentRating,
  onFeedback,
}: {
  messageId: string;
  currentRating: number | null;
  onFeedback(messageId: string, rating: 1 | -1): void;
}) {
  return (
    <div style={{ marginTop: 8, display: "flex", gap: 4 }}>
      <button
        type="button"
        onClick={() => onFeedback(messageId, 1)}
        aria-label="Helpful"
        title="Helpful"
        style={{
          border: 0,
          background: "transparent",
          cursor: "pointer",
          padding: "4px 6px",
          borderRadius: 6,
          opacity: currentRating === -1 ? 0.3 : 1,
          color: currentRating === 1 ? "var(--accent)" : "var(--text-tertiary)",
          fontSize: 16,
        }}
      >
        {currentRating === 1 ? "\u{1F44D}" : "\u{1F44D}\u{FE0E}"}
      </button>
      <button
        type="button"
        onClick={() => onFeedback(messageId, -1)}
        aria-label="Not helpful"
        title="Not helpful"
        style={{
          border: 0,
          background: "transparent",
          cursor: "pointer",
          padding: "4px 6px",
          borderRadius: 6,
          opacity: currentRating === 1 ? 0.3 : 1,
          color: currentRating === -1 ? "#c0392b" : "var(--text-tertiary)",
          fontSize: 16,
        }}
      >
        {currentRating === -1 ? "\u{1F44E}" : "\u{1F44E}\u{FE0E}"}
      </button>
    </div>
  );
}

/** Short readable title from the raw doc title (which often has SHA prefixes). */
function shortenTitle(raw: string): string {
  // Strip leading hex hash prefixes (e.g. "a1b2c3d4... ACTUAL TITLE")
  const cleaned = raw.replace(/^[0-9a-fA-F]{32,}\s*/, "").trim();
  if (!cleaned) return raw;
  // Truncate long titles
  return cleaned.length > 50 ? cleaned.slice(0, 47) + "..." : cleaned;
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
  // Find the data.gov.my citation index (if any) for linking prose mentions
  const datagovCitation = citations.find((c) => c.agency === "data.gov.my");

  // Replace citation markers with inline code tokens for the custom renderer.
  let processed = content
    .replace(/\[(\d+)\]/g, (_, n) => `\`cite:${n}\``)
    .replace(/\[General knowledge\]/gi, "")
    .replace(/\[data\.gov\.my\]/gi, datagovCitation ? `\`cite:${datagovCitation.index}\`` : "");

  // Also catch bare "data.gov.my" mentions in prose and make them clickable
  if (datagovCitation) {
    processed = processed.replace(
      /(?<!\`cite:)\bdata\.gov\.my\b(?![`\]])/g,
      `\`cite:${datagovCitation.index}\``
    );
  }

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
            if (!citation) return <sup style={{ color: "var(--text-tertiary)", fontSize: "0.75em" }}>[{n}]</sup>;

            const title = shortenTitle(citation.title || citation.agency);
            const hasLink = !!citation.source_url;

            return (
              <span
                role="button"
                tabIndex={0}
                onClick={() => onCitationSelect(citation)}
                onKeyDown={(e) => e.key === "Enter" && onCitationSelect(citation)}
                aria-label={`Source: ${title}`}
                title={citation.title || citation.agency}
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 3,
                  padding: "1px 8px",
                  margin: "0 1px",
                  borderRadius: 12,
                  background: "var(--accent-light)",
                  border: "1px solid rgba(61,138,90,0.2)",
                  color: "var(--accent)",
                  fontSize: "0.78em",
                  fontWeight: 600,
                  cursor: "pointer",
                  verticalAlign: "baseline",
                  lineHeight: 1.6,
                  whiteSpace: "nowrap",
                  maxWidth: 220,
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  transition: "background 0.15s, border-color 0.15s",
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.background = "rgba(61,138,90,0.15)";
                  e.currentTarget.style.borderColor = "var(--accent)";
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.background = "var(--accent-light)";
                  e.currentTarget.style.borderColor = "rgba(61,138,90,0.2)";
                }}
              >
                {hasLink ? (
                  <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0 }}>
                    <path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6M15 3h6v6M10 14L21 3" />
                  </svg>
                ) : null}
                <span style={{ overflow: "hidden", textOverflow: "ellipsis" }}>{title}</span>
              </span>
            );
          }
          // Regular code — pass through
          return <code className={className}>{children}</code>;
        }
      }}
    >
      {processed}
    </ReactMarkdown>
  );
}
