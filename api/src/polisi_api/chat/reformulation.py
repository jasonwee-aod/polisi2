"""Conversation-aware query reformulation."""

from __future__ import annotations

from anthropic import AsyncAnthropic


async def reformulate_with_history(
    question: str,
    history: list[tuple[str, str]],
    client: AsyncAnthropic,
    model: str,
) -> str:
    """Rewrite a question as a standalone query using conversation history.

    *history* is a list of (role, content) pairs, most recent last.
    Returns the reformulated query, or the original question on failure.
    """
    if not history:
        return question

    history_block = "\n".join(
        f"{role.upper()}: {content}" for role, content in history
    )

    prompt = (
        "Given the conversation history and the latest question, rewrite the latest "
        "question as a standalone query for document retrieval. Resolve pronouns and "
        "references. Return only the reformulated query — no explanation.\n\n"
        f"Conversation history:\n{history_block}\n\n"
        f"Latest question: {question}"
    )

    try:
        response = await client.messages.create(
            model=model,
            max_tokens=200,
            system="You are a query reformulation assistant. Return only the rewritten query.",
            messages=[{"role": "user", "content": prompt}],
        )

        text = ""
        for block in response.content:
            if getattr(block, "type", None) == "text":
                text += block.text

        reformulated = text.strip()
        return reformulated if reformulated else question

    except Exception:
        return question
