"use client";

import React from "react";
import { FormEvent, useState } from "react";

type MessageComposerProps = {
  disabled?: boolean;
  onSubmit(question: string): Promise<void> | void;
};

export function MessageComposer({ disabled, onSubmit }: MessageComposerProps) {
  const [draft, setDraft] = useState("");

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const question = draft.trim();
    if (!question) {
      return;
    }
    setDraft("");
    await onSubmit(question);
  }

  return (
    <form onSubmit={handleSubmit} style={{ display: "grid", gap: "0.85rem" }}>
      <textarea
        aria-label="Question"
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        placeholder="Ask about a Malaysian policy in BM or English."
        rows={4}
        disabled={disabled}
        style={{
          width: "100%",
          borderRadius: "1.25rem",
          border: "1px solid rgba(20, 35, 29, 0.12)",
          padding: "1rem",
          resize: "vertical",
          background: "#fbfcf8"
        }}
      />
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <span style={{ color: "#4f6a5f", fontSize: "0.92rem" }}>
          Grounded answers only. BM supported.
        </span>
        <button type="submit" disabled={disabled} style={submitButton}>
          {disabled ? "Generating..." : "Ask"}
        </button>
      </div>
    </form>
  );
}

const submitButton = {
  border: 0,
  borderRadius: "999px",
  padding: "0.8rem 1rem",
  background: "#173a2a",
  color: "#f7fbf7",
  fontWeight: 700,
  cursor: "pointer"
} satisfies React.CSSProperties;
