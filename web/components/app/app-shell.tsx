"use client";

import { useRouter } from "next/navigation";
import React from "react";
import type { ReactNode } from "react";
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
        minHeight: "100vh",
        padding: "2rem",
        display: "grid",
        gap: "1.5rem"
      }}
    >
      <header
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          gap: "1rem",
          padding: "1rem 1.25rem",
          borderRadius: "1.5rem",
          background: "rgba(255, 255, 255, 0.78)",
          border: "1px solid rgba(20, 35, 29, 0.08)"
        }}
      >
        <div style={{ display: "grid", gap: "0.15rem" }}>
          <strong style={{ fontSize: "1.1rem" }}>Polisi</strong>
          <span style={{ color: "#4f6a5f", fontSize: "0.95rem" }}>
            Ask in BM or English. Answers stay grounded to government documents.
          </span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
          <span style={{ color: "#4f6a5f", fontSize: "0.95rem" }}>
            {userEmail ?? "Signed in"}
          </span>
          <button
            type="button"
            onClick={handleSignOut}
            disabled={isPending}
            style={{
              borderRadius: "999px",
              border: "1px solid rgba(20, 35, 29, 0.15)",
              background: "#f6f7f1",
              padding: "0.65rem 0.95rem",
              cursor: isPending ? "wait" : "pointer"
            }}
          >
            {isPending ? "Signing out..." : "Sign out"}
          </button>
        </div>
      </header>

      <main
        style={{
          display: "grid",
          placeItems: "center",
          padding: "2rem",
          borderRadius: "2rem",
          background: "rgba(255, 255, 255, 0.72)",
          border: "1px solid rgba(20, 35, 29, 0.08)"
        }}
      >
        {children}
      </main>
    </div>
  );
}
