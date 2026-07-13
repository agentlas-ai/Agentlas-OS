from __future__ import annotations

import gc
import json
import subprocess
import warnings
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from agentlas_cloud.project_bootstrap import ensure_project, project_status


def make_project(tmp_path: Path) -> Path:
    project = tmp_path / "workspace"
    project.mkdir()
    subprocess.run(["git", "init", "-q", str(project)], check=True)
    (project / "main.py").write_text("def hello_world():\n    return 1\n", encoding="utf-8")
    return project


def test_first_contact_creates_complete_private_project_architecture(tmp_path: Path) -> None:
    project = make_project(tmp_path)

    result = ensure_project(project, reason="test-first-contact")

    assert result["status"] == "active"
    assert result["missing"] == []
    assert result["mergeOnly"] is True
    assert result["overwritten"] == []
    assert result["warnings"] == []
    assert result["codeMap"]["stats"]["codeFiles"] == 1
    assert (project / ".agentlas" / "project-soul-memory.md").is_file()
    assert (project / ".agentlas" / "code-map" / "project-map.json").is_file()
    assert (project / ".agentlas" / "ontology-runtime.sqlite").is_file()
    assert (project / ".agentlas" / "career-graph.sqlite").is_file()
    assert (project / "signing" / "README.md").is_file()
    assert (project / "credentials" / "README.md").is_file()

    ignored = subprocess.run(
        ["git", "-C", str(project), "check-ignore", "-q", ".agentlas/project-soul-memory.md"],
        check=False,
    )
    assert ignored.returncode == 0
    visible = subprocess.check_output(["git", "-C", str(project), "status", "--short"], text=True)
    assert ".agentlas/project-soul-memory.md" not in visible
    assert ".agentlas/code-map" not in visible

    project_map = json.loads((project / ".agentlas" / "code-map" / "project-map.json").read_text(encoding="utf-8"))
    assert project_map["schemaVersion"] == "agentlas.code-map.v1"
    assert project_map["entryPoints"][0]["path"] == "main.py"


def test_bootstrap_is_idempotent_and_never_overwrites_user_memory(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    ensure_project(project)
    soul = project / ".agentlas" / "project-soul-memory.md"
    soul.write_text("USER CONTENT MUST SURVIVE\n", encoding="utf-8")

    repeated = ensure_project(project, reason="test-repeat")

    assert repeated["status"] == "active"
    assert repeated["created"] == []
    assert repeated["gitignore"]["changed"] is False
    assert repeated["codeMap"]["status"] == "existing"
    assert soul.read_text(encoding="utf-8") == "USER CONTENT MUST SURVIVE\n"


def test_concurrent_first_contacts_converge_without_partial_files(tmp_path: Path) -> None:
    project = make_project(tmp_path)

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda index: ensure_project(project, reason=f"concurrent-{index}"), range(6)))

    assert all(result["status"] == "active" for result in results)
    assert project_status(project)["missing"] == []
    leftovers = [path for path in project.rglob("*") if ".tmp-" in path.name or path.name.endswith(".lock")]
    assert leftovers == []


def test_existing_tracked_private_paths_are_reported_not_removed(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    private = project / ".agentlas" / "project-soul-memory.md"
    private.parent.mkdir()
    private.write_text("tracked before Agentlas privacy install\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(project), "add", ".agentlas/project-soul-memory.md"], check=True)

    result = ensure_project(project)

    assert ".agentlas/project-soul-memory.md" in result["trackedSensitivePaths"]
    staged = subprocess.check_output(["git", "-C", str(project), "diff", "--cached", "--name-only"], text=True)
    assert ".agentlas/project-soul-memory.md" in staged
    assert private.read_text(encoding="utf-8") == "tracked before Agentlas privacy install\n"


def test_first_contact_closes_graph_database_connections(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    gc.collect()

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", ResourceWarning)
        ensure_project(project, reason="connection-lifecycle-test")
        gc.collect()

    leaked = [
        warning
        for warning in caught
        if issubclass(warning.category, ResourceWarning)
        and "unclosed database" in str(warning.message)
    ]
    assert leaked == []
