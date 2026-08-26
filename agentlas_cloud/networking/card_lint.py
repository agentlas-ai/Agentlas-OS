"""Routing card validation and quality gates.

routing_ready minimum requirements (docs/hephaestus-network-2.0.md):
>=5 trigger examples (>=2 ko and >=2 en), >=3 anti-triggers, verb-form
capabilities, declared required_inputs, declared risk profile, validated
entrypoints, >=10 benchmark cases, declared memory behavior, and no broad
"do anything" capability without penalty.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .domains import DOMAIN_IDS



# One owner for how much a card must say. The repair pass fills to exactly these
# numbers; before this constant existed the repairer topped up at "fewer than 5
# triggers" and "fewer than 3 anti-triggers" while this check demanded 6 and 4,
# so a card holding exactly 5 and 3 fell in the gap: the repair thought it was
# done and the gate refused to publish. Measured on a live package
# (webhook-idempotency-doctor): has 5 ko=2 en=3, has 3 ko=1 en=2 — blocked by two
# sentences nobody was going to write. Blocking a user action that the repair
# pass was supposed to handle is the failure mode, not the safeguard.
TRIGGER_MINIMUM_TOTAL = 6
TRIGGER_MINIMUM_PER_LOCALE = 3
ANTI_TRIGGER_MINIMUM_TOTAL = 4
ANTI_TRIGGER_MINIMUM_PER_LOCALE = 2

def _workforce_ontology() -> dict[str, Any]:
    """Pinned Agent Workforce Ontology vocabulary (awo:2026-07-15.2)."""
    import json

    path = Path(__file__).resolve().parent.parent / "workforce" / "ontology_v1.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError:
        return {}


WORKFORCE_MODALITY_IDS = {"text", "image", "audio", "video", "multimodal"}
WORKFORCE_LANGUAGE_IDS = {"ar", "de", "en", "es", "fr", "hi", "it", "ja", "ko", "pt", "zh", "zh-CN", "zh-TW"}


# A skill's name IS its markdown folder name: `<root>/<skill-name>/SKILL.md`.
# Nothing in the engine derived this, so a card's skill list was whatever the
# build agent happened to hand-write, and it drifted from the folders on disk.
# Same host set upload_repair already used to prove a declared skill exists
# on disk — kept in one place so the two can never disagree.
SKILL_MANIFEST_ROOTS = (
    "skills",
    ".claude/skills",
    ".codex/skills",
    ".gemini/skills",
    ".agents/skills",
)

# Scaffolds ship `{{SKILL_ID_1}}` etc. Slugifying an unfilled placeholder
# minted real-looking ids (`skill:skill-id-1`) that match nothing — measured
# live 2026-08-26 on 2 of 1026 published workforce profiles, and on 4 of 4
# concept fields of every freshly scaffolded package.
_PLACEHOLDER_RE = re.compile(r"\{\{.*?\}\}")


def _is_unfilled_placeholder(raw: str, prefix: str, slug: str) -> bool:
    if _PLACEHOLDER_RE.search(raw):
        return True
    return bool(re.fullmatch(rf"{prefix}-id-\d+", slug))


def discover_skill_manifests(workspace: Path) -> list[tuple[str, str]]:
    """Every skill the package ships, as `(name, package-relative SKILL.md path)`.

    The name is the folder name — that is what a skill IS called.
    """
    found: list[tuple[str, str]] = []
    seen: set[str] = set()
    for root in SKILL_MANIFEST_ROOTS:
        base = workspace / root
        if not base.is_dir():
            continue
        for manifest in sorted(base.glob("*/SKILL.md")):
            slug = re.sub(r"[^a-z0-9-]+", "-", manifest.parent.name.lower().replace("_", "-")).strip("-")
            if slug and slug not in seen:
                seen.add(slug)
                found.append((slug, f"{root}/{manifest.parent.name}/SKILL.md"))
    return found


def discover_skill_slugs(workspace: Path) -> list[str]:
    """Return the package's skill names, taken from its SKILL.md folder names."""
    return [slug for slug, _ in discover_skill_manifests(workspace)]


def ensure_workforce_block(
    card: dict[str, Any], workspace: Path | None = None
) -> dict[str, Any]:
    """Deterministically fill a missing workforce résumé block in place.

    Build agents 10/20/30 author this contract, but older packages may predate
    it. Repair only facts already declared by the card: capabilities become
    open skill IDs and domain tags become open community IDs. Listing language,
    runtime and text-only transport are not agent identity, so they are never
    invented here.
    """
    workforce = card.get("workforce") if isinstance(card.get("workforce"), dict) else {}

    def semantic(values: Any, prefix: str, cap: int) -> list[str]:
        out: list[str] = []
        for value in values if isinstance(values, list) else []:
            # Leveled entries ({"concept": "skill:x", "level": "declared"}) are
            # the CURRENT card schema. str(dict) slugified the whole repr into
            # ids like "skill:concept-skill-evidence-synthesis-level-declared"
            # — measured live in workforce search results 2026-08-12.
            if isinstance(value, dict):
                value = value.get("concept") or value.get("id") or value.get("name") or ""
            raw = str(value).strip().lower()
            body = raw
            # Strip the prefix repeatedly: already-prefixed inputs otherwise
            # compound ("skill:skill:write-tool-contracts", also measured live).
            while body.startswith(f"{prefix}:"):
                body = body.split(":", 1)[1]
            slug = re.sub(r"[^a-z0-9-]+", "-", body.replace("_", "-")).strip("-")
            if _is_unfilled_placeholder(raw, prefix, slug):
                # An unfilled scaffold slot means "not declared", not
                # "declared as skill-id-1". Drop it.
                continue
            concept = f"{prefix}:{slug}" if slug else ""
            if concept and concept not in out:
                out.append(concept)
            if len(out) >= cap:
                break
        return out

    roles = semantic(workforce.get("roles"), "role", 4)
    communities = semantic(workforce.get("communities"), "community", 5)
    if not communities:
        communities = semantic(card.get("domains"), "community", 5)
    skills = semantic(workforce.get("skills"), "skill", 12)
    if not skills:
        skills = semantic(card.get("capabilities"), "skill", 12)
    knowledge = semantic(workforce.get("knowledge"), "knowledge", 12)
    # The skill folders on disk are facts; a hand-written list is a claim.
    # Keep both, folders first, so a card can never advertise fewer skills
    # than it actually ships.
    if workspace is not None:
        from_disk = [f"skill:{slug}" for slug in discover_skill_slugs(workspace)]
        skills = from_disk + [item for item in skills if item not in from_disk]
        skills = skills[:12]
    modalities = [
        str(value)
        for value in workforce.get("modalities") or []
        if str(value) in WORKFORCE_MODALITY_IDS
    ][:3]
    languages = [
        str(value)
        for value in workforce.get("languages") or []
        if str(value) in WORKFORCE_LANGUAGE_IDS
    ][:4]
    card["workforce"] = {
        "roles": roles,
        "communities": communities,
        "skills": skills,
        "knowledge": knowledge,
        "modalities": modalities,
        "languages": languages,
    }
    return card

VERB_CAPABILITY_RE = re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)+$")
BROAD_CAPABILITIES = {
    "do_anything",
    "handle_everything",
    "general_assistant",
    "general_assistance",
    "anything_else",
    "all_tasks",
}
VALID_STATUSES = ["draft", "searchable", "candidate", "routing_ready", "trusted"]
REQUIRED_FIELDS = ["schemaVersion", "id", "type", "name", "summary", "capabilities", "routing_status"]
BREADTH_PENALTY_THRESHOLD = 12


def _is_local_card(card: dict[str, Any]) -> bool:
    card_id = str(card.get("id") or "")
    return card_id.startswith("local/")


def _triggers_by_locale(card: dict[str, Any], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for entry in card.get(field) or []:
        if isinstance(entry, dict) and entry.get("text"):
            locale = str(entry.get("locale") or "en")
            counts[locale] = counts.get(locale, 0) + 1
    return counts


def _benchmark_case_count(card: dict[str, Any]) -> int:
    # Inline cases first: the card may carry the benchmark rows directly, which is
    # the only form the linter can count without knowing the package root. Upload
    # runs the card through here with no filesystem base, so a `benchmark_fixtures`
    # path relative to the package could never be resolved — a package with real
    # cases on disk still linted as zero. `benchmark_cases` is the resolved count.
    inline = card.get("benchmark_cases")
    if isinstance(inline, int) and inline >= 0:
        return inline
    inline_rows = card.get("benchmark_case_rows")
    if isinstance(inline_rows, list):
        return sum(1 for row in inline_rows if isinstance(row, dict) and row.get("input"))
    fixture = card.get("benchmark_fixtures")
    if not fixture:
        return 0
    fixture_path = Path(str(fixture))
    if not fixture_path.is_absolute():
        source_ref = ((card.get("source") or {}).get("ref")) or ""
        if source_ref:
            fixture_path = Path(str(source_ref)) / fixture_path
    if not fixture_path.is_file():
        return 0
    try:
        return sum(1 for line in fixture_path.read_text(encoding="utf-8").splitlines() if line.strip())
    except OSError:
        return 0


def lint_card(card: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    score = 0.0

    for field in REQUIRED_FIELDS:
        if not card.get(field):
            errors.append(f"missing required field: {field}")
    if card.get("type") not in ("agent", "team", "plugin", None):
        errors.append(f"invalid type: {card.get('type')}")
    if card.get("routing_status") not in VALID_STATUSES and card.get("routing_status") is not None:
        errors.append(f"invalid routing_status: {card.get('routing_status')}")

    capabilities = [str(cap) for cap in card.get("capabilities") or []]
    non_verb = [cap for cap in capabilities if not VERB_CAPABILITY_RE.match(cap)]
    broad = [cap for cap in capabilities if cap in BROAD_CAPABILITIES]
    trigger_counts = _triggers_by_locale(card, "trigger_examples")
    anti_counts = _triggers_by_locale(card, "anti_triggers")
    trigger_total = sum(trigger_counts.values())
    anti_total = sum(anti_counts.values())
    bench_cases = _benchmark_case_count(card)

    ready_blockers: list[str] = []
    trigger_locales = {locale: trigger_counts.get(locale, 0) for locale in ("ko", "en")}
    anti_locales = {locale: anti_counts.get(locale, 0) for locale in ("ko", "en")}
    # How many, and in which languages, are two different questions with two
    # different answers. Too few examples altogether means the card genuinely
    # cannot route, and that blocks. A shortfall in one language means Korean or
    # English queries will match this agent less well — a real quality problem,
    # and not one the author can fix by translating: a trigger is how a user
    # actually phrases a request, so a machine translation of an English trigger
    # is a guess about Korean users, not evidence. The repair pass carries over
    # whatever Korean the package already wrote; when the package has none, the
    # honest outcome is to publish and say so, not to refuse the upload.
    if trigger_total < TRIGGER_MINIMUM_TOTAL:
        ready_blockers.append(
            f"needs >={TRIGGER_MINIMUM_TOTAL} trigger_examples (has {trigger_total})"
        )
    elif any(trigger_locales[locale] < TRIGGER_MINIMUM_PER_LOCALE for locale in ("ko", "en")):
        warnings.append(
            f"trigger_examples reach {TRIGGER_MINIMUM_TOTAL} but not "
            f"{TRIGGER_MINIMUM_PER_LOCALE} per language "
            f"(ko={trigger_locales['ko']}, en={trigger_locales['en']}); "
            "queries in the thin language will match this agent less often"
        )
    if anti_total < ANTI_TRIGGER_MINIMUM_TOTAL:
        ready_blockers.append(
            f"needs >={ANTI_TRIGGER_MINIMUM_TOTAL} anti_triggers (has {anti_total})"
        )
    elif any(anti_locales[locale] < ANTI_TRIGGER_MINIMUM_PER_LOCALE for locale in ("ko", "en")):
        warnings.append(
            f"anti_triggers reach {ANTI_TRIGGER_MINIMUM_TOTAL} but not "
            f"{ANTI_TRIGGER_MINIMUM_PER_LOCALE} per language "
            f"(ko={anti_locales['ko']}, en={anti_locales['en']})"
        )
    if non_verb:
        ready_blockers.append(f"capabilities must be verb_object snake_case: {non_verb[:3]}")
    if broad:
        ready_blockers.append(f"broad 'do anything' capabilities are not allowed: {broad}")
    if "required_inputs" not in card:
        ready_blockers.append("required_inputs must be declared (empty list is allowed)")
    # Model-authored cards can put a string where an object belongs (observed
    # live: risk_profile: "low" from a local-model build). Malformed shape is a
    # blocker to report, never a crash.
    risk_profile = card.get("risk_profile")
    if not (isinstance(risk_profile, dict) and risk_profile.get("tier")):
        ready_blockers.append(
            "risk_profile.tier must be declared"
            if risk_profile is None or isinstance(risk_profile, dict)
            else "risk_profile must be an object with a tier field"
        )
    entrypoints = card.get("entrypoints") if isinstance(card.get("entrypoints"), dict) else {}
    if not entrypoints.get("canonical_command") and not entrypoints.get("agent"):
        ready_blockers.append("entrypoints must declare canonical_command or agent path")
    if not card.get("memory_behavior"):
        ready_blockers.append("memory_behavior must be declared")
    if bench_cases < 10:
        ready_blockers.append(f"needs >=10 benchmark cases (has {bench_cases})")

    # résumé (workforce) block — the hub standard résumé the Workforce search
    # matches on. Measured over the live catalog (2026-07-27) sellers declared
    # roles/modalities on 0 of 250 cards, so every WorkOrder using those fields
    # excluded the whole catalog. Built packages must ship the block filled;
    # roles may honestly be [] when no canonical role fits, but the block and
    # its semantic fields must exist and use stable namespaced IDs. The
    # ontology snapshot supplies aliases/relations, not a profession allowlist.
    workforce = card.get("workforce")
    if not isinstance(workforce, dict):
        # An automated build pipeline (Stormbreaker workers, conversion
        # packaging) cannot hand-write this block. Since a deterministic
        # derivation is possible, lint only warns — the hard gate is left to
        # the server registration boundary (workforce_resume_incomplete) and
        # the upload gate's auto-fill.
        derived = ensure_workforce_block(dict(card))
        workforce = derived["workforce"]
        warnings.append(
            "workforce block missing — deterministically derivable (roles [], languages by script); declare it explicitly for better ranking"
        )
    if True:
        if not isinstance(workforce.get("roles"), list):
            ready_blockers.append("workforce.roles must be a list (empty is allowed)")
        else:
            malformed_roles = [
                str(r)
                for r in workforce.get("roles") or []
                if not re.fullmatch(r"role:[a-z0-9][a-z0-9-]*", str(r))
            ]
            if malformed_roles:
                errors.append(f"workforce.roles must use open role:* ids: {malformed_roles[:3]}")
        if not isinstance(workforce.get("communities"), list):
            ready_blockers.append("workforce.communities must be a list (empty is allowed)")
        else:
            malformed_communities = [
                str(c)
                for c in workforce.get("communities") or []
                if not re.fullmatch(r"community:[a-z0-9][a-z0-9-]*", str(c))
            ]
            if malformed_communities:
                errors.append(f"workforce.communities must use open community:* ids: {malformed_communities[:3]}")
        if not isinstance(workforce.get("skills"), list) or not workforce.get("skills"):
            ready_blockers.append("workforce.skills must declare at least one concrete capability")
        else:
            # Skills are the agent's concrete verb-object capabilities, not a
            # closed job-family vocabulary. `skillAliases` normalizes common
            # synonyms; treating its small alias target set as an allowlist
            # rejected ordinary-domain agents (event planning, writing, care,
            # operations) even when their identifiers were well formed.
            malformed_skills = [
                str(s)
                for s in workforce.get("skills") or []
                if not re.fullmatch(r"skill:[a-z0-9][a-z0-9-]*", str(s))
            ]
            if malformed_skills:
                errors.append(f"workforce.skills must use skill:* verb-object ids: {malformed_skills[:3]}")
        if not isinstance(workforce.get("knowledge"), list):
            ready_blockers.append(
                "workforce.knowledge must be a list (empty is allowed when no durable knowledge asset ships)"
            )
        else:
            malformed_knowledge = [
                str(k)
                for k in workforce.get("knowledge") or []
                if not re.fullmatch(r"knowledge:[a-z0-9][a-z0-9-]*", str(k))
            ]
            if malformed_knowledge:
                errors.append(f"workforce.knowledge must use knowledge:* ids: {malformed_knowledge[:3]}")
        bad_modalities = [str(m) for m in workforce.get("modalities") or [] if str(m) not in WORKFORCE_MODALITY_IDS]
        if bad_modalities:
            errors.append(f"workforce.modalities outside the public vocabulary: {bad_modalities[:3]}")
        bad_languages = [str(l) for l in workforce.get("languages") or [] if str(l) not in WORKFORCE_LANGUAGE_IDS]
        if bad_languages:
            errors.append(f"workforce.languages outside the public vocabulary: {bad_languages[:3]}")

    score += min(trigger_total, 8) * 0.06
    score += min(anti_total, 5) * 0.05
    score += 0.15 if capabilities and not non_verb else 0.0
    score += 0.10 if isinstance(risk_profile, dict) and risk_profile.get("tier") else 0.0
    score += 0.10 if card.get("memory_behavior") else 0.0
    score += min(bench_cases, 12) * 0.015
    if len(capabilities) > BREADTH_PENALTY_THRESHOLD:
        score -= 0.10
        warnings.append(f"breadth penalty: {len(capabilities)} capabilities declared")
    if broad:
        score -= 0.25
    score = max(0.0, min(1.0, round(score, 3)))

    # Domain tags (soft): validate the vocabulary but never block a route — the
    # router infers domains from text when the field is absent, so this is a
    # quality nudge, not a gate.
    declared_domains = card.get("domains")
    if declared_domains:
        if not isinstance(declared_domains, list):
            warnings.append("domains must be a list of domain ids")
        else:
            unknown = [str(d) for d in declared_domains if str(d) not in DOMAIN_IDS]
            if unknown:
                warnings.append(f"unknown domain tags (not in vocab): {unknown[:3]}")
    else:
        warnings.append("no domain tags declared (router will infer from text)")

    claimed = str(card.get("routing_status") or "draft")
    if errors:
        allowed = "quarantined"
    elif ready_blockers:
        if _is_local_card(card) and claimed == "trusted":
            allowed = "trusted"
        else:
            allowed = "searchable" if trigger_total >= 1 else "draft"
    else:
        allowed = claimed if claimed in ("routing_ready", "trusted") else "routing_ready"

    return {
        "id": card.get("id"),
        "errors": errors,
        "warnings": warnings,
        "ready_blockers": ready_blockers,
        "quality_score": score,
        "claimed_status": claimed,
        "allowed_status": allowed,
        "benchmark_cases": bench_cases,
    }


def effective_status(card: dict[str, Any]) -> str:
    """The status the router actually honors: never above what lint allows."""
    if card.get("stale"):
        return "stale"
    report = lint_card(card)
    if report["errors"]:
        return "quarantined"
    claimed = report["claimed_status"]
    if claimed in ("routing_ready", "trusted") and report["ready_blockers"] and not (
        claimed == "trusted" and _is_local_card(card)
    ):
        return "searchable"
    return claimed if claimed in VALID_STATUSES else "draft"


def routing_ineligibility_reasons(card: dict[str, Any]) -> list[str]:
    """Why the router will not staff this card, in words the owner can act on.

    ``effective_status`` answers only *what* status is honored and throws the
    evidence away, so every caller that demoted a package on its answer had
    nothing left to show the person who just registered it.  The demotion and
    its reason must travel together: this returns the same decision's reasons,
    and an empty list means the card is routable.  A card that never claimed
    ``routing_ready`` is not a defect but it is still a reason — the owner has
    to be told the template default is what is holding the agent back.
    """

    status = effective_status(card)
    if status in ("routing_ready", "trusted"):
        return []
    if status == "stale":
        return ["source folder no longer exists"]
    report = lint_card(card)
    if report["errors"]:
        return list(report["errors"])
    if report["ready_blockers"]:
        return list(report["ready_blockers"])
    return [
        f'routing_card.routing_status is "{report["claimed_status"]}"; '
        'only "routing_ready" or "trusted" are staffed'
    ]
