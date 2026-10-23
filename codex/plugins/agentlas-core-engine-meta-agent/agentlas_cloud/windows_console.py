"""Keep non-interactive child processes from opening console windows on Windows.

Agentlas Desktop starts the engine's background workers (the auto-updater,
memory and index jobs) without a console of their own. On Windows, a console
program started from a process that has no console gets a brand-new console,
and with Windows Terminal as the default terminal that console is a visible,
empty window. Measured 2026-10-24: three blank Windows Terminal windows on the
first launch, one per child of the update worker (two runtime healthchecks and
the memory-hook installer).

``CREATE_NO_WINDOW`` gives the child a console that has no window. Its own
children inherit that hidden console, so one flag at each spawn covers the
whole tree below it. ``DETACHED_PROCESS`` must not be combined with it:
Windows then ignores ``CREATE_NO_WINDOW`` and every console grandchild opens a
new window again. A new process group is not requested either; see
``cli._stormbreaker_background_process_options`` for why that was dropped.

Every ``subprocess`` call in the engine's runtime code passes
``**no_console_window()``. A child that needs the user's terminal (an
interactive login, say) must not use it; mark that call with
``# console: interactive`` so the source scan accepts it as a deliberate choice.
On macOS and Linux this returns no options, so those platforms are unchanged.
"""

from __future__ import annotations

import os
import subprocess

# The value is fixed by the Win32 API; the constant only exists in
# ``subprocess`` on Windows builds of Python.
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)


def no_console_window(platform_name: str | None = None) -> dict[str, int]:
    """Return the ``subprocess`` keyword options that hide a child's console.

    ``platform_name`` takes an ``os.name`` value and exists for tests; callers
    leave it out.
    """

    target = os.name if platform_name is None else platform_name
    if target != "nt":
        return {}
    return {"creationflags": CREATE_NO_WINDOW}
