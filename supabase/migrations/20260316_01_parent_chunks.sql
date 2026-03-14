-- Add parent_chunk_text column for Parent Document Retrieval (RAG best practice 2.2).
-- Each chunk stores its broader section context so the retrieval layer can
-- return the full section when a narrow chunk matches.

ALTER TABLE public.documents
  ADD COLUMN IF NOT EXISTS parent_chunk_text text;

-- Update hybrid_match_documents to also return parent_chunk_text
DROP FUNCTION IF EXISTS public.hybrid_match_documents(vector(3072), text, integer, text, date, date, integer);

CREATE OR REPLACE FUNCTION public.hybrid_match_documents(
  query_embedding vector(3072),
  query_text text DEFAULT '',
  match_count integer DEFAULT 5,
  filter_agency text DEFAULT null,
  filter_date_from date DEFAULT null,
  filter_date_to date DEFAULT null,
  rrf_k integer DEFAULT 60
)
RETURNS TABLE (
  id uuid,
  title text,
  source_url text,
  agency text,
  storage_path text,
  version_token text,
  chunk_index integer,
  chunk_text text,
  parent_chunk_text text,
  metadata jsonb,
  similarity double precision,
  fts_rank real,
  rrf_score double precision
)
LANGUAGE sql
STABLE
AS $$
  WITH
  pool_size AS (
    SELECT greatest(match_count * 4, 20) AS n
  ),

  vector_ranked AS (
    SELECT
      d.id,
      d.title,
      d.source_url,
      d.agency,
      d.storage_path,
      d.version_token,
      d.chunk_index,
      d.chunk_text,
      d.parent_chunk_text,
      d.metadata,
      1 - (d.embedding <=> query_embedding) AS similarity,
      row_number() OVER (ORDER BY d.embedding <=> query_embedding) AS vrank
    FROM public.documents d
    WHERE d.embedding IS NOT NULL
      AND (filter_agency IS NULL OR d.agency = filter_agency)
      AND (filter_date_from IS NULL OR d.published_at >= filter_date_from)
      AND (filter_date_to IS NULL OR d.published_at <= filter_date_to)
    ORDER BY d.embedding <=> query_embedding
    LIMIT (SELECT n FROM pool_size)
  ),

  fts_query AS (
    SELECT plainto_tsquery('simple', query_text) AS q
  ),
  fts_ranked AS (
    SELECT
      d.id,
      ts_rank_cd(d.fts, fq.q) AS fts_rank,
      row_number() OVER (ORDER BY ts_rank_cd(d.fts, fq.q) DESC) AS frank
    FROM public.documents d, fts_query fq
    WHERE d.fts IS NOT NULL
      AND query_text <> ''
      AND d.fts @@ fq.q
      AND (filter_agency IS NULL OR d.agency = filter_agency)
      AND (filter_date_from IS NULL OR d.published_at >= filter_date_from)
      AND (filter_date_to IS NULL OR d.published_at <= filter_date_to)
    ORDER BY ts_rank_cd(d.fts, fq.q) DESC
    LIMIT (SELECT n FROM pool_size)
  ),

  combined AS (
    SELECT
      v.id,
      v.title,
      v.source_url,
      v.agency,
      v.storage_path,
      v.version_token,
      v.chunk_index,
      v.chunk_text,
      v.parent_chunk_text,
      v.metadata,
      v.similarity,
      coalesce(f.fts_rank, 0.0)::real AS fts_rank,
      (1.0 / (rrf_k + v.vrank))
        + coalesce(1.0 / (rrf_k + f.frank), 0.0) AS rrf_score
    FROM vector_ranked v
    LEFT JOIN fts_ranked f ON f.id = v.id

    UNION ALL

    SELECT
      d.id,
      d.title,
      d.source_url,
      d.agency,
      d.storage_path,
      d.version_token,
      d.chunk_index,
      d.chunk_text,
      d.parent_chunk_text,
      d.metadata,
      0.0 AS similarity,
      f.fts_rank::real AS fts_rank,
      (1.0 / (rrf_k + f.frank)) AS rrf_score
    FROM fts_ranked f
    JOIN public.documents d ON d.id = f.id
    WHERE NOT EXISTS (SELECT 1 FROM vector_ranked vr WHERE vr.id = f.id)
  )

  SELECT
    combined.id,
    combined.title,
    combined.source_url,
    combined.agency,
    combined.storage_path,
    combined.version_token,
    combined.chunk_index,
    combined.chunk_text,
    combined.parent_chunk_text,
    combined.metadata,
    combined.similarity,
    combined.fts_rank,
    combined.rrf_score
  FROM combined
  ORDER BY combined.rrf_score DESC
  LIMIT greatest(match_count, 1);
$$;
