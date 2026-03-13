"use client";

import React from "react";

import { CitationRecord } from "@/lib/api/client";

function decodeDocTitle(raw: string): string {
  try {
    return decodeURIComponent(raw.replace(/ ([0-9A-Fa-f]{2})/g, "%$1"));
  } catch {
    return raw;
  }
}

type CitationPanelProps = {
  citation: CitationRecord | null;
  onClose(): void;
};

export function CitationPanel({ citation, onClose }: CitationPanelProps) {
  if (!citation) {
    return (
      <aside style={panelStyle}>
        <div style={{ padding: 20 }}>
          <strong style={{ fontSize: 14, fontWeight: 600 }}>Citations</strong>
          <p style={{ margin: "8px 0 0", fontSize: 13, color: "var(--text-tertiary)", lineHeight: 1.6 }}>
            Select a citation marker in the answer to inspect the source.
          </p>
        </div>
      </aside>
    );
  }

  return (
    <aside style={panelStyle}>
      {/* Panel header */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "14px 20px",
          borderBottom: "1px solid var(--border-subtle)",
          flexShrink: 0
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <svg
            width="18"
            height="18"
            viewBox="0 0 24 24"
            fill="none"
            stroke="var(--icon-default)"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7z" />
            <path d="M14 2v5h5M16 13H8M16 17H8M10 9H8" />
          </svg>
          <span style={{ fontSize: 14, fontWeight: 600, color: "var(--text-primary)" }}>
            Source [{citation.index}]
          </span>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close citation panel"
          style={{
            width: 28,
            height: 28,
            borderRadius: 6,
            border: "none",
            background: "none",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            cursor: "pointer",
            color: "var(--icon-default)"
          }}
        >
          <svg
            width="16"
            height="16"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M18 6 6 18M6 6l12 12" />
          </svg>
        </button>
      </div>

      {/* Panel content */}
      <div
        style={{
          flex: 1,
          overflow: "auto",
          padding: 20,
          display: "flex",
          flexDirection: "column",
          gap: 16
        }}
      >
        {/* Document card */}
        <div
          style={{
            borderRadius: 12,
            border: "1px solid var(--border-subtle)",
            background: "#FAFAF8",
            padding: 16,
            display: "flex",
            flexDirection: "column",
            gap: 12
          }}
        >
          {/* Card header */}
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <div
              style={{
                width: 32,
                height: 32,
                borderRadius: 6,
                flexShrink: 0,
                background: "#FEE2E2",
                display: "flex",
                alignItems: "center",
                justifyContent: "center"
              }}
            >
              <span style={{ fontSize: 9, fontWeight: 700, color: "#DC2626" }}>PDF</span>
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div
                style={{
                  fontSize: 13,
                  fontWeight: 600,
                  color: "var(--text-primary)",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap"
                }}
              >
                {decodeDocTitle(citation.title || citation.agency)}
              </div>
              <div style={{ fontSize: 11, color: "var(--text-tertiary)" }}>{citation.agency}</div>
            </div>
          </div>

          {/* Divider */}
          <div style={{ height: 1, background: "var(--border-subtle)" }} />

          {/* Relevant excerpt */}
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <div
              style={{
                fontSize: 11,
                fontWeight: 600,
                color: "var(--text-tertiary)",
                textTransform: "uppercase",
                letterSpacing: 0.5
              }}
            >
              Relevant Passage
            </div>
            <div
              style={{
                display: "flex",
                borderRadius: 8,
                border: "1px solid rgba(61,138,90,0.2)",
                background: "var(--accent-light)",
                overflow: "hidden"
              }}
            >
              <div style={{ width: 3, flexShrink: 0, background: "var(--accent)" }} />
              <p
                style={{
                  margin: 0,
                  padding: "12px 14px",
                  fontSize: 13,
                  lineHeight: 1.6,
                  color: "var(--text-primary)"
                }}
              >
                {citation.excerpt}
              </p>
            </div>
          </div>

          {citation.published_at ? (
            <div style={{ fontSize: 11, color: "var(--text-tertiary)" }}>
              Published: {citation.published_at}
            </div>
          ) : null}
        </div>

        {/* Source link */}
        {citation.source_url && !citation.source_url.startsWith("file://") ? (
          <a
            href={citation.source_url}
            rel="noreferrer"
            target="_blank"
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
              fontSize: 13,
              fontWeight: 500,
              color: "var(--accent)"
            }}
          >
            Open original source
          </a>
        ) : (
          <span style={{ fontSize: 13, color: "var(--text-tertiary)" }}>
            No public URL available for this document.
          </span>
        )}
      </div>
    </aside>
  );
}

const panelStyle = {
  width: 380,
  flexShrink: 0,
  height: "100%",
  display: "flex",
  flexDirection: "column",
  background: "var(--bg-surface)",
  borderLeft: "1px solid var(--border-subtle)",
  overflow: "hidden"
} satisfies React.CSSProperties;
