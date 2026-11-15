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
# Embedded defaults. The values in force come from the canonical ruleset (kinds.stored, scopes.stored) through
# stored_kinds()/stored_scopes(); a missing or malformed file falls back to exactly these.
KINDS = {"fact", "decision", "preference", "risk", "procedure", "hypothesis"}
SCOPES = {"agent_repo", "project", "user_identity", "session"}


def _ruleset_tokens(path: str, default: Any) -> frozenset[str]:
    try:
        from .one_workspace import rule_tokens
        return rule_tokens(path, default)
    except Exception:
        return frozenset(default)


def stored_kinds() -> frozenset[str]:
    return _ruleset_tokens("kinds.stored", KINDS)


def stored_scopes() -> frozenset[str]:
    return _ruleset_tokens("scopes.stored", SCOPES)
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
    data = {k: v for k, v in source.items() if k not in ("project_path", "in_project")}  # in_project is for code, not the model
    if source.get("project_path"):
        data["project_path_hash"] = hashlib.sha256(source["project_path"].encode("utf-8")).hexdigest()
    if source.get("project_path") or source.get("project_ref"):
        # flaw 9: a folder-bound turn showed "project_ref": null and the model read "no project bound". Say that one is
        # bound (a flag, never the path or the name); an unbound turn's packet is byte-for-byte what it was.
        data["project_bound"] = True
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
    kept = {key: source.get(key) for key in (
        "owner_namespace", "actor_id", "context_key", "source_ref", "source_revision", "ticket_ref", "project_ref", "project_path", "intake_epoch", "source_input_digest")}
    if "in_project" in source:  # only when the host said so: a snapshot of an older queued turn keeps its digest
        kept["in_project"] = bool(source["in_project"])
    snapshot = {"policy": POLICY, "source": kept,
        "source_digest": digest(source), "model_binding": model_binding,
        "input_revision": store_revision, "originals": originals, "allowed_origins": refs}
    snapshot["input_digest"] = digest([value, snapshot])
    value["input_digest"] = snapshot["input_digest"]
    return value, snapshot


# --- format tolerance ---------------------------------------------------------
# A curator reply that is merely written differently (case, wrapper, a plural, a string number, a trailing
# period, an extra field) is corrected by code and never costs a model call. A scope or
# kind the model left out is taken from the value the host itself supplied with the observations when that
# value is one and the same everywhere (never user_identity: correction never promotes to personal memory).
# Whatever code still cannot read as exactly what the model meant (unknown scope or kind, nothing supplied,
# a project scope without a project) is never guessed and never widened: it gets ONE retry that says what
# was wrong; if that also fails the operation is deferred (`memory_format_unrecoverable`, its source stays in
# memory_operations.payload_json) and process_format_deferred() runs it again on a later curation, at most
# three attempts in all. Provenance guards (input digest, revision, source ref) are never corrected: those
# mean the world changed.
_ACTION_ALIASES = {
    "create": "add", "new": "add", "insert": "add", "save": "add", "write": "add", "record": "add", "append": "add",
    "update": "revise", "edit": "revise", "modify": "revise", "amend": "revise", "rewrite": "revise",
    "replace": "supersede", "override": "supersede", "combine": "merge", "consolidate": "merge",
    "skip": "noop", "none": "noop", "ignore": "noop", "nothing": "noop", "no_op": "noop", "no_change": "noop", "discard": "noop",
    "postpone": "defer", "later": "defer", "wait": "defer", "hold": "defer",
}
_KIND_ALIASES = {"preferences": "preference", "decisions": "decision", "facts": "fact",
                 "risks": "risk", "procedures": "procedure", "hypotheses": "hypothesis"}
_SCOPE_ALIASES = {"agentrepo": "agent_repo", "agent_repo": "agent_repo", "agent": "agent_repo", "agents": "agent_repo",
                  "agent_repository": "agent_repo", "projects": "project", "sessions": "session"}
_WRAPPERS = ("decision", "result", "output", "curation", "response")
_CONTENT_ALIASES = ("memory", "text", "summary", "note", "learning")
_KNOWN_KEYS = {"action", "reason", "content", "content_native", "scope", "kind", "source_ref", "target_memory_ids",
               "target_memory_id", "target_refs", "origin_refs", "input_digest", "input_revision", "schema_version"}
RETRYABLE = frozenset({
    "memory_decision_invalid", "memory_decision_schema_invalid", "memory_proposal_invalid", "memory_native_invalid",
    "memory_target_refs_invalid", "memory_target_refs_conflict", "memory_target_invalid", "memory_target_count_invalid",
    "memory_target_authority_mismatch", "memory_native_preservation_required", "memory_target_applicability_mismatch",
    "memory_origin_invalid", "memory_origin_not_supplied", "memory_origin_revision_invalid", "memory_personal_too_long"})
# Deferred only because the reply could not be read, the model did not answer, or the store changed under the model's feet; process_format_deferred() runs these again.
# `memory_format_corrected` is no longer written; it stays so rows held by an earlier build are still retried.
# (memory B2, D1): a model that exited at once (`memory_model_unavailable`), an empty reply (`memory_model_output_invalid`) and a store that changed while the model was thinking
# (`memory_input_revision_changed`) are held work too. They were deferred for good: only a timeout (which ends as `model_output_invalid`) used to be tried again.
FORMAT_DEFERRED_REASONS = frozenset({"memory_format_corrected", "memory_format_unrecoverable", "model_output_invalid", "memory_model_unavailable", "memory_model_output_invalid", "memory_input_revision_changed"})
# The model did not answer: the rows held behind it would only fail the same way, so a pass that saw this reason does not run them.
MODEL_NOT_ANSWERING = frozenset({"model_output_invalid", "memory_model_unavailable", "memory_model_output_invalid"})
_HINTS = {
    "memory_decision_invalid": "Reply with exactly one JSON object whose action is one of: " + ", ".join(ACTIONS) + ".",
    "memory_proposal_invalid": "A write needs non-empty content, a kind (" + ", ".join(sorted(KINDS)) + ") and a scope ("
                               + ", ".join(sorted(SCOPES)) + "); project scope needs a project in the input.",
    "memory_target_count_invalid": "add takes no target; revise and supersede take exactly one existing memory id; merge takes two or more.",
    "memory_target_authority_mismatch": "Targets must be ids from existing_memories with the same scope and kind as the new memory.",
    "memory_origin_not_supplied": "origin_refs may only repeat entries from the input origin_refs.",
    "memory_personal_too_long": "A user_identity line must be short (one sentence): shorten the content, or choose another scope.",
}


_EDGE = " \t\r\n.,;:!?\"'`()[]{}*"


def _token(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return re.sub(r"[\s\-]+", "_", value.strip(_EDGE).lower()) or None


def norm_kind(value: Any) -> str | None:
    token = _token(value)
    token = _KIND_ALIASES.get(token, token)
    return token if token in stored_kinds() else None


def norm_scope(value: Any) -> str | None:
    token = _token(value)
    token = _SCOPE_ALIASES.get(token, token)
    return token if token in stored_scopes() else None


def norm_confidence(value: Any) -> str | None:
    token = _token(value)
    return token if token in {"high", "medium", "low"} else None


def supplied_values(packet: Any) -> dict[str, str]:
    """The kind and scope the host itself attached to the observations, when they all agree on one value."""
    items = ((packet or {}).get("data") or {}).get("observations") if isinstance(packet, dict) else None
    found: dict[str, set[str]] = {"kind": set(), "scope": set()}
    for item in items if isinstance(items, list) else []:
        if isinstance(item, dict):
            for name, norm in (("kind", norm_kind), ("scope", norm_scope)):
                value = norm(item.get("suggested_" + name))
                if value:
                    found[name].add(value)
    return {name: next(iter(values)) for name, values in found.items() if len(values) == 1 and values != {"user_identity"}}


def parse_model_json(text: Any) -> Any:
    """First JSON object in a model reply, tolerating code fences and prose around it; ValueError if none."""
    if not isinstance(text, str):
        return text
    body = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", body, re.S | re.I)
    for candidate in ([fenced.group(1).strip()] if fenced else []) + [body]:
        try:
            return json.loads(candidate)
        except ValueError:
            pass
    start, decoder = body.find("{"), json.JSONDecoder()
    while start != -1:
        try:
            return decoder.raw_decode(body[start:])[0]
        except ValueError:
            start = body.find("{", start + 1)
    raise ValueError("memory_decision_invalid")


def repair(output: Any, snapshot: dict[str, Any], supplied: dict[str, str] | None = None) -> Any:
    """Correct spelling-level differences. Never raises, never touches provenance fields, never invents meaning.

    `supplied` (from supplied_values) fills only a kind or scope the model left out entirely."""
    try:
        if isinstance(output, str):
            output = parse_model_json(output)
        if isinstance(output, list) and len(output) == 1:
            output = output[0]
        for _ in range(2):
            if isinstance(output, dict) and len(output) == 1 and isinstance(next(iter(output.values())), dict) \
                    and _token(next(iter(output))) in _WRAPPERS:
                output = next(iter(output.values()))
        if not isinstance(output, dict):
            return output
        fixed: dict[str, Any] = {}
        for key, value in output.items():
            name = _token(key) if isinstance(key, str) else None
            if name in _KNOWN_KEYS and name not in fixed:
                fixed[name] = value
            elif name in _CONTENT_ALIASES and "content" not in output:
                fixed.setdefault("content", value)
        action = _token(fixed.get("action"))
        action = _ACTION_ALIASES.get(action, action)
        if action in ACTIONS:
            fixed["action"] = action
        if isinstance(fixed.get("input_revision"), str) and fixed["input_revision"].strip().isdigit():
            fixed["input_revision"] = int(fixed["input_revision"])
        if action in {"noop", "defer"}:
            return {k: v for k, v in fixed.items() if k in {"action", "reason", "input_digest", "input_revision", "source_ref", "schema_version"}}
        if action not in ACTIONS:
            return fixed
        if isinstance(fixed.get("content"), str):
            fixed["content"] = fixed["content"].strip()
        if fixed.get("content_native") in ("", None):
            fixed.pop("content_native", None)
        kind, scope = norm_kind(fixed.get("kind")), norm_scope(fixed.get("scope"))
        if kind is None and fixed.get("kind") in (None, ""):
            kind = (supplied or {}).get("kind")
        if scope is None and fixed.get("scope") in (None, ""):
            scope = (supplied or {}).get("scope")
        # Still unreadable: leave the field as the model wrote it so validate() asks for ONE retry; never guess or widen.
        if kind is not None:
            fixed["kind"] = kind
        if scope is not None:
            fixed["scope"] = scope
        ids = fixed.pop("target_memory_ids", None)
        single = fixed.pop("target_memory_id", None)
        if ids is None and single is not None:
            ids = single
        if isinstance(ids, str):
            ids = [ids]
        elif isinstance(ids, list):
            ids = [item.get("id") if isinstance(item, dict) else item for item in ids]
        refs = fixed.get("target_refs")
        if isinstance(refs, list):
            known = {row["id"]: row for row in snapshot.get("originals", [])}
            clean = []
            for ref in refs:
                if isinstance(ref, str):
                    ref = {"id": ref}
                if not isinstance(ref, dict) or "id" not in ref:
                    clean = None
                    break
                revision = ref.get("revision", known.get(ref["id"], {}).get("revision"))
                if isinstance(revision, str) and revision.strip().isdigit():
                    revision = int(revision)
                clean.append({"id": ref["id"], "revision": revision})
            if clean is not None:
                fixed["target_refs"] = clean
                if ids is not None and ids == [ref["id"] for ref in clean]:
                    ids = None
        if ids is not None:
            fixed["target_memory_ids"] = ids
        origins = fixed.get("origin_refs")
        if isinstance(origins, list):
            fixed["origin_refs"] = [{"kind": o.get("kind"), "id": o.get("id"), "revision": str(o.get("revision"))}
                                    if isinstance(o, dict) and {"kind", "id", "revision"} <= set(o) else o for o in origins]
        return fixed
    except Exception:
        return output


def feedback(code: str) -> dict[str, str]:
    """What a retry tells the model: a stable code and one fix line, never the rejected content."""
    return {"code": code, "fix": _HINTS.get(code, "Reply with one JSON object that follows the output contract exactly.")}


class FormatUnrecoverable(ValueError):
    def __init__(self, code: str):
        super().__init__("memory_format_unrecoverable")
        self.code = code


def _same_kind(row: dict[str, Any], scope: str, kind: str) -> bool:
    """A target is accepted when its kind, read the way stored lines are read, is the new line's corrected kind."""
    if row["kind"] == kind:
        return True
    from . import memory_classify
    rs = memory_classify.active()
    return rs is not None and memory_classify.read_kind(rs, scope, row["kind"]) == kind


def _target_ids(output: dict[str, Any]) -> list[str] | None:
    refs, ids = output.get("target_refs"), output.get("target_memory_ids")
    if isinstance(refs, list) and all(isinstance(r, dict) and isinstance(r.get("id"), str) for r in refs):
        return [r["id"] for r in refs]
    if isinstance(ids, list) and all(isinstance(i, str) for i in ids):
        return list(ids)
    return [output["target_memory_id"]] if isinstance(output.get("target_memory_id"), str) else ([] if ids is None and refs is None else None)


def _as_new_line(output: dict[str, Any]) -> dict[str, Any]:
    fixed = {k: v for k, v in output.items() if k not in ("target_refs", "target_memory_ids", "target_memory_id")}
    fixed["action"] = "add"
    return fixed


def classify_decision(output: Any, packet_value: Any, snapshot: dict[str, Any], *, home_state: Any = "home", rules_on: Any = False) -> Any:
    """ the model's answer is corrected by code BEFORE validation, the duplicate check and the forget-stamp check
    (so a text forgotten as one kind cannot return as another): kind corrections, the Personal admission, a resident
    actor's agent_repo line inside a project becoming a project line, a replacement that is not similar enough becoming a
    new line. Never raises except for a too-long Personal line (the existing one retry). With no usable rules the output
    is returned untouched."""
    from . import memory_classify as mc
    rs = mc.active()
    if rs is None or not isinstance(output, dict) or output.get("action") not in {"add", "revise", "merge", "supersede"}:
        return output
    scope, kind, content = output.get("scope"), output.get("kind"), output.get("content")
    if scope not in stored_scopes() or kind not in stored_kinds() or not isinstance(content, str) or not content.strip():
        return output  # validate() says what is wrong
    from .memory_scopes import actor_kind, personal_set
    source = snapshot["source"]
    data = (packet_value or {}).get("data") or {}
    outcome = mc.stage1(rs, scope=scope, kind=kind, confidence=mc.personal_min_confidence(rs),  # the model's confidence no longer decides (')
                        text=content.strip(), surface="engine-hook", project=bool(source.get("project_ref") or source.get("project_path")),
                        in_project=bool(source.get("in_project")), actor_kind=actor_kind(source.get("actor_id")), owner_spoke=None,
                        home_state=home_state, personal=personal_set(), rules_on=rules_on, personal_conversation=False)
    if outcome.get("askAgain"):
        raise ValueError("memory_personal_too_long")
    if outcome.get("discard"):
        return {"action": "noop", "reason": "memory_discarded"}
    if "modelCall" in outcome:
        return output
    new_scope, new_kind = outcome["scope"], outcome.get("kind", kind)
    fixed = dict(output)
    if new_scope == "session":
        fixed = _as_new_line(fixed)
        fixed["scope"] = "session"
        return fixed
    fixed["scope"], fixed["kind"] = new_scope, new_kind
    ids = _target_ids(fixed)
    if ids:
        known = {row["id"]: row for row in snapshot.get("originals", [])}
        rows = [known.get(i) for i in ids]
        if all(rows):
            floor = mc.merge_overlap_min(rs)
            from .one_workspace import _recall_tokens
            mine = _recall_tokens(content)

            def overlap(other: str) -> float:
                theirs = _recall_tokens(other)
                union = mine | theirs
                return len(mine & theirs) / len(union) if union else 0.0

            def containment(other: str) -> float:
                theirs = _recall_tokens(other)
                shorter = min(len(mine), len(theirs))
                return len(mine & theirs) / shorter if shorter else 0.0
            close = max(overlap(r["content"]) for r in rows) >= floor
            named_floor = mc.named_containment_min(rs)
            if not close and len(rows) == 1 and fixed.get("action") in ("revise", "supersede") and named_floor is not None:
                # The model named exactly one line: a revision that adds words ("...; jest is removed") or changes one word of a
                # short line is still that line ((b)). A merge of several lines keeps the stricter similarity.
                close = containment(rows[0]["content"]) >= named_floor
            if any(r["scope"] != new_scope for r in rows) or not close:
                fixed = _as_new_line(fixed)
    return fixed


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
    content = safe_text(output["content"]) if isinstance(output.get("content"), str) else ""
    scope, kind = output.get("scope"), output.get("kind")
    if not content or scope not in stored_scopes() or kind not in stored_kinds() or (scope == "project" and not source["project_ref"] and not source["project_path"]):
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
        if not row or row["scope"] != scope or not _same_kind(row, scope, kind):
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
