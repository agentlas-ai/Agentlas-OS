from __future__ import annotations

import dataclasses
import fnmatch
import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SECRET_PATTERNS = [
    re.compile(r"sk-(?:ant-)?[A-Za-z0-9_-]{20,}"),
    re.compile(r"gh[opsu]_[A-Za-z0-9_]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"AIza[0-9A-Za-z_-]{35}"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\b(?:api[_-]?key|secret|password|token)\s*[:=]\s*[\"']?([A-Za-z0-9+/=_-]{20,})[\"']?", re.I),
]
PROMPT_INJECTION = re.compile(r"(ignore (?:all |previous |prior )?instructions|reveal (?:your )?system prompt|print hidden instructions)", re.I)
DESTRUCTIVE = re.compile(r"(rm\s+-rf\s+(?:/|~)|curl\b[^\n]{0,240}\|\s*(?:sudo\s+)?(?:sh|bash|zsh)|mkfs\.|dd\s+if=/dev/)", re.I)
EXFIL = re.compile(r"(curl|wget|fetch|requests\.(?:post|put))[^\n]{0,240}(\.env|token|secret|password|credentials|cookie|keychain)", re.I)
UNICODE_OBFUSCATION = re.compile(r"[\u200b\u200c\u200d\ufeff\u202a-\u202e\u2066-\u2069]")
TEXT_FILE_ALLOW = {".md", ".txt", ".json", ".jsonl", ".yaml", ".yml", ".toml", ".py", ".js", ".ts", ".tsx", ".cjs", ".mjs", ".sh"}

# 2-stage security scan (plan \u00a76.2: static rules + user-LLM judgment, BYOK only).
# The server never calls an LLM; the user's own session writes this judgment file.
LLM_JUDGMENT_RELATIVE_PATH = ".agentlas/security-llm-judgment.json"
LLM_JUDGMENT_SCHEMA_VERSION = "1.0"
LLM_JUDGMENT_FINDING_TYPES = {
    "prompt-injection",
    "tool-poisoning",
    "secret-exfiltration",
    "destructive-command",
    "excessive-permission",
    "other",
}
LLM_JUDGMENT_MESSAGE_MAX_CHARS = 500
VERDICT_RANK = {"PASS": 0, "WARN": 1, "BLOCK": 2}


@dataclass
class AgentlasManifest:
    schemaVersion: str
    name: str
    packageHash: str
    runtimeBundleVersion: str
    entry: str
    skills: list[str]
    toolPermissions: dict[str, str]
    memoryPolicy: dict[str, str]
    memory: list[str]
    allowRead: list[str]
    denyRead: list[str]
    publicExportPolicy: str
    requiredRuntime: list[str]
    license: str
    createdBy: str

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PackageFile:
    path: str
    content: str


@dataclass
class SecurityFinding:
    verdict: str
    type: str
    path: str
    message: str
    line: int | None = None
    redacted: bool = True
    source: str = "static"


@dataclass
class SecurityReport:
    verdict: str
    scannedAt: str
    findings: list[SecurityFinding] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["findings"] = [asdict(finding) for finding in self.findings]
        return payload


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def redact(text: str) -> str:
    redacted = text
    for pattern in SECRET_PATTERNS:
      redacted = pattern.sub("[REDACTED_SECRET]", redacted)
    return redacted


def collect_package_files(root: str | Path) -> list[PackageFile]:
    base = Path(root).expanduser().resolve()
    files: list[PackageFile] = []
    for path in sorted(base.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(base).as_posix()
        if rel.startswith(".git/") or "/node_modules/" in f"/{rel}/" or rel.startswith("node_modules/"):
            continue
        if path.suffix and path.suffix not in TEXT_FILE_ALLOW:
            continue
        try:
            files.append(PackageFile(path=rel, content=path.read_text(encoding="utf-8")))
        except UnicodeDecodeError:
            continue
    return files


def package_hash(files: list[PackageFile]) -> str:
    digest = hashlib.sha256()
    for item in sorted(files, key=lambda file: file.path):
        if item.path == "agentlas.json":
            continue
        digest.update(item.path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(item.content.encode("utf-8", errors="replace"))
        digest.update(b"\0")
    return f"sha256:{digest.hexdigest()}"


def infer_entry(files: list[PackageFile]) -> str:
    candidates = ["AGENTS.md", "agent.md", "CLAUDE.md", "README.md"]
    paths = {file.path for file in files}
    for candidate in candidates:
        if candidate in paths:
            return candidate
    return files[0].path if files else "AGENTS.md"


def infer_skills(files: list[PackageFile]) -> list[str]:
    skills: list[str] = []
    for file in files:
        match = re.search(r"(?:^|/)skills/([^/]+)/SKILL\.md$", file.path)
        if match:
            skills.append(match.group(1))
    return sorted(set(skills)) or ["agentlas-package"]


def build_manifest(files: list[PackageFile], name: str) -> AgentlasManifest:
    return AgentlasManifest(
        schemaVersion="1.0",
        name=name,
        packageHash=package_hash(files),
        runtimeBundleVersion="1.0",
        entry=infer_entry(files),
        skills=infer_skills(files),
        toolPermissions={"network": "ask", "shell": "deny", "fileRead": "manifest-allowlist"},
        memoryPolicy={"writeBack": "ask", "publicCopy": "reset"},
        memory=[file.path for file in files if file.path in {".agentlas/memory-map.json", ".agentlas/agent-card.json"}],
        allowRead=["README.md", "AGENTS.md", "agent.md", "skills/**", ".agentlas/*.json"],
        denyRead=[".env", ".env.*", "**/secrets/**", "**/credentials/**", "**/cookies/**", "**/*token*", "**/*secret*"],
        publicExportPolicy="clean-copy",
        requiredRuntime=["mcp-client"],
        license="call-only-default",
        createdBy="hephaestus-setup-wizard",
    )


def scan_files(files: list[PackageFile]) -> SecurityReport:
    findings: list[SecurityFinding] = []
    for file in files:
        if any(matches(file.path, pattern) for pattern in [".env", ".env.*", "**/secrets/**", "**/credentials/**", "**/cookies/**", "**/*token*", "**/*secret*"]):
            findings.append(SecurityFinding("BLOCK", "credential-path", file.path, "Credential-like file path is excluded from Cloud package and public publish."))
        for number, line in enumerate(file.content.splitlines(), start=1):
            if any(pattern.search(line) for pattern in SECRET_PATTERNS):
                findings.append(SecurityFinding("BLOCK", "secret-like-value", file.path, "Secret-like value detected and redacted.", number))
            if PROMPT_INJECTION.search(line):
                findings.append(SecurityFinding("WARN", "prompt-injection", file.path, "Prompt-injection style instruction needs review.", number))
            if DESTRUCTIVE.search(line):
                findings.append(SecurityFinding("WARN", "destructive-command", file.path, "Destructive or remote shell command needs review before execution.", number))
            if EXFIL.search(line):
                findings.append(SecurityFinding("BLOCK", "external-exfiltration", file.path, "Potential credential exfiltration pattern blocked.", number))
            if UNICODE_OBFUSCATION.search(line):
                findings.append(SecurityFinding("WARN", "unicode-obfuscation", file.path, "Unicode bidi or zero-width control character detected.", number))
    verdict = "BLOCK" if any(f.verdict == "BLOCK" for f in findings) else "WARN" if findings else "PASS"
    return SecurityReport(verdict=verdict, scannedAt=now_iso(), findings=findings)


def combine_verdicts(*verdicts: str) -> str:
    return max(verdicts, key=lambda verdict: VERDICT_RANK.get(verdict, 0), default="PASS")


def merge_llm_judgment(report_dict: dict[str, Any], judgment_dict: dict[str, Any]) -> dict[str, Any]:
    """Merge a BYOK LLM judgment file (stage 2) into a static scan report (stage 1).

    Raises ValueError when the judgment payload does not match the
    `.agentlas/security-llm-judgment.json` contract. Never prints secret values:
    judgment messages are kept as-is but truncated to 500 chars.
    """
    if not isinstance(judgment_dict, dict):
        raise ValueError("LLM judgment must be a JSON object.")
    judgment_verdict = judgment_dict.get("verdict")
    if judgment_verdict not in VERDICT_RANK:
        raise ValueError("LLM judgment verdict must be PASS, WARN, or BLOCK.")
    raw_findings = judgment_dict.get("findings", [])
    if not isinstance(raw_findings, list):
        raise ValueError("LLM judgment findings must be a list.")

    merged = dict(report_dict)
    findings = [dict(finding) for finding in merged.get("findings", [])]
    for finding in findings:
        finding.setdefault("source", "static")
    stage_verdict = judgment_verdict
    for raw in raw_findings:
        if not isinstance(raw, dict):
            raise ValueError("Each LLM judgment finding must be a JSON object.")
        finding_verdict = raw.get("verdict") if raw.get("verdict") in {"WARN", "BLOCK"} else judgment_verdict
        finding_type = raw.get("type") if raw.get("type") in LLM_JUDGMENT_FINDING_TYPES else "other"
        message = str(raw.get("message", ""))[:LLM_JUDGMENT_MESSAGE_MAX_CHARS]
        findings.append(
            {
                "verdict": finding_verdict,
                "type": finding_type,
                "path": str(raw.get("path", "")),
                "message": message,
                "line": raw.get("line") if isinstance(raw.get("line"), int) else None,
                "redacted": bool(raw.get("redacted", True)),
                "source": "llm-judgment",
            }
        )
        stage_verdict = combine_verdicts(stage_verdict, finding_verdict)

    merged["findings"] = findings
    merged["verdict"] = combine_verdicts(merged.get("verdict", "PASS"), stage_verdict)
    merged["stages"] = ["static", "llm-judgment"]
    merged["llmJudgment"] = {
        "schemaVersion": str(judgment_dict.get("schemaVersion", LLM_JUDGMENT_SCHEMA_VERSION)),
        "judgedAt": str(judgment_dict.get("judgedAt", "")),
        "model": str(judgment_dict.get("model", "")) or None,
        "verdict": stage_verdict,
    }
    return merged


def scan_agent_folder(root: str | Path, llm_judgment_path: str | Path | None = None) -> dict[str, Any]:
    base = Path(root).expanduser().resolve()
    report = scan_files(collect_package_files(base)).to_json()
    report["stages"] = ["static"]
    judgment_file = Path(llm_judgment_path).expanduser() if llm_judgment_path else base / LLM_JUDGMENT_RELATIVE_PATH
    if judgment_file.exists():
        try:
            judgment = json.loads(judgment_file.read_text(encoding="utf-8"))
            report = merge_llm_judgment(report, judgment)
        except (OSError, ValueError, UnicodeDecodeError):
            report["llmJudgment"] = "invalid — ignored"
    elif llm_judgment_path is not None:
        report["llmJudgment"] = "invalid — ignored"
    return report


def run_setup_wizard(root: str | Path, name: str | None = None, write: bool = True) -> dict[str, Any]:
    base = Path(root).expanduser().resolve()
    files = collect_package_files(base)
    manifest = build_manifest(files, name or base.name)
    scan = scan_files(files)
    state = "Ready for MCP call" if scan.verdict != "BLOCK" else "Blocked"
    manifest_payload = manifest.to_json()
    existing_manifest = _read_existing_manifest(base)
    if existing_manifest:
        # Preserve uploader-authored display metadata such as publicProfile while
        # refreshing the runtime contract fields that Hephaestus owns.
        manifest_payload = {**existing_manifest, **manifest_payload}
    if write:
        (base / "agentlas.json").write_text(json.dumps(manifest_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        agentlas_dir = base / ".agentlas"
        agentlas_dir.mkdir(exist_ok=True)
        (agentlas_dir / "security-scan.json").write_text(json.dumps(scan.to_json(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "status": state,
        "manifest": manifest_payload,
        "scanReport": scan.to_json(),
        "stateTransitionLog": ["Started setup wizard", "Generated agentlas.json", f"Security scan: {scan.verdict}", state],
        "blockers": [] if state == "Ready for MCP call" else ["Security scan blocked package upload."],
    }


def _read_existing_manifest(base: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads((base / "agentlas.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError, OSError):
        return None
    return payload if isinstance(payload, dict) else None


def load_manifest(root: str | Path) -> AgentlasManifest:
    payload = json.loads((Path(root) / "agentlas.json").read_text(encoding="utf-8"))
    allowed = {field.name for field in dataclasses.fields(AgentlasManifest)}
    filtered = {key: value for key, value in payload.items() if key in allowed}
    return AgentlasManifest(**filtered)


def compile_runtime_bundle(root: str | Path) -> dict[str, Any]:
    base = Path(root).expanduser().resolve()
    manifest = load_manifest(base)
    files = collect_package_files(base)
    by_path = {file.path: file for file in files}
    entry = by_path.get(manifest.entry) or by_path.get("AGENTS.md")
    if not entry:
        raise FileNotFoundError(f"Entry file not found: {manifest.entry}")
    scan = scan_files(files)
    return {
        "schemaVersion": "1.0",
        "agent": manifest.name,
        "packageHash": manifest.packageHash,
        "entry": {"path": entry.path, "content": redact(entry.content)[:8000]},
        "skills": manifest.skills,
        "toolPermissions": manifest.toolPermissions,
        "memoryPolicy": manifest.memoryPolicy,
        "memorySummary": [summarize_memory(by_path[path]) for path in manifest.memory if path in by_path],
        "securityWarnings": [f"{item.verdict}:{item.type}:{item.path}" for item in scan.findings],
        "lazyRead": {"tool": "agentlas.read_agent_file", "allowedPatterns": manifest.allowRead, "deniedPatterns": manifest.denyRead},
    }


def read_agent_file(root: str | Path, requested_path: str) -> dict[str, Any]:
    base = Path(root).expanduser().resolve()
    manifest = load_manifest(base)
    if any(matches(requested_path, pattern) for pattern in manifest.denyRead):
        return {"status": "denied", "path": requested_path, "reason": "Denied by agentlas.json denyRead.", "redacted": True}
    if not any(matches(requested_path, pattern) for pattern in manifest.allowRead):
        return {"status": "denied", "path": requested_path, "reason": "Path is not in agentlas.json allowRead.", "redacted": False}
    path = base / requested_path
    if not path.exists():
        return {"status": "missing", "path": requested_path, "reason": "File not found."}
    raw = path.read_text(encoding="utf-8")
    text = redact(raw)
    return {"status": "allowed", "path": requested_path, "content": text, "redacted": text != raw}


class AgentlasMockStore:
    def __init__(self) -> None:
        self.records: dict[str, dict[str, Any]] = {}
        self.invocation_ledger: list[dict[str, Any]] = []

    def upload_private(self, record: dict[str, Any]) -> dict[str, Any]:
        next_record = {**record, "visibility": "private", "sourceDownloadPolicy": "owner-only"}
        self.records[next_record["agentId"]] = next_record
        return next_record

    def download(self, user_id: str, agent_id: str) -> dict[str, Any]:
        record = self.records.get(agent_id)
        if not record:
            return {"status": "missing"}
        if record["ownerId"] != user_id and record.get("sourceDownloadPolicy") != "allowed":
            return {"status": "denied"}
        return {"status": "allowed", "record": record}

    def publish_clean_copy(self, owner_id: str, agent_id: str, public_agent_id: str) -> dict[str, Any]:
        source = self.records[agent_id]
        if source["ownerId"] != owner_id:
            raise PermissionError("Only owners can publish clean copies.")
        clean_files = [
            {"path": file["path"], "content": re.sub(r"/Users/[^/\s]+/[^\s\"']+", "[REDACTED_LOCAL_PATH]", file["content"])}
            for file in source["files"]
            if not re.search(r"memory|credential|secret|token|\.env|local path", file["path"], re.I)
        ]
        clean = {
            **source,
            "agentId": public_agent_id,
            "visibility": "public",
            "memory": {"scope": "public", "summary": "Public clean copy starts empty.", "deltas": []},
            "sourceDownloadPolicy": "owner-only",
            "files": clean_files,
        }
        self.records[public_agent_id] = clean
        return clean

    def call_agent(self, caller_id: str, agent_id: str) -> dict[str, Any]:
        record = self.records.get(agent_id)
        if not record:
            return {"status": "DENIED", "output": "Agent not found."}
        is_owner = caller_id == record["ownerId"]
        can_call = is_owner or record["visibility"] == "public"
        status = "PASS" if can_call else "DENIED"
        self.invocation_ledger.append(
            {
                "agentId": agent_id,
                "callerId": caller_id,
                "creatorId": record["creatorId"],
                "version": record["version"],
                "calledAt": now_iso(),
                "status": status,
                "mode": "owner-private" if is_owner else "public-call-only",
            }
        )
        return {"status": status, "output": f"Called {record['manifest']['name']} via MCP context bundle." if can_call else "Call denied."}


def summarize_memory(file: PackageFile) -> str:
    compact = re.sub(r"\s+", " ", re.sub(r"[{}\[\]\",]", " ", file.content)).strip()
    return f"{file.path}: {redact(compact)[:480]}"


def matches(path: str, pattern: str) -> bool:
    return fnmatch.fnmatch(path, pattern)
