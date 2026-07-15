"""Deterministic privacy boundary for public Experience data.

The scanner is deliberately small and model-free.  It rejects deterministic
private identifiers and host paths while preserving public protocol metadata,
HTTPS documentation links, and the two portable runtime placeholders.
"""

from __future__ import annotations

import ipaddress
import re
from urllib.parse import unquote


PRIVACY_CONTRACT_VERSION = "agentlas.experience-privacy.v1"

_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
_PHONE_CANDIDATE_RE = re.compile(r"(?<!\w)(?:\+?\d[\d ().-]{7,}\d)(?!\w)")
_LABELED_IDENTIFIER_RE = re.compile(
    r"\b(?:tenant|workspace|account|customer|user|client)[ _-]?"
    r"(?:id|key|number|no|ref|reference)\s*[:=#]?\s*[A-Za-z0-9_-]{4,}\b|"
    r"(?:테넌트|워크스페이스|계정|고객|사용자|클라이언트)[ _-]?"
    r"(?:id|아이디|키|번호|참조)\s*[:=#]?\s*[A-Za-z0-9_-]{4,}",
    re.I,
)
_UUID_RE = re.compile(
    r"(?<![A-Fa-f0-9])"
    r"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[1-8][0-9A-Fa-f]{3}-"
    r"[89ABab0-9][0-9A-Fa-f]{3}-[0-9A-Fa-f]{12}"
    r"(?![A-Fa-f0-9])"
)
_IP_CANDIDATE_RE = re.compile(r"(?<![A-Za-z0-9])\[?[0-9A-Fa-f:.]{3,}\]?(?![A-Za-z0-9])")
_HTTPS_URL_RE = re.compile(r"https://[^\s<>\"']+", re.I)
_PORTABLE_PLACEHOLDER_RE = re.compile(
    r"\$(?:PROJECT_ROOT|OUTPUT_DIR)(?:[/\\][^\s<>\"']*)?"
)
_FILE_URL_RE = re.compile(r"file://", re.I)
_TRAVERSAL_RE = re.compile(r"(?:^|[\s\"'`()\[\]{}=:,;])\.\.[/\\]")
_HOME_PATH_RE = re.compile(r"(?:^|[\s\"'`()\[\]{}=:,;])~[/\\](?=\S)")
_WINDOWS_DRIVE_RE = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:[/\\](?=\S)")
_UNC_RE = re.compile(r"(?:^|[\s\"'`()\[\]{}=:,;])\\\\[^\\/\s]+[\\/][^\\/\s]+")
_POSIX_ABSOLUTE_RE = re.compile(
    # HTTPS URLs and portable placeholders are masked before this pattern is
    # evaluated, so a colon is not a safe reason to exempt the following
    # slash.  Exempting it allowed labels such as ``path:/etc/passwd`` to pass
    # the public projection boundary.
    r"(?<![A-Za-z0-9$])/(?!/|\s)(?:[^/\s\"'`<>]+/)*[^/\s\"'`<>]+"
)

# Public, model-free credential detectors shared by every outbound public/Hub
# boundary.  Keep the result classes stable: callers persist only the class and
# field path, never the matched value.
_SECRET_VALUE_PATTERNS = (
    (
        "provider_token",
        re.compile(
            r"\b(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9_]{20,}|"
            r"github_pat_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16}|"
            r"xox[baprs]-[A-Za-z0-9-]{10,})\b"
        ),
    ),
    (
        "private_key",
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----", re.I),
    ),
    (
        "bearer_token",
        re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{12,}", re.I),
    ),
    (
        "jwt",
        re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
    ),
    (
        "credential_assignment",
        re.compile(
            r"\b(?:api[_-]?key|access[_-]?key|client[_-]?secret|secret|token|"
            r"password|passwd|cookie)\s*[:=]\s*['\"]?[^\s'\";,]{8,}",
            re.I,
        ),
    ),
    (
        "credential_url",
        re.compile(r"\b[A-Za-z][A-Za-z0-9+.-]*://[^\s/:@]+:[^\s/@]+@[^\s/]+", re.I),
    ),
)

_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_CANONICAL_ASSET_ID_RE = re.compile(
    r"^(?:ex[biu]_[0-9a-f]{48}|[a-z]{3}_[0-9a-f]{32,64}|rev_[0-9a-f]{32})$"
)
_NAMESPACED_PROTOCOL_ID_RE = re.compile(
    r"^(?:task|evidence|receipt|mcp|agent|variant|owner|user|workspace|ref|runtime|environment|env|skill|model):"
    r"[A-Za-z0-9][A-Za-z0-9._:/-]{1,240}$"
)
_ISO_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T[^\s]+$")


def _decoded(value: str) -> str:
    decoded = value
    for _ in range(3):
        next_value = unquote(decoded)
        if next_value == decoded:
            break
        decoded = next_value
    return decoded


def _masked_public_locations(value: str) -> str:
    """Mask public network links/placeholders before host-path detection."""

    return _PORTABLE_PLACEHOLDER_RE.sub(" ", _HTTPS_URL_RE.sub(" ", value))


def _contains_phone(value: str) -> bool:
    for match in _PHONE_CANDIDATE_RE.finditer(value):
        digit_count = sum(character.isdigit() for character in match.group(0))
        if 10 <= digit_count <= 15:
            return True
    return False


def _contains_ip(value: str) -> bool:
    for match in _IP_CANDIDATE_RE.finditer(value):
        candidate = match.group(0).strip("[]")
        if ":" not in candidate and "." not in candidate:
            continue
        try:
            ipaddress.ip_address(candidate)
        except ValueError:
            continue
        return True
    return False


def contains_private_path(value: str) -> bool:
    decoded = _decoded(value)
    masked = _masked_public_locations(decoded)
    return any(
        pattern.search(masked)
        for pattern in (
            _FILE_URL_RE,
            _TRAVERSAL_RE,
            _HOME_PATH_RE,
            _WINDOWS_DRIVE_RE,
            _UNC_RE,
            _POSIX_ABSOLUTE_RE,
        )
    )


def personal_identifier_kinds(value: str) -> tuple[str, ...]:
    """Return deterministic PII classes found outside an allowed HTTPS URL."""

    # A URL or portable-placeholder suffix can still contain an email, phone,
    # account label, UUID, or private IP.  Only path detection needs those
    # portable locations masked; PII detection must inspect the full value.
    masked = _decoded(value)
    has_uuid = bool(_UUID_RE.search(masked))
    phone_source = _UUID_RE.sub(" ", masked)
    findings: list[str] = []
    checks = (
        ("email", bool(_EMAIL_RE.search(masked))),
        ("phone", _contains_phone(phone_source)),
        ("labeled_identifier", bool(_LABELED_IDENTIFIER_RE.search(masked))),
        ("uuid", has_uuid),
        ("ip_address", _contains_ip(masked)),
    )
    for kind, matched in checks:
        if matched and kind not in findings:
            findings.append(kind)
    return tuple(findings)


def is_allowed_protocol_metadata(path: str, value: str) -> bool:
    """Allow only exact protocol-shaped values in explicit metadata fields."""

    key = re.sub(r"\[[0-9]+\]$", "", path.rsplit(".", 1)[-1]).lower()
    if key == "setupurl":
        return bool(_HTTPS_URL_RE.fullmatch(value))
    if key.endswith("hash"):
        return bool(_SHA256_RE.fullmatch(value))
    if key in {"createdat", "updatedat", "releasedat", "withdrawnat"}:
        return bool(_ISO_TIMESTAMP_RE.fullmatch(value))
    if (
        key.endswith("id")
        or key.endswith("ids")
        or key.endswith("ref")
        or key.endswith("refs")
        or key in {"ownerref", "revision"}
    ):
        return bool(_CANONICAL_ASSET_ID_RE.fullmatch(value) or _NAMESPACED_PROTOCOL_ID_RE.fullmatch(value))
    return False


def scan_public_text(value: str) -> tuple[str, ...]:
    """Scan user-authored public text, with no protocol-field exemption."""

    findings = list(personal_identifier_kinds(value))
    if contains_private_path(value):
        findings.append("local_path")
    return tuple(findings)


def secret_like_kinds(value: str) -> tuple[str, ...]:
    """Return stable secret classes without returning or rewriting a value."""

    decoded = _decoded(value)
    return tuple(kind for kind, pattern in _SECRET_VALUE_PATTERNS if pattern.search(decoded))


def scan_public_field(path: str, value: str) -> tuple[str, ...]:
    """Scan a public wire value with a narrow field-aware metadata allowlist."""

    findings: list[str] = []
    if not is_allowed_protocol_metadata(path, value):
        findings.extend(personal_identifier_kinds(value))
    if contains_private_path(value):
        findings.append("local_path")
    return tuple(dict.fromkeys(findings))
