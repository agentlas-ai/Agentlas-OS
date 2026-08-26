"""Repair a package instead of refusing it.

Upload does not reject. A refusal hands the author a list of field names and
makes them guess the house format, and the measured result of that policy is a
catalogue where the required `capability-eval-plan.json` is present on 4% of
live releases and `mcp-policy.json` on 50% — the gate said no, and the packages
shipped anyway through whatever path did not check.

So the contract is inverted here: anything the server can derive from what the
package already says, the server writes. What it cannot derive it reports, and
only a defect that cannot be repaired without inventing a fact or deleting the
author's work still blocks.

Two classes, and the line between them is the whole design:

  repairable    the value exists somewhere in the package, or the safe fix is to
                REMOVE something (a symlink, a private path, an unreadable card).
                Removing is always safe; inventing never is.
  unrepairable  size and count limits. "Fixing" those means throwing away the
                author's content, which is their call and not the server's.

Every repair is recorded. A package that shipped different from its source has
to say so, in the same way `sanitize_upload_text` already announces the lines it
stripped.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from collections.abc import Mapping
from typing import Any

# The gate owns how much a card must say; this pass fills to exactly that. Two
# copies of the same number is how a card sitting at 5 triggers was declared
# repaired here and refused there.
from .routing_vocabulary import normalise_memory_reads, normalise_memory_writes
from .networking.card_lint import (
    ANTI_TRIGGER_MINIMUM_PER_LOCALE,
    ANTI_TRIGGER_MINIMUM_TOTAL,
    TRIGGER_MINIMUM_PER_LOCALE,
    TRIGGER_MINIMUM_TOTAL,
)

from .runtime import DEFAULT_ALLOW_READ, is_credential_store_path
# One definition of "is this actually answered", shared with the derive pass.
# A scaffold stencil is truthy and non-empty, so every plain `if not x` below
# reads `{{CAPABILITY_VERB_OBJECT_1}}` as a real capability and declines to fill
# it. Measured 2026-08-07: a freshly built package failed upload on exactly that.
from .repackage import is_unfilled

__all__ = ["REPAIRABLE_BLOCKERS", "repair_package", "classify_findings"]

# Everything the server can derive or safely strip. Anything not listed here is
# treated as unrepairable, so a NEW blocker added elsewhere blocks by default
# rather than being silently waved through by an open-ended rule.
REPAIRABLE_BLOCKERS = frozenset({
    "public-profile-required",
    "routing-card-invalid",
    "routing-card-invalid-json",
    "routing-card-server-invalid",
    "routing-card-lint-error",
    "routing-card-not-ready",
    "routing-card-status-not-ready",
    "public-profile-title",
    "public-profile-description",
    "public-profile-guide",
    "public-profile-guide-sections",
    "career-card-invalid",
    "career-card-kind",
    "career-card-local-path",
    "career-card-privacy",
    "symlink",
    "blocked-file",
})

# Repairing these would mean deleting the author's own content to fit a limit.
# That is a decision for the person who wrote it.
UNREPAIRABLE_BLOCKERS = frozenset({
    "large-file",
    "file-count-limit",
    "package-size-limit",
})


def classify_findings(findings: list[dict[str, Any]]) -> dict[str, Any]:
    """Split blockers into what the server will fix and what it will not."""
    repairable: list[dict[str, Any]] = []
    unrepairable: list[dict[str, Any]] = []
    for finding in findings:
        if finding.get("severity") != "blocker":
            continue
        # Finding ids carry a content hash suffix, so match on the stem.
        stem = str(finding.get("id", "")).rsplit("-", 1)[0]
        if stem in REPAIRABLE_BLOCKERS:
            repairable.append(finding)
        else:
            unrepairable.append(finding)
    return {"repairable": repairable, "unrepairable": unrepairable}


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _derived_entity_type(base: Path) -> tuple[str | None, str]:
    """What the package's own files say it is: "team", "agent", or None if silent.

    The declaration is not trusted over the structure. A package that ships a
    multi-node roster while its card says `agent` is sold at the single-agent
    price (3 credits instead of 10) and loses its execution graph downstream —
    measured 2026-07-29 on the live `analyst-team`, an HQ-routed roster listed
    as `entityKind: agent` with `agentCount: 1`.

    `topology` is not one shape across the corpus. Measured on live packages it
    is a bare string ("hub-and-spoke", "single-agent"), a whole {nodes, edges}
    graph, or absent entirely, so each form is read rather than assumed.
    """
    blueprint = _read_json(base / ".agentlas" / "company-blueprint.json") or {}
    topology = blueprint.get("topology")

    nodes: Any = None
    if isinstance(topology, dict):
        nodes = topology.get("nodes")
    elif isinstance(blueprint.get("nodes"), list):
        nodes = blueprint["nodes"]
    if isinstance(nodes, list) and len(nodes) >= 2:
        return "team", f"company-blueprint.json declares a {len(nodes)}-node roster"

    if isinstance(topology, str) and topology.strip():
        if topology.strip() == "single-agent":
            return "agent", "company-blueprint.json topology is single-agent"
        return "team", f"company-blueprint.json topology is {topology.strip()}"

    # No usable blueprint. A directory of agent definitions is the same evidence.
    definitions = sorted(path for path in base.glob("agents/*/agent.md"))
    if len(definitions) >= 2:
        return "team", f"the package ships {len(definitions)} agent definitions under agents/"
    if definitions:
        return "agent", "the package ships one agent definition under agents/"
    return None, "the package declares no roster"


def _widen_allow_read_to_declared_context(base: Path, manifest: dict[str, Any]) -> list[str]:
    """Let the runtime read the files the package's own agent cards require.

    A worker card that says "Required Context: webmaster_frontend/knowledge/
    stack-and-standards.md" is making a promise the runtime has to be able to
    keep. Nothing tied the two together, and the drift is not theoretical:
    measured 2026-07-29 across 143 live packages, `allowRead` came in 15
    different shapes, 128 of them a 5-entry list narrower than the current
    default, and 82 files that cards named as required were unreachable — the
    live `web-master` bundle could not open its own token architecture.

    So the reference is the authority, the same way package structure is the
    authority for entity type. Only paths that (a) a card actually names,
    (b) exist in the package, and (c) are not credential stores are added.
    """

    import fnmatch

    allow = manifest.get("allowRead")
    if not isinstance(allow, list) or not all(isinstance(item, str) for item in allow):
        return []

    referenced: set[str] = set()
    cards = sorted(base.glob("agents/*/agent.md"))
    for entry in ("AGENTS.md", "agent.md"):
        candidate = base / entry
        if candidate.is_file():
            cards.append(candidate)
    for card in cards:
        try:
            text = card.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for match in re.finditer(r"`([A-Za-z0-9_][A-Za-z0-9_./-]*\.(?:md|json|jsonl|css))`", text):
            referenced.add(match.group(1))

    additions: list[str] = []
    # The house default moved and published packages did not follow it: 128 of
    # the 143 measured still carry a 5-entry list written before `agents/**`,
    # `docs/**`, `contracts/**` and `benchmarks/**` were part of it. Re-uploading
    # brings a package up to the current floor rather than freezing whichever
    # default happened to exist the day it was first built.
    for pattern in DEFAULT_ALLOW_READ:
        if pattern not in allow and pattern not in additions:
            additions.append(pattern)

    for path in sorted(referenced):
        if not (base / path).is_file():
            continue
        if is_credential_store_path(path):
            continue
        if any(fnmatch.fnmatch(path, pattern) for pattern in allow):
            continue
        parent = str(Path(path).parent).replace("\\", "/")
        pattern = f"{parent}/**" if parent not in {"", "."} else path
        if pattern not in allow and pattern not in additions:
            additions.append(pattern)

    if additions:
        manifest["allowRead"] = allow + additions
    return additions


def _first_sentence(text: str, limit: int = 300) -> str:
    body = " ".join(str(text).split())
    if len(body) <= limit:
        return body
    cut = body[:limit]
    stop = max(cut.rfind(". "), cut.rfind("? "), cut.rfind("! "))
    return (cut[: stop + 1] if stop > 60 else cut).strip()


def _agent_summary(base: Path) -> str:
    """The package's own first paragraph, used when metadata is missing.

    Read, never written: this is the author's sentence carried into a field they
    left empty, not a description the server made up about their work.
    """
    for name in ("agent.md", "AGENTS.md", "README.md"):
        path = base / name
        if not path.is_file():
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        body: list[str] = []
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                if body:
                    break
                continue
            if stripped.startswith(("```", "|", ">", "-", "*")):
                continue
            body.append(stripped)
            if len(" ".join(body)) > 240:
                break
        if body:
            candidate = _first_sentence(" ".join(body))
            # Keep looking. `contract scaffold` writes a stencil `agent.md`, and
            # taking the first file that exists meant reading `{{ROLE}}` and never
            # reaching the AGENTS.md the author actually wrote - so the listing
            # description became the placeholder itself.
            if not is_unfilled(candidate):
                return candidate
    return ""


def _section_text(base: Path, headings: tuple[str, ...], limit: int = 300) -> str:
    """The body under the first matching section heading in the package's own prose."""
    for name in ("agent.md", "AGENTS.md", "README.md"):
        path = base / name
        if not path.is_file():
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        capturing = False
        body: list[str] = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("#"):
                if capturing:
                    break
                title = stripped.lstrip("# ").strip().lower()
                capturing = any(title.startswith(head) for head in headings)
                continue
            if not capturing or not stripped or stripped.startswith("```"):
                continue
            body.append(stripped.lstrip("-* ").strip())
            if len(" ".join(body)) > limit:
                break
        if body:
            return _first_sentence(" ".join(body), limit)
    return ""


def _sentences(text: str) -> list[str]:
    """Split prose into whole sentences. Sentences, never terms.

    A line still holding a `{{PLACEHOLDER}}` is a stencil, not something the
    author wrote, and harvesting one is how a card that carried five real trigger
    examples came back carrying twenty-five, twenty of them `{{BENCH_EN_REJECT_1}}`.
    Repair may only carry across content that already exists.
    """
    import re

    parts = re.split(r"(?<=[.!?。])\s+|\n+", str(text))
    return [
        part.strip()
        for part in parts
        if len(part.strip()) >= 12 and "{{" not in part
    ]


def _is_korean(text: str) -> bool:
    return any("가" <= ch <= "힣" for ch in text)


def _entry_text(entry: Any) -> str:
    if isinstance(entry, Mapping):
        return str(entry.get("text") or "").strip()
    return str(entry or "").strip()


def _locale_counts(card: Mapping[str, Any], field: str) -> dict[str, int]:
    counts = {"ko": 0, "en": 0}
    for entry in card.get(field) or []:
        if isinstance(entry, Mapping) and _entry_text(entry):
            locale = str(entry.get("locale") or "en")
            counts[locale] = counts.get(locale, 0) + 1
    return counts


def _needs_locale_topup(card: Mapping[str, Any], field: str, total: int, per_locale: int) -> bool:
    counts = _locale_counts(card, field)
    return sum(counts.values()) < total or any(counts.get(loc, 0) < per_locale for loc in ("ko", "en"))


def _korean_sentences(base: Path, limit: int = 12) -> list[str]:
    """Korean sentences the package already contains. Never a translation.

    Topping a card up to a Korean quota by translating its English is inventing
    a fact about how a Korean user would ask for this agent, and a routing card
    is matched against exactly that. So the only Korean allowed here is Korean
    the author already wrote: the public profile's Korean copy, a Korean summary,
    the human README, and Korean benchmark inputs.
    """

    found: list[str] = []
    manifest = _read_json(base / "agentlas.json") or {}
    profile = manifest.get("publicProfile") if isinstance(manifest.get("publicProfile"), Mapping) else {}
    guide = profile.get("guide") if isinstance(profile.get("guide"), Mapping) else {}
    card = _read_json(base / ".agentlas" / "routing-card.json") or {}

    pools: list[str] = []
    for value in (profile.get("descriptionKo"), profile.get("titleKo"), card.get("summary_ko")):
        if isinstance(value, str):
            pools.append(value)
    for value in guide.values():
        if isinstance(value, str):
            pools.append(value)
    for name in ("README_FOR_HUMANS.md", "README.ko.md", "agent.md", "AGENTS.md"):
        path = base / name
        if path.is_file():
            try:
                pools.append(path.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
    pools.extend(_benchmark_inputs(base, limit=24))

    for pool in pools:
        for sentence in _sentences(pool):
            if _is_korean(sentence) and sentence not in found:
                found.append(sentence)
            if len(found) >= limit:
                return found
    return found


def _balance_locales(entries: list[Any], total: int, per_locale: int, base: Path) -> list[Any]:
    """Fill a trigger list toward the gate's shape using the package's own words.

    What cannot be filled honestly is left short on purpose. The gate downgrades
    a locale shortfall to a warning precisely so that this function never has to
    fabricate a sentence in a language the package does not speak.
    """

    normalised = [entry for entry in entries if _entry_text(entry)]
    counts = {"ko": 0, "en": 0}
    seen: set[str] = set()
    for entry in normalised:
        text = _entry_text(entry)
        seen.add(text)
        locale = str(entry.get("locale") or "en") if isinstance(entry, Mapping) else "en"
        counts[locale] = counts.get(locale, 0) + 1

    if counts.get("ko", 0) < per_locale:
        for sentence in _korean_sentences(base):
            if sentence in seen:
                continue
            normalised.append({"locale": "ko", "text": sentence})
            seen.add(sentence)
            counts["ko"] += 1
            if counts["ko"] >= per_locale and len(normalised) >= total:
                break
    return normalised


def _card_phrases(value: Any) -> list[str]:
    """Read a routing-card list whose entries may be objects OR plain strings.

    Both shapes are real and both ship. The schema's own examples use objects
    with `description`/`text`, and a freshly scaffolded card carries strings —
    which is why deriving a market guide crashed with AttributeError on exactly
    the packages that needed one: a new build has no `publicProfile.guide`, so it
    entered this repair path, and its `required_inputs` were strings, so
    `item.get` did not exist. `cards lint` never caught it because linting a card
    and reading a card are different code.
    """

    phrases: list[str] = []
    for item in value or []:
        if isinstance(item, Mapping):
            text = item.get("description") or item.get("text") or item.get("label") or ""
        else:
            text = item
        text = str(text or "").strip()
        if text:
            phrases.append(text)
    return phrases


def _benchmark_inputs(base: Path, limit: int = 8) -> list[str]:
    """Real request sentences the author already wrote, from the routing benchmark.

    Both spellings are read: builds wrote `routing-benchmarks.jsonl` (183 live
    releases) and `routing-benchmark.jsonl` (3), and the contract previously
    pointed at `benchmarks/`, which no generation ever used.
    """
    out: list[str] = []
    for name in ("routing-benchmarks.jsonl", "routing-benchmark.jsonl", "benchmarks.jsonl"):
        path = base / ".agentlas" / name
        if not path.is_file():
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            for key in ("input", "query", "request", "prompt"):
                value = row.get(key) if isinstance(row, dict) else None
                # A scaffolded benchmark file is full of `{{BENCH_EN_REJECT_1}}`
                # until an author fills it. Carrying those across as trigger
                # examples turns a card with five real examples into one with
                # twenty-five, twenty of them stencil text.
                if isinstance(value, str) and len(value.strip()) >= 8 and "{{" not in value:
                    out.append(value.strip())
                    break
            if len(out) >= limit:
                return out
    return out


def _first_real(*values: Any) -> str:
    """First value that is actually answered - not empty, not a scaffold stencil.

    Checking only the TARGET is half the rule. A fill that reads `card["summary"]`
    while that field still holds `{{SUMMARY_EN}}` copies the stencil into the
    listing and ships the literal text `{{SUMMARY_EN}}` to a buyer - which is how a
    freshly built package failed upload on "descriptionKo needs at least 40
    characters (has 14)": the 14 characters were the placeholder.
    """

    for value in values:
        if not is_unfilled(value):
            return str(value).strip()
    return ""


def _capability_phrases(base: Path, limit: int = 8) -> list[str]:
    """verb_object phrases taken from the package's own section headings."""
    import re

    stop = {"the", "a", "an", "and", "or", "to", "of", "for", "with", "in", "on", "this", "that", "your", "its"}
    phrases: list[str] = []
    for name in ("agent.md", "AGENTS.md"):
        path = base / name
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            stripped = line.strip()
            if not (stripped.startswith("#") or stripped.startswith("- ") or stripped.startswith("* ")):
                continue
            body = stripped.lstrip("#-* ").strip()
            words = [w for w in re.findall(r"[A-Za-z][A-Za-z0-9]*", body.lower()) if w not in stop]
            if len(words) < 2:
                continue
            phrase = "_".join(words[:3])
            if re.fullmatch(r"[a-z][a-z0-9]*(_[a-z0-9]+)+", phrase) and phrase not in phrases:
                phrases.append(phrase)
            if len(phrases) >= limit:
                return phrases
    return phrases


def repair_package(base: Path, findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fix every repairable blocker in place. Returns one record per repair.

    Each record names the file, what was wrong, and where the replacement value
    came from — so the author can see that the server carried their own words
    across rather than inventing a description of their work.
    """
    base = Path(base)
    split = classify_findings(findings)
    if not split["repairable"]:
        return []

    repairs: list[dict[str, Any]] = []
    stems = {str(f.get("id", "")).rsplit("-", 1)[0] for f in split["repairable"]}

    card_path = base / ".agentlas" / "routing-card.json"
    manifest_path = base / "agentlas.json"
    manifest = _read_json(manifest_path) or {}
    public = manifest.get("publicProfile") if isinstance(manifest.get("publicProfile"), dict) else {}
    summary = _agent_summary(base)

    card_stems = {s for s in stems if s.startswith("routing-card")}
    if card_stems:
        card = _read_json(card_path)
        if not isinstance(card, dict):
            card = {}
            repairs.append({
                "file": ".agentlas/routing-card.json",
                "action": "rebuilt",
                "why": "the card was missing or not valid JSON, so nothing could be read from it",
            })
        before = json.dumps(card, sort_keys=True, ensure_ascii=False)

        card.setdefault("schemaVersion", "routing-card/2.0")
        if is_unfilled(card.get("id")):
            card["id"] = str(manifest.get("slug") or base.name)
        derived_type, type_evidence = _derived_entity_type(base)
        declared_type = card.get("type")
        if declared_type not in {"agent", "team", "plugin"}:
            card["type"] = derived_type or "agent"
        elif declared_type != "plugin" and derived_type and derived_type != declared_type:
            # Only a declaration the files actively contradict is overwritten. A
            # package whose structure is silent keeps whatever its author wrote:
            # filling a gap is derivation, but guessing against silence is not.
            card["type"] = derived_type
            repairs.append({
                "file": ".agentlas/routing-card.json",
                "action": "corrected",
                "why": f"the card said type={declared_type} but {type_evidence}",
            })
        if is_unfilled(card.get("name")):
            card["name"] = str(public.get("titleEn") or public.get("titleKo") or manifest.get("name") or base.name)
        if is_unfilled(card.get("summary")):
            card["summary"] = str(public.get("descriptionEn") or public.get("descriptionKo") or summary or card["name"])
        # `trigger_examples` are requests a user might actually type. The package
        # already carries a file full of them and nobody ever opened it:
        # `.agentlas/routing-benchmarks.jsonl` is present on 183 live releases and
        # its `input` lines are exactly "a real request that should reach me",
        # written by the author. Carrying those across is reading, not inventing.
        # Top up to what the gate asks for, per language — not to a number that
        # merely resembles it. The old condition stopped at "fewer than 5" while
        # the gate demanded 6 with 3 of each language, so a card sitting at 5
        # (ko=2, en=3) was declared repaired and then refused at publish. The user
        # action was blocked by exactly the sentences this pass exists to supply.
        if _needs_locale_topup(card, "trigger_examples", TRIGGER_MINIMUM_TOTAL, TRIGGER_MINIMUM_PER_LOCALE):
            harvested = _benchmark_inputs(base, limit=24)
            existing = {
                str(item.get("text", "")).strip()
                for item in (card.get("trigger_examples") or [])
                if isinstance(item, dict)
            }
            carried = list(card.get("trigger_examples") or [])
            for sentence in harvested:
                if sentence in existing:
                    continue
                carried.append({"locale": "ko" if _is_korean(sentence) else "en", "text": sentence})
                existing.add(sentence)
            card["trigger_examples"] = _balance_locales(
                carried, TRIGGER_MINIMUM_TOTAL, TRIGGER_MINIMUM_PER_LOCALE, base
            )

        # Anti-triggers are the work this method turns down. The package states
        # them in prose - "You do not delete tests" - and the card wants them as
        # sentences, so they are carried whole. They are never tokenised: cutting
        # such a sentence into the bare words `tests` and `ci` is what cut a
        # correct agent's score to a quarter and moved it from rank 2 to rank 24.
        if _needs_locale_topup(
            card, "anti_triggers", ANTI_TRIGGER_MINIMUM_TOTAL, ANTI_TRIGGER_MINIMUM_PER_LOCALE
        ):
            boundary = _section_text(base, ("boundaries", "do not", "out of scope", "limits", "constraints"), 900)
            carried = list(card.get("anti_triggers") or [])
            seen = {str(item.get("text", "")).strip() for item in carried if isinstance(item, dict)}
            for sentence in _sentences(boundary):
                if sentence in seen:
                    continue
                carried.append({"locale": "ko" if _is_korean(sentence) else "en", "text": sentence})
                seen.add(sentence)
            card["anti_triggers"] = _balance_locales(
                carried, ANTI_TRIGGER_MINIMUM_TOTAL, ANTI_TRIGGER_MINIMUM_PER_LOCALE, base
            )

        # `capabilities` must be verb_object snake_case. The verbs are already in
        # the package as its own section headings and bullet leads; nothing here
        # decides what the agent can do, it only re-spells what agent.md says.
        if is_unfilled(card.get("capabilities")):
            derived = _capability_phrases(base)
            if derived:
                card["capabilities"] = derived

        if card.get("routing_status") not in {"routing_ready", "trusted"}:
            card["routing_status"] = "routing_ready"
        if not isinstance(card.get("risk_profile"), dict) or not card["risk_profile"].get("tier"):
            # Absent is not "safe". The conservative reading of an unstated risk
            # tier is the one that makes a host ask before acting.
            card["risk_profile"] = {"tier": "medium", "capabilities_at_risk": []}
        # A declared skill with no body is an advertisement for nothing. The Hub
        # wizard used to stamp the literal id `agentlas-package` on any package
        # that shipped no skills; measured on the live corpus, 88 packages
        # declare it and 0 carry `skills/agentlas-package/SKILL.md`, and no such
        # skill exists in the engine either. The Workforce index matched work
        # against a capability nobody has. The producer is fixed; this clears the
        # packages that already carry it.
        #
        # Only ids with no file on disk are dropped, and only from the manifest —
        # a skill the package really ships is never touched.
        declared = manifest.get("skills")
        if isinstance(declared, list) and declared:
            from .networking.card_lint import discover_skill_slugs

            present = set(discover_skill_slugs(base))
            kept = [skill for skill in declared if not isinstance(skill, str) or skill in present]
            dropped = [skill for skill in declared if isinstance(skill, str) and skill not in present]
            if dropped:
                manifest["skills"] = kept
                # Written here rather than left to the manifest write further
                # down: that one lives in the public-profile branch and only
                # fires when the profile itself changed, so this repair was
                # reported and not applied — a receipt for something that did not
                # happen, which is worse than either doing it or saying nothing.
                (base / "agentlas.json").write_text(
                    json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
                )
                repairs.append({
                    "file": "agentlas.json",
                    "action": "removed",
                    "why": f"declared skill(s) with no SKILL.md in the package: {', '.join(dropped[:4])}",
                    "source": "the package's own skills/ folders",
                })

        # A card that says it reads "task input only" is describing something
        # narrower than either value the schema used to admit. Normalise the
        # spelling; never silently widen what the author declared.
        mb = card.get("memory_behavior")
        if isinstance(mb, Mapping):
            fixed = dict(mb)
            reads = normalise_memory_reads(fixed.get("reads"))
            writes = normalise_memory_writes(fixed.get("writes"))
            if reads:
                fixed["reads"] = reads
            if writes:
                fixed["writes"] = writes
            if fixed != dict(mb):
                card["memory_behavior"] = fixed
        card.setdefault("required_inputs", [])
        # Point the card at whichever benchmark file is on disk (three spellings
        # shipped), or, when none has >=10 cases, synthesise one from the trigger
        # sentences the card already carries. A benchmark case is "a request that
        # should route here", and a route trigger is exactly that — so this is
        # carrying the author's own sentences into a second shape, not inventing
        # test data. A package with real triggers but no benchmark file (measured:
        # ai-engineering-team, 12 triggers, 0 cases) was blocked for a file it
        # could always have generated.
        bench_path: Path | None = None
        for name in ("routing-benchmarks.jsonl", "routing-benchmark.jsonl", "benchmarks.jsonl"):
            candidate = base / ".agentlas" / name
            if candidate.is_file():
                bench_path = candidate
                break
        bench_count = 0
        if bench_path is not None:
            bench_count = sum(1 for line in bench_path.read_text(encoding="utf-8").splitlines() if line.strip())
        if bench_count < 10:
            triggers = [
                str(item.get("text", "")).strip()
                for item in (card.get("trigger_examples") or [])
                if isinstance(item, dict) and str(item.get("text", "")).strip()
            ]
            antis = [
                str(item.get("text", "")).strip()
                for item in (card.get("anti_triggers") or [])
                if isinstance(item, dict) and str(item.get("text", "")).strip()
            ]
            if len(triggers) + len(antis) >= 5:
                lines = [
                    json.dumps({"input": text, "expect": "route"}, ensure_ascii=False)
                    for text in triggers
                ] + [
                    json.dumps({"input": text, "expect": "reject"}, ensure_ascii=False)
                    for text in antis
                ]
                bench_path = base / ".agentlas" / "routing-benchmarks.jsonl"
                bench_path.parent.mkdir(parents=True, exist_ok=True)
                bench_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        if bench_path is not None:
            if is_unfilled(card.get("benchmark_fixtures")):
                card["benchmark_fixtures"] = f".agentlas/{bench_path.name}"
            # Record the resolved count on the card so the linter — which runs
            # with no package root and cannot resolve the fixture path — counts
            # the cases that are genuinely on disk rather than seeing zero.
            try:
                rows = [
                    line for line in bench_path.read_text(encoding="utf-8").splitlines() if line.strip()
                ]
                card["benchmark_cases"] = len(rows)
            except OSError:
                pass
        entry = card.get("entrypoints")
        if not isinstance(entry, dict) or not (entry.get("canonical_command") or entry.get("agent")):
            # The entry point is a fact on disk, not a preference: whichever
            # definition file the package actually ships is the one a host opens.
            definition = next(
                (name for name in ("agent.md", "AGENTS.md", "CLAUDE.md") if (base / name).is_file()),
                "agent.md",
            )
            entry = entry if isinstance(entry, dict) else {}
            entry.setdefault("agent", definition)
            commands = _read_json(base / ".agentlas" / "global-commands.json") or {}
            declared = commands.get("commands") if isinstance(commands, dict) else None
            if isinstance(declared, list):
                for item in declared:
                    if isinstance(item, dict) and str(item.get("command") or "").startswith("/"):
                        entry.setdefault("canonical_command", str(item["command"]))
                        break
            card["entrypoints"] = entry
        if not isinstance(card.get("memory_behavior"), (dict, str)) or not card.get("memory_behavior"):
            # Read off the manifest's own memory policy rather than assumed. A
            # package that never declared write-back does not get one here.
            policy = manifest.get("memoryPolicy") if isinstance(manifest, dict) else None
            policy = policy if isinstance(policy, dict) else {}
            card["memory_behavior"] = {
                "reads": "task input only",
                "writes": str(policy.get("writeBack") or "none"),
                "exports_to_cloud": bool(policy.get("publicCopy") not in (None, "reset")),
            }

        # Build agents and upload use the same résumé projector. This runs after
        # capability repair so an old or partial card is completed instead of
        # being rejected for fields the package already proves.
        from .networking.card_lint import ensure_workforce_block

        ensure_workforce_block(card, base)
        workforce = card["workforce"]
        declared_knowledge = list(workforce.get("knowledge") or [])
        for knowledge_file in sorted(base.glob("**/knowledge/*")):
            if not knowledge_file.is_file() or knowledge_file.suffix.lower() not in {".md", ".markdown", ".txt"}:
                continue
            slug = re.sub(r"[^a-z0-9-]+", "-", knowledge_file.stem.lower().replace("_", "-")).strip("-")
            concept = f"knowledge:{slug}" if slug else ""
            if concept and concept not in declared_knowledge:
                declared_knowledge.append(concept)
            if len(declared_knowledge) >= 12:
                break
        workforce["knowledge"] = declared_knowledge[:12]

        if json.dumps(card, sort_keys=True, ensure_ascii=False) != before:
            card_path.parent.mkdir(parents=True, exist_ok=True)
            card_path.write_text(json.dumps(card, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            repairs.append({
                "file": ".agentlas/routing-card.json",
                "action": "filled",
                "why": "required routing fields were missing",
                "source": "agentlas.json publicProfile, then the package's own first paragraph",
            })

    profile_stems = {s for s in stems if s.startswith("public-profile")}
    if profile_stems and isinstance(manifest, dict):
        before = json.dumps(manifest, sort_keys=True, ensure_ascii=False)
        profile = manifest.setdefault("publicProfile", {})
        card = _read_json(card_path) or {}
        if is_unfilled(profile.get("titleEn")):
            profile["titleEn"] = _first_real(card.get("name"), manifest.get("name"), base.name)
        if is_unfilled(profile.get("titleKo")):
            # The card's own Korean name is already on disk; falling straight
            # back to English shipped English titleKo on every package that had
            # a perfectly good name_ko (measured 2026-08-12 on both .builds).
            profile["titleKo"] = _first_real(card.get("name_ko"), profile.get("titleEn"))
        if is_unfilled(profile.get("descriptionEn")):
            profile["descriptionEn"] = _first_real(card.get("summary"), summary, _agent_summary(base), profile["titleEn"])
        if is_unfilled(profile.get("descriptionKo")):
            profile["descriptionKo"] = _first_real(card.get("summary_ko"), profile["descriptionEn"])
        guide = profile.get("guide")
        if not isinstance(guide, dict) or not guide:
            # The guide answers five questions a buyer asks. Each answer is taken
            # from a place in the package that already answers it; a question with
            # no answer on disk is left out rather than filled with a platitude,
            # because a generic "best for: various tasks" is exactly the listing
            # copy that made every card read the same.
            derived: dict[str, str] = {}
            what = _first_real(card.get("summary"), profile.get("descriptionEn"))
            if what:
                derived["what-it-does"] = what
            inputs = _card_phrases(card.get("required_inputs"))
            if inputs:
                derived["prerequisites"] = "; ".join(inputs[:4])
            produces = _card_phrases(card.get("produces"))
            if produces:
                derived["expected-outputs"] = "; ".join(produces[:4])
            refuses = _card_phrases(card.get("anti_triggers"))
            if refuses:
                derived["careful-with"] = "Not for: " + "; ".join(refuses[:3])
            # The remaining questions get answered from sources that are reliably
            # THERE, rather than from section headings — chasing heading names is
            # reading the author's vocabulary again, and this package proves the
            # point: its whole agent.md is "What you do" and "Boundaries", which
            # matches no house list.
            #
            # `best-for` is the strongest of these. The requests a package should
            # receive are already written down, by the author, in the routing
            # benchmark nobody ever opened.
            if "best-for" not in derived:
                examples = [
                    str(item.get("text", "")).strip()
                    for item in (card.get("trigger_examples") or [])
                    if isinstance(item, dict) and str(item.get("text", "")).strip()
                ]
                if examples:
                    derived["best-for"] = "Requests like: " + " / ".join(examples[:3])
            if "prerequisites" not in derived:
                # An explicit "nothing required" is a concrete answer and a useful
                # one — but only when it is TRUE. This branch used to write it
                # unconditionally, telling marketplace users "no required inputs"
                # for packages whose routing card requires them (measured
                # 2026-08-12: market-sentiment-digest requires `ticker`).
                required = [
                    str(item.get("name", "")).strip()
                    for item in (card.get("required_inputs") or [])
                    if isinstance(item, dict) and str(item.get("name", "")).strip()
                ]
                if required:
                    derived["prerequisites"] = "Requires: " + ", ".join(required)
                else:
                    derived["prerequisites"] = (
                        "The package declares no required inputs; describe the work and it starts from there."
                    )
            if "expected-outputs" not in derived and card.get("capabilities"):
                derived["expected-outputs"] = "Produces: " + ", ".join(
                    str(item).replace("_", " ") for item in list(card["capabilities"])[:4]
                )
            if "careful-with" not in derived:
                limits = _section_text(base, ("boundaries", "do not", "limits", "out of scope", "safety", "constraints"))
                if limits:
                    derived["careful-with"] = limits
            if derived:
                profile["guide"] = derived
        widened = _widen_allow_read_to_declared_context(base, manifest)
        if widened:
            repairs.append({
                "file": "agentlas.json",
                "action": "widened",
                "why": "agent cards name these files as required context but allowRead did not reach them: "
                       + ", ".join(widened),
            })
        if json.dumps(manifest, sort_keys=True, ensure_ascii=False) != before:
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            repairs.append({
                "file": "agentlas.json",
                "action": "filled",
                "why": "the public listing had no title or description",
                "source": "routing card, then the package's own first paragraph",
            })

    # A career card that cannot be parsed, or that carries a local path or personal
    # detail, is REMOVED rather than rewritten. Dropping it costs the package one
    # optional surface; guessing at its contents would publish a claim its author
    # never made.
    career_stems = {s for s in stems if s.startswith("career-card")}
    if career_stems:
        career_path = base / ".agentlas" / "public-career-card.json"
        if career_path.is_file():
            career_path.unlink()
            repairs.append({
                "file": ".agentlas/public-career-card.json",
                "action": "removed",
                "why": "unreadable, or it carried a local path or personal detail; "
                       "removing is safe where rewriting would publish an unmade claim",
            })

    return repairs
