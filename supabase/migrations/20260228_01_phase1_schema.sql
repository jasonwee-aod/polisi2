-- Phase 1 schema foundation for corpus + chat persistence

create extension if not exists vector;
create extension if not exists pgcrypto;

create table if not exists public.documents (
  id uuid primary key default gen_random_uuid(),
  title text not null,
  source_url text not null,
  agency text not null,
  published_at date,
  file_type text not null,
  sha256 char(64) not null,
  storage_path text not null,
  chunk_index integer not null default 0,
  chunk_text text,
  embedding vector(3072),
  metadata jsonb not null default '{}'::jsonb,
  scraped_at timestamptz not null default timezone('utc', now()),
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now()),
  constraint documents_file_type_check
    check (file_type in ('html', 'pdf', 'docx', 'xlsx')),
  constraint documents_sha256_format_check
    check (sha256 ~ '^[0-9a-fA-F]{64}$'),
  constraint documents_source_sha_unique unique (source_url, sha256),
  constraint documents_storage_path_unique unique (storage_path)
);

create table if not exists public.conversations (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null,
  title text,
  language text,
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now()),
  constraint conversations_language_check
    check (language in ('ms', 'en') or language is null)
);

create table if not exists public.messages (
  id uuid primary key default gen_random_uuid(),
  conversation_id uuid not null references public.conversations(id) on delete cascade,
  role text not null,
  content text not null,
  language text,
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now()),
  constraint messages_role_check
    check (role in ('system', 'user', 'assistant')),
  constraint messages_language_check
    check (language in ('ms', 'en') or language is null)
);

create table if not exists public.citations (
  id uuid primary key default gen_random_uuid(),
  message_id uuid not null references public.messages(id) on delete cascade,
  document_id uuid references public.documents(id) on delete set null,
  citation_index integer not null,
  source_url text not null,
  title text,
  agency text,
  excerpt text,
  published_at date,
  created_at timestamptz not null default timezone('utc', now()),
  constraint citations_index_positive check (citation_index > 0)
);

create index if not exists documents_source_url_idx on public.documents (source_url);
create index if not exists documents_agency_idx on public.documents (agency);
create index if not exists documents_published_at_idx on public.documents (published_at);
create index if not exists documents_sha256_idx on public.documents (sha256);
create index if not exists documents_scraped_at_idx on public.documents (scraped_at desc);
create index if not exists documents_embedding_idx
  on public.documents using ivfflat (embedding vector_cosine_ops)
  with (lists = 100);

create index if not exists conversations_user_id_idx on public.conversations (user_id);
create index if not exists messages_conversation_id_idx on public.messages (conversation_id, created_at);
create index if not exists citations_message_id_idx on public.citations (message_id);
create index if not exists citations_document_id_idx on public.citations (document_id);

create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = timezone('utc', now());
  return new;
end;
$$;

drop trigger if exists set_documents_updated_at on public.documents;
create trigger set_documents_updated_at
before update on public.documents
for each row execute function public.set_updated_at();

drop trigger if exists set_conversations_updated_at on public.conversations;
create trigger set_conversations_updated_at
before update on public.conversations
for each row execute function public.set_updated_at();

drop trigger if exists set_messages_updated_at on public.messages;
create trigger set_messages_updated_at
before update on public.messages
for each row execute function public.set_updated_at();
