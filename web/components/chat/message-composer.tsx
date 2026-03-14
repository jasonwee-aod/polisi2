"use client";

import React from "react";
import { FormEvent, useCallback, useRef, useState } from "react";

import type { FileAttachment, SkillInfo } from "@/lib/api/client";
import { SkillSelector } from "./skill-selector";

const ACCEPTED_TYPES =
  ".pdf,.docx,.xlsx,.csv,.txt,.md,.png,.jpg,.jpeg,.gif,.webp";
const MAX_FILE_SIZE = 10 * 1024 * 1024; // 10 MB
const MAX_FILES = 5;

const IMAGE_EXTENSIONS = new Set([
  "png",
  "jpg",
  "jpeg",
  "gif",
  "webp",
]);

function fileIcon(filename: string): string {
  const ext = filename.split(".").pop()?.toLowerCase() ?? "";
  return IMAGE_EXTENSIONS.has(ext) ? "\u{1F5BC}\uFE0F" : "\u{1F4C4}";
}

function truncate(text: string, max: number): string {
  return text.length > max ? text.slice(0, max - 1) + "\u2026" : text;
}

function readFileAsBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = reader.result as string;
      // Strip the data URL prefix ("data:...;base64,")
      const base64 = result.split(",")[1] ?? "";
      resolve(base64);
    };
    reader.onerror = () => reject(new Error(`Failed to read ${file.name}`));
    reader.readAsDataURL(file);
  });
}

type MessageComposerProps = {
  disabled?: boolean;
  isStreaming?: boolean;
  onSubmit(question: string, attachments?: FileAttachment[]): Promise<void> | void;
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
  const [attachedFiles, setAttachedFiles] = useState<File[]>([]);
  const [isDragOver, setIsDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const addFiles = useCallback((incoming: FileList | File[]) => {
    const files = Array.from(incoming);
    const errors: string[] = [];

    setAttachedFiles((current) => {
      const remaining = MAX_FILES - current.length;
      if (remaining <= 0) {
        errors.push(`Maximum ${MAX_FILES} files allowed.`);
        return current;
      }

      const valid: File[] = [];
      for (const file of files) {
        if (valid.length >= remaining) {
          errors.push(`Maximum ${MAX_FILES} files allowed.`);
          break;
        }
        if (file.size > MAX_FILE_SIZE) {
          errors.push(`${file.name} exceeds 10 MB limit.`);
          continue;
        }
        // Deduplicate by name + size
        const isDuplicate =
          current.some((f) => f.name === file.name && f.size === file.size) ||
          valid.some((f) => f.name === file.name && f.size === file.size);
        if (isDuplicate) continue;
        valid.push(file);
      }

      if (errors.length) {
        // Use setTimeout so the alert doesn't block the state update
        setTimeout(() => alert(errors.join("\n")), 0);
      }

      return valid.length ? [...current, ...valid] : current;
    });
  }, []);

  function removeFile(index: number) {
    setAttachedFiles((current) => current.filter((_, i) => i !== index));
  }

  async function buildAttachments(): Promise<FileAttachment[] | undefined> {
    if (attachedFiles.length === 0) return undefined;
    const results: FileAttachment[] = [];
    for (const file of attachedFiles) {
      const data = await readFileAsBase64(file);
      results.push({
        filename: file.name,
        content_type: file.type || "application/octet-stream",
        data,
      });
    }
    return results;
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const question = draft.trim();
    if (!question && attachedFiles.length === 0) return;
    const attachments = await buildAttachments();
    setDraft("");
    setAttachedFiles([]);
    await onSubmit(question, attachments);
  }

  async function handleKeyDown(event: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      const question = draft.trim();
      if ((!question && attachedFiles.length === 0) || disabled) return;
      const attachments = await buildAttachments();
      setDraft("");
      setAttachedFiles([]);
      void onSubmit(question, attachments);
    }
  }

  function handleDragOver(event: React.DragEvent) {
    event.preventDefault();
    event.stopPropagation();
    setIsDragOver(true);
  }

  function handleDragLeave(event: React.DragEvent) {
    event.preventDefault();
    event.stopPropagation();
    setIsDragOver(false);
  }

  function handleDrop(event: React.DragEvent) {
    event.preventDefault();
    event.stopPropagation();
    setIsDragOver(false);
    if (event.dataTransfer.files.length > 0) {
      addFiles(event.dataTransfer.files);
    }
  }

  function handleFileInputChange(event: React.ChangeEvent<HTMLInputElement>) {
    if (event.target.files && event.target.files.length > 0) {
      addFiles(event.target.files);
    }
    // Reset so selecting the same file again triggers onChange
    event.target.value = "";
  }

  const canSubmit =
    (!!draft.trim() || attachedFiles.length > 0) && !disabled && !isStreaming;

  return (
    <div
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
      style={{
        borderRadius: 20,
        border: isDragOver
          ? "2px dashed var(--accent)"
          : "1px solid var(--border-subtle)",
        background: isDragOver ? "var(--accent-light)" : "var(--bg-surface)",
        boxShadow: "0 2px 12px rgba(26,25,24,0.03)",
        transition: "border 0.15s, background 0.15s",
      }}
    >
      {/* Hidden file input */}
      <input
        ref={fileInputRef}
        type="file"
        multiple
        accept={ACCEPTED_TYPES}
        onChange={handleFileInputChange}
        style={{ display: "none" }}
        aria-hidden="true"
      />

      <form onSubmit={handleSubmit}>
        {/* Input row */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 12,
            padding: "14px 16px 14px 20px",
          }}
        >
          <textarea
            aria-label="Question"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={
              selectedSkill
                ? `Describe what you need (${skills.find((s) => s.id === selectedSkill)?.name || "skill"} mode)`
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
              lineHeight: 1.5,
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
                background: canSubmit
                  ? "var(--accent)"
                  : "var(--border-subtle)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                cursor: canSubmit ? "pointer" : "not-allowed",
                transition: "background 0.15s",
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

        {/* File attachment chips */}
        {attachedFiles.length > 0 && (
          <div
            style={{
              display: "flex",
              flexWrap: "wrap",
              gap: 6,
              padding: "0 16px 8px 20px",
            }}
          >
            {attachedFiles.map((file, index) => (
              <div
                key={`${file.name}-${file.size}-${index}`}
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 4,
                  padding: "4px 8px",
                  borderRadius: 8,
                  background: "var(--bg-page)",
                  border: "1px solid var(--border-subtle)",
                  fontSize: 12,
                  color: "var(--text-secondary)",
                  maxWidth: 200,
                }}
              >
                <span style={{ flexShrink: 0 }}>{fileIcon(file.name)}</span>
                <span
                  style={{
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                >
                  {truncate(file.name, 20)}
                </span>
                <button
                  type="button"
                  onClick={() => removeFile(index)}
                  aria-label={`Remove ${file.name}`}
                  style={{
                    border: "none",
                    background: "transparent",
                    cursor: "pointer",
                    padding: "0 2px",
                    fontSize: 14,
                    lineHeight: 1,
                    color: "var(--text-tertiary)",
                    flexShrink: 0,
                  }}
                >
                  \u2715
                </button>
              </div>
            ))}
          </div>
        )}

        {/* Toolbar row */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 4,
            padding: "4px 12px 10px",
          }}
        >
          {/* Attach button */}
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            disabled={disabled || isStreaming}
            aria-label="Attach files"
            title="Attach files"
            style={{
              display: "flex",
              alignItems: "center",
              gap: 4,
              padding: "4px 10px",
              borderRadius: 8,
              border: "1px solid var(--border-subtle)",
              background: "var(--bg-surface)",
              fontSize: 13,
              color: "var(--text-secondary)",
              cursor: disabled || isStreaming ? "not-allowed" : "pointer",
              opacity: disabled || isStreaming ? 0.5 : 1,
              transition: "background 0.15s",
            }}
            onMouseEnter={(e) => {
              if (!disabled && !isStreaming) {
                e.currentTarget.style.background = "var(--bg-hover)";
              }
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.background = "var(--bg-surface)";
            }}
          >
            {/* Paperclip icon */}
            <svg
              width="14"
              height="14"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M21.44 11.05l-9.19 9.19a6 6 0 01-8.49-8.49l9.19-9.19a4 4 0 015.66 5.66l-9.2 9.19a2 2 0 01-2.83-2.83l8.49-8.48" />
            </svg>
            <span>Attach</span>
          </button>

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
