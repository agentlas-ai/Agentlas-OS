from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .auth import ensure_access_token, normalize_base_url
from .networking.card_lint import lint_card
from .runtime import collect_package_files, package_hash, run_setup_wizard

MAX_TOTAL_BYTES = 3 * 1024 * 1024
MAX_FILE_BYTES = 512 * 1024
MAX_FILES = 400
TEXT_EXTENSIONS = {".md", ".txt", ".json", ".jsonl", ".yaml", ".yml", ".toml", ".py", ".js", ".ts", ".tsx", ".cjs", ".mjs", ".sh"}
AGENT_DEFINITION_FILES = {"AGENT.md", "AGENTS.md", "CLAUDE.md", "GEMINI.md", "README.md", "agent.md", "manifest.md", "system-prompt.md"}
SKIP_DIRS = {".git", ".next", "node_modules", "dist", "out", "release", "__pycache__"}
BLOCKED_FILE_PATTERNS = [
    re.compile(r"^\.env(?:\..*)?$", re.I),
    re.compile(r"^id_rsa(?:\.pub)?$", re.I),
    re.compile(r"^credentials(?:\..*)?$", re.I),
    re.compile(r"^secrets?(?:\..*)?$", re.I),
    re.compile(r"(?:^|[._-])service-account(?:[._-]|$)", re.I),
    re.compile(r"\.(?:key|pem|p12|pfx|mobileprovision)$", re.I),
]
SECRET_PATTERNS = [
    ("private-key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----", re.I), "private key material"),
    ("openai-key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"), "OpenAI-style API key"),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{30,}\b"), "GitHub token"),
    ("slack-token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"), "Slack token"),
    ("aws-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "AWS access key"),
    ("generic-secret", re.compile(r"\b(?:api[_-]?key|secret|token|password)\s*[:=]\s*['\"][^'\"]{8,}['\"]", re.I), "hard-coded credential"),
]
CAPABILITY_RE = re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)+$")


class UploadError(RuntimeError):
    pass


@dataclass
class UploadFile:
    path: str
    bytes: int
    sha256: str
    contentBase64: str


def package_agent(
    folder: str | Path,
    *,
    slug: str | None = None,
    visibility: str = "marketplace",
    write_manifest: bool = True,
) -> dict[str, Any]:
    base = Path(folder).expanduser().resolve()
    if not base.is_dir():
        raise UploadError(f"agent folder not found: {folder}")

    routing_meta = refresh_routing_card_metadata(base)
    if write_manifest:
        run_setup_wizard(base, _read_package_name(base), write=True)

    files, file_count, findings = collect_upload_files(base)
    routing = validate_routing_card_for_upload(base)
    findings.extend(routing["findings"])
    findings.extend(validate_public_profile_for_upload(base, visibility))
    if not any(Path(item.path).name in AGENT_DEFINITION_FILES for item in files):
        findings.append(
            _finding(
                "missing-agent-definition",
                "blocker",
                "structure",
                "No root agent definition file was present in the package.",
                None,
                "Add AGENTS.md, CLAUDE.md, GEMINI.md, AGENT.md, or README.md.",
            )
        )

    package_hash_hex = hash_upload_files(files)
    manifest = {
        "version": "0.1",
        "kind": "agentlas-cloud-agent",
        "slug": _slugify(slug or _read_package_name(base) or base.name),
        "name": _read_package_name(base) or base.name,
        "tagline": _read_tagline(base),
        "agentKind": _infer_kind(base),
        "runtimeLabels": _runtime_labels(base),
        "visibility": "private-link" if visibility == "private-link" else "marketplace",
        "packageHash": package_hash_hex,
        "fileCount": file_count,
        "includedFileCount": len(files),
        "totalBytes": sum(item.bytes for item in files),
        "createdAt": _now_iso(),
        "billingMode": "static-only",
        "costOwner": "none",
    }
    if routing.get("card"):
        manifest["routingCard"] = routing["card"]

    review = static_review(findings)
    bundle = {
        "manifest": manifest,
        "files": [item.__dict__ for item in files],
        "source": {"packagedBy": "hephaestus-runtime", "packagedAt": manifest["createdAt"], "costOwner": "none"},
    }
    status = "blocked" if review["verdict"] == "fail" else "ready"
    return {
        "status": status,
        "folder": str(base),
        "manifest": manifest,
        "bundle": bundle,
        "review": review,
        "routing": routing,
        "routingMetadata": routing_meta,
        "summary": "Blocked by package review." if status == "blocked" else f"Ready: {manifest['slug']}.",
    }


def publish_agent(
    folder: str | Path,
    *,
    slug: str | None = None,
    visibility: str = "marketplace",
    base_url: str | None = None,
    dry_run: bool = False,
    interactive: bool = True,
) -> dict[str, Any]:
    packaged = package_agent(folder, slug=slug, visibility=visibility, write_manifest=True)
    if packaged["status"] == "blocked":
        packaged["registration"] = None
        return packaged
    if dry_run:
        packaged["status"] = "dry-run"
        packaged["registration"] = None
        packaged["summary"] = f"Dry run passed: {packaged['manifest']['slug']}."
        return packaged

    registration = register_package(
        packaged["manifest"],
        packaged["bundle"],
        packaged["review"],
        visibility=packaged["manifest"]["visibility"],
        base_url=base_url,
        interactive=interactive,
    )
    packaged["status"] = "registered"
    packaged["registration"] = registration
    packaged["summary"] = f"Registered {registration.get('slug') or packaged['manifest']['slug']}."
    return packaged


def register_package(
    manifest: dict[str, Any],
    bundle: dict[str, Any],
    review: dict[str, Any],
    *,
    visibility: str,
    base_url: str | None = None,
    interactive: bool = True,
) -> dict[str, Any]:
    base = normalize_base_url(base_url)
    token = ensure_access_token(base, interactive=interactive)
    if not token:
        raise UploadError("Agentlas sign-in is required. Run `bin/hephaestus auth login` first.")
    payload = {
        "manifest": manifest,
        "bundle": bundle,
        "review": review,
        "visibility": visibility,
        "billing": {"modelCallsPaidBy": review["costOwner"], "localRuntime": review.get("runtimeLabel")},
    }
    request = urllib.request.Request(
        f"{base}/api/cloud-agents/v1/register",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "hephaestus-upload",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:800]
        raise UploadError(f"Agentlas Cloud registration failed HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        raise UploadError(f"Agentlas Cloud registration failed: {exc}") from exc


def refresh_routing_card_metadata(base: Path) -> dict[str, Any]:
    card_path = base / ".agentlas" / "routing-card.json"
    if not card_path.is_file():
        return {"updated": False, "reason": "missing_routing_card"}
    try:
        card = json.loads(card_path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {"updated": False, "reason": "invalid_routing_card"}
    if not isinstance(card, dict):
        return {"updated": False, "reason": "invalid_routing_card"}

    before = json.dumps(card, sort_keys=True, ensure_ascii=False)
    agent_card_path = base / ".agentlas" / "agent-card.json"
    if isinstance(card.get("agent_card_ref"), dict) and agent_card_path.is_file():
        card["agent_card_ref"]["content_hash"] = _sha256_bytes(agent_card_path.read_bytes())
    source = card.get("source") if isinstance(card.get("source"), dict) else {}
    source["package_hash"] = package_hash(
        [
            item
            for item in collect_package_files(base)
            if item.path != "agentlas.json" and not item.path.endswith(".agentlas/routing-card.json")
        ]
    )
    source["ref"] = None
    manifest = _read_json(base / "manifest.json")
    if isinstance(manifest, dict) and manifest.get("version"):
        source["package_version"] = manifest["version"]
    card["source"] = source

    after = json.dumps(card, sort_keys=True, ensure_ascii=False)
    if after != before:
        card_path.write_text(json.dumps(card, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return {"updated": True, "path": str(card_path)}
    return {"updated": False, "path": str(card_path)}


def validate_routing_card_for_upload(base: Path) -> dict[str, Any]:
    card_path = base / ".agentlas" / "routing-card.json"
    if not card_path.is_file():
        return {
            "ok": False,
            "card": None,
            "findings": [
                _finding(
                    "routing-card-required",
                    "blocker",
                    "structure",
                    "Public upload requires .agentlas/routing-card.json.",
                    ".agentlas/routing-card.json",
                    "Run `bin/hephaestus cards migrate <agent-folder> --tier local`, then fill triggers, anti-triggers, and benchmark fixtures.",
                )
            ],
        }
    try:
        card = json.loads(card_path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {
            "ok": False,
            "card": None,
            "findings": [_finding("routing-card-invalid-json", "blocker", "structure", "Routing card is not valid JSON.", ".agentlas/routing-card.json", "Fix the JSON before upload.")],
        }
    if not isinstance(card, dict):
        return {
            "ok": False,
            "card": None,
            "findings": [_finding("routing-card-invalid", "blocker", "structure", "Routing card must be a JSON object.", ".agentlas/routing-card.json", "Replace it with routing-card/2.0 metadata.")],
        }

    findings: list[dict[str, Any]] = []
    server_problem = _server_routing_problem(card)
    if server_problem:
        findings.append(_finding("routing-card-server-invalid", "blocker", "structure", f"Routing card is invalid: {server_problem}", ".agentlas/routing-card.json", "Fix the routing card before upload."))
    # The package-local card must not persist absolute machine paths, but the
    # linter needs a package root to resolve relative benchmark_fixtures.
    lint_card_input = dict(card)
    source = card.get("source") if isinstance(card.get("source"), dict) else {}
    lint_card_input["source"] = {**source, "ref": str(base)}
    report = lint_card(lint_card_input)
    for error in report["errors"]:
        findings.append(_finding("routing-card-lint-error", "blocker", "structure", error, ".agentlas/routing-card.json", "Fix the routing card before upload."))
    if report["ready_blockers"]:
        findings.append(
            _finding(
                "routing-card-not-ready",
                "blocker",
                "structure",
                "Routing card is not routing_ready: " + "; ".join(report["ready_blockers"]),
                ".agentlas/routing-card.json",
                "Add concrete triggers, anti-triggers, verb_object capabilities, entrypoint, memory behavior, risk profile, and 10 benchmark cases.",
            )
        )
    if card.get("routing_status") not in {"routing_ready", "trusted"}:
        findings.append(
            _finding(
                "routing-card-status-not-ready",
                "blocker",
                "structure",
                f"routing_status must be routing_ready or trusted for upload (got {card.get('routing_status')}).",
                ".agentlas/routing-card.json",
                "Promote only after the quality gates pass.",
            )
        )
    return {"ok": not findings, "card": card, "findings": findings, "lint": report}


def validate_public_profile_for_upload(base: Path, visibility: str) -> list[dict[str, Any]]:
    if visibility != "marketplace":
        return []
    manifest = _read_json(base / "agentlas.json")
    public_profile = manifest.get("publicProfile") if isinstance(manifest, dict) and isinstance(manifest.get("publicProfile"), dict) else None
    if not public_profile:
        return [
            _finding(
                "public-profile-required",
                "blocker",
                "market-page",
                "Agentlas Hub upload requires agentlas.json publicProfile copy.",
                "agentlas.json",
                "Add a specific publicProfile with title, description, guide sections, member roster, and expected outputs.",
            )
        ]

    findings: list[dict[str, Any]] = []
    title = _first_text(public_profile, ("titleKo", "titleEn", "title"))
    description = _first_text(public_profile, ("descriptionKo", "descriptionEn", "description"))
    if not title or _looks_generic_copy(title):
        findings.append(_finding("public-profile-title", "blocker", "market-page", "publicProfile title is missing or generic.", "agentlas.json", "Use a concrete agent/team name, not boilerplate."))
    if len(description) < 40 or _looks_generic_copy(description):
        findings.append(_finding("public-profile-description", "blocker", "market-page", "publicProfile description is missing, too short, or generic.", "agentlas.json", "Explain what the package does, who it is for, and what it produces."))

    guide = public_profile.get("guide")
    if not isinstance(guide, dict):
        findings.append(_finding("public-profile-guide", "blocker", "market-page", "publicProfile guide is missing.", "agentlas.json", "Add guide sections for what-it-does, best-for, prerequisites, expected-outputs, and careful-with."))
        return findings
    section_keys = [
        ("what-it-does", "whatItDoes"),
        ("best-for", "bestFor"),
        ("prerequisites",),
        ("expected-outputs", "expectedOutputs"),
        ("careful-with", "carefulWith"),
    ]
    filled = 0
    for keys in section_keys:
        value = _first_text(guide, keys)
        if value and not _looks_generic_copy(value):
            filled += 1
    if filled < 4:
        findings.append(_finding("public-profile-guide-sections", "blocker", "market-page", "publicProfile guide lacks enough concrete sections.", "agentlas.json", "Fill at least four concrete guide sections for marketplace readers."))
    return findings


def collect_upload_files(base: Path) -> tuple[list[UploadFile], int, list[dict[str, Any]]]:
    files: list[UploadFile] = []
    findings: list[dict[str, Any]] = []
    total_bytes = 0
    file_count = 0
    for path in sorted(base.rglob("*")):
        rel = path.relative_to(base).as_posix()
        if any(part in SKIP_DIRS for part in path.relative_to(base).parts):
            continue
        if path.is_symlink():
            findings.append(_finding("symlink", "blocker", "policy", "Symbolic links are not allowed in cloud agent packages.", rel, "Replace the symlink with an ordinary file or remove it."))
            continue
        if not path.is_file():
            continue
        file_count += 1
        if file_count > MAX_FILES:
            findings.append(_finding("file-count-limit", "blocker", "size", f"Package has more than {MAX_FILES} files.", None, "Publish a focused agent/team folder."))
            continue
        stat = path.stat()
        total_bytes += stat.st_size
        if total_bytes > MAX_TOTAL_BYTES:
            findings.append(_finding("package-size-limit", "blocker", "size", f"Package exceeds {MAX_TOTAL_BYTES} bytes.", None, "Publish a smaller package."))
            continue
        if any(pattern.search(path.name) for pattern in BLOCKED_FILE_PATTERNS):
            findings.append(_finding("blocked-file", "blocker", "secret", "Secret-bearing file names are not allowed in cloud packages.", rel, "Remove credentials and publish only setup instructions or env key names."))
            continue
        if stat.st_size > MAX_FILE_BYTES:
            findings.append(_finding("large-file", "high", "size", f"File exceeds {MAX_FILE_BYTES} bytes.", rel, "Move large assets out of the package."))
            continue
        if not _is_text_package_file(path):
            continue
        raw = path.read_bytes()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
        for finding_id, pattern, label in SECRET_PATTERNS:
            if pattern.search(text):
                findings.append(_finding(finding_id, "blocker", "secret", f"Possible {label} found in package content.", rel, "Remove the value and require each user to configure their own key."))
        if re.search(r"(?:curl|wget)[^\n|&;]+[|]\s*(?:sh|bash)", text, re.I):
            findings.append(_finding("curl-pipe-shell", "high", "network", "Remote shell install pattern detected.", rel, "Use explicit, reviewable install steps."))
        digest = _sha256_bytes(raw)
        files.append(UploadFile(path=rel, bytes=len(raw), sha256=digest, contentBase64=base64.b64encode(raw).decode("ascii")))
    return files, file_count, findings


def hash_upload_files(files: list[UploadFile]) -> str:
    digest = hashlib.sha256()
    for item in sorted(files, key=lambda file: file.path):
        digest.update(item.path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(item.sha256.encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def static_review(findings: list[dict[str, Any]]) -> dict[str, Any]:
    blockers = sum(1 for finding in findings if finding["severity"] == "blocker")
    high = sum(1 for finding in findings if finding["severity"] == "high")
    return {
        "mode": "static-only",
        "verdict": "fail" if blockers else ("needs-review" if high else "pass"),
        "costOwner": "none",
        "summary": f"{blockers} blocker(s), {high} high-risk finding(s)." if blockers or high else "Static package review passed.",
        "findings": findings,
        "reviewedAt": _now_iso(),
    }


def _server_routing_problem(card: dict[str, Any]) -> str | None:
    if card.get("schemaVersion") != "routing-card/2.0":
        return "schemaVersion must be routing-card/2.0"
    if not isinstance(card.get("id"), str) or not str(card.get("id")).strip():
        return "id must be a non-empty string"
    if card.get("type") not in {"agent", "team", "plugin"}:
        return "type must be agent, team, or plugin"
    if not isinstance(card.get("name"), str) or not str(card.get("name")).strip():
        return "name must be a non-empty string"
    if not isinstance(card.get("summary"), str) or not str(card.get("summary")).strip():
        return "summary must be a non-empty string"
    capabilities = card.get("capabilities")
    if not isinstance(capabilities, list) or not capabilities:
        return "capabilities must be a non-empty array"
    for capability in capabilities:
        if not isinstance(capability, str) or not CAPABILITY_RE.match(capability):
            return f"capability {capability!r} must be snake_case with at least two words"
    if card.get("routing_status") not in {"draft", "searchable", "candidate", "routing_ready", "trusted"}:
        return "routing_status must be draft, searchable, candidate, routing_ready, or trusted"
    return None


def _finding(finding_id: str, severity: str, category: str, message: str, file: str | None, remediation: str | None = None) -> dict[str, Any]:
    payload = {"id": f"{finding_id}-{_sha256_text(file or message)[:10]}", "severity": severity, "category": category, "message": message}
    if file:
        payload["file"] = file
    if remediation:
        payload["remediation"] = remediation
    return payload


def _read_package_name(base: Path) -> str:
    card = _read_json(base / ".agentlas" / "routing-card.json")
    if isinstance(card, dict):
        for key in ("name", "name_ko"):
            value = str(card.get(key) or "").strip()
            if value:
                return value[:120]
    for name in ("agent.md", "AGENT.md", "README.md", "CLAUDE.md", "AGENTS.md"):
        text = _read_text(base / name, 2000)
        match = re.search(r"^#\s+(.+)$", text, re.M)
        if match:
            return re.sub(r"\s+", " ", match.group(1)).strip()[:120]
    return base.name


def _read_tagline(base: Path) -> str:
    manifest = _read_json(base / "agentlas.json")
    public_profile = manifest.get("publicProfile") if isinstance(manifest, dict) and isinstance(manifest.get("publicProfile"), dict) else {}
    for key in ("descriptionKo", "descriptionEn"):
        value = str(public_profile.get(key) or "").strip()
        if value:
            return value[:240]
    card = _read_json(base / ".agentlas" / "routing-card.json")
    if isinstance(card, dict):
        for key in ("summary_ko", "summary", "description"):
            value = str(card.get(key) or "").strip()
            if value:
                return value[:240]
    for name in ("README.md", "agent.md", "AGENT.md"):
        for line in _read_text(base / name, 3000).splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and not stripped.startswith(">"):
                return stripped[:240]
    return "Portable Agentlas cloud agent package."


def _infer_kind(base: Path) -> str:
    card = _read_json(base / ".agentlas" / "routing-card.json")
    if isinstance(card, dict) and card.get("type") in {"agent", "team", "plugin"}:
        return str(card["type"])
    for marker in ("TEAM.md", "team.json", "agents", "team", "departments", "hr-departments"):
        if (base / marker).exists():
            return "team"
    return "agent"


def _runtime_labels(base: Path) -> list[str]:
    labels: list[str] = []
    if (base / "CLAUDE.md").exists() or (base / ".claude").exists():
        labels.append("claude-code")
    if (base / "AGENTS.md").exists():
        labels.append("codex")
    if (base / "GEMINI.md").exists():
        labels.append("gemini")
    return labels or ["agents-md"]


def _is_text_package_file(path: Path) -> bool:
    return path.suffix.lower() in TEXT_EXTENSIONS or path.name in AGENT_DEFINITION_FILES


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError, OSError):
        return None
    return value if isinstance(value, dict) else None


def _read_text(path: Path, max_chars: int) -> str:
    try:
        return path.read_text(encoding="utf-8")[:max_chars]
    except (FileNotFoundError, UnicodeDecodeError, OSError):
        return ""


def _first_text(payload: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str):
            text = re.sub(r"\s+", " ", value).strip()
            if text:
                return text
        if isinstance(value, list):
            text = " ".join(str(item).strip() for item in value if str(item).strip())
            if text:
                return re.sub(r"\s+", " ", text).strip()
    return ""


def _looks_generic_copy(value: str) -> bool:
    text = value.strip().lower()
    if not text:
        return True
    generic_markers = [
        "todo",
        "tbd",
        "lorem ipsum",
        "agent description",
        "portable agentlas cloud agent",
        "describe this agent",
        "replace this",
        "sample agent",
        "generic agent",
    ]
    return any(marker in text for marker in generic_markers)


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")[:64] or "agentlas-cloud-agent"


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
