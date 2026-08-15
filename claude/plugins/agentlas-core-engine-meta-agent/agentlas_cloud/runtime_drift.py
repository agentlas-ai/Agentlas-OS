"""Runtime drift detector — detect automatically, apply by hand (PRD 2026-08-15 OS-10).

Shipped in the runtime home so `agentlas-one` can run it on the user's machine
(once a day, from the session-end hook, fail-open) and surface the result where
the owner already looks: the status line and `agentlas-one status`. The GitHub
daily workflow runs the same code as a backstop.

Compares our pins in contracts/runtime-registry.json against:
  * the ACP registry (https://cdn.agentclientprotocol.com/registry/v1/latest/registry.json)
    -> pin.registryVersion != registry version   => DRIFT (version)
  * the ACP daily protocol matrix (.protocol-matrix/latest.json)
    -> initialize.status != success              => DRIFT (health)
    -> agentInfoVersion != registryVersion       => DRIFT (self-reported version disagrees)
  * an optional previous matrix snapshot
    -> capabilities/authMethods/protocolVersion changed => DRIFT (capability)

Exit 0 = no drift, 1 = drift found, 2 = usage/input error. It never edits the
registry: automatic application of upstream changes is exactly what the
supply-chain incidents (axios 5 min, trivy-action 56 min) punish. Cooldown and
merge stay human decisions.

Stdlib only. Network access only when --acp-registry / --matrix are URLs (or
omitted, in which case the defaults are fetched with a User-Agent).
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path
from typing import Any, Mapping, Optional

DEFAULT_ACP_REGISTRY = "https://cdn.agentclientprotocol.com/registry/v1/latest/registry.json"
DEFAULT_MATRIX = "https://raw.githubusercontent.com/agentclientprotocol/registry/main/.protocol-matrix/latest.json"
USER_AGENT = "agentlas-runtime-drift/1.0 (+https://agentlas.ai)"
CAPABILITY_KEYS = ("protocolVersion", "authMethods", "capabilities", "setModelSignal")


def _load(source: str, *, timeout: float) -> Any:
    if source.startswith("http://") or source.startswith("https://"):
        req = urllib.request.Request(source, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - fixed public URLs
            return json.load(resp)
    with open(source, encoding="utf-8") as fh:
        return json.load(fh)


def _by_id(items: Any) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    if isinstance(items, list):
        for item in items:
            if isinstance(item, Mapping) and item.get("id"):
                out[str(item["id"])] = dict(item)
    elif isinstance(items, Mapping):
        for key, item in items.items():
            if isinstance(item, Mapping):
                out[str(key)] = dict(item)
    return out


def check_drift(
    our_registry: Mapping[str, Any],
    acp_registry: Optional[Mapping[str, Any]],
    matrix: Optional[Mapping[str, Any]],
    previous_matrix: Optional[Mapping[str, Any]] = None,
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    acp_agents = _by_id(acp_registry.get("agents")) if isinstance(acp_registry, Mapping) else {}
    matrix_agents = _by_id(matrix.get("agents")) if isinstance(matrix, Mapping) else {}
    prev_agents = _by_id(previous_matrix.get("agents")) if isinstance(previous_matrix, Mapping) else {}

    for row in our_registry.get("runtimes", []):
        acp = row.get("acp") or {}
        rid = acp.get("registryId")
        if not rid:
            continue
        pin = (row.get("pin") or {}).get("registryVersion")
        live = acp_agents.get(rid)
        if acp_agents and live is None:
            findings.append({"runtime": row["id"], "kind": "missing", "detail": f"{rid} not in ACP registry"})
        elif live is not None and pin and str(live.get("version")) != str(pin):
            findings.append({
                "runtime": row["id"], "kind": "version",
                "detail": f"pin {pin} != registry {live.get('version')} ({rid})",
                "pinned": pin, "upstream": live.get("version"),
            })
        probe = matrix_agents.get(rid)
        if probe is not None:
            init = probe.get("initialize") if isinstance(probe.get("initialize"), Mapping) else {}
            status = str(init.get("status") or "unknown")
            if status != "success":
                findings.append({
                    "runtime": row["id"], "kind": "health",
                    "detail": f"{rid} initialize.status={status} ({init.get('message')})",
                })
            reg_v, info_v = probe.get("registryVersion"), probe.get("agentInfoVersion")
            if reg_v and info_v and str(reg_v) != str(info_v):
                findings.append({
                    "runtime": row["id"], "kind": "self-report",
                    "detail": f"{rid} registryVersion {reg_v} != agentInfoVersion {info_v}",
                })
            prev = prev_agents.get(rid)
            if prev is not None:
                for key in CAPABILITY_KEYS:
                    if json.dumps(prev.get(key), sort_keys=True) != json.dumps(probe.get(key), sort_keys=True):
                        findings.append({
                            "runtime": row["id"], "kind": "capability",
                            "detail": f"{rid} {key} changed: {prev.get(key)!r} -> {probe.get(key)!r}",
                        })
    return findings


def _now() -> str:
    import time
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _write_report(path: str, payload: dict) -> None:
    import os
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + f".tmp-{os.getpid()}")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, target)


def read_report(path: str) -> Optional[dict]:
    """Last written report or None (never raises)."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:  # noqa: BLE001
        return None


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    root = Path(__file__).resolve().parents[1]
    default_registry = root / "contracts" / "runtime-registry.json"
    parser.add_argument("--registry", default=str(default_registry), help="our runtime registry (file)")
    parser.add_argument("--acp-registry", default=DEFAULT_ACP_REGISTRY, help="ACP registry.json (file or URL); 'none' to skip")
    parser.add_argument("--matrix", default=DEFAULT_MATRIX, help="ACP protocol matrix latest.json (file or URL); 'none' to skip")
    parser.add_argument("--previous-matrix", default=None, help="previous matrix snapshot for capability diff (file or URL)")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--write", default=None, help="also write the JSON report to this path (atomic); used by agentlas-one")
    parser.add_argument("--quiet", action="store_true", help="no stdout (for background runs)")
    args = parser.parse_args(argv)

    try:
        ours = _load(args.registry, timeout=args.timeout)
        acp_reg = None if args.acp_registry == "none" else _load(args.acp_registry, timeout=args.timeout)
        matrix = None if args.matrix == "none" else _load(args.matrix, timeout=args.timeout)
        prev = _load(args.previous_matrix, timeout=args.timeout) if args.previous_matrix else None
    except Exception as exc:  # noqa: BLE001
        if args.write:
            _write_report(args.write, {"checkedAt": _now(), "status": "unavailable", "drift": False, "findings": [], "reason": str(exc)})
        if not args.quiet:
            sys.stderr.write(f"check-runtime-drift: cannot load inputs: {exc}\n")
        return 2

    findings = check_drift(ours, acp_reg, matrix, prev)
    if args.write:
        _write_report(args.write, {"checkedAt": _now(), "status": "ok", "drift": bool(findings), "findings": findings})
    if args.quiet:
        return 1 if findings else 0
    if args.json:
        print(json.dumps({"drift": bool(findings), "findings": findings}, ensure_ascii=False, indent=2))
    else:
        if not findings:
            print("check-runtime-drift: no drift against ACP registry/matrix")
        else:
            print(f"check-runtime-drift: {len(findings)} finding(s) — review, do not auto-apply (cooldown 7d)")
            for f in findings:
                print(f"  [{f['kind']}] {f['runtime']}: {f['detail']}")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
