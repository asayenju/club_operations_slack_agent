-- Two identical HNSW indexes exist on documents.embedding:
--   documents_embedding_idx
--   documents_embedding_hnsw_idx
-- Both are `hnsw (embedding extensions.vector_cosine_ops)` — redundant,
-- doubling index-maintenance cost on every insert/update with no query
-- benefit. Before running this, manually verify (e.g. via `select * from
-- pg_indexes where tablename = 'documents'` and checking query plans with
-- EXPLAIN on a typical similarity search) that dropping
-- documents_embedding_hnsw_idx specifically (not documents_embedding_idx)
-- is the one with no other dependents/usage. This is intentionally not
-- bundled into 0001 so it can be reviewed and run independently.

drop index if exists public.documents_embedding_hnsw_idx;
