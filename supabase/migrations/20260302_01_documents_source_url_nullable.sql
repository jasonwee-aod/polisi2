-- Make source_url nullable in documents table.
-- The original schema defined it as text (nullable) but the live DB has a NOT NULL constraint.
alter table public.documents alter column source_url drop not null;
