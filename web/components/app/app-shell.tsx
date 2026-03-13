"use client";

import React from "react";
import type { ReactNode } from "react";
import { useRouter } from "next/navigation";
import { useTransition } from "react";

import { createBrowserSupabaseClient } from "@/lib/supabase/client";

type AppShellProps = {
  children: ReactNode;
  userEmail?: string | null;
  authClient?: {
    auth: {
      signOut(): Promise<{ error: { message: string } | null }>;
    };
  };
  navigate?: (path: string) => void;
};

export function AppShell({
  children,
  userEmail,
  authClient = createBrowserSupabaseClient(),
  navigate
}: AppShellProps) {
  const router = useRouter();
  const [isPending, startTransition] = useTransition();

  function handleSignOut() {
    startTransition(() => {
      void authClient.auth.signOut().finally(() => {
        if (navigate) {
          navigate("/auth");
          return;
        }
        router.replace("/auth");
        router.refresh();
      });
    });
  }

  return (
    <div
      style={{
        height: "100vh",
        display: "flex",
        flexDirection: "column",
        overflow: "hidden"
      }}
    >
      <header
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "0 20px",
          height: 52,
          flexShrink: 0,
          borderBottom: "1px solid var(--border-subtle)",
          background: "var(--bg-surface)"
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <span style={{ fontSize: 16, fontWeight: 600, color: "var(--text-primary)" }}>
            Polisi.ai
          </span>
          <span style={{ fontSize: 12, color: "var(--text-tertiary)" }}>
            Protected workspace for grounded Malaysian policy questions.
          </span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          {userEmail ? (
            <span style={{ fontSize: 13, color: "var(--text-tertiary)" }}>{userEmail}</span>
          ) : null}
          <button
            type="button"
            onClick={handleSignOut}
            disabled={isPending}
            style={{
              border: "1px solid var(--border-subtle)",
              borderRadius: 8,
              padding: "4px 12px",
              background: "transparent",
              fontSize: 13,
              color: "var(--text-secondary)",
              cursor: isPending ? "wait" : "pointer"
            }}
          >
            {isPending ? "Signing out…" : "Sign out"}
          </button>
        </div>
      </header>
      <main style={{ flex: 1, minHeight: 0, overflow: "hidden" }}>{children}</main>
    </div>
  );
}
