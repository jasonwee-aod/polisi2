"use client";

import React from "react";
import { FormEvent, useState } from "react";

import type { SkillInfo } from "@/lib/api/client";
import { SkillSelector } from "./skill-selector";

type MessageComposerProps = {
  disabled?: boolean;
  isStreaming?: boolean;
  onSubmit(question: string): Promise<void> | void;
  onStop?(): void;
  skills?: SkillInfo[];
  selectedSkill: string | null;
  onSkillSelect(skillId: string | null): void;
};

export function MessageComposer({
  disabled,
  isStreaming = false,
  onSubmit,
  onStop,
  skills = [],
  selectedSkill,
  onSkillSelect,
}: MessageComposerProps) {
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

  const canSubmit = !!draft.trim() && !disabled && !isStreaming;

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
            placeholder={
              selectedSkill
                ? `Describe what you need (${skills.find(s => s.id === selectedSkill)?.name || "skill"} mode)`
                : "Message Polisi.ai"
            }
            rows={1}
            disabled={disabled || isStreaming}
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

          {isStreaming ? (
            /* Stop button */
            <button
              type="button"
              onClick={onStop}
              aria-label="Stop generating"
              style={{
                width: 36,
                height: 36,
                flexShrink: 0,
                borderRadius: "50%",
                border: "2px solid var(--text-tertiary)",
                background: "transparent",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                cursor: "pointer",
                transition: "border-color 0.15s",
              }}
            >
              {/* Square stop icon */}
              <div
                style={{
                  width: 12,
                  height: 12,
                  borderRadius: 2,
                  background: "var(--text-tertiary)",
                }}
              />
            </button>
          ) : (
            /* Submit button */
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
          )}
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
          {/* Skill selector */}
          {skills.length > 0 && (
            <SkillSelector
              skills={skills}
              selectedSkill={selectedSkill}
              onSelect={onSkillSelect}
              disabled={disabled || isStreaming}
            />
          )}
        </div>
      </form>
    </div>
  );
}
