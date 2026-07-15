from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CROSS_PLATFORM_WORKFLOW = ROOT / ".github" / "workflows" / "cross-platform-harness.yml"
RELEASE_WORKFLOW = ROOT / ".github" / "workflows" / "release-runtime.yml"

WORKFORCE_PATH_FILTERS = (
    "agentlas_cloud/**",
    "docs/agent-workforce-ontology.md",
    "schemas/workforce-*.schema.json",
    "benchmarks/workforce-ontology/**",
    "manifest.json",
    "scripts/verify-package.sh",
    "skills/hephaestus-network/**",
    ".agents/skills/hephaestus-network/**",
    ".agents/workflows/hep-network.md",
    "tests/test_workforce_ontology.py",
    "tests/test_workforce_benchmark.py",
    "tests/test_workforce_workflow_gates.py",
    ".github/workflows/release-runtime.yml",
)

WORKFORCE_TESTS = (
    "tests/test_workforce_ontology.py",
    "tests/test_workforce_benchmark.py",
)


def _between(text: str, start: str, end: str) -> str:
    start_at = text.index(start)
    end_at = text.index(end, start_at + len(start))
    return text[start_at:end_at]


def test_cross_platform_workflow_routes_every_workforce_contract_change() -> None:
    workflow = CROSS_PLATFORM_WORKFLOW.read_text(encoding="utf-8")
    pull_request = _between(workflow, "  pull_request:\n", "  push:\n")
    push = _between(workflow, "  push:\n", "\npermissions:\n")

    for path in WORKFORCE_PATH_FILTERS:
        entry = f'      - "{path}"'
        assert entry in pull_request, f"pull_request path filter missing {path}"
        assert entry in push, f"push path filter missing {path}"


def test_cross_platform_workflow_runs_workforce_contracts_on_the_os_matrix() -> None:
    workflow = CROSS_PLATFORM_WORKFLOW.read_text(encoding="utf-8")
    matrix_job = _between(workflow, "  harness-contract:\n", "  compare-platform-proofs:\n")
    workforce_gate = _between(
        matrix_job,
        "      - name: Verify Agent Workforce Ontology contracts\n",
        "      - name: Run Stormbreaker contract suite\n",
    )

    assert "os: [ubuntu-latest, macos-latest, windows-latest]" in matrix_job
    for test_path in WORKFORCE_TESTS:
        assert test_path in workforce_gate
    assert "tests/test_workforce_workflow_gates.py" in matrix_job


def test_release_workflow_blocks_archive_build_on_workforce_contracts() -> None:
    workflow = RELEASE_WORKFLOW.read_text(encoding="utf-8")
    workforce_gate = _between(
        workflow,
        "      - name: Verify Agent Workforce Ontology release gate\n",
        "      - name: Verify updater and credential gates\n",
    )

    assert "python -m pip install pytest jsonschema" in workflow
    for test_path in WORKFORCE_TESTS:
        assert test_path in workforce_gate
    assert workflow.index("Verify Agent Workforce Ontology release gate") < workflow.index(
        "Build deterministic runtime archive"
    )
    assert "tests/test_workforce_workflow_gates.py" in workflow
