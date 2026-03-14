"""Bilingual query expansion for improved retrieval coverage."""

from __future__ import annotations

from anthropic import AsyncAnthropic


async def expand_query(
    question: str,
    language: str,
    client: AsyncAnthropic,
    model: str,
) -> list[str]:
    """Generate expanded queries: original + translation + rephrase.

    Returns the original question plus up to 2 expansions.
    Falls back to [question] on any error.
    """
    other_language = "English" if language == "ms" else "Bahasa Malaysia"

    prompt = (
        "Generate 2 alternative search queries for retrieving Malaysian government documents.\n"
        f"Query 1: translate to {other_language}.\n"
        "Query 2: rephrase with more specific terms.\n"
        "Return each on its own line. No numbering, no explanation — just the queries."
    )

    try:
        response = await client.messages.create(
            model=model,
            max_tokens=200,
            system="You are a search query expansion assistant for Malaysian government documents.",
            messages=[
                {"role": "user", "content": f"Original query: {question}\n\n{prompt}"},
            ],
        )

        text = ""
        for block in response.content:
            if getattr(block, "type", None) == "text":
                text += block.text

        lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
        expansions = lines[:2]  # Take at most 2 expansions

        result = [question]
        for expansion in expansions:
            if expansion and expansion != question:
                result.append(expansion)
        return result

    except Exception:
        return [question]
