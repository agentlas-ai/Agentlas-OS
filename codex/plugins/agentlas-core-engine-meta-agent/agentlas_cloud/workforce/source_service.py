"""Typed source-scope adapter for Workforce federation."""

from __future__ import annotations

from datetime import datetime, timezone
import inspect
import json
import time
from typing import Any, Callable, Collection, Mapping

from ..auth import ensure_login_instance_id, read_token_record
from ..networking.hub_client import (
    HubAuthRequiredError,
    HubToolError,
    call_hub_tool,
    finite_hub_tool_error_code,
    hub_url,
    list_hub_tools,
)
from .contracts import canonical_digest, canonical_json
from .federation import (
    LineageVerifier,
    WORKFORCE_SOURCE_FAILURE_CODES,
    federate_candidate_sets,
    sources_for_scope,
)
from .federation_store import FederationSessionError, FederationSessionStore
from .index import WorkforceIndex
from .local_registry import LocalWorkforceRegistry
from .privacy import assert_hub_work_order_boundary
from .prepare_cache import (
    WorkforcePrepareCacheError,
    WorkforcePrepareReceiptCache,
    source_fetch_idempotency,
    validate_prepare_attempt,
)
from .provenance import validate_federated_selection_wrapper


RemoteSearch = Callable[[str, Mapping[str, Any], list[str]], Mapping[str, Any]]
RemoteBundleFetch = Callable[..., Mapping[str, Any]]
RemoteBundleVerifier = Callable[[str, Mapping[str, Any], Mapping[str, Any]], bool]
RemoteCapabilities = Callable[[], list[Mapping[str, Any]]]

WORKFORCE_SOURCE_BUNDLE_RECEIPT_SCHEMA = "agentlas.workforce-source-bundle-verification.v1"
WORKFORCE_SOURCE_BUNDLE_TOOL = "workforce.fetch_runtime_bundle"
_WORKFORCE_SEARCH_DISCOVERY_NAMES = frozenset(
    {"workforce.search_candidates", "workforce_search_candidates"}
)
_WORKFORCE_BUNDLE_DISCOVERY_NAMES = frozenset(
    {WORKFORCE_SOURCE_BUNDLE_TOOL, "workforce_fetch_runtime_bundle"}
)
WORKFORCE_SOURCE_BUNDLE_FAILURE_CODES = frozenset(
    {
        "source_bundle_fetch_not_supported",
        "source_bundle_fetch_failed",
        "source_bundle_verification_failed",
        "source_bundle_claim_mismatch",
        "prepare_receipt_cache_busy",
        "source_not_configured",
        "source_not_supported",
        "source_unavailable",
        "source_unauthorized",
        "source_forbidden",
        "source_timeout",
        "source_rate_limited",
        "insufficient_credits",
        "owner_only",
        "no_cloud_package",
        "agent_not_found",
        "release_artifact_unavailable",
    }
)

_PREPARE_CACHE_WAIT_SECONDS = 10.0
_PREPARE_CACHE_POLL_SECONDS = 0.025


class WorkforceSourceError(ValueError):
    def __init__(
        self,
        code: str,
        *,
        retry_after_ms: int | None = None,
        receipt_expires_at: str | None = None,
    ):
        self.code = code
        self.retry_after_ms = (
            max(100, min(10_000, retry_after_ms))
            if isinstance(retry_after_ms, int) and not isinstance(retry_after_ms, bool)
            else None
        )
        self.receipt_expires_at = (
            receipt_expires_at
            if isinstance(receipt_expires_at, str) and receipt_expires_at
            else None
        )
        super().__init__(code)


def _finite_failure(code: str) -> str:
    return code if code in WORKFORCE_SOURCE_FAILURE_CODES else "source_unavailable"


_REMOTE_ERROR_STATUSES = frozenset(
    {"blocked", "denied", "error", "failed", "failure", "rejected"}
)


def _response_failure_code(
    response: Mapping[str, Any],
    *,
    allowed_codes: Collection[str],
    fallback: str,
) -> str | None:
    """Return a finite refusal only when the response signals failure."""

    status = response.get("status")
    error = response.get("error")
    code = response.get("code")
    status_value = status.lower() if isinstance(status, str) else ""
    error_present = error not in (None, False, "", [], {})
    extracted = finite_hub_tool_error_code(
        {"status": status, "error": error, "code": code},
        allowed_codes=allowed_codes,
        default="",
    )
    failure_signaled = (
        response.get("isError") is True
        or error_present
        or bool(extracted)
        or status_value in _REMOTE_ERROR_STATUSES
        or status_value in allowed_codes
    )
    if not failure_signaled:
        return None
    return extracted or fallback


def _bundle_fetch_failure_code(exc: HubToolError) -> str:
    remote_code = getattr(exc, "code", "source_unavailable")
    message = str(exc).lower()
    if remote_code == "source_unavailable" and any(
        marker in message for marker in ("unknown tool", "not found", "unsupported")
    ):
        return "source_bundle_fetch_not_supported"
    if remote_code in WORKFORCE_SOURCE_BUNDLE_FAILURE_CODES:
        return remote_code
    return "source_bundle_fetch_failed"


def _response_retry_after_ms(response: Mapping[str, Any], *, default: int = 250) -> int:
    value = response.get("retryAfterMs")
    if not isinstance(value, int) or isinstance(value, bool):
        return default
    return max(100, min(10_000, value))


def _response_receipt_expiry(response: Mapping[str, Any]) -> str | None:
    value = response.get("receiptExpiresAt")
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _remote_fetch_accepts_context(remote_fetch: RemoteBundleFetch) -> bool:
    """Inspect once; never catch an internal TypeError and replay a paid call."""

    try:
        signature = inspect.signature(remote_fetch)
    except (TypeError, ValueError):
        return False
    positional = [
        parameter
        for parameter in signature.parameters.values()
        if parameter.kind in {
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        }
    ]
    return any(
        parameter.kind == inspect.Parameter.VAR_POSITIONAL
        for parameter in signature.parameters.values()
    ) or len(positional) >= 3


def _default_hub_auth_partition() -> str | None:
    """Return a rotation-stable, account-separated OAuth cache partition."""

    base_url = hub_url()
    record = read_token_record(base_url)
    if not isinstance(record, Mapping):
        return None
    subject = record.get("account_subject")
    if (
        isinstance(subject, str)
        and subject.startswith("sha256:")
        and len(subject) == 71
        and all(character in "0123456789abcdef" for character in subject[7:])
    ):
        return canonical_digest({
            "schemaVersion": "agentlas.workforce-auth-cache-partition.v2",
            "baseUrl": base_url,
            "accountSubject": subject,
        })
    client_id = record.get("client_id")
    if not isinstance(client_id, str) or not client_id:
        return None
    login_instance_id = ensure_login_instance_id(base_url)
    if not login_instance_id:
        return None
    return canonical_digest({
        "schemaVersion": "agentlas.workforce-auth-cache-partition.v2",
        "baseUrl": base_url,
        "clientId": client_id,
        "loginInstanceId": login_instance_id,
    })


class WorkforceSourceService:
    """Collect source-owned menus, then invoke the source-neutral federation."""

    def __init__(
        self,
        *,
        local_registry: LocalWorkforceRegistry | None = None,
        session_store: FederationSessionStore | None = None,
        remote_search: RemoteSearch | None = None,
        remote_bundle_fetch: RemoteBundleFetch | None = None,
        remote_bundle_verifier: RemoteBundleVerifier | None = None,
        remote_capabilities: RemoteCapabilities | None = None,
        lineage_verifier: LineageVerifier | None = None,
        cloud_source_supported: bool | None = None,
        reconcile_local: bool = True,
        auth_partition: str | None = None,
        prepare_receipt_cache: WorkforcePrepareReceiptCache | None = None,
    ):
        self.local_registry = local_registry or LocalWorkforceRegistry()
        self.session_store = session_store or FederationSessionStore(lineage_verifier=lineage_verifier)
        if self.session_store.lineage_verifier is not lineage_verifier and lineage_verifier is not None:
            raise WorkforceSourceError("lineage_verifier_store_mismatch")
        self._uses_default_remote_search = remote_search is None
        self.remote_search = remote_search or self._default_remote_search
        self._uses_default_remote_bundle_fetch = remote_bundle_fetch is None
        self.remote_bundle_fetch = remote_bundle_fetch or self._default_remote_bundle_fetch
        self._remote_bundle_fetch_accepts_context = _remote_fetch_accepts_context(
            self.remote_bundle_fetch
        )
        self.remote_bundle_verifier = remote_bundle_verifier or self._default_remote_bundle_verifier
        self.remote_capabilities = remote_capabilities or list_hub_tools
        self._remote_capability_cache: list[Mapping[str, Any]] | None = None
        self.lineage_verifier = lineage_verifier or self.session_store.lineage_verifier
        # None means capability-negotiated. Explicit False is useful for an
        # offline/older deployment that must not be probed.
        self.cloud_source_supported = cloud_source_supported
        self.reconcile_local = reconcile_local
        self._configured_auth_partition = auth_partition
        self.prepare_receipt_cache = prepare_receipt_cache or WorkforcePrepareReceiptCache(
            self.session_store.path
        )

    def _prepare_auth_partition(self) -> str:
        if self._configured_auth_partition:
            return self._configured_auth_partition
        if self._uses_default_remote_bundle_fetch:
            partition = _default_hub_auth_partition()
            if partition is None:
                raise WorkforceSourceError("source_unauthorized")
            return partition
        # An injected source adapter has no production OAuth identity.  Keep it
        # process/callable-isolated unless its caller explicitly supplies a
        # stable test/private adapter partition.
        return canonical_digest({
            "schemaVersion": "agentlas.workforce-injected-source-partition.v1",
            "processIdentity": id(self.remote_bundle_fetch),
        })

    def _remote_tools(self) -> list[Mapping[str, Any]]:
        if self._remote_capability_cache is None:
            try:
                self._remote_capability_cache = list(self.remote_capabilities())
            except HubAuthRequiredError as exc:
                raise WorkforceSourceError("source_unauthorized") from exc
            except HubToolError as exc:
                raise WorkforceSourceError(
                    _finite_failure(getattr(exc, "code", "source_unavailable"))
                ) from exc
            except (OSError, TimeoutError, TypeError, ValueError) as exc:
                raise WorkforceSourceError("source_unavailable") from exc
        return self._remote_capability_cache

    def _remote_search_scope_mode(self, source: str) -> str:
        search = next(
            (
                row
                for row in self._remote_tools()
                if isinstance(row, Mapping)
                and row.get("name") in _WORKFORCE_SEARCH_DISCOVERY_NAMES
            ),
            None,
        )
        if not isinstance(search, Mapping):
            raise WorkforceSourceError("source_not_supported")
        schema = search.get("inputSchema")
        properties = schema.get("properties") if isinstance(schema, Mapping) else None
        source_scope = properties.get("sourceScope") if isinstance(properties, Mapping) else None
        if not isinstance(source_scope, Mapping):
            if source == "hub":
                # Explicitly negotiated legacy Hub adapter. This is a protocol
                # shape decision, never a semantic fallback to another source.
                return "legacy-hub"
            raise WorkforceSourceError("source_not_supported")
        scopes = source_scope.get("enum")
        if not isinstance(scopes, list) or source not in scopes:
            raise WorkforceSourceError("source_not_supported")
        return "typed"

    def _cloud_supported(self) -> bool:
        if self.cloud_source_supported is not None:
            return self.cloud_source_supported
        try:
            if self._remote_search_scope_mode("cloud") != "typed":
                return False
            tools = self._remote_tools()
        except WorkforceSourceError:
            return False
        names = {
            str(row.get("name"))
            for row in tools
            if isinstance(row, Mapping) and row.get("name")
        }
        return bool(names & _WORKFORCE_BUNDLE_DISCOVERY_NAMES)

    def _default_remote_search(
        self,
        source: str,
        work_order: Mapping[str, Any],
        expand_slot_ids: list[str],
    ) -> Mapping[str, Any]:
        if source == "cloud" and self.cloud_source_supported is False:
            raise WorkforceSourceError("source_not_supported")
        scope_mode = (
            "typed"
            if source == "cloud" and self.cloud_source_supported is True
            else self._remote_search_scope_mode(source)
        )
        if source == "cloud" and not self._cloud_supported():
            raise WorkforceSourceError("source_not_supported")
        payload: dict[str, Any] = {"workOrder": dict(work_order)}
        if expand_slot_ids:
            payload["expandSlotIds"] = list(expand_slot_ids)
        if scope_mode == "typed":
            payload["sourceScope"] = source
        # Workforce runs can be scheduled/headless. Never open an interactive
        # login after dispatch: surface source_unauthorized so Desktop can keep
        # the automation enabled and request attention without hanging it.
        return call_hub_tool("workforce.search_candidates", payload, auto_auth=False)

    def _default_remote_bundle_fetch(
        self,
        source: str,
        pin: Mapping[str, Any],
        fetch_idempotency: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        """Use the exact-release source capability; never replay a merged menu.

        The remote source must resolve the release inside its own immutable
        CandidateSet session.  This deliberately does not call the legacy
        slug/latest bundle endpoint and does not send the federated CandidateSet
        or selection back to a source.
        """

        if source == "cloud":
            if self.cloud_source_supported is False:
                raise WorkforceSourceError("source_not_supported")
            if self.cloud_source_supported is None:
                self._remote_search_scope_mode("cloud")
            if not self._cloud_supported():
                raise WorkforceSourceError("source_not_supported")
        payload = {
            "sourceSelectionSessionId": pin["sourceSelectionSessionId"],
            "sourceCandidateSetDigest": pin["sourceCandidateSetDigest"],
            "agentDefinitionId": pin["agentDefinitionId"],
            "agentReleaseId": pin["agentReleaseId"],
            "releaseVersion": pin["releaseVersion"],
            "packageHash": pin["packageHash"],
            "contentDigest": pin["contentDigest"],
            "entityKind": pin["entityKind"],
        }
        if not isinstance(fetch_idempotency, Mapping):
            raise WorkforceSourceError("prepare_idempotency_invalid")
        payload.update({
            "prepareAttemptDigest": fetch_idempotency["prepareAttemptDigest"],
            "selectedSourcePinDigest": fetch_idempotency["selectedSourcePinDigest"],
            "sourceFetchBindingDigest": fetch_idempotency["sourceFetchBindingDigest"],
            "sourceFetchIdempotencyKey": fetch_idempotency["sourceFetchIdempotencyKey"],
        })
        if source == "cloud":
            payload["sourceScope"] = "cloud"
        return call_hub_tool(WORKFORCE_SOURCE_BUNDLE_TOOL, payload, auto_auth=False)

    @staticmethod
    def _default_remote_bundle_verifier(
        source: str,
        pin: Mapping[str, Any],
        response: Mapping[str, Any],
    ) -> bool:
        receipt = response.get("verificationReceipt")
        bundle = response.get("runtimeBundle")
        if not isinstance(receipt, Mapping) or not isinstance(bundle, Mapping):
            return False
        required = {
            "schemaVersion", "status", "verification", "source",
            "sourceSelectionSessionId", "sourceCandidateSetDigest",
            "agentDefinitionId", "agentReleaseId", "releaseVersion",
            "packageHash", "contentDigest", "entityKind",
            "prepareAttemptDigest", "selectedSourcePinDigest",
            "sourceFetchBindingDigest", "sourceFetchIdempotencyKey",
            "receiptDigest",
        }
        if (
            set(receipt) != required
            or receipt.get("schemaVersion") != WORKFORCE_SOURCE_BUNDLE_RECEIPT_SCHEMA
            or receipt.get("status") != "verified"
            or receipt.get("verification") not in {"verified_transport", "verified_signature"}
            or receipt.get("source") != source
            or receipt.get("receiptDigest")
            != canonical_digest({key: value for key, value in receipt.items() if key != "receiptDigest"})
        ):
            return False
        for field in (
            "sourceSelectionSessionId", "sourceCandidateSetDigest",
            "agentDefinitionId", "agentReleaseId", "releaseVersion",
            "packageHash", "contentDigest", "entityKind",
        ):
            if receipt.get(field) != pin.get(field):
                return False
        for field in (
            "prepareAttemptDigest", "selectedSourcePinDigest",
            "sourceFetchBindingDigest", "sourceFetchIdempotencyKey",
        ):
            if receipt.get(field) != pin.get(field):
                return False
        return all(bundle.get(field) == pin.get(field) for field in ("agentReleaseId", "packageHash", "contentDigest"))

    def _search_remote(
        self,
        source: str,
        work_order: Mapping[str, Any],
        expand_slot_ids: list[str],
    ) -> tuple[dict[str, Any], dict[str, Mapping[str, Any]]]:
        try:
            response = self.remote_search(source, work_order, expand_slot_ids)
        except WorkforceSourceError:
            raise
        except HubAuthRequiredError as exc:
            raise WorkforceSourceError("source_unauthorized") from exc
        except TimeoutError as exc:
            raise WorkforceSourceError("source_timeout") from exc
        except HubToolError as exc:
            raise WorkforceSourceError(_finite_failure(getattr(exc, "code", "source_unavailable"))) from exc
        except (OSError, ValueError) as exc:
            raise WorkforceSourceError("source_unavailable") from exc
        if not isinstance(response, Mapping):
            raise WorkforceSourceError("source_invalid_candidate_set")
        refusal = _response_failure_code(
            response,
            allowed_codes=WORKFORCE_SOURCE_FAILURE_CODES,
            fallback="source_unavailable",
        )
        if refusal is not None:
            raise WorkforceSourceError(refusal)
        if source == "cloud":
            source_receipt = response.get("sourceReceipt")
            source_claim = response.get("sourceScope") == "cloud" or (
                isinstance(source_receipt, Mapping) and source_receipt.get("source") == "cloud"
            )
            if not source_claim:
                # An older server may ignore the new sourceScope argument and
                # return a public Hub menu. Never relabel that as owner Cloud.
                raise WorkforceSourceError("source_not_supported")
        candidate_set = response.get("candidateSet") if isinstance(response.get("candidateSet"), Mapping) else response
        lineages = response.get("lineageAttestations") if isinstance(response.get("lineageAttestations"), Mapping) else {}
        return dict(candidate_set), {
            str(key): dict(value)
            for key, value in lineages.items()
            if isinstance(value, Mapping)
        }

    def search(
        self,
        work_order: Mapping[str, Any],
        *,
        source_scope: str = "network",
        expand_slot_ids: list[str] | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        sources = sources_for_scope(source_scope)
        # WorkOrder v1 is the existing content-only/redacted contract.  It is
        # enforced before any remote call and consistently for Local today.
        assert_hub_work_order_boundary(work_order)
        # Freeze the exact accepted object once. The same canonical bytes drive
        # every source query, federation identity, and durable session pin.
        accepted_work_order = json.loads(canonical_json(work_order))
        slot_ids = [
            str(slot.get("slotId"))
            for slot in accepted_work_order.get("roleSlots") or []
            if isinstance(slot, Mapping) and slot.get("slotId")
        ]
        if not slot_ids:
            raise WorkforceSourceError("work_order_slots_missing")
        candidate_sets: dict[str, dict[str, Any]] = {}
        failures: dict[str, str] = {}
        lineages: dict[str, dict[str, Mapping[str, Any]]] = {}
        expand = list(expand_slot_ids or [])
        for source in sources:
            if source == "local":
                try:
                    if self.reconcile_local:
                        self.local_registry.reconcile()
                    index = WorkforceIndex(self.local_registry.active_profiles())
                    candidate_sets["local"] = index.search_candidates(
                        accepted_work_order,
                        now=now,
                        expand_slot_ids=expand,
                    )
                    lineages["local"] = self.local_registry.lineage_attestations()
                except (OSError, ValueError):
                    failures["local"] = "source_unavailable"
                continue
            if source == "cloud" and self.cloud_source_supported is False and self._uses_default_remote_search:
                failures["cloud"] = "source_not_supported"
                continue
            try:
                candidate_set, source_lineages = self._search_remote(source, accepted_work_order, expand)
                candidate_sets[source] = candidate_set
                lineages[source] = source_lineages
            except WorkforceSourceError as exc:
                failures[source] = _finite_failure(exc.code)

        policy = (
            accepted_work_order.get("selectionPolicy")
            if isinstance(accepted_work_order.get("selectionPolicy"), Mapping)
            else {}
        )
        policy_minimum = policy.get("minimumCandidatesPerSlot")
        minimum_candidates = (
            policy_minimum
            if isinstance(policy_minimum, int) and not isinstance(policy_minimum, bool) and 1 <= policy_minimum <= 30
            else 2
        )
        policy_maximum = policy.get("maximumCandidatesPerSlot")
        maximum_candidates = (
            policy_maximum
            if isinstance(policy_maximum, int) and not isinstance(policy_maximum, bool) and 1 <= policy_maximum <= 100
            else 100
        )
        result = federate_candidate_sets(
            candidate_sets,
            scope=source_scope,
            work_order_id=str(accepted_work_order.get("workOrderId") or ""),
            ontology_version=str(accepted_work_order.get("ontologyVersion") or ""),
            slot_ids=slot_ids,
            source_failures=failures,
            lineage_attestations=lineages,
            lineage_verifier=self.lineage_verifier,
            minimum_candidates_per_slot=minimum_candidates,
            maximum_candidates_per_slot=maximum_candidates,
            now=now,
        )
        successful_sources = {
            str(row["source"])
            for row in result.get("sourceReceipts") or []
            if isinstance(row, Mapping) and row.get("status") == "succeeded"
        }
        self.session_store.save(
            result,
            work_order=accepted_work_order,
            source_candidate_sets={source: candidate_sets[source] for source in successful_sources},
            now=now,
        )
        return result

    def fetch_selected_runtime_bundles(
        self,
        federated_selection: Mapping[str, Any],
        *,
        work_order: Mapping[str, Any],
        selection: Mapping[str, Any],
        prepare_attempt: Mapping[str, Any],
        now: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch exact pins once per account-bound logical prepare attempt."""

        session_id = str(federated_selection.get("selectionSessionId") or "")
        try:
            work_order_digest = self.session_store.assert_work_order_binding(
                session_id,
                work_order,
                now=now,
            )
        except FederationSessionError as exc:
            if exc.code in {
                "federation_session_expired",
                "federation_session_not_found",
                "source_candidate_set_expired",
                "source_candidate_set_not_found",
                "federated_selection_not_pinned",
            }:
                raise WorkforceSourceError(exc.code) from exc
            raise WorkforceSourceError("federated_work_order_binding_mismatch") from exc
        try:
            selection_digest = canonical_digest(selection)
        except (TypeError, ValueError) as exc:
            raise WorkforceSourceError("federated_selection_exact_binding_mismatch") from exc
        if (
            federated_selection.get("workOrderDigest") != work_order_digest
            or federated_selection.get("selectionDigest") != selection_digest
        ):
            raise WorkforceSourceError("federated_selection_exact_binding_mismatch")
        validate_federated_selection_wrapper(federated_selection)
        session_result = self.session_store.get(session_id, now=now)
        stored_selection = self.session_store.get_federated_selection(
            session_id,
            str(federated_selection.get("federatedSelectionDigest") or ""),
            now=now,
        )
        if canonical_digest(stored_selection) != canonical_digest(federated_selection):
            raise WorkforceSourceError("federated_selection_store_binding_mismatch")

        # Validate every pin before the first billable remote fetch.  A malformed
        # later pin must never leave an earlier exact bundle charged but unable
        # to be durably associated with this prepare attempt.
        pins: list[dict[str, Any]] = []
        for raw_pin in federated_selection.get("selectedSourcePins") or []:
            if not isinstance(raw_pin, Mapping):
                raise WorkforceSourceError("selected_release_source_pin_mismatch")
            pin = dict(raw_pin)
            authoritative_pin = self.session_store.source_pin(
                session_id,
                slot_id=str(pin.get("slotId") or ""),
                agent_definition_id=str(pin.get("agentDefinitionId") or ""),
                agent_release_id=str(pin.get("agentReleaseId") or ""),
                now=now,
            )
            if pin != authoritative_pin:
                raise WorkforceSourceError("selected_release_source_pin_mismatch")
            source = str(pin.get("source") or "")
            source_candidate_set = self.session_store.source_candidate_set(session_id, source, now=now)
            source_candidate = next(
                (
                    candidate
                    for slot in source_candidate_set.get("slots") or []
                    if isinstance(slot, Mapping) and slot.get("slotId") == pin.get("slotId")
                    for candidate in slot.get("candidates") or []
                    if isinstance(candidate, Mapping)
                    and candidate.get("agentDefinitionId") == pin.get("agentDefinitionId")
                    and candidate.get("agentReleaseId") == pin.get("agentReleaseId")
                ),
                None,
            )
            if not isinstance(source_candidate, Mapping) or any(
                source_candidate.get(field) != pin.get(field)
                for field in ("releaseVersion", "packageHash", "contentDigest", "entityKind")
            ):
                raise WorkforceSourceError("selected_release_source_pin_mismatch")
            pins.append(pin)
        if not pins:
            raise WorkforceSourceError("selected_release_source_pin_mismatch")

        try:
            accepted_prepare_attempt = validate_prepare_attempt(
                prepare_attempt,
                work_order=work_order,
                selection=selection,
                federated_selection=federated_selection,
            )
        except WorkforcePrepareCacheError as exc:
            raise WorkforceSourceError(exc.code) from exc

        remote_pins = [pin for pin in pins if pin.get("source") != "local"]
        auth_partition: str | None = None
        if remote_pins:
            auth_partition = self._prepare_auth_partition()
            try:
                expiry = datetime.fromisoformat(
                    str(session_result["candidateSet"]["expiresAt"]).replace("Z", "+00:00")
                )
                self.prepare_receipt_cache.bind_attempt(
                    auth_partition=auth_partition,
                    prepare_attempt=accepted_prepare_attempt,
                    selection_session_id=session_id,
                    pins=remote_pins,
                    session_expires_at=expiry,
                    now=now,
                )
            except WorkforcePrepareCacheError as exc:
                raise WorkforceSourceError(exc.code) from exc
            except (KeyError, TypeError, ValueError) as exc:
                raise WorkforceSourceError("prepare_receipt_cache_unavailable") from exc

        result: list[dict[str, Any]] = []
        bundle_cache: dict[tuple[str, ...], dict[str, Any]] = {}
        prepare_attempt_digest = canonical_digest(accepted_prepare_attempt)
        prepare_idempotency_key = str(accepted_prepare_attempt["idempotencyKey"])
        for pin in pins:
            source = str(pin.get("source") or "")
            bundle_key = (
                source,
                str(pin.get("sourceSelectionSessionId") or ""),
                str(pin.get("sourceCandidateSetDigest") or ""),
                str(pin.get("agentDefinitionId") or ""),
                str(pin.get("agentReleaseId") or ""),
                str(pin.get("releaseVersion") or ""),
                str(pin.get("packageHash") or ""),
                str(pin.get("contentDigest") or ""),
                str(pin.get("entityKind") or ""),
                str(pin.get("sourcePinDigest") or ""),
            )
            cached = bundle_cache.get(bundle_key)
            if cached is not None:
                bundle = dict(cached)
            elif source == "local":
                try:
                    bundle = self.local_registry.runtime_bundle(str(pin["agentReleaseId"]))
                except KeyError as exc:
                    detail = str(exc.args[0]) if exc.args else ""
                    raise WorkforceSourceError(
                        detail if detail.startswith("local_") else "source_bundle_fetch_failed"
                    ) from exc
                except OSError as exc:
                    raise WorkforceSourceError("source_bundle_fetch_failed") from exc
                bundle = dict(bundle)
                bundle_cache[bundle_key] = dict(bundle)
            else:
                if auth_partition is None:
                    raise WorkforceSourceError("source_unauthorized")
                fetch_idempotency = source_fetch_idempotency(prepare_attempt_digest, pin)
                remote_pin = {
                    **pin,
                    **{
                        key: value
                        for key, value in fetch_idempotency.items()
                        if key != "schemaVersion"
                    },
                }
                claim_owner: str | None = None
                response: dict[str, Any] | None = None
                deadline = time.monotonic() + _PREPARE_CACHE_WAIT_SECONDS
                while True:
                    try:
                        claim_status, claim_value = self.prepare_receipt_cache.claim(
                            auth_partition=auth_partition,
                            idempotency_key=prepare_idempotency_key,
                            pin=pin,
                            now=now,
                        )
                    except WorkforcePrepareCacheError as exc:
                        raise WorkforceSourceError(exc.code) from exc
                    if claim_status == "cached":
                        if not isinstance(claim_value, Mapping):
                            raise WorkforceSourceError("prepare_receipt_cache_corrupted")
                        response = dict(claim_value)
                        refusal = _response_failure_code(
                            response,
                            allowed_codes=WORKFORCE_SOURCE_BUNDLE_FAILURE_CODES,
                            fallback="source_bundle_fetch_failed",
                        )
                        if refusal is not None:
                            raise WorkforceSourceError("prepare_receipt_cache_corrupted")
                        if self.remote_bundle_verifier(source, remote_pin, response) is not True:
                            raise WorkforceSourceError("prepare_receipt_cache_corrupted")
                        break
                    if claim_status == "claimed" and isinstance(claim_value, str):
                        claim_owner = claim_value
                        break
                    if claim_status != "pending":
                        raise WorkforceSourceError("prepare_receipt_cache_corrupted")
                    if time.monotonic() >= deadline:
                        raise WorkforceSourceError(
                            "prepare_receipt_cache_busy",
                            retry_after_ms=max(100, int(_PREPARE_CACHE_POLL_SECONDS * 1_000)),
                            receipt_expires_at=expiry.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                        )
                    time.sleep(_PREPARE_CACHE_POLL_SECONDS)

                if response is None:
                    if claim_owner is None:
                        raise WorkforceSourceError("prepare_receipt_cache_corrupted")

                    def release_claim() -> None:
                        try:
                            self.prepare_receipt_cache.release_claim(
                                auth_partition=auth_partition,
                                idempotency_key=prepare_idempotency_key,
                                pin=pin,
                                claim_owner=claim_owner,
                                now=now,
                            )
                        except WorkforcePrepareCacheError:
                            # Preserve the exact Hub refusal/auth code.  A stale
                            # claim expires and can only replay with the same
                            # sourceFetchIdempotencyKey.
                            pass

                    while True:
                        try:
                            if self._remote_bundle_fetch_accepts_context:
                                raw_response = self.remote_bundle_fetch(
                                    source,
                                    pin,
                                    fetch_idempotency,
                                )
                            else:
                                raw_response = self.remote_bundle_fetch(source, remote_pin)
                            response = dict(raw_response)
                        except WorkforceSourceError:
                            release_claim()
                            raise
                        except HubAuthRequiredError as exc:
                            release_claim()
                            raise WorkforceSourceError("source_unauthorized") from exc
                        except TimeoutError as exc:
                            release_claim()
                            raise WorkforceSourceError("source_timeout") from exc
                        except HubToolError as exc:
                            release_claim()
                            raise WorkforceSourceError(_bundle_fetch_failure_code(exc)) from exc
                        except (OSError, ValueError) as exc:
                            release_claim()
                            raise WorkforceSourceError("source_bundle_fetch_failed") from exc
                        refusal = _response_failure_code(
                            response,
                            allowed_codes=WORKFORCE_SOURCE_BUNDLE_FAILURE_CODES,
                            fallback="source_bundle_fetch_failed",
                        )
                        if refusal != "prepare_receipt_cache_busy":
                            break
                        retry_after_ms = _response_retry_after_ms(response)
                        receipt_expires_at = _response_receipt_expiry(response)
                        session_remaining = max(
                            0.0,
                            (expiry - datetime.now(timezone.utc)).total_seconds(),
                        )
                        remaining = min(deadline - time.monotonic(), session_remaining)
                        if remaining <= 0:
                            release_claim()
                            raise WorkforceSourceError(
                                "prepare_receipt_cache_busy",
                                retry_after_ms=retry_after_ms,
                                receipt_expires_at=receipt_expires_at,
                            )
                        time.sleep(min(retry_after_ms / 1_000.0, remaining))
                    if refusal is not None:
                        release_claim()
                        raise WorkforceSourceError(refusal)
                    bundle_value = response.get("runtimeBundle")
                    receipt = response.get("verificationReceipt")
                    if (
                        not isinstance(bundle_value, Mapping)
                        or not isinstance(receipt, Mapping)
                        or self.remote_bundle_verifier(source, remote_pin, response) is not True
                    ):
                        release_claim()
                        raise WorkforceSourceError("source_bundle_verification_failed")
                    try:
                        self.prepare_receipt_cache.store_verified(
                            auth_partition=auth_partition,
                            idempotency_key=prepare_idempotency_key,
                            pin=pin,
                            fetch_idempotency=fetch_idempotency,
                            claim_owner=claim_owner,
                            response=response,
                            now=now,
                        )
                    except WorkforcePrepareCacheError as exc:
                        raise WorkforceSourceError(exc.code) from exc

                try:
                    bundle = dict(response["runtimeBundle"])
                except (KeyError, TypeError, ValueError) as exc:
                    raise WorkforceSourceError("prepare_receipt_cache_corrupted") from exc
                bundle_cache[bundle_key] = dict(bundle)
            for field in ("agentReleaseId", "packageHash", "contentDigest"):
                if bundle.get(field) != pin.get(field):
                    raise WorkforceSourceError("source_bundle_claim_mismatch")
            result.append({"sourcePin": pin, "runtimeBundle": bundle})
        return result


def search_workforce_sources(
    work_order: Mapping[str, Any],
    *,
    source_scope: str,
    service: WorkforceSourceService | None = None,
    expand_slot_ids: list[str] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    return (service or WorkforceSourceService()).search(
        work_order,
        source_scope=source_scope,
        expand_slot_ids=expand_slot_ids,
        now=now,
    )


__all__ = [
    "WORKFORCE_SOURCE_BUNDLE_RECEIPT_SCHEMA",
    "WORKFORCE_SOURCE_BUNDLE_FAILURE_CODES",
    "WORKFORCE_SOURCE_BUNDLE_TOOL",
    "WorkforceSourceError",
    "WorkforceSourceService",
    "search_workforce_sources",
]
