-- SaaS customer-management API - PostgreSQL 16
-- App stack: python 3.12 / fastapi 0.115 / fastjwt 2.3.1 / sqlalchemy 2.0
-- Dependency versions pinned in requirements.txt, mirrored here for ops.

CREATE TABLE customers (
    id            BIGSERIAL PRIMARY KEY,
    email         TEXT NOT NULL UNIQUE,
    full_name     TEXT NOT NULL,
    phone         TEXT,
    address       TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE users (
    id            BIGSERIAL PRIMARY KEY,
    username      TEXT NOT NULL UNIQUE,
    kind          TEXT NOT NULL CHECK (kind IN ('staff', 'service')),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE api_tokens (
    id            BIGSERIAL PRIMARY KEY,
    user_id       BIGINT NOT NULL REFERENCES users(id),
    token_hash    TEXT NOT NULL,
    scopes        TEXT NOT NULL,
    expires_at    TIMESTAMPTZ
);

CREATE TABLE audit_log (
    id            BIGSERIAL PRIMARY KEY,
    user_id       BIGINT REFERENCES users(id),
    action        TEXT NOT NULL,
    target        TEXT,
    at            TIMESTAMPTZ NOT NULL DEFAULT now()
);
