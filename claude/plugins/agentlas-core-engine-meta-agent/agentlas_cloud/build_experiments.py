"""Collect comparable, host-executed agent-build experiments.

This module does not run a model, read package files, verify human identity, or
judge art. A host supplies an executor and, optionally, an artifact hasher. The
executor is called once for each case/repetition/variant and reports what it
actually observed. Returned metadata is evidence *from that host*, not proof
that the host or its tools are truthful.

Minimal plan::

    {
      "experimentId": "motion-eval-1",
      "variants": {
        "baseline": {"packageHash": "sha256:<64 hex>"},
        "candidate": {"packageHash": "sha256:<64 hex>"}
      },
      "conditions": {
        "runtimeId": "codex", "provider": "provider", "modelId": "model",
        "requestedEffort": "high",  # null for a fixed-effort runtime
        "toolInventoryDigest": "sha256:<64 hex>",
        "toolPolicyDigest": "sha256:<64 hex>",
        "environmentDigest": "sha256:<64 hex>",
        "generationSettingsDigest": "sha256:<64 hex>"
      },
      "cases": [{"id": "case-1", "input": {"prompt": "..."}, "inputAssets": []}],
      "repetitions": 2
    }

The input is an immutable JSON request, not the bytes behind a path or URL.
Each case declares ``inputAssets`` as ``{ref, sha256}`` entries, or an empty
list if it has no external inputs. The host must supply the pinned bytes to
both runs. The input hash binds the JSON request and declared assets; this
module does not establish that a model actually consumed those bytes or that
the host's observations are true.

The executor receives a JSON-compatible request containing the exact input,
its ``inputHash``, the expected package hash and conditions. A completed
response reports ``invocationId``, ``packageHash``, ``inputHash``,
``actualConditions``, ``appliedEffort``, ``effortEvidence`` and ``artifacts``.
An artifact is ``{ref, sha256}``. Optional ``technicalChecks`` and ``playback``
are kept separate; neither creates a creative verdict. An artifact hasher takes
one opaque ref and returns the digest observed by the host. Package and input
hashers bracket each executor call. Execution requires a package hasher and,
when any case declares external assets, an input hasher. Hashers must resolve only host-authorized
references; this module never opens a path or treats a ref as authority.
Every execution slot must use its own artifact ref, even when bytes are equal;
a host can create distinct run-bound refs for an immutable shared blob.
If a supplied package or input hasher cannot confirm the pre-run digest, that
slot is blocked before the executor starts. An absent hasher is unverified.
The executor can stop the whole experiment with ``stopExperiment: true`` or
the machine-readable reason ``owner_denied`` or ``user_cancelled``; subsequent
slots are recorded as not run. Executor responses are frozen as bounded JSON
before another callback can change them.

``validate_experiment`` can also consume already-collected responses, each
tagged with ``caseId``, ``repetition`` and ``variant`` and host-observed
``packageHashBefore``/``packageHashAfter`` plus
``inputHashesBefore``/``inputHashesAfter`` maps. Human or independent model
pairwise reviews may be recorded separately; choices are not aggregated into a
manufactured creativity score or an overall pass.
"""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
import hashlib
import inspect
import json
import math
import re
from typing import Any, Callable, Mapping, Sequence


SPEC_SCHEMA = "agentlas.build-experiment-spec.v1"
REPORT_SCHEMA = "agentlas.build-experiment-report.v1"
REQUEST_SCHEMA = "agentlas.build-experiment-request.v1"
_HASH = re.compile(r"^sha256:[0-9a-f]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@-]{0,255}$")
_VARIANTS = ("baseline", "candidate")
_CONDITION_TEXT = ("runtimeId", "provider", "modelId")
_CONDITION_DIGESTS = (
    "toolInventoryDigest", "toolPolicyDigest", "environmentDigest",
    "generationSettingsDigest",
)
_EXECUTION_STATUSES = {"completed", "failed", "blocked", "not_run"}
_GLOBAL_STOP_REASONS = {"owner_denied", "desktop_approval_denied", "user_cancelled", "user_canceled"}
# These limits bound a malformed plan before it can request host invocations.
MAX_SPEC_BYTES = 2 * 1024 * 1024
MAX_CASE_INPUT_BYTES = 256 * 1024
MAX_CONDITIONS_BYTES = 64 * 1024
MAX_EXECUTOR_RESPONSE_BYTES = 256 * 1024
MAX_CASES = 64
MAX_REPETITIONS = 8
MAX_EXECUTIONS = 256
MAX_ARTIFACTS_PER_RUN = 64
MAX_TECHNICAL_CHECKS_PER_RUN = 128
MAX_REVIEWS = 512


class ExperimentSpecError(ValueError):
    """The experiment cannot be scheduled from the supplied plan."""


def _json_value(value: Any) -> bool:
    if value is None or type(value) in (str, bool, int):
        return True
    if type(value) is float:
        return math.isfinite(value)
    if isinstance(value, list):
        return all(_json_value(item) for item in value)
    if isinstance(value, dict):
        return all(isinstance(key, str) and _json_value(item) for key, item in value.items())
    return False


def _canonical(value: Any) -> str:
    try:
        if not _json_value(value):
            raise ValueError("not a JSON value")
        return json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError, RecursionError) as exc:
        raise ExperimentSpecError("value_not_canonical_json") from exc


def _bounded_canonical(value: Any, maximum: int, reason: str) -> str:
    """Serialize a JSON value without collecting an unbounded encoded result."""
    try:
        if not _json_value(value):
            raise ValueError("not a JSON value")
        encoder = json.JSONEncoder(ensure_ascii=False, sort_keys=True,
                                   separators=(",", ":"), allow_nan=False)
        chunks: list[str] = []
        size = 0
        for chunk in encoder.iterencode(value):
            if len(chunk) > maximum:
                raise ExperimentSpecError(reason)
            size += len(chunk.encode("utf-8"))
            if size > maximum:
                raise ExperimentSpecError(reason)
            chunks.append(chunk)
        return "".join(chunks)
    except ExperimentSpecError:
        raise
    except (TypeError, ValueError, RecursionError, UnicodeEncodeError) as exc:
        raise ExperimentSpecError("value_not_canonical_json") from exc


def canonical_hash(value: Any) -> str:
    """Hash a JSON value with a stable encoding; no external state is read."""
    try:
        data = _canonical(value).encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ExperimentSpecError("value_not_canonical_json") from exc
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _identifier(value: Any) -> bool:
    return (isinstance(value, str) and bool(_ID.fullmatch(value))
            and all(part not in {"", ".", ".."} for part in value.split("/")))


def _digest(value: Any) -> bool:
    return isinstance(value, str) and bool(_HASH.fullmatch(value))


def _plan(spec: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(spec, Mapping):
        raise ExperimentSpecError("spec_must_be_object")
    # Freeze inputs before the first callback, including nested objects. This
    # also rejects non-JSON values and non-finite numbers.
    try:
        frozen = json.loads(_bounded_canonical(spec, MAX_SPEC_BYTES, "spec_too_large"))
    except (UnicodeEncodeError, json.JSONDecodeError) as exc:
        raise ExperimentSpecError("value_not_canonical_json") from exc
    if frozen.get("schemaVersion", SPEC_SCHEMA) != SPEC_SCHEMA:
        raise ExperimentSpecError("spec_schema_invalid")
    if not _identifier(frozen.get("experimentId")):
        raise ExperimentSpecError("experiment_id_invalid")
    variants = frozen.get("variants")
    if not isinstance(variants, dict) or set(variants) != set(_VARIANTS):
        raise ExperimentSpecError("variants_invalid")
    for variant in _VARIANTS:
        if not isinstance(variants[variant], dict) or not _digest(variants[variant].get("packageHash")):
            raise ExperimentSpecError(f"{variant}_package_hash_invalid")
    conditions = frozen.get("conditions")
    if not isinstance(conditions, dict):
        raise ExperimentSpecError("conditions_invalid")
    _bounded_canonical(conditions, MAX_CONDITIONS_BYTES, "conditions_too_large")
    if any(not _identifier(conditions.get(key))
           or conditions[key].strip().lower() in {"unknown", "unavailable", "not-observable"}
           for key in _CONDITION_TEXT):
        raise ExperimentSpecError("condition_identity_missing")
    if "requestedEffort" not in conditions or not (
        conditions["requestedEffort"] is None
        or _identifier(conditions["requestedEffort"])
        and conditions["requestedEffort"].lower() not in {"unknown", "unavailable", "not-observable"}
    ):
        raise ExperimentSpecError("requested_effort_invalid")
    if any(not _digest(conditions.get(key)) for key in _CONDITION_DIGESTS):
        raise ExperimentSpecError("condition_digest_invalid")
    cases = frozen.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ExperimentSpecError("cases_missing")
    if len(cases) > MAX_CASES:
        raise ExperimentSpecError("case_limit_exceeded")
    ids: set[str] = set()
    for case in cases:
        if (not isinstance(case, dict) or not _identifier(case.get("id")) or "input" not in case
                or not isinstance(case.get("inputAssets"), list)):
            raise ExperimentSpecError("case_invalid")
        if case["id"] in ids:
            raise ExperimentSpecError("case_id_duplicate")
        ids.add(case["id"])
        canonical_hash(case["input"])
        refs: set[str] = set()
        for asset in case["inputAssets"]:
            if (not isinstance(asset, dict) or set(asset) != {"ref", "sha256"}
                    or not _identifier(asset.get("ref")) or not _digest(asset.get("sha256"))
                    or asset["ref"] in refs):
                raise ExperimentSpecError("input_asset_invalid")
            refs.add(asset["ref"])
        _bounded_canonical({"input": case["input"], "inputAssets": case["inputAssets"]},
                           MAX_CASE_INPUT_BYTES, "case_input_too_large")
    repetitions = frozen.get("repetitions", 1)
    if type(repetitions) is not int or repetitions < 1:
        raise ExperimentSpecError("repetitions_invalid")
    if repetitions > MAX_REPETITIONS:
        raise ExperimentSpecError("repetition_limit_exceeded")
    if len(cases) * repetitions * len(_VARIANTS) > MAX_EXECUTIONS:
        raise ExperimentSpecError("execution_limit_exceeded")
    frozen["repetitions"] = repetitions
    return frozen


def _slots(plan: Mapping[str, Any]):
    for case in plan["cases"]:
        for repetition in range(1, plan["repetitions"] + 1):
            # Alternation is deterministic, not a claim of randomized blinding.
            variants = _VARIANTS if repetition % 2 else tuple(reversed(_VARIANTS))
            for variant in variants:
                yield case, repetition, variant


def _input_hash(case: Mapping[str, Any]) -> str:
    return canonical_hash({"input": case["input"], "inputAssets": case["inputAssets"]})


def _request(plan: Mapping[str, Any], case: Mapping[str, Any], repetition: int, variant: str) -> dict[str, Any]:
    conditions = deepcopy(plan["conditions"])
    return {
        "schemaVersion": REQUEST_SCHEMA,
        "experimentId": plan["experimentId"],
        "caseId": case["id"],
        "repetition": repetition,
        "variant": variant,
        "packageHash": plan["variants"][variant]["packageHash"],
        "input": deepcopy(case["input"]),
        "inputAssets": deepcopy(case["inputAssets"]),
        "inputHash": _input_hash(case),
        "conditions": conditions,
        "conditionsHash": canonical_hash(conditions),
    }


def _global_stop_reason(response: Mapping[str, Any]) -> str | None:
    reason = response.get("reasonCode")
    if isinstance(reason, str) and reason in _GLOBAL_STOP_REASONS:
        return reason
    if response.get("stopExperiment") is True:
        explicit = response.get("stopReasonCode")
        if _identifier(explicit):
            return explicit
        return reason if _identifier(reason) else "host_requested_stop"
    return None


def run_experiment(
    spec: Mapping[str, Any],
    executor: Callable[[dict[str, Any]], Mapping[str, Any]],
    *,
    artifact_hasher: Callable[[str], str] | None = None,
    package_hasher: Callable[[str], str] | None = None,
    input_hasher: Callable[[str], str] | None = None,
    reviews: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Invoke a synchronous host executor for every slot and validate reports.

    The executor must perform the model/tool call itself. It may return failed,
    blocked or not_run without inventing a result; ordinary exceptions are
    captured by type only. Explicit global stops prevent all later callbacks.
    KeyboardInterrupt and other BaseException subclasses are not swallowed.
    """
    plan = _plan(spec)
    if not callable(executor):
        raise ExperimentSpecError("executor_not_callable")
    if inspect.iscoroutinefunction(executor):
        raise ExperimentSpecError("async_executor_unsupported")
    if artifact_hasher is not None and not callable(artifact_hasher):
        raise ExperimentSpecError("artifact_hasher_not_callable")
    if package_hasher is not None and not callable(package_hasher):
        raise ExperimentSpecError("package_hasher_not_callable")
    if input_hasher is not None and not callable(input_hasher):
        raise ExperimentSpecError("input_hasher_not_callable")
    if package_hasher is None:
        raise ExperimentSpecError("package_hasher_required_for_execution")
    if input_hasher is None and any(case["inputAssets"] for case in plan["cases"]):
        raise ExperimentSpecError("input_hasher_required_for_execution")
    if not isinstance(reviews, (list, tuple)):
        raise ExperimentSpecError("reviews_invalid")
    if len(reviews) > MAX_REVIEWS:
        raise ExperimentSpecError("review_limit_exceeded")
    records: list[dict[str, Any]] = []
    stopped: str | None = None
    for case, repetition, variant in _slots(plan):
        if stopped is not None:
            records.append({"caseId": case["id"], "repetition": repetition, "variant": variant,
                            "status": "not_run", "reasonCode": "experiment_stopped", "stopReasonCode": stopped})
            continue
        request = _request(plan, case, repetition, variant)
        before_package = _host_hash(package_hasher, variant)
        before_inputs: dict[str, str | None] = {}
        preflight_reason: str | None = None
        if package_hasher is not None:
            if before_package is None:
                preflight_reason = "package_hash_preflight_unavailable"
            elif before_package != request["packageHash"]:
                preflight_reason = "package_hash_preflight_mismatch"
        if preflight_reason is None:
            for asset in case["inputAssets"]:
                observed = _host_hash(input_hasher, asset["ref"])
                before_inputs[asset["ref"]] = observed
                if input_hasher is not None and observed != asset["sha256"]:
                    preflight_reason = "input_hash_preflight_unavailable" if observed is None else "input_hash_preflight_mismatch"
                    break
        if preflight_reason is not None:
            records.append({"caseId": case["id"], "repetition": repetition, "variant": variant,
                            "status": "blocked", "reasonCode": preflight_reason,
                            "packageHashBefore": before_package, "packageHashAfter": None,
                            "inputHashesBefore": before_inputs, "inputHashesAfter": {}})
            continue
        stop_from_response: str | None = None
        try:
            response = executor(deepcopy(request))
            if inspect.isawaitable(response):
                if inspect.iscoroutine(response):
                    response.close()
                response = {"status": "failed", "reasonCode": "async_executor_unsupported"}
            elif not isinstance(response, Mapping):
                response = {"status": "failed", "reasonCode": "executor_response_invalid"}
            else:
                response = dict(response)
                stop_from_response = _global_stop_reason(response)
                try:
                    response = json.loads(_bounded_canonical(response, MAX_EXECUTOR_RESPONSE_BYTES, "executor_response_too_large"))
                except ExperimentSpecError as exc:
                    reason = "executor_response_too_large" if str(exc) == "executor_response_too_large" else "executor_response_invalid"
                    response = {"status": "failed", "reasonCode": reason}
                    if stop_from_response:
                        response.update({"stopExperiment": True, "stopReasonCode": stop_from_response})
        except Exception as exc:  # Host failure is an observed failure, not a pass.
            response = {"status": "failed", "reasonCode": "executor_exception",
                        "exceptionType": type(exc).__name__}
        stopped = stop_from_response or _global_stop_reason(response)
        # A global cancellation must not trigger further host callbacks.
        after_package = None if stopped else _host_hash(package_hasher, variant)
        after_inputs = {} if stopped else {asset["ref"]: _host_hash(input_hasher, asset["ref"]) for asset in case["inputAssets"]}
        # The host callback cannot relabel its response as another slot.
        records.append({**response, "caseId": case["id"], "repetition": repetition, "variant": variant,
                        "packageHashBefore": before_package, "packageHashAfter": after_package,
                        "inputHashesBefore": before_inputs, "inputHashesAfter": after_inputs})
    return _validate(plan, records, artifact_hasher=None if stopped else artifact_hasher, reviews=reviews)


def validate_experiment(
    spec: Mapping[str, Any],
    records: Sequence[Mapping[str, Any]],
    *,
    artifact_hasher: Callable[[str], str] | None = None,
    reviews: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Validate host-reported executions without starting or repeating them."""
    return _validate(_plan(spec), records, artifact_hasher=artifact_hasher, reviews=reviews)


def _host_hash(hasher: Callable[[str], str] | None, ref: str) -> str | None:
    if hasher is None:
        return None
    try:
        value = hasher(ref)
        return value if _digest(value) else None
    except Exception:
        return None


def _artifact_records(value: Any, artifact_hasher: Callable[[str], str] | None) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    artifacts: list[dict[str, Any]] = []
    conflicts: list[str] = []
    unknown: list[str] = []
    if not isinstance(value, list) or not value:
        return artifacts, conflicts, ["artifacts_unreported"]
    if len(value) > MAX_ARTIFACTS_PER_RUN:
        return artifacts, ["artifact_limit_exceeded"], ["artifacts_unreported"]
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, Mapping) or not _identifier(item.get("ref")) or not _digest(item.get("sha256")):
            conflicts.append("artifact_descriptor_invalid")
            continue
        ref, expected = item["ref"], item["sha256"]
        if ref in seen:
            conflicts.append("artifact_ref_duplicate")
            continue
        seen.add(ref)
        verification = "unverified"
        if artifact_hasher is not None:
            try:
                actual = artifact_hasher(ref)
                if not _digest(actual):
                    unknown.append("artifact_hash_unavailable")
                elif actual != expected:
                    verification = "mismatch"
                    conflicts.append("artifact_hash_mismatch")
                else:
                    verification = "matched_host_hash"
            except Exception:
                unknown.append("artifact_hash_unavailable")
        else:
            unknown.append("artifact_hash_unverified")
        artifacts.append({"ref": ref, "sha256": expected, "hashVerification": verification})
    if not artifacts:
        unknown.append("artifacts_unreported")
    return artifacts, conflicts, unknown


def _technical_checks(value: Any, artifact_hashes: set[str]) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    out: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping) or not _identifier(item.get("name")):
            continue
        status = item.get("status")
        digest = item.get("artifactSha256")
        if not isinstance(status, str) or status not in {"passed", "failed", "unreviewed"}:
            status = "unreviewed"
        known_digest = _digest(digest) and digest in artifact_hashes
        if status != "unreviewed" and (not known_digest or not _identifier(item.get("method"))):
            status = "unreviewed"
        out.append({"name": item["name"], "status": status,
                    "artifactSha256": digest if known_digest else None,
                    "method": item.get("method") if _identifier(item.get("method")) else None,
                    "evidence": "host_reported"})
    return out


def _playback(value: Any, artifact_hashes: set[str]) -> dict[str, Any]:
    source = value if isinstance(value, Mapping) else {}
    out: dict[str, Any] = {}
    for modality in ("visual", "audio"):
        item = source.get(modality)
        if not isinstance(item, Mapping):
            out[modality] = {"status": "unreviewed"}
            continue
        status = item.get("status")
        if status == "not_applicable":
            out[modality] = {"status": "not_applicable", "evidence": "host_reported"}
        elif (status == "observed" and isinstance(item.get("coverage"), str)
              and item["coverage"] in {"full", "partial"} and type(item.get("normalSpeed")) is bool
              and _digest(item.get("artifactSha256")) and item["artifactSha256"] in artifact_hashes
              and isinstance(item.get("observerType"), str) and item["observerType"] in {"human", "model", "host"}):
            out[modality] = {"status": "observed", "coverage": item["coverage"],
                             "normalSpeed": item["normalSpeed"], "observerType": item["observerType"],
                             "artifactSha256": item["artifactSha256"], "evidence": "host_reported"}
        else:
            out[modality] = {"status": "unreviewed"}
    return out


def _one_run(
    plan: Mapping[str, Any], case: Mapping[str, Any], repetition: int, variant: str,
    record: Mapping[str, Any] | None, artifact_hasher: Callable[[str], str] | None,
    duplicate_ids: set[str],
) -> tuple[dict[str, Any], list[str], list[str]]:
    if record is None:
        return {"executionStatus": "not_run", "technicalChecks": [], "playback": _playback(None, set()),
                "artifacts": []}, [], ["run_missing"]
    conflicts: list[str] = []
    unknown: list[str] = []
    actual_conditions_hash: str | None = None
    status = record.get("status")
    if not isinstance(status, str) or status not in _EXECUTION_STATUSES:
        status = "failed"
        conflicts.append("execution_status_invalid")
    invocation = record.get("invocationId")
    if status == "completed":
        if not _identifier(invocation):
            unknown.append("invocation_id_unreported")
        elif invocation in duplicate_ids:
            conflicts.append("invocation_id_reused")
        expected_package = plan["variants"][variant]["packageHash"]
        for field, expected in (("packageHash", expected_package), ("inputHash", _input_hash(case))):
            actual = record.get(field)
            if actual is None:
                unknown.append(f"{field}_unreported")
            elif actual != expected:
                conflicts.append(f"{field}_mismatch")
        for field in ("packageHashBefore", "packageHashAfter"):
            actual = record.get(field)
            if actual is None:
                unknown.append(f"{field}_unverified")
            elif actual != expected_package:
                conflicts.append(f"{field}_mismatch")
        for field in ("inputHashesBefore", "inputHashesAfter"):
            observed = record.get(field)
            for asset in case["inputAssets"]:
                actual = observed.get(asset["ref"]) if isinstance(observed, Mapping) else None
                if actual is None:
                    unknown.append(f"{field}_unverified")
                elif actual != asset["sha256"]:
                    conflicts.append(f"{field}_mismatch")
        actual_conditions = record.get("actualConditions")
        if actual_conditions is None:
            unknown.append("actual_conditions_unreported")
        else:
            try:
                bounded = _bounded_canonical(actual_conditions, MAX_CONDITIONS_BYTES, "actual_conditions_too_large")
                actual_conditions_hash = "sha256:" + hashlib.sha256(bounded.encode("utf-8")).hexdigest()
                if actual_conditions_hash != canonical_hash(plan["conditions"]):
                    conflicts.append("actual_conditions_mismatch")
            except ExperimentSpecError:
                conflicts.append("actual_conditions_invalid")
        effort = record.get("appliedEffort")
        effort_evidence = record.get("effortEvidence")
        if (not _identifier(effort) or effort.lower() in {"unknown", "unavailable", "not-observable"}
                or not isinstance(effort_evidence, str)
                or effort_evidence not in {"runner-reported", "runtime-fixed"}):
            unknown.append("applied_effort_unverified")
        elif plan["conditions"]["requestedEffort"] is not None and effort != plan["conditions"]["requestedEffort"]:
            conflicts.append("applied_effort_mismatch_requested")
        artifacts, art_conflicts, art_unknown = _artifact_records(record.get("artifacts"), artifact_hasher)
        conflicts.extend(art_conflicts)
        unknown.extend(art_unknown)
    else:
        artifacts, art_conflicts, _ = _artifact_records(record.get("artifacts"), artifact_hasher) if record.get("artifacts") else ([], [], [])
        conflicts.extend(art_conflicts)
        effort, effort_evidence = None, None
        unknown.append("run_not_completed")
        reason = record.get("reasonCode")
        if isinstance(reason, str) and reason in {"package_hash_preflight_mismatch", "input_hash_preflight_mismatch"}:
            conflicts.append(reason)
        elif isinstance(reason, str) and reason in {"package_hash_preflight_unavailable", "input_hash_preflight_unavailable"}:
            unknown.append(reason)
    hashes = {item["sha256"] for item in artifacts}
    if isinstance(record.get("technicalChecks"), list) and len(record["technicalChecks"]) > MAX_TECHNICAL_CHECKS_PER_RUN:
        conflicts.append("technical_check_limit_exceeded")
        technical_checks: list[dict[str, Any]] = []
    else:
        technical_checks = _technical_checks(record.get("technicalChecks"), hashes)
    result: dict[str, Any] = {
        "executionStatus": status,
        "invocationId": invocation if _identifier(invocation) else None,
        "packageHash": record.get("packageHash") if _digest(record.get("packageHash")) else None,
        "packageHashBefore": record.get("packageHashBefore") if _digest(record.get("packageHashBefore")) else None,
        "packageHashAfter": record.get("packageHashAfter") if _digest(record.get("packageHashAfter")) else None,
        "inputHash": record.get("inputHash") if _digest(record.get("inputHash")) else None,
        "inputAssets": [{"ref": asset["ref"], "sha256": asset["sha256"],
                         "before": (record.get("inputHashesBefore") or {}).get(asset["ref"])
                         if isinstance(record.get("inputHashesBefore"), dict) and _digest(record["inputHashesBefore"].get(asset["ref"])) else None,
                         "after": (record.get("inputHashesAfter") or {}).get(asset["ref"])
                         if isinstance(record.get("inputHashesAfter"), dict) and _digest(record["inputHashesAfter"].get(asset["ref"])) else None}
                        for asset in case["inputAssets"]],
        "actualConditionsHash": actual_conditions_hash,
        "appliedEffort": effort if _identifier(effort) else None,
        "effortEvidence": effort_evidence if isinstance(effort_evidence, str) and effort_evidence in {"runner-reported", "runtime-fixed", "not-observable"} else None,
        "artifacts": artifacts,
        "technicalChecks": technical_checks,
        "playback": _playback(record.get("playback"), hashes),
        "globalStopRequested": _global_stop_reason(record) is not None,
        "evidence": "host_reported",
    }
    for key in ("reasonCode", "exceptionType", "stopReasonCode"):
        if _identifier(record.get(key)):
            result[key] = record[key]
    return result, conflicts, unknown


def _reviews(value: Sequence[Mapping[str, Any]], pair_map: Mapping[tuple[str, int], dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not isinstance(value, (list, tuple)):
        return out
    for review in value:
        if not isinstance(review, Mapping):
            out.append({"status": "invalid", "reason": "review_invalid"})
            continue
        case_id, repetition = review.get("caseId"), review.get("repetition")
        pair = pair_map.get((case_id, repetition)) if _identifier(case_id) and type(repetition) is int else None
        reviewer_type, choice = review.get("reviewerType"), review.get("choice")
        baseline_hash, candidate_hash = review.get("baselineArtifactHash"), review.get("candidateArtifactHash")
        valid = (pair is not None and isinstance(reviewer_type, str) and reviewer_type in {"human", "independent_model"}
                 and _digest(review.get("reviewerIdHash"))
                 and isinstance(choice, str) and choice in {"baseline", "candidate", "tie", "skip"}
                 and type(review.get("orderRandomized")) is bool
                 and type(review.get("blinded")) is bool
                 and _digest(baseline_hash) and baseline_hash in {a["sha256"] for a in pair["runs"]["baseline"]["artifacts"]}
                 and _digest(candidate_hash) and candidate_hash in {a["sha256"] for a in pair["runs"]["candidate"]["artifacts"]})
        if not valid:
            out.append({"status": "invalid", "reason": "review_binding_invalid"})
            continue
        out.append({key: review[key] for key in ("caseId", "repetition", "reviewerType", "reviewerIdHash", "choice",
                                                 "orderRandomized", "blinded", "baselineArtifactHash", "candidateArtifactHash")}
                   | {"status": "recorded", "evidence": "host_reported"})
    return out


def _validate(
    plan: Mapping[str, Any], records: Sequence[Mapping[str, Any]], *,
    artifact_hasher: Callable[[str], str] | None, reviews: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    if artifact_hasher is not None and not callable(artifact_hasher):
        raise ExperimentSpecError("artifact_hasher_not_callable")
    if not isinstance(records, (list, tuple)):
        raise ExperimentSpecError("records_invalid")
    if len(records) > MAX_EXECUTIONS * 2:
        raise ExperimentSpecError("record_limit_exceeded")
    if not isinstance(reviews, (list, tuple)):
        raise ExperimentSpecError("reviews_invalid")
    if len(reviews) > MAX_REVIEWS:
        raise ExperimentSpecError("review_limit_exceeded")
    expected = {(case["id"], repetition, variant) for case, repetition, variant in _slots(plan)}
    indexed: dict[tuple[str, int, str], Mapping[str, Any]] = {}
    duplicates: set[tuple[str, int, str]] = set()
    rejected = 0
    for record in records:
        if not isinstance(record, Mapping):
            rejected += 1
            continue
        if (not _identifier(record.get("caseId")) or type(record.get("repetition")) is not int
                or record.get("variant") not in _VARIANTS):
            rejected += 1
            continue
        key = (record.get("caseId"), record.get("repetition"), record.get("variant"))
        try:
            known = key in expected
        except TypeError:
            known = False
        if not known:
            rejected += 1
        elif key in indexed:
            duplicates.add(key)
        else:
            indexed[key] = record
    counts = Counter(record.get("invocationId") for record in indexed.values() if _identifier(record.get("invocationId")))
    duplicate_ids = {key for key, count in counts.items() if count > 1}
    ordered_keys = [(case["id"], repetition, variant) for case, repetition, variant in _slots(plan)]
    stop_reasons: dict[tuple[str, int, str], str] = {}
    for record in records:
        if (not isinstance(record, Mapping) or not _identifier(record.get("caseId"))
                or type(record.get("repetition")) is not int or record.get("variant") not in _VARIANTS):
            continue
        key = (record["caseId"], record["repetition"], record["variant"])
        reason = _global_stop_reason(record)
        if key in expected and reason:
            stop_reasons.setdefault(key, reason)
    stop_key = next((key for key in ordered_keys if key in stop_reasons), None)
    post_stop = set(ordered_keys[ordered_keys.index(stop_key) + 1:]) if stop_key else set()
    ref_owners: dict[str, set[tuple[str, int, str]]] = {}
    # Include duplicate records for a known slot too: discarding a later record
    # must not hide that its ref was also used by another slot.
    for record in records:
        if (not isinstance(record, Mapping) or not _identifier(record.get("caseId"))
                or type(record.get("repetition")) is not int or record.get("variant") not in _VARIANTS):
            continue
        key = (record["caseId"], record["repetition"], record["variant"])
        if key not in expected:
            continue
        reported = record.get("artifacts")
        if not isinstance(reported, list) or len(reported) > MAX_ARTIFACTS_PER_RUN:
            continue
        for artifact in reported:
            if isinstance(artifact, Mapping) and _identifier(artifact.get("ref")):
                ref_owners.setdefault(artifact["ref"], set()).add(key)
    reused_refs = {ref for ref, owners in ref_owners.items() if len(owners) > 1}
    pairs: list[dict[str, Any]] = []
    for case in plan["cases"]:
        for repetition in range(1, plan["repetitions"] + 1):
            runs: dict[str, Any] = {}
            conflicts: list[str] = []
            unknown: list[str] = []
            for variant in _VARIANTS:
                key = (case["id"], repetition, variant)
                run, bad, missing = _one_run(plan, case, repetition, variant, indexed.get(key), artifact_hasher, duplicate_ids)
                runs[variant] = run
                conflicts.extend(f"{variant}:{item}" for item in bad)
                unknown.extend(f"{variant}:{item}" for item in missing)
                if key in duplicates:
                    conflicts.append(f"{variant}:slot_duplicated")
                if any(artifact["ref"] in reused_refs for artifact in run["artifacts"]):
                    conflicts.append(f"{variant}:artifact_ref_reused_across_slots")
                if key in post_stop and (run["executionStatus"] in {"completed", "failed"} or run.get("invocationId")):
                    conflicts.append(f"{variant}:reported_run_after_global_stop")
            if (runs["baseline"].get("appliedEffort") and runs["candidate"].get("appliedEffort")
                    and runs["baseline"]["appliedEffort"] != runs["candidate"]["appliedEffort"]):
                conflicts.append("applied_effort_mismatch")
            status = "not_comparable" if conflicts else "unverified" if unknown else "comparable"
            pairs.append({"caseId": case["id"], "repetition": repetition,
                          "inputHash": _input_hash(case), "comparability": status,
                          "conflicts": sorted(set(conflicts)), "unverified": sorted(set(unknown)), "runs": runs})
    pair_map = {(item["caseId"], item["repetition"]): item for item in pairs}
    return {
        "schemaVersion": REPORT_SCHEMA,
        "experimentId": plan["experimentId"],
        "conditionsHash": canonical_hash(plan["conditions"]),
        "conditionSummary": {key: plan["conditions"][key] for key in
                             (*_CONDITION_TEXT, "requestedEffort", *_CONDITION_DIGESTS)},
        "packageHashes": {name: plan["variants"][name]["packageHash"] for name in _VARIANTS},
        "packageHashesIdentical": plan["variants"]["baseline"]["packageHash"] == plan["variants"]["candidate"]["packageHash"],
        "caseCount": len(plan["cases"]),
        "uniqueInputHashCount": len({_input_hash(case) for case in plan["cases"]}),
        "topicDiversity": "not_assessed",
        "repetitions": plan["repetitions"],
        "pairs": pairs,
        "rejectedRecordCount": rejected,
        "reusedArtifactRefCount": len(reused_refs),
        "globalStop": ({"caseId": stop_key[0], "repetition": stop_key[1], "variant": stop_key[2],
                        "reasonCode": stop_reasons[stop_key], "evidence": "host_reported"} if stop_key else None),
        "reviews": _reviews(reviews, pair_map),
        "creativeVerdict": "not_computed",
        "evidenceScope": "host_reported_not_independently_attested",
    }
