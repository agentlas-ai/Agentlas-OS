"""Trusted host model policy shared by MCP and CLI entry points."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping

from .model_allocation import EFFORT_TOKEN_RE

MODEL_ALLOCATION_POLICY_ENV = "AGENTLAS_MODEL_ALLOCATION_POLICY_JSON"
_HOST_MODEL_POLICY_FIELDS = frozenset({
    "pinnedModelId",
    "pinnedProvider",
    "maxTier",
    "maxEffort",
    "requiredCapabilities",
    "orchestrator",
    "worker",
})
_HOST_MODEL_ROLE_POLICY_FIELDS = frozenset({
    "pinnedModelId",
    "pinnedProvider",
    "maxTier",
    "maxEffort",
    "requiredCapabilities",
    "inherit",
})

def _host_model_allocation_policy() -> dict[str, Any]:
    """Read operator cost guardrails from the MCP process boundary.

    Tool arguments are untrusted workload input. They may carry a parent-AI
    allocation decision, but they must never raise the host's model/effort
    ceiling or forge a user pin. Operators configure this JSON in the MCP
    server launch environment instead.
    """

    raw = os.environ.get(MODEL_ALLOCATION_POLICY_ENV, "").strip()
    if not raw:
        # Fall back to the file `agentlas-one orch` writes. The env var is the
        # operator override and still wins; without this file the policy was
        # empty on every host because nobody hand-writes JSON into a launch
        # environment, so every worker silently inherited the orchestrator's
        # frontier model — the opposite of why the allocator exists.
        policy_file = Path(
            os.environ.get("AGENTLAS_ONE_DIR") or (Path.home() / ".agentlas" / "one")
        ) / "model-policy.json"
        try:
            raw = policy_file.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return {}
        except OSError:
            raise ValueError("host model allocation policy could not be read") from None
        if not raw:
            return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError) as exc:
        # Keep the decoder's line/column so a trailing comma is locatable. The
        # decoder message carries a position, never the policy value itself.
        raise ValueError(f"invalid host model allocation policy JSON: {exc}") from None
    if not isinstance(parsed, Mapping):
        raise ValueError("host model allocation policy must be an object")
    unknown = sorted(set(parsed) - _HOST_MODEL_POLICY_FIELDS)
    if unknown:
        raise ValueError(f"host model allocation policy has unknown fields: {','.join(unknown)}")
    policy = {key: parsed[key] for key in _HOST_MODEL_POLICY_FIELDS if key in parsed}

    def validate_scope(value: Mapping[str, Any], label: str, *, allow_inherit: bool) -> dict[str, Any]:
        unknown = sorted(set(value) - _HOST_MODEL_ROLE_POLICY_FIELDS)
        if unknown:
            raise ValueError(f"host {label} model policy has unknown fields: {','.join(unknown)}")
        scoped = dict(value)
        if "inherit" in scoped:
            if not allow_inherit or not isinstance(scoped["inherit"], bool):
                raise ValueError(f"host {label} inherit flag is invalid")
            if scoped["inherit"] and set(scoped) != {"inherit"}:
                raise ValueError(f"host {label} inherit policy cannot also pin or clamp a model")
        pinned_model_id = scoped.get("pinnedModelId")
        if pinned_model_id is not None and (
            not isinstance(pinned_model_id, str)
            or not pinned_model_id.strip()
            or len(pinned_model_id) > 255
        ):
            raise ValueError(f"host {label} pinnedModelId is invalid")
        pinned_provider = scoped.get("pinnedProvider")
        if pinned_provider is not None and (
            not isinstance(pinned_provider, str)
            or not pinned_provider.strip()
            or len(pinned_provider) > 80
        ):
            raise ValueError(f"host {label} pinnedProvider is invalid")
        if scoped.get("maxTier") is not None and scoped.get("maxTier") not in ("economy", "balanced", "frontier"):
            raise ValueError(f"host {label} maxTier is invalid")
        scoped_max_effort = scoped.get("maxEffort")
        if scoped_max_effort is not None and (
            not isinstance(scoped_max_effort, str) or not EFFORT_TOKEN_RE.fullmatch(scoped_max_effort)
        ):
            raise ValueError(f"host {label} maxEffort is invalid")
        capabilities = scoped.get("requiredCapabilities")
        if capabilities is not None and (
            not isinstance(capabilities, list)
            or len(capabilities) > 32
            or any(not isinstance(item, str) or not item.strip() or len(item) > 80 for item in capabilities)
        ):
            raise ValueError(f"host {label} requiredCapabilities is invalid")
        return scoped

    for role in ("orchestrator", "worker"):
        scoped = policy.get(role)
        if scoped is None:
            continue
        if not isinstance(scoped, Mapping):
            raise ValueError(f"host {role} model policy must be an object")
        policy[role] = validate_scope(scoped, role, allow_inherit=role == "worker")

    if "pinnedModelId" in policy and (
        not isinstance(policy["pinnedModelId"], str)
        or not policy["pinnedModelId"].strip()
        or len(policy["pinnedModelId"]) > 255
    ):
        raise ValueError("host pinnedModelId is invalid")
    if "pinnedProvider" in policy and (
        not isinstance(policy["pinnedProvider"], str)
        or not policy["pinnedProvider"].strip()
        or len(policy["pinnedProvider"]) > 80
    ):
        raise ValueError("host pinnedProvider is invalid")
    if policy.get("maxTier") is not None and policy.get("maxTier") not in ("economy", "balanced", "frontier"):
        raise ValueError("host maxTier is invalid")
    top_level_max_effort = policy.get("maxEffort")
    if top_level_max_effort is not None and (
        not isinstance(top_level_max_effort, str) or not EFFORT_TOKEN_RE.fullmatch(top_level_max_effort)
    ):
        raise ValueError("host maxEffort is invalid")
    capabilities = policy.get("requiredCapabilities")
    if capabilities is not None and (
        not isinstance(capabilities, list)
        or len(capabilities) > 32
        or any(not isinstance(item, str) or not item.strip() or len(item) > 80 for item in capabilities)
    ):
        raise ValueError("host requiredCapabilities is invalid")
    return policy
