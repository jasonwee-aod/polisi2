from __future__ import annotations

import pathlib


def test_documents_schema_supports_multiple_chunks_per_version() -> None:
    sql = pathlib.Path("supabase/migrations/20260228_02_phase2_documents_chunks.sql").read_text()

    assert "documents_storage_version_chunk_unique" in sql
    assert "version_token text" in sql
    assert "create or replace function public.match_documents" in sql
