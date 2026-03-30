-- ============================================================
-- episodic pipeline — Supabase schema
-- Run this in Supabase SQL editor (or via migration tool).
-- ============================================================

-- Enable pgvector (if not already enabled)
create extension if not exists vector;


-- ============================================================
-- episode_jobs
-- The queue. One row per agent run. Merger polls this table.
-- ============================================================
create table if not exists episode_jobs (
    id              uuid        primary key default gen_random_uuid(),
    episode_id      text        not null unique,
    run_id          text        not null,           -- LangSmith run ID
    agent_id        text        not null,
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
    run_id          text        not null,
    task            text,
    outcome         text,                           -- 'success' | 'failure' | 'partial'
    total_steps     int,
    total_latency_ms int,
    created_at      timestamptz not null default now()
);


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