-- Extensoes exigidas pelo alvo de producao. pgvector fica disponivel para o WP-11
-- (embeddings sao opcionais: a ontologia usa synonyms + rapidfuzz por decisao do CLAUDE.md).
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
