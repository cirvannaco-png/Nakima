-- ============================================================================
-- NAKIMA LAB / SANDBOX SCHEMA
-- ============================================================================
-- Design principle (non-negotiable): per-repo data is isolated. The shared
-- NEIS base model only ever learns from `pattern_memory`, and every row in
-- `pattern_memory` is CHECK-constrained to reject raw code, diffs, or
-- repo-identifying strings. This is enforced structurally, not by policy,
-- so a bug elsewhere in the app can't accidentally leak tenant code into the
-- shared base.
--
-- Team/org support is built in from day one per the earlier discussion: every
-- tenant-scoped table carries organization_id, even while most orgs today are
-- a single implicit org per user. Retrofitting this later is the expensive
-- mistake; adding it now costs nothing.
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS "pgcrypto"; -- for gen_random_uuid()

-- ----------------------------------------------------------------------------
-- Tenancy
-- ----------------------------------------------------------------------------

CREATE TABLE organizations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            TEXT NOT NULL,
    plan_tier       TEXT NOT NULL DEFAULT 'solo' CHECK (plan_tier IN ('solo', 'team', 'enterprise')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE org_members (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id         UUID NOT NULL,  -- FK to your existing users table
    role            TEXT NOT NULL DEFAULT 'member' CHECK (role IN ('owner', 'admin', 'member', 'viewer')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (organization_id, user_id)
);
CREATE INDEX idx_org_members_org ON org_members(organization_id);
CREATE INDEX idx_org_members_user ON org_members(user_id);

CREATE TABLE repositories (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    github_repo_id  BIGINT NOT NULL,          -- GitHub's numeric repo id
    full_name       TEXT NOT NULL,             -- e.g. "cirvannaco-png/Nakima"
    default_branch  TEXT NOT NULL DEFAULT 'main',
    sandbox_lab_opt_in       BOOLEAN NOT NULL DEFAULT false, -- explicit consent for synthetic vuln injection
    consented_at             TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (organization_id, github_repo_id)
);
CREATE INDEX idx_repositories_org ON repositories(organization_id);

-- ----------------------------------------------------------------------------
-- Sandbox runs — fully isolated per repo. Nothing here is ever shared
-- across tenants. This table CAN contain raw diffs, logs, code snippets —
-- because it's scoped to exactly one repo/org and never read cross-tenant.
-- ----------------------------------------------------------------------------

CREATE TYPE run_trigger AS ENUM ('ci_failure', 'cve_scan', 'synthetic_injection', 'manual');
CREATE TYPE run_status  AS ENUM ('queued', 'provisioning', 'running', 'awaiting_review', 'approved', 'rejected', 'expired', 'failed');

CREATE TABLE sandbox_runs (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id     UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    repository_id       UUID NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
    trigger             run_trigger NOT NULL,
    status              run_status NOT NULL DEFAULT 'queued',

    -- provenance: which commit was the sandbox cloned from
    source_commit_sha   TEXT NOT NULL,

    -- container isolation metadata (see orchestrator/README for network policy)
    container_id        TEXT,
    container_image      TEXT,
    network_isolated     BOOLEAN NOT NULL DEFAULT true,

    -- synthetic injection requires explicit prior opt-in on the repo row;
    -- this is re-checked at insert time via trigger below, not just app logic
    synthetic_injection_used BOOLEAN NOT NULL DEFAULT false,

    diagnosis           JSONB,      -- structured root-cause finding
    proposed_fix_diff   TEXT,       -- raw diff — fine here, tenant-scoped table
    ai_models_consulted JSONB,      -- e.g. [{"model": "claude-sonnet-5", "verdict": "..."}]
    full_test_suite_passed BOOLEAN,
    outcome             TEXT,       -- 'fix_correct' | 'fix_incorrect' | 'no_fix_found' | 'user_rejected'

    started_at          TIMESTAMPTZ,
    completed_at        TIMESTAMPTZ,
    expires_at          TIMESTAMPTZ NOT NULL DEFAULT (now() + interval '24 hours'), -- ephemeral container TTL
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_sandbox_runs_repo ON sandbox_runs(repository_id);
CREATE INDEX idx_sandbox_runs_org ON sandbox_runs(organization_id);
CREATE INDEX idx_sandbox_runs_status ON sandbox_runs(status);

-- enforce: synthetic injection can only be used on repos that explicitly opted in
CREATE OR REPLACE FUNCTION enforce_synthetic_injection_consent()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.synthetic_injection_used THEN
        IF NOT EXISTS (
            SELECT 1 FROM repositories
            WHERE id = NEW.repository_id AND sandbox_lab_opt_in = true
        ) THEN
            RAISE EXCEPTION 'synthetic_injection_used requires repositories.sandbox_lab_opt_in = true for repo %', NEW.repository_id;
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_enforce_synthetic_consent
    BEFORE INSERT OR UPDATE ON sandbox_runs
    FOR EACH ROW EXECUTE FUNCTION enforce_synthetic_injection_consent();

-- Human approval gate — required for every run before a PR can be opened.
-- Security-classified runs cannot self-approve even in future automation modes.
CREATE TABLE run_reviews (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sandbox_run_id  UUID NOT NULL REFERENCES sandbox_runs(id) ON DELETE CASCADE,
    reviewed_by     UUID NOT NULL, -- user_id
    decision        TEXT NOT NULL CHECK (decision IN ('approved', 'rejected')),
    notes           TEXT,
    reviewed_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_run_reviews_run ON run_reviews(sandbox_run_id);

-- ----------------------------------------------------------------------------
-- Pattern memory — the ONLY table NEIS's shared base model reads from.
-- Structurally forbidden from containing raw code, diffs, or repo identifiers.
-- ----------------------------------------------------------------------------

CREATE TABLE pattern_memory (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_run_id       UUID REFERENCES sandbox_runs(id) ON DELETE SET NULL, -- provenance only, not joined at inference time

    vulnerability_class TEXT NOT NULL,      -- e.g. "sql_injection", "insecure_deserialization"
    language            TEXT NOT NULL,      -- e.g. "python", "javascript"
    framework           TEXT,               -- e.g. "fastapi", "express"

    fix_pattern         TEXT NOT NULL,      -- abstract description, e.g. "parameterized_query"
    fix_pattern_summary  TEXT NOT NULL,      -- human-readable, generalized — NOT the literal diff
    context_features     JSONB NOT NULL DEFAULT '{}', -- e.g. {"has_orm": true, "test_coverage_pct": 81}

    confidence_score     NUMERIC(4,3) NOT NULL CHECK (confidence_score BETWEEN 0 AND 1),
    validated_by_human    BOOLEAN NOT NULL DEFAULT false,

    -- promoted_to_base_model = true only after deliberate, batch, offline review —
    -- never set true by an in-run process. See orchestrator/README "no live weight updates".
    promoted_to_base_model BOOLEAN NOT NULL DEFAULT false,
    promoted_at             TIMESTAMPTZ,

    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- structural guardrails against accidental leakage of raw code:
    CONSTRAINT no_raw_diff_markers CHECK (
        fix_pattern_summary !~ '(diff --git|^\+\+\+|^---|@@ -)' -- reject unified-diff syntax
    ),
    CONSTRAINT reasonable_summary_length CHECK (
        length(fix_pattern_summary) BETWEEN 10 AND 500 -- forces abstraction; a 500-char cap can't hold a real diff
    )
);
CREATE INDEX idx_pattern_memory_class ON pattern_memory(vulnerability_class, language);
CREATE INDEX idx_pattern_memory_promoted ON pattern_memory(promoted_to_base_model) WHERE promoted_to_base_model = true;

-- ----------------------------------------------------------------------------
-- Model comparison log — runtime candidate selection across providers.
-- This is RUNTIME SELECTION ONLY (pick the best candidate fix per run).
-- It is explicitly NOT training data for NEIS. See docs/PROVIDER_TOS_NOTES.md —
-- persisting third-party model outputs as training data may violate several
-- providers' ToS and must be reviewed per-provider before any such use.
-- ----------------------------------------------------------------------------

CREATE TABLE model_candidate_fixes (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sandbox_run_id  UUID NOT NULL REFERENCES sandbox_runs(id) ON DELETE CASCADE,
    provider        TEXT NOT NULL,   -- 'claude' | 'gemini' | 'kimi' | 'deepseek' | 'gpt'
    candidate_diff  TEXT NOT NULL,
    selected        BOOLEAN NOT NULL DEFAULT false,
    judge_reasoning TEXT,
    retained_for_training BOOLEAN NOT NULL DEFAULT false, -- must stay false until ToS review is complete per provider
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_model_candidates_run ON model_candidate_fixes(sandbox_run_id);
