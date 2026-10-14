-- Agentlas owner-scoped memory contract v1. Runtime source; no user data.
CREATE TABLE IF NOT EXISTS memory_entries (
        id TEXT PRIMARY KEY,
        scope TEXT NOT NULL,
        kind TEXT NOT NULL,
        content TEXT NOT NULL,
        project_id TEXT,
        project_path TEXT,
        agent_id TEXT,
        chat_id TEXT,
        confidence TEXT NOT NULL DEFAULT 'medium',
        sensitivity TEXT NOT NULL DEFAULT 'internal',
        evidence_json TEXT NOT NULL DEFAULT '[]',
        context_json TEXT NOT NULL DEFAULT '{}',
        embedding_model TEXT, embedding_adapter TEXT, embedding_model_sha256 TEXT,
        embedding_content_hash TEXT, embedding_dimensions INTEGER, embedding_json TEXT,
        superseded_at TEXT,
        created_at TEXT NOT NULL
      );
CREATE TABLE IF NOT EXISTS memory_tickets (
        ticket_id TEXT PRIMARY KEY,
        turn_key TEXT NOT NULL UNIQUE,
        turn_id TEXT,
        run_id TEXT,
        node_id TEXT,
        chat_id TEXT,
        agent_id TEXT,
        project_id TEXT,
        project_path_hash TEXT,
        emitter_status TEXT NOT NULL
          CHECK(emitter_status IN ('valid','empty','missing','malformed','read_only')),
        candidate_count INTEGER NOT NULL DEFAULT 0 CHECK(candidate_count >= 0),
        state TEXT NOT NULL DEFAULT 'received'
          CHECK(state IN ('received','completed','read_only','failed')),
        curator_mode TEXT NOT NULL DEFAULT 'policy'
          CHECK(curator_mode IN ('semantic','policy','policy_fallback','read_only')),
        curation_outcome TEXT NOT NULL DEFAULT 'no_candidates'
          CHECK(curation_outcome IN ('decided','no_candidates','malformed_output','curator_failed','read_only')),
        written_count INTEGER NOT NULL DEFAULT 0 CHECK(written_count >= 0),
        deduped_count INTEGER NOT NULL DEFAULT 0 CHECK(deduped_count >= 0),
        redacted_count INTEGER NOT NULL DEFAULT 0 CHECK(redacted_count >= 0),
        session_count INTEGER NOT NULL DEFAULT 0 CHECK(session_count >= 0),
        discarded_count INTEGER NOT NULL DEFAULT 0 CHECK(discarded_count >= 0),
        failure_code TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
      );
CREATE TABLE IF NOT EXISTS memory_decisions (
        decision_id TEXT PRIMARY KEY,
        ticket_id TEXT NOT NULL,
        candidate_index INTEGER NOT NULL CHECK(candidate_index >= 0),
        content_hash TEXT NOT NULL
          CHECK(length(content_hash) = 64 AND content_hash NOT GLOB '*[^0-9a-f]*'),
        memory_kind TEXT NOT NULL,
        proposed_scope TEXT NOT NULL,
        resolved_scope TEXT NOT NULL,
        action TEXT NOT NULL
          CHECK(action IN ('written','deduped','redacted','session','discarded','deferred')),
        reason_code TEXT NOT NULL,
        target_memory_id TEXT,
        confidence TEXT NOT NULL,
        sensitivity TEXT NOT NULL,
        curator_mode TEXT NOT NULL
          CHECK(curator_mode IN ('semantic','policy','policy_fallback','read_only')),
        created_at TEXT NOT NULL,
        FOREIGN KEY(ticket_id) REFERENCES memory_tickets(ticket_id) ON DELETE CASCADE,
        FOREIGN KEY(target_memory_id) REFERENCES memory_entries(id) ON DELETE SET NULL,
        UNIQUE(ticket_id, candidate_index)
      );
CREATE TABLE IF NOT EXISTS memory_relation_edges (
        relation_id TEXT PRIMARY KEY,
        from_memory_id TEXT NOT NULL,
        to_memory_id TEXT NOT NULL,
        relation_type TEXT NOT NULL
          CHECK(relation_type IN ('similar_to','supersedes','contradicts')),
        score REAL,
        owner_scope_key TEXT NOT NULL,
        embedding_model TEXT,
        embedding_adapter TEXT,
        embedding_model_sha256 TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY(from_memory_id) REFERENCES memory_entries(id) ON DELETE CASCADE,
        FOREIGN KEY(to_memory_id) REFERENCES memory_entries(id) ON DELETE CASCADE,
        CHECK(from_memory_id <> to_memory_id),
        CHECK(score IS NULL OR (score >= -1.0 AND score <= 1.0)),
        UNIQUE(from_memory_id, to_memory_id, relation_type)
      );
CREATE TABLE IF NOT EXISTS memory_episodes (
        episode_id TEXT PRIMARY KEY,
        ticket_id TEXT NOT NULL UNIQUE,
        project_id TEXT,
        project_path_hash TEXT,
        agent_id TEXT,
        chat_id TEXT,
        summary TEXT,
        summary_hash TEXT,
        embedding_model TEXT,
        embedding_adapter TEXT,
        embedding_model_sha256 TEXT,
        embedding_content_hash TEXT,
        embedding_dimensions INTEGER,
        embedding_json TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY(ticket_id) REFERENCES memory_tickets(ticket_id) ON DELETE CASCADE,
        CHECK(project_path_hash IS NULL OR
          (length(project_path_hash) = 64 AND project_path_hash NOT GLOB '*[^0-9a-f]*')),
        CHECK(summary_hash IS NULL OR
          (length(summary_hash) = 64 AND summary_hash NOT GLOB '*[^0-9a-f]*'))
      );
CREATE TABLE IF NOT EXISTS memory_forget_clock (
          id INTEGER PRIMARY KEY CHECK(id = 1),
          epoch INTEGER NOT NULL CHECK(epoch >= 0)
        );
CREATE TABLE IF NOT EXISTS memory_run_epochs (
          run_id TEXT PRIMARY KEY,
          intake_epoch INTEGER NOT NULL CHECK(intake_epoch >= 0),
          captured_at TEXT NOT NULL
        );
CREATE TABLE IF NOT EXISTS memory_revocations (
          revocation_id TEXT PRIMARY KEY,
          owner_key TEXT NOT NULL
            CHECK(length(owner_key) = 64 AND owner_key NOT GLOB '*[^0-9a-f]*'),
          memory_kind TEXT NOT NULL,
          content_hash TEXT NOT NULL
            CHECK(length(content_hash) = 64 AND content_hash NOT GLOB '*[^0-9a-f]*'),
          source_memory_id TEXT NOT NULL,
          revoked_epoch INTEGER NOT NULL CHECK(revoked_epoch > 0),
          revoked_at TEXT NOT NULL,
          UNIQUE(owner_key, memory_kind, content_hash)
        );
CREATE TABLE IF NOT EXISTS memory_revocation_sources (
          source_memory_id TEXT PRIMARY KEY,
          revocation_id TEXT NOT NULL REFERENCES memory_revocations(revocation_id) ON DELETE CASCADE
        );
CREATE TABLE IF NOT EXISTS memory_episode_quarantines (
          ticket_id TEXT PRIMARY KEY REFERENCES memory_tickets(ticket_id) ON DELETE CASCADE,
          revocation_id TEXT NOT NULL REFERENCES memory_revocations(revocation_id) ON DELETE CASCADE,
          reason TEXT NOT NULL CHECK(reason IN ('legacy-unlinked-dedup')),
          created_at TEXT NOT NULL
        );
CREATE TABLE IF NOT EXISTS memory_revocation_cleanup_targets (
        target_id TEXT PRIMARY KEY,
        source_memory_id TEXT NOT NULL,
        revocation_id TEXT REFERENCES memory_revocations(revocation_id) ON DELETE CASCADE,
        target_kind TEXT NOT NULL CHECK(target_kind IN ('project-files','agent-nest-scan')),
        target_ref TEXT NOT NULL,
        target_ref_hash TEXT NOT NULL
          CHECK(length(target_ref_hash) = 64 AND target_ref_hash NOT GLOB '*[^0-9a-f]*'),
        state TEXT NOT NULL CHECK(state IN ('writing','registered','pending','leased','complete')),
        lease_kind TEXT CHECK(lease_kind IN ('writer','cleanup')),
        lease_token TEXT,
        lease_expires_at TEXT,
        attempt_count INTEGER NOT NULL DEFAULT 0 CHECK(attempt_count >= 0),
        progress_cursor TEXT,
        next_attempt_at TEXT,
        last_error_code TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        completed_at TEXT,
        UNIQUE(source_memory_id, target_kind, target_ref_hash),
        CHECK(
          (lease_kind IS NULL AND lease_token IS NULL AND lease_expires_at IS NULL)
          OR (lease_kind IS NOT NULL AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL)
        )
      );
CREATE TABLE IF NOT EXISTS memory_store_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS memory_identity_bindings(
  memory_id TEXT PRIMARY KEY REFERENCES memory_entries(id) ON DELETE CASCADE,
  owner_namespace TEXT NOT NULL,actor_id TEXT,origin_refs_json TEXT NOT NULL DEFAULT '[]',
  applicability_json TEXT NOT NULL DEFAULT '{}',curation_actor TEXT NOT NULL DEFAULT 'legacy',
  policy_version TEXT,revision INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS memory_project_links(
  memory_id TEXT NOT NULL REFERENCES memory_entries(id) ON DELETE CASCADE,
  project_id TEXT NOT NULL,relation TEXT NOT NULL CHECK(relation IN ('origin','applies_to')),
  source_ref TEXT NOT NULL DEFAULT '',PRIMARY KEY(memory_id,project_id,relation,source_ref));
