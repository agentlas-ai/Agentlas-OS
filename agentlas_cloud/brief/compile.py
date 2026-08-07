"""Compile a package directory into an `agentlas.brief/1` offer.

Deterministic. No model runs here. Everything this module emits is either read
verbatim off a file the package already ships, or computed from a schema's
topology - and every field records which of those it was, so a later reader can
tell an author's sentence from a derived fact from a gap.

The gaps are the point. `provenance.from = "absent"` scores zero and stays
absent; nothing here fills a hole with something plausible. The measured history
of doing otherwise is a catalogue where `capabilities` was
`snake_case(agent.md ## Responsibilities)` in 130 of 130 packages - a field that
was always full and never carried information.

What this module cannot do without a model is invent an intake or output schema
for a package that never wrote one. Those come back `absent`, which is the
honest answer and tells the caller exactly where a model is actually needed.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from .shape import classify_shape

__all__ = ["compile_offer", "BRIEF_VERSION"]

BRIEF_VERSION = "agentlas.brief/1"

# Effects, in the order a requester feels them. Derived from what the package
# says it must ask permission for, never from what it calls itself.
_WRITE_HINTS = ("write", "commit", "publish", "deploy", "upload", "push", "install", "delete", "modify", "patch")
_TRANSACT_HINTS = ("pay", "purchase", "order", "transfer", "send", "post to", "submit to", "charge", "book")


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _digest(path: Path) -> str | None:
    try:
        return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _texts(value: Any) -> list[str]:
    """Pull sentences out of a field that may be strings or {text: …} objects."""
    out: list[str] = []
    if isinstance(value, str):
        out.append(value)
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, str):
                out.append(item)
            elif isinstance(item, Mapping):
                for key in ("text", "description", "about", "value"):
                    candidate = item.get(key)
                    if isinstance(candidate, str) and candidate.strip():
                        out.append(candidate)
                        break
    return [item.strip() for item in out if item and item.strip()]


def _effect_of(sentence: str) -> str:
    lowered = sentence.lower()
    if any(hint in lowered for hint in _TRANSACT_HINTS):
        return "transact"
    if any(hint in lowered for hint in _WRITE_HINTS):
        return "modify"
    return "other"


def _schema_contents(schema: Mapping[str, Any], limit: int = 40) -> list[str]:
    """What is actually inside the deliverable, as readable sentences.

    A schema's title is usually the package's own name again. What separates one
    output from another is what it CONTAINS — measured: a request for a "contract
    alignment log with a provision-level verdict" ranked the correct package 4th,
    because that phrase names a PROPERTY inside its schema while the title said
    only "DORA Compliance Control Room — output".

    Property names are split back into words so a reader sees `contractAlignmentLog`
    as "contract alignment log". That is de-camelCasing an identifier, not
    tokenising a sentence: the author's own descriptions are carried whole.
    """
    import re

    out: list[str] = []
    seen: set[str] = set()

    def words(name: str) -> str:
        spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", str(name))
        return re.sub(r"[_\-]+", " ", spaced).strip().lower()

    def walk(node: Any, depth: int = 0) -> None:
        if len(out) >= limit or depth > 4 or not isinstance(node, Mapping):
            return
        props = node.get("properties")
        if isinstance(props, Mapping):
            for name, child in props.items():
                if len(out) >= limit:
                    return
                phrase = words(name)
                description = child.get("description") if isinstance(child, Mapping) else None
                if isinstance(description, str) and description.strip():
                    phrase = f"{phrase}: {description.strip()}"
                if phrase and phrase not in seen:
                    seen.add(phrase)
                    out.append(phrase[:400])
                walk(child, depth + 1)
        items = node.get("items")
        if isinstance(items, Mapping):
            walk(items, depth + 1)
        defs = node.get("$defs") or node.get("definitions")
        if isinstance(defs, Mapping):
            for child in defs.values():
                walk(child, depth + 1)

    walk(schema)
    return out


def compile_offer(root: Path) -> dict[str, Any]:
    """Build the offer side of the brief for the package rooted at `root`."""
    root = Path(root)
    card = _load(root / ".agentlas" / "routing-card.json") or {}
    manifest = _load(root / "agentlas.json") or {}
    policy = _load(root / ".agentlas" / "mcp-policy.json") or {}

    provenance: dict[str, dict[str, Any]] = {}

    def note(pointer: str, origin: str, file: str | None = None, method: str | None = None) -> None:
        entry: dict[str, Any] = {"from": origin}
        if file:
            entry["file"] = file
        if method:
            entry["method"] = method
        provenance[pointer] = entry

    # --- statement -----------------------------------------------------------
    statement = ""
    for key in ("summary_ko", "summary", "description"):
        value = card.get(key)
        if isinstance(value, str) and value.strip():
            statement = value.strip()
            break
    if not statement:
        public = manifest.get("publicProfile") or {}
        for key in ("descriptionKo", "descriptionEn"):
            value = public.get(key)
            if isinstance(value, str) and value.strip():
                statement = value.strip()
                break
    note("/statement", "read" if statement else "absent",
         ".agentlas/routing-card.json" if statement else None,
         "author sentence carried through whole; never tokenised")

    locale = card.get("locale_coverage")
    if isinstance(locale, Mapping):
        locale = [
            locale.get("primary"),
            *(locale.get("ready") or []),
            *(locale.get("partial") or []),
        ]
        locale = sorted({str(item) for item in locale if item})
    if not isinstance(locale, list) or not locale:
        locale = sorted({str(item.get("locale")) for item in (card.get("trigger_examples") or [])
                         if isinstance(item, Mapping) and item.get("locale")}) or ["en"]

    # --- deliverables --------------------------------------------------------
    deliverables: list[dict[str, Any]] = []
    output_schema_path = root / "contracts" / "output.schema.json"
    if not output_schema_path.is_file():
        # Pre-contract generations wrote domain-named schemas with no direction
        # marker. Take every schema that is not the intake one; direction stays
        # unknown, which is why the contract now fixes these two filenames.
        candidates = sorted(p for p in (root / "contracts").glob("*.schema.json")
                            if "intake" not in p.name.lower())
    else:
        candidates = [output_schema_path]

    for path in candidates:
        schema = _load(path)
        if not isinstance(schema, Mapping):
            continue
        shape, pointer, values = classify_shape(schema)
        title = schema.get("title")
        label = title.strip() if isinstance(title, str) and title.strip() else path.stem.replace("-", " ")
        entry: dict[str, Any] = {
            "label": label,
            "effect": "describe",
            "shape": shape,
            "format": ["json"],
            "contract": str(path.relative_to(root)),
            "contains": _schema_contents(schema),
        }
        digest = _digest(path)
        if digest:
            entry["contractDigest"] = digest
        if pointer:
            entry["rowVerdict"] = pointer
            entry["verdictValues"] = values
        deliverables.append(entry)
        index = len(deliverables) - 1
        note(f"/deliverables/{index}/shape", "extracted", str(path.relative_to(root)),
             "computed from schema topology only - no title, description or filename read")

    # Artefacts the card advertises but no schema backs. Label only: a claimed
    # output with no contract can be shown and ranked, never structurally matched.
    if not deliverables:
        for sentence in _texts(card.get("produces")):
            deliverables.append({"label": sentence, "effect": _effect_of(sentence)})
            note(f"/deliverables/{len(deliverables) - 1}", "read", ".agentlas/routing-card.json")

    if not deliverables:
        note("/deliverables", "absent", None, "no output schema and no declared artefacts")

    # --- obligations ---------------------------------------------------------
    obligations: list[dict[str, Any]] = []
    intake = _load(root / "contracts" / "intake.schema.json")
    intake_required: set[str] = set()
    if isinstance(intake, Mapping):
        required = intake.get("required")
        if isinstance(required, list):
            intake_required = {str(item) for item in required}
        props = intake.get("properties")
        if isinstance(props, Mapping):
            for name, node in props.items():
                about = ""
                if isinstance(node, Mapping):
                    description = node.get("description")
                    if isinstance(description, str) and description.strip():
                        about = description.strip()
                obligations.append({
                    "about": about or str(name),
                    "stage": "request" if str(name) in intake_required else "intake",
                    "required": str(name) in intake_required,
                    "pointer": f"contracts/intake.schema.json#/properties/{name}",
                })
                note(f"/obligations/{len(obligations) - 1}", "extracted", "contracts/intake.schema.json")

    if not obligations:
        for sentence in _texts(card.get("required_inputs")):
            obligations.append({"about": sentence, "stage": "intake", "required": True})
            note(f"/obligations/{len(obligations) - 1}", "read", ".agentlas/routing-card.json")

    if not obligations:
        note("/obligations", "absent")

    # --- authority -----------------------------------------------------------
    gated: list[dict[str, Any]] = []
    for sentence in _texts(card.get("approval_requirements")):
        gated.append({"effect": _effect_of(sentence), "act": sentence})
    if gated:
        note("/authority/gated", "extracted", ".agentlas/routing-card.json")

    # `anti_triggers` is deliberately NOT carried over. Measured across the live
    # corpus, 29-37% of those sentences are neighbour routing ("that is X's job")
    # rather than refusal, and tokenising them is what moved a correct agent from
    # rank 2 to rank 24. A real refusal needs a stated reason, which no current
    # generation records, so this comes back absent until the builder emits it.
    note("/authority/refuses", "absent", None,
         "anti_triggers are not refusals: 29-37% are neighbour routing, and they carry no reason")

    performs = sorted({item["effect"] for item in gated} |
                      {item.get("effect", "other") for item in deliverables}) or []
    authority: dict[str, Any] = {"performs": [e for e in performs if e != "other"]}
    if gated:
        authority["gated"] = gated
    note("/authority/performs", "extracted", None, "union of deliverable effects and gated acts")

    # --- host ----------------------------------------------------------------
    host: list[dict[str, Any]] = []
    requirements = policy.get("requirements")
    if isinstance(requirements, list):
        for item in requirements:
            if not isinstance(item, Mapping):
                continue
            capability = item.get("capability")
            if not isinstance(capability, str) or not capability.strip():
                continue
            row: dict[str, Any] = {
                "capability": capability.strip(),
                "withoutIt": str(item.get("fallback") or "").strip()
                             or "not stated by the package",
            }
            preferred = item.get("preferred")
            if isinstance(preferred, str) and preferred.strip():
                row["preferred"] = preferred.strip()
            host.append(row)
    if not host:
        # "No external capability required" is an ANSWER, not a gap. Omitting the
        # key made the brief say nothing about what the machine must be able to
        # do, and a host reading it could not tell "needs nothing" apart from
        # "never stated" - which is exactly what the review refuses. A package
        # that declares no MCP requirement has told us it runs on the model
        # alone; say so rather than leaving the field out.
        host = [{
            "capability": "none",
            "withoutIt": "runs anywhere; this package declares no external tool or "
                         "MCP server requirement",
        }]
        note("/host", "derived", ".agentlas/mcp-policy.json",
             "no MCP requirement declared, so the requirement is explicitly none")
    else:
        note("/host", "extracted", ".agentlas/mcp-policy.json")

    brief: dict[str, Any] = {
        "schemaVersion": BRIEF_VERSION,
        "side": "offer",
        "ref": str(card.get("id") or manifest.get("name") or root.name),
        "locale": [str(item) for item in locale],
        "statement": statement or root.name,
        "provenance": provenance,
    }
    if deliverables:
        brief["deliverables"] = deliverables
    if obligations:
        brief["obligations"] = obligations
    if authority.get("performs") or authority.get("gated"):
        brief["authority"] = authority
    if host:
        brief["host"] = host
    return brief
