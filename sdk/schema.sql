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

-- api_keys: add expires_at and last_used_at columns
alter table if exists api_keys
    add column if not exists expires_at   timestamptz;   -- null = never expires
alter table if exists api_keys
    add column if not exists last_used_at timestamptz;   -- updated on each auth

-- episodes: add cluster_id for task clustering
alter table if exists episodes
    add column if not exists cluster_id uuid; -- foreign key added later

-- episodes: episodic-memory deepening (EVAL_DEPTH_AND_MEMORY_PLAN §1.1)
--   episode_fingerprint — stable hash of the tool-name sequence + outcome, so
--                         identically-shaped runs group in O(1) (regression diff).
--   parent_episode_id   — links retries/replays back to the run they re-ran.
alter table if exists episodes
    add column if not exists episode_fingerprint text;
alter table if exists episodes
    add column if not exists parent_episode_id  text;

create index if not exists idx_episodes_fingerprint
    on episodes (agent_id, episode_fingerprint);


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
-- episode_clusters
-- Stores K-means centroids for task clustering
-- ============================================================
create table if not exists episode_clusters (
    id            uuid primary key default gen_random_uuid(),
    user_id       text not null,
    agent_id      text not null,
    label         text not null,
    centroid      vector(1536),
    episode_count int default 0,
    avg_score     numeric,
    drift         numeric,
    top_failing_tool text,
    created_at    timestamptz default now()
);

-- Note: Cannot easily 'add foreign key if not exists' in raw postgres 
-- without a DO block, so we rely on application logic or just adding the column.
-- We added the column in the MIGRATION block above.



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
-- golden_datasets
-- A named, versioned set of test cases for an agent (the "golden" set
-- it should be evaluated against). Scoped per user.
-- ============================================================
create table if not exists golden_datasets (
    id           uuid        primary key default gen_random_uuid(),
    user_id      text        not null,
    project_id   text        not null,
    name         text        not null,
    version      text        not null default 'v1',
    created_at   timestamptz not null default now(),
    updated_at   timestamptz not null default now()
);

create index if not exists idx_golden_datasets_user
    on golden_datasets (user_id, project_id, created_at desc);


-- ============================================================
-- dataset_test_cases
-- One row per test case in a golden dataset.
-- ============================================================
create table if not exists dataset_test_cases (
    id              uuid        primary key default gen_random_uuid(),
    dataset_id      uuid        not null references golden_datasets(id) on delete cascade,
    input_data      jsonb       not null,
    expected_output text,
    context         jsonb,                          -- optional retrieval context
    created_at      timestamptz not null default now()
);

create index if not exists idx_dataset_test_cases_dataset
    on dataset_test_cases (dataset_id);


-- ============================================================
-- EVALUATION-MEMORY tables (EVAL_DEPTH_AND_MEMORY_PLAN Phase 1)
--
-- These three tables turn AGeval's memory from "similar tasks" into
-- evaluation memory that makes scoring smarter the more episodes it sees:
--   • failure_memory       — a library of how an agent fails (the moat)
--   • failure_occurrences   — every episode that matched a failure signature
--   • cluster_baselines     — per-cluster score distributions for peer-relative
--                             scoring + statistical (confidence) scoring
--
-- All are RLS-scoped by user_id exactly like golden_datasets, and every
-- consumer degrades gracefully (skip / 503) if the table is absent — the same
-- pattern api/datasets.py already uses.
-- ============================================================

-- ---- failure-pattern memory -----------------------------------------
-- One row per distinct failure signature for a (user, agent). A signature is
-- a stable bucket of (error_category | failing tool | failure-position band).
-- The centroid is the mean embedding of the failing episodes' error messages,
-- reusing the existing 1536-d embedding path (no new vendor).
create table if not exists failure_memory (
    id                uuid        primary key default gen_random_uuid(),
    user_id           text        not null,
    agent_id          text        not null,
    signature         text        not null,   -- error_category|tool|position-band
    label             text,                   -- human/auto name, e.g. "inventory timeout"
    centroid          vector(1536),           -- error-message embedding centroid
    occurrences       int         not null default 0,
    first_seen        timestamptz not null default now(),
    last_seen         timestamptz not null default now(),
    sample_episode_id text,
    sample_error      text,                   -- a representative error message
    created_at        timestamptz not null default now(),

    unique (user_id, agent_id, signature)
);

create index if not exists idx_failure_memory_agent
    on failure_memory (user_id, agent_id, last_seen desc);

-- ---- failure occurrences --------------------------------------------
-- The lifecycle log: which episodes matched which signature, and when. Lets
-- the UI say "this signature appeared in 14 runs over 3 days" (recurrence).
create table if not exists failure_occurrences (
    id            uuid        primary key default gen_random_uuid(),
    failure_id    uuid        not null references failure_memory(id) on delete cascade,
    episode_id    text        not null,
    step_index    int,
    occurred_at   timestamptz not null default now(),

    unique (failure_id, episode_id)
);

create index if not exists idx_failure_occurrences_failure
    on failure_occurrences (failure_id, occurred_at desc);

-- ---- per-cluster score baselines ------------------------------------
-- Semantic memory upgraded from "similar tasks" to "calibrated expectations".
-- One row per (cluster, scorer-or-metric): the score distribution of runs in
-- that cluster. A new episode is then scored RELATIVE to its peers.
create table if not exists cluster_baselines (
    cluster_id   uuid        not null references episode_clusters(id) on delete cascade,
    scorer       text        not null,   -- 'rules'|'llm_judge'|'custom'| metric name
    n            int         not null,   -- sample size behind this baseline
    mean         numeric     not null,
    p10          numeric,
    p50          numeric,
    p90          numeric,
    stddev       numeric,
    updated_at   timestamptz not null default now(),

    primary key (cluster_id, scorer)
);

-- ---- procedural memory (the "golden trajectory") --------------------
-- Procedural memory (EVAL_DEPTH_AND_MEMORY_PLAN §1.3): for each task cluster,
-- the canonical way the task *should* be done — the modal successful tool
-- sequence mined from the cluster's highest-scoring episodes, plus the expected
-- step count and tool set. A new run is then scored by how closely its tool
-- sequence follows this golden path (trajectory_adherence), catching "wrong
-- path, right answer". One row per cluster.
create table if not exists procedural_memory (
    cluster_id        uuid        not null references episode_clusters(id) on delete cascade,
    user_id           text        not null,
    agent_id          text        not null,
    golden_sequence   jsonb       not null,   -- ordered list of tool names
    expected_steps    numeric,                -- median meaningful-step count
    expected_tools    jsonb,                  -- the set of tools a good run uses
    n                 int         not null,    -- successful runs the golden path was mined from
    sample_episode_id text,                    -- the exemplar episode
    updated_at        timestamptz not null default now(),

    primary key (cluster_id)
);

create index if not exists idx_procedural_memory_agent
    on procedural_memory (user_id, agent_id);

-- ---- drift alerts (online drift detection) --------------------------
-- Online drift alerts (EVAL_DEPTH_AND_MEMORY_PLAN §2.6): one row per detected
-- regression of a cluster's recent score below its baseline. Written by the
-- drift sweep in the worker; read via GET /drift/alerts.
create table if not exists drift_alerts (
    id            uuid        primary key default gen_random_uuid(),
    cluster_id    uuid        references episode_clusters(id) on delete cascade,
    scorer        text        not null,
    baseline_mean numeric,
    recent_mean   numeric,
    drop          numeric,
    n_recent      int,
    detected_at   timestamptz not null default now()
);

create index if not exists idx_drift_alerts_cluster
    on drift_alerts (cluster_id, detected_at desc);


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
drop policy if exists api_keys_select on api_keys;
create policy api_keys_select on api_keys
    for select using (
        user_id = current_user_id()
        or current_user_id() = ''  -- service role / admin paths
    );

-- Only service role inserts keys (register endpoint)
-- The service_role key bypasses RLS, so no insert policy is needed.

-- Users can update only their own keys (for rotation/revocation)
drop policy if exists api_keys_update on api_keys;
create policy api_keys_update on api_keys
    for update using (user_id = current_user_id());


-- ---- episodes -------------------------------------------------------
alter table episodes enable row level security;

drop policy if exists episodes_select on episodes;
create policy episodes_select on episodes
    for select using (
        user_id = current_user_id()
        or current_user_id() = ''
    );

drop policy if exists episodes_insert on episodes;
create policy episodes_insert on episodes
    for insert with check (
        user_id = current_user_id()
        or current_user_id() = ''
    );

drop policy if exists episodes_update on episodes;
create policy episodes_update on episodes
    for update using (
        user_id = current_user_id()
        or current_user_id() = ''
    );

drop policy if exists episodes_delete on episodes;
create policy episodes_delete on episodes
    for delete using (
        user_id = current_user_id()
    );


-- ---- episode_steps --------------------------------------------------
-- Steps are owned by their parent episode's user_id.
-- We join through episodes to check ownership.
alter table episode_steps enable row level security;

drop policy if exists episode_steps_select on episode_steps;
create policy episode_steps_select on episode_steps
    for select using (
        current_user_id() = ''
        or exists (
            select 1 from episodes e
            where  e.episode_id = episode_steps.episode_id
              and  e.user_id    = current_user_id()
        )
    );

drop policy if exists episode_steps_insert on episode_steps;
create policy episode_steps_insert on episode_steps
    for insert with check (
        current_user_id() = ''
        or exists (
            select 1 from episodes e
            where  e.episode_id = episode_steps.episode_id
              and  e.user_id    = current_user_id()
        )
    );

drop policy if exists episode_steps_delete on episode_steps;
create policy episode_steps_delete on episode_steps
    for delete using (
        current_user_id() = ''
        or exists (
            select 1 from episodes e
            where  e.episode_id = episode_steps.episode_id
              and  e.user_id    = current_user_id()
        )
    );


-- ---- episode_jobs ---------------------------------------------------
alter table episode_jobs enable row level security;

drop policy if exists episode_jobs_select on episode_jobs;
create policy episode_jobs_select on episode_jobs
    for select using (
        user_id = current_user_id()
        or current_user_id() = ''
    );

drop policy if exists episode_jobs_insert on episode_jobs;
create policy episode_jobs_insert on episode_jobs
    for insert with check (
        user_id = current_user_id()
        or current_user_id() = ''
    );

drop policy if exists episode_jobs_update on episode_jobs;
create policy episode_jobs_update on episode_jobs
    for update using (
        user_id = current_user_id()
        or current_user_id() = ''
    );

drop policy if exists episode_jobs_delete on episode_jobs;
create policy episode_jobs_delete on episode_jobs
    for delete using (
        user_id = current_user_id()
    );


-- ---- episode_scores -------------------------------------------------
alter table episode_scores enable row level security;

drop policy if exists episode_scores_select on episode_scores;
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

drop policy if exists webhooks_select on webhooks;
create policy webhooks_select on webhooks
    for select using (
        user_id = current_user_id()
        or current_user_id() = ''
    );

drop policy if exists webhooks_insert on webhooks;
create policy webhooks_insert on webhooks
    for insert with check (
        user_id = current_user_id()
        or current_user_id() = ''
    );

drop policy if exists webhooks_update on webhooks;
create policy webhooks_update on webhooks
    for update using (user_id = current_user_id());

drop policy if exists webhooks_delete on webhooks;
create policy webhooks_delete on webhooks
    for delete using (user_id = current_user_id());


-- ---- webhook_deliveries ---------------------------------------------
-- Deliveries are written by the merger (service_role) and read by users.
alter table webhook_deliveries enable row level security;

drop policy if exists webhook_deliveries_select on webhook_deliveries;
create policy webhook_deliveries_select on webhook_deliveries
    for select using (
        current_user_id() = ''
        or exists (
            select 1 from webhooks w
            where  w.id      = webhook_deliveries.webhook_id
              and  w.user_id = current_user_id()
        )
    );

-- ---- golden_datasets ------------------------------------------------
alter table golden_datasets enable row level security;

drop policy if exists golden_datasets_select on golden_datasets;
create policy golden_datasets_select on golden_datasets
    for select using (user_id = current_user_id() or current_user_id() = '');

drop policy if exists golden_datasets_insert on golden_datasets;
create policy golden_datasets_insert on golden_datasets
    for insert with check (user_id = current_user_id() or current_user_id() = '');

drop policy if exists golden_datasets_update on golden_datasets;
create policy golden_datasets_update on golden_datasets
    for update using (user_id = current_user_id() or current_user_id() = '');

drop policy if exists golden_datasets_delete on golden_datasets;
create policy golden_datasets_delete on golden_datasets
    for delete using (user_id = current_user_id());


-- ---- dataset_test_cases ---------------------------------------------
-- Test cases inherit ownership from their parent golden_dataset.
alter table dataset_test_cases enable row level security;

drop policy if exists dataset_test_cases_select on dataset_test_cases;
create policy dataset_test_cases_select on dataset_test_cases
    for select using (
        current_user_id() = ''
        or exists (
            select 1 from golden_datasets d
            where d.id = dataset_test_cases.dataset_id
              and d.user_id = current_user_id()
        )
    );

drop policy if exists dataset_test_cases_insert on dataset_test_cases;
create policy dataset_test_cases_insert on dataset_test_cases
    for insert with check (
        current_user_id() = ''
        or exists (
            select 1 from golden_datasets d
            where d.id = dataset_test_cases.dataset_id
              and d.user_id = current_user_id()
        )
    );

drop policy if exists dataset_test_cases_delete on dataset_test_cases;
create policy dataset_test_cases_delete on dataset_test_cases
    for delete using (
        current_user_id() = ''
        or exists (
            select 1 from golden_datasets d
            where d.id = dataset_test_cases.dataset_id
              and d.user_id = current_user_id()
        )
    );


-- ---- failure_memory -------------------------------------------------
-- Written by the merger worker (service_role, bypasses RLS); read by users.
alter table failure_memory enable row level security;

drop policy if exists failure_memory_select on failure_memory;
create policy failure_memory_select on failure_memory
    for select using (user_id = current_user_id() or current_user_id() = '');

drop policy if exists failure_memory_insert on failure_memory;
create policy failure_memory_insert on failure_memory
    for insert with check (user_id = current_user_id() or current_user_id() = '');

drop policy if exists failure_memory_update on failure_memory;
create policy failure_memory_update on failure_memory
    for update using (user_id = current_user_id() or current_user_id() = '');

drop policy if exists failure_memory_delete on failure_memory;
create policy failure_memory_delete on failure_memory
    for delete using (user_id = current_user_id());


-- ---- failure_occurrences --------------------------------------------
-- Occurrences inherit ownership from their parent failure_memory row.
alter table failure_occurrences enable row level security;

drop policy if exists failure_occurrences_select on failure_occurrences;
create policy failure_occurrences_select on failure_occurrences
    for select using (
        current_user_id() = ''
        or exists (
            select 1 from failure_memory f
            where f.id = failure_occurrences.failure_id
              and f.user_id = current_user_id()
        )
    );


-- ---- cluster_baselines ----------------------------------------------
-- Baselines inherit ownership from their parent episode_clusters row.
alter table cluster_baselines enable row level security;

drop policy if exists cluster_baselines_select on cluster_baselines;
create policy cluster_baselines_select on cluster_baselines
    for select using (
        current_user_id() = ''
        or exists (
            select 1 from episode_clusters c
            where c.id = cluster_baselines.cluster_id
              and c.user_id = current_user_id()
        )
    );


-- ---- procedural_memory ----------------------------------------------
-- Written by the clustering job (service_role, bypasses RLS); read by users.
alter table procedural_memory enable row level security;

drop policy if exists procedural_memory_select on procedural_memory;
create policy procedural_memory_select on procedural_memory
    for select using (user_id = current_user_id() or current_user_id() = '');


-- ---- drift_alerts ---------------------------------------------------
-- Inherit ownership from the parent cluster.
alter table drift_alerts enable row level security;

drop policy if exists drift_alerts_select on drift_alerts;
create policy drift_alerts_select on drift_alerts
    for select using (
        current_user_id() = ''
        or exists (
            select 1 from episode_clusters c
            where c.id = drift_alerts.cluster_id
              and c.user_id = current_user_id()
        )
    );


-- ============================================================
-- END OF SCHEMA
-- ============================================================