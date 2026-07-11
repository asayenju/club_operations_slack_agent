-- Migration: change filter_source (text) -> filter_sources (text[]) in match_documents RPC
-- Run once in Supabase SQL Editor (Database → SQL Editor).

-- PostgreSQL cannot change a function's OUT-row type with CREATE OR REPLACE,
-- and the old scalar filter_source overload otherwise remains visible to
-- PostgREST. Drop both signatures transactionally before recreating the one
-- canonical array-filter function.
DROP FUNCTION IF EXISTS public.match_documents(
  extensions.vector, integer, text, text
);
DROP FUNCTION IF EXISTS public.match_documents(
  extensions.vector, integer, text, text[]
);

CREATE OR REPLACE FUNCTION match_documents(
  query_embedding  extensions.vector(1024),
  match_count      int     DEFAULT 10,
  filter_workspace text    DEFAULT NULL,
  filter_sources   text[]  DEFAULT NULL
)
RETURNS TABLE (
  id           bigint,
  workspace_id text,
  source       text,
  source_id    text,
  chunk_key    text,
  content      text,
  author_id    text,
  channel_id   text,
  metadata     jsonb,
  similarity   float8
)
LANGUAGE sql STABLE
SET search_path = public, extensions
AS $$
  SELECT
    id,
    workspace_id,
    source,
    source_id,
    chunk_key,
    content,
    author_id,
    channel_id,
    metadata,
    1 - (embedding <=> query_embedding) AS similarity
  FROM documents
  WHERE
    (filter_workspace IS NULL OR workspace_id = filter_workspace)
    AND (filter_sources IS NULL OR source = ANY(filter_sources))
  ORDER BY embedding <=> query_embedding
  LIMIT match_count;
$$;
