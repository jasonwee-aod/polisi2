-- Phase 3: Hybrid search — full-text (BM25-style) + vector with RRF fusion
-- and metadata filtering by agency / date range.

-- 1. Add tsvector column for full-text search
alter table public.documents
  add column if not exists fts tsvector;

-- 2. GIN index for fast full-text lookups
create index if not exists documents_fts_idx
  on public.documents using gin (fts);

-- 3. Backfill tsvector from existing rows.
--    Uses 'simple' config (tokenise + lowercase, no stemmer) because
--    Postgres has no built-in Malay stemmer and simple works well for
--    both BM and EN keyword matching.
update public.documents
set fts = to_tsvector('simple',
  coalesce(title, '') || ' ' ||
  coalesce(agency, '') || ' ' ||
  coalesce(chunk_text, ''))
where fts is null;

-- 4. Trigger: auto-populate fts on every insert / relevant update
create or replace function public.documents_fts_trigger()
returns trigger
language plpgsql
as $$
begin
  new.fts := to_tsvector('simple',
    coalesce(new.title, '') || ' ' ||
    coalesce(new.agency, '') || ' ' ||
    coalesce(new.chunk_text, '')
  );
  return new;
end;
$$;

drop trigger if exists documents_fts_update on public.documents;
create trigger documents_fts_update
before insert or update of title, agency, chunk_text
on public.documents
for each row execute function public.documents_fts_trigger();

-- 5. Hybrid match function: vector + full-text with Reciprocal Rank Fusion
--    Returns results ranked by RRF score so callers get a single ordered list.
drop function if exists public.hybrid_match_documents(vector(3072), text, integer, text, date, date, integer);

create or replace function public.hybrid_match_documents(
  query_embedding vector(3072),
  query_text text default '',
  match_count integer default 5,
  filter_agency text default null,
  filter_date_from date default null,
  filter_date_to date default null,
  rrf_k integer default 60
)
returns table (
  id uuid,
  title text,
  source_url text,
  agency text,
  storage_path text,
  version_token text,
  chunk_index integer,
  chunk_text text,
  metadata jsonb,
  similarity double precision,
  fts_rank real,
  rrf_score double precision
)
language sql
stable
as $$
  with
  -- Fetch more candidates than requested so RRF has enough to work with
  pool_size as (
    select greatest(match_count * 4, 20) as n
  ),

  -- Vector similarity ranking
  vector_ranked as (
    select
      d.id,
      d.title,
      d.source_url,
      d.agency,
      d.storage_path,
      d.version_token,
      d.chunk_index,
      d.chunk_text,
      d.metadata,
      1 - (d.embedding <=> query_embedding) as similarity,
      row_number() over (order by d.embedding <=> query_embedding) as vrank
    from public.documents d
    where d.embedding is not null
      and (filter_agency is null or d.agency = filter_agency)
      and (filter_date_from is null or d.published_at >= filter_date_from)
      and (filter_date_to is null or d.published_at <= filter_date_to)
    order by d.embedding <=> query_embedding
    limit (select n from pool_size)
  ),

  -- Full-text search ranking (skipped when query_text is empty)
  fts_query as (
    select plainto_tsquery('simple', query_text) as q
  ),
  fts_ranked as (
    select
      d.id,
      ts_rank_cd(d.fts, fq.q) as fts_rank,
      row_number() over (order by ts_rank_cd(d.fts, fq.q) desc) as frank
    from public.documents d, fts_query fq
    where d.fts is not null
      and query_text <> ''
      and d.fts @@ fq.q
      and (filter_agency is null or d.agency = filter_agency)
      and (filter_date_from is null or d.published_at >= filter_date_from)
      and (filter_date_to is null or d.published_at <= filter_date_to)
    order by ts_rank_cd(d.fts, fq.q) desc
    limit (select n from pool_size)
  ),

  -- RRF fusion: combine vector and FTS rankings
  combined as (
    -- Results that appeared in the vector search (with optional FTS boost)
    select
      v.id,
      v.title,
      v.source_url,
      v.agency,
      v.storage_path,
      v.version_token,
      v.chunk_index,
      v.chunk_text,
      v.metadata,
      v.similarity,
      coalesce(f.fts_rank, 0.0)::real as fts_rank,
      (1.0 / (rrf_k + v.vrank))
        + coalesce(1.0 / (rrf_k + f.frank), 0.0) as rrf_score
    from vector_ranked v
    left join fts_ranked f on f.id = v.id

    union all

    -- FTS-only results that vector search missed (exact keyword / acronym matches)
    select
      d.id,
      d.title,
      d.source_url,
      d.agency,
      d.storage_path,
      d.version_token,
      d.chunk_index,
      d.chunk_text,
      d.metadata,
      0.0 as similarity,
      f.fts_rank::real as fts_rank,
      (1.0 / (rrf_k + f.frank)) as rrf_score
    from fts_ranked f
    join public.documents d on d.id = f.id
    where not exists (select 1 from vector_ranked vr where vr.id = f.id)
  )

  select
    combined.id,
    combined.title,
    combined.source_url,
    combined.agency,
    combined.storage_path,
    combined.version_token,
    combined.chunk_index,
    combined.chunk_text,
    combined.metadata,
    combined.similarity,
    combined.fts_rank,
    combined.rrf_score
  from combined
  order by combined.rrf_score desc
  limit greatest(match_count, 1);
$$;
