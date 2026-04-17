-- ============================================================
-- episodic pipeline — Supabase schema  (v3 — safe to re-run)
-- Run this in Supabase SQL editor (or via migration tool).
--
-- This file is idempotent:
--   • CREATE TABLE IF NOT EXISTS   → skips if table already exists
--   • ALTER TABLE  ADD COLUMN IF NOT EXISTS → skips if column exists
--   • CREATE OR REPLACE FUNCTION   → always updates the function
--   • CREATE INDEX IF NOT EXISTS   → skips if index exists
--   • Row Level Security (RLS) is enabled on all user-data tables.
--     The API server sets app.user_id via set_config() before queries.
--     The merger worker uses the service_role key which bypasses RLS.
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

-- episodes: add final_output for grounded LLM judging
alter table if exists episodes
    add column if not exists final_output jsonb;

-- episode_jobs: add user_id if missing
alter table if exists episode_jobs
    add column if not exists user_id text;

-- episode_jobs: add scheduled_at for non-blocking not-ready requeue
alter table if exists episode_jobs
    add column if not exists scheduled_at timestamptz;

-- api_keys: add expiry and audit columns (v3)
alter table if exists api_keys
    add column if not exists expires_at   timestamptz;   -- null = never expires
alter table if exists api_keys
    add column if not exists last_used_at timestamptz;   -- updated on each auth

-- Drop the old trigger first so we can recreate it cleanly
drop trigger if exists episode_jobs_updated_at on episode_jobs;

-- Drop functions before recreating
drop function if exists pick_next_job();
drop function if exists match_episodes(vector, int, text);
drop function if exists reclaim_stale_jobs(timestamptz);


-- ============================================================
-- api_keys
-- Stores hashed API keys for SDK authentication.
-- Raw key is NEVER stored — only the sha256 hash.
-- expires_at: null = never expires; set for time-limited keys.
-- last_used_at: updated on every successful auth (audit trail).
-- ============================================================
create table if not exists api_keys (
    id           uuid        primary key default gen_random_uuid(),
    key_hash     text        not null unique,
    user_id      text        not null,
    label        text        not null default '',
    is_active    boolean     not null default true,
    expires_at   timestamptz,                           -- null = never expires
    last_used_at timestamptz,                           -- set on each successful auth
    created_at   timestamptz not null default now()
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
    run_id          text        not null,           -- LangSmith run ID (or 'none')
    agent_id        text        not null,
    user_id         text,                           -- scoped per user
    task            text,                           -- human-readable task description
    status          text        not null default 'pending'
                                check (status in ('pending','processing','done','failed')),
    retry_count     int         not null default 0,
    locked_at       timestamptz,                    -- set when worker picks it up
    scheduled_at    timestamptz,                    -- not-ready jobs: don't pick before this time
    error_message   text,
    created_at      timestamptz not null default now(),
    updated_at      timestamptz not null default now()
);

-- Index for the poll query
create index if not exists idx_episode_jobs_status
    on episode_jobs (status, scheduled_at, created_at);

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
    id               uuid        primary key default gen_random_uuid(),
    episode_id       text        not null unique,
    agent_id         text        not null,
    user_id          text,                           -- scoped per user
    run_id           text        not null,
    task             text,
    outcome          text,                           -- 'success' | 'failure' | 'partial'
    total_steps      int,
    total_latency_ms int,
    final_output     jsonb,                          -- final agent output for grounded judging
    created_at       timestamptz not null default now()
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
-- Honors scheduled_at: skips jobs that aren't due yet.
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
          and  (scheduled_at is null or scheduled_at <= now())
        order  by created_at asc
        limit  1
        for update skip locked
    )
    returning *;
$$;


-- ============================================================
-- reclaim_stale_jobs
-- Reclaims jobs stuck in 'processing' (dead workers) back to 'pending'.
-- Call this periodically from the worker process.
-- ============================================================
create or replace function reclaim_stale_jobs(cutoff_time timestamptz)
returns setof episode_jobs
language sql as $$
    update episode_jobs
    set
        status    = 'pending',
        locked_at = null,
        error_message = 'reclaimed_stale'
    where status = 'processing'
      and locked_at < cutoff_time
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


-- ============================================================
-- webhook_deliveries
-- Audit trail for webhook delivery attempts.
-- Allows users to inspect failed deliveries.
-- ============================================================
create table if not exists webhook_deliveries (
    id          uuid        primary key default gen_random_uuid(),
    webhook_id  uuid,                               -- references webhooks.id
    episode_id  text,
    status      text        not null default 'pending'
                            check (status in ('pending','delivered','failed')),
    attempts    int         not null default 0,
    last_error  text,
    created_at  timestamptz not null default now()
);

create index if not exists idx_webhook_deliveries_webhook
    on webhook_deliveries (webhook_id, created_at desc);

create index if not exists idx_webhook_deliveries_episode
    on webhook_deliveries (episode_id);


-- ============================================================
-- ROW LEVEL SECURITY (RLS) — v3
--
-- Enforces multi-tenant data isolation at the Postgres layer.
-- Even if application code forgets _assert_episode_owned,
-- a user can only ever see their own rows.
--
-- How it works:
--   • The API server calls set_config('app.user_id', user_id, true)
--     before running any user query.
--   • Policies filter rows using current_setting('app.user_id', true).
--   • The merger worker connects with the service_role key, which
--     bypasses RLS entirely — no worker changes needed.
--   • The 'true' (is_nullable) flag means unset config returns ''
--     instead of raising an error, so health/register endpoints
--     (which never call set_config) still work fine.
-- ============================================================

-- Helper: get the current request's user_id from session config.
-- Returns '' if not set (service role queries, /health, /register).
create or replace function current_user_id() returns text
language sql stable as $$
    select coalesce(current_setting('app.user_id', true), '')
$$;


-- ---- api_keys -------------------------------------------------------
alter table api_keys enable row level security;

-- Users can only see their own keys
create policy api_keys_select on api_keys
    for select using (
        user_id = current_user_id()
        or current_user_id() = ''  -- service role / admin paths
    );

-- Only service role inserts keys (register endpoint)
-- The service_role key bypasses RLS, so no insert policy is needed.

-- Users can update only their own keys (for rotation/revocation)
create policy api_keys_update on api_keys
    for update using (user_id = current_user_id());


-- ---- episodes -------------------------------------------------------
alter table episodes enable row level security;

create policy episodes_select on episodes
    for select using (
        user_id = current_user_id()
        or current_user_id() = ''
    );

create policy episodes_insert on episodes
    for insert with check (
        user_id = current_user_id()
        or current_user_id() = ''
    );

create policy episodes_update on episodes
    for update using (
        user_id = current_user_id()
        or current_user_id() = ''
    );


-- ---- episode_steps --------------------------------------------------
-- Steps are owned by their parent episode's user_id.
-- We join through episodes to check ownership.
alter table episode_steps enable row level security;

create policy episode_steps_select on episode_steps
    for select using (
        current_user_id() = ''
        or exists (
            select 1 from episodes e
            where  e.episode_id = episode_steps.episode_id
              and  e.user_id    = current_user_id()
        )
    );

create policy episode_steps_insert on episode_steps
    for insert with check (
        current_user_id() = ''
        or exists (
            select 1 from episodes e
            where  e.episode_id = episode_steps.episode_id
              and  e.user_id    = current_user_id()
        )
    );


-- ---- episode_jobs ---------------------------------------------------
alter table episode_jobs enable row level security;

create policy episode_jobs_select on episode_jobs
    for select using (
        user_id = current_user_id()
        or current_user_id() = ''
    );

create policy episode_jobs_insert on episode_jobs
    for insert with check (
        user_id = current_user_id()
        or current_user_id() = ''
    );

create policy episode_jobs_update on episode_jobs
    for update using (
        user_id = current_user_id()
        or current_user_id() = ''
    );


-- ---- episode_scores -------------------------------------------------
alter table episode_scores enable row level security;

create policy episode_scores_select on episode_scores
    for select using (
        current_user_id() = ''
        or exists (
            select 1 from episodes e
            where  e.episode_id = episode_scores.episode_id
              and  e.user_id    = current_user_id()
        )
    );

-- Scores are written by the merger (service role) — no user insert policy needed.


-- ---- webhooks -------------------------------------------------------
alter table webhooks enable row level security;

create policy webhooks_select on webhooks
    for select using (
        user_id = current_user_id()
        or current_user_id() = ''
    );

create policy webhooks_insert on webhooks
    for insert with check (
        user_id = current_user_id()
        or current_user_id() = ''
    );

create policy webhooks_update on webhooks
    for update using (user_id = current_user_id());

create policy webhooks_delete on webhooks
    for delete using (user_id = current_user_id());


-- ---- webhook_deliveries ---------------------------------------------
-- Deliveries are written by the merger (service_role) and read by users.
alter table webhook_deliveries enable row level security;

create policy webhook_deliveries_select on webhook_deliveries
    for select using (
        current_user_id() = ''
        or exists (
            select 1 from webhooks w
            where  w.id      = webhook_deliveries.webhook_id
              and  w.user_id = current_user_id()
        )
    );

-- ============================================================
-- END OF SCHEMA
-- ============================================================