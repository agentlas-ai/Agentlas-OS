"""Vendored pure-Python fallback for schema validation.

Why this exists (audit F7, closed here): `jsonschema` 4.18+ hard-depends on
`rpds`, a compiled module. That made schema validation unavailable exactly
where it matters most — a fresh Mac has no jsonschema at all, and a machine
with a wrong-architecture user-site copy (measured on the dev Mac itself:
x86_64 `rpds.so` under an arm64 interpreter) crashes on import. Local
`contract verify` degraded honestly, but workforce execution-receipt
verification was entirely unavailable on such machines.

The vendor set is jsonschema 4.17.3 — the last release before the compiled
dependency — plus its two pure-Python dependencies (attrs, pyrsistent; the
optional pyrsistent C accelerator is simply absent, its pure fallback is
automatic). Licenses ship in `licenses/`.

`load_jsonschema()` prefers a working installed jsonschema and falls back to
this copy only when the real import fails for any reason, so a machine with a
healthy system package keeps using it.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

_VENDOR_ROOT = str(Path(__file__).resolve().parent)


def load_jsonschema():
    """Return the jsonschema module, vendored if the installed one is broken."""

    try:
        return importlib.import_module("jsonschema")
    except Exception:
        # ImportError for an absent package, but also the measured
        # wrong-architecture dlopen failure, which surfaces as ImportError from
        # a transitive dependency. Any failure to import the real one means the
        # vendored pure-Python copy is the working option.
        pass
    if _VENDOR_ROOT not in sys.path:
        sys.path.insert(0, _VENDOR_ROOT)
    for name in [m for m in list(sys.modules) if m == "jsonschema" or m.startswith("jsonschema.")]:
        del sys.modules[name]
    return importlib.import_module("jsonschema")
