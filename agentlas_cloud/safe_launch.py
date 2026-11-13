"""Start engine code without the current directory on ``sys.path``.

``python -m module`` and ``python -c code`` put the current directory first, so
a folder named ``agentlas_cloud`` (or ``json.py``) in the project a hook runs in
would be loaded in place of the installed engine. This module builds the argument
vectors the engine's own detached workers use: the installed root is the only
engine location on the path.

The same bootstrap text is the value of ``AGENTLAS_SAFE_RUNPY`` in
``bin/agentlas-python-cache-boundary`` (and the one copy in ``bin/agentlas-one``,
``bin/hephaestus.cmd``); ``tests/test_safe_launch.py`` keeps them identical.
Plain ``-c`` text, no flags: it works on Python 3.9 to 3.14 and on Windows, and it
keeps every environment variable (``-I`` would drop ``PYTHONPATH`` and the
``PYTHONUTF8`` the hooks rely on).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Iterable

BOOTSTRAP = (
    "import os,sys;"
    "sys.path[:]=[p for p in sys.path if os.path.isabs(p) and not (os.path.exists(p) and os.path.exists(os.curdir) and os.path.samefile(p,os.curdir))];"
    "import runpy;"
    "r=sys.argv[1];"
    "sys.path.insert(0,r);"
    "sys.argv=sys.argv[2:];"
    "runpy.run_module(sys.argv[0],run_name='__main__',alter_sys=True)"
)


def runtime_root() -> Path:
    return Path(__file__).resolve().parent.parent


def module_command(module: str, args: Iterable[str] = (), *, root: Path | str | None = None,
                   python: str | None = None) -> list[str]:
    """``python -m module args`` that cannot load ``module`` (or the standard
    library) from the current directory: only ``root`` is placed on the path."""
    return [python or sys.executable, "-c", BOOTSTRAP, str(root or runtime_root()), module, *args]
