-- Extensions required by the platform.
-- Run once against a fresh database:
--   docker compose exec -T db psql -U app -d enterprise_ai -f /sql/00_extensions.sql
--
-- pgvector provides the `vector` column type and similarity operators used by
-- dense retrieval (<=> cosine distance). Business tables, document chunks and
-- the audit log all live in this same database — see docs/decisions.md ADR-001.

CREATE EXTENSION IF NOT EXISTS vector;

-- pg_trgm supports trigram similarity, used for fuzzy matching of product and
-- document codes alongside full-text search on the lexical retrieval side.
CREATE EXTENSION IF NOT EXISTS pg_trgm;
