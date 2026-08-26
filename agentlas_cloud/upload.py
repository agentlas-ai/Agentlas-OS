from __future__ import annotations

import base64
import gzip
import hashlib
import json
import os
import re
import stat
import tempfile
import unicodedata
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import content_guard
from .auth import AgentlasAuthError, ensure_access_token, normalize_base_url, same_origin_urlopen
from .pricing import PriceError, build_patch, set_prices
from .networking.card_lint import lint_card
from .package_contract import (
    is_generated_runtime_path,
    refresh_generated_projections,
    verify as verify_package_contract,
)
from .brief.write import write_offer_brief
from .experience_contracts import ContractValidationError, default_mcp_policy, validate_mcp_policy
from .upload_repair import classify_findings, repair_package
from .runtime import (
    collect_package_files,
    is_local_experience_lineage_path,
    is_value_free_credential_template,
    package_hash,
    package_hash_includes,
    run_setup_wizard,
    standalone_experience_asset_identity,
)
from .upload_limits_generated import (
    PACKAGE_MAX_FILE_BYTES,
    PACKAGE_MAX_FILES,
    PACKAGE_MAX_TOTAL_BYTES,
    PACKAGE_MAX_UNCOMPRESSED_FILE_BYTES,
    PACKAGE_MAX_UNCOMPRESSED_TOTAL_BYTES,
)

# 상한은 정본 하나(agentlas/AgentsAtlas/app .../upload-scan-catalog.json)에서
# 생성돼 내려온다 — upload_limits_generated.py. 여기서 다시 적으면 서버·데스크탑·
# 터미널과 어긋나고, 어긋난 쪽은 파일 이름도 없는 코드로 거절한다.
MAX_TOTAL_BYTES = PACKAGE_MAX_TOTAL_BYTES
MAX_FILE_BYTES = PACKAGE_MAX_FILE_BYTES
MAX_UNCOMPRESSED_FILE_BYTES = PACKAGE_MAX_UNCOMPRESSED_FILE_BYTES
MAX_UNCOMPRESSED_TOTAL_BYTES = PACKAGE_MAX_UNCOMPRESSED_TOTAL_BYTES
# Walk bound so a pathological tree terminates; the package ceiling is MAX_FILES,
# measured on the files actually uploaded.
MAX_WALKED_ENTRIES = 20_000
MAX_FILES = PACKAGE_MAX_FILES
# Collection keeps walking past MAX_FILES so the ranked trimmer can choose what
# to drop; this is the bound where a tree is too big for that choice to matter.
MAX_COLLECTED_FILES = 4 * MAX_FILES
MAX_SNAPSHOT_BYTES = 32 * 1024 * 1024
AGENT_DEFINITION_FILES = {"AGENT.md", "AGENTS.md", "CLAUDE.md", "GEMINI.md", "README.md", "agent.md", "manifest.md", "system-prompt.md"}
# Engine scaffold stencils are all `{{UPPER_SNAKE}}` (mirrors repackage._PLACEHOLDER).
# Deliberately does NOT match user templating like `{{input}}` or `${{ secrets.X }}`,
# so the withdraw pass never deletes a file a person actually authored.
_ENGINE_STENCIL_RE = re.compile(r"\{\{[A-Z0-9_]+\}\}")
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
        # The routing brief is DERIVED — every field of it is computed from the
        # card, the manifest and the contracts that ship beside it. Shipping a
        # derived file would tie the artifact's identity to the compiler rather
        # than to the author's work: improving how a shape is inferred would mint
        # a new release for all 247 published packages without one of them having
        # changed. It is written locally so an author can read what the routing
        # layer sees, and the reader compiles its own from the same sources.
        ".agentlas/brief.json",
    }
)
# Private per-machine project memory the product's own generated .gitignore
# declares "describes THEM rather than the product" and keeps out of git —
# Desktop's `isMachineLocalStatePath` mirrors this exact set so one folder
# hashes identically no matter which channel uploads it. Installers lose
# nothing: project bootstrap regenerates every one of these on first contact.
# (memory-tickets.jsonl / ticket-slugs.json stay: teams ship authored seed
# memories and One's memory-map consumes them.)
UPLOAD_PRIVATE_PROJECT_STATE_PATHS = frozenset(
    {
        ".agentlas/sitemap.json",
        ".agentlas/project-soul-memory.md",
        ".agentlas/memory-log.jsonl",
        ".agentlas/curator-decisions.jsonl",
        ".agentlas/skill-trials.jsonl",
        ".agentlas/local-credentials.map.json",
    }
)
UPLOAD_PRIVATE_PROJECT_STATE_DIRS = (".agentlas/code-map/",)
# A RESULT IS NOT A CAPABILITY (owner decision 2026-08-18). What an agent
# produces while it works -- the rendered page, the screenshot it took to check
# itself, the deck it exported, the page dump its browser tool left behind -- is
# the output of one run on one machine. What ships is the script/prompt/preset
# that makes it again on the installer's machine. Measured across the published
# teams: every folder over the 3 MB ceiling was over it because of outputs, and
# not one of those files was read by the agent that carried it.
# `.agentlas/work/` is the declared home for run outputs so authors have a
# correct place to write. Mirrors Desktop's WORK_OUTPUT_DIRS file-for-file.
UPLOAD_WORK_OUTPUT_DIRS = (
    ".agentlas/work/",
    ".agentlas/chat-attachments/",
    ".agentlas/runs/",
    ".playwright-mcp/",
    ".studio-runtime/",
    ".pytest_cache/",
    ".ruff_cache/",
    ".mypy_cache/",
    ".gradle/",
    ".venv/",
    "venv/",
    ".cache/",
    "tmp/",
    "temp/",
    ".tmp/",
)
# WHAT THE PRODUCT REFUSES TO COMMIT, THE PRODUCT MUST REFUSE TO PUBLISH.
# The generated project .gitignore keeps `signing/*` and `credentials/*` out of
# git, exempting only each folder's README. Upload screened file NAMES only, so
# `credentials/google-services.json` shipped. Mirrored folder-for-folder here.
UPLOAD_PRODUCT_PRIVATE_DIRS = ("credentials/", "signing/")
UPLOAD_PRODUCT_PRIVATE_KEPT_FILES = frozenset({"readme.md"})


def is_work_output_path(relative_path: str) -> bool:
    """Return whether a package path is a run output that regenerates on install."""

    normalized = relative_path.replace("\\", "/").lower()
    return any(
        normalized == candidate.rstrip("/")
        or normalized.startswith(candidate)
        or f"/{candidate}" in normalized
        for candidate in UPLOAD_WORK_OUTPUT_DIRS
    )


def is_product_private_folder_path(relative_path: str) -> bool:
    """Return whether a package path sits in a folder the product keeps out of git."""

    normalized = relative_path.replace("\\", "/").lower()
    inside = any(
        normalized.startswith(candidate) or f"/{candidate}" in normalized
        for candidate in UPLOAD_PRODUCT_PRIVATE_DIRS
    )
    if not inside:
        return False
    return normalized.rsplit("/", 1)[-1] not in UPLOAD_PRODUCT_PRIVATE_KEPT_FILES
BLOCKED_FILE_PATTERNS = [
    re.compile(r"^\.env(?:\..*)?$", re.I),
    re.compile(r"^id_rsa(?:\.pub)?$", re.I),
    re.compile(r"^credentials(?:\..*)?$", re.I),
    re.compile(r"^secrets?(?:\..*)?$", re.I),
    re.compile(r"^\.npmrc$", re.I),
    re.compile(r"(?:^|[._-])service-account(?:[._-]|$)", re.I),
    re.compile(r"\.(?:key|pem|p12|pfx|mobileprovision)$", re.I),
]
SECRET_PATTERNS = [
    ("private-key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----", re.I), "private key material"),
    ("openai-key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"), "OpenAI-style API key"),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{30,}\b"), "GitHub token"),
    ("slack-token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"), "Slack token"),
    ("aws-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "AWS access key"),
    ("npm-token", re.compile(r"\bnpm_[A-Za-z0-9]{20,}\b"), "npm access token"),
    ("anthropic-key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b"), "Anthropic API key"),
    ("google-api-key", re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b"), "Google API key"),
    ("gitlab-token", re.compile(r"\bglpat-[0-9A-Za-z_-]{20,}\b"), "GitLab token"),
    ("huggingface-token", re.compile(r"\bhf_[A-Za-z0-9]{20,}\b"), "Hugging Face token"),
    ("stripe-secret", re.compile(r"\b(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{16,}\b"), "Stripe secret key"),
    ("generic-secret", re.compile(r"\b(?:api[_-]?key|secret|token|password)\s*[:=]\s*['\"][^'\"]{8,}['\"]", re.I), "hard-coded credential"),
]
UNQUOTED_SECRET_ASSIGNMENT = re.compile(
    r"(?<![A-Za-z0-9])[_A-Za-z0-9-]*(?:api[_-]?(?:key|token)|access[_-]?token|auth[_-]?token|"
    r"secret(?:[_-]?access[_-]?key)?|password|passphrase|credential)[_A-Za-z0-9-]*"
    r"\s*[:=]\s*([^\s,;#}\]]{8,})",
    re.I,
)
CAPABILITY_RE = re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)+$")


class UploadError(RuntimeError):
    def __init__(self, message: str, *, code: str = "upload_error") -> None:
        super().__init__(message)
        self.code = code


@dataclass
class UploadFile:
    path: str
    #: Size of the ORIGINAL file. packageHash is built from this and sha256, so
    #: it does not move with the encoding.
    bytes: int
    #: sha256 of the ORIGINAL bytes.
    sha256: str
    contentBase64: str
    executable: bool
    #: None means identity -- exactly what packages written before compression say.
    encoding: str | None = None
    #: Bytes that actually travel. Set only alongside ``encoding``.
    encodedBytes: int | None = None


def encode_upload_content(raw: bytes) -> tuple[str, str | None, int | None]:
    """Compress when it helps and say so; otherwise ship the bytes unchanged.

    Text shrinks 2-3x, already-compressed media does not, and a "compressed"
    file that grew would cost the author room for nothing.
    """

    compressed = gzip.compress(raw, 9)
    if len(compressed) >= len(raw):
        return base64.b64encode(raw).decode("ascii"), None, None
    return base64.b64encode(compressed).decode("ascii"), "gzip", len(compressed)


@dataclass(frozen=True)
class SnapshotEntry:
    kind: str
    mode: int
    device: int
    inode: int
    links: int
    size: int
    modified_ns: int
    changed_ns: int


@dataclass(frozen=True)
class SnapshotTailCommitment:
    entry_count: int
    regular_file_bytes: int
    digest: str



def _is_unfinished_artifact(finding: dict[str, Any]) -> bool:
    """True when a blocker is only "the author has not written this yet".

    This narrow classification controls the user-facing explanation. Other
    unsupported entries are withheld later with an engine-gap receipt; none of
    the classifications authorize shipping bytes that the collector omitted.
    """

    message = str(finding.get("message") or "")
    if "unfilled placeholders" in message:
        return True
    if message.endswith(": missing"):
        artifact = message.rsplit(":", 1)[0].strip()
        return artifact.startswith((".agentlas/", "docs/", "contracts/")) or artifact in {
            "AGENTS.md",
            "agent.md",
        }
    return False


def referenced_file_names(files: list[UploadFile]) -> set[str]:
    """Every file name mentioned inside the package's own text.

    A shotplan naming ``/samples/angle-frontal.jpg``, a prompt naming
    ``lens-24.jpg``, a skill naming ``dossier.md`` -- each of those makes the
    named file part of the agent. Names only, never paths, so ``./samples/x.jpg``
    and ``samples/x.jpg`` both count.
    """

    # `[A-Za-z0-9._-]+\.[A-Za-z0-9]{1,8}` scanned over a whole file is
    # quadratic on the lines real packages contain. On a run of identical
    # characters — minified JS, a base64 data URI, a one-line JSON — the greedy
    # class matches to the end at every start position, then backtracks looking
    # for the dot that never comes. Measured: 256 KB in one line spent 29.6s
    # here, 1 MB spent 483s, and the author saw an upload that simply never
    # finished. Tokenizing first is linear: a run with no dot in it is skipped
    # whole, and the name pattern only ever runs on a bounded candidate.
    token_re = re.compile(r"[A-Za-z0-9._-]+")
    name_re = re.compile(r"[A-Za-z0-9._-]+\.[A-Za-z0-9]{1,8}")
    names: set[str] = set()
    for item in files:
        if item.bytes > MAX_UNCOMPRESSED_FILE_BYTES:
            continue
        try:
            raw = base64.b64decode(item.contentBase64)
            if item.encoding == "gzip":
                raw = gzip.decompress(raw)
            text = raw.decode("utf-8")
        except (ValueError, UnicodeDecodeError, OSError):
            continue
        for token in token_re.finditer(text):
            candidate = token.group(0)
            if "." not in candidate:
                continue
            # A name is short. A dotted token this long is data, not a filename,
            # and only its tail could carry one.
            if len(candidate) > 512:
                candidate = candidate[-512:]
            names.update(match.group(0).lower() for match in name_re.finditer(candidate))
    return names

def _trim_upload_files_to_limits(
    files: list[UploadFile],
    findings: list[dict[str, Any]],
) -> list[UploadFile]:
    """Drop the least essential files, largest first, until the package fits.

    Mirrors Desktop's `trimPackageToLimits`. Without it a package over either
    whole-package limit was packaged in full and refused by the server with a
    413 the author could do nothing about — hep-upload softens every local
    blocker to a warning precisely so an author is never handed a refusal, and
    that made the size blockers travel all the way to the server instead of
    being fixed here. Rank 0 (agent definitions, .agentlas cards, manifests) is
    never dropped; each drop is recorded as a finding.
    """
    # TRIMMING MUST NOT COST THE AGENT ITS ABILITIES (owner decision 2026-08-18).
    #
    # Ranking by size and file type alone knows nothing about what the agent
    # needs. Two consequences, both measured on shipped teams: `knowledge/`,
    # `skills/`, `prompts/` and `presets/` counted as ordinary content, so the
    # biggest knowledge file went before any build output; and `samples/` was
    # dropped early as "examples" while photo-studio-agent-team's shotplans name
    # `/samples/angle-frontal.jpg` on every cut -- those samples ARE the
    # capability. Mirrors Desktop's rankOf in cloud-agents/package.ts.
    capability_dir = re.compile(r"(^|/)(knowledge|skills?|prompts?|presets?|agents|workers|contracts|shotplans|playbooks|templates)/")
    referenced = referenced_file_names(files)

    def rank(item: UploadFile) -> int:
        lower = item.path.lower()
        base = lower.rsplit("/", 1)[-1]
        if base in {name.lower() for name in AGENT_DEFINITION_FILES}:
            return 0
        if lower.startswith(".agentlas/"):
            return 0
        if lower in {"agentlas.json", "manifest.json", "package.json"}:
            return 0
        if capability_dir.search(lower):
            return 0
        # Named by something else in the package -- part of the agent, wherever it sits.
        if base in referenced:
            return 0
        if re.search(r"(^|/)(node_modules|dist|build|out|coverage|\.next|\.venv|__pycache__|\.git)/", lower):
            return 1
        if re.search(r"\.(png|jpe?g|gif|webp|svg|mp4|mov|mp3|wav|pdf|zip|tar|gz|tgz|bin|so|dylib|dll|wasm|sqlite|db)$", lower):
            return 2
        if re.search(r"(^|/)(tests?|__tests__|fixtures?|benchmarks?|logs?|examples?)/", lower):
            return 3
        if re.search(r"\.(log|jsonl|csv|tsv|lock)$", lower):
            return 4
        return 5 if item.bytes > 64 * 1024 else 6

    def over_limit(current: list[UploadFile]) -> bool:
        # The ceiling is about what is stored, so it counts the bytes that
        # actually travel -- the same rule the packer and the server apply.
        return len(current) > MAX_FILES or sum(
            (item.encodedBytes if item.encodedBytes is not None else item.bytes) for item in current
        ) > MAX_TOTAL_BYTES

    if not over_limit(files):
        return files
    kept = list(files)
    # Least essential first; within a rank the biggest file buys the most room.
    order = sorted(
        (item for item in files if rank(item) > 0),
        key=lambda item: (rank(item), -item.bytes),
    )
    dropped: list[str] = []
    for item in order:
        if not over_limit(kept):
            break
        kept.remove(item)
        dropped.append(item.path)
    for path_value in dropped:
        findings.append(
            _finding(
                "trimmed-for-package-limits",
                "warning",
                "size",
                "Left out of the uploaded package so it fits the Agent Cloud limits.",
                path_value,
                "Nothing to do. Keep large assets outside the agent folder to control what ships.",
            )
        )
    # Everything droppable is gone and the package is still over. What remains
    # is rank 0 — the agent definition, its cards, its skills. Dropping any of
    # it would publish something that is not the agent, so this is the one size
    # case that stays a refusal instead of a receipt.
    if over_limit(kept):
        biggest = max(kept, key=lambda item: item.encodedBytes if item.encodedBytes is not None else item.bytes, default=None)
        rel = biggest.path if biggest is not None else None
        if len(kept) > MAX_FILES:
            findings.append(_finding("file-count-limit", "blocker", "size", f"Package still has more than {MAX_FILES} essential files after dropping everything droppable.", rel, "Split the team into smaller packages."))
        else:
            findings.append(_finding("package-size-limit", "blocker", "size", f"Package is over {MAX_TOTAL_BYTES} bytes even with only the agent's essential files left.", rel, "Move large assets out of the agent folder, or split the package."))
    return kept


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

    # An installed copy is never published to the Hub.
    #
    # The server refuses a fork two ways -- declared lineage on the submission,
    # and identical bytes already listed by another account. A local round trip
    # defeats both: restore the copy, edit one line, and the hash no longer
    # matches anything while the folder carries no lineage of its own. The
    # restore marker is what survives that round trip, so the refusal has to
    # read it here, before a minute is spent packaging an upload the server
    # would reject anyway.
    #
    # Only the public Hub upload is blocked. A private re-upload of your own
    # copy is ordinary use and stays allowed.
    if visibility == "marketplace":
        fork = _read_restore_fork(base)
        if fork:
            origin = fork.get("originSlug") or "another creator"
            raise UploadError(
                f"this folder is an installed copy of {origin}; it can be run, edited, "
                "and staffed into work orders, but the Hub listing belongs to the "
                "original creator",
                code="fork_cannot_publish",
            )

    # Deferred until after the derivations below. Refreshing here recorded a
    # `source.package_hash` over a package that had not been completed yet, so
    # the card lagged one round: the first upload of any package whose content
    # the engine changed produced a different hash from every later one, which
    # breaks hash preservation on republish. The card is written last, over the
    # package as it will actually ship.
    routing_meta: dict[str, Any] = {"updated": False, "reason": "deferred"}
    package_name = _read_package_name(base)
    package_slug = _read_package_slug(base)
    # Deferred with the card refresh below, and for the same reason: the wizard
    # computes the package hash and writes it into `agentlas.json`. Running it
    # here hashed the package BEFORE the engine completed it, so the first
    # upload of any package the derivations touched recorded an identity for a
    # package that no longer existed, and only the second run agreed with the
    # first. Identity is recorded last, over what actually ships.
    if write_manifest:
        package_slug = _read_package_slug(base) or package_slug

    # Lay the package contract down before anything reads the folder. The repair
    # pass below fixes fields inside files that exist; it was never able to fix a
    # file that was absent, and absence is what actually blocks: measured on this
    # product's own published corpus, 13 of the 13 blockers on a real package were
    # "<artifact>: missing", every one of them an artifact the engine ships a
    # template for. Refusing an upload over a file the product can write itself is
    # the failure this whole path exists to avoid.
    #
    # `scaffold` never overwrites, and `derive` only answers questions the package
    # already answers — its slug, its own summary, its own capability list. What
    # neither can supply without inventing a fact is still reported below.
    contract_scaffold: dict[str, Any] = {}
    try:
        from .package_contract import scaffold as scaffold_contract
        from .repackage import derive as derive_contract

        manifest_hint = _read_json(base / "agentlas.json") if callable(globals().get("_read_json")) else {}
        if not isinstance(manifest_hint, dict):
            manifest_hint = {}
        slug_hint = str(manifest_hint.get("slug") or base.name)
        # Ask the ROSTER what this package is, not the artifact we are here to
        # create. Keying the mode off `company-blueprint.json` made the scaffold
        # circular: a team missing its blueprint was scaffolded as a single, so no
        # blueprint was ever written, while the contract verifier - which reads the
        # roster - kept checking it against every TEAM requirement. Measured
        # 2026-08-07 across the 178 published packages, that one line produced 262
        # of the 264 standing blockers on 65 packages, every one of them a team
        # whose `agents/*/agent.md` roster was complete.
        # FIRST: make the roster on disk and the declared kind agree. Everything
        # after this reads the package as the fact, so a flat roster or a card
        # claiming `team` over an empty folder has to be settled before the
        # scaffold decides what to lay down - otherwise the mode is derived from
        # a shape that is about to change.
        from .repackage import reconcile_team_shape

        reconciled = reconcile_team_shape(base)
        if reconciled:
            contract_scaffold["teamShapeReconciled"] = reconciled
        from .upload_repair import _derived_entity_type

        derived_kind, _ = _derived_entity_type(base)
        mode_hint = "team" if derived_kind == "team" else "single"
        # Merge, never replace. This was a bare assignment, so everything the
        # passes above recorded — the team-shape reconciliation in particular —
        # was thrown away before the caller ever saw it, and a receipt nobody
        # receives is the same as a repair nobody made.
        contract_scaffold = {
            **contract_scaffold,
            **scaffold_contract(
                base, mode=mode_hint, package_id=slug_hint, name=slug_hint, command=slug_hint
            ),
        }
        derive_contract(base, slug=slug_hint, entity_kind=mode_hint)
        # Shape mismatches last, after derive has written whatever it could: an
        # answer in the wrong shape is not a missing answer, and blocking on one
        # asks the author to retype what the package already says.
        from .repackage import coerce_contract_shapes

        coerced = coerce_contract_shapes(base, slug_hint)
        if coerced:
            contract_scaffold["coerced"] = coerced
        from .repackage import (
            fill_capability_eval_plan,
            fill_declared_artifacts,
            fill_runtime_adapter_bodies,
            fill_thin_runtime_adapters,
            redact_host_paths,
        )

        from .repackage import prune_unrecognised_manifest_keys

        pruned = prune_unrecognised_manifest_keys(base)
        if pruned:
            contract_scaffold["manifestKeysDropped"] = pruned
        declared = fill_declared_artifacts(base, slug_hint)
        if declared:
            contract_scaffold["declaredArtifacts"] = declared
        if fill_capability_eval_plan(base):
            contract_scaffold["evalPlanDerived"] = True
        adapters = fill_runtime_adapter_bodies(base, slug_hint)
        if adapters:
            contract_scaffold["adaptersWritten"] = adapters
        thin_adapters = fill_thin_runtime_adapters(base, slug_hint)
        if thin_adapters:
            contract_scaffold["thinRuntimeAdaptersWritten"] = thin_adapters

        redacted = redact_host_paths(base)
        if redacted:
            contract_scaffold["hostPathsRedacted"] = redacted
    except Exception as error:  # noqa: BLE001 - never let repair stop the upload path
        contract_scaffold = {"status": "skipped", "reason": str(error)[:200]}

    # Whatever this pass laid down and could not fill is withdrawn again. A
    # stencil that still reads `{{ROLE}}` is worse than the absence it replaced:
    # it ships the word `{{ROLE}}` to a buyer, and it blocks the upload on a file
    # the author never wrote. Upload does not block, and it does not publish
    # placeholder text either — so the only correct move is to take back exactly
    # what this pass added and could not answer.
    # Withdraw what this pass created AND any canonical entry file that is still
    # an ENGINE stencil. The created-only list misses a PRE-EXISTING stencil
    # AGENTS.md: scaffold skips a file that already exists, so it is never in
    # `created`, yet it ships `{{ROLE}}` to a buyer as the very file the runtime
    # reads first (measured 2026-08-12).
    #
    # Match ONLY engine stencil tokens `{{UPPER_SNAKE}}` (repackage._PLACEHOLDER),
    # never any `{{`. The bare-`{{` test deleted user-authored source in place —
    # a README with `${{ secrets.TOKEN }}` (GitHub Actions), an agent.md with
    # `{{input}}`/`{{target_lang}}` prompt placeholders — permanent silent data
    # loss that could leave a package with no entry file (measured 2026-08-12
    # adversarial set 2). Engine stencils are all UPPER_SNAKE; user templating
    # (lowercase, dotted, spaced) never is.
    withdraw_paths: list[str] = list(contract_scaffold.get("created") or [])
    for name in AGENT_DEFINITION_FILES:
        if name not in withdraw_paths:
            withdraw_paths.append(name)
    withdrawn: list[str] = []
    for relative in withdraw_paths:
        candidate = base / str(relative)
        if not candidate.is_file():
            continue
        try:
            body = candidate.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if _ENGINE_STENCIL_RE.search(body) is None:
            continue
        try:
            candidate.unlink()
            withdrawn.append(str(relative))
        except OSError:
            continue
    if withdrawn:
        contract_scaffold["withdrawn"] = withdrawn

    files, file_count, findings = collect_upload_files(base)

    # Repair before judging. Upload does not reject: a refusal hands the author a
    # list of field names and lets them guess the house format, and the measured
    # result of that policy is `capability-eval-plan.json` present on 4% of live
    # releases and `mcp-policy.json` on 50% — both marked required since the
    # contract was written. Anything derivable from what the package already says
    # gets written here; only a defect that cannot be fixed without inventing a
    # fact or deleting the author's content still blocks. Every repair is recorded
    # and surfaced, exactly like the lines the content guard strips.
    repairs = repair_package(base, findings + validate_routing_card_for_upload(base, visibility=visibility)["findings"]
                             + validate_public_profile_for_upload(base, visibility))
    if repairs:
        # Re-read from disk: the repair rewrote the card and the manifest, so every
        # finding derived from them has to be recomputed rather than filtered. A
        # filter would leave a stale blocker that the package no longer has.
        files, file_count, findings = collect_upload_files(base)

    # Compile the resume LAST, after every repair has run, so it describes what is
    # actually about to ship rather than what arrived. Without this call the whole
    # brief pipeline is dead code: an audit of the shipped tree found
    # `.agentlas/brief.json` on 0 of 186 packages because nothing ever invoked the
    # compiler. It is deterministic and reads only files already in the package, so
    # it cannot fail the upload — a package that yields a thin brief gets a thin
    # brief, and `provenance` says which fields were absent rather than guessing.
    # LAST write before the hash. Every earlier pass - scaffold, derive, coerce,
    # redact, repair, brief - can still change what ships, so recording the
    # card's `source.package_hash` before them left it describing a package that
    # no longer existed, and the first upload of a package the engine touched
    # disagreed with every upload after it.
    # Card first, wizard second. The card refresh WRITES the routing card, so a
    # wizard that ran before it hashed a package whose card was about to change,
    # and `agentlas.json` ended up describing a state that never shipped. The
    # wizard is the last writer, so it must also be the last hasher.
    # Same ordering rule as the comment above states for scaffold/derive/coerce/
    # redact/repair: A2A/tools/permissions/hooks/provenance.json must be in
    # their FINAL form before the routing card is refreshed, because the
    # routing card embeds `source.package_hash` — a hash of the tree AT THAT
    # MOMENT. Generating these afterward left that embedded hash (and, one
    # level up, the wizard's real packageHash) describing a package that was
    # about to grow five more files, so the bootstrap upload (those files
    # created here for the first time) disagreed with every upload after it,
    # once those files already existed. Measured via
    # test_local_source_hash_and_cloud_artifact_hash_have_explicit_distinct_contracts.
    if write_manifest:
        refresh_generated_projections(base)
    routing_meta = refresh_routing_card_metadata(base)
    if write_manifest:
        refresh_manifest_skills(base)
    _repair_mcp_policy_file(base, findings, write=write_manifest)
    setup_wizard = run_setup_wizard(base, package_name, write=write_manifest)
    if write_manifest:
        brief_findings = write_offer_brief(base)
        findings.extend(brief_findings)
    files, file_count, _ = collect_upload_files(base)

    # Build, package, and upload must enforce the same artifact contract. The
    # standalone build verifier already rejects missing memory maps, I/O
    # schemas, malformed identity cards, and incomplete routing résumés; upload
    # previously skipped that verifier entirely, so every one of those broken
    # shapes could still become the active Cloud release. Run the shared
    # machine-readable contract after deterministic repair and brief
    # compilation. Remaining gaps need author/model facts, so they are exact
    # blockers rather than invented auto-fills.
    contract_mode = "team" if _infer_kind(base) == "team" else "single"
    contract_report = verify_package_contract(base, mode=contract_mode)
    # 로컬 verify 는 스키마 검증기(jsonschema)가 없는 환경에서 '축소 검증' 경고로
    # 지나가지만, 발행은 다르다 — 스키마 검증이 실제로 돌지 않은 패키지를 시장에
    # 내보내지 않는다 (2026-08-24, 신품 맥 실측에서 강등을 넣으며 함께 고정).
    if contract_report.get("schemaValidation") == "unavailable":
        findings.append(
            _finding(
                "schema-validation-unavailable",
                "blocker",
                "structure",
                "schema validation did not run in this environment; publishing requires it",
                None,
                "Install jsonschema for the interpreter this CLI runs under (the verify report names it), then rerun the upload.",
            )
        )
    for blocker in contract_report["blockers"]:
        artifact_path = blocker.split(":", 1)[0] if ":" in blocker else None
        # Upload packages the collected file set, not the mutable source tree.
        # Career/Ontology indexing may materialize rebuildable state while
        # generating a public card. collect_upload_files excludes that state,
        # so do not turn an already-removed path into a false upload blocker.
        # The standalone contract verifier still blocks the same path when a
        # Build folder itself is the delivered artifact.
        if artifact_path and is_generated_runtime_path(artifact_path):
            continue
        findings.append(
            _finding(
                "package-contract-incomplete",
                "blocker",
                "structure",
                blocker,
                artifact_path,
                "Repair the named artifact with the package's own facts, then rerun the upload.",
            )
        )

    # Generate a public card only when the package opted in and no card exists.
    # Existing cards are accepted as authored metadata; Career freshness is not
    # an upload policy gate.
    findings.extend(prepare_public_career_card_for_upload(base))
    files, file_count, final_collection_findings = collect_upload_files(base)
    existing_findings = {
        (item.get("id"), item.get("file"), item.get("line"), item.get("message"))
        for item in findings
    }
    for finding in final_collection_findings:
        identity = (
            finding.get("id"),
            finding.get("file"),
            finding.get("line"),
            finding.get("message"),
        )
        if identity not in existing_findings:
            findings.append(finding)
            existing_findings.add(identity)

    if setup_wizard.get("mcpPolicyValidation", {}).get("status") != "valid":
        # `_repair_mcp_policy_file` ran before the wizard and either stripped the
        # forbidden fields or replaced the file with the safe default, so this
        # firing means the deterministic repair itself missed a shape - an engine
        # defect, not an author task (owner rule 2026-08-08: the author is never
        # handed a "fix it yourself" refusal).
        findings.append(
            _finding(
                "mcp-policy-invalid",
                "high",
                "policy",
                "MCP policy still invalid after deterministic auto-repair - engine defect; upload proceeds and the defect is surfaced for the engine team.",
                ".agentlas/mcp-policy.json",
                "No author action needed; the engine repair path must learn this shape.",
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

    # Fit the package to the server's limits before its identity is computed:
    # the hash, fileCount and totalBytes must describe what actually ships.
    files = _trim_upload_files_to_limits(files, findings)
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
    # Carry the author's market-page copy onto the delivered manifest.
    # The upload gate forces every marketplace package to write publicProfile in
    # agentlas.json, and both `_with_localized_listing` here and the register
    # endpoint's own derivation read it from `manifest.publicProfile` — but it
    # was never mapped there, so both silently fell back to the English routing
    # card and the Hub listing showed English boilerplate in the Korean fields.
    # Attached before sanitization so the content guard scans this copy too.
    public_profile = _read_public_profile(base)
    if public_profile:
        manifest["publicProfile"] = public_profile
    if public_career_card:
        manifest["careerGraph"] = public_career_card
    manifest, manifest_findings = sanitize_structured_payload(manifest, "manifest")
    findings.extend(manifest_findings)
    sanitized_line_count = sum(1 for finding in findings if finding["id"].startswith("sanitized-upload-line"))
    manifest["sanitizationApplied"] = sanitized_line_count > 0
    manifest["sanitizedLineCount"] = sanitized_line_count

    bundle = {
        "manifest": manifest,
        # Drop the encoding keys when there is nothing to say. Emitting
        # `"encoding": null` is not the same as omitting it: the register route
        # accepts "gzip", "identity" or absent, and refuses null.
        "files": [
            {key: value for key, value in item.__dict__.items() if value is not None or key not in {"encoding", "encodedBytes"}}
            for item in files
        ],
        "source": {"packagedBy": "hephaestus-runtime", "packagedAt": manifest["createdAt"], "costOwner": "none"},
        "sanitization": {"removedLineCount": sanitized_line_count},
    }
    if public_career_card:
        bundle["careerGraph"] = public_career_card
    # The completion pass leaves a receipt. Without it the caller cannot tell a
    # package that needed eight artifacts derived from one that needed none,
    # and a repair nobody can see is indistinguishable from one that never ran.
    if contract_scaffold:
        # Never the workspace path. The receipt is useful to the author, but it
        # rides inside the published bundle, and `workspace` is an absolute path
        # on whoever ran the upload — the exact leak the career-card test guards.
        # What repaired is the fact worth shipping; where it ran is not.
        bundle["contractScaffold"] = {
            key: value for key, value in contract_scaffold.items() if key != "workspace"
        }
    if repairs:
        # What shipped is not what the author wrote. Say so where the author will
        # see it, not only in a findings list nobody reads.
        bundle["repairs"] = repairs
    # Findings are collected before final policy normalization. Unsupported bytes
    # have already been withheld, so a remaining blocker describes an engine gap
    # in the thinner artifact rather than a permission to ship those bytes.
    remaining = [f for f in findings if f["severity"] == "blocker"]
    # A contract artifact the author has not finished writing is a gap in the
    # listing, not a reason to refuse the upload. The package still works; what
    # is missing is copy a buyer would have liked to read. Refusing here is how
    # `capability-eval-plan.json` ended up on 4% of live releases — the gate said
    # no, and the packages shipped through whatever path did not check.
    #
    # This first pass labels unfinished artifact gaps distinctly. Since
    # 2026-08-08, secrets are masked or withheld
    # in place with receipt findings ("redacted-secret", "redacted-file",
    # "mcp-policy-auto-repaired"), because "remove the value and try again" hands
    # the author work the engine can do deterministically. Other unsupported
    # bytes are withheld and normalized to engine-gap receipts below.
    deferred = [f for f in remaining if _is_unfinished_artifact(f)]
    if deferred:
        deferred_ids = {id(f) for f in deferred}
        remaining = [f for f in remaining if id(f) not in deferred_ids]
        for finding in deferred:
            finding["severity"] = "warning"
            finding["deferred"] = "publishable; the listing is thinner until this is written"
    # Owner rule: upload never hands a refusal back to the author. Anything
    # unsafe or unsupported has already been omitted from `files`; anything
    # derivable has already been repaired. A blocker still standing here is an
    # engine gap receipt about the thinner artifact, not permission to publish
    # the omitted bytes and not a reason to prevent the remaining package from
    # uploading.
    #
    # Owner rule (restated 2026-08-23): upload repairs and conforms, it does not
    # refuse. Anything oversized is withheld with a receipt and the rest ships;
    # `_trim_upload_files_to_limits` drops the least essential files by rank
    # until the package fits. So no size finding is a refusal by policy.
    #
    # What is left here is not policy but arithmetic: after everything droppable
    # is gone, only rank 0 remains — the agent definition, its cards, its skills
    # — and it is still over the ceiling. There is nothing left to repair with,
    # and shipping would publish something that is not the agent (the server
    # refuses it anyway, by code, naming nothing). That single case stays a
    # refusal; both findings are raised only after trimming has run.
    HARD_BLOCK_ID_PREFIXES = (
        "package-size-limit",
        "package-uncompressed-size-limit",
        "file-count-limit",
    )
    def _must_stay_blocked(finding: dict[str, Any]) -> bool:
        return str(finding.get("id", "")).startswith(HARD_BLOCK_ID_PREFIXES)
    engine_gap = [f for f in remaining if not _must_stay_blocked(f)]
    if engine_gap:
        gap_ids = {id(f) for f in engine_gap}
        remaining = [f for f in remaining if id(f) not in gap_ids]
        for finding in engine_gap:
            finding["severity"] = "warning"
            finding["deferred"] = "published with a thinner listing; the engine could not auto-complete this and it is flagged as an engine gap, never handed back to the author to fix"
            finding["engineGap"] = True
    # The remaining package proceeds, but approval must seal what was withheld
    # as well as what shipped. This is recomputed after snapshot-level omissions
    # are added by publish_agent.
    provisional = {"manifest": manifest, "bundle": bundle, "review": {"findings": findings}}
    omissions = _attach_omission_manifest(provisional, base)
    manifest = provisional["manifest"]
    bundle = provisional["bundle"]
    # Review verdict/summary must reflect the FINAL severities, computed after
    # secret redaction and artifact deferral have run. Building it earlier froze
    # a "9 blocker(s) / fail" string onto a package whose findings had all been
    # softened to warnings — the summary lied and the fail verdict could gate a
    # downstream that trusts it. static_review reads the same mutated list, so
    # calling it here makes the verdict match what actually ships.
    review = static_review(findings)
    status = "blocked" if remaining else "ready"
    return {
        "status": status,
        "folder": str(base),
        "manifest": manifest,
        "bundle": bundle,
        "review": review,
        "routing": routing,
        "routingMetadata": routing_meta,
        "summary": (
            "Blocked by package review."
            if status == "blocked"
            else (
                f"Ready: {manifest['slug']} (content guard removed {sanitized_line_count} line(s))."
                if sanitized_line_count
                else (
                    f"Ready: {manifest['slug']} ({len(omissions)} source item(s) omitted and receipt-bound)."
                    if omissions
                    else f"Ready: {manifest['slug']}."
                )
            )
        ),
    }


# Written by Desktop when it restores a Cloud package into a local folder.
# Shared filename, deliberately: the two products have to agree on it or the
# lineage is invisible to whichever one did not write it.
_RESTORE_MARKER = ".agentlas-cloud-package.json"


def _read_restore_fork(base: Path) -> dict[str, Any] | None:
    """Fork lineage from the restore marker, or None when this is original work.

    A malformed or unreadable marker returns None rather than raising. The
    marker is not the security boundary -- the server checks are -- and failing
    an upload over a corrupt local file would block ordinary work for no gain.
    """
    marker = base / _RESTORE_MARKER
    try:
        raw = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    fork = raw.get("fork") if isinstance(raw, dict) else None
    return fork if isinstance(fork, dict) else None


def _dry_run_summary(packaged: dict[str, Any]) -> str:
    """Never report a bare pass when the package that would ship is not the
    package the author wrote.

    The content guard removes lines it scores as high severity, and the dry run
    used to answer "Dry run passed" while `sanitizationApplied` was true — an
    author could publish an agent whose method had silently lost steps, triggers,
    or benchmark cases. Deleted content and a review that still wants a human
    both belong in the one line the caller actually reads.
    """

    manifest = packaged.get("manifest") or {}
    review = packaged.get("review") or {}
    slug = manifest.get("slug")
    notes: list[str] = []
    removed = manifest.get("sanitizedLineCount") or 0
    if manifest.get("sanitizationApplied") or removed:
        notes.append(
            f"content guard removed {removed} line(s) — the uploaded package differs from your source; "
            "review the flagged findings and rewrite those lines before publishing"
        )
    verdict = review.get("verdict")
    if verdict and verdict not in {"pass", "passed", "ok"}:
        notes.append(f"package review verdict: {verdict}")
    omissions = (packaged.get("bundle") or {}).get("omissions") or []
    if omissions:
        paths = [str(item.get("path") or "unknown") for item in omissions[:3]]
        suffix = "" if len(omissions) <= 3 else f" and {len(omissions) - 3} more"
        notes.append(
            f"{len(omissions)} source item(s) were omitted and receipt-bound: "
            f"{', '.join(paths)}{suffix}"
        )
    if not notes:
        return f"Dry run passed: {slug}."
    return f"Dry run ready: {slug}; " + "; ".join(notes) + "."


def _hash_regular_source(path: Path) -> str | None:
    """Hash one ordinary source file without following links or accepting mutation."""

    try:
        before = path.lstat()
    except OSError:
        return None
    if not stat.S_ISREG(before.st_mode) or stat.S_ISLNK(before.st_mode):
        return None
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        return None
    digest = hashlib.sha256()
    try:
        opened = os.fstat(descriptor)
        if _snapshot_entry(opened, "file") != _snapshot_entry(before, "file"):
            return None
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
        if _snapshot_entry(os.fstat(descriptor), "file") != _snapshot_entry(before, "file"):
            return None
    finally:
        os.close(descriptor)
    return f"sha256:{digest.hexdigest()}"


def _attach_omission_manifest(packaged: dict[str, Any], source_root: Path) -> list[dict[str, Any]]:
    """Bind every named source omission to the package approval receipt.

    Upload remains nonblocking. The binding makes the thinner artifact honest:
    changing omitted regular-file bytes changes the dry-run receipt even when
    the shipped package bytes themselves are unchanged.
    """

    bundle = packaged.get("bundle") or {}
    shipped = {
        str(item.get("path") or "")
        for item in bundle.get("files") or []
        if isinstance(item, dict)
    }
    findings = (packaged.get("review") or {}).get("findings") or []
    omissions: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        omitted_digest = str(finding.get("omittedDigest") or "")
        if (
            str(finding.get("id") or "").startswith("snapshot-entry-budget-")
            and re.fullmatch(r"sha256:[0-9a-f]{64}", omitted_digest)
        ):
            evidence_scope = {
                "path": "<snapshot-tail>",
                "reason": "snapshot-entry-budget",
                "category": "package-omission",
                "sourceSha256": omitted_digest,
                "omittedEntryCount": int(finding.get("omittedEntryCount") or 0),
                "omittedBytes": int(finding.get("omittedBytes") or 0),
            }
            evidence = json.dumps(
                evidence_scope,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            omissions.append(
                {
                    **evidence_scope,
                    "evidenceSha256": f"sha256:{hashlib.sha256(evidence).hexdigest()}",
                }
            )
            continue
        raw_path = finding.get("file")
        if not isinstance(raw_path, str) or not raw_path.strip():
            continue
        relative = raw_path.strip().replace("\\", "/")
        if relative in shipped:
            continue
        reason = str(finding.get("id") or "package-omission")
        key = (relative, reason)
        if key in seen:
            continue
        seen.add(key)
        source_sha256: str | None = None
        candidate = Path(relative)
        if not candidate.is_absolute() and ".." not in candidate.parts:
            source_sha256 = _hash_regular_source(source_root / candidate)
        category = str(finding.get("category") or "package-omission")
        if source_sha256 is None and category != "package-omission":
            # A missing desired contract file is an engine gap, not omitted
            # source input. Keep it in findings without misreporting it here.
            continue
        evidence_scope = {
            "path": relative,
            "reason": reason,
            "category": category,
            "sourceSha256": source_sha256,
        }
        evidence = json.dumps(
            evidence_scope,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        omissions.append({
            **evidence_scope,
            "evidenceSha256": f"sha256:{hashlib.sha256(evidence).hexdigest()}",
        })
    omissions.sort(key=lambda item: (str(item["path"]), str(item["reason"])))
    canonical = json.dumps(
        omissions,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    omission_digest = f"sha256:{hashlib.sha256(canonical).hexdigest()}"
    bundle["omissions"] = omissions
    bundle["omissionDigest"] = omission_digest
    packaged["bundle"] = bundle
    manifest = packaged.get("manifest") or {}
    manifest["omissionCount"] = len(omissions)
    manifest["omissionDigest"] = omission_digest
    snapshot_tail = next(
        (item for item in omissions if item.get("reason") == "snapshot-entry-budget"),
        None,
    )
    if snapshot_tail is not None:
        manifest["snapshotOmittedEntryCount"] = snapshot_tail["omittedEntryCount"]
        manifest["snapshotOmittedBytes"] = snapshot_tail["omittedBytes"]
        manifest["snapshotOmissionDigest"] = snapshot_tail["sourceSha256"]
    packaged["manifest"] = manifest
    return omissions
    return f"Dry run completed with warnings: {slug} — " + "; ".join(notes)


def _read_regular_file(
    path: Path | str, expected: os.stat_result, *, directory_fd: int | None = None
) -> bytes:
    """Read one file without following a last-moment symlink or inode swap."""

    path_name = Path(path).name
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags, dir_fd=directory_fd)
    except OSError as exc:
        raise UploadError(f"Unsafe or unreadable package file: {path_name}", code="unsafe_package_tree") from exc
    try:
        opened = os.fstat(descriptor)
        if _snapshot_entry(opened, "file") != _snapshot_entry(expected, "file"):
            raise UploadError(
                f"Package file changed or crossed a filesystem boundary while being read: {path_name}",
                code="unsafe_package_tree",
            )
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            raw = handle.read(expected.st_size + 1)
        if len(raw) != expected.st_size:
            raise UploadError(
                f"Package file changed while being read: {path_name}",
                code="unsafe_package_tree",
            )
        return raw
    finally:
        os.close(descriptor)


def _snapshot_entry(metadata: os.stat_result, kind: str) -> SnapshotEntry:
    return SnapshotEntry(
        kind=kind,
        mode=stat.S_IMODE(metadata.st_mode),
        device=metadata.st_dev,
        inode=metadata.st_ino,
        links=metadata.st_nlink,
        size=metadata.st_size,
        modified_ns=metadata.st_mtime_ns,
        changed_ns=metadata.st_ctime_ns,
    )


def _open_snapshot_root(source: Path) -> tuple[int, os.stat_result]:
    root_meta = source.lstat()
    if not stat.S_ISDIR(root_meta.st_mode) or stat.S_ISLNK(root_meta.st_mode):
        raise UploadError("Upload source must be an ordinary directory.", code="unsafe_package_tree")
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(source, flags)
    except OSError as exc:
        raise UploadError("Upload source changed while being opened.", code="unsafe_package_tree") from exc
    opened = os.fstat(descriptor)
    if _snapshot_entry(opened, "directory") != _snapshot_entry(root_meta, "directory"):
        os.close(descriptor)
        raise UploadError("Upload source changed while being opened.", code="unsafe_package_tree")
    return descriptor, opened


_SNAPSHOT_TRUNCATED = "__agentlas_snapshot_truncated__"


def _hash_snapshot_file(
    path_name: str, expected: os.stat_result, *, directory_fd: int
) -> str:
    """Hash an omitted regular file without following links or accepting mutation."""

    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path_name, flags, dir_fd=directory_fd)
    except OSError as exc:
        raise UploadError(
            f"Unsafe or unreadable omitted package file: {path_name}",
            code="unsafe_package_tree",
        ) from exc
    digest = hashlib.sha256()
    try:
        opened = os.fstat(descriptor)
        if _snapshot_entry(opened, "file") != _snapshot_entry(expected, "file"):
            raise UploadError(
                f"Omitted package file changed while being hashed: {path_name}",
                code="unsafe_package_tree",
            )
        remaining = expected.st_size
        while remaining:
            block = os.read(descriptor, min(1024 * 1024, remaining))
            if not block:
                raise UploadError(
                    f"Omitted package file changed while being hashed: {path_name}",
                    code="unsafe_package_tree",
                )
            digest.update(block)
            remaining -= len(block)
        if os.read(descriptor, 1):
            raise UploadError(
                f"Omitted package file changed while being hashed: {path_name}",
                code="unsafe_package_tree",
            )
        if _snapshot_entry(os.fstat(descriptor), "file") != _snapshot_entry(expected, "file"):
            raise UploadError(
                f"Omitted package file changed while being hashed: {path_name}",
                code="unsafe_package_tree",
            )
    finally:
        os.close(descriptor)
    return f"sha256:{digest.hexdigest()}"


def _capture_snapshot_inventory(
    source: Path,
) -> tuple[dict[str, SnapshotEntry], SnapshotTailCommitment]:
    """Capture shipped entries plus a deterministic commitment to the omitted tail."""

    inventory: dict[str, SnapshotEntry] = {}
    walked = 0
    total_bytes = 0
    truncated = False
    omitted_count = 0
    omitted_bytes = 0
    omitted_digest = hashlib.sha256()

    def bind_omitted(
        relative: str,
        metadata: os.stat_result,
        *,
        directory_fd: int,
        entry_name: str,
    ) -> None:
        nonlocal omitted_count, omitted_bytes
        if stat.S_ISLNK(metadata.st_mode):
            kind = "symlink"
            try:
                target = os.readlink(entry_name, dir_fd=directory_fd)
            except OSError as exc:
                raise UploadError(
                    f"Could not inspect omitted package link: {relative}",
                    code="unsafe_package_tree",
                ) from exc
            byte_digest = f"sha256:{hashlib.sha256(os.fsencode(target)).hexdigest()}"
        elif stat.S_ISDIR(metadata.st_mode):
            kind = "directory"
            byte_digest = None
        elif stat.S_ISREG(metadata.st_mode):
            kind = "file" if metadata.st_nlink == 1 else "hardlink"
            byte_digest = _hash_snapshot_file(
                entry_name,
                metadata,
                directory_fd=directory_fd,
            )
            omitted_bytes += metadata.st_size
        else:
            kind = "special"
            byte_digest = None
        record = {
            "path": relative,
            "kind": kind,
            "mode": stat.S_IMODE(metadata.st_mode),
            "bytes": metadata.st_size if stat.S_ISREG(metadata.st_mode) else 0,
            "byteDigest": byte_digest,
        }
        omitted_digest.update(
            json.dumps(
                record,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        omitted_digest.update(b"\n")
        omitted_count += 1

    def scan_directory(
        directory_fd: int,
        relative_parts: tuple[str, ...],
        *,
        parent_withheld: bool = False,
    ) -> None:
        nonlocal walked, total_bytes, truncated
        try:
            iterator = os.scandir(directory_fd)
        except OSError as exc:
            location = "/".join(relative_parts) or "."
            raise UploadError(f"Could not read package directory: {location}", code="unsafe_package_tree") from exc
        with iterator:
            entries = sorted(iterator, key=lambda item: os.fsencode(item.name))
            for entry in entries:
                if entry.name in SKIP_DIRS:
                    continue
                walked += 1
                parts = (*relative_parts, entry.name)
                relative = Path(*parts).as_posix()
                try:
                    metadata = entry.stat(follow_symlinks=False)
                except OSError as exc:
                    raise UploadError(f"Could not inspect package path: {relative}", code="unsafe_package_tree") from exc
                withheld = parent_withheld or walked > MAX_WALKED_ENTRIES
                if withheld:
                    truncated = True
                    bind_omitted(
                        relative,
                        metadata,
                        directory_fd=directory_fd,
                        entry_name=entry.name,
                    )
                    if stat.S_ISDIR(metadata.st_mode) and not stat.S_ISLNK(metadata.st_mode):
                        expected = _snapshot_entry(metadata, "directory")
                        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
                        try:
                            child_fd = os.open(entry.name, flags, dir_fd=directory_fd)
                        except OSError as exc:
                            raise UploadError(
                                f"Package directory changed while being read: {relative}",
                                code="unsafe_package_tree",
                            ) from exc
                        try:
                            if _snapshot_entry(os.fstat(child_fd), "directory") != expected:
                                raise UploadError(
                                    f"Package directory changed while being read: {relative}",
                                    code="unsafe_package_tree",
                                )
                            scan_directory(child_fd, parts, parent_withheld=True)
                        finally:
                            os.close(child_fd)
                    continue
                if stat.S_ISLNK(metadata.st_mode):
                    inventory[relative] = _snapshot_entry(metadata, "ignored-symlink")
                    continue
                if stat.S_ISDIR(metadata.st_mode):
                    expected = _snapshot_entry(metadata, "directory")
                    inventory[relative] = expected
                    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
                    try:
                        child_fd = os.open(entry.name, flags, dir_fd=directory_fd)
                    except OSError as exc:
                        raise UploadError(
                            f"Package directory changed while being read: {relative}",
                            code="unsafe_package_tree",
                        ) from exc
                    try:
                        if _snapshot_entry(os.fstat(child_fd), "directory") != expected:
                            raise UploadError(
                                f"Package directory changed while being read: {relative}",
                                code="unsafe_package_tree",
                            )
                        scan_directory(child_fd, parts)
                    finally:
                        os.close(child_fd)
                    continue
                if not stat.S_ISREG(metadata.st_mode):
                    inventory[relative] = _snapshot_entry(metadata, "ignored-special-file")
                    continue
                if metadata.st_nlink != 1:
                    inventory[relative] = _snapshot_entry(metadata, "ignored-hardlink")
                    continue
                total_bytes += metadata.st_size
                if total_bytes > MAX_SNAPSHOT_BYTES:
                    inventory[relative] = _snapshot_entry(metadata, "ignored-snapshot-byte-budget")
                    continue
                inventory[relative] = _snapshot_entry(metadata, "file")

    root_fd, root_meta = _open_snapshot_root(source)
    inventory["."] = _snapshot_entry(root_meta, "directory")
    try:
        scan_directory(root_fd, ())
    finally:
        os.close(root_fd)
    if truncated:
        inventory[_SNAPSHOT_TRUNCATED] = SnapshotEntry(
            kind="ignored-entry-budget",
            mode=0,
            device=0,
            inode=0,
            links=0,
            size=0,
            modified_ns=0,
            changed_ns=0,
        )
    commitment = SnapshotTailCommitment(
        entry_count=omitted_count,
        regular_file_bytes=omitted_bytes,
        digest=f"sha256:{omitted_digest.hexdigest()}",
    )
    return inventory, commitment


def _copy_snapshot_inventory(source: Path, destination: Path, inventory: dict[str, SnapshotEntry]) -> None:
    seen = {"."}
    destination.mkdir(mode=0o700)

    def copy_directory(directory_fd: int, target: Path, relative_parts: tuple[str, ...]) -> None:
        try:
            iterator = os.scandir(directory_fd)
        except OSError as exc:
            location = "/".join(relative_parts) or "."
            raise UploadError(f"Could not read package directory: {location}", code="unsafe_package_tree") from exc
        with iterator:
            for entry in iterator:
                if entry.name in SKIP_DIRS:
                    continue
                parts = (*relative_parts, entry.name)
                relative = Path(*parts).as_posix()
                expected = inventory.get(relative)
                if expected is None:
                    if _SNAPSHOT_TRUNCATED in inventory:
                        continue
                    raise UploadError(
                        f"Package entry appeared while the snapshot was being copied: {relative}",
                        code="unsafe_package_tree",
                    )
                try:
                    metadata = entry.stat(follow_symlinks=False)
                except OSError as exc:
                    raise UploadError(f"Could not inspect package path: {relative}", code="unsafe_package_tree") from exc
                if expected.kind.startswith("ignored-"):
                    if _snapshot_entry(metadata, expected.kind) != expected:
                        raise UploadError(
                            f"Omitted package entry changed while the snapshot was being copied: {relative}",
                            code="unsafe_package_tree",
                        )
                    seen.add(relative)
                    continue
                if stat.S_ISDIR(metadata.st_mode):
                    current = _snapshot_entry(metadata, "directory")
                elif stat.S_ISREG(metadata.st_mode):
                    current = _snapshot_entry(metadata, "file")
                else:
                    raise UploadError(
                        f"Package entry changed type while the snapshot was being copied: {relative}",
                        code="unsafe_package_tree",
                    )
                if current != expected:
                    raise UploadError(
                        f"Package entry changed while the snapshot was being copied: {relative}",
                        code="unsafe_package_tree",
                    )
                seen.add(relative)
                target_path = target / entry.name
                if expected.kind == "directory":
                    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
                    try:
                        child_fd = os.open(entry.name, flags, dir_fd=directory_fd)
                    except OSError as exc:
                        raise UploadError(
                            f"Package directory changed while being copied: {relative}",
                            code="unsafe_package_tree",
                        ) from exc
                    try:
                        if _snapshot_entry(os.fstat(child_fd), "directory") != expected:
                            raise UploadError(
                                f"Package directory changed while being copied: {relative}",
                                code="unsafe_package_tree",
                            )
                        target_path.mkdir(mode=expected.mode or 0o700)
                        copy_directory(child_fd, target_path, parts)
                    finally:
                        os.close(child_fd)
                    continue
                if expected.size > MAX_FILE_BYTES:
                    with target_path.open("wb") as handle:
                        handle.truncate(expected.size)
                else:
                    target_path.write_bytes(
                        _read_regular_file(entry.name, metadata, directory_fd=directory_fd)
                    )
                target_path.chmod(expected.mode)

    root_fd, root_meta = _open_snapshot_root(source)
    try:
        if _snapshot_entry(root_meta, "directory") != inventory.get("."):
            raise UploadError("Upload source changed before it could be copied.", code="unsafe_package_tree")
        copy_directory(root_fd, destination, ())
    finally:
        os.close(root_fd)
    missing = sorted(set(inventory) - seen - {_SNAPSHOT_TRUNCATED})
    if missing:
        raise UploadError(
            f"Package entries disappeared while the snapshot was being copied: {missing[0]}",
            code="unsafe_package_tree",
        )


def _snapshot_package_source(source: Path, destination: Path) -> list[dict[str, Any]]:
    """Copy a bounded, link-free snapshot and return omission receipts.

    Unsupported filesystem entries are withheld rather than turning upload into
    a user-facing refusal. The source is still descriptor-anchored and checked
    for concurrent mutation; only ordinary files copied into the snapshot can
    reach the package hash or the server.
    """

    inventory, tail_commitment = _capture_snapshot_inventory(source)
    _copy_snapshot_inventory(source, destination, inventory)
    if _capture_snapshot_inventory(source) != (inventory, tail_commitment):
        raise UploadError(
            "Upload source changed while the package snapshot was being copied.",
            code="unsafe_package_tree",
        )
    omissions: list[dict[str, Any]] = []
    for relative, entry in sorted(inventory.items()):
        if relative == _SNAPSHOT_TRUNCATED:
            finding = _finding(
                    "snapshot-entry-budget",
                    "warning",
                    "size",
                    (
                        f"{tail_commitment.entry_count} entries after the "
                        f"{MAX_WALKED_ENTRIES}-entry snapshot budget were withheld."
                    ),
                    None,
                    "Engine receipt: the bounded package was uploaded; split large source trees for complete delivery.",
                )
            finding.update(
                {
                    "omittedEntryCount": tail_commitment.entry_count,
                    "omittedBytes": tail_commitment.regular_file_bytes,
                    "omittedDigest": tail_commitment.digest,
                }
            )
            omissions.append(finding)
        elif entry.kind.startswith("ignored-"):
            omissions.append(
                _finding(
                    entry.kind,
                    "warning",
                    "package-omission",
                    "Unsupported or out-of-budget filesystem entry was withheld from the uploaded copy.",
                    relative,
                    "Engine receipt: this path did not ship and did not block the remaining package.",
                )
            )
    return omissions


def _pin_snapshot_agent_identity(snapshot: Path, fallback_name: str) -> None:
    """Give first-run snapshots a repeatable ID without writing it to source."""

    manifest_path = snapshot / "agentlas.json"
    manifest = _read_json(manifest_path) or {}
    if str(manifest.get("agentId") or "").strip():
        return
    identity_seed = str(manifest.get("slug") or manifest.get("name") or fallback_name).strip().lower()
    digest = hashlib.sha256(f"agentlas-upload-agent-id-v1\0{identity_seed}".encode("utf-8")).hexdigest()
    manifest["agentId"] = f"agt_{digest[:32]}"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _normalized_sha256(value: Any) -> str:
    text = str(value or "").strip().lower()
    return text[7:] if text.startswith("sha256:") else text


def _normalize_destination_base_url(base_url: str | None) -> str:
    try:
        return normalize_base_url(base_url)
    except AgentlasAuthError as exc:
        raise UploadError(str(exc), code="invalid_destination") from exc


def _upload_receipt(manifest: dict[str, Any], base_url: str) -> dict[str, Any]:
    scope = {
        "schemaVersion": "agentlas.upload-receipt.v1",
        "packageHash": f"sha256:{_normalized_sha256(manifest.get('packageHash'))}",
        "packageHashVersion": str(manifest.get("packageHashVersion") or ""),
        "slug": str(manifest.get("slug") or ""),
        "visibility": str(manifest.get("visibility") or ""),
        "destinationBaseUrl": base_url,
        "omissionCount": int(manifest.get("omissionCount") or 0),
        "omissionDigest": str(manifest.get("omissionDigest") or ""),
        "snapshotOmittedEntryCount": int(manifest.get("snapshotOmittedEntryCount") or 0),
        "snapshotOmittedBytes": int(manifest.get("snapshotOmittedBytes") or 0),
        "snapshotOmissionDigest": str(manifest.get("snapshotOmissionDigest") or ""),
    }
    canonical = json.dumps(scope, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {**scope, "receipt": f"sha256:{hashlib.sha256(canonical).hexdigest()}"}


def _without_local_upload_paths(value: Any, local_paths: tuple[str, ...]) -> Any:
    """Copy server-bound metadata while replacing host-local source paths."""

    if isinstance(value, dict):
        return {
            key: _without_local_upload_paths(item, local_paths)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_without_local_upload_paths(item, local_paths) for item in value]
    if isinstance(value, tuple):
        return tuple(_without_local_upload_paths(item, local_paths) for item in value)
    if isinstance(value, str):
        sanitized = value
        for local_path in local_paths:
            sanitized = sanitized.replace(local_path, "<local-upload-root>")
        return sanitized
    return value


def _normalized_upload_receipt(value: Any) -> str:
    text = str(value or "").strip().lower()
    return text if text.startswith("sha256:") else f"sha256:{text}"


def _attest_registration(
    registration: dict[str, Any], manifest: dict[str, Any], visibility: str
) -> dict[str, Any]:
    """Fail closed unless the server proves the exact release it registered."""

    if not isinstance(registration, dict):
        raise UploadError("Registration response was not an object.", code="registration_attestation_failed")
    # ★ 응답의 visibility 는 요청 어휘가 아니라 **저장 스코프 어휘**다.
    #     요청 marketplace  → 응답 marketplace   (그대로)
    #     요청 private-link → 응답 owner-private (번역됨)
    #   서버가 한쪽만 번역하는 비대칭이라, 이 검증은 marketplace 만 통과시키고
    #   비공개 저장은 항상 실패시켰다 — 2026-08-14(v1.2.1)에 이 함수가 들어온 뒤
    #   모든 `--visibility private-link` 발행이 **서버가 이미 쓴 뒤에** 실패로
    #   보고됐다. Desktop 클라이언트는 처음부터 같은 매핑을 하고 있었고,
    #   그래서 Desktop 만 멀쩡했다.
    #
    #   서버 값을 바꾸면 이미 배포된 Desktop 이 전부 깨지므로, 맞추는 쪽은 여기다.
    #   양쪽 어휘를 다 받는다: 서버가 나중에 요청 어휘를 그대로 돌려주게 되어도
    #   이 검증은 계속 맞다.
    accepted_visibility = {
        "marketplace": {"marketplace"},
        "private-link": {"private-link", "owner-private"},
    }.get(visibility, {visibility})
    if registration.get("visibility") not in accepted_visibility:
        raise UploadError(
            "Registration response did not attest visibility={!r} (got {!r}).".format(
                visibility, registration.get("visibility")
            ),
            code="registration_attestation_failed",
        )
    expected = {
        "status": "registered",
        "slug": str(manifest.get("slug") or ""),
    }
    for field, value in expected.items():
        if registration.get(field) != value:
            raise UploadError(
                f"Registration response did not attest {field}={value!r}.",
                code="registration_attestation_failed",
            )
    # THE SERVER MAY STORE LESS THAN IT RECEIVED, AND THAT IS NOT A FAILED PROOF.
    #
    #   Registration verifies the submitted hash, then withholds any file its own
    #   scanner judged credential-like and stores the remainder under a new hash
    #   (`packageHash` != `submittedPackageHash`, with `uploadReceipt.omissions`
    #   naming every dropped path). Comparing only against `packageHash` turned
    #   that documented repair into `registration_attestation_failed` AFTER the
    #   listing was live: the agent was on the Hub, searchable and callable,
    #   while the publisher was told the upload failed — and everything after
    #   attestation, pricing included, never ran.
    #
    #   What attestation is for is proof that the server saw exactly this
    #   package. `submittedPackageHash` is that proof, so either hash matching
    #   ours satisfies it. Neither matching still fails closed.
    submitted = _normalized_sha256(manifest.get("packageHash"))
    stored_hash = _normalized_sha256(registration.get("packageHash"))
    receipt = registration.get("uploadReceipt")
    receipt_submitted = (
        _normalized_sha256(receipt.get("submittedPackageHash"))
        if isinstance(receipt, dict)
        else None
    )
    if stored_hash != submitted and receipt_submitted != submitted:
        raise UploadError(
            "Registration response did not attest the submitted package hash.",
            code="registration_attestation_failed",
        )
    for field in ("agentReleaseId", "releaseVersion"):
        if not isinstance(registration.get(field), str) or not registration[field].strip():
            raise UploadError(
                f"Registration response omitted {field}.", code="registration_attestation_failed"
            )
    digest = str(registration.get("contentDigest") or "")
    if re.fullmatch(r"sha256:[0-9a-fA-F]{64}", digest) is None:
        raise UploadError(
            "Registration response omitted a valid contentDigest.",
            code="registration_attestation_failed",
        )
    return registration


def publish_agent(
    folder: str | Path,
    *,
    slug: str | None = None,
    visibility: str,
    base_url: str | None = None,
    dry_run: bool = False,
    interactive: bool = True,
    expected_package_hash: str | None = None,
    expected_upload_receipt: str | None = None,
    overwrite_cloud_id: str | None = None,
    rent_credits: int | None = None,
    ingest_credits: int | None = None,
    fork_credits: int | None = None,
) -> dict[str, Any]:
    if visibility not in {"marketplace", "private-link"}:
        raise UploadError("Choose exactly one upload visibility: marketplace or private-link.", code="visibility_required")
    # Checked before anything is packaged or uploaded. A ceiling violation found
    # after the upload would leave a live free listing and an error message,
    # which reads as "the publish failed" when it did not.
    price_patch: dict[str, int] = {}
    if visibility == "marketplace":
        try:
            price_patch = build_patch(
                rent=rent_credits, ingest=ingest_credits, fork=fork_credits
            )
        except PriceError as exc:
            raise UploadError(str(exc), code=f"price_{exc.code}") from exc
    elif rent_credits is not None or ingest_credits is not None or fork_credits is not None:
        # A private save is not on the Hub and nobody can hire it, so there is
        # nothing for a price to apply to. Refused rather than ignored: silently
        # dropping a number someone typed is how they find out months later.
        raise UploadError(
            "Prices apply to a public Hub listing. Use --visibility marketplace, or drop the price flags.",
            code="price_requires_marketplace",
        )

    destination_base_url = _normalize_destination_base_url(base_url)
    requested_source = Path(folder).expanduser()
    source_link_resolved = requested_source.is_symlink()
    source = requested_source.resolve()
    if not source.is_dir():
        raise UploadError(f"agent folder not found: {folder}", code="agent_folder_not_found")
    with tempfile.TemporaryDirectory(prefix="hephaestus-upload.") as temporary:
        snapshot = Path(temporary) / "package"
        snapshot_omissions = _snapshot_package_source(source, snapshot)
        _pin_snapshot_agent_identity(snapshot, source.name)
        packaged = package_agent(snapshot, slug=slug, visibility=visibility, write_manifest=True)
        if source_link_resolved:
            snapshot_omissions.insert(
                0,
                _finding(
                    "source-symlink-resolved",
                    "warning",
                    "source-selection",
                    "The selected upload root was a symlink; its resolved directory was snapshotted.",
                    ".",
                    "Engine receipt: only the resolved directory contents were considered.",
                ),
            )
        if snapshot_omissions:
            packaged["review"]["findings"].extend(snapshot_omissions)
            packaged["review"] = static_review(packaged["review"]["findings"])
            packaged["bundle"]["snapshotOmissions"] = snapshot_omissions
        omissions = _attach_omission_manifest(packaged, source)
        if omissions and packaged.get("status") != "blocked":
            packaged["summary"] = (
                f"Ready: {packaged['manifest']['slug']} "
                f"({len(omissions)} source item(s) omitted and receipt-bound)."
            )
        packaged["folder"] = str(source)
        packaged["sourceSelection"] = {
            "selected": str(requested_source),
            "resolved": str(source),
            "symlinkResolved": source_link_resolved,
        }
        actual_hash = str(packaged.get("manifest", {}).get("packageHash") or "")
        upload_receipt = _upload_receipt(packaged.get("manifest") or {}, destination_base_url)
        packaged["uploadReceipt"] = upload_receipt
        if expected_package_hash and _normalized_sha256(expected_package_hash) != _normalized_sha256(actual_hash):
            raise UploadError(
                f"Package hash changed: expected {_normalized_sha256(expected_package_hash)}, got {actual_hash}.",
                code="package_hash_mismatch",
            )
        if expected_upload_receipt and _normalized_upload_receipt(expected_upload_receipt) != upload_receipt["receipt"]:
            raise UploadError(
                "Upload approval receipt does not match the package hash, visibility, slug, and destination.",
                code="upload_receipt_mismatch",
            )
        if not dry_run and expected_package_hash and not expected_upload_receipt:
            raise UploadError(
                "A package hash alone does not bind the approved destination and slug. "
                "Run one dry-run and pass its uploadReceipt.receipt with --expected-upload-receipt.",
                code="upload_receipt_required",
            )
        if packaged["status"] == "blocked":
            packaged["registration"] = None
            return packaged
        if dry_run:
            packaged["status"] = "dry-run"
            packaged["registration"] = None
            packaged["summary"] = _dry_run_summary(packaged)
            return packaged

        local_paths = tuple(
            sorted(
                {
                    str(source),
                    *(str(requested_source.resolve()) for _ in (0,)),
                    *(str(requested_source) for _ in (0,) if requested_source.is_absolute()),
                },
                key=len,
                reverse=True,
            )
        )
        server_manifest = _without_local_upload_paths(packaged["manifest"], local_paths)
        server_bundle = _without_local_upload_paths(packaged["bundle"], local_paths)
        server_review = _without_local_upload_paths(packaged["review"], local_paths)
        registration = register_package(
            server_manifest,
            server_bundle,
            server_review,
            visibility=packaged["manifest"]["visibility"],
            base_url=destination_base_url,
            interactive=interactive,
            overwrite_cloud_id=overwrite_cloud_id,
        )
        registration = _attest_registration(registration, packaged["manifest"], visibility)
        # The server withheld files of its own. Say so at the top level: buried
        # in the registration receipt, "your package shipped without these two
        # files" is something no caller reads.
        server_receipt = registration.get("uploadReceipt")
        if isinstance(server_receipt, dict) and server_receipt.get("omissions"):
            packaged["serverWithheld"] = {
                "count": len(server_receipt["omissions"]),
                "paths": [
                    str(item.get("path"))
                    for item in server_receipt["omissions"]
                    if isinstance(item, dict) and item.get("path")
                ],
                "storedPackageHash": server_receipt.get("storedPackageHash"),
                "note": (
                    "The listing is live. These files were withheld by the server's own scan "
                    "and are not part of the stored package."
                ),
            }
    packaged["status"] = "registered"
    packaged["registration"] = registration
    registered_slug = registration.get("slug") or packaged["manifest"]["slug"]

    # Priced only after the listing exists, and never allowed to fail the
    # publish. If this does not go through, the agent is on the Hub and free —
    # the same state every agent published before pricing existed is in — and
    # the result says so instead of claiming the upload broke.
    if price_patch and not dry_run:
        packaged["pricing"] = set_prices(
            registered_slug,
            price_patch,
            base_url=destination_base_url,
            interactive=interactive,
        )
    elif price_patch:
        packaged["pricing"] = {"status": "skipped", "reason": "dry_run", "prices": {}}
    removed_lines = packaged.get("manifest", {}).get("sanitizedLineCount") or 0
    if removed_lines:
        # What shipped is not what the author wrote. Say it at the top level, on
        # the real upload too — after this point the Hub serves the sanitized copy.
        packaged["summary"] = (
            f"Registered {registered_slug} — content guard removed {removed_lines} line(s) from the "
            "uploaded copy; the published package differs from your source"
        )
    else:
        packaged["summary"] = f"Registered {registered_slug}."
    pricing = packaged.get("pricing")
    if isinstance(pricing, dict) and pricing.get("status") == "priced":
        priced = ", ".join(f"{kind} {value}" for kind, value in (pricing.get("prices") or {}).items())
        packaged["summary"] += f" Priced: {priced}."
    elif isinstance(pricing, dict) and pricing.get("status") == "failed":
        # Stated in the summary, not only in a nested field. A pricing failure
        # that only appears three keys deep is a failure nobody reads.
        packaged["summary"] += (
            f" WARNING: the price was NOT set ({pricing.get('reason')}) — "
            "the agent is published and currently free to call."
        )
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



def _korean_dominates(value: str) -> bool:
    """Mirrors the register endpoint's `koreanDominates`
    (AgentsAtlas/app/src/lib/marketplace/localized-listing.ts): counting script
    ranges, not a wordlist, so both sides agree on which locale a line is in.
    """

    hangul = len(re.findall(r"[가-힣]", value))
    if not hangul:
        return False
    return hangul >= 12 or hangul > len(re.findall(r"[A-Za-z]", value))


def _with_localized_listing(manifest: dict[str, Any]) -> dict[str, Any]:
    """Attach the bilingual listing block the marketplace register endpoint requires.

    The endpoint reads `manifest.localized.{titleEn,titleKo,descriptionEn,descriptionKo}`
    and rejects a publish with `localized_metadata_required` when any is missing.
    Packages carry exactly that copy — in an authored or auto-repaired
    `publicProfile` and again as `name/nameKo/summary/summaryKo`
    — but nothing ever mapped it onto the manifest, so a package that passed every
    local gate still failed at registration. This maps it; it never invents copy.
    """
    if not isinstance(manifest, dict):
        return manifest
    existing = manifest.get("localized")
    if isinstance(existing, dict) and all(
        str(existing.get(key) or "").strip()
        for key in ("titleEn", "titleKo", "descriptionEn", "descriptionKo")
    ):
        return manifest
    profile = manifest.get("publicProfile") if isinstance(manifest.get("publicProfile"), dict) else {}
    card = manifest.get("routingCard") if isinstance(manifest.get("routingCard"), dict) else {}

    def pick(*candidates: Any) -> str:
        for value in candidates:
            text = str(value or "").strip()
            if text:
                return text
        return ""

    # The gate also accepts locale-neutral `title`/`description`, so packages
    # exist that carry the author's copy only under those keys. Route it to the
    # locale it is actually written in: Hangul in the English slot is rejected
    # by the endpoint (`titleEn_contains_hangul`), and English in the Korean
    # slot is exactly the substitution this function exists to prevent.
    def en_only(value: Any) -> str:
        text = str(value or "").strip()
        return "" if _korean_dominates(text) else text

    def ko_only(value: Any) -> str:
        text = str(value or "").strip()
        return text if _korean_dominates(text) else ""

    localized = {
        "titleEn": pick(profile.get("titleEn"), en_only(profile.get("title")), card.get("name"), manifest.get("name")),
        "titleKo": pick(
            profile.get("titleKo"), ko_only(profile.get("title")), card.get("name_ko"), card.get("name"), manifest.get("name")
        ),
        "descriptionEn": pick(
            profile.get("descriptionEn"),
            en_only(profile.get("description")),
            card.get("summary"),
            card.get("description"),
            manifest.get("tagline"),
        ),
        "descriptionKo": pick(
            profile.get("descriptionKo"),
            ko_only(profile.get("description")),
            card.get("summary_ko"),
            card.get("summary"),
            manifest.get("tagline"),
        ),
    }
    if not all(localized.values()):
        return manifest
    merged = dict(manifest)
    merged["localized"] = localized
    return merged

def register_package(
    manifest: dict[str, Any],
    bundle: dict[str, Any],
    review: dict[str, Any],
    *,
    visibility: str,
    base_url: str | None = None,
    interactive: bool = True,
    overwrite_cloud_id: str | None = None,
) -> dict[str, Any]:
    base = _normalize_destination_base_url(base_url)
    try:
        token = ensure_access_token(base, interactive=interactive)
    except AgentlasAuthError as exc:
        raise UploadError(str(exc), code="auth_unavailable") from exc
    if not token:
        raise UploadError(
            "Agentlas sign-in is required. Run `bin/hephaestus auth login` first.",
            code="sign_in_required",
        )
    payload = {
        "manifest": _with_localized_listing(manifest),
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
        with same_origin_urlopen(request, timeout=180) as response:
            return json.loads(response.read().decode("utf-8"))

    try:
        return _post()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        if exc.code == 428:
            precondition = _overwrite_precondition_headers(detail)
            if precondition:
                current_cloud_id = precondition["x-agentlas-cloud-id"]
                if not overwrite_cloud_id:
                    raise UploadError(
                        "The destination already contains a different release. "
                        f"Re-run with --overwrite-cloud-id {current_cloud_id} only after confirming that exact target.",
                        code="overwrite_confirmation_required",
                    ) from exc
                if overwrite_cloud_id != current_cloud_id:
                    raise UploadError(
                        "Overwrite authorization does not match the server's current cloud asset.",
                        code="overwrite_target_mismatch",
                    ) from exc
                try:
                    return _post(precondition)
                except urllib.error.HTTPError as retry_exc:
                    retry_detail = retry_exc.read().decode("utf-8", errors="replace")
                    retry_code = _registration_error_code(retry_detail, "registration_http_error")
                    raise UploadError(
                        f"Agentlas Cloud registration failed HTTP {retry_exc.code} after authorized overwrite: {retry_detail[:800]}",
                        code=retry_code,
                    ) from retry_exc
        # The CLI half of the BYOM repair-retry loop: the server never calls a
        # platform LLM during upload, it returns a mismatch list plus the
        # pinned ontology menu. The one reading this message is the
        # submitter's own model driving the upload, so truncating the
        # guidance at an 800-char cap would kill the loop — pass the full,
        # structured message through untouched.
        if exc.code == 422:
            try:
                body = json.loads(detail)
            except ValueError:
                body = None
            if isinstance(body, dict) and body.get("code") == "workforce_resume_incomplete":
                issues = body.get("issues") or []
                guide = body.get("repairGuide") or {}
                menus = guide.get("menus") or {}
                lines = [
                    "Agentlas Cloud found an incomplete agent description and did not upload the broken copy.",
                    "The same hep-build model that made the package should repair it from the package's own capabilities and knowledge files, then retry automatically.",
                    "",
                    "Missing information:",
                    *[f"  - {issue}" for issue in issues],
                    "",
                    str(guide.get("howToRepair") or ""),
                    f"ontologyVersion: {guide.get('ontologyVersion')}",
                ]
                seed_examples = guide.get("seedExamples") or {}
                for key in ("roles", "communities", "skills"):
                    values = seed_examples.get(key) or menus.get(key) or []
                    lines.append(f"{key} examples: {', '.join(str(value) for value in values)}")
                lines.extend([
                    "",
                    "If the package truly does not say what work it performs, ask the user one plain question:",
                    '"What concrete work should this agent complete, and what should the finished result look like?"',
                ])
                raise UploadError("\n".join(lines), code="workforce_resume_incomplete") from exc
        # ★ 중복과 포크는 결함이 아니라 서버의 결정이다 (오너 지시 2026-08-18).
        #   자가수리는 "패키지를 고쳐 다시 올리는 것"(위 422 경로)이지, 거절을
        #   우회해 두 번째 항목을 만들거나 지목하지 않은 항목을 덮어쓰는 것이
        #   아니다. 이 셋은 전부 아래 generic 분기로 떨어져 HTTP 상태와 JSON
        #   원문만 남겼다 — 무엇이 왜 막혔는지 한 줄도 없이.
        refusal = _publication_refusal(exc.code, detail)
        if refusal is not None:
            message, code = refusal
            raise UploadError(message, code=code) from exc
        raise UploadError(
            f"Agentlas Cloud registration failed HTTP {exc.code}: {detail[:800]}",
            code=_registration_error_code(detail, "registration_http_error"),
        ) from exc
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        raise UploadError(f"Agentlas Cloud registration failed: {exc}", code="registration_transport_error") from exc


def _publication_refusal(status: int, detail: str) -> tuple[str, str] | None:
    """A publication the server declined on purpose, in one plain sentence.

    Returns ``(message, code)`` for the refusals that are decisions rather than
    defects, and ``None`` for everything else so the caller keeps its existing
    behaviour. Nothing here is retried, repackaged, renamed, or overwritten:
    a duplicate stays a duplicate and a fork stays a fork.
    """
    # 428 stays with the overwrite-confirmation flow above; everything else is
    # matched on its code so the author reads a sentence instead of an HTTP
    # status and a JSON body. Same set Desktop's result card explains.
    if status == 428:
        return None
    try:
        body = json.loads(detail)
    except (TypeError, ValueError):
        return None
    if not isinstance(body, dict):
        return None
    code = body.get("code")
    conflict = body.get("conflict") if isinstance(body.get("conflict"), dict) else {}
    existing = conflict.get("existingSlug") if isinstance(conflict, dict) else None
    canonical = conflict.get("canonicalSlug") if isinstance(conflict, dict) else None
    named = canonical or existing
    if code == "slug_identity_conflict":
        return (
            "This agent is already in your Agent Cloud"
            + (f' as "{named}"' if isinstance(named, str) and named else "")
            + ", so a second listing for the same agent was not created. Nothing was uploaded. "
            + (
                f'Upload it under "{named}" to update that listing.'
                if isinstance(named, str) and named
                else "Upload it under its existing name to update that listing."
            ),
            "slug_identity_conflict",
        )
    if code in ("cloud_agent_duplicate", "duplicate_hub_package"):
        return (
            "This agent is already listed on the Agentlas Hub"
            + (f' as "{existing}"' if isinstance(existing, str) and existing else "")
            + " by another account. Nothing was uploaded.",
            str(code),
        )
    if code == "cloud_agent_limit_reached":
        used = body.get("usedAgents")
        limit = body.get("limitAgents")
        counts = f" ({used} of {limit} used)" if isinstance(used, int) and isinstance(limit, int) else ""
        return (
            f"Uploading does not spend credits. Your plan's Agent Cloud seats are full{counts}, "
            "and nothing was uploaded. Delete a cloud agent you no longer need, or move to a "
            "larger plan, then upload again.",
            "cloud_agent_limit_reached",
        )
    if code == "cloud_mutations_maintenance":
        return (
            "Writes to Agent Cloud are paused for maintenance. Nothing was uploaded and nothing "
            "changed. Try the same folder again shortly.",
            "cloud_mutations_maintenance",
        )
    if code in (
        "registration_commit_failed",
        "cloud_save_commit_failed",
        "workforce_projection_pending",
        "workforce_identity_missing",
        "base_release_materialization_failed",
    ):
        return (
            "Nothing is wrong with the package — the Cloud side could not finish the write, and "
            "the previous version is still live. Upload the same folder again shortly.",
            str(code),
        )
    if code == "localized_metadata_required":
        return (
            "The Hub listing still needs verified Korean and English title/description text, and "
            "the package could not be completed automatically. Nothing was uploaded. Fill "
            "localized.titleEn/titleKo/descriptionEn/descriptionKo in .agentlas/agent-card.json "
            "and upload again.",
            "localized_metadata_required",
        )
    if code in ("bundle_too_large", "file_limit", "file_too_large", "request_too_large"):
        return (
            "Even after leaving out the less essential files, this package is over the Agent "
            "Cloud size or file-count limit. Nothing was uploaded. Publish just the agent folder, "
            "or split the team into smaller packages.",
            str(code),
        )
    if code == "fork_cannot_publish":
        origin = body.get("originSlug")
        return (
            "This is an installed copy"
            + (f' of "{origin}"' if isinstance(origin, str) and origin else "")
            + ". Run it and staff it into work orders, but the Hub listing belongs to its creator. "
            + "Nothing was uploaded.",
            "fork_cannot_publish",
        )
    return None


def _registration_error_code(detail: str, fallback: str) -> str:
    try:
        body = json.loads(detail)
    except (TypeError, ValueError):
        return fallback
    code = body.get("code") if isinstance(body, dict) else None
    return code if isinstance(code, str) and code else fallback


def refresh_manifest_skills(base: Path) -> dict[str, Any]:
    """Make `agentlas.json` skills[] say what the package actually ships.

    A skill's name IS its `<host>/skills/<name>/SKILL.md` folder name, so the
    folders answer this without guessing. Measured 2026-08-26: a package with
    six skill folders kept them in the manifest only because its build agent
    typed them by hand — nothing derived or checked it, and a package that
    shipped skills while declaring none advertised nothing at all.

    Author intent is preserved: an explicit list is never reordered or trimmed
    here (upload_repair drops ids with no file); only genuinely missing entries
    are added.
    """
    from .networking.card_lint import discover_skill_slugs

    manifest_path = base / "agentlas.json"
    if not manifest_path.is_file():
        return {"updated": False, "reason": "missing_manifest"}
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {"updated": False, "reason": "invalid_manifest"}
    if not isinstance(manifest, dict):
        return {"updated": False, "reason": "invalid_manifest"}

    on_disk = discover_skill_slugs(base)
    declared = manifest.get("skills")
    declared = [str(item) for item in declared] if isinstance(declared, list) else []
    added = [slug for slug in on_disk if slug not in declared]
    if not added:
        return {"updated": False, "skills": declared}
    manifest["skills"] = declared + added
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return {"updated": True, "added": added, "skills": manifest["skills"]}


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
    # A card with no résumé (workforce) block gets filled with a deterministic
    # minimal block — a gate that keeps an auto-built agent from dying at the
    # new standard gate (no model call, preserves any existing block).
    from .networking.card_lint import ensure_workforce_block

    # `base` lets the projector read the package's own skill folders — a skill
    # is named by its `<root>/<name>/SKILL.md` directory, not by whatever the
    # build agent typed into the card.
    ensure_workforce_block(card, base)
    agent_card_path = base / ".agentlas" / "agent-card.json"
    if isinstance(card.get("agent_card_ref"), dict) and agent_card_path.is_file():
        card["agent_card_ref"]["content_hash"] = _sha256_bytes(agent_card_path.read_bytes())
    source = card.get("source") if isinstance(card.get("source"), dict) else {}
    # Use the canonical exclusion rule, not a second hand-written one. This
    # filter listed only `agentlas.json` and the card itself, so the card's hash
    # covered `.agentlas/security-scan.json` - a file that carries a fresh
    # `scannedAt` on every run. The card therefore changed every time it was
    # refreshed, which changed the package, which changed the upload hash.
    # Measured 2026-08-07: `package_agent` returned a different packageHash on
    # its first call and settled only from the second, which breaks the
    # hash-preservation requirement for republishing the corpus.
    #
    # `package_hash_includes` already excludes security-scan.json, brief.json,
    # field-test-report.json, the LLM judgment, and the experience lineage,
    # because those are generated evidence rather than package intent. The card
    # is excluded on top of that: a hash of the package cannot include the file
    # it is being written into.
    source["package_hash"] = package_hash(
        [
            item
            for item in collect_package_files(base)
            if package_hash_includes(item.path)
            and not item.path.endswith(".agentlas/routing-card.json")
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
    # Judge the BEST description across locales, not the first one present.
    # Reading Korean first meant a 36-character Korean line blocked upload even
    # when the English description was complete — the gate exists to guarantee a
    # readable market page, and one adequate locale delivers that. A package may
    # ship English-only; it may not ship an empty market page.
    description, description_field = _best_localized_text(
        public_profile, ("descriptionKo", "descriptionEn", "description")
    )
    if not title or _looks_generic_copy(title):
        findings.append(_finding("public-profile-title", "blocker", "market-page", "publicProfile title is missing or generic.", "agentlas.json", "Use a concrete agent/team name, not boilerplate."))
    # Name the field and the measurement: "missing, too short, or generic" put
    # three different causes behind one message and sent authors hunting.
    if not description:
        findings.append(_finding("public-profile-description", "blocker", "market-page", "publicProfile descriptionKo is missing.", "agentlas.json", "Explain what the package does, who it is for, and what it produces."))
    elif len(description) < 40:
        findings.append(_finding("public-profile-description", "blocker", "market-page", f"publicProfile {description_field} needs at least 40 characters (has {len(description)}).", "agentlas.json", "Explain what the package does, who it is for, and what it produces. The gate reads the Korean copy first."))
    elif _looks_generic_copy(description):
        findings.append(_finding("public-profile-description", "blocker", "market-page", f"publicProfile {description_field} is boilerplate copy.", "agentlas.json", "Replace placeholder wording with what this specific package does."))

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
    missing_sections: list[str] = []
    for keys in section_keys:
        value = _first_text(guide, keys)
        if value and not _looks_generic_copy(value):
            filled += 1
        else:
            missing_sections.append(keys[0])
    if filled < 4:
        # List the sections that are actually empty or boilerplate instead of
        # asking the author to guess which four of five already count.
        findings.append(_finding("public-profile-guide-sections", "blocker", "market-page", f"publicProfile guide needs at least 4 concrete sections (has {filled}); missing or generic: {', '.join(missing_sections)}.", "agentlas.json", "Fill these guide sections with copy specific to this package."))
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


_MCP_POLICY_FORBIDDEN_KEYS = {"command", "args", "endpoint", "executable", "headers", "env", "token", "apiKey", "api_key", "credentials"}


def _repair_mcp_policy_file(base: Path, findings: list[dict[str, Any]], *, write: bool) -> None:
    """Deterministically repair .agentlas/mcp-policy.json before the wizard hashes it.

    Owner rule (2026-08-08): upload never bounces a fixable defect back to the
    author. An invalid MCP policy is fixable without inventing a fact - the
    forbidden fields (server execution / credential values) are stripped, and if
    the remainder still fails the contract, the file becomes the safe default
    policy. Every repair leaves a receipt finding. This runs BEFORE
    run_setup_wizard because the wizard is the last writer and the last hasher -
    repairing after it would ship a hash of a policy that no longer exists.
    """

    path = base / ".agentlas" / "mcp-policy.json"
    if not path.is_file():
        return
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        payload = None
    if not isinstance(payload, dict):
        if write:
            path.write_text(json.dumps(default_mcp_policy(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        findings.append(_finding("mcp-policy-auto-repaired", "high", "policy", "Unreadable MCP policy replaced with the safe default before upload.", ".agentlas/mcp-policy.json", "Receipt: the previous file was not valid JSON; no author action needed."))
        return
    try:
        validate_mcp_policy(payload)
        return
    except ContractValidationError:
        pass

    def strip(value: Any) -> Any:
        if isinstance(value, dict):
            return {k: strip(v) for k, v in value.items() if k not in _MCP_POLICY_FORBIDDEN_KEYS}
        if isinstance(value, list):
            return [strip(item) for item in value]
        return value

    stripped = strip(payload)
    try:
        validate_mcp_policy(stripped)
        repaired, note = stripped, "forbidden execution/credential fields stripped"
    except ContractValidationError:
        repaired, note = default_mcp_policy(), "policy replaced with the safe default (stripped shape still failed the contract)"
    if write:
        path.write_text(json.dumps(repaired, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    findings.append(_finding("mcp-policy-auto-repaired", "high", "policy", f"MCP policy auto-repaired before upload: {note}.", ".agentlas/mcp-policy.json", "Receipt: value-free catalog requirements kept; no author action needed."))


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


# Packaging reads the tree four times — once, then again after repair, after the
# brief compiles, and after the public card is prepared — because each of those
# rewrites files and every finding derived from them has to be recomputed rather
# than filtered. What must NOT be recomputed is the scan of a file that did not
# change: the content guard is 96% of packaging time (measured 7s per authored
# MB), so the four passes cost four times that for three passes of identical
# input. Keyed by exact content, so a repaired file is always rescanned.
_SANITIZE_CACHE: dict[tuple[str, str], tuple[str, list[dict[str, Any]]]] = {}
_SANITIZE_CACHE_MAX = 4096


def clear_sanitize_cache() -> None:
    _SANITIZE_CACHE.clear()


def sanitize_upload_file_text(file_path: str, text: str) -> tuple[str, list[dict[str, Any]]]:
    key = (file_path, hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest())
    hit = _SANITIZE_CACHE.get(key)
    if hit is not None:
        sanitized, findings = hit
        return sanitized, [dict(finding) for finding in findings]
    sanitized, findings = _sanitize_upload_file_text_uncached(file_path, text)
    if len(_SANITIZE_CACHE) >= _SANITIZE_CACHE_MAX:
        _SANITIZE_CACHE.clear()
    _SANITIZE_CACHE[key] = (sanitized, [dict(finding) for finding in findings])
    return sanitized, findings


def _sanitize_upload_file_text_uncached(file_path: str, text: str) -> tuple[str, list[dict[str, Any]]]:
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
    unquoted = UNQUOTED_SECRET_ASSIGNMENT.search(line)
    if unquoted and not _looks_like_secret_placeholder(unquoted.group(1)):
        return "generic-secret", "Removed possible unquoted hard-coded credential before upload."
    return None


def _looks_like_secret_placeholder(value: str) -> bool:
    candidate = value.strip().strip("'\"")
    lowered = candidate.lower()
    if not candidate or candidate.startswith(("$", "<", "[", "{{")):
        return True
    if re.fullmatch(r"[A-Z][A-Z0-9_]{2,}", candidate):
        return True
    return lowered in {
        "changeme",
        "example",
        "none",
        "null",
        "placeholder",
        "redacted",
        "replace-me",
        "your-api-key",
        "your-token-here",
    } or any(marker in lowered for marker in ("placeholder", "example", "your_", "your-"))


# Mirrors Agent Cloud's portableRelativePath contract
# (AgentsAtlas/app/src/lib/agentlas-cloud/package-contract.ts). The server
# refuses the whole bundle when any one path breaks these rules. The client
# catches and withholds the exact local path, then emits an engine receipt so
# the portable remainder can still upload.
_UNPORTABLE_SEGMENT_CHARS = re.compile('[<>:"|?*\x00-\x1f]')
_WINDOWS_RESERVED_SEGMENT = re.compile(r"^(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)", re.I)


def _quote(value: str) -> str:
    """Quote like JavaScript's JSON.stringify so both mirrors read identically."""

    return json.dumps(value, ensure_ascii=False)


def portable_relative_path_problem(value: str) -> str | None:
    """Return why ``value`` is not a portable package path, or None when it is."""

    if not isinstance(value, str) or not value:
        return "path must be a non-empty string"
    if value != unicodedata.normalize("NFC", value):
        return "path must be Unicode NFC (macOS commonly stores decomposed NFD filenames)"
    if "\\" in value:
        return "path must use '/' separators, not a backslash"
    if "\0" in value:
        return "path must not contain a NUL byte"
    if value.startswith("/"):
        return "path must be relative, not rooted at '/'"
    if value.endswith("/"):
        return "path must not end with '/'"
    if "//" in value:
        return "path must not contain an empty '//' segment"
    if len(value) > 260:
        return "path must be at most 260 characters"
    for part in value.split("/"):
        if not part or part in {".", ".."}:
            return "path must not contain a '.' or '..' segment"
        if len(part) > 255 or len(part.encode("utf-8")) > 255:
            return f"path segment {_quote(part)} must be at most 255 characters and 255 UTF-8 bytes"
        if _UNPORTABLE_SEGMENT_CHARS.search(part):
            return (
                f"path segment {_quote(part)} contains a character no portable filesystem "
                'accepts (one of <>:"|?* or a control character)'
            )
        if part[-1] in " .":
            return f"path segment {_quote(part)} must not end with a space or '.'"
        if _WINDOWS_RESERVED_SEGMENT.match(part):
            return (
                f"path segment {_quote(part)} is a Windows reserved device name "
                "(con, prn, aux, nul, com1-9, lpt1-9)"
            )
    return None


def collect_upload_files(base: Path) -> tuple[list[UploadFile], int, list[dict[str, Any]]]:
    files: list[UploadFile] = []
    findings: list[dict[str, Any]] = []
    # `total_bytes` is what the folder weighs; `transport_bytes` is what the
    # package costs to send and store, and that is what the ceiling is about.
    total_bytes = 0
    transport_bytes = 0
    file_count = 0
    walked = 0
    shipped_paths: dict[str, str] = {}
    # Keep traversal lazy. Sorting `rglob()` first materialized an attacker-sized
    # tree before the walk bound below could run, defeating the bound entirely.
    for path in base.rglob("*"):
        rel = path.relative_to(base).as_posix()
        if any(part in SKIP_DIRS for part in path.relative_to(base).parts):
            continue
        if (
            rel in UPLOAD_DERIVED_EVIDENCE_PATHS
            or rel in UPLOAD_PRIVATE_PROJECT_STATE_PATHS
            or any(rel.startswith(prefix) for prefix in UPLOAD_PRIVATE_PROJECT_STATE_DIRS)
            or is_local_experience_lineage_path(rel)
            or is_generated_runtime_path(rel)
            or is_work_output_path(rel)
            or is_product_private_folder_path(rel)
        ):
            continue
        walked += 1
        if walked > MAX_WALKED_ENTRIES:
            findings.append(_finding("walk-entry-limit", "blocker", "size", f"Package tree has more than {MAX_WALKED_ENTRIES} entries.", None, "Publish a focused agent/team folder."))
            break
        try:
            metadata = path.lstat()
        except OSError:
            findings.append(_finding("unsafe-file", "blocker", "policy", "Package path could not be inspected safely.", rel, "Remove or replace the unreadable path."))
            continue
        if stat.S_ISLNK(metadata.st_mode):
            findings.append(_finding("symlink", "blocker", "policy", "Symbolic links are not allowed in cloud agent packages.", rel, "Replace the symlink with an ordinary file or remove it."))
            continue
        if stat.S_ISDIR(metadata.st_mode):
            continue
        if not stat.S_ISREG(metadata.st_mode):
            findings.append(_finding("special-file", "blocker", "policy", "Special filesystem objects are not allowed in cloud agent packages.", rel, "Replace the path with an ordinary file or remove it."))
            continue
        if metadata.st_nlink != 1:
            findings.append(_finding("hardlink", "blocker", "policy", "Hard-linked files can expose content outside the selected package boundary.", rel, "Copy the content into a new ordinary file and remove the hard link."))
            continue
        # `^\.env(?:\..*)?$` also matches `.env.example`, which the Output
        # Contract makes mandatory, so the packager's own output was an
        # unpublishable blocker. Value-free by the OS's own declaration; the
        # SECRET_PATTERNS content scan further down still reads it.
        if not is_value_free_credential_template(rel) and any(pattern.search(path.name) for pattern in BLOCKED_FILE_PATTERNS):
            # Owner rule (2026-08-08): withholding IS the redaction. The file
            # never ships (no leak), the upload proceeds (no block), and the
            # receipt below tells the author exactly what was kept back.
            findings.append(_finding("redacted-file", "high", "secret", "Credential-named file withheld from the upload (never ships).", rel, "Receipt: publish setup instructions or env key names instead; the package uploaded without this file."))
            continue
        # Inclusion is decided by what this artifact can actually carry (UTF-8
        # text), not by a guessed extension allowlist. The allowlist dropped real
        # package content — templates/*.html, data/*.csv, an extensionless
        # `scripts/run` or `LICENSE` — with a bare `continue` and no finding, and
        # both counts below tally survivors only, so the author saw "Ready" with
        # matching fileCount/includedFileCount and shipped an agent missing its
        # own files. Every path that now refuses a file names that file.
        # Refuse early only what cannot fit even at a good compression ratio.
        # Anything smaller is read, compressed, and judged on what it costs.
        if metadata.st_size > MAX_UNCOMPRESSED_FILE_BYTES:
            # Blocker, not "high": the file is dropped from the bundle, and a
            # "high" finding never fails static_review, so publish_agent went on
            # to register the truncated package and answered "Registered <slug>."
            findings.append(_finding("large-file", "warning", "size", f"File is over {MAX_UNCOMPRESSED_FILE_BYTES} bytes, so it was left out and the rest of the package was uploaded.", rel, "Receipt: nothing to do to publish. Host the large asset outside the agent folder if the agent needs it at runtime."))
            continue
        # Path portability boundary. Agent Cloud refuses the entire bundle when
        # any path breaks its contract, so decide it here and withhold the exact
        # offending path before registration.
        # macOS stores Korean/accented filenames decomposed (NFD) while the
        # contract requires NFC, so normalize that away instead of blocking a
        # name that is byte-different but visually identical; everything else
        # (Windows reserved names, control characters, trailing dot/space) is a
        # real rename and becomes a named blocker.
        shipped_rel = unicodedata.normalize("NFC", rel)
        path_problem = portable_relative_path_problem(shipped_rel)
        if path_problem:
            findings.append(
                _finding(
                    "unportable-path",
                    "blocker",
                    "structure",
                    f"Agent Cloud rejects this package path: {path_problem}.",
                    rel,
                    "Rename the file or folder to a portable relative path and package again.",
                )
            )
            continue
        if shipped_rel in shipped_paths:
            # Only reachable through the NFC normalization above, which can make
            # two distinct on-disk names collide into one bundle path.
            findings.append(
                _finding(
                    "path-collision",
                    "blocker",
                    "structure",
                    f"Two files normalize to the same package path {shipped_rel!r} "
                    f"(also {shipped_paths[shipped_rel]!r}).",
                    rel,
                    "Rename one of the two files so the package paths differ.",
                )
            )
            continue
        try:
            raw = _read_regular_file(path, metadata)
        except UploadError as exc:
            findings.append(_finding("unsafe-file", "blocker", "policy", str(exc), rel, "Retry from a stable package directory containing only ordinary files."))
            continue
        text = _decode_package_text(raw)
        if text is None:
            # A real binary cannot ride in a UTF-8 text artifact, but silence made
            # that indistinguishable from "nothing was here". Name the file so the
            # author learns which asset the borrower will not receive.
            findings.append(_finding("binary-file", "blocker", "content", "Binary file cannot be shipped in a text-only cloud package and was left out.", rel, "Host the asset outside the package, or remove it so the package contents match what ships."))
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
            # Never place cross-kind bytes in the returned base-agent bundle;
            # the final policy records the omission without blocking the rest.
            continue
        text, sanitized_findings = sanitize_upload_file_text(rel, text)
        findings.extend(sanitized_findings)
        # Anything the line sanitizer missed (structured payloads, odd shapes)
        # is masked in place, not blocked (owner rule 2026-08-08): the shipped
        # bytes carry [REDACTED:<kind>:<hash8>] where the value was, so the
        # package uploads, nothing leaks, and the receipt names every masking.
        # This must run BEFORE the bytes are encoded/hashed below so the
        # package hash seals what actually ships.
        for finding_id, pattern, label in SECRET_PATTERNS:
            def _mask(match: re.Match[str], _kind: str = finding_id) -> str:
                digest8 = hashlib.sha256(match.group(0).encode("utf-8")).hexdigest()[:8]
                return f"[REDACTED:{_kind}:{digest8}]"
            text, masked = pattern.subn(_mask, text)
            if masked:
                findings.append(_finding("redacted-secret", "high", "secret", f"Masked {masked} {label} occurrence(s) in place before upload.", rel, "Receipt: the value was replaced with a [REDACTED:kind:hash8] marker; each user configures their own key."))
        raw = text.encode("utf-8")
        if re.search(r"(?:curl|wget)[^\n|&;]+[|]\s*(?:sh|bash)", text, re.I):
            findings.append(_finding("curl-pipe-shell", "high", "network", "Remote shell install pattern detected.", rel, "Use explicit, reviewable install steps."))
        # Count only what is actually uploaded. These two ran before the
        # inclusion filters, so a 4 MB PNG that is never shipped still consumed
        # the package ceiling and blocked the upload — and the blocker carried
        # `file: None`, so the author could not tell which file to remove while
        # the same response reported a manifest of a few kilobytes.
        file_count += 1
        if file_count > MAX_COLLECTED_FILES:
            findings.append(_finding("file-count-limit", "blocker", "size", f"Package has more than {MAX_COLLECTED_FILES} files, past the point where dropping the least essential ones can still fit it.", rel, "Publish a focused agent/team folder."))
            break
        content_base64, encoding, encoded_bytes = encode_upload_content(raw)
        stored = encoded_bytes if encoded_bytes is not None else len(raw)
        if stored > MAX_FILE_BYTES:
            findings.append(_finding("large-file", "warning", "size", f"File is {stored} bytes even after compression, over the {MAX_FILE_BYTES} byte limit, so it was left out and the rest of the package was uploaded.", rel, "Receipt: nothing to do to publish. Host the large asset outside the agent folder if the agent needs it at runtime."))
            continue
        # What travelled is what counts against the ceiling; an uncompressed
        # package is unaffected because for it the two numbers are the same.
        #
        # Crossing the ceiling must NOT stop the walk. Whoever is left out is
        # chosen by `_trim_upload_files_to_limits`, which ranks by what the
        # agent needs (owner decision 2026-08-18: trimming must not cost the
        # agent its abilities) and leaves a receipt per dropped path. Breaking
        # here handed that decision to the filesystem's walk order instead: a
        # package with a heavy `benchmarks/` folder shipped 13 benchmark files
        # and zero `skills/` files, because "b" is walked before "s" — the
        # ranked trimmer never saw the skills to keep them.
        transport_bytes += stored
        total_bytes += len(raw)
        if total_bytes > MAX_UNCOMPRESSED_TOTAL_BYTES:
            findings.append(_finding("package-uncompressed-size-limit", "blocker", "size", f"Package contents exceed {MAX_UNCOMPRESSED_TOTAL_BYTES} bytes before compression at {rel}.", rel, "Publish a focused agent/team folder."))
            break
        digest = _sha256_bytes(raw)
        shipped_paths[shipped_rel] = rel
        files.append(
            UploadFile(
                path=shipped_rel,
                bytes=len(raw),
                sha256=digest,
                contentBase64=content_base64,
                executable=bool(metadata.st_mode & 0o111),
                encoding=encoding,
                encodedBytes=encoded_bytes,
            )
        )
    files.sort(key=lambda item: item.path.encode("utf-16-be"))
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


def _read_public_profile(base: Path) -> dict[str, Any]:
    """The author's market-page copy from agentlas.json, or an empty dict.

    One reader for every consumer of publicProfile: the market-page gate, the
    manifest tagline, and the manifest field the listing mapper reads.
    """

    manifest = _read_json(base / "agentlas.json")
    profile = manifest.get("publicProfile") if isinstance(manifest, dict) else None
    return profile if isinstance(profile, dict) else {}


def _read_tagline(base: Path) -> str:
    public_profile = _read_public_profile(base)
    # `description` is locale-neutral copy the market-page gate accepts too;
    # skipping it here sent the tagline back to the English routing card even
    # though the author had written a description.
    for key in ("descriptionKo", "descriptionEn", "description"):
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
    antigravity_workflows = base / "antigravity" / "workflows"
    if antigravity_workflows.is_dir() and any(path.is_file() for path in antigravity_workflows.rglob("*")):
        labels.append("antigravity")
    return labels or ["agents-md"]


def _decode_package_text(raw: bytes) -> str | None:
    """Return the shippable text of a package file, or None if it is binary.

    Replaces the old extension allowlist: the cloud artifact carries UTF-8 text,
    so decodability — not the file's suffix — is the real inclusion rule. A NUL
    byte marks binary content that happens to survive a lenient decode.
    """

    if b"\x00" in raw:
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return None


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


def _best_localized_text(payload: dict[str, Any], keys: tuple[str, ...]) -> tuple[str, str]:
    """Return the strongest localized value and the key it came from.

    Locale order states preference, not authority: a package that documents its
    market page in one language should not be refused because a sibling locale
    holds a stub. Prefers a non-generic value that clears the length gate, then
    the longest available, so the reported field is the one the author must fix.
    """

    candidates: list[tuple[str, str]] = []
    for key in keys:
        text = _first_text(payload, (key,))
        if text:
            candidates.append((key, text))
    if not candidates:
        return "", keys[0]
    passing = [
        (key, text)
        for key, text in candidates
        if len(text) >= 40 and not _looks_generic_copy(text)
    ]
    key, text = (passing or sorted(candidates, key=lambda item: len(item[1]), reverse=True))[0]
    return text, key


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
    text = re.sub(r"\s+", " ", str(value or "")).strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", text).strip("-")[:64]
    if slug:
        return slug
    # An identity carrying no ASCII letter or digit (a Korean/Japanese name, an
    # emoji name, a punctuation-only name) used to collapse to one hard-coded
    # constant, so EVERY such package published under the same slug — and the
    # 428 precondition retry in `register_agent` then overwrote the agent that
    # already owned that slug without ever asking. The fallback must therefore
    # be a function of the identity, not a shared literal: republishing the same
    # package still lands on the same slug (an intentional overwrite keeps
    # working) while two different non-ASCII names can no longer claim one Hub
    # identity. Reached by every caller path — derived package name, folder
    # name, routing-card `agent_card_ref.slug`, and an explicit `--slug`.
    if not text:
        raise UploadError(
            "cannot derive an upload slug: the package has no name, slug, or folder name. Pass an explicit --slug."
        )
    return f"agentlas-cloud-agent-{_sha256_text(text)[:12]}"


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
