"""Migrate existing Agentlas packages to routing-card v2.

Default status is ``draft`` for Hub/private/restricted/plugin cards, while local cards use
``trusted`` so they can be auto-routed without extra local promotion.
Auto routing still depends on ``effective_status`` for hard-gated errors.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .bootstrap import read_json, utc_now
from ..interview.schema import load_work_brief
from .card_store import save_card
from .domains import DOMAIN_IDS, classify_domains
from ..runtime import collect_package_files, package_hash

SCHEMA = "routing-card/2.0"
DEFAULT_RUNTIMES = ["claude-code", "codex", "gemini-cli", "agents-md"]


def _snake(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (value or "").lower()).strip("_")


def _derive_capabilities(card: dict[str, Any], slug: str) -> list[str]:
    capabilities: list[str] = []
    raw = card.get("capabilities")
    if isinstance(raw, list):
        for item in raw:
            snake = _snake(str(item))
            if "_" not in snake:
                snake = f"run_{snake}"
            capabilities.append(snake)
    elif isinstance(raw, dict):
        for skill in raw.get("skills") or []:
            capabilities.append(f"run_{_snake(str(skill))}")
    for worker in card.get("workers") or []:
        capabilities.append(f"coordinate_{_snake(str(worker))}")
    if not capabilities:
        core = _snake(slug)
        capabilities = [f"operate_{core}" if "_" not in core else core]
    seen: list[str] = []
    for capability in capabilities:
        if capability and capability not in seen:
            seen.append(capability)
    return seen[:16]


def _file_content_hash(path: Path) -> str | None:
    try:
        import hashlib

        return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"
    except OSError:
        return None


def _package_content_hash(pkg_dir: Path) -> str:
    return package_hash(
        [
            item
            for item in collect_package_files(pkg_dir)
            if item.path != "agentlas.json" and not item.path.endswith(".agentlas/routing-card.json")
        ]
    )


def _safety_risk(card: dict[str, Any]) -> dict[str, Any]:
    at_risk: list[str] = []
    safety = (card.get("capabilities") or {}).get("safety") if isinstance(card.get("capabilities"), dict) else None
    if isinstance(safety, dict):
        if safety.get("fileAccess"):
            at_risk.append("file_write")
        if safety.get("network") or safety.get("externalApi"):
            at_risk.append("cloud_call")
    return {"tier": "medium", "capabilities_at_risk": at_risk}


# Human/builder-authored content fields on a routing-card. On --overwrite we
# refresh infra/derived metadata (source hash, agent_card_ref, updated_at,
# quality) but keep these when the existing card already has a meaningful value,
# so a re-migrate never clobbers rich triggers/capabilities/domains/ko copy with
# agent-card-derived stubs (e.g. ["operate_<slug>"]).
_PRESERVE_CONTENT_KEYS = (
    "name", "name_ko", "summary", "summary_ko", "description", "aliases",
    "capabilities", "domains", "trigger_examples", "anti_triggers",
    "required_inputs", "optional_inputs", "required_plugins",
    "benchmark_fixtures", "known_failure_cases", "risk_profile", "cost_hints",
    "locale_coverage", "memory_behavior", "approval_requirements", "entrypoints",
)


def _is_meaningful(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, (str, list, dict)):
        return len(value) > 0
    return True


def _merge_preserving_existing(new_card: dict[str, Any], existing: dict[str, Any]) -> dict[str, Any]:
    merged = dict(new_card)
    for key in _PRESERVE_CONTENT_KEYS:
        if _is_meaningful(existing.get(key)):
            merged[key] = existing[key]
    rev = existing.get("revision")
    if isinstance(rev, int):
        merged["revision"] = rev + 1
    return merged


def migrate_package(
    pkg_dir: Path,
    tier: str,
    card_type: str | None = None,
    home: Path | str | None = None,
    overwrite: bool = False,
) -> dict[str, Any] | None:
    pkg_dir = Path(pkg_dir)
    if not pkg_dir.is_dir():
        return None
    slug = pkg_dir.name
    agent_card = read_json(pkg_dir / ".agentlas" / "agent-card.json", default={}) or {}
    manifest = read_json(pkg_dir / "manifest.json", default={}) or {}
    plugin_manifest = read_json(pkg_dir / "plugin.json", default={}) or {}
    package_commands = read_json(pkg_dir / ".agentlas" / "global-commands.json", default={}) or {}

    if card_type is None:
        if plugin_manifest or tier == "plugin":
            card_type = "plugin"
        elif agent_card.get("workers") or agent_card.get("orchestrator") or (pkg_dir / "agents").is_dir():
            card_type = "team"
        else:
            card_type = "agent"

    name = str(agent_card.get("name") or plugin_manifest.get("name") or manifest.get("name") or slug).strip() or slug
    name_ko = agent_card.get("display_name_ko") or agent_card.get("name_ko")
    description = str(
        agent_card.get("description") or plugin_manifest.get("description") or manifest.get("description") or name
    ).strip() or name
    summary = description[:240]

    runtimes = agent_card.get("runtime_targets") or agent_card.get("runtime")
    if isinstance(agent_card.get("capabilities"), dict):
        runtimes = runtimes or (agent_card["capabilities"].get("runtimeTargets"))
    if not isinstance(runtimes, list) or not runtimes:
        runtimes = list(DEFAULT_RUNTIMES)

    canonical_command = None
    for entry in package_commands.get("commands") or []:
        if isinstance(entry, dict) and entry.get("command"):
            canonical_command = str(entry["command"])
            break
    if not canonical_command and agent_card.get("command"):
        canonical_command = str(agent_card["command"])

    locale_ready = ["en"]
    if str(agent_card.get("language") or "").startswith("ko") or name_ko:
        locale_ready.append("ko")

    capabilities = _derive_capabilities(agent_card, slug)
    # Domain tags: trust an explicit agent-card `domains`/`category` (this is the
    # field the generator used to silently drop), else infer from the card text.
    raw_domains = agent_card.get("domains")
    if not raw_domains and agent_card.get("category"):
        raw_domains = [agent_card.get("category")]
    # Normalize before the DOMAIN_IDS membership filter so a non-canonical
    # category casing ("Finance", "GAME ") still maps to its domain id instead
    # of being silently dropped.
    domains = []
    for raw in (raw_domains or []):
        norm = str(raw).strip().lower()
        if norm in DOMAIN_IDS:
            domains.append(norm)
    if not domains:
        domains = classify_domains(name, description, " ".join(str(c) for c in capabilities))

    card_slug = slug.strip() or _snake(name) or "agent"
    card_id = f"{tier}/{card_slug}"
    default_local_status = "trusted" if tier == "local" else "draft"

    card: dict[str, Any] = {
        "schemaVersion": SCHEMA,
        "card_version": "2.0.0",
        "revision": 1,
        "id": card_id,
        "canonical_id": card_id,
        "type": card_type,
        "name": name,
        "name_ko": name_ko,
        "aliases": [],
        "summary": summary,
        "summary_ko": None,
        "description": description,
        "capabilities": capabilities,
        "domains": domains,
        "trigger_examples": [
            {"text": name, "locale": "en"},
            {"text": " ".join(description.split()[:10]), "locale": "en"},
        ],
        "anti_triggers": [],
        "required_inputs": [],
        "optional_inputs": [],
        "required_plugins": [],
        "supported_runtimes": [str(rt) for rt in runtimes][:8],
        "entrypoints": {
            "canonical_command": canonical_command,
            "agent": "AGENTS.md" if (pkg_dir / "AGENTS.md").is_file() else None,
        },
        "risk_profile": _safety_risk(agent_card),
        "approval_requirements": [],
        "memory_behavior": {"reads": "project", "writes": "project", "exports_to_cloud": False},
        "cloud_delegation_policy": "ask",
        "cost_hints": {"model_calls": "medium", "paid_api": False},
        "benchmark_fixtures": None,
        "known_failure_cases": [],
        "locale_coverage": {"primary": "en", "ready": locale_ready, "partial": []},
        "card_quality_score": 0.0,
        "routing_status": default_local_status,
        "routing_status_reason": "auto-migrated from agent-card.json; needs human review of triggers and benchmarks",
        "agent_card_ref": {"path": ".agentlas/agent-card.json", "slug": slug, "content_hash": _file_content_hash(pkg_dir / ".agentlas" / "agent-card.json")}
        if agent_card
        else None,
        "data_access": {"reads": ["project_memory"], "writes": ["project_files"], "exports": []},
        "approval_scope": {"grant": "per_call", "ttl_seconds": None},
        "quality": {"score": 0.0, "lint_version": SCHEMA, "evaluated_at": utc_now(), "benchmark_suites": []},
        # Package-local cards never embed absolute machine paths (public-safety
        # hard constraint); the global copy gets source.ref at save/reindex time.
        "source": {
            "kind": "local_path",
            "ref": None,
            "package_hash": _package_content_hash(pkg_dir),
            "package_version": manifest.get("version") or agent_card.get("version"),
        },
        "updated_at": utc_now(),
    }

    # Briefing interview output is the highest-quality card source: the user's
    # own words about what the agent must NOT do become anti_triggers verbatim
    # (always better than a generated guess), and the confirmed goal/acceptance
    # criteria replace the name/description trigger stubs.
    work_brief = load_work_brief(pkg_dir)
    if work_brief:
        anti_scope = [str(item).strip() for item in work_brief.get("anti_scope") or [] if str(item).strip()]
        if anti_scope:
            card["anti_triggers"] = [
                {"text": item, "locale": "ko" if any("가" <= ch <= "힣" for ch in item) else "en"}
                for item in anti_scope[:6]
            ]
        brief_triggers = [str(work_brief.get("goal") or "").strip()] + [
            str(item).strip() for item in work_brief.get("acceptance_criteria") or []
        ]
        brief_triggers = [item for item in brief_triggers if item][:6]
        if brief_triggers:
            card["trigger_examples"] = [
                {"text": item, "locale": "ko" if any("가" <= ch <= "힣" for ch in item) else "en"}
                for item in brief_triggers
            ]
        card["routing_status_reason"] = "derived from briefing interview work-brief; triggers/anti-triggers are user-confirmed"
        card["work_brief_ref"] = {
            "path": ".agentlas/work-brief.json",
            "ambiguity_score": (work_brief.get("metadata") or {}).get("ambiguity_score"),
        }

    local_path = pkg_dir / ".agentlas" / "routing-card.json"
    if local_path.exists():
        existing = read_json(local_path, default=None)
        if isinstance(existing, dict) and existing.get("id"):
            if not overwrite:
                if home is not None:
                    global_copy = dict(existing)
                    global_copy.setdefault("source", {})
                    global_copy["source"] = {**global_copy["source"], "kind": "local_path", "ref": str(pkg_dir)}
                    save_card(Path(home), global_copy)
                return {"id": existing.get("id"), "status": "kept_existing", "path": str(local_path)}
            # overwrite=True: refresh infra/derived metadata but preserve the
            # human-authored content already on the card, so a re-migrate never
            # downgrades a rich routing-card to agent-card-derived stubs.
            card = _merge_preserving_existing(card, existing)

    from .bootstrap import atomic_write_json

    local_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(local_path, card)
    if home is not None:
        global_copy = dict(card)
        global_copy["source"] = {**card["source"], "ref": str(pkg_dir)}
        save_card(Path(home), global_copy)
    return {"id": card_id, "status": "migrated", "type": card_type, "path": str(local_path)}


def migrate_tree(
    root: Path | str,
    tier: str,
    home: Path | str | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    root_path = Path(root)
    results: list[dict[str, Any]] = []
    skipped: list[str] = []

    def _has_package_metadata(path: Path) -> bool:
        return (
            (path / ".agentlas").is_dir() or (path / "plugin.json").is_file() or (path / "AGENTS.md").is_file()
        )

    if root_path.is_dir() and _has_package_metadata(root_path):
        result = migrate_package(root_path, tier=tier, home=home, overwrite=overwrite)
        if result:
            results.append(result)

    for child in sorted(root_path.iterdir()) if root_path.is_dir() else []:
        if not child.is_dir() or child.name.startswith(".") or child == root_path:
            continue
        has_metadata = _has_package_metadata(child)
        if not has_metadata:
            skipped.append(child.name)
            continue
        result = migrate_package(child, tier=tier, home=home, overwrite=overwrite)
        if result:
            results.append(result)
    return {
        "root": str(root_path),
        "tier": tier,
        "migrated": sum(1 for item in results if item.get("status") == "migrated"),
        "kept_existing": sum(1 for item in results if item.get("status") == "kept_existing"),
        "skipped": skipped,
        "results": results,
    }


def _infer_card_domains(card: dict[str, Any]) -> list[str]:
    triggers = " ".join(
        str(entry.get("text") or "")
        for entry in (card.get("trigger_examples") or [])
        if isinstance(entry, dict)
    )
    return classify_domains(
        str(card.get("name") or ""),
        str(card.get("name_ko") or ""),
        str(card.get("summary") or ""),
        str(card.get("summary_ko") or ""),
        " ".join(str(c) for c in (card.get("capabilities") or [])),
        triggers,
    )


def backfill_domains(home: Path | str | None = None, *, write: bool = True, overwrite: bool = False) -> dict[str, Any]:
    """Backfill ``domains`` onto existing global routing cards.

    Idempotent: cards that already declare domains are skipped unless
    ``overwrite=True``. Cards whose text yields no confident domain are left
    untouched (the router still infers at routing time).
    """
    from .bootstrap import networking_home
    from .card_store import load_global_cards, save_card

    base = Path(home) if home is not None else networking_home()
    cards, _quarantined = load_global_cards(base)
    updated: list[dict[str, Any]] = []
    skipped = 0
    for card in cards:
        if card.get("domains") and not overwrite:
            skipped += 1
            continue
        domains = _infer_card_domains(card)
        if not domains:
            skipped += 1
            continue
        card["domains"] = domains
        if write:
            # Strip internal (underscore-prefixed) keys such as _card_path before
            # persisting, so machine-absolute paths don't leak into the on-disk
            # card and the content hash isn't taken over them.
            clean = {k: v for k, v in card.items() if not str(k).startswith("_")}
            save_card(base, clean)
        updated.append({"id": card.get("id"), "domains": domains})
    return {"status": "ok", "home": str(base), "updated": len(updated), "skipped": skipped, "cards": updated}
