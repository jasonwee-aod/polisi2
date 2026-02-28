import { redirect } from "next/navigation";

import { AuthForm } from "@/components/auth/auth-form";
import { createServerSupabaseClient } from "@/lib/supabase/server";

export default async function AuthPage() {
  const supabase = createServerSupabaseClient();
  const {
    data: { user }
  } = await supabase.auth.getUser();

  if (user) {
    redirect("/chat");
  }

  return (
    <div
      style={{
        minHeight: "100vh",
        display: "grid",
        placeItems: "center",
        padding: "2rem"
      }}
    >
      <div style={{ width: "min(100%, 28rem)", display: "grid", gap: "1.5rem" }}>
        <div style={{ display: "grid", gap: "0.5rem" }}>
          <span
            style={{
              textTransform: "uppercase",
              letterSpacing: "0.1em",
              fontWeight: 700,
              color: "#4f6a5f"
            }}
          >
            Auth
          </span>
          <p style={{ margin: 0, color: "#31443b", lineHeight: 1.6 }}>
            Sign in or create an account to ask Malaysian policy questions and keep your
            conversation history in one place.
          </p>
        </div>
        <AuthForm />
      </div>
    </div>
  );
}
