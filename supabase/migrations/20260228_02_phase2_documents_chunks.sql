-- Phase 2 chunk-row storage and vector retrieval support

alter table public.documents
  add column if not exists version_token text;

update public.documents
set version_token = sha256
where version_token is null;

alter table public.documents
  alter column version_token set not null;

alter table public.documents
  drop constraint if exists documents_source_sha_unique;

alter table public.documents
  drop constraint if exists documents_storage_path_unique;

create unique index if not exists documents_storage_version_chunk_unique
  on public.documents (storage_path, version_token, chunk_index);

create index if not exists documents_storage_version_idx
  on public.documents (storage_path, version_token);

drop function if exists public.match_documents(vector, integer, text);
create or replace function public.match_documents(
  query_embedding vector(3072),
  match_count integer default 5,
  filter_agency text default null
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
  similarity double precision
)
language sql
stable
as $$
  select
    documents.id,
    documents.title,
    documents.source_url,
    documents.agency,
    documents.storage_path,
    documents.version_token,
    documents.chunk_index,
    documents.chunk_text,
    documents.metadata,
    1 - (documents.embedding <=> query_embedding) as similarity
  from public.documents as documents
  where documents.embedding is not null
    and (filter_agency is null or documents.agency = filter_agency)
  order by documents.embedding <=> query_embedding
  limit greatest(match_count, 1);
$$;
