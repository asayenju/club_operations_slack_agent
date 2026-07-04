-- Migration: change filter_source (text) -> filter_sources (text[]) in match_documents RPC
-- Run once in Supabase SQL Editor (Database → SQL Editor).

CREATE OR REPLACE FUNCTION match_documents(
  query_embedding  vector(1024),
  match_count      int     DEFAULT 10,
  filter_workspace text    DEFAULT NULL,
  filter_sources   text[]  DEFAULT NULL
)
RETURNS TABLE (
  id           uuid,
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
LANGUAGE sql STABLE AS $$
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
