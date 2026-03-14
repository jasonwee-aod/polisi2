"""Tests for data.gov.my integration — catalog, client, and chat enrichment."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from polisi_api.chat.datagov import (
    CATALOG,
    CATALOG_BY_ID,
    CatalogEntry,
    DataGovMyClient,
    build_metadata_text,
    build_tool_definition,
    execute_tool_call,
    find_catalog_match,
)
from polisi_api.chat.prompting import PromptPackage, build_prompt
from polisi_api.chat.retrieval import RetrievalFilters, RetrievedChunk
from polisi_api.chat.service import ChatService
from polisi_api.config import Settings


# ---------------------------------------------------------------------------
# Catalog tests
# ---------------------------------------------------------------------------


def test_catalog_has_entries() -> None:
    assert len(CATALOG) >= 5
    assert all(isinstance(e, CatalogEntry) for e in CATALOG)


def test_catalog_by_id_lookup() -> None:
    assert "fuelprice" in CATALOG_BY_ID
    entry = CATALOG_BY_ID["fuelprice"]
    assert entry.title_en == "Weekly Fuel Prices"
    assert entry.endpoint == "data-catalogue"


def test_build_metadata_text_contains_key_fields() -> None:
    entry = CATALOG_BY_ID["fuelprice"]
    text = build_metadata_text(entry)
    assert "fuelprice" in text
    assert "RON95" in text
    assert "weekly" in text
    assert "data-catalogue" in text


def test_find_catalog_match_returns_entry() -> None:
    metadata = {"datagov_dataset_id": "fuelprice", "source_type": "datagov_metadata"}
    entry = find_catalog_match(metadata)
    assert entry is not None
    assert entry.dataset_id == "fuelprice"


def test_find_catalog_match_returns_none_for_non_datagov() -> None:
    assert find_catalog_match({}) is None
    assert find_catalog_match({"source_type": "ckan_api"}) is None
    assert find_catalog_match({"datagov_dataset_id": "nonexistent"}) is None


# ---------------------------------------------------------------------------
# Client formatting tests
# ---------------------------------------------------------------------------


def test_format_rows_empty() -> None:
    client = DataGovMyClient()
    entry = CATALOG_BY_ID["fuelprice"]
    result = client.format_rows_for_context(entry, [])
    assert "No data returned" in result


def test_format_rows_with_data() -> None:
    client = DataGovMyClient()
    entry = CATALOG_BY_ID["fuelprice"]
    rows = [
        {"date": "2026-03-14", "ron95": "2.05", "ron97": "3.35", "diesel": "2.15"},
        {"date": "2026-03-07", "ron95": "2.05", "ron97": "3.35", "diesel": "2.15"},
    ]
    result = client.format_rows_for_context(entry, rows)
    assert "Live data from data.gov.my" in result
    assert "Weekly Fuel Prices" in result
    assert "2026-03-14" in result
    assert "ron95" in result
    assert "data.gov.my" in result


# ---------------------------------------------------------------------------
# Prompt integration tests
# ---------------------------------------------------------------------------


def test_build_prompt_with_live_data_no_docs() -> None:
    prompt = build_prompt(
        question="What is the latest fuel price?",
        language="en",
        contexts=[],
        support_mode="none",
        live_data_blocks=["Live data: RON95 = RM 2.05"],
    )
    assert "live government data" in prompt.system.lower() or "data.gov.my" in prompt.system.lower()
    assert "Live data" in prompt.user
    assert "RON95" in prompt.user


def test_build_prompt_with_live_data_and_docs() -> None:
    chunk = RetrievedChunk(
        document_id="00000000-0000-0000-0000-000000000001",
        title="Fuel Policy",
        agency="MOF",
        source_url="https://example.gov",
        chunk_text="The government sets fuel prices weekly.",
        similarity=0.85,
        chunk_index=0,
    )
    prompt = build_prompt(
        question="What is the latest fuel price?",
        language="en",
        contexts=[chunk],
        support_mode="strong",
        live_data_blocks=["Live data: RON95 = RM 2.05"],
    )
    assert "Fuel Policy" in prompt.user
    assert "Live data" in prompt.user
    assert "data.gov.my" in prompt.system


def test_build_prompt_without_live_data_unchanged() -> None:
    """Existing behavior should be unchanged when no live data."""
    prompt = build_prompt(
        question="What is education policy?",
        language="en",
        contexts=[],
        support_mode="none",
    )
    assert "data.gov.my" not in prompt.system
    assert "Live data" not in prompt.user


# ---------------------------------------------------------------------------
# ChatService integration test with datagov enrichment
# ---------------------------------------------------------------------------


@dataclass
class FakeRetriever:
    responses: dict[str, list[RetrievedChunk]]

    async def retrieve(
        self,
        question: str,
        *,
        limit: int,
        filters: RetrievalFilters | None = None,
    ) -> list[RetrievedChunk]:
        return self.responses.get(question, [])[:limit]


@dataclass
class FakeGenerator:
    async def generate(self, prompt: PromptPackage) -> str:
        if "Live data from data.gov.my" in prompt.user:
            return "Based on the latest data from data.gov.my, RON95 is RM 2.05 [data.gov.my]."
        return "General answer."


@dataclass
class FakeDataGovClient:
    """Returns canned data for any fetch_dataset call."""
    rows: list[dict]

    async def fetch_dataset(self, entry, **kwargs) -> list[dict]:
        return self.rows

    def format_rows_for_context(self, entry, rows) -> str:
        if not rows:
            return "[No data]"
        return f"Live data from data.gov.my — {entry.title_en}: {rows}"


def _build_settings() -> Settings:
    return Settings.from_env(
        {
            "SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_DB_URL": "postgresql://postgres:postgres@localhost:5432/postgres",
            "SUPABASE_JWT_SECRET": "test-secret",
            "ANTHROPIC_API_KEY": "test-key",
            "OPENAI_API_KEY": "test-openai-key",
        }
    )


def test_chat_service_enriches_with_live_data_when_metadata_matches() -> None:
    asyncio.run(_run_datagov_enrichment())


async def _run_datagov_enrichment() -> None:
    question = "What is the current fuel price in Malaysia?"

    # Retrieval returns a datagov metadata chunk (high similarity)
    metadata_chunk = RetrievedChunk(
        document_id="00000000-0000-0000-0000-000000000002",
        title="Weekly Fuel Prices",
        agency="data.gov.my",
        source_url="https://data.gov.my/data-catalogue/fuelprice",
        chunk_text="Weekly retail fuel prices in Malaysia for RON95, RON97, and diesel.",
        similarity=0.88,
        chunk_index=0,
        metadata={"datagov_dataset_id": "fuelprice", "source_type": "datagov_metadata"},
    )
    retriever = FakeRetriever(responses={question: [metadata_chunk]})

    fake_datagov = FakeDataGovClient(
        rows=[{"date": "2026-03-14", "ron95": "2.05", "ron97": "3.35", "diesel": "2.15"}]
    )
    service = ChatService(
        settings=_build_settings(),
        retriever=retriever,
        generator=FakeGenerator(),
        datagov_client=fake_datagov,
    )

    reply = await service.generate_reply(question=question)

    assert reply.kind == "answer"
    assert "data.gov.my" in reply.response.answer
    # Should have citations for both the metadata chunk and the live data source
    agencies = [c.agency for c in reply.response.citations]
    assert "data.gov.my" in agencies


def test_chat_service_no_datagov_when_no_metadata_match() -> None:
    asyncio.run(_run_no_datagov_match())


async def _run_no_datagov_match() -> None:
    question = "What education subsidies exist?"

    # Normal document chunk, no datagov metadata
    doc_chunk = RetrievedChunk(
        document_id="00000000-0000-0000-0000-000000000003",
        title="Education Policy",
        agency="MOE",
        source_url="https://moe.gov.my/policy",
        chunk_text="Education subsidies are available through PTPTN.",
        similarity=0.80,
        chunk_index=0,
        metadata={"source_type": "scraper"},
    )
    retriever = FakeRetriever(responses={question: [doc_chunk]})
    fake_datagov = FakeDataGovClient(rows=[])

    service = ChatService(
        settings=_build_settings(),
        retriever=retriever,
        generator=FakeGenerator(),
        datagov_client=fake_datagov,
    )

    reply = await service.generate_reply(question=question)

    assert reply.kind == "answer"
    # No data.gov.my citations since no metadata matched
    datagov_citations = [c for c in reply.response.citations if c.agency == "data.gov.my"]
    assert len(datagov_citations) == 0


# ---------------------------------------------------------------------------
# Tool definition and execution tests
# ---------------------------------------------------------------------------


def test_tool_definition_structure() -> None:
    tool = build_tool_definition()
    assert tool["name"] == "query_government_data"
    schema = tool["input_schema"]
    assert "dataset_id" in schema["properties"]
    assert schema["properties"]["dataset_id"]["type"] == "string"
    assert "fuelprice" in schema["properties"]["dataset_id"]["enum"]
    assert "dataset_id" in schema["required"]


def test_execute_tool_call_unknown_dataset() -> None:
    asyncio.run(_run_execute_unknown())


async def _run_execute_unknown() -> None:
    client = DataGovMyClient()
    result = await execute_tool_call(client, {"dataset_id": "nonexistent"})
    assert "Unknown dataset" in result
    assert "fuelprice" in result  # lists available datasets
