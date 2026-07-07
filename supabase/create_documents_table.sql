-- Run this once in the Supabase SQL Editor (Database → SQL Editor).
-- This is the initial setup for the documents table used by all ingestion sources.

-- 1. Ensure pgvector extension is enabled (on by default for new Supabase projects)
CREATE EXTENSION IF NOT EXISTS vector;

-- 2. Create the documents table
CREATE TABLE IF NOT EXISTS documents (
  id            uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id  text        NOT NULL,
  source        text        NOT NULL,  -- 'slack_decide' | 'gdoc' | 'gsheet'
  source_id     text        NOT NULL,  -- document/channel/sheet ID
  chunk_key     text        NOT NULL,
  content       text        NOT NULL,
  content_hash  text        NOT NULL,
  author_id     text,                  -- populated for slack_decide
  channel_id    text,                  -- populated for slack_decide
  metadata      jsonb       NOT NULL DEFAULT '{}',
  embedding     vector(1024) NOT NULL,
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now(),

  CONSTRAINT documents_workspace_source_key UNIQUE (workspace_id, source, source_id, chunk_key)
);

-- 3. HNSW index for fast cosine-similarity search
CREATE INDEX IF NOT EXISTS documents_embedding_hnsw_idx
  ON documents USING hnsw (embedding vector_cosine_ops);

-- 4. Supporting indexes for filtered lookups
CREATE INDEX IF NOT EXISTS documents_workspace_source_idx
  ON documents (workspace_id, source);

-- 5. Similarity-search RPC (see also supabase/match_documents.sql for the standalone version)
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
