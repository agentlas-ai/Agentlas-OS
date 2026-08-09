#!/usr/bin/env bash
# Verify the no-block upload contract (owner rule 2026-08-08).
#
# Re-injects the defects that used to BLOCK an upload and fails unless every
# one now ships safely with a receipt instead:
#   1) a package planted with real-looking keys + a credential-named file
#      yields ZERO blocker findings
#   2) the credential-named file is withheld (never in the shipped set) with a
#      "redacted-file" receipt
#   3) no planted key value survives in any shipped byte
#   4) a design token ("token": "#FF5500") ships UNTOUCHED - the false-positive
#      class that 422-blocked live uploads must stay green
#   5) an invalid MCP policy (execution fields) is auto-repaired with a receipt
set -euo pipefail
cd "$(dirname "$0")/.."

python3 - <<'PY'
import sys, json, base64, shutil, tempfile, pathlib
sys.path.insert(0, ".")
from agentlas_cloud.upload import collect_upload_files, _repair_mcp_policy_file

base = pathlib.Path(tempfile.mkdtemp(prefix="upload-redaction-gate."))
try:
    (base / "README.md").write_text("Usage guide.\n")
    (base / "notes.md").write_text('config uses api_key = "abcd1234efgh5678"\nAlso AKIAABCDEFGHIJKLMNOP is the key\n')
    (base / "credentials.json").write_text('{"k":"v"}')
    (base / "design.json").write_text(json.dumps({"token": "#FF5500", "motion_token": "ease-out"}))

    files, count, findings = collect_upload_files(base)
    ids = [f["id"] for f in findings]
    has = lambda p: any(i.startswith(p) for i in ids)

    blockers = [f for f in findings if f["severity"] == "blocker"]
    assert not blockers, f"secret findings still block: {blockers}"
    shipped = {f.path for f in files}
    assert "credentials.json" not in shipped, "credential-named file shipped"
    assert has("redacted-file"), "withheld file has no receipt"
    for shipped_file in files:
        body = base64.b64decode(shipped_file.contentBase64).decode("utf-8", "replace")
        assert "abcd1234efgh5678" not in body and "AKIAABCDEFGHIJKLMNOP" not in body, f"key leaked via {shipped_file.path}"
    design = next(f for f in files if f.path == "design.json")
    assert "#FF5500" in base64.b64decode(design.contentBase64).decode(), "design token falsely masked"

    ag = base / ".agentlas"; ag.mkdir()
    (ag / "mcp-policy.json").write_text(json.dumps({
        "policy": "system-global-first", "resolution": "one-pass",
        "degradation": "per-requirement", "capabilities": {},
        "command": "/bin/sh", "headers": {"Authorization": "Bearer xyz"},
    }))
    receipts: list = []
    _repair_mcp_policy_file(base, receipts, write=True)
    repaired = json.load(open(ag / "mcp-policy.json"))
    assert "command" not in repaired and "headers" not in repaired, "forbidden fields survived"
    assert receipts and receipts[0]["id"].startswith("mcp-policy-auto-repaired"), receipts
    # Review verdict must reflect FINAL severities (computed after redaction/
    # deferral), not a frozen pre-redaction "N blocker(s)/fail" string.
    from agentlas_cloud.upload import package_agent
    (ag / "AGENTS.md").write_text("# Canary\n" + "Body line to be substantive.\n" * 8)
    result = package_agent(str(base), visibility="private-link")
    assert result["status"] == "ready", result["status"]
    review = result["review"]
    assert review["verdict"] in ("pass", "needs-review"), review["verdict"]
    assert not any(f["severity"] == "blocker" for f in review["findings"])
    assert review["summary"].startswith("0 blocker"), review["summary"]

    # 7-2 (owner 2026-08-09): 구조/마켓페이지 깨짐도 반려하지 않는다 — 결정론 리패키징
    # 후에도 남은 구조·마켓 blocker는 경고+engineGap으로 강등해 ready로 출하. 단 size 등
    # 안전/불가 항목은 계속 차단.
    from agentlas_cloud.upload import package_agent as _pa
    import tempfile as _tf, shutil as _sh, pathlib as _pl
    broken = _pl.Path(_tf.mkdtemp(prefix="broken-gate."))
    try:
        (broken / "AGENTS.md").write_text("# Broken\n" + "body line to be substantive.\n" * 10)
        rb = _pa(str(broken), visibility="marketplace")
        assert rb["status"] == "ready", f"broken pkg still blocked: {rb['status']}"
        assert not [f for f in rb["review"]["findings"] if f["severity"] == "blocker"], "structure blocker survived"
        assert any(f.get("engineGap") for f in rb["review"]["findings"]), "no engine-gap receipt"
    finally:
        _sh.rmtree(broken, ignore_errors=True)
    big = _pl.Path(_tf.mkdtemp(prefix="big-gate."))
    try:
        (big / "AGENTS.md").write_text("# Big\n" + "body\n" * 10)
        (big / "big.md").write_text("A" * (4 * 1024 * 1024))
        rg = _pa(str(big), visibility="marketplace")
        assert rg["status"] == "blocked" and any(f["category"] == "size" for f in rg["review"]["findings"] if f["severity"] == "blocker"), "size limit no longer blocks"
    finally:
        _sh.rmtree(big, ignore_errors=True)

    print("PASS verify-upload-redaction")
finally:
    shutil.rmtree(base, ignore_errors=True)
PY
