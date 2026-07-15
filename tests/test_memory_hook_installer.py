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

    def run_installer(self) -> dict:
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
                "all",
            ],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=True,
        )
        return json.loads(result.stdout)

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
        self.assertIn('"chat.message"', plugin.read_text(encoding="utf-8"))
        self.assertNotIn("http://", plugin.read_text(encoding="utf-8"))
        self.assertNotIn("https://", plugin.read_text(encoding="utf-8"))

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


if __name__ == "__main__":
    unittest.main()
