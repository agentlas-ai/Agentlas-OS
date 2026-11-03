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


def launch(root: Path, home: Path, host: str, arguments=(), *, execute=None):
    from .host_core import Conflict, _identity, _namespace, session_plan

    root, home, _ = _identity(root, home, host, 'core')
    plan = session_plan(root, home, host, prepare=False)
    command = plan.get('hostCommand')
    if not isinstance(command, list) or not command or command[0] != host:
        raise Conflict(plan.get('reason', 'session_command_unavailable'))
    namespace = _namespace(home)
    runtime_base = namespace if namespace == home / '.agentlas/os-runtime' else namespace.parent
    environment = dict(os.environ)
    environment.update({
        'AGENTLAS_HOST_RUNTIME': 'standalone',
        'HEPHAESTUS_RUNTIME_BASE': str(runtime_base),
        'HEPHAESTUS_RUNTIME_ROOT': str(root),
        'AGENTLAS_ONE_RUNTIME_BIN': str(root / 'bin/agentlas-one'),
        'PYTHONDONTWRITEBYTECODE': '1',
    })
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
