"use client";

import React from "react";

import { CitationRecord } from "@/lib/api/client";

type CitationPanelProps = {
  citation: CitationRecord | null;
  onClose(): void;
};

export function CitationPanel({ citation, onClose }: CitationPanelProps) {
  if (!citation) {
    return (
      <aside style={panelStyle}>
        <div style={{ display: "grid", gap: "0.65rem" }}>
          <strong>Citations</strong>
          <p style={mutedText}>Select a citation marker in the answer to inspect the source.</p>
        </div>
      </aside>
    );
  }

  return (
    <aside style={panelStyle}>
      <div style={{ display: "grid", gap: "0.85rem" }}>
        <span
          style={{
            textTransform: "uppercase",
            letterSpacing: "0.1em",
            fontWeight: 700,
            color: "#4f6a5f",
            fontSize: "0.8rem"
          }}
        >
          Source [{citation.index}]
        </span>
        <div style={{ display: "flex", justifyContent: "space-between", gap: "1rem" }}>
          <strong>{citation.title || citation.agency}</strong>
          <button type="button" onClick={onClose} style={ghostButton}>
            Close
          </button>
        </div>
        <p style={mutedText}>{citation.agency}</p>
        {citation.published_at ? (
          <p style={mutedText}>Published: {citation.published_at}</p>
        ) : null}
        <blockquote
          style={{
            margin: 0,
            padding: "0.85rem 1rem",
            borderRadius: "1rem",
            background: "#f5f7f0",
            lineHeight: 1.6,
            borderLeft: "4px solid rgba(23, 58, 42, 0.35)"
          }}
        >
          {citation.excerpt}
        </blockquote>
        <a href={citation.source_url} rel="noreferrer" target="_blank" style={linkStyle}>
          Open original source
        </a>
      </div>
    </aside>
  );
}

const panelStyle = {
  borderRadius: "1.5rem",
  border: "1px solid rgba(20, 35, 29, 0.08)",
  background: "rgba(255, 255, 255, 0.82)",
  padding: "1.1rem",
  minHeight: "16rem"
} satisfies React.CSSProperties;

const mutedText = {
  margin: 0,
  color: "#4f6a5f",
  lineHeight: 1.6
} satisfies React.CSSProperties;

const ghostButton = {
  border: 0,
  background: "transparent",
  color: "#173a2a",
  cursor: "pointer"
} satisfies React.CSSProperties;

const linkStyle = {
  color: "#173a2a",
  fontWeight: 700
} satisfies React.CSSProperties;
