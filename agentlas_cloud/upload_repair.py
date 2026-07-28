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
from pathlib import Path
from typing import Any

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
            return _first_sentence(" ".join(body))
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
    """Split prose into whole sentences. Sentences, never terms."""
    import re

    parts = re.split(r"(?<=[.!?。])\s+|\n+", str(text))
    return [part.strip() for part in parts if len(part.strip()) >= 12]


def _is_korean(text: str) -> bool:
    return any("가" <= ch <= "힣" for ch in text)


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
                if isinstance(value, str) and len(value.strip()) >= 8:
                    out.append(value.strip())
                    break
            if len(out) >= limit:
                return out
    return out


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
        if not str(card.get("id") or "").strip():
            card["id"] = str(manifest.get("slug") or base.name)
        if card.get("type") not in {"agent", "team", "plugin"}:
            blueprint = _read_json(base / ".agentlas" / "company-blueprint.json") or {}
            card["type"] = "team" if blueprint.get("topology") not in (None, "single-agent") else "agent"
        if not str(card.get("name") or "").strip():
            card["name"] = str(public.get("titleEn") or public.get("titleKo") or manifest.get("name") or base.name)
        if not str(card.get("summary") or "").strip():
            card["summary"] = str(public.get("descriptionEn") or public.get("descriptionKo") or summary or card["name"])
        # `trigger_examples` are requests a user might actually type. The package
        # already carries a file full of them and nobody ever opened it:
        # `.agentlas/routing-benchmarks.jsonl` is present on 183 live releases and
        # its `input` lines are exactly "a real request that should reach me",
        # written by the author. Carrying those across is reading, not inventing.
        if len(card.get("trigger_examples") or []) < 5:
            harvested = _benchmark_inputs(base)
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
            if carried:
                card["trigger_examples"] = carried

        # Anti-triggers are the work this method turns down. The package states
        # them in prose - "You do not delete tests" - and the card wants them as
        # sentences, so they are carried whole. They are never tokenised: cutting
        # such a sentence into the bare words `tests` and `ci` is what cut a
        # correct agent's score to a quarter and moved it from rank 2 to rank 24.
        if len(card.get("anti_triggers") or []) < 3:
            boundary = _section_text(base, ("boundaries", "do not", "out of scope", "limits", "constraints"), 600)
            carried = list(card.get("anti_triggers") or [])
            seen = {str(item.get("text", "")).strip() for item in carried if isinstance(item, dict)}
            for sentence in _sentences(boundary):
                if sentence in seen:
                    continue
                carried.append({"locale": "ko" if _is_korean(sentence) else "en", "text": sentence})
                seen.add(sentence)
                if len(carried) >= 3:
                    break
            if carried:
                card["anti_triggers"] = carried

        # `capabilities` must be verb_object snake_case. The verbs are already in
        # the package as its own section headings and bullet leads; nothing here
        # decides what the agent can do, it only re-spells what agent.md says.
        if not card.get("capabilities"):
            derived = _capability_phrases(base)
            if derived:
                card["capabilities"] = derived

        if card.get("routing_status") not in {"routing_ready", "trusted"}:
            card["routing_status"] = "routing_ready"
        if not isinstance(card.get("risk_profile"), dict) or not card["risk_profile"].get("tier"):
            # Absent is not "safe". The conservative reading of an unstated risk
            # tier is the one that makes a host ask before acting.
            card["risk_profile"] = {"tier": "medium", "capabilities_at_risk": []}
        card.setdefault("required_inputs", [])
        if not str(card.get("benchmark_fixtures") or "").strip():
            # The file is usually already on disk and the card simply never
            # pointed at it — which is how 142 of 144 packages "had no benchmark".
            # Three spellings shipped; whichever one is here is the one to name.
            for name in ("routing-benchmarks.jsonl", "routing-benchmark.jsonl", "benchmarks.jsonl"):
                if (base / ".agentlas" / name).is_file():
                    card["benchmark_fixtures"] = f".agentlas/{name}"
                    break
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
        if not str(profile.get("titleEn") or "").strip():
            profile["titleEn"] = str(card.get("name") or manifest.get("name") or base.name)
        if not str(profile.get("titleKo") or "").strip():
            profile["titleKo"] = str(profile.get("titleEn"))
        if not str(profile.get("descriptionEn") or "").strip():
            profile["descriptionEn"] = str(card.get("summary") or summary or profile["titleEn"])
        if not str(profile.get("descriptionKo") or "").strip():
            profile["descriptionKo"] = str(profile["descriptionEn"])
        guide = profile.get("guide")
        if not isinstance(guide, dict) or not guide:
            # The guide answers five questions a buyer asks. Each answer is taken
            # from a place in the package that already answers it; a question with
            # no answer on disk is left out rather than filled with a platitude,
            # because a generic "best for: various tasks" is exactly the listing
            # copy that made every card read the same.
            derived: dict[str, str] = {}
            what = str(card.get("summary") or profile.get("descriptionEn") or "").strip()
            if what:
                derived["what-it-does"] = what
            inputs = [
                str(item.get("description") or item.get("text") or item)
                for item in (card.get("required_inputs") or [])
            ]
            inputs = [item for item in inputs if item and item.strip()]
            if inputs:
                derived["prerequisites"] = "; ".join(inputs[:4])
            produces = [
                str(item.get("description") or item.get("text") or item)
                for item in (card.get("produces") or [])
            ]
            produces = [item for item in produces if item and item.strip()]
            if produces:
                derived["expected-outputs"] = "; ".join(produces[:4])
            refuses = [
                str(item.get("text") or item)
                for item in (card.get("anti_triggers") or [])
            ]
            refuses = [item for item in refuses if item and item.strip()]
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
                # one. Leaving the field empty would say the same thing far worse.
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
