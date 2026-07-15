from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "scripts" / "install-memory-hooks.py"
ONE_TOUCH_INSTALLER = ROOT / "scripts" / "install-all-runtimes.sh"


def tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest.update(str(path.relative_to(root)).encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\n")
    return digest.hexdigest()


class MemoryHookInstallerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        (self.home / ".gemini" / "config").mkdir(parents=True)
        (self.home / ".gemini" / "config" / "hooks.json").write_text(
            json.dumps({"existing-hook": {"enabled": False, "Stop": []}}),
            encoding="utf-8",
        )
        (self.home / ".grok" / "hooks").mkdir(parents=True)
        (self.home / ".grok" / "hooks" / "user-owned.json").write_text(
            '{"hooks":{"Stop":[]}}\n', encoding="utf-8"
        )
        (self.home / ".grok" / "AGENTS.md").write_text(
            "# My Grok rules\n\nKeep this user-owned text.\n", encoding="utf-8"
        )
        (self.home / ".config" / "opencode" / "plugins").mkdir(parents=True)
        (self.home / ".config" / "opencode" / "plugins" / "user-owned.js").write_text(
            "export const UserOwned = async () => ({})\n", encoding="utf-8"
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def run_installer(self, hosts: str = "all") -> dict:
        env = dict(os.environ)
        env["HOME"] = str(self.home)
        result = subprocess.run(
            [
                str(INSTALLER),
                "--source-dir",
                str(ROOT),
                "--home",
                str(self.home),
                "--hosts",
                hosts,
            ],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=True,
        )
        return json.loads(result.stdout)

    def test_antigravity_cli_marker_is_auto_detected_in_isolated_home(self) -> None:
        marker = self.home / ".gemini" / "antigravity-cli"
        marker.mkdir(parents=True)

        payload = self.run_installer(hosts="auto")

        self.assertEqual(payload["status"], "pass")
        self.assertIn("antigravity", payload["installed"])
        hooks_path = self.home / ".gemini" / "config" / "hooks.json"
        hooks = json.loads(hooks_path.read_text(encoding="utf-8"))
        self.assertIn("agentlas-memory", hooks)

    def test_one_touch_antigravity_detection_uses_cli_marker_without_mutating_it(self) -> None:
        marker = self.home / ".gemini" / "antigravity-cli"
        marker.mkdir(parents=True)
        sourcable = self.home / "install-all-runtimes-sourcable.sh"
        source = ONE_TOUCH_INSTALLER.read_text(encoding="utf-8")
        self.assertTrue(source.rstrip().endswith('main "$@"'))
        sourcable.write_text(source.rsplit('\nmain "$@"', 1)[0] + "\n", encoding="utf-8")
        env = dict(os.environ)
        env.update(
            {
                "HOME": str(self.home),
                "HEPHAESTUS_SOURCE_DIR": str(ROOT),
            }
        )

        result = subprocess.run(
            [
                "bash",
                "-c",
                'set -e; source "$1"; antigravity_present; install_antigravity',
                "agentlas-antigravity-marker-test",
                str(sourcable),
            ],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        workflows = self.home / ".gemini" / "antigravity" / "global_workflows"
        self.assertTrue((workflows / "hep-build.md").is_file())
        self.assertTrue((workflows / "hep-network.md").is_file())
        self.assertTrue((self.home / ".gemini" / "config" / "mcp_config.json").is_file())
        self.assertFalse(
            (marker / "global_workflows").exists(),
            "the Antigravity CLI state marker must not be repurposed as a workflow root",
        )

    def test_merge_no_clobber_and_idempotency(self) -> None:
        first = self.run_installer()
        self.assertEqual(first["status"], "pass")
        hooks = json.loads(
            (self.home / ".gemini" / "config" / "hooks.json").read_text(encoding="utf-8")
        )
        self.assertIn("existing-hook", hooks)
        self.assertIn("agentlas-memory", hooks)
        self.assertIn("PreInvocation", hooks["agentlas-memory"])

        grok_rules = (self.home / ".grok" / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("Keep this user-owned text.", grok_rules)
        self.assertEqual(grok_rules.count("AGENTLAS:MEMORY-HOOK:BEGIN"), 1)
        self.assertTrue((self.home / ".grok" / "hooks" / "user-owned.json").is_file())
        self.assertTrue(
            (self.home / ".config" / "opencode" / "plugins" / "user-owned.js").is_file()
        )
        plugin = self.home / ".config" / "opencode" / "plugins" / "agentlas-memory.js"
        plugin_source = plugin.read_text(encoding="utf-8")
        self.assertIn('"chat.message"', plugin_source)
        self.assertIn("RECALL_TIMEOUT_MS", plugin_source)
        self.assertIn("child.kill()", plugin_source)
        self.assertIn('event?.type !== "session.deleted"', plugin_source)
        self.assertNotIn("http://", plugin_source)
        self.assertNotIn("https://", plugin_source)

        before = tree_digest(self.home)
        second = self.run_installer()
        after = tree_digest(self.home)
        self.assertEqual(second["status"], "pass")
        self.assertEqual(before, after)

    def test_invalid_existing_json_is_preserved_and_reported(self) -> None:
        hooks_path = self.home / ".gemini" / "config" / "hooks.json"
        hooks_path.write_text("{broken", encoding="utf-8")
        result = subprocess.run(
            [
                str(INSTALLER),
                "--source-dir",
                str(ROOT),
                "--home",
                str(self.home),
                "--hosts",
                "antigravity",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )
        self.assertEqual(result.returncode, 1)
        self.assertEqual(hooks_path.read_text(encoding="utf-8"), "{broken")
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "fail")

    def test_one_touch_installer_wires_verified_model_and_host_hooks(self) -> None:
        source = (ROOT / "scripts" / "install-all-runtimes.sh").read_text(encoding="utf-8")
        self.assertIn('model_source="$source_dir/assets/model2vec/potion-base-8M-int8"', source)
        self.assertIn('model_dest="$home_dir/models/model2vec/potion-base-8M-int8"', source)
        self.assertIn('-m ontology.model_assets verify "$model_dest"', source)
        self.assertIn('"$home_dir/bin/ontology"', source)
        self.assertIn("hephaestus ontology hep-build", source)
        self.assertIn("install_memory_hooks()", source)
        self.assertIn('install-memory-hooks.py"', source)
        self.assertIn(
            'install_memory_hooks || { warn "Local ontology memory hook install failed.";',
            source,
        )


if __name__ == "__main__":
    unittest.main()
