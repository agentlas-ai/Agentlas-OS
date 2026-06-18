"""Phase 3: bi-temporal memory — supersede-not-delete + valid-time queries."""

from agentlas_cloud.agent_graph.memory import BiTemporalStore, MemoryEntry


def test_supersede_keeps_old_entry() -> None:
    store = BiTemporalStore()
    store.add(
        MemoryEntry(
            id="a", scope="project", text="v1",
            valid_from="2026-01-01", ingested_at="2026-01-01", evidence_refs=["e1"],
        )
    )
    store.supersede(
        "a",
        MemoryEntry(id="b", scope="project", text="v2", valid_from="2026-02-01", ingested_at="2026-02-01"),
    )
    assert store.get("a").status == "superseded"  # not deleted
    assert store.get("b").supersedes == "a"
    assert {e.id for e in store.history("b")} == {"a", "b"}
    assert store.get("a").evidence_refs == ["e1"]  # provenance preserved


def test_active_at_valid_window() -> None:
    store = BiTemporalStore()
    store.add(
        MemoryEntry(id="x", scope="p", text="t", valid_from="2026-01-01", valid_to="2026-06-01", ingested_at="2026-01-01")
    )
    assert [e.id for e in store.active_at("2026-03-01")] == ["x"]
    assert store.active_at("2026-07-01") == []  # after valid_to
    assert store.active_at("2025-12-01") == []  # before valid_from


def test_superseded_excluded_from_active() -> None:
    store = BiTemporalStore()
    store.add(MemoryEntry(id="a", scope="p", text="v1", valid_from="2026-01-01", ingested_at="2026-01-01"))
    store.supersede(
        "a", MemoryEntry(id="b", scope="p", text="v2", valid_from="2026-01-01", ingested_at="2026-02-01")
    )
    assert {e.id for e in store.active_at("2026-03-01")} == {"b"}


def test_active_at_timezone_aware_instant() -> None:
    """Cross-timezone instants compare correctly (not raw ISO string order)."""
    store = BiTemporalStore()
    store.add(
        MemoryEntry(
            id="x", scope="p", text="t",
            valid_from="2026-01-01T00:00:00+09:00", ingested_at="2026-01-01T00:00:00+09:00",
        )
    )
    # 2025-12-31T15:00:00Z is the SAME instant as 2026-01-01T00:00:00+09:00.
    assert [e.id for e in store.active_at("2025-12-31T15:00:00Z")] == ["x"]
    assert store.active_at("2025-12-31T14:59:59Z") == []  # one second before


def test_deprecate_excluded_from_active() -> None:
    store = BiTemporalStore()
    store.add(MemoryEntry(id="x", scope="p", text="t", valid_from="2026-01-01", ingested_at="2026-01-01"))
    store.deprecate("x", at="2026-03-01")
    assert store.get("x").status == "deprecated"
    assert store.active_at("2026-02-01") == []
