-- Iterative learning: user feedback on messages and automatic knowledge gap tracking.

-- 1. feedback — thumbs up/down on assistant messages
create table if not exists public.feedback (
  id uuid primary key default gen_random_uuid(),
  message_id uuid not null references public.messages(id) on delete cascade,
  user_id uuid not null,
  rating smallint not null,
  created_at timestamptz not null default timezone('utc', now()),
  constraint feedback_rating_check check (rating in (-1, 1)),
  constraint feedback_one_per_user_message unique (message_id, user_id)
);

create index if not exists feedback_message_id_idx on public.feedback (message_id);
create index if not exists feedback_user_id_idx on public.feedback (user_id);

-- 2. knowledge_gaps — questions the bot couldn't answer from indexed docs
create table if not exists public.knowledge_gaps (
  id uuid primary key default gen_random_uuid(),
  question text not null,
  language text,
  conversation_id uuid references public.conversations(id) on delete set null,
  gap_type text not null,
  top_similarity double precision,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default timezone('utc', now()),
  constraint knowledge_gaps_type_check
    check (gap_type in ('no_match', 'low_similarity', 'general_knowledge'))
);

create index if not exists knowledge_gaps_type_idx on public.knowledge_gaps (gap_type);
create index if not exists knowledge_gaps_created_idx on public.knowledge_gaps (created_at desc);

-- 3. Materialized view: aggregate feedback scores per document
--    Positive feedback on a citation → that document is useful for similar queries.
--    Refreshed periodically (e.g. daily cron) to avoid per-query overhead.
create materialized view if not exists public.document_feedback_scores as
select
  c.document_id,
  count(*) filter (where f.rating = 1) as positive_count,
  count(*) filter (where f.rating = -1) as negative_count,
  coalesce(sum(f.rating), 0) as net_score
from public.citations c
join public.feedback f on f.message_id = c.message_id
where c.document_id is not null
group by c.document_id;

create unique index if not exists document_feedback_scores_doc_idx
  on public.document_feedback_scores (document_id);

-- 4. Feedback-boosted match function: wraps hybrid_match_documents and
--    applies a small similarity bonus to documents with positive feedback.
create or replace function public.feedback_boosted_match(
  query_embedding vector(3072),
  query_text text default '',
  match_count integer default 5,
  filter_agency text default null,
  filter_date_from date default null,
  filter_date_to date default null,
  rrf_k integer default 60,
  feedback_boost double precision default 0.02
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
  select
    h.id,
    h.title,
    h.source_url,
    h.agency,
    h.storage_path,
    h.version_token,
    h.chunk_index,
    h.chunk_text,
    h.metadata,
    -- Boost similarity for documents with positive feedback
    h.similarity + (
      case when fs.net_score > 0
        then least(feedback_boost * ln(1 + fs.net_score), 0.10)
        else 0.0
      end
    ) as similarity,
    h.fts_rank,
    h.rrf_score + (
      case when fs.net_score > 0
        then least(feedback_boost * ln(1 + fs.net_score) / rrf_k, 0.005)
        else 0.0
      end
    ) as rrf_score
  from public.hybrid_match_documents(
    query_embedding, query_text, match_count * 2,
    filter_agency, filter_date_from, filter_date_to, rrf_k
  ) h
  left join public.document_feedback_scores fs on fs.document_id = h.id
  order by h.rrf_score + coalesce(
    case when fs.net_score > 0
      then least(feedback_boost * ln(1 + fs.net_score) / rrf_k, 0.005)
      else 0.0
    end, 0.0
  ) desc
  limit match_count;
$$;

-- 5. RLS for feedback and knowledge_gaps
alter table public.feedback enable row level security;
alter table public.knowledge_gaps enable row level security;

create policy "feedback_select_own"
  on public.feedback for select to authenticated
  using (user_id = auth.uid());

create policy "feedback_insert_own"
  on public.feedback for insert to authenticated
  with check (user_id = auth.uid());

create policy "feedback_update_own"
  on public.feedback for update to authenticated
  using (user_id = auth.uid());

-- knowledge_gaps: no direct user access (written by service role only)

grant select, insert, update on public.feedback to authenticated;
grant select on public.document_feedback_scores to authenticated;
