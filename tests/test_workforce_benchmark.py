from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "benchmarks" / "workforce-ontology" / "score_run.py"
SPEC = json.loads(
    (ROOT / "benchmarks" / "workforce-ontology" / "difficult-payment-platform.json").read_text(encoding="utf-8")
)
module_spec = importlib.util.spec_from_file_location("workforce_benchmark_score", MODULE_PATH)
assert module_spec and module_spec.loader
score_module = importlib.util.module_from_spec(module_spec)
module_spec.loader.exec_module(score_module)


def _slot(slot_id: str, community: str, role: str, skill: str) -> dict:
    return {
        "slotId": slot_id,
        "title": slot_id,
        "task": f"Own {slot_id}",
        "cardinality": 1,
        "criticality": "required",
        "requiredCommunities": [community],
        "requiredRoles": [role],
        "requiredSkills": [skill],
        "requiredKnowledge": [],
        "requiredToolCapabilities": [],
        "consumes": [],
        "produces": [],
        "requiredAuthorities": [],
        "forbiddenAuthorities": [],
        "runtimes": [],
        "languages": [],
        "modalities": [],
        "allowedEntityKinds": ["agent"],
    }


def _passing_run() -> dict:
    slots = [
        _slot("backend", "community:backend-engineering", "role:backend-engineer", "skill:api-design"),
        _slot("database", "community:database-engineering", "role:database-engineer", "skill:data-modeling"),
        _slot("payments", "community:payments-engineering", "role:payments-engineer", "skill:billing-integration"),
        _slot("security", "community:security-engineering", "role:security-engineer", "skill:security-review"),
        _slot("quality", "community:quality-engineering", "role:quality-engineer", "skill:test-design"),
    ]
    digest = "sha256:" + "a" * 64
    candidates = []
    assignments = []
    workers = []
    for index, slot in enumerate(slots):
        release_id = f"agent:{slot['slotId']}:v1"
        candidate = {
            "agentDefinitionId": f"agent:{slot['slotId']}",
            "agentReleaseId": release_id,
            "releaseVersion": "1.0.0",
            "packageHash": "sha256:" + f"{index + 1:064x}",
            "contentDigest": "sha256:" + f"{index + 11:064x}",
            "entityKind": "agent",
            "name": slot["slotId"],
            "communities": slot["requiredCommunities"],
            "semanticSnapshot": {
                "summaries": [slot["task"]],
                "roles": slot["requiredRoles"],
                "skills": [{"concept": slot["requiredSkills"][0], "level": "demonstrated"}],
                "toolCapabilities": [],
                "consumes": [],
                "produces": [],
                "authorities": [],
                "runtimes": [],
                "languages": [],
            },
            "fitEvidence": [f"fit:role:{slot['requiredRoles'][0]}"],
            "qualificationEvidence": [f"eval:{slot['slotId']}"],
            "optionalGaps": [],
            "operational": {"callable": True, "installable": True, "unavailableReasons": []},
        }
        candidates.append({"slotId": slot["slotId"], "candidates": [candidate], "coverageGaps": []})
        assignments.append({"slotId": slot["slotId"], "agentReleaseId": release_id, "reasonCodes": [f"fit:{slot['slotId']}"]})
        workers.append({
            "slotId": slot["slotId"],
            "agentReleaseId": release_id,
            "packageHash": candidate["packageHash"],
            "contentDigest": candidate["contentDigest"],
            "modelId": "test-model",
            "invocationId": f"worker:{index}",
            "status": "completed",
            "handoffArtifactRefs": [f"artifact:{index}"],
        })
    work_order = {
        "schemaVersion": "agentlas.workforce-work-order.v1",
        "workOrderId": "work-order:test",
        "taskBrief": "test",
        "redacted": True,
        "roleSlots": slots,
        "forbiddenCommunities": SPEC["forbiddenCommunities"],
    }
    candidate_set = {
        "schemaVersion": "agentlas.workforce-candidate-set.v1",
        "selectionSessionId": "selection:test",
        "workOrderId": work_order["workOrderId"],
        "ontologyVersion": "awo:test",
        "candidateSetDigest": digest,
        "decisionOwner": "host_llm",
        "historyInfluence": "none",
        "slots": candidates,
        "issuedAt": "2098-01-01T00:00:00Z",
        "expiresAt": "2099-01-01T00:00:00Z",
    }
    selection = {
        "schemaVersion": "agentlas.workforce-selection.v1",
        "selectionSessionId": candidate_set["selectionSessionId"],
        "candidateSetDigest": digest,
        "decisionAuthor": {"kind": "host_llm", "modelId": "test-model", "runtimeId": "test-runtime"},
        "assignments": assignments,
        "edges": [],
        "alternativesConsidered": [],
    }
    validation = score_module.validate_host_selection(selection, candidate_set=candidate_set, work_order=work_order)
    return {
        "workOrder": work_order,
        "candidateSet": candidate_set,
        "selection": selection,
        "selectionValidation": validation,
        "selectionReceipt": {
            "decisionOwner": "host_llm",
            "decisionModel": "test-model",
            "decisionRuntime": "test-runtime",
            "historyInfluence": "none",
            "substitutions": [],
            "mcpCalls": [{"tool": tool, "status": "ok"} for tool in SPEC["requiredMcpSequence"]],
            "leaderInvocations": [
                {"phase": "work-order", "status": "completed"},
                {"phase": "selection", "status": "completed"},
            ],
        },
        "executionReceipt": {
            "schemaVersion": "agentlas.workforce-execution-receipt.v1",
            "status": "passed",
            "executionId": "execution:test",
            "selectionReceiptId": validation["selectionReceiptId"],
            "preparationReceiptId": "preparation:test",
            "orchestrator": {"modelId": "test-model", "invocationId": "orchestrator:test"},
            "planner": {"modelId": "test-model", "invocationId": "planner:test", "parseSuccess": True, "fallbackUsed": False},
            "workers": workers,
            "synthesis": {"modelId": "test-model", "invocationId": "synthesis:test", "status": "completed"},
            "verifier": {"modelId": "test-model", "invocationId": "verifier:test", "status": "completed", "verdict": "pass"},
        },
    }


def test_difficult_workforce_benchmark_passes_only_with_real_architecture_evidence() -> None:
    result = score_module.score_run(SPEC, _passing_run())
    assert result["status"] == "pass", result
    assert set(result["roleFamilySlots"]) == {"backend", "database", "payments", "security", "quality"}
    assert result["workerInvocationCount"] == 5


def test_difficult_workforce_benchmark_rejects_fake_single_model_execution() -> None:
    run = _passing_run()
    run["selectionReceipt"]["mcpCalls"] = []
    run["executionReceipt"]["planner"]["fallbackUsed"] = True
    run["executionReceipt"]["workers"] = run["executionReceipt"]["workers"][:1]
    result = score_module.score_run(SPEC, run)
    assert result["status"] == "fail"
    assert "mcp_sequence_missing_or_out_of_order" in result["issues"]
    assert "planner_fallback_used" in result["issues"]
    assert any(issue.startswith("insufficient_distinct_worker_invocations:") for issue in result["issues"])
