import base64
import hashlib
import json

from agentlas_cloud.networking import init_networking, save_card
from agentlas_cloud.networking.gui_shortcut import open_local_gui_shortcut
from test_network_cards import make_ready_card


def _cloud_file(path: str, content: str) -> dict[str, object]:
    raw = content.encode("utf-8")
    return {
        "path": path,
        "contentBase64": base64.b64encode(raw).decode("ascii"),
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def test_operator_local_gui_shortcut_requires_allow_local(tmp_path):
    home = tmp_path / "networking"
    init_networking(home)
    package = tmp_path / "startup-package"
    (package / "scripts").mkdir(parents=True)
    launcher = package / "scripts" / "open.py"
    launcher.write_text(
        "import json\n"
        "print(json.dumps({'status': 'gui_ready', 'opened': False, 'gui_url': 'file:///tmp/demo.html'}))\n",
        encoding="utf-8",
    )
    card = make_ready_card(
        tmp_path,
        "startup-gui",
        triggers_ko=["스타트업 열어줘", "창업 gui"],
        triggers_en=["startup", "startup founder studio", "open startup gui"],
        antis=["legal", "payment", "deploy"],
        capabilities=["open_startup_gui"],
    )
    card["entrypoints"] = {
        "canonical_command": "/startup",
        "agent": "agents/00-startup-orchestrator/agent.md",
        "gui": "webapp/index.html",
        "gui_launcher": "scripts/open.py",
    }
    card["network_shortcut"] = {
        "enabled": True,
        "phrases": ["local startup"],
        "mode": "local_gui",
    }
    card["source"] = {"kind": "local_path", "ref": str(package)}
    save_card(home, card)

    blocked = open_local_gui_shortcut("local startup", home=home, no_open=True)
    assert blocked["action"] == "no_local_gui_shortcut"
    assert blocked["local_routing"] == "disabled_by_default"

    result = open_local_gui_shortcut("local startup", home=home, no_open=True, allow_local=True)

    assert result["action"] == "open_gui"
    assert result["status"] == "opened"
    assert result["selected"]["id"] == "local/startup-gui"
    assert result["launcher_result"]["status"] == "gui_ready"


def test_local_gui_shortcut_requires_exact_opt_in_phrase(tmp_path):
    home = tmp_path / "networking"
    init_networking(home)
    card = make_ready_card(
        tmp_path,
        "startup-gui",
        triggers_ko=["스타트업 열어줘", "창업 gui"],
        triggers_en=["startup", "startup founder studio", "open startup gui"],
        antis=["legal", "payment", "deploy"],
        capabilities=["open_startup_gui"],
    )
    card["network_shortcut"] = {
        "enabled": True,
        "phrases": ["startup"],
        "mode": "local_gui",
    }
    save_card(home, card)

    result = open_local_gui_shortcut("startup market research", home=home, no_open=True)

    assert result == {
        "action": "no_local_gui_shortcut",
        "status": "not_found",
        "query": "startup market research",
        "quarantined": 0,
        "local_routing": "disabled_by_default",
        "hub_routing": "no_registered_gui_shortcut",
    }


def test_hub_gui_shortcut_preempts_local_paid_card(tmp_path, monkeypatch):
    home = tmp_path / "networking"
    init_networking(home)
    package = tmp_path / "paid-startup-package"
    package.mkdir()
    card = make_ready_card(
        tmp_path,
        "paid-startup-gui",
        triggers_ko=["스타트업"],
        triggers_en=["startup"],
        antis=["legal", "payment", "deploy"],
        capabilities=["open_startup_gui"],
    )
    card["entrypoints"] = {
        "canonical_command": "/startup",
        "agent": "agents/00-startup-orchestrator/agent.md",
        "gui_launcher": "scripts/local-open.py",
    }
    card["network_shortcut"] = {
        "enabled": True,
        "phrases": ["startup"],
        "mode": "local_gui",
    }
    card["source"] = {"kind": "local_path", "ref": str(package)}
    save_card(home, card)

    def fake_call(name, arguments=None, home=None, timeout=60):
        assert name == "marketplace.get_manifest"
        assert arguments == {"kind": "agent", "slug": "agentlas-startup-founder-studio"}
        return {
            "name": "Startup Founder Studio",
            "cloudPackage": {
                "packageHash": "sha256:test",
                "files": [
                    _cloud_file("agentlas.json", json.dumps({"ui": {"launcher": "scripts/open.py"}})),
                    _cloud_file("scripts/open.py", "print('hub')\n"),
                ],
            },
        }

    monkeypatch.setattr("agentlas_cloud.networking.gui_shortcut.call_hub_tool", fake_call)
    monkeypatch.setattr(
        "agentlas_cloud.networking.gui_shortcut._launch_python_gui",
        lambda launcher, cwd, no_open, detach: {
            "status": "opened",
            "launcher_result": {"status": "hub_ready"},
            "stderr": "",
            "returncode": 0,
        },
    )
    monkeypatch.setenv("AGENTLAS_CLOUD_INSTALL_HOME", str(tmp_path / "cloud-installs"))

    result = open_local_gui_shortcut("startup", home=home, no_open=True)

    assert result["action"] == "open_gui"
    assert result["source"] == "hub_cloud_package"
    assert result["local_routing"] == "skipped"
    assert result["hub_routing"] == "cloud_package_installed"
    assert "selected" not in result
