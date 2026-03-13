"use client";

import React, { useState } from "react";

import { ConversationSummary } from "@/lib/api/client";

type ConversationSidebarProps = {
  conversations: ConversationSummary[];
  activeConversationId?: string | null;
  onSelect(conversationId: string): void;
  onNewConversation(): void;
  userEmail?: string | null;
};

function groupByDate(conversations: ConversationSummary[]) {
  const todayStart = new Date();
  todayStart.setHours(0, 0, 0, 0);
  const yesterdayStart = new Date(todayStart.getTime() - 86_400_000);
  const sevenDaysAgo = new Date(todayStart.getTime() - 7 * 86_400_000);

  const today: ConversationSummary[] = [];
  const yesterday: ConversationSummary[] = [];
  const week: ConversationSummary[] = [];
  const older: ConversationSummary[] = [];

  for (const c of conversations) {
    const d = new Date(c.updated_at);
    if (d >= todayStart) today.push(c);
    else if (d >= yesterdayStart) yesterday.push(c);
    else if (d >= sevenDaysAgo) week.push(c);
    else older.push(c);
  }
  return { today, yesterday, week, older };
}

function getInitials(email?: string | null): string {
  if (!email) return "?";
  const name = email.split("@")[0];
  const parts = name.split(/[._-]/);
  return parts.length >= 2
    ? (parts[0][0] + parts[1][0]).toUpperCase()
    : name.slice(0, 2).toUpperCase();
}

function ChatGroup({
  label,
  items,
  activeId,
  onSelect
}: {
  label: string;
  items: ConversationSummary[];
  activeId?: string | null;
  onSelect(id: string): void;
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
      {items.map((c) => {
        const isActive = c.id === activeId;
        return (
          <button
            key={c.id}
            type="button"
            onClick={() => onSelect(c.id)}
            style={{
              width: "100%",
              textAlign: "left",
              border: "none",
              borderRadius: 8,
              padding: "10px 12px",
              background: isActive ? "var(--bg-hover)" : "transparent",
              color: isActive ? "var(--text-primary)" : "var(--text-secondary)",
              fontSize: 13,
              fontWeight: isActive ? 500 : 400,
              cursor: "pointer",
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap"
            }}
          >
            {c.title ?? "Untitled conversation"}
          </button>
        );
      })}
    </div>
  );
}

export function ConversationSidebar({
  conversations,
  activeConversationId,
  onSelect,
  onNewConversation,
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
              label="Today"
              items={groups.today}
              activeId={activeConversationId}
              onSelect={onSelect}
            />
            <ChatGroup
              label="Yesterday"
              items={groups.yesterday}
              activeId={activeConversationId}
              onSelect={onSelect}
            />
            <ChatGroup
              label="Previous 7 Days"
              items={groups.week}
              activeId={activeConversationId}
              onSelect={onSelect}
            />
            <ChatGroup
              label="Older"
              items={groups.older}
              activeId={activeConversationId}
              onSelect={onSelect}
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
