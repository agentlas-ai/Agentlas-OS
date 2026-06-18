"""Phase 1 kernel: the two promoted super-ontology seeds are runtime-enforced.

Integration test against the real repo: the seeds were lifted to
``runtime_enforced`` and are realized by live AO grammar axioms.
"""

from agentlas_cloud.agent_graph import ENFORCED_SEEDS, load_kernel, verify_enforcement


def test_kernel_loads_master_and_themes() -> None:
    kernel = load_kernel(".")
    assert kernel["master_present"] is True
    # 1 master + 24 themes.
    assert kernel["theme_count"] >= 24


def test_two_seeds_are_runtime_enforced() -> None:
    verification = verify_enforcement(".")
    assert verification["all_enforced"] is True
    assert verification["fully_enforced_count"] == len(ENFORCED_SEEDS) == 2
    for entry in verification["enforced_seeds"]:
        assert entry["state_ok"] is True, entry["contract"]
        assert entry["axiom_present"] is True, entry["contract"]
        assert entry["enforced"] is True, entry["contract"]
