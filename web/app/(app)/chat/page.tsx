import { ChatShell } from "@/components/chat/chat-shell";
import { createServerSupabaseClient } from "@/lib/supabase/server";

export default async function ChatPage() {
  const supabase = await createServerSupabaseClient();
  const {
    data: { session }
  } = await supabase.auth.getSession();

  return (
    <ChatShell
      accessToken={session?.access_token ?? ""}
      userEmail={session?.user?.email}
    />
  );
}
