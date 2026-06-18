"""Phase 2 (Ontology Pack manifest) + Phase 6 (Agent OS surface) assembly checks."""

from agentlas_cloud.agent_graph import PACK_FORMAT, build_pack, os_surface


def test_build_pack_is_installable() -> None:
    pack = build_pack(".")
    assert pack["format"] == PACK_FORMAT
    assert pack["installable"] is True
    assert pack["counts"]["agents"] >= 1
    assert pack["kernel"]["all_enforced"] is True
    assert len(pack["content_hash"]) == 16
    # deterministic: same inputs -> same fingerprint
    assert build_pack(".")["content_hash"] == pack["content_hash"]


def test_os_surface_all_modules_live() -> None:
    surface = os_surface(".")
    assert surface["agent_os"] == "hephaestus"
    assert len(surface["modules"]) == 6
    dead = [m["os_role"] for m in surface["modules"] if not m["live"]]
    assert surface["all_live"] is True, f"dead modules: {dead}"
    # Phase 6 factory inheritance contract is present.
    assert len(surface["factory_contract"]["inherited_contract"]) >= 5


def test_knowledge_catalog_descriptor(tmp_path) -> None:
    from agentlas_cloud.agent_graph import knowledge_catalog_descriptor

    desc = knowledge_catalog_descriptor(".", okf_dir=tmp_path / "okf")
    assert desc["format"] == "knowledge-catalog-descriptor-v1"
    assert desc["value_free_export"] is True
    assert "claude-code" in desc["supported_runtimes"]
    assert desc["bundle"]["files"] >= 1
    assert desc["kernel_enforced"] is True
