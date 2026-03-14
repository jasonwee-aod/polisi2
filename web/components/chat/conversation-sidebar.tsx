"use client";

import React, { useEffect, useRef, useState } from "react";

import { ConversationSummary } from "@/lib/api/client";

type ConversationSidebarProps = {
  conversations: ConversationSummary[];
  activeConversationId?: string | null;
  onSelect(conversationId: string): void;
  onNewConversation(): void;
  onRename?(conversationId: string, newTitle: string): void;
  onDelete?(conversationId: string): void;
  onPin?(conversationId: string, pinned: boolean): void;
  userEmail?: string | null;
};

function groupByDate(conversations: ConversationSummary[]) {
  const todayStart = new Date();
  todayStart.setHours(0, 0, 0, 0);
  const yesterdayStart = new Date(todayStart.getTime() - 86_400_000);
  const sevenDaysAgo = new Date(todayStart.getTime() - 7 * 86_400_000);

  const pinned: ConversationSummary[] = [];
  const today: ConversationSummary[] = [];
  const yesterday: ConversationSummary[] = [];
  const week: ConversationSummary[] = [];
  const older: ConversationSummary[] = [];

  for (const c of conversations) {
    if (c.pinned) {
      pinned.push(c);
      continue;
    }
    const d = new Date(c.updated_at);
    if (d >= todayStart) today.push(c);
    else if (d >= yesterdayStart) yesterday.push(c);
    else if (d >= sevenDaysAgo) week.push(c);
    else older.push(c);
  }
  return { pinned, today, yesterday, week, older };
}

function getInitials(email?: string | null): string {
  if (!email) return "?";
  const name = email.split("@")[0];
  const parts = name.split(/[._-]/);
  return parts.length >= 2
    ? (parts[0][0] + parts[1][0]).toUpperCase()
    : name.slice(0, 2).toUpperCase();
}

/* ------------------------------------------------------------------ */
/*  Context Menu                                                       */
/* ------------------------------------------------------------------ */

type ContextMenuProps = {
  x: number;
  y: number;
  isPinned: boolean;
  onPin(): void;
  onRename(): void;
  onDelete(): void;
  onClose(): void;
};

function ContextMenu({ x, y, isPinned, onPin, onRename, onDelete, onClose }: ContextMenuProps) {
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        onClose();
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [onClose]);

  const menuItemStyle: React.CSSProperties = {
    display: "flex",
    alignItems: "center",
    gap: 8,
    width: "100%",
    padding: "8px 12px",
    border: "none",
    background: "none",
    fontSize: 13,
    color: "var(--text-primary)",
    cursor: "pointer",
    borderRadius: 4,
    textAlign: "left",
  };

  return (
    <div
      ref={menuRef}
      style={{
        position: "fixed",
        top: y,
        left: x,
        zIndex: 1000,
        minWidth: 160,
        padding: 4,
        background: "var(--bg-surface)",
        border: "1px solid var(--border-subtle)",
        borderRadius: 8,
        boxShadow: "0 4px 16px rgba(26,25,24,0.12)",
      }}
    >
      <button
        type="button"
        style={menuItemStyle}
        onClick={() => { onPin(); onClose(); }}
        onMouseEnter={(e) => { e.currentTarget.style.background = "var(--bg-hover)"; }}
        onMouseLeave={(e) => { e.currentTarget.style.background = "none"; }}
      >
        <span style={{ width: 16, textAlign: "center" }}>{isPinned ? "📌" : "📌"}</span>
        {isPinned ? "Unpin" : "Pin"}
      </button>
      <button
        type="button"
        style={menuItemStyle}
        onClick={() => { onRename(); onClose(); }}
        onMouseEnter={(e) => { e.currentTarget.style.background = "var(--bg-hover)"; }}
        onMouseLeave={(e) => { e.currentTarget.style.background = "none"; }}
      >
        <span style={{ width: 16, textAlign: "center" }}>✏️</span>
        Rename
      </button>
      <div style={{ height: 1, background: "var(--border-subtle)", margin: "4px 0" }} />
      <button
        type="button"
        style={{ ...menuItemStyle, color: "#c0392b" }}
        onClick={() => { onDelete(); onClose(); }}
        onMouseEnter={(e) => { e.currentTarget.style.background = "var(--bg-hover)"; }}
        onMouseLeave={(e) => { e.currentTarget.style.background = "none"; }}
      >
        <span style={{ width: 16, textAlign: "center" }}>🗑️</span>
        Delete
      </button>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Chat Item                                                          */
/* ------------------------------------------------------------------ */

type ChatItemProps = {
  conversation: ConversationSummary;
  isActive: boolean;
  onSelect(): void;
  onRename?(newTitle: string): void;
  onDelete?(): void;
  onPin?(pinned: boolean): void;
};

function ChatItem({ conversation, isActive, onSelect, onRename, onDelete, onPin }: ChatItemProps) {
  const [isHovered, setIsHovered] = useState(false);
  const [menuPos, setMenuPos] = useState<{ x: number; y: number } | null>(null);
  const [isRenaming, setIsRenaming] = useState(false);
  const [renameValue, setRenameValue] = useState(conversation.title ?? "");
  const inputRef = useRef<HTMLInputElement>(null);
  const dotsRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (isRenaming && inputRef.current) {
      inputRef.current.focus();
      inputRef.current.select();
    }
  }, [isRenaming]);

  function handleDotsClick(e: React.MouseEvent) {
    e.stopPropagation();
    if (dotsRef.current) {
      const rect = dotsRef.current.getBoundingClientRect();
      setMenuPos({ x: rect.left, y: rect.bottom + 4 });
    }
  }

  function handleRenameSubmit() {
    const trimmed = renameValue.trim();
    if (trimmed && trimmed !== conversation.title) {
      onRename?.(trimmed);
    }
    setIsRenaming(false);
  }

  function handleDeleteClick() {
    if (window.confirm("Delete this chat?")) {
      onDelete?.();
    }
  }

  return (
    <>
      <div
        style={{
          position: "relative",
          display: "flex",
          alignItems: "center",
          borderRadius: 8,
          background: isActive ? "var(--bg-hover)" : isHovered ? "rgba(0,0,0,0.03)" : "transparent",
          cursor: "pointer",
        }}
        onMouseEnter={() => setIsHovered(true)}
        onMouseLeave={() => setIsHovered(false)}
      >
        {isRenaming ? (
          <input
            ref={inputRef}
            value={renameValue}
            onChange={(e) => setRenameValue(e.target.value)}
            onBlur={handleRenameSubmit}
            onKeyDown={(e) => {
              if (e.key === "Enter") handleRenameSubmit();
              if (e.key === "Escape") { setIsRenaming(false); setRenameValue(conversation.title ?? ""); }
            }}
            style={{
              flex: 1,
              border: "1px solid var(--accent)",
              borderRadius: 6,
              padding: "8px 10px",
              fontSize: 13,
              background: "var(--bg-surface)",
              color: "var(--text-primary)",
              outline: "none",
              margin: "2px 4px",
            }}
          />
        ) : (
          <button
            type="button"
            onClick={onSelect}
            style={{
              flex: 1,
              textAlign: "left",
              border: "none",
              background: "transparent",
              borderRadius: 8,
              padding: "10px 12px",
              color: isActive ? "var(--text-primary)" : "var(--text-secondary)",
              fontSize: 13,
              fontWeight: isActive ? 500 : 400,
              cursor: "pointer",
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
              paddingRight: conversation.pinned ? 28 : undefined,
            }}
          >
            {conversation.pinned && (
              <span style={{ marginRight: 4, fontSize: 11 }}>📌</span>
            )}
            {conversation.title ?? "Untitled conversation"}
          </button>
        )}

        {/* Three-dot button — visible on hover or when menu is open */}
        {(isHovered || menuPos) && !isRenaming && (
          <button
            ref={dotsRef}
            type="button"
            onClick={handleDotsClick}
            aria-label="Conversation options"
            style={{
              position: "absolute",
              right: 4,
              top: "50%",
              transform: "translateY(-50%)",
              border: "none",
              background: "var(--bg-hover)",
              borderRadius: 4,
              padding: "2px 4px",
              cursor: "pointer",
              color: "var(--text-tertiary)",
              lineHeight: 1,
              fontSize: 14,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            <svg
              width="14"
              height="14"
              viewBox="0 0 24 24"
              fill="currentColor"
              stroke="none"
            >
              <circle cx="12" cy="5" r="2" />
              <circle cx="12" cy="12" r="2" />
              <circle cx="12" cy="19" r="2" />
            </svg>
          </button>
        )}
      </div>

      {/* Context menu */}
      {menuPos && (
        <ContextMenu
          x={menuPos.x}
          y={menuPos.y}
          isPinned={!!conversation.pinned}
          onPin={() => onPin?.(!conversation.pinned)}
          onRename={() => {
            setRenameValue(conversation.title ?? "");
            setIsRenaming(true);
          }}
          onDelete={handleDeleteClick}
          onClose={() => setMenuPos(null)}
        />
      )}
    </>
  );
}

/* ------------------------------------------------------------------ */
/*  Chat Group                                                         */
/* ------------------------------------------------------------------ */

function ChatGroup({
  label,
  items,
  activeId,
  onSelect,
  onRename,
  onDelete,
  onPin,
}: {
  label: string;
  items: ConversationSummary[];
  activeId?: string | null;
  onSelect(id: string): void;
  onRename?(id: string, title: string): void;
  onDelete?(id: string): void;
  onPin?(id: string, pinned: boolean): void;
}) {
  if (!items.length) return null;
  return (
    <div style={{ marginBottom: 16 }}>
      <div
        style={{
          fontSize: 11,
          fontWeight: 600,
          color: "var(--text-tertiary)",
          textTransform: "uppercase",
          letterSpacing: 0.3,
          padding: "0 8px 4px"
        }}
      >
        {label}
      </div>
      {items.map((c) => (
        <ChatItem
          key={c.id}
          conversation={c}
          isActive={c.id === activeId}
          onSelect={() => onSelect(c.id)}
          onRename={(title) => onRename?.(c.id, title)}
          onDelete={() => onDelete?.(c.id)}
          onPin={(pinned) => onPin?.(c.id, pinned)}
        />
      ))}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Sidebar                                                            */
/* ------------------------------------------------------------------ */

export function ConversationSidebar({
  conversations,
  activeConversationId,
  onSelect,
  onNewConversation,
  onRename,
  onDelete,
  onPin,
  userEmail
}: ConversationSidebarProps) {
  const [search, setSearch] = useState("");

  const filtered = search
    ? conversations.filter((c) =>
        (c.title ?? "").toLowerCase().includes(search.toLowerCase())
      )
    : conversations;

  const groups = groupByDate(filtered);
  const initials = getInitials(userEmail);
  const displayName = userEmail?.split("@")[0] ?? "User";

  return (
    <aside
      style={{
        width: 260,
        flexShrink: 0,
        height: "100%",
        display: "flex",
        flexDirection: "column",
        background: "var(--bg-sidebar)",
        borderRight: "1px solid var(--border-subtle)",
        overflow: "hidden"
      }}
    >
      {/* Top row: New Chat + collapse */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: 16,
          flexShrink: 0
        }}
      >
        <button
          type="button"
          onClick={onNewConversation}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            border: "none",
            background: "none",
            padding: 0,
            fontSize: 15,
            fontWeight: 600,
            color: "var(--text-primary)",
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
            <path d="M12 5v14M5 12h14" />
          </svg>
          New Chat
        </button>
        <button
          type="button"
          aria-label="Collapse sidebar"
          style={{
            border: "none",
            background: "none",
            padding: 4,
            color: "var(--icon-default)",
            cursor: "pointer",
            lineHeight: 1,
            borderRadius: 8
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
            <rect x="3" y="3" width="18" height="18" rx="2" />
            <path d="M9 3v18" />
          </svg>
        </button>
      </div>

      {/* Search bar */}
      <div style={{ padding: "0 16px 12px", flexShrink: 0 }}>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            padding: "8px 12px",
            borderRadius: 8,
            background: "#E7E8E5"
          }}
        >
          <svg
            width="14"
            height="14"
            viewBox="0 0 24 24"
            fill="none"
            stroke="var(--icon-default)"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <circle cx="11" cy="11" r="8" />
            <path d="m21 21-4.3-4.3" />
          </svg>
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search chats..."
            style={{
              flex: 1,
              border: "none",
              background: "none",
              outline: "none",
              fontSize: 13,
              color: "var(--text-primary)"
            }}
          />
        </div>
      </div>

      {/* Chat list */}
      <div style={{ flex: 1, overflow: "auto", padding: "0 8px" }}>
        {conversations.length === 0 && !search ? (
          <p
            style={{
              padding: "0 8px",
              fontSize: 13,
              color: "var(--text-tertiary)",
              lineHeight: 1.6
            }}
          >
            No conversations yet. Start with a policy question.
          </p>
        ) : filtered.length === 0 ? (
          <p style={{ padding: "0 8px", fontSize: 13, color: "var(--text-tertiary)" }}>
            No results for &ldquo;{search}&rdquo;
          </p>
        ) : (
          <>
            <ChatGroup
              label="Pinned"
              items={groups.pinned}
              activeId={activeConversationId}
              onSelect={onSelect}
              onRename={onRename}
              onDelete={onDelete}
              onPin={onPin}
            />
            <ChatGroup
              label="Today"
              items={groups.today}
              activeId={activeConversationId}
              onSelect={onSelect}
              onRename={onRename}
              onDelete={onDelete}
              onPin={onPin}
            />
            <ChatGroup
              label="Yesterday"
              items={groups.yesterday}
              activeId={activeConversationId}
              onSelect={onSelect}
              onRename={onRename}
              onDelete={onDelete}
              onPin={onPin}
            />
            <ChatGroup
              label="Previous 7 Days"
              items={groups.week}
              activeId={activeConversationId}
              onSelect={onSelect}
              onRename={onRename}
              onDelete={onDelete}
              onPin={onPin}
            />
            <ChatGroup
              label="Older"
              items={groups.older}
              activeId={activeConversationId}
              onSelect={onSelect}
              onRename={onRename}
              onDelete={onDelete}
              onPin={onPin}
            />
          </>
        )}
      </div>

      {/* User profile row */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 10,
          padding: "12px 16px",
          flexShrink: 0,
          borderTop: "1px solid var(--border-subtle)"
        }}
      >
        <div
          style={{
            width: 32,
            height: 32,
            borderRadius: "50%",
            background: "var(--accent)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            flexShrink: 0
          }}
        >
          <span style={{ color: "var(--text-inverse)", fontSize: 11, fontWeight: 600 }}>
            {initials}
          </span>
        </div>
        <span
          style={{
            flex: 1,
            fontSize: 13,
            fontWeight: 500,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
            color: "var(--text-primary)"
          }}
        >
          {displayName}
        </span>
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
          <circle cx="12" cy="12" r="1" />
          <circle cx="19" cy="12" r="1" />
          <circle cx="5" cy="12" r="1" />
        </svg>
      </div>
    </aside>
  );
}
