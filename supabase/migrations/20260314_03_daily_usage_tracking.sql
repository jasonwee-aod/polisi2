-- Daily usage tracking for per-user rate limiting.
-- Each row holds one user's aggregated usage for a single calendar day.
-- The primary key (user_id, usage_date) means an upsert is always safe.

create table if not exists public.daily_usage (
  user_id    uuid    not null,
  usage_date date    not null default current_date,
  request_count  integer not null default 0,
  tokens_budgeted integer not null default 0,
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now()),
  primary key (user_id, usage_date)
);

create index if not exists daily_usage_date_idx
  on public.daily_usage (usage_date);

-- Auto-update updated_at on change
drop trigger if exists set_daily_usage_updated_at on public.daily_usage;
create trigger set_daily_usage_updated_at
before update on public.daily_usage
for each row execute function public.set_updated_at();

-- Atomic check-and-increment function.
-- Returns the NEW totals after increment so the caller can decide
-- whether to proceed or reject.
create or replace function public.increment_daily_usage(
  p_user_id uuid,
  p_tokens  integer default 0
)
returns table (
  request_count  integer,
  tokens_budgeted integer
)
language sql
volatile
as $$
  insert into public.daily_usage (user_id, usage_date, request_count, tokens_budgeted)
  values (p_user_id, current_date, 1, p_tokens)
  on conflict (user_id, usage_date)
  do update set
    request_count   = daily_usage.request_count + 1,
    tokens_budgeted = daily_usage.tokens_budgeted + p_tokens
  returning daily_usage.request_count, daily_usage.tokens_budgeted;
$$;
