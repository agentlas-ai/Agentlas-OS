"""Phase 3: a Hub-borrowed agent references its OWN local memory + the super
ontology, but only when the task needs grounding (selective, not constant).

Validates the structural wiring (agent_id + per-agent memory_root + grounding
directive emitted by invoke_hub_agent) and the relevance-gated retrieval that
makes the reference selective.
"""

from pathlib import Path

from agentlas_cloud.networking import init_networking
from agentlas_cloud.networking.hub_invocation import invoke_hub_agent
from ontology.runtime import OntologyRuntime, RuntimeConfig


def _mock_bundle(name, arguments=None, home=None, timeout=15):
    if name == "agentlas.get_runtime_bundle":
        return {
            "bundle": {
                "agent": arguments["slug"],
                "packageHash": "sha256:test",
                "entry": {"path": "AGENTS.md", "content": "Write magnetic product descriptions for the shop."},
                "toolPermissions": {"fileRead": "manifest-allowlist"},
            }
        }
    if name == "agentlas.resolve_plugins":
        return {"resolved": arguments["needs"], "hub": {"installable": []}}
    if name == "agentlas.memory.status":
        return {"expected_layout": {"soul": ".agentlas/project-soul-memory.md"}}
    if name == "agentlas.wizard.start":
        return {"ok": True}
    if name == "agentlas.soul.update":
        return {"write_to": ".agentlas/project-soul-memory.md", "append": "\n### note\n- borrowed for shop copy\n"}
    raise AssertionError(name)


def test_borrowed_agent_grounding_and_selective_ontology(tmp_path, monkeypatch):
    home = tmp_path / "networking"
    init_networking(home)
    project = tmp_path / "project"
    (project / ".agentlas").mkdir(parents=True)

    # 1. Super ontology with a distinctive fact only findable here.
    db = project / ".agentlas" / "ontology-runtime.sqlite"
    doc = project / "brand.md"
    doc.write_text(
        "# Acme 브랜드 보이스 가이드\n\n"
        "Acme 상품 설명 톤은 장난스럽고 이모지를 적극 쓴다.\n"
        "절대 '최저가' '할인' 같은 단어를 쓰지 않는다.\n"
        "상품 설명 끝에는 항상 'Acme와 함께 🚀' 문구를 붙인다.\n",
        encoding="utf-8",
    )
    rt = OntologyRuntime(RuntimeConfig(db_path=db))
    rt.ingest_path(str(doc), access_scope="internal")

    # 2. Borrow a Hub agent → it gets agent_id + per-agent memory_root + grounding.
    monkeypatch.setattr("agentlas_cloud.networking.hub_invocation.call_hub_tool", _mock_bundle)
    result = invoke_hub_agent(
        "신상 가방 상품 상세설명 써줘",
        slug="shop-product-writer",
        hub_decision={
            "action": "hub_candidates",
            "receipt_id": "r1",
            "hub": {"results": [{"slug": "shop-product-writer", "kind": "cloud-callable", "callable": True}]},
        },
        project_dir=project,
        home=home,
    )

    assert result["status"] == "prepared"
    grounding = result["output"]["grounding"]
    agent_id = grounding["agent_id"]
    assert agent_id == "hub:shop-product-writer"
    assert grounding["policy"] == "attach_codebase_then_selective_memory"
    directive = grounding["directive"].lower()
    # Tier 1 (mandatory): attach to the live project codebase.
    assert grounding["project_dir"] and "project" in grounding["project_dir"]
    assert "attach to that live codebase" in directive and "mandatory" in directive
    # Tier 2 (selective): memory/ontology consulted only when the task needs it.
    assert "trivial or self-contained, skip" in directive
    # Borrowed agent has its OWN persistent local memory store (from the fetch).
    assert Path(grounding["memory_root"]).joinpath("project-soul-memory.md").is_file()
    assert Path(grounding["experience_db"]).is_file()
    assert grounding["ontology_db"] == str(db)
    assert grounding["commands"]["experience_query"].startswith(
        f"python3 -m ontology --db {grounding['experience_db']} query "
    )
    assert f"--agent {agent_id}" in grounding["commands"]["experience_query"]
    assert "cat " not in grounding["commands"]["memory_read"]
    assert grounding["commands"]["ontology_query"].startswith(
        f"python3 -m ontology --db {grounding['ontology_db']} query "
    )

    # 3. Relevant task → references ontology fact + caches working memory.
    relevant = rt.query("이 상품 설명 쓸 때 우리 브랜드 톤이랑 금지어가 뭐지?", agent_id=agent_id, allowed_scopes=["internal"], limit=5)
    rel_chunks = relevant.get("chunks") or []
    assert len(rel_chunks) >= 1
    assert "최저가" in " ".join(c.get("text", "") for c in rel_chunks)
    assert len(relevant.get("working_memory") or []) >= 1

    # 4. Irrelevant task → no reference, no crash (selective, not constant).
    irrelevant = rt.query("오늘 서울 날씨 어때?", agent_id=agent_id, allowed_scopes=["internal"], limit=5)
    assert len(irrelevant.get("chunks") or []) == 0

    # 5. Selective: relevant retrieved grounding, irrelevant did not.
    assert len(rel_chunks) > len(irrelevant.get("chunks") or [])

    # 6. The borrowed agent's working memory persists and is readable by agent_id.
    cached = rt.read_working_memory(agent_id)
    assert any("최저가" in item.get("memory_item", "") or "브랜드" in item.get("memory_item", "") or "Acme" in item.get("memory_item", "") for item in cached) or len(cached) >= 1
