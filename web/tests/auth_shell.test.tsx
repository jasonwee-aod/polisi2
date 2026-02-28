import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import React from "react";
import { vi } from "vitest";

import { AppShell } from "@/components/app/app-shell";
import { AuthForm } from "@/components/auth/auth-form";
import { resolveRouteAccess } from "@/middleware";

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    replace: vi.fn(),
    refresh: vi.fn()
  })
}));

describe("auth shell", () => {
  it("submits sign up from the combined auth form", async () => {
    const navigate = vi.fn();
    const signUp = vi.fn().mockResolvedValue({ error: null });
    const signInWithPassword = vi.fn().mockResolvedValue({ error: null });

    render(
      <AuthForm
        authClient={{ auth: { signUp, signInWithPassword } }}
        navigate={navigate}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: /need an account\? sign up/i }));
    fireEvent.change(screen.getByLabelText(/email/i), {
      target: { value: "citizen@example.com" }
    });
    fireEvent.change(screen.getByLabelText(/password/i), {
      target: { value: "password123" }
    });
    fireEvent.click(screen.getByRole("button", { name: /create account/i }));

    await waitFor(() => {
      expect(signUp).toHaveBeenCalledWith({
        email: "citizen@example.com",
        password: "password123"
      });
      expect(navigate).toHaveBeenCalledWith("/chat");
    });
  });

  it("keeps unauthenticated traffic auth-first and redirects signed-in auth visits", () => {
    expect(resolveRouteAccess("/", false)).toEqual({
      action: "redirect",
      destination: "/auth?next=%2Fchat"
    });
    expect(resolveRouteAccess("/chat", false)).toEqual({
      action: "redirect",
      destination: "/auth?next=%2Fchat"
    });
    expect(resolveRouteAccess("/auth", true)).toEqual({
      action: "redirect",
      destination: "/chat"
    });
  });

  it("renders the minimal signed-in shell with BM guidance", () => {
    render(
      <AppShell
        userEmail="citizen@example.com"
        navigate={vi.fn()}
        authClient={{ auth: { signOut: vi.fn().mockResolvedValue({ error: null }) } }}
      >
        <p>Conversation area</p>
      </AppShell>
    );

    expect(screen.getByText(/protected workspace for grounded malaysian policy questions\./i)).toBeInTheDocument();
    expect(screen.getByText("Conversation area")).toBeInTheDocument();
    expect(screen.getByText("citizen@example.com")).toBeInTheDocument();
  });
});
