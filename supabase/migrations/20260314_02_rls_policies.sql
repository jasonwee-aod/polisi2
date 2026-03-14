-- Row Level Security for all public tables.
--
-- The backend API connects as postgres (superuser) or service_role,
-- both of which bypass RLS.  These policies protect against direct
-- Supabase client access (anon / authenticated roles) and serve as
-- defense-in-depth for user data isolation.

-- ============================================================
-- 1. Enable RLS on every table
-- ============================================================

alter table public.conversations enable row level security;
alter table public.messages      enable row level security;
alter table public.citations     enable row level security;
alter table public.documents     enable row level security;

-- ============================================================
-- 2. conversations — owned by user_id
-- ============================================================

create policy "conversations_select_own"
  on public.conversations for select
  to authenticated
  using (user_id = auth.uid());

create policy "conversations_insert_own"
  on public.conversations for insert
  to authenticated
  with check (user_id = auth.uid());

create policy "conversations_update_own"
  on public.conversations for update
  to authenticated
  using (user_id = auth.uid());

create policy "conversations_delete_own"
  on public.conversations for delete
  to authenticated
  using (user_id = auth.uid());

-- ============================================================
-- 3. messages — access through conversation ownership
-- ============================================================

create policy "messages_select_own"
  on public.messages for select
  to authenticated
  using (
    exists (
      select 1 from public.conversations c
      where c.id = messages.conversation_id
        and c.user_id = auth.uid()
    )
  );

create policy "messages_insert_own"
  on public.messages for insert
  to authenticated
  with check (
    exists (
      select 1 from public.conversations c
      where c.id = messages.conversation_id
        and c.user_id = auth.uid()
    )
  );

-- No update/delete for messages — immutable chat history.

-- ============================================================
-- 4. citations — access through message → conversation chain
-- ============================================================

create policy "citations_select_own"
  on public.citations for select
  to authenticated
  using (
    exists (
      select 1 from public.messages m
      join public.conversations c on c.id = m.conversation_id
      where m.id = citations.message_id
        and c.user_id = auth.uid()
    )
  );

-- Insert allowed for messages the user owns (backend uses service_role
-- so this is mainly for completeness).
create policy "citations_insert_own"
  on public.citations for insert
  to authenticated
  with check (
    exists (
      select 1 from public.messages m
      join public.conversations c on c.id = m.conversation_id
      where m.id = citations.message_id
        and c.user_id = auth.uid()
    )
  );

-- No update/delete for citations — immutable.

-- ============================================================
-- 5. documents — read-only for authenticated users
--    (indexer writes via service_role which bypasses RLS)
-- ============================================================

create policy "documents_select_authenticated"
  on public.documents for select
  to authenticated
  using (true);

-- No insert/update/delete policies for authenticated role.
-- Only service_role (indexer, scraper) can write documents.

-- ============================================================
-- 6. Grant table permissions to authenticated role
--    (Supabase sets these by default for new tables, but be
--     explicit for tables created before RLS was enabled.)
-- ============================================================

grant select, insert, update, delete
  on public.conversations to authenticated;

grant select, insert
  on public.messages to authenticated;

grant select, insert
  on public.citations to authenticated;

grant select
  on public.documents to authenticated;

-- Grant execute on search functions so authenticated users
-- can call them via Supabase RPC.
grant execute on function public.match_documents to authenticated;

-- When hybrid_match_documents is deployed, also grant:
-- grant execute on function public.hybrid_match_documents to authenticated;
