# Phase 3: Product - Context

**Gathered:** 2026-02-28
**Status:** Ready for planning

<domain>
## Phase Boundary

Deliver the end-user product: a logged-in web app where a user can ask a Malaysian policy question in Bahasa Malaysia or English, receive an answer grounded in indexed government documents with citations, and return to past conversations with full history. This phase covers the RAG API behavior and the Next.js chat experience within the existing government-document corpus.

</domain>

<decisions>
## Implementation Decisions

### Answer and citation experience
- Answers should use a formal government-brief style rather than a casual chat tone.
- Citation markers should appear inline immediately after the specific supported claim.
- Clicking a citation should open a side panel inside the app showing source details, with a link to open the original document in a new tab.
- Citation presentation should emphasize the document title or agency rather than exposing raw URLs as the main label.

### Conversation history and session flow
- Match the familiar ChatGPT/Claude chat pattern to reduce learning friction.
- New conversations should be titled automatically from the first user question, with manual rename available later.
- A new conversation starts only when the user explicitly creates one or opens a fresh browser session/window.
- Reopening a past conversation should load the full message history and continue in the same thread.
- Sidebar ordering should prioritize the most recent conversations first.

### Login and first-run experience
- Unauthenticated users should hit auth first rather than seeing a usable chat screen before logging in.
- Use a single combined authentication screen for sign up and log in.
- After successful sign up, drop the user directly into a new empty chat.
- Keep the first-run empty state minimal, with a hint that BM queries are supported.

### No-answer, loading, and confidence states
- Answers should stream progressively while generating.
- If a question is too broad or ambiguous, the product should ask a clarifying follow-up instead of forcing an answer immediately.
- Confidence should be communicated through subtle wording rather than explicit scores or badges.
- When retrieval support is weak, the system should still provide a best-effort answer grounded only in the indexed government corpus, with clear wording that support is limited.

### Claude's Discretion
- Exact layout, spacing, and styling of the chat interface and citation side panel.
- Specific copy for loading, weak-support, and clarifying-question states, as long as it stays formal and subtle.
- Exact metadata fields shown in the citation side panel beyond prioritizing document title or agency.

</decisions>

<specifics>
## Specific Ideas

- "Replicate normal AI chat user experience that encourages familiarity."
- Sidebar and chat flow should feel familiar to users of ChatGPT or Claude.
- Keep the initial experience minimal rather than adding onboarding steps or heavy explanation.

</specifics>

<deferred>
## Deferred Ideas

- Open-web fallback when the government document corpus cannot support an answer. This is a separate future capability and not part of Phase 3.

</deferred>

---

*Phase: 03-product*
*Context gathered: 2026-02-28*
