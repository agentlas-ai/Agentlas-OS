from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import unicodedata
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import content_guard
from .auth import ensure_access_token, normalize_base_url
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

MAX_TOTAL_BYTES = 3 * 1024 * 1024
MAX_FILE_BYTES = 512 * 1024
# Walk bound so a pathological tree terminates; the package ceiling is MAX_FILES,
# measured on the files actually uploaded.
MAX_WALKED_ENTRIES = 20_000
MAX_FILES = 400
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



def _is_unfinished_artifact(finding: dict[str, Any]) -> bool:
    """True when a blocker is only "the author has not written this yet".

    Kept deliberately narrow. It matches a missing or still-templated package
    contract artifact and nothing else — never a secret, a symlink, a size limit,
    a credential-bearing path, or a malformed card. Widening this predicate would
    turn "we repair instead of refusing" into "we publish anything", which is a
    different policy and not this one.
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
    # a stencil. The created-only list misses a PRE-EXISTING stencil AGENTS.md:
    # scaffold skips a file that already exists, so it is never in `created`, yet
    # it ships `{{ROLE}}` to a buyer as the very file the runtime reads first
    # (measured 2026-08-12 adversarial set — a stencil AGENTS.md reached upload
    # at status ready). Only a wholly-stencil file is taken back; a body a person
    # partly wrote (no `{{`) is left exactly as it is.
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
        if "{{" not in body:
            continue
        try:
            candidate.unlink()
            withdrawn.append(str(relative))
        except OSError:
            continue
    if withdrawn:
        contract_scaffold["withdrawn"] = withdrawn

    career_card_findings = prepare_public_career_card_for_upload(base)
    files, file_count, findings = collect_upload_files(base)
    findings = career_card_findings + findings

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
        findings = prepare_public_career_card_for_upload(base) + findings

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
        "files": [item.__dict__ for item in files],
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
    # ANY blocker still standing after the repair pass blocks. The classification
    # only decides what the repair ATTEMPTS; it never excuses a defect the repair
    # failed to fix. Letting "repairable" mean "ignorable" would publish a package
    # nobody fixed while reporting it ready — the same silent-default failure this
    # file's content guard exists to prevent.
    remaining = [f for f in findings if f["severity"] == "blocker"]
    # A contract artifact the author has not finished writing is a gap in the
    # listing, not a reason to refuse the upload. The package still works; what
    # is missing is copy a buyer would have liked to read. Refusing here is how
    # `capability-eval-plan.json` ended up on 4% of live releases — the gate said
    # no, and the packages shipped through whatever path did not check.
    #
    # This only ever softens an artifact-completeness finding. Since 2026-08-08
    # (owner rule) secrets no longer BLOCK either - they are masked or withheld
    # in place with receipt findings ("redacted-secret", "redacted-file",
    # "mcp-policy-auto-repaired"), because "remove the value and try again" hands
    # the author work the engine can do deterministically. What still blocks is
    # what cannot be repaired without inventing facts or shipping a broken
    # artifact: symlinks, size/count limits, cross-kind asset embedding, and
    # contract gaps that need author/model facts (until the packager re-invoke
    # loop lands - see docs/2026-08-08-upgrade R7/R12).
    deferred = [f for f in remaining if _is_unfinished_artifact(f)]
    if deferred:
        deferred_ids = {id(f) for f in deferred}
        remaining = [f for f in remaining if id(f) not in deferred_ids]
        for finding in deferred:
            finding["severity"] = "warning"
            finding["deferred"] = "publishable; the listing is thinner until this is written"
    # 필수개정 7-2 (owner rule 2026-08-09): 유저는 스스로 못 고친다 — 구조/마켓페이지
    # 결함으로 업로드를 반려하지 않는다. 결정론 리패키징(derive/reconcile/coerce/
    # refresh/repair)이 여기까지 왔는데도 남은 structure·market-page blocker는 엔진이
    # 자동 완성하지 못한 지점이므로, 사용자에게 "고쳐오세요"를 넘기지 않고 경고로 강등해
    # 얇은 리스팅으로라도 출하하며 엔진 결함으로 고지한다("리패키징까지 실패하면 사용자
    # 잘못이 아니라 엔진 결함"). 단 진짜 안전/불가 항목은 계속 막는다:
    #   - size (파일 수·용량 한계 — 물리적으로 못 싣는다)
    #   - privacy (career-card-privacy — 원시 기억/프롬프트 유출)
    #   - asset-boundary (교차종 자산 임베딩 — 다른 소유 자산)
    #   - secret 값(이미 마스킹되어 blocker가 아니지만, 못 가린 실키가 남으면 유지)
    HARD_BLOCK_CATEGORIES = {"size", "asset-boundary", "secret"}
    HARD_BLOCK_IDS_PREFIX = ("career-card-privacy", "unportable-path")
    def _must_stay_blocked(finding: dict[str, Any]) -> bool:
        if finding.get("category") in HARD_BLOCK_CATEGORIES:
            return True
        fid = str(finding.get("id") or "")
        return any(fid.startswith(p) for p in HARD_BLOCK_IDS_PREFIX)
    engine_gap = [f for f in remaining if not _must_stay_blocked(f)]
    if engine_gap:
        gap_ids = {id(f) for f in engine_gap}
        remaining = [f for f in remaining if id(f) not in gap_ids]
        for finding in engine_gap:
            finding["severity"] = "warning"
            finding["deferred"] = "published with a thinner listing; the engine could not auto-complete this and it is flagged as an engine gap, never handed back to the author to fix"
            finding["engineGap"] = True
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
                else f"Ready: {manifest['slug']}."
            )
        ),
    }


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
    if not notes:
        return f"Dry run passed: {slug}."
    return f"Dry run completed with warnings: {slug} — " + "; ".join(notes)


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
        packaged["summary"] = _dry_run_summary(packaged)
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
    registered_slug = registration.get("slug") or packaged["manifest"]["slug"]
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
    Packages carry exactly that copy — in `publicProfile` (the market-page gate
    already blocks upload without it) and again as `name/nameKo/summary/summaryKo`
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
) -> dict[str, Any]:
    base = normalize_base_url(base_url)
    token = ensure_access_token(base, interactive=interactive)
    if not token:
        raise UploadError("Agentlas sign-in is required. Run `bin/hephaestus auth login` first.")
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
        with urllib.request.urlopen(request, timeout=180) as response:
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
                raise UploadError("\n".join(lines)) from exc
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
    # A card with no résumé (workforce) block gets filled with a deterministic
    # minimal block — a gate that keeps an auto-built agent from dying at the
    # new standard gate (no model call, preserves any existing block).
    from .networking.card_lint import ensure_workforce_block

    ensure_workforce_block(card)
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


# Mirrors Agent Cloud's portableRelativePath contract
# (AgentsAtlas/app/src/lib/agentlas-cloud/package-contract.ts). The server
# refuses the whole bundle when any one path breaks these rules, so the same
# rules have to run here — while we still know which local file produced the
# path — or `package` says "ready" and only the real upload finds out.
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
    total_bytes = 0
    file_count = 0
    walked = 0
    shipped_paths: dict[str, str] = {}
    for path in sorted(base.rglob("*")):
        rel = path.relative_to(base).as_posix()
        if any(part in SKIP_DIRS for part in path.relative_to(base).parts):
            continue
        if (
            rel in UPLOAD_DERIVED_EVIDENCE_PATHS
            or is_local_experience_lineage_path(rel)
            or is_generated_runtime_path(rel)
        ):
            continue
        if path.is_symlink():
            findings.append(_finding("symlink", "blocker", "policy", "Symbolic links are not allowed in cloud agent packages.", rel, "Replace the symlink with an ordinary file or remove it."))
            continue
        if not path.is_file():
            continue
        # A pathological tree must still terminate even when almost nothing in it
        # is uploadable, but this is a walk bound, not the package ceiling.
        walked += 1
        if walked > MAX_WALKED_ENTRIES:
            findings.append(_finding("file-count-limit", "blocker", "size", f"Package has more than {MAX_FILES} files.", None, "Publish a focused agent/team folder."))
            break
        stat = path.stat()
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
        if stat.st_size > MAX_FILE_BYTES:
            # Blocker, not "high": the file is dropped from the bundle, and a
            # "high" finding never fails static_review, so publish_agent went on
            # to register the truncated package and answered "Registered <slug>."
            findings.append(_finding("large-file", "blocker", "size", f"File exceeds {MAX_FILE_BYTES} bytes and cannot be shipped in the package.", rel, "Move the large asset out of the package folder, or split it below the limit."))
            continue
        # Path portability gate. Agent Cloud refuses the ENTIRE bundle when any
        # one path breaks its portableRelativePath contract, and its 400 could
        # not name the file — with up to MAX_FILES paths the author had to guess.
        # Decide it here, where the offending local file is still in hand.
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
        raw = path.read_bytes()
        text = _decode_package_text(raw)
        if text is None:
            # A real binary cannot ride in a UTF-8 text artifact, but silence made
            # that indistinguishable from "nothing was here". Name the file so the
            # author learns which asset the borrower will not receive.
            findings.append(_finding("binary-file", "high", "content", "Binary file cannot be shipped in a text-only cloud package and was left out.", rel, "Host the asset outside the package, or remove it so the package contents match what ships."))
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
        if file_count > MAX_FILES:
            findings.append(_finding("file-count-limit", "blocker", "size", f"Package has more than {MAX_FILES} files.", rel, "Publish a focused agent/team folder."))
            break
        total_bytes += len(raw)
        if total_bytes > MAX_TOTAL_BYTES:
            findings.append(_finding("package-size-limit", "blocker", "size", f"Package exceeds {MAX_TOTAL_BYTES} bytes at {rel}.", rel, "Publish a smaller package."))
            break
        digest = _sha256_bytes(raw)
        shipped_paths[shipped_rel] = rel
        files.append(
            UploadFile(
                path=shipped_rel,
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
