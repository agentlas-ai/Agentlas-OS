"""A memory tool's caller does not choose a project or the whole owner's range that the host did not give it.

``memory.search|timeline|get|crosscheck`` took ``projectDir`` (any folder: its project store is opened) and ``scope=owner_all`` (every project on the machine) as free arguments, so
an agent working in project A, or a borrowed Hub agent, could read project B's memory. When the HOST names the caller's own project (the environment variable
``AGENTLAS_MEMORY_PROJECT_REF``, which the app sets per turn), the arguments are narrowed to it:

  * ``projectDir`` that is not that project is dropped (the read falls back to the host's own project);
  * ``scope=owner_all`` is kept only when the host says this is the personal agent's own conversation (``AGENTLAS_MEMORY_PERSONAL_READ=1``); otherwise it reads as ``default``.

No host ref (a window outside the app, an older app that does not set it): nothing is narrowed, exactly as before. Pure on its inputs; never raises; writes nothing.
"""

from __future__ import annotations

import os
from typing import Any

PROJECT_REF_ENV = "AGENTLAS_MEMORY_PROJECT_REF"


def narrow(arguments: dict[str, Any]) -> dict[str, Any]:
    ref = (os.environ.get(PROJECT_REF_ENV) or "").strip()
    if not ref or not isinstance(arguments, dict):
        return arguments
    narrowed = dict(arguments)
    try:
        project_dir = narrowed.get("projectDir")
        if isinstance(project_dir, str) and project_dir.strip():
            from .project_identity import project_key

            if project_key(project_dir) != ref:
                narrowed.pop("projectDir", None)
        if narrowed.get("scope") == "owner_all":
            from . import memory_classify

            if not memory_classify.personal_flag():
                narrowed["scope"] = "default"
    except Exception:  # noqa: BLE001 - cannot tell: the narrow side
        narrowed.pop("projectDir", None)
        if narrowed.get("scope") == "owner_all":
            narrowed["scope"] = "default"
    return narrowed
