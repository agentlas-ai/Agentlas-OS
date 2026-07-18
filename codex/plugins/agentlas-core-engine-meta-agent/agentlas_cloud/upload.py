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

from . import content_guard
from .auth import ensure_access_token, normalize_base_url
from .networking.card_lint import lint_card
from .runtime import (
    collect_package_files,
    is_local_experience_lineage_path,
    package_hash,
    run_setup_wizard,
    standalone_experience_asset_identity,
)

MAX_TOTAL_BYTES = 3 * 1024 * 1024
MAX_FILE_BYTES = 512 * 1024
MAX_FILES = 400
TEXT_EXTENSIONS = {".md", ".txt", ".json", ".jsonl", ".yaml", ".yml", ".toml", ".py", ".js", ".ts", ".tsx", ".cjs", ".mjs", ".sh"}
AGENT_DEFINITION_FILES = {"AGENT.md", "AGENTS.md", "CLAUDE.md", "GEMINI.md", "README.md", "agent.md", "manifest.md", "system-prompt.md"}
SKIP_DIRS = {".git", ".next", "node_modules", "dist", "out", "release", "__pycache__"}
CLOUD_PACKAGE_HASH_VERSION = "path-sha256-executable-v2"
# These files are local, mutable verification evidence. Agent Cloud performs
# its own server-side review and stores submitted review metadata separately;
# shipping these files would make an otherwise identical artifact change on
# every scan and would leak host-local timestamps/status into the package.
UPLOAD_DERIVED_EVIDENCE_PATHS = frozenset(
    {
        ".agentlas/security-scan.json",
        ".agentlas/security-llm-judgment.json",
        ".agentlas/field-test-report.json",
        # Separate local/user-owned Experience lineage must never be folded
        # into an AgentDefinition artifact or its delivered package hash.
        ".agentlas/experience-relations.jsonl",
    }
)
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
    executable: bool


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
    package_name = _read_package_name(base)
    package_slug = _read_package_slug(base)
    setup_wizard = run_setup_wizard(base, package_name, write=write_manifest)
    if write_manifest:
        package_slug = _read_package_slug(base) or package_slug

    career_card_findings = prepare_public_career_card_for_upload(base)
    files, file_count, findings = collect_upload_files(base)
    findings = career_card_findings + findings
    if setup_wizard.get("mcpPolicyValidation", {}).get("status") != "valid":
        findings.append(
            _finding(
                "mcp-policy-invalid",
                "blocker",
                "policy",
                "The package MCP policy is invalid or contains forbidden server execution fields.",
                ".agentlas/mcp-policy.json",
                "Keep only value-free catalog requirements; remove command, args, endpoint, executable, headers, and credential values.",
            )
        )
    routing = validate_routing_card_for_upload(base, visibility=visibility)
    findings.extend(routing["findings"])
    findings.extend(validate_public_profile_for_upload(base, visibility))
    public_career_card, public_career_findings = read_public_career_card_for_upload(base, visibility)
    findings.extend(public_career_findings)
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
        "slug": _slugify(slug or package_slug or package_name or base.name),
        "name": package_name or base.name,
        "tagline": _read_tagline(base),
        "agentKind": _infer_kind(base),
        "runtimeLabels": _runtime_labels(base),
        "visibility": "private-link" if visibility == "private-link" else "marketplace",
        "packageHash": package_hash_hex,
        # This is the delivered Agent Cloud artifact identity. It is distinct
        # from agentlas.json's local sourcePackage hash contract.
        "packageHashVersion": CLOUD_PACKAGE_HASH_VERSION,
        "fileCount": file_count,
        "includedFileCount": len(files),
        "totalBytes": sum(item.bytes for item in files),
        "createdAt": _now_iso(),
        "billingMode": "static-only",
        "costOwner": "none",
    }
    if routing.get("card"):
        manifest["routingCard"] = routing["card"]
    if public_career_card:
        manifest["careerGraph"] = public_career_card
    manifest, manifest_findings = sanitize_structured_payload(manifest, "manifest")
    findings.extend(manifest_findings)
    sanitized_line_count = sum(1 for finding in findings if finding["id"].startswith("sanitized-upload-line"))
    manifest["sanitizationApplied"] = sanitized_line_count > 0
    manifest["sanitizedLineCount"] = sanitized_line_count

    review = static_review(findings)
    bundle = {
        "manifest": manifest,
        "files": [item.__dict__ for item in files],
        "source": {"packagedBy": "hephaestus-runtime", "packagedAt": manifest["createdAt"], "costOwner": "none"},
        "sanitization": {"removedLineCount": sanitized_line_count},
    }
    if public_career_card:
        bundle["careerGraph"] = public_career_card
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


def _overwrite_precondition_headers(detail: str) -> dict[str, str] | None:
    """From a 428 ``client_upgrade_required`` register response, build the
    ``If-Match`` + ``x-agentlas-cloud-id`` headers the server requires to
    overwrite an existing same-slug asset of a different generation. The server
    hands us the current ETag and cloudId in the error body; returning them lets
    a same-id overwrite proceed (the normal expectation) instead of hard-failing.
    Returns ``None`` when the body is not this specific precondition case.
    """
    try:
        body = json.loads(detail)
    except (ValueError, TypeError):
        return None
    if not isinstance(body, dict) or body.get("code") != "client_upgrade_required":
        return None
    current = body.get("current")
    if not isinstance(current, dict):
        return None
    etag = current.get("etag")
    cloud_id = current.get("cloudId")
    if not (isinstance(etag, str) and etag and isinstance(cloud_id, str) and cloud_id):
        return None
    return {"If-Match": etag, "x-agentlas-cloud-id": cloud_id}


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
    data = json.dumps(payload).encode("utf-8")

    def _post(extra_headers: dict[str, str] | None = None) -> dict[str, Any]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "hephaestus-upload",
            "Origin": base,
        }
        if extra_headers:
            headers.update(extra_headers)
        request = urllib.request.Request(
            f"{base}/api/cloud-agents/v1/register",
            data=data,
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))

    try:
        return _post()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        # A same-slug overwrite of a different-generation asset needs an
        # optimistic-concurrency precondition. The 428 body hands us the current
        # ETag + cloudId; retry once with them so the overwrite proceeds (the
        # expected "same id overwrites" behavior) instead of hard-failing.
        if exc.code == 428:
            precondition = _overwrite_precondition_headers(detail)
            if precondition:
                try:
                    return _post(precondition)
                except urllib.error.HTTPError as retry_exc:
                    retry_detail = retry_exc.read().decode("utf-8", errors="replace")[:800]
                    raise UploadError(
                        f"Agentlas Cloud registration failed HTTP {retry_exc.code} after precondition retry: {retry_detail}"
                    ) from retry_exc
        raise UploadError(f"Agentlas Cloud registration failed HTTP {exc.code}: {detail[:800]}") from exc
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


def validate_routing_card_for_upload(base: Path, visibility: str = "marketplace") -> dict[str, Any]:
    # The routing card powers Hub routing, so it gates only public (marketplace)
    # uploads. Private-link Cloud storage accepts packages without one; when a
    # card exists but has problems, those findings are downgraded to advice.
    public = visibility == "marketplace"

    def _result(ok: bool, card: dict[str, Any] | None, findings: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
        if not public and findings:
            findings = [{**finding, "severity": "advice"} for finding in findings]
            ok = True
        return {"ok": ok, "card": card, "findings": findings, **extra}

    card_path = base / ".agentlas" / "routing-card.json"
    if not card_path.is_file():
        if not public:
            return {"ok": True, "card": None, "findings": []}
        return _result(
            False,
            None,
            [
                _finding(
                    "routing-card-required",
                    "blocker",
                    "structure",
                    "Public upload requires .agentlas/routing-card.json.",
                    ".agentlas/routing-card.json",
                    "Run `bin/hephaestus cards migrate <agent-folder> --tier local`, then fill triggers, anti-triggers, and benchmark fixtures.",
                )
            ],
        )
    try:
        card = json.loads(card_path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return _result(
            False,
            None,
            [_finding("routing-card-invalid-json", "blocker", "structure", "Routing card is not valid JSON.", ".agentlas/routing-card.json", "Fix the JSON before upload.")],
        )
    if not isinstance(card, dict):
        return _result(
            False,
            None,
            [_finding("routing-card-invalid", "blocker", "structure", "Routing card must be a JSON object.", ".agentlas/routing-card.json", "Replace it with routing-card/2.0 metadata.")],
        )

    findings: list[dict[str, Any]] = []
    card, card_findings = sanitize_structured_payload(card, ".agentlas/routing-card.json")
    findings.extend(card_findings)
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
    return _result(not findings, card, findings, lint=report)


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
    # Accept the *Ko localized variants too: title/description already read Ko
    # (line ~324), so guide sections must as well — otherwise a Korean-first
    # package with full guide copy is wrongly flagged "lacks enough sections".
    section_keys = [
        ("what-it-does", "whatItDoes", "whatItDoesKo"),
        ("best-for", "bestFor", "bestForKo"),
        ("prerequisites", "prerequisitesKo"),
        ("expected-outputs", "expectedOutputs", "expectedOutputsKo"),
        ("careful-with", "carefulWith", "carefulWithKo"),
    ]
    filled = 0
    for keys in section_keys:
        value = _first_text(guide, keys)
        if value and not _looks_generic_copy(value):
            filled += 1
    if filled < 4:
        findings.append(_finding("public-profile-guide-sections", "blocker", "market-page", "publicProfile guide lacks enough concrete sections.", "agentlas.json", "Fill at least four concrete guide sections for marketplace readers."))
    return findings


def prepare_public_career_card_for_upload(base: Path) -> list[dict[str, Any]]:
    """Generate a Hub-safe Career Graph card when this package already opted in.

    Upload packaging must not crawl arbitrary folders. The automatic path is
    enabled only when the package already has Career Graph markers; otherwise
    the feature remains absent and upload behavior is unchanged.
    """
    agentlas_dir = base / ".agentlas"
    public_card = agentlas_dir / "public-career-card.json"
    if public_card.is_file():
        return []
    markers = (
        agentlas_dir / "career-graph.json",
        agentlas_dir / "career-graph-sources.json",
        agentlas_dir / "career-graph.sqlite",
    )
    if not any(path.exists() for path in markers):
        return []
    try:
        from career_graph.runtime import CareerGraphRuntime, RuntimeConfig

        runtime = CareerGraphRuntime(RuntimeConfig(project=base))
        runtime.ingest(rebuild=True)
        runtime.public_card(write=True)
        return []
    except Exception:
        return [
            _finding(
                "career-card-auto-generate-failed",
                "advice",
                "market-page",
                "Career Graph public card could not be generated during packaging.",
                ".agentlas/public-career-card.json",
                "Run `career-graph ingest --project .` and `career-graph public-card --write --project .` before upload.",
            )
        ]


def read_public_career_card_for_upload(base: Path, visibility: str) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    path = base / ".agentlas" / "public-career-card.json"
    if not path.is_file():
        return None, []
    card = _read_json(path)
    if not isinstance(card, dict):
        return None, [_finding("career-card-invalid", "blocker", "market-page", "public Career Graph card is not valid JSON.", ".agentlas/public-career-card.json", "Regenerate it with `career-graph public-card --write`.")]
    findings: list[dict[str, Any]] = []
    if card.get("kind") != "agentlas-public-career-card":
        findings.append(_finding("career-card-kind", "blocker", "market-page", "public Career Graph card has an invalid kind.", ".agentlas/public-career-card.json", "Regenerate it with `career-graph public-card --write`."))
    privacy = card.get("privacy") if isinstance(card.get("privacy"), dict) else {}
    for key in ("rawLocalPathsIncluded", "rawPromptsIncluded", "rawTranscriptsIncluded", "sourceTextIncluded"):
        if privacy.get(key) is not False:
            findings.append(_finding("career-card-privacy", "blocker", "market-page", f"public Career Graph card must set privacy.{key}=false.", ".agentlas/public-career-card.json", "Do not publish raw local memory, prompts, transcripts, source text, or paths."))
    raw = json.dumps(card, ensure_ascii=False, sort_keys=True)
    sensitive_roots = [str(base), str(Path.home())]
    if any(root and root in raw for root in sensitive_roots):
        findings.append(_finding("career-card-local-path", "blocker", "market-page", "public Career Graph card contains a local absolute path.", ".agentlas/public-career-card.json", "Regenerate the redacted public card before upload."))
    if findings and visibility == "marketplace":
        return None, findings
    if findings:
        findings = [{**finding, "severity": "advice"} for finding in findings]
    allowed = {
        "schemaVersion",
        "kind",
        "generatedAt",
        "projectName",
        "indexStatus",
        "policy",
        "privacy",
        "counts",
        "canonicalSources",
        "staleSourceCount",
        "sourceKinds",
        "nodeTypes",
        "edgeTypes",
    }
    return {key: card[key] for key in allowed if key in card}, findings


def sanitize_structured_payload(payload: Any, file_label: str) -> tuple[Any, list[dict[str, Any]]]:
    findings: list[dict[str, Any]] = []

    def _walk(value: Any, path: str) -> Any:
        if isinstance(value, str):
            sanitized, value_findings = sanitize_upload_text(path, value)
            findings.extend(value_findings)
            return sanitized
        if isinstance(value, list):
            return [_walk(item, f"{path}[{index}]") for index, item in enumerate(value)]
        if isinstance(value, dict):
            return {key: _walk(item, f"{path}.{key}") for key, item in value.items()}
        return value

    return _walk(payload, file_label), findings


def sanitize_upload_text(file_path: str, text: str) -> tuple[str, list[dict[str, Any]]]:
    """Enterprise upload guard.

    Removes only high-confidence malicious lines (prompt-injection, secret
    exfiltration, encoded execution, destructive commands, persistence, hidden
    control characters, hard-coded credentials, spanning private keys) so the
    package can still be published. Ambiguous/advisory/quoted matches are FLAGGED
    for review but KEPT, preserving agent quality. Obfuscation (homoglyphs,
    leetspeak, zero-width, bidi, separators, non-English) is defeated via a
    normalized detection shadow, and split injections via a multi-line window.
    """
    findings: list[dict[str, Any]] = []
    lines = text.splitlines(keepends=True)
    remove = [False] * len(lines)
    dropping_private_key = False

    for idx, line in enumerate(lines):
        line_number = idx + 1

        # 1) private-key material may span multiple lines
        if "-----BEGIN" in line and "PRIVATE KEY-----" in line.upper():
            dropping_private_key = True
        if dropping_private_key:
            remove[idx] = True
            findings.append(_line_finding("sanitized-upload-line", "high", "sanitized-content", "Removed private key material before upload.", file_path, line_number, "private-key", "Publish setup instructions or env key names, never key material."))
            if "-----END" in line and "PRIVATE KEY-----" in line.upper():
                dropping_private_key = False
            continue

        # 2) hard-coded credentials / tokens on this line
        secret = _secret_line_reason(line)
        if secret:
            rule, message = secret
            remove[idx] = True
            findings.append(_line_finding("sanitized-upload-line", "high", "sanitized-content", message, file_path, line_number, rule, "Require each user to configure their own credentials."))
            continue

        # 3) content-safety verdict (injection / exfil / danger / obfuscation)
        verdict = content_guard.evaluate_line(line)
        if verdict is None:
            continue
        if verdict.action == "redact":
            remove[idx] = True
            findings.append(_line_finding("sanitized-upload-line", verdict.severity, "sanitized-content", verdict.message, file_path, line_number, verdict.rule, "Keep package content instructional; never embed attacker directives."))
        else:  # flag: keep the line, surface for review (quality preserved)
            findings.append(_line_finding("flagged-upload-line", verdict.severity, "flagged-content", verdict.message, file_path, line_number, verdict.rule, "Reviewed as advisory/quoted; kept to preserve agent quality."))

    # 4) split injections spanning consecutive lines (per-line scan evades these)
    for span in content_guard.find_multiline_spans(lines):
        if span.action == "redact":
            for k in range(span.start, span.end + 1):
                if not remove[k] and lines[k].strip():
                    remove[k] = True
                    findings.append(_line_finding("sanitized-upload-line", "high", "sanitized-content", span.message, file_path, k + 1, span.rule, "Keep package content instructional; never embed attacker directives."))
        else:  # flag: keep the split window, surface for review
            findings.append(_line_finding("flagged-upload-line", span.severity, "flagged-content", span.message, file_path, span.start + 1, span.rule, "Reviewed as descriptive/quoted; kept to preserve agent quality."))

    kept = [lines[i] for i in range(len(lines)) if not remove[i]]
    return "".join(kept), findings


def sanitize_upload_file_text(file_path: str, text: str) -> tuple[str, list[dict[str, Any]]]:
    if Path(file_path).suffix.lower() != ".json":
        return sanitize_upload_text(file_path, text)
    try:
        payload = json.loads(text)
    except ValueError:
        return sanitize_upload_text(file_path, text)
    sanitized, findings = sanitize_structured_payload(payload, file_path)
    return json.dumps(sanitized, ensure_ascii=False, indent=2) + "\n", findings


def _secret_line_reason(line: str) -> tuple[str, str] | None:
    for finding_id, pattern, message in SECRET_PATTERNS:
        if pattern.search(line):
            return finding_id, f"Removed possible {message} before upload."
    return None


def collect_upload_files(base: Path) -> tuple[list[UploadFile], int, list[dict[str, Any]]]:
    files: list[UploadFile] = []
    findings: list[dict[str, Any]] = []
    total_bytes = 0
    file_count = 0
    for path in sorted(base.rglob("*")):
        rel = path.relative_to(base).as_posix()
        if any(part in SKIP_DIRS for part in path.relative_to(base).parts):
            continue
        if rel in UPLOAD_DERIVED_EVIDENCE_PATHS or is_local_experience_lineage_path(rel):
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
        if not _is_text_package_file(path):
            continue
        raw = path.read_bytes()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
        asset_identity = standalone_experience_asset_identity(text)
        if asset_identity:
            findings.append(
                _finding(
                    "standalone-experience-asset",
                    "blocker",
                    "asset-boundary",
                    "A separately owned Experience/Taste asset JSON cannot be embedded in an AgentDefinition "
                    f"package ({asset_identity}).",
                    rel,
                    "Remove the standalone asset and publish it through the separate Experience/Taste flow; "
                    "the base package may keep only exact release IDs or value-free loadout references.",
                )
            )
            # Never place cross-kind bytes in the returned base-agent bundle,
            # even though the blocker already prevents registration/dry-run.
            continue
        if stat.st_size > MAX_FILE_BYTES:
            findings.append(_finding("large-file", "high", "size", f"File exceeds {MAX_FILE_BYTES} bytes.", rel, "Move large assets out of the package."))
            continue
        text, sanitized_findings = sanitize_upload_file_text(rel, text)
        findings.extend(sanitized_findings)
        raw = text.encode("utf-8")
        for finding_id, pattern, label in SECRET_PATTERNS:
            if pattern.search(text):
                findings.append(_finding(finding_id, "blocker", "secret", f"Possible {label} found in package content.", rel, "Remove the value and require each user to configure their own key."))
        if re.search(r"(?:curl|wget)[^\n|&;]+[|]\s*(?:sh|bash)", text, re.I):
            findings.append(_finding("curl-pipe-shell", "high", "network", "Remote shell install pattern detected.", rel, "Use explicit, reviewable install steps."))
        digest = _sha256_bytes(raw)
        files.append(
            UploadFile(
                path=rel,
                bytes=len(raw),
                sha256=digest,
                contentBase64=base64.b64encode(raw).decode("ascii"),
                executable=bool(stat.st_mode & 0o111),
            )
        )
    return files, file_count, findings


def hash_upload_files(files: list[UploadFile]) -> str:
    """Match Agent Cloud's path-sha256-executable-v2 artifact contract.

    JavaScript compares strings by UTF-16 code units. Encoding the path as
    big-endian UTF-16 gives Python the same deterministic ordering even for
    astral Unicode filenames.
    """

    digest = hashlib.sha256()
    for item in sorted(files, key=lambda file: file.path.encode("utf-16-be")):
        digest.update(item.path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(item.sha256.encode("ascii"))
        digest.update(b"\0")
        digest.update(b"x" if item.executable else b"-")
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


def _line_finding(finding_id: str, severity: str, category: str, message: str, file: str, line: int, rule: str, remediation: str | None = None) -> dict[str, Any]:
    payload = _finding(finding_id, severity, category, message, file, remediation)
    payload["id"] = f"{finding_id}-{_sha256_text(f'{file}:{line}:{rule}:{message}')[:10]}"
    payload["line"] = line
    payload["rule"] = rule
    return payload


def _read_package_name(base: Path) -> str:
    manifest = _read_json(base / "agentlas.json")
    if isinstance(manifest, dict):
        for key in ("displayName", "name"):
            value = str(manifest.get(key) or "").strip()
            if value:
                return value[:120]
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


def _read_package_slug(base: Path) -> str:
    manifest = _read_json(base / "agentlas.json")
    package_manifest = _read_json(base / "manifest.json")
    agent_card = _read_json(base / ".agentlas" / "agent-card.json")
    routing_card = _read_json(base / ".agentlas" / "routing-card.json")
    routing_ref = routing_card.get("agent_card_ref") if isinstance(routing_card, dict) else None
    candidates = [
        manifest.get("slug") if isinstance(manifest, dict) else None,
        manifest.get("id") if isinstance(manifest, dict) else None,
        package_manifest.get("package") if isinstance(package_manifest, dict) else None,
        package_manifest.get("slug") if isinstance(package_manifest, dict) else None,
        agent_card.get("slug") if isinstance(agent_card, dict) else None,
        agent_card.get("id") if isinstance(agent_card, dict) else None,
        routing_ref.get("slug") if isinstance(routing_ref, dict) else None,
    ]
    for candidate in candidates:
        slug = _stable_slug_candidate(candidate)
        if slug:
            return slug
    return ""


def _stable_slug_candidate(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    text = value.strip()
    if not text:
        return ""
    # routing ids may include a scope prefix such as paid/Web_master; the
    # package identity is the final segment, not the tier.
    return text.rsplit("/", 1)[-1].strip()


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
