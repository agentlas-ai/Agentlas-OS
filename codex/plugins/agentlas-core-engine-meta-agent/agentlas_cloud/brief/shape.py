"""Compute a deliverable's shape from an output schema's topology.

Nothing here reads a name, a description, or any word the author chose. Names are
what failed: `capabilities` turned out to be `snake_case(agent.md ## Responsibilities)`
in 130 of 130 packages, and `trigger_examples` were 1186 unique strings across 1189
slots. A field derived from an author's vocabulary inherits that author's vocabulary,
so this one is derived from structure instead - the arity and the value space of the
schema, which the author cannot phrase differently.

The shapes answer one question: what does the requester end up holding?

  ledger       many uniform records, each carrying its own judgement
  verdict      one judgement about one thing, with its reasons
  dossier      several named sections of prose about one subject
  computation  numbers derived from numbers
  blueprint    a structure to be built or followed - steps, nodes, flows
  rendition    a produced file the schema only points at
  other        none of the above, and that is a legal answer

`other` is not a failure mode. Measured across the live corpus, 38% of output
schemas land there, so anything that treats `other` as a penalty would quietly
demote a third of the catalogue.
"""

from __future__ import annotations

from typing import Any, Mapping

__all__ = ["classify_shape", "find_row_verdict", "SHAPES"]

SHAPES = ("ledger", "verdict", "dossier", "computation", "blueprint", "rendition", "other")

# A judgement property is one whose value space is a small closed set. The name is
# irrelevant - `severity`, `status`, `verdict`, `grade` and `risk_tier` all qualify by
# having few allowed values, and a free-text field never does however it is named.
_MAX_VERDICT_VALUES = 12

_RENDITION_HINT_FORMATS = {"uri", "uri-reference", "binary", "byte"}
_NUMERIC = {"number", "integer"}


def _resolve(node: Any, root: Mapping[str, Any], seen: frozenset[str] = frozenset()) -> Mapping[str, Any]:
    """Follow a local $ref. Remote refs are left unresolved rather than fetched."""
    if not isinstance(node, Mapping):
        return {}
    ref = node.get("$ref")
    if not isinstance(ref, str) or not ref.startswith("#"):
        return node
    if ref in seen:
        return {}
    target: Any = root
    for part in ref.lstrip("#/").split("/"):
        if not part:
            continue
        part = part.replace("~1", "/").replace("~0", "~")
        if isinstance(target, Mapping):
            target = target.get(part)
        else:
            return {}
    return _resolve(target, root, seen | {ref}) if isinstance(target, Mapping) else {}


def _properties(node: Mapping[str, Any], root: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    resolved = _resolve(node, root)
    props = resolved.get("properties")
    out: dict[str, Mapping[str, Any]] = {}
    if isinstance(props, Mapping):
        for key, value in props.items():
            if isinstance(value, Mapping):
                out[str(key)] = _resolve(value, root)
    return out


def _type_of(node: Mapping[str, Any]) -> str | None:
    kind = node.get("type")
    if isinstance(kind, str):
        return kind
    if isinstance(kind, list):
        # A nullable field is still its non-null type for topology purposes.
        real = [item for item in kind if item != "null"]
        if len(real) == 1 and isinstance(real[0], str):
            return real[0]
    return None


# Reserved technical property names, not domain vocabulary. Excluding these is not
# the name-reading this module refuses to do: an author does not choose whether the
# version stamp is called schemaVersion, and treating `schemaVersion: {const: "…/1.0"}`
# as a judgement classified Web_master's design-read as a verdict about its own
# version number.
_METADATA_NAMES = frozenset({
    "schemaversion", "schema_version", "version", "$schema", "id", "$id",
    "generatedat", "generated_at", "createdat", "created_at", "updatedat", "updated_at",
})


def _is_verdict_property(name: str, node: Mapping[str, Any]) -> list[str] | None:
    """Return the closed value set if this property is a judgement, else None.

    A single fixed value is a constant, not a judgement: nothing is being decided
    when there is only one thing it can say.
    """
    if name.lower() in _METADATA_NAMES:
        return None
    values = node.get("enum")
    if isinstance(values, list) and 1 < len(values) <= _MAX_VERDICT_VALUES:
        return [str(item) for item in values]
    return None


def find_row_verdict(
    item: Mapping[str, Any], root: Mapping[str, Any], base_pointer: str
) -> tuple[str | None, list[str]]:
    """The per-record judgement inside a repeated item, as a JSON Pointer."""
    best: tuple[str, list[str]] | None = None
    for name, node in _properties(item, root).items():
        values = _is_verdict_property(name, node)
        if not values:
            continue
        # Prefer the smallest closed set: a 3-value status discriminates a record
        # far more than a 12-value taxonomy that mostly sorts.
        if best is None or len(values) < len(best[1]):
            best = (f"{base_pointer}/properties/{name}", values)
    return (best[0], best[1]) if best else (None, [])


def _array_item(node: Mapping[str, Any], root: Mapping[str, Any]) -> Mapping[str, Any] | None:
    resolved = _resolve(node, root)
    if _type_of(resolved) != "array":
        return None
    items = resolved.get("items")
    if isinstance(items, Mapping):
        item = _resolve(items, root)
        return item if _type_of(item) == "object" or "properties" in item else None
    return None


def classify_shape(schema: Mapping[str, Any]) -> tuple[str, str | None, list[str]]:
    """Return (shape, rowVerdictPointer, verdictValues) for one output schema.

    Only the schema is read. No filename, no title, no description.
    """
    if not isinstance(schema, Mapping):
        return ("other", None, [])
    root = schema
    top = _properties(schema, root)

    # A schema that is itself an array of records is the clearest ledger there is.
    direct = _array_item(schema, root)
    if direct is not None:
        pointer, values = find_row_verdict(direct, root, "#/items")
        return ("ledger", pointer, values) if pointer else ("ledger", None, [])

    # Otherwise look for the dominant repeated collection among the properties.
    collections: list[tuple[str, Mapping[str, Any]]] = []
    for name, node in top.items():
        item = _array_item(node, root)
        if item is not None:
            collections.append((name, item))

    for name, item in collections:
        pointer, values = find_row_verdict(item, root, f"#/properties/{name}/items")
        if pointer:
            # Many uniform records, each judged: a ledger, regardless of what the
            # surrounding object is called.
            return ("ledger", pointer, values)

    # One judgement about one subject.
    for name, node in top.items():
        values = _is_verdict_property(name, node)
        if values and len(values) <= 6:
            return ("verdict", f"#/properties/{name}", values)

    if collections:
        # Repeated records with no judgement: a structure to follow or build.
        return ("blueprint", None, [])

    if top:
        numeric = sum(1 for node in top.values() if _type_of(node) in _NUMERIC)
        if numeric and numeric >= max(1, len(top) // 2):
            return ("computation", None, [])

        pointers = 0
        for node in top.values():
            if _type_of(node) == "string" and str(node.get("format", "")) in _RENDITION_HINT_FORMATS:
                pointers += 1
        if pointers and pointers >= max(1, len(top) // 2):
            return ("rendition", None, [])

        prose = sum(
            1
            for name, node in top.items()
            if _type_of(node) == "string" and not _is_verdict_property(name, node) and "format" not in node
        )
        objects = sum(1 for node in top.values() if _type_of(node) == "object" or "properties" in node)
        if prose + objects >= max(2, (len(top) * 2) // 3):
            return ("dossier", None, [])

    return ("other", None, [])
