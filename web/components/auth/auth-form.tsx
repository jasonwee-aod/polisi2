"use client";

import { useRouter } from "next/navigation";
import React from "react";
import { CSSProperties, FormEvent, useState, useTransition } from "react";

import { createBrowserSupabaseClient } from "@/lib/supabase/client";

type AuthMode = "sign-in" | "sign-up";

type AuthClient = {
  auth: {
    signInWithPassword(input: { email: string; password: string }): Promise<{
      error: { message: string } | null;
    }>;
    signUp(input: { email: string; password: string }): Promise<{
      error: { message: string } | null;
    }>;
    signInWithOAuth(input: {
      provider: string;
      options?: { redirectTo?: string };
    }): Promise<{
      error: { message: string } | null;
    }>;
  };
};

type AuthFormProps = {
  initialMode?: AuthMode;
  authClient?: AuthClient;
  navigate?: (path: string) => void;
  nextPath?: string;
};

export function AuthForm({
  initialMode = "sign-in",
  authClient = createBrowserSupabaseClient(),
  navigate,
  nextPath = "/chat"
}: AuthFormProps) {
  const router = useRouter();
  const [mode, setMode] = useState<AuthMode>(initialMode);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formData = new FormData(event.currentTarget);
    const email = String(formData.get("email") ?? "").trim();
    const password = String(formData.get("password") ?? "");

    startTransition(() => {
      void submitCredentials(email, password);
    });
  }

  async function submitCredentials(email: string, password: string) {
    setErrorMessage(null);
    setSuccessMessage(null);

    const response =
      mode === "sign-up"
        ? await authClient.auth.signUp({ email, password })
        : await authClient.auth.signInWithPassword({ email, password });

    if (response.error) {
      setErrorMessage(response.error.message);
      return;
    }

    setSuccessMessage(
      mode === "sign-up"
        ? "Account created. Redirecting to your workspace."
        : "Signed in. Redirecting to your workspace."
    );

    if (navigate) {
      navigate(nextPath);
      return;
    }

    router.replace(nextPath);
    router.refresh();
  }

  async function handleGoogleSignIn() {
    setErrorMessage(null);
    setSuccessMessage(null);

    const redirectTo = `${window.location.origin}/auth/callback?next=${encodeURIComponent(nextPath)}`;
    const { error } = await authClient.auth.signInWithOAuth({
      provider: "google",
      options: { redirectTo },
    });

    if (error) {
      setErrorMessage(error.message);
    }
  }

  return (
      <form
        onSubmit={handleSubmit}
        style={{
          display: "grid",
          gap: "1rem",
          padding: "1.5rem",
          borderRadius: "1.5rem",
          border: "1px solid rgba(20, 35, 29, 0.12)",
          background: "rgba(255, 255, 255, 0.88)",
          boxShadow: "0 24px 80px rgba(20, 35, 29, 0.08)"
        }}
      >
        <div style={{ display: "grid", gap: "0.35rem" }}>
          <span
            style={{
              fontSize: "0.8rem",
              fontWeight: 700,
              letterSpacing: "0.08em",
              textTransform: "uppercase",
              color: "#4f6a5f"
            }}
          >
            {mode === "sign-up" ? "Create account" : "Welcome back"}
          </span>
          <h1 style={{ margin: 0, fontSize: "2rem" }}>
            {mode === "sign-up" ? "Start a cited policy thread." : "Continue your policy thread."}
          </h1>
        </div>

        <button
          type="button"
          onClick={() => { startTransition(() => { void handleGoogleSignIn(); }); }}
          disabled={isPending}
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            gap: "0.6rem",
            border: "1px solid rgba(20, 35, 29, 0.15)",
            borderRadius: "999px",
            padding: "0.9rem 1.1rem",
            background: "#fff",
            color: "#173a2a",
            fontWeight: 600,
            cursor: isPending ? "wait" : "pointer",
          }}
        >
          <svg width="18" height="18" viewBox="0 0 48 48" aria-hidden="true">
            <path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"/>
            <path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"/>
            <path fill="#FBBC05" d="M10.53 28.59a14.5 14.5 0 0 1 0-9.18l-7.98-6.19a24.02 24.02 0 0 0 0 21.56l7.98-6.19z"/>
            <path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"/>
          </svg>
          Continue with Google
        </button>

        <div style={{
          display: "flex",
          alignItems: "center",
          gap: "0.75rem",
          color: "#8a9e93",
          fontSize: "0.85rem",
        }}>
          <div style={{ flex: 1, height: "1px", background: "rgba(20, 35, 29, 0.1)" }} />
          or
          <div style={{ flex: 1, height: "1px", background: "rgba(20, 35, 29, 0.1)" }} />
        </div>

        <label style={{ display: "grid", gap: "0.35rem" }}>
          <span>Email</span>
          <input
            name="email"
            type="email"
            required
            placeholder="name@example.com"
            style={inputStyle}
          />
        </label>

        <label style={{ display: "grid", gap: "0.35rem" }}>
          <span>Password</span>
          <input
            name="password"
            type="password"
            required
            minLength={8}
            placeholder="Minimum 8 characters"
            style={inputStyle}
          />
        </label>

        {errorMessage ? (
          <p style={{ margin: 0, color: "#8b2d1b" }} role="alert">
            {errorMessage}
          </p>
        ) : null}
        {successMessage ? (
          <p style={{ margin: 0, color: "#25624a" }} role="status">
            {successMessage}
          </p>
        ) : null}

        <button
          type="submit"
          disabled={isPending}
          style={{
            border: 0,
            borderRadius: "999px",
            padding: "0.9rem 1.1rem",
            background: "#173a2a",
            color: "#f7fbf7",
            fontWeight: 700,
            cursor: isPending ? "wait" : "pointer"
          }}
        >
          {isPending
            ? "Working..."
            : mode === "sign-up"
              ? "Create account"
              : "Sign in"}
        </button>

        <button
          type="button"
          onClick={() => setMode(mode === "sign-up" ? "sign-in" : "sign-up")}
          style={{
            border: 0,
            background: "transparent",
            color: "#173a2a",
            padding: 0,
            textAlign: "left",
            cursor: "pointer"
          }}
        >
          {mode === "sign-up"
            ? "Already have an account? Sign in"
            : "Need an account? Sign up"}
        </button>
      </form>
  );
}

const inputStyle = {
  borderRadius: "1rem",
  border: "1px solid rgba(20, 35, 29, 0.15)",
  padding: "0.95rem 1rem",
  background: "#fbfcf8"
} satisfies CSSProperties;
