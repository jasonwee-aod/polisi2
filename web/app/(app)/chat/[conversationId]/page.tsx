import { ChatShell } from "@/components/chat/chat-shell";
import { createServerSupabaseClient } from "@/lib/supabase/server";

type ChatConversationPageProps = {
  params: Promise<{ conversationId: string }>;
};

export default async function ChatConversationPage({ params }: ChatConversationPageProps) {
  const supabase = createServerSupabaseClient();
  const {
    data: { session }
  } = await supabase.auth.getSession();
  const { conversationId } = await params;

  return (
    <ChatShell
      accessToken={session?.access_token ?? ""}
      initialConversationId={conversationId}
    />
  );
}
