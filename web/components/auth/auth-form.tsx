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
