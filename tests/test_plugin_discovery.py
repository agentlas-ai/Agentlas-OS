import io
import json
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from agentlas_cloud import plugin_discovery


def write_plugin(root: Path, manifest_dir: str, name: str, version: str = "0.1.0", description: str = "") -> None:
    plugin_dir = root / name / manifest_dir
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "plugin.json").write_text(
        json.dumps({"name": name, "version": version, "description": description}),
        encoding="utf-8",
    )


def write_registry(path: Path, plugins: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"name": "test-market", "plugins": plugins}), encoding="utf-8")


class PluginDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name) / "home"
        self.project = Path(self.tmp.name) / "project"
        (self.home / ".claude" / "plugins").mkdir(parents=True)
        self.project.mkdir(parents=True)
        self.env = mock.patch.dict(
            os.environ,
            {"HOME": str(self.home), "CODEX_HOME": str(self.home / ".codex")},
        )
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_scan_finds_project_and_home_plugins_and_dedupes(self):
        write_plugin(self.project / "claude" / "plugins", ".claude-plugin", "korean-docs", description="Korean document reading and writing")
        write_plugin(self.project / "codex" / "plugins", ".codex-plugin", "korean-docs", description="Korean document reading and writing")
        write_plugin(self.home / ".claude" / "plugins", ".claude-plugin", "home-only-plugin")
        write_registry(
            self.project / ".claude-plugin" / "marketplace.json",
            [{"name": "hephaestus", "version": "0.3.0", "description": "meta agent", "source": "./claude/plugins/x"}],
        )
        result = plugin_discovery.scan_local_plugins(self.project)
        names = {plugin["name"] for plugin in result["plugins"]}
        self.assertEqual(names, {"korean-docs", "home-only-plugin", "hephaestus"})
        korean = next(plugin for plugin in result["plugins"] if plugin["name"] == "korean-docs")
        self.assertEqual(len(korean["locations"]), 2)

    def test_resolve_local_only_when_hub_skipped(self):
        write_plugin(self.project / "claude" / "plugins", ".claude-plugin", "korean-docs", description="한글 문서 HWP HWPX parsing")
        result = plugin_discovery.resolve_plugins("korean-docs", self.project, use_hub=False)
        self.assertEqual(result["hub"]["status"], "skipped")
        self.assertEqual(result["local"]["count"], 1)
        self.assertFalse(result["unresolved"])

    def test_resolve_merges_hub_matches_and_marks_already_local(self):
        write_plugin(self.project / "claude" / "plugins", ".claude-plugin", "korean-docs", description="한글 문서")
        hub_payload = {
            "count": 2,
            "plugins": [
                {"slug": "korean-docs", "name": "Korean Docs", "family": "agentlas-public", "category": "productivity", "taglineKo": "한글 문서", "auth": "none", "installCli": "npx agentlas@latest plugin add korean-docs", "manifestHref": "/api/plugins/korean-docs"},
                {"slug": "slack", "name": "Slack", "family": "third-party", "category": "communication", "taglineKo": "슬랙", "auth": "oauth", "installCli": "npx agentlas@latest plugin add slack", "manifestHref": "/api/plugins/slack"},
            ],
        }
        fake_response = io.BytesIO(json.dumps(hub_payload).encode("utf-8"))
        fake_response.__enter__ = lambda *args: fake_response
        fake_response.__exit__ = lambda *args: None
        with mock.patch.object(plugin_discovery.urllib.request, "urlopen", return_value=fake_response):
            result = plugin_discovery.resolve_plugins("한글 문서", self.project)
        self.assertEqual(result["hub"]["status"], "ok")
        already_local_slugs = [plugin["slug"] for plugin in result["hub"]["already_local"]]
        installable_slugs = [plugin["slug"] for plugin in result["hub"]["installable"]]
        self.assertEqual(already_local_slugs, ["korean-docs"])
        self.assertEqual(installable_slugs, ["slack"])
        self.assertEqual(
            result["hub"]["installable"][0]["manifest_url"],
            f"{plugin_discovery.hub_base_url()}/api/plugins/slack",
        )

    def test_hub_unreachable_falls_back_to_local(self):
        write_plugin(self.project / "claude" / "plugins", ".claude-plugin", "korean-docs", description="한글 문서")
        with mock.patch.object(
            plugin_discovery.urllib.request,
            "urlopen",
            side_effect=urllib.error.URLError("offline"),
        ):
            result = plugin_discovery.resolve_plugins("한글 문서", self.project)
        self.assertEqual(result["hub"]["status"], "unreachable")
        self.assertEqual(result["local"]["count"], 1)
        self.assertFalse(result["unresolved"])

    def test_unresolved_when_nothing_matches(self):
        result = plugin_discovery.resolve_plugins("quantum-fusion-reactor", self.project, use_hub=False)
        self.assertTrue(result["unresolved"])


if __name__ == "__main__":
    unittest.main()
