"""Bounded model decision data, never a memory owner or write authority.

The runtime supplies already governed original rows, source custody and model
identity. This contract performs no IO, retrieval, model call or publication.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Callable

POLICY = "agentlas.core-memory-curation.v2"
INPUT_SCHEMA = "agentlas.memory-curation-input.v1"
PENDING_SCHEMA = "agentlas.memory-curation-pending.v1"
ACTIONS = ("add", "revise", "merge", "supersede", "noop", "defer")
KINDS = {"fact", "decision", "preference", "risk", "procedure", "hypothesis"}
SCOPES = {"agent_repo", "project", "user_identity", "session"}
_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:._/-]{0,511}$")


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode("utf-8")).hexdigest()


def origin(kind: str, identifier: str, revision: str | int) -> dict[str, str]:
    if kind not in {"memory-ticket", "host-summary", "memory"} or not isinstance(identifier, str) or not _REF.fullmatch(identifier) or ".." in identifier:
        raise ValueError("memory_origin_invalid")
    if isinstance(revision, bool) or not isinstance(revision, (str, int)) or len(str(revision)) > 256:
        raise ValueError("memory_origin_revision_invalid")
    return {"kind": kind, "id": identifier, "revision": str(revision)}


def packet(source: dict[str, Any], originals: list[dict[str, Any]], *,
           store_revision: int, model_binding: str | None) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return the model packet and a private host snapshot, without path values."""
    if len(originals) > 40 or type(store_revision) is not int or store_revision < 0:
        raise ValueError("memory_snapshot_invalid")
    refs = [origin("memory-ticket", source["ticket_ref"], source["source_revision"]),
            origin("host-summary", source["source_ref"], source["source_revision"])]
    data = {k: v for k, v in source.items() if k != "project_path"}
    if source.get("project_path"):
        data["project_path_hash"] = hashlib.sha256(source["project_path"].encode("utf-8")).hexdigest()
    existing = []
    for row in originals:
        if len(row.get("content", "")) > 4000 or len(row.get("content_native") or "") > 4000:
            raise ValueError("memory_snapshot_size")
        ref = origin("memory", row["id"], row["revision"])
        refs.append(ref)
        existing.append({key: row[key] for key in ("id", "scope", "kind", "content", "content_native", "revision", "confidence", "sensitivity")})
    value = {"schema_version": INPUT_SCHEMA, "data": data, "existing_memories": existing,
             "origin_refs": refs, "policy_version": POLICY, "input_revision": store_revision,
             "require_no_tools": True, "timeout_ms": 20000, "operations": list(ACTIONS)}
    if len(json.dumps(value, ensure_ascii=False).encode("utf-8")) > 96 * 1024:
        raise ValueError("memory_snapshot_size")
    snapshot = {"policy": POLICY, "source": {key: source.get(key) for key in (
        "owner_namespace", "actor_id", "context_key", "source_ref", "source_revision", "ticket_ref", "project_ref", "project_path", "intake_epoch", "source_input_digest")},
        "source_digest": digest(source), "model_binding": model_binding,
        "input_revision": store_revision, "originals": originals, "allowed_origins": refs}
    snapshot["input_digest"] = digest([value, snapshot])
    value["input_digest"] = snapshot["input_digest"]
    return value, snapshot


def validate(output: Any, snapshot: dict[str, Any], safe_text: Callable[[Any], str]) -> dict[str, Any]:
    """Model prose can choose only exact IDs in this original host inventory."""
    if not isinstance(output, dict) or output.get("action") not in ACTIONS:
        raise ValueError("memory_decision_invalid")
    allowed = {"action", "reason", "content", "content_native", "scope", "kind", "source_ref",
               "target_memory_ids", "target_memory_id", "target_refs", "origin_refs", "input_digest", "input_revision", "schema_version"}
    if set(output) - allowed:
        raise ValueError("memory_decision_fields_invalid")
    if "schema_version" in output and output["schema_version"] not in {"agentlas.memory-curation-output.v1", "agentlas.memory-curation-decision.v1"}:
        raise ValueError("memory_decision_schema_invalid")
    if "input_digest" in output and output["input_digest"] != snapshot["input_digest"]:
        raise ValueError("memory_decision_input_changed")
    if "input_revision" in output and (type(output["input_revision"]) is not int or output["input_revision"] != snapshot["input_revision"]):
        raise ValueError("memory_decision_revision_changed")
    source = snapshot["source"]
    if "source_ref" in output and output["source_ref"] != source["source_ref"]:
        raise ValueError("memory_decision_source_changed")
    reason = str(output.get("reason") or "automatic_model_curation")
    result = {"action": output["action"], "reason": reason if re.fullmatch(r"[a-z0-9_]{1,80}", reason) else "automatic_model_curation"}
    if result["action"] in {"noop", "defer"}:
        if any(key in output for key in ("content", "content_native", "target_refs", "target_memory_ids", "target_memory_id")):
            raise ValueError("memory_decision_nonwrite_payload")
        return result
    content = safe_text(output.get("content"))
    scope, kind = output.get("scope"), output.get("kind")
    if not content or scope not in SCOPES or kind not in KINDS or (scope == "project" and not source["project_ref"] and not source["project_path"]):
        raise ValueError("memory_proposal_invalid")
    result.update(content=content, scope=scope, kind=kind, origin_refs=[])
    if output.get("content_native") is not None:
        native = safe_text(output["content_native"])
        if not native:
            raise ValueError("memory_native_invalid")
        result["content_native"] = native
    target_ids = output.get("target_memory_ids", [output["target_memory_id"]] if "target_memory_id" in output else [])
    target_refs = output.get("target_refs")
    if target_refs is not None:
        if not isinstance(target_refs, list) or any(not isinstance(ref, dict) or set(ref) != {"id", "revision"} for ref in target_refs):
            raise ValueError("memory_target_refs_invalid")
        if target_ids and target_ids != [ref["id"] for ref in target_refs]:
            raise ValueError("memory_target_refs_conflict")
        target_ids = [ref["id"] for ref in target_refs]
    if not isinstance(target_ids, list) or len(target_ids) > 8 or any(not isinstance(ref, str) for ref in target_ids) or len(set(target_ids)) != len(target_ids):
        raise ValueError("memory_target_invalid")
    expected = 0 if result["action"] == "add" else 1 if result["action"] in {"revise", "supersede"} else None
    if (expected is not None and len(target_ids) != expected) or (result["action"] == "merge" and len(target_ids) < 2):
        raise ValueError("memory_target_count_invalid")
    known = {row["id"]: row for row in snapshot["originals"]}
    targets = []
    for index, identifier in enumerate(target_ids):
        row = known.get(identifier)
        if not row or row["scope"] != scope or row["kind"] != kind:
            raise ValueError("memory_target_authority_mismatch")
        if target_refs is not None and (type(target_refs[index]["revision"]) is not int or target_refs[index]["revision"] != row["revision"]):
            raise ValueError("memory_target_revision_changed")
        targets.append({"id": identifier, "revision": row["revision"], "row_digest": row["row_digest"]})
    if any(known[ref].get("content_native") for ref in target_ids) and "content_native" not in result:
        if len(target_ids) != 1 or content != known[target_ids[0]]["content"]:
            raise ValueError("memory_native_preservation_required")
    policies = {known[ref]["authority_digest"] for ref in target_ids}
    if len(policies) > 1:
        raise ValueError("memory_target_applicability_mismatch")
    refs = output.get("origin_refs", [])
    if not isinstance(refs, list) or len(refs) > 32:
        raise ValueError("memory_origin_invalid")
    permitted = {digest(ref) for ref in snapshot["allowed_origins"]}
    for ref in refs:
        if not isinstance(ref, dict) or set(ref) != {"kind", "id", "revision"}:
            raise ValueError("memory_origin_invalid")
        normalized = origin(ref["kind"], ref["id"], ref["revision"])
        if digest(normalized) not in permitted:
            raise ValueError("memory_origin_not_supplied")
        if normalized not in result["origin_refs"]:
            result["origin_refs"].append(normalized)
    result["targets"] = targets
    return result


def pending(decision: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
    return {"schema_version": PENDING_SCHEMA, "binding": {key: snapshot[key] for key in (
        "policy", "source_digest", "model_binding", "input_digest", "input_revision")}, "decision": decision, "decision_digest": digest(decision)}


def reusable(value: Any, snapshot: dict[str, Any]) -> bool:
    """Unknown model identity never permits cross-dispatch result reuse."""
    return bool(isinstance(value, dict) and value.get("schema_version") == PENDING_SCHEMA
                and snapshot["model_binding"] and value.get("binding") == pending({}, snapshot)["binding"]
                and isinstance(value.get("decision"), dict) and value.get("decision_digest") == digest(value["decision"]))

# Only a host-created callable registration supplies a stable model cache key.
# Neither a returned JSON packet nor a requestedRuntime field can register it.
import weakref
_MODEL_BINDINGS: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()


def bind_model_runner(runner: Callable, identity: str, assert_current: Callable[[], None]) -> Callable:
    if not isinstance(identity, str) or not re.fullmatch(r"[a-f0-9]{64}", identity) or not callable(assert_current):
        raise ValueError("memory_model_binding_invalid")
    _MODEL_BINDINGS[runner] = (identity, assert_current)
    return runner


def model_binding(runner: Callable | None) -> str | None:
    try:
        value = _MODEL_BINDINGS.get(runner) if runner else None
    except TypeError:
        value = None
    if value:
        value[1]()
        return value[0]
    return None


def validate_pending(value: dict[str, Any], snapshot: dict[str, Any], safe_text: Callable[[Any], str]) -> dict[str, Any]:
    stored = value["decision"]
    model_form = {key: item for key, item in stored.items() if key != "targets"}
    if stored.get("targets"):
        model_form["target_refs"] = [{"id": ref["id"], "revision": ref["revision"]} for ref in stored["targets"]]
    checked = validate(model_form, snapshot, safe_text)
    if checked != stored:
        raise ValueError("memory_pending_decision_invalid")
    return checked
