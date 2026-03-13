-- Make source_url nullable in citations table.
-- Documents scraped without a public URL (e.g. local PDF ingestion) have no
-- source_url, so the corresponding citations must also allow NULL.
alter table public.citations alter column source_url drop not null;
