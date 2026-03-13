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
    if (!question) return;
    setDraft("");
    await onSubmit(question);
  }

  function handleKeyDown(event: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      const question = draft.trim();
      if (!question || disabled) return;
      setDraft("");
      void onSubmit(question);
    }
  }

  const canSubmit = !!draft.trim() && !disabled;

  return (
    <div
      style={{
        borderRadius: 20,
        border: "1px solid var(--border-subtle)",
        background: "var(--bg-surface)",
        boxShadow: "0 2px 12px rgba(26,25,24,0.03)"
      }}
    >
      <form onSubmit={handleSubmit}>
        {/* Input row */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 12,
            padding: "14px 16px 14px 20px"
          }}
        >
          <textarea
            aria-label="Question"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Message Polisi.ai"
            rows={1}
            disabled={disabled}
            style={{
              flex: 1,
              border: "none",
              outline: "none",
              resize: "none",
              background: "transparent",
              fontSize: 15,
              color: "var(--text-primary)",
              lineHeight: 1.5
            }}
          />
          <button
            type="submit"
            disabled={!canSubmit}
            aria-label="Ask"
            style={{
              width: 36,
              height: 36,
              flexShrink: 0,
              borderRadius: "50%",
              border: "none",
              background: canSubmit ? "var(--accent)" : "var(--border-subtle)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              cursor: canSubmit ? "pointer" : "not-allowed",
              transition: "background 0.15s"
            }}
          >
            <svg
              width="18"
              height="18"
              viewBox="0 0 24 24"
              fill="none"
              stroke="white"
              strokeWidth="2.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="m5 12 7-7 7 7M12 19V5" />
            </svg>
          </button>
        </div>

        {/* Toolbar row */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 4,
            padding: "4px 12px 10px"
          }}
        >
          {[
            {
              label: "Attach file",
              d: "m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l8.57-8.57A4 4 0 1 1 18 8.84l-8.59 8.57a2 2 0 0 1-2.83-2.83l8.49-8.48"
            },
            {
              label: "Web search",
              d: "M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20M2 12h20M12 2c-2.76 0-5 4.48-5 10s2.24 10 5 10 5-4.48 5-10S14.76 2 12 2"
            },
            {
              label: "Add image",
              d: "M21 15a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V9a2 2 0 0 1 2-2h4l2-3h4l2 3h4a2 2 0 0 1 2 2zM12 13a3 3 0 1 0 0-6 3 3 0 0 0 0 6z"
            }
          ].map(({ label, d }) => (
            <button
              key={label}
              type="button"
              aria-label={label}
              style={{
                width: 32,
                height: 32,
                border: "none",
                background: "none",
                borderRadius: 8,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                color: "var(--icon-default)",
                cursor: "pointer"
              }}
            >
              <svg
                width="18"
                height="18"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d={d} />
              </svg>
            </button>
          ))}
        </div>
      </form>
    </div>
  );
}
