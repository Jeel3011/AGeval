-- ============================================================
-- episodic pipeline — Supabase schema  (v2 — safe to re-run)
-- Run this in Supabase SQL editor (or via migration tool).
--
-- This file is idempotent:
--   • CREATE TABLE IF NOT EXISTS   → skips if table already exists
--   • ALTER TABLE  ADD COLUMN IF NOT EXISTS → skips if column exists
--   • CREATE OR REPLACE FUNCTION   → always updates the function
--   • CREATE INDEX IF NOT EXISTS   → skips if index exists
-- ============================================================

-- Enable pgvector (if not already enabled)
create extension if not exists vector;


-- ============================================================
-- MIGRATION — patch columns on already-existing tables
-- Safe no-ops when the column already exists.
-- ============================================================

-- episodes: add user_id if missing
alter table if exists episodes
    add column if not exists user_id text;

-- episode_jobs: add user_id if missing
alter table if exists episode_jobs
    add column if not exists user_id text;

-- Drop the old trigger first so we can recreate it cleanly
-- (CREATE OR REPLACE doesn't work for triggers, only for functions)
drop trigger if exists episode_jobs_updated_at on episode_jobs;

-- Drop functions before recreating — CREATE OR REPLACE cannot change return type
drop function if exists pick_next_job();
drop function if exists match_episodes(vector, int, text);


-- ============================================================
-- api_keys
-- Stores hashed API keys for SDK authentication.
-- Raw key is NEVER stored — only the sha256 hash.
-- ============================================================
create table if not exists api_keys (
    id          uuid        primary key default gen_random_uuid(),
    key_hash    text        not null unique,
    user_id     text        not null,
    label       text        not null default '',
    is_active   boolean     not null default true,
    created_at  timestamptz not null default now()
);

create index if not exists idx_api_keys_hash
    on api_keys (key_hash);


-- ============================================================
-- episode_jobs
-- The queue. One row per agent run. Merger polls this table.
-- ============================================================
create table if not exists episode_jobs (
    id              uuid        primary key default gen_random_uuid(),
    episode_id      text        not null unique,
    run_id          text        not null,           -- LangSmith run ID
    agent_id        text        not null,
    user_id         text,                           -- scoped per user
    task            text,                           -- human-readable task description
    status          text        not null default 'pending'
                                check (status in ('pending','processing','done','failed')),
    retry_count     int         not null default 0,
    locked_at       timestamptz,                    -- set when worker picks it up
    error_message   text,
    created_at      timestamptz not null default now(),
    updated_at      timestamptz not null default now()
);

-- Index for the poll query: SELECT FOR UPDATE SKIP LOCKED WHERE status='pending'
create index if not exists idx_episode_jobs_status
    on episode_jobs (status, created_at);

create index if not exists idx_episode_jobs_user
    on episode_jobs (user_id, created_at);

-- Auto-update updated_at
create or replace function set_updated_at()
returns trigger language plpgsql as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

create trigger episode_jobs_updated_at
    before update on episode_jobs
    for each row execute procedure set_updated_at();


-- ============================================================
-- episodes
-- One row per completed agent run (written by merger).
-- ============================================================
create table if not exists episodes (
    id              uuid        primary key default gen_random_uuid(),
    episode_id      text        not null unique,
    agent_id        text        not null,
    user_id         text,                           -- scoped per user
    run_id          text        not null,
    task            text,
    outcome         text,                           -- 'success' | 'failure' | 'partial'
    total_steps     int,
    total_latency_ms int,
    created_at      timestamptz not null default now()
);

create index if not exists idx_episodes_agent
    on episodes (agent_id, created_at desc);

create index if not exists idx_episodes_user
    on episodes (user_id, created_at desc);


-- ============================================================
-- episode_steps
-- One row per tool call. Written by the SDK immediately.
-- Merger reads these; it does NOT re-derive them from LangSmith.
-- ============================================================
create table if not exists episode_steps (
    id              uuid        primary key default gen_random_uuid(),
    episode_id      text        not null references episodes(episode_id) on delete cascade,
    step_index      int         not null,
    tool_name       text        not null,
    tool_input      jsonb,
    tool_output     jsonb,
    success         boolean     not null,
    error_message   text,
    error_category  text        check (error_category in ('agent_error','env_error','unknown')),
    is_recoverable  boolean,
    reasoning       text,                           -- CoT extracted from LLM output; nullable
    latency_ms      int,
    created_at      timestamptz not null default now(),

    unique (episode_id, step_index)
);

create index if not exists idx_episode_steps_episode_id
    on episode_steps (episode_id, step_index);


-- ============================================================
-- episode_embeddings
-- One row per episode. Written by merger after generating embedding.
-- ============================================================
create table if not exists episode_embeddings (
    id              uuid        primary key default gen_random_uuid(),
    episode_id      text        not null unique references episodes(episode_id) on delete cascade,
    embedding       vector(1536),                   -- adjust dim to match your embedding model
    created_at      timestamptz not null default now()
);

-- IVFFlat index for approximate nearest-neighbour search.
-- Note: create this AFTER you have data (needs rows to build centroids).
-- Uncomment when ready:
-- create index on episode_embeddings using ivfflat (embedding vector_cosine_ops) with (lists = 100);


-- ============================================================
-- episode_scores
-- One row per (episode, scorer). Written by eval/rules.py and
-- eval/llm_judge.py. Uses upsert so re-scoring overwrites.
-- ============================================================
create table if not exists episode_scores (
    id          uuid        primary key default gen_random_uuid(),
    episode_id  text        not null references episodes(episode_id) on delete cascade,
    scorer      text        not null,   -- 'rules' | 'llm_judge'
    score       numeric     not null,   -- 0.0 – 1.0
    breakdown   jsonb,                  -- per-metric detail
    created_at  timestamptz not null default now(),

    unique (episode_id, scorer)
);

create index if not exists idx_episode_scores_episode
    on episode_scores (episode_id);


-- ============================================================
-- pick_next_job
-- Atomically picks one pending job, marks it 'processing'.
-- Uses SELECT FOR UPDATE SKIP LOCKED so multiple workers never
-- grab the same job.
-- ============================================================
create or replace function pick_next_job()
returns setof episode_jobs
language sql as $$
    update episode_jobs
    set
        status    = 'processing',
        locked_at = now()
    where id = (
        select id
        from   episode_jobs
        where  status = 'pending'
        order  by created_at asc
        limit  1
        for update skip locked
    )
    returning *;
$$;


-- ============================================================
-- match_episodes
-- Used by GET /similar to find episodes similar to a given one.
-- Requires pgvector extension and episode_embeddings populated by
-- the merger worker.
--
-- Parameters:
--   query_embedding  vector(1536)  — the source episode's embedding
--   match_count      int           — how many results to return
--   filter_user_id   text          — restrict to this user's episodes
-- ============================================================
create or replace function match_episodes(
    query_embedding vector(1536),
    match_count     int            default 5,
    filter_user_id  text           default null
)
returns table (
    episode_id       text,
    agent_id         text,
    task             text,
    outcome          text,
    total_steps      int,
    total_latency_ms int,
    similarity       float
)
language sql stable as $$
    select
        e.episode_id,
        e.agent_id,
        e.task,
        e.outcome,
        e.total_steps,
        e.total_latency_ms,
        1 - (ee.embedding <=> query_embedding) as similarity
    from episode_embeddings ee
    join episodes e using (episode_id)
    where
        (filter_user_id is null or e.user_id = filter_user_id)
    order by ee.embedding <=> query_embedding
    limit match_count;
$$;


-- ============================================================
-- webhooks
-- Stores user-configured webhook URLs for score alerts.
-- ============================================================
create table if not exists webhooks (
    id          uuid        primary key default gen_random_uuid(),
    user_id     text        not null,
    url         text        not null,
    threshold   numeric     not null default 0.7,
    is_active   boolean     not null default true,
    created_at  timestamptz not null default now()
);

create index if not exists idx_webhooks_user
    on webhooks (user_id);