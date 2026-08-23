#!/usr/bin/env bash
# A publish that succeeded must not be reported as a failure.
#
# Registration verifies the hash the client submitted, then withholds any file
# the server's own scan judged credential-like and stores the remainder under a
# NEW hash, with `uploadReceipt.omissions` naming every dropped path. The client
# compared only against the stored hash, so that documented repair surfaced as
# `registration_attestation_failed` AFTER the listing was live: the agent was on
# the Hub, searchable and callable, while the publisher was told the upload had
# failed — and everything downstream of attestation, pricing included, never ran.
#
# Attestation exists to prove the server saw exactly this package.
# `submittedPackageHash` is that proof, so either hash matching ours satisfies
# it, and the withheld paths are reported. A response carrying neither still
# fails closed — that half is what keeps the first half honest.
set -euo pipefail
cd "$(dirname "$0")/.."

python3 - <<'PY'
import pathlib, sys, tempfile

sys.path.insert(0, ".")
from agentlas_cloud import upload as upload_module
from agentlas_cloud.package_contract import scaffold
from agentlas_cloud.upload import UploadError, publish_agent

workspace = pathlib.Path(tempfile.mkdtemp(prefix="registration-attestation."))
agent = workspace / "attestation-fixture"
scaffold(
    agent,
    mode="single",
    package_id="attestation-fixture",
    name="Attestation Fixture",
    command="attestation-fixture",
    minimal_private_reason="gate fixture, not a built package",
)
(agent / "AGENTS.md").write_text(
    "# Attestation Fixture\n\nProves a live publish is not reported as a failure.\n",
    encoding="utf-8",
)

upload_module.ensure_access_token = lambda base_url, interactive=True: "gate-token"
submitted: dict[str, str] = {}


def register_withholding_a_file(manifest, bundle, review, **kwargs):
    submitted["hash"] = str(manifest["packageHash"])
    return {
        "slug": manifest["slug"],
        "status": "registered",
        "visibility": "marketplace",
        "packageHash": "b" * 64,
        "agentReleaseId": "agent:fixture:release:1.0.0",
        "releaseVersion": "1.0.0",
        "contentDigest": "sha256:" + "b" * 64,
        "uploadReceipt": {
            "submittedPackageHash": submitted["hash"],
            "storedPackageHash": "b" * 64,
            "omittedFileCount": 1,
            "omissions": [{"path": "notes.md", "reason": "credential-like-content"}],
        },
    }


upload_module.register_package = register_withholding_a_file
result = publish_agent(agent, visibility="marketplace")
assert result["status"] == "registered", result["status"]
assert result["serverWithheld"]["paths"] == ["notes.md"], result.get("serverWithheld")


def register_for_someone_else(manifest, bundle, review, **kwargs):
    return {
        "slug": manifest["slug"],
        "status": "registered",
        "visibility": "marketplace",
        "packageHash": "c" * 64,
        "agentReleaseId": "agent:other:release:9.9.9",
        "releaseVersion": "9.9.9",
        "contentDigest": "sha256:" + "c" * 64,
        "uploadReceipt": {"submittedPackageHash": "d" * 64, "omissions": []},
    }


upload_module.register_package = register_for_someone_else
try:
    publish_agent(agent, visibility="marketplace")
except UploadError as error:
    assert error.code == "registration_attestation_failed", error.code
else:
    raise AssertionError("a registration that never saw our package must not pass")

print("PASS verify-registration-attestation")
PY
