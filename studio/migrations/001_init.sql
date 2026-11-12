-- DocQABot Studio tables (DESIGN 5.2). Forward-only; never edit after release.

CREATE TABLE IF NOT EXISTS studio_schema_migrations (
    version    TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS studio_document_meta (
    document_id  INTEGER PRIMARY KEY REFERENCES documents(id) ON DELETE CASCADE,
    size_bytes   BIGINT NOT NULL,
    content_type TEXT,
    error_code   TEXT,
    processed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS studio_conversations (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title      TEXT NOT NULL DEFAULT 'New conversation',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS studio_conversations_updated_idx
    ON studio_conversations (updated_at DESC);

CREATE TABLE IF NOT EXISTS studio_messages (
    id              BIGSERIAL PRIMARY KEY,
    conversation_id UUID NOT NULL REFERENCES studio_conversations(id) ON DELETE CASCADE,
    role            TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content         TEXT NOT NULL,
    grounded        BOOLEAN,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS studio_messages_conversation_idx
    ON studio_messages (conversation_id, id);

CREATE TABLE IF NOT EXISTS studio_citations (
    id          BIGSERIAL PRIMARY KEY,
    message_id  BIGINT NOT NULL REFERENCES studio_messages(id) ON DELETE CASCADE,
    rank        SMALLINT NOT NULL,
    document_id INTEGER REFERENCES documents(id) ON DELETE SET NULL,
    filename    TEXT NOT NULL,
    chunk_index INTEGER,
    similarity  REAL NOT NULL,
    content     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS studio_citations_message_idx
    ON studio_citations (message_id, rank);
