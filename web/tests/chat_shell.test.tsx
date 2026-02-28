import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import React from "react";
import { vi } from "vitest";

import { ChatShell } from "@/components/chat/chat-shell";
import { ConversationDetail, ConversationSummary } from "@/lib/api/client";

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn()
  })
}));

const conversations: ConversationSummary[] = [
  {
    id: "conv-new",
    title: "Childcare subsidies",
    language: "en",
    created_at: "2026-02-28T14:00:00Z",
    updated_at: "2026-02-28T14:05:00Z",
    message_count: 2
  },
  {
    id: "conv-old",
    title: "Bantuan pendidikan",
    language: "ms",
    created_at: "2026-02-27T14:00:00Z",
    updated_at: "2026-02-27T14:05:00Z",
    message_count: 4
  }
];

const conversationDetail: ConversationDetail = {
  id: "conv-new",
  title: "Childcare subsidies",
  language: "en",
  created_at: "2026-02-28T14:00:00Z",
  updated_at: "2026-02-28T14:05:00Z",
  messages: [
    {
      id: "m1",
      role: "user",
      content: "What childcare subsidies are available?",
      language: "en",
      created_at: "2026-02-28T14:00:00Z",
      citations: []
    },
    {
      id: "m2",
      role: "assistant",
      content: "Working parents may qualify for childcare subsidies [1].",
      language: "en",
      created_at: "2026-02-28T14:00:02Z",
      citations: [
        {
          index: 1,
          title: "Childcare Support",
          agency: "KPWKM",
          source_url: "https://gov.example/childcare",
          excerpt: "Working parents may qualify for childcare subsidies.",
          document_id: null
        }
      ]
    }
  ]
};

describe("chat shell", () => {
  it("streams answers and opens the citation panel", async () => {
    const navigate = vi.fn();
    const streamChat = vi.fn().mockImplementation(async ({ onEvent }) => {
      onEvent({ event: "conversation", conversation_id: "conv-new", message_id: "msg-2" });
      onEvent({ event: "message-start", conversation_id: "conv-new", message_id: "msg-2" });
      onEvent({ event: "message-delta", delta: "Working parents may qualify " });
      onEvent({ event: "message-delta", delta: "for childcare subsidies [1]." });
      onEvent({
        event: "message-complete",
        response: {
          conversation_id: "conv-new",
          message_id: "msg-2",
          language: "en",
          answer: "Working parents may qualify for childcare subsidies [1].",
          kind: "answer",
          citations: [
            {
              index: 1,
              title: "Childcare Support",
              agency: "KPWKM",
              source_url: "https://gov.example/childcare",
              excerpt: "Working parents may qualify for childcare subsidies."
            }
          ]
        }
      });
      onEvent({ event: "done" });
    });

    render(
      <ChatShell
        accessToken="token"
        navigate={navigate}
        apiClient={{
          fetchConversations: vi.fn().mockResolvedValue(conversations),
          fetchConversationDetail: vi.fn().mockResolvedValue(conversationDetail)
        }}
        streamChat={streamChat}
      />
    );

    fireEvent.change(screen.getByLabelText(/question/i), {
      target: { value: "What childcare subsidies are available?" }
    });
    fireEvent.click(screen.getByRole("button", { name: /^ask$/i }));

    await waitFor(() => {
      expect(screen.getByText(/working parents may qualify for childcare subsidies/i)).toBeInTheDocument();
      expect(navigate).toHaveBeenCalledWith("/chat/conv-new");
    });

    fireEvent.click(screen.getByRole("button", { name: /citation 1/i }));

    expect(screen.getByText("Childcare Support")).toBeInTheDocument();
    expect(screen.getByText("Source [1]")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /open original source/i })).toHaveAttribute(
      "href",
      "https://gov.example/childcare"
    );
  });

  it("loads an existing conversation and keeps the sidebar recent-first", async () => {
    const fetchConversationDetail = vi.fn().mockResolvedValue(conversationDetail);

    render(
      <ChatShell
        accessToken="token"
        initialConversationId="conv-new"
        apiClient={{
          fetchConversations: vi.fn().mockResolvedValue(conversations),
          fetchConversationDetail
        }}
        streamChat={vi.fn().mockResolvedValue(undefined)}
      />
    );

    await waitFor(() => {
      expect(fetchConversationDetail).toHaveBeenCalledWith("conv-new", {
        accessToken: "token",
        apiBaseUrl: undefined
      });
      expect(screen.getByText("Childcare subsidies")).toBeInTheDocument();
      expect(screen.getByText("Bantuan pendidikan")).toBeInTheDocument();
    });
  });

  it("keeps empty, clarification, weak-support, and no-information states in the thread", async () => {
    render(
      <ChatShell
        accessToken="token"
        apiClient={{
          fetchConversations: vi.fn().mockResolvedValue([]),
          fetchConversationDetail: vi.fn().mockResolvedValue({
            ...conversationDetail,
            messages: [
              {
                id: "a1",
                role: "assistant",
                content:
                  "Could you narrow this to a specific policy, benefit, or government agency first?",
                language: "en",
                created_at: "2026-02-28T14:00:00Z",
                citations: []
              },
              {
                id: "a2",
                role: "assistant",
                content:
                  "The retrieved document support is limited, so this answer relies on the available excerpts:\n\nPartial support [1].",
                language: "en",
                created_at: "2026-02-28T14:00:02Z",
                citations: []
              },
              {
                id: "a3",
                role: "assistant",
                content:
                  "I could not find enough support in the indexed government documents to answer this safely.",
                language: "en",
                created_at: "2026-02-28T14:00:04Z",
                citations: []
              }
            ]
          })
        }}
        initialConversationId="conv-new"
        streamChat={vi.fn().mockResolvedValue(undefined)}
      />
    );

    await waitFor(() => {
      expect(screen.getByText(/specific policy, benefit, or government agency/i)).toBeInTheDocument();
      expect(screen.getByText(/clarification requested/i)).toBeInTheDocument();
      expect(screen.getByText(/document support is limited/i)).toBeInTheDocument();
      expect(screen.getByText(/limited support/i)).toBeInTheDocument();
      expect(screen.getByText(/could not find enough support/i)).toBeInTheDocument();
      expect(screen.getByText(/no indexed support/i)).toBeInTheDocument();
    });
  });
});
