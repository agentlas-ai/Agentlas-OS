"""Launch a verified host session with process-local standalone identity.

No host configuration or authentication is written. POSIX uses exec; Windows
waits for its native executable child and propagates the child exit status.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys


def _windows_run(vector, environment, *, popen=None):
    # Windows CRT exec exits the launcher before the child finishes. Popen
    # quotes argv for CreateProcess and keeps the terminal and exit status.
    import shutil
    import subprocess
    from .host_core import Conflict
    executable=shutil.which(vector[0],path=environment.get('PATH'))
    if not executable:
        raise Conflict('windows_native_host_executable_missing')
    if not executable.lower().endswith('.exe'):
        raise Conflict('windows_native_host_executable_required')
    process=(popen or subprocess.Popen)([executable,*vector[1:]],env=environment,shell=False)
    def stop():
        if process.poll() is not None:return
        process.terminate()
        try:process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    try:
        return process.wait()
    except KeyboardInterrupt:
        stop()
        return 130
    except BaseException:
        stop()
        raise


# Engine locator variables this launcher (and bin/hephaestus) set for its own
# process. The host session must not inherit them: every child of the host CLI
# (another installed Agentlas plugin, a hook, a shell command) would read them,
# and a legacy engine then treats the standalone namespace as its own runtime
# base and auto-updates over it. The standalone plugin pins its runtime in its
# own MCP and command payloads instead.
_ENGINE_LOCATOR_KEYS = frozenset({
    'AGENTLAS_HOST_RUNTIME', 'HEPHAESTUS_RUNTIME_BASE', 'HEPHAESTUS_RUNTIME_ROOT', 'AGENTLAS_ONE_RUNTIME_BIN',
})


def _host_environment(source, root: Path) -> dict:
    environment = {key: value for key, value in source.items() if key.upper() not in _ENGINE_LOCATOR_KEYS}
    python_path = environment.get('PYTHONPATH')
    if python_path:
        owned = {os.path.normcase(os.path.realpath(str(root)))}
        kept = [entry for entry in python_path.split(os.pathsep)
                if entry and os.path.normcase(os.path.realpath(entry)) not in owned]
        if kept:
            environment['PYTHONPATH'] = os.pathsep.join(kept)
        else:
            environment.pop('PYTHONPATH', None)
    return environment


def launch(root: Path, home: Path, host: str, arguments=(), *, execute=None):
    from .host_core import Conflict, _identity, _namespace, session_plan

    root, home, _ = _identity(root, home, host, 'core')
    plan = session_plan(root, home, host, prepare=False)
    command = plan.get('hostCommand')
    if not isinstance(command, list) or not command or command[0] != host:
        raise Conflict(plan.get('reason', 'session_command_unavailable'))
    _namespace(home)  # refuses an unowned or unsafe standalone namespace
    environment = _host_environment(os.environ, root)
    # Argument vectors preserve spaces, Unicode and Windows paths. Never use a
    # shell, change the caller's environment, or copy authentication material.
    vector = [*command, *arguments]
    if os.name=='nt' and execute is None:
        return _windows_run(vector,environment)
    return (execute or os.execvpe)(vector[0], vector, environment)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Launch a standalone Agentlas host session')
    parser.add_argument('--host', choices=('claude', 'codex'), required=True)
    parser.add_argument('arguments', nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    arguments = args.arguments[1:] if args.arguments[:1] == ['--'] else args.arguments
    from .host_core import Conflict
    try:
        result=launch(Path(__file__).resolve().parent.parent, Path.home(), args.host, arguments)
        return result if isinstance(result,int) else 0
    except (Conflict, OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({'status': 'partial', 'reason': str(exc) if isinstance(exc, Conflict) else type(exc).__name__}), file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
