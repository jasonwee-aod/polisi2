"use client";

import React from "react";
import { useEffect, useRef, useState } from "react";

import type { SkillInfo } from "@/lib/api/client";

const SKILL_ICONS: Record<string, string> = {
  parliament: "\u{1F3DB}",
  speech: "\u{1F399}",
  brief: "\u{1F4CB}",
  document: "\u{1F4C4}",
  chart: "\u{1F4CA}",
  scale: "\u{2696}",
  data: "\u{1F4C8}",
  memo: "\u{1F4DD}",
};

type SkillSelectorProps = {
  skills: SkillInfo[];
  selectedSkill: string | null;
  onSelect(skillId: string | null): void;
  disabled?: boolean;
};

export function SkillSelector({ skills, selectedSkill, onSelect, disabled }: SkillSelectorProps) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (ref.current && !ref.current.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const active = skills.find((s) => s.id === selectedSkill);

  return (
    <div ref={ref} style={{ position: "relative" }}>
      <button
        type="button"
        disabled={disabled}
        onClick={() => setOpen(!open)}
        aria-label="Select skill"
        style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          padding: "6px 12px",
          borderRadius: 10,
          border: active ? "1px solid var(--accent)" : "1px solid var(--border-subtle)",
          background: active ? "var(--accent-light)" : "transparent",
          fontSize: 13,
          fontWeight: 500,
          color: active ? "var(--accent)" : "var(--text-secondary)",
          cursor: disabled ? "not-allowed" : "pointer",
          transition: "all 0.15s",
          whiteSpace: "nowrap",
        }}
      >
        {active ? (
          <>
            <span>{SKILL_ICONS[active.icon] || "\u{2699}"}</span>
            <span>{active.name}</span>
            <span
              onClick={(e) => {
                e.stopPropagation();
                onSelect(null);
                setOpen(false);
              }}
              style={{
                marginLeft: 2,
                cursor: "pointer",
                fontSize: 14,
                lineHeight: 1,
                color: "var(--text-tertiary)",
              }}
              aria-label="Clear skill"
            >
              \u00D7
            </span>
          </>
        ) : (
          <>
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
              <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z" />
            </svg>
            <span>Skills</span>
          </>
        )}
      </button>

      {open && (
        <div
          style={{
            position: "absolute",
            bottom: "calc(100% + 8px)",
            left: 0,
            width: 320,
            maxHeight: 400,
            overflowY: "auto",
            background: "var(--bg-surface)",
            border: "1px solid var(--border-subtle)",
            borderRadius: 14,
            boxShadow: "0 8px 32px rgba(26,25,24,0.12)",
            zIndex: 100,
            padding: "6px",
          }}
        >
          {/* None option */}
          <button
            type="button"
            onClick={() => {
              onSelect(null);
              setOpen(false);
            }}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 10,
              width: "100%",
              padding: "10px 12px",
              borderRadius: 10,
              border: "none",
              background: !selectedSkill ? "var(--bg-hover)" : "transparent",
              textAlign: "left",
              cursor: "pointer",
              fontSize: 13,
              color: "var(--text-primary)",
              transition: "background 0.1s",
            }}
          >
            <span style={{ width: 24, textAlign: "center", fontSize: 16 }}>💬</span>
            <div>
              <div style={{ fontWeight: 600 }}>General Chat</div>
              <div style={{ fontSize: 12, color: "var(--text-tertiary)", marginTop: 1 }}>
                Standard policy Q&A without a specific output format
              </div>
            </div>
          </button>

          <div
            style={{
              height: 1,
              background: "var(--border-subtle)",
              margin: "4px 8px",
            }}
          />

          {skills.map((skill) => (
            <button
              key={skill.id}
              type="button"
              onClick={() => {
                onSelect(skill.id);
                setOpen(false);
              }}
              style={{
                display: "flex",
                alignItems: "flex-start",
                gap: 10,
                width: "100%",
                padding: "10px 12px",
                borderRadius: 10,
                border: "none",
                background: selectedSkill === skill.id ? "var(--accent-light)" : "transparent",
                textAlign: "left",
                cursor: "pointer",
                fontSize: 13,
                color: "var(--text-primary)",
                transition: "background 0.1s",
              }}
            >
              <span style={{ width: 24, textAlign: "center", fontSize: 16, flexShrink: 0, marginTop: 1 }}>
                {SKILL_ICONS[skill.icon] || "\u{2699}"}
              </span>
              <div style={{ minWidth: 0 }}>
                <div style={{ fontWeight: 600 }}>{skill.name}</div>
                <div
                  style={{
                    fontSize: 12,
                    color: "var(--text-tertiary)",
                    marginTop: 1,
                    lineHeight: 1.4,
                  }}
                >
                  {skill.description}
                </div>
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
