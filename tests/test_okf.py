import json
from pathlib import Path

from agentlas_cloud.agent_graph import (
    OKF_FORMAT,
    from_okf_bundle,
    load_graph,
    migrate_ontology,
    to_okf_bundle,
)


def _seed(root: Path) -> None:
    base = root / ".agentlas"
    base.mkdir(parents=True, exist_ok=True)
    (base / "company-blueprint.json").write_text(
        json.dumps(
            {
                "nodes": [
                    {"id": "00-orchestrator", "role": "Orchestrator", "member_of": "platform"},
                    {
                        "id": "10-builder",
                        "role": "Single Agent Builder",
                        "member_of": "platform",
                        "consumes": ["agent-spec"],
                        "produces": ["agent-package"],
                    },
                ],
                "edges": [{"from": "00-orchestrator", "to": "10-builder", "handoff": "delegate"}],
            }
        ),
        encoding="utf-8",
    )
    (base / "routing-card.json").write_text(
        json.dumps({"id": "local/meta", "name": "Meta", "capabilities": ["build_agent_team"], "routing_status": "trusted"}),
        encoding="utf-8",
    )
    (base / "memory-map.json").write_text(json.dumps({"writeOwners": {"project": "10-builder"}}), encoding="utf-8")


def test_okf_roundtrip_preserves_nodes_and_edges(tmp_path: Path) -> None:
    _seed(tmp_path)
    migrate_ontology(tmp_path, write=True, overwrite=True)
    out = tmp_path / "okf"

    exported = to_okf_bundle(tmp_path, out)
    assert exported["format"] == OKF_FORMAT
    assert exported["nodes"] >= 4
    assert (out / "index.md").exists()

    imported = from_okf_bundle(out)
    graph = load_graph(tmp_path)["graph"]
    src_ids = (
        {a["id"] for a in graph["agents"]}
        | {a["id"] for a in graph["artifacts"]}
        | {s["id"] for s in graph["scopes"]}
        | {f"capability:{c}" for c in graph["capabilities"]}
    )
    imported_ids = {n["id"] for n in imported["nodes"]}
    assert src_ids == imported_ids
    relations = {e["relation"] for e in imported["edges"]}
    assert "produces" in relations
    assert "owns_scope" in relations


def test_okf_export_redacts_private_fields(tmp_path: Path) -> None:
    _seed(tmp_path)
    migrate_ontology(tmp_path, write=True, overwrite=True)
    out = tmp_path / "okf"
    to_okf_bundle(tmp_path, out)
    blob = "\n".join(p.read_text(encoding="utf-8") for p in out.rglob("*.md"))
    # private fields and their values must never reach the public bundle.
    assert "member_of" not in blob
    assert "platform" not in blob
    assert "routing_overrides" not in blob


def test_okf_from_missing_bundle_is_safe(tmp_path: Path) -> None:
    result = from_okf_bundle(tmp_path / "does-not-exist")
    assert result["counts"]["nodes"] == 0
    assert "error" in result
