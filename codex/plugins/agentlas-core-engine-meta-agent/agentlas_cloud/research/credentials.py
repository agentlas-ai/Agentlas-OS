"""Secret-safe credential setup guide for research platform cartridges."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .status import run_research_status


PROVIDER_DEFINITIONS: tuple[dict[str, Any], ...] = (
    {
        "id": "reddit_oauth",
        "module_id": "platform.reddit.oauth",
        "label": "Reddit OAuth reader",
        "proof_id": "reddit_oauth_live_check",
        "env_aliases": ("AGENTLAS_REDDIT_BEARER_TOKEN", "REDDIT_BEARER_TOKEN"),
        "env_alternatives": (
            ("AGENTLAS_REDDIT_BEARER_TOKEN",),
            ("REDDIT_BEARER_TOKEN",),
            ("AGENTLAS_REDDIT_CLIENT_ID", "AGENTLAS_REDDIT_CLIENT_SECRET"),
            ("REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET"),
        ),
        "preferred_env": "AGENTLAS_REDDIT_BEARER_TOKEN",
        "token_kind": "OAuth2 bearer token",
        "alternative_setup_commands": (
            "export AGENTLAS_REDDIT_CLIENT_ID='<Reddit app client id>'",
            "export AGENTLAS_REDDIT_CLIENT_SECRET='<Reddit app client secret>'",
        ),
        "minimum_permissions": ("read",),
        "check_command": "bin/hephaestus research platform-check --module platform.reddit.oauth --source 'reddit:subreddit:redditdev'",
        "public_fallback_module": "platform.reddit",
        "docs": (
            {
                "label": "Reddit API access policy",
                "url": "https://www.reddit.com/r/reddit.com/wiki/api/",
            },
            {
                "label": "Reddit OAuth API and scopes",
                "url": "https://www.reddit.com/dev/api/oauth/",
            },
        ),
    },
    {
        "id": "threads_graph",
        "module_id": "platform.threads",
        "label": "Threads Graph keyword/profile reader",
        "proof_id": "threads_live_graph_check",
        "env_aliases": ("AGENTLAS_THREADS_ACCESS_TOKEN", "THREADS_ACCESS_TOKEN"),
        "preferred_env": "AGENTLAS_THREADS_ACCESS_TOKEN",
        "token_kind": "Meta Threads access token",
        "minimum_permissions": ("threads_basic", "threads_keyword_search"),
        "check_command": "bin/hephaestus research platform-check --module platform.threads --source 'threads:keyword:agent browser'",
        "public_fallback_module": "platform.threads.public",
        "docs": (
            {
                "label": "Threads keyword search",
                "url": "https://developers.facebook.com/docs/threads/keyword-search/",
            },
            {
                "label": "Meta permissions reference",
                "url": "https://developers.facebook.com/docs/permissions/",
            },
        ),
    },
)


def run_research_credentials(*, home: Path | str | None = None) -> dict[str, Any]:
    """Return setup state for credentialed research modules without leaking secrets."""

    status = run_research_status(home=home)
    requirements = {
        str(item.get("id")): item
        for item in status.get("requirements", [])
        if isinstance(item, dict)
    }
    providers = [
        _provider_state(definition, requirements=requirements)
        for definition in PROVIDER_DEFINITIONS
    ]
    missing = [
        provider["id"]
        for provider in providers
        if provider["status"] != "ok"
    ]
    return {
        "schema": "agentlas.research.credentials.v0",
        "status": "ok" if not missing else "partial",
        "commands_will_run": False,
        "network_will_run": False,
        "credentials_exposed_to_model": False,
        "home": status.get("home") or str(home or ""),
        "providers": providers,
        "summary": {
            "credentialed_social_ok": bool(status.get("summary", {}).get("credentialed_social_ok")),
            "missing_provider_ids": missing,
            "missing_env": _dedupe(
                env
                for provider in providers
                for env in provider.get("missing_env", [])
            ),
            "present_env": _dedupe(
                env
                for provider in providers
                for env in provider.get("present_env", [])
            ),
            "public_fallbacks_ok": bool(status.get("summary", {}).get("public_social_fallbacks_ok")),
            "secret_values_exposed": False,
        },
        "next_commands": _dedupe(
            command
            for provider in providers
            if provider["status"] != "ok"
            for command in provider.get("next_commands", [])
        ),
        "safety": {
            "stores_tokens": False,
            "prints_token_values": False,
            "env_names_only": True,
            "operator_must_configure_provider_tokens": True,
        },
    }


def _provider_state(definition: dict[str, Any], *, requirements: dict[str, dict[str, Any]]) -> dict[str, Any]:
    requirement = requirements.get(str(definition["module_id"]), {})
    setup = requirement.get("setup") if isinstance(requirement.get("setup"), dict) else {}
    env_aliases = [str(item) for item in definition["env_aliases"]]
    alternatives = tuple(tuple(str(env) for env in group) for group in definition.get("env_alternatives", ()))
    present_env = _present_credential_env(alternatives) if alternatives else [name for name in env_aliases if os.environ.get(name)]
    missing_env = [] if present_env else env_aliases
    status = str(requirement.get("status") or "missing")
    if present_env and status == "needs_config":
        status = "needs_live_proof"
    next_commands: list[str] = []
    if missing_env:
        next_commands.append(f"export {definition['preferred_env']}='<{definition['token_kind']}>'")
        next_commands.extend(str(command) for command in definition.get("alternative_setup_commands", ()))
    if status != "ok":
        next_commands.append(str(definition["check_command"]))
    return {
        "id": definition["id"],
        "module_id": definition["module_id"],
        "label": definition["label"],
        "status": status,
        "proof_id": definition["proof_id"],
        "token_kind": definition["token_kind"],
        "preferred_env": definition["preferred_env"],
        "env_aliases": env_aliases,
        "env_alternatives": [list(group) for group in alternatives],
        "present_env": present_env[:2],
        "missing_env": missing_env,
        "minimum_permissions": list(definition["minimum_permissions"]),
        "public_fallback_module": definition["public_fallback_module"],
        "public_fallback_still_available": True,
        "check_command": definition["check_command"],
        "next_commands": next_commands,
        "docs": list(definition["docs"]),
        "readiness": {
            "state": setup.get("state") or ("ready" if present_env else "needs_config"),
            "reason": setup.get("reason") or ("" if present_env else f"missing_env:{'|'.join(env_aliases)}"),
            "secret_values_exposed": False,
        },
    }


def _dedupe(values) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        item = str(value or "")
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _present_credential_env(alternatives: tuple[tuple[str, ...], ...]) -> list[str]:
    for group in alternatives:
        if all(os.environ.get(name) for name in group):
            return list(group)
    return []
