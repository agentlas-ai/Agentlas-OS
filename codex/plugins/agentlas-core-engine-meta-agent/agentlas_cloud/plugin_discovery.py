"""Local + hub plugin discovery for the Agentlas runtime.

The hub contract: when an agent is invoked through the agentlas MCP, the
tools/plugins it uses must be resolvable from BOTH (1) plugins already
installed on this machine and (2) the Agentlas Hub catalog. This module is
the local half of that contract — it scans the standard install locations,
queries the hub's public ``/api/plugins`` endpoint (server-side counterpart:
``agentlas.resolve_plugins`` MCP tool), and merges the two views.

Local always wins; hub entries that are not installed yet come back as
``installable`` with their install CLI and manifest URL. The hub call is
best-effort: offline machines still get the full local inventory.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_HUB_URL = "https://agentlas.cloud"

# One list with the web side (AgentsAtlas app, lib/search/stopwords.ts). Words
# that cannot describe work: before this filter, a query carrying ordinary
# English glue matched most of the catalogue because matching is substring
# containment ("it" hits "edit", "the" hits "theme"). Question words
# (how/why/when/where) stay out of the list on purpose — they carry intent.
_SEARCH_STOPWORDS = frozenset("""
agent agents an a the for to i me my that which what want need needs find search
please help with do does can is are and or of in on at by from as it its this
these those they their there then be was were been being am our us you your we
he she him her them into about over than too very just also any all some more
most other own same such both each few had has have here next up out off so if
but no not
""".split())


def _search_tokens(text: str) -> list[str]:
    return [
        token
        for token in (text or "").lower().split()
        if len(token) >= 2 and token not in _SEARCH_STOPWORDS
    ]
_HUB_TIMEOUT_SECONDS = 6
_SCAN_MAX_DEPTH = 6

HOW_TO_LOAD = [
    "local matches → load the installed plugin as-is (skills + .mcp.json it ships).",
    "installable → install with install_cli (or fetch manifest_url for the agentlas.plugin/v1 payload), then load.",
    "unresolved needs → surface to the user; never fabricate a tool.",
]


def hub_base_url() -> str:
    return os.environ.get("AGENTLAS_HUB_URL", DEFAULT_HUB_URL).rstrip("/")


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def local_search_locations(project_dir: Path) -> list[dict[str, str]]:
    home = Path(os.path.expanduser("~"))
    codex_home = Path(os.environ.get("CODEX_HOME", str(home / ".codex")))
    return [
        # 1순위: 세 채널(데스크탑·터미널·Agentlas-OS)이 공유하는 Agentlas 플러그인
        # 저장소. `agentlas plugin add` / 데스크탑 마켓플레이스 설치가 <slug>/plugin.json
        # (schema agentlas.local-plugin/v1) 마커와 skills/ 파일을 여기에 착지시킨다.
        {"kind": "agentlas_store", "path": str(home / ".agentlas" / "plugins"), "runtime": "any"},
        {"kind": "plugin_tree", "path": str(home / ".claude" / "plugins"), "runtime": "claude-code"},
        {"kind": "plugin_tree", "path": str(codex_home / "plugins" / "cache"), "runtime": "codex"},
        {"kind": "plugin_tree", "path": str(project_dir / "claude" / "plugins"), "runtime": "claude-code"},
        {"kind": "plugin_tree", "path": str(project_dir / "codex" / "plugins"), "runtime": "codex"},
        {"kind": "registry", "path": str(project_dir / ".claude-plugin" / "marketplace.json"), "runtime": "claude-code"},
        {"kind": "registry", "path": str(project_dir / "claude" / ".claude-plugin" / "marketplace.json"), "runtime": "claude-code"},
        {"kind": "registry", "path": str(project_dir / ".agents" / "plugins" / "marketplace.json"), "runtime": "any"},
        {"kind": "registry", "path": str(project_dir / "codex" / ".agents" / "plugins" / "marketplace.json"), "runtime": "codex"},
    ]


def _registry_entries(path: Path) -> list[dict[str, Any]]:
    payload = _read_json(path)
    if not isinstance(payload, dict):
        return []
    entries: list[dict[str, Any]] = []
    for plugin in payload.get("plugins") or []:
        if not isinstance(plugin, dict):
            continue
        name = plugin.get("name")
        if not name:
            continue
        source = plugin.get("source")
        if isinstance(source, dict):
            source = source.get("path")
        entries.append(
            {
                "name": str(name),
                "version": plugin.get("version"),
                "description": str(plugin.get("description") or ""),
                "origin": "marketplace_registry",
                "location": str(path),
                "source": str(source) if source else None,
            }
        )
    return entries


def _plugin_tree_entries(root: Path) -> list[dict[str, Any]]:
    if not root.is_dir():
        return []
    entries: list[dict[str, Any]] = []
    for manifest_dir_name in (".claude-plugin", ".codex-plugin"):
        for manifest_path in root.rglob(f"{manifest_dir_name}/plugin.json"):
            try:
                relative_depth = len(manifest_path.relative_to(root).parts)
            except ValueError:
                continue
            if relative_depth > _SCAN_MAX_DEPTH:
                continue
            payload = _read_json(manifest_path)
            if not isinstance(payload, dict):
                continue
            name = payload.get("name") or payload.get("id")
            if not name:
                continue
            entries.append(
                {
                    "name": str(name),
                    "version": payload.get("version"),
                    "description": str(payload.get("description") or ""),
                    "origin": "installed_plugin",
                    "location": str(manifest_path.parent.parent),
                    "source": None,
                }
            )
    return entries


def _agentlas_store_entries(root: Path) -> list[dict[str, Any]]:
    """~/.agentlas/plugins/<slug>/plugin.json markers (agentlas.local-plugin/v1).

    데스크탑 hub-plugin-bridge.installSkillBundle / 터미널 engine/hub/plugins.cjs
    installPluginSkills 가 쓰는 공유 규약의 스캔 절반. 마커 없는 디렉터리는 다른
    도구의 산출물일 수 있어 조용히 건너뛴다.
    """
    if not root.is_dir():
        return []
    entries: list[dict[str, Any]] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        payload = _read_json(child / "plugin.json")
        if not isinstance(payload, dict):
            continue
        name = payload.get("slug") or payload.get("name") or child.name
        skills = payload.get("skills")
        skill_names = (
            [str(item.get("name")) for item in skills if isinstance(item, dict) and item.get("name")]
            if isinstance(skills, list)
            else []
        )
        entries.append(
            {
                "name": str(name),
                "version": payload.get("version"),
                "description": ", ".join(skill_names) if skill_names else str(payload.get("name") or ""),
                "origin": "agentlas_plugin_store",
                "location": str(child),
                "source": None,
            }
        )
    return entries


def scan_local_plugins(project_dir: Path | str = ".") -> dict[str, Any]:
    project = Path(project_dir).resolve()
    locations = local_search_locations(project)
    plugins: dict[str, dict[str, Any]] = {}
    for location in locations:
        path = Path(location["path"])
        if location["kind"] == "registry":
            found = _registry_entries(path)
        elif location["kind"] == "agentlas_store":
            found = _agentlas_store_entries(path)
        else:
            found = _plugin_tree_entries(path)
        for entry in found:
            key = entry["name"].lower()
            existing = plugins.get(key)
            if existing is None:
                entry["locations"] = [entry.pop("location")]
                plugins[key] = entry
            else:
                location_value = entry["location"]
                if location_value not in existing["locations"]:
                    existing["locations"].append(location_value)
    return {
        "project": str(project),
        "search_locations": locations,
        "count": len(plugins),
        "plugins": sorted(plugins.values(), key=lambda item: item["name"]),
    }


def fetch_hub_plugins(query: str = "") -> dict[str, Any]:
    base = hub_base_url()
    url = f"{base}/api/plugins"
    if query:
        url += "?" + urllib.parse.urlencode({"q": query})
    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "hephaestus-plugin-discovery"})
    try:
        with urllib.request.urlopen(request, timeout=_HUB_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        return {"hub": base, "status": "unreachable", "detail": str(exc), "plugins": []}
    plugins = payload.get("plugins") if isinstance(payload, dict) else None
    if not isinstance(plugins, list):
        return {"hub": base, "status": "unexpected_response", "plugins": []}
    return {"hub": base, "status": "ok", "plugins": plugins}


def resolve_plugins(query: str, project_dir: Path | str = ".", use_hub: bool = True) -> dict[str, Any]:
    local = scan_local_plugins(project_dir)
    tokens = _search_tokens(query)

    def matches_local(entry: dict[str, Any]) -> bool:
        haystack = f"{entry['name']} {entry.get('description', '')}".lower()
        return any(token in haystack for token in tokens) if tokens else True

    local_matches = [entry for entry in local["plugins"] if matches_local(entry)]
    local_names = {entry["name"].lower() for entry in local["plugins"]}

    hub_result = fetch_hub_plugins(query) if use_hub else {"hub": hub_base_url(), "status": "skipped", "plugins": []}
    already_local: list[dict[str, Any]] = []
    installable: list[dict[str, Any]] = []
    for plugin in hub_result["plugins"]:
        if not isinstance(plugin, dict):
            continue
        slug = str(plugin.get("slug") or "").lower()
        name = str(plugin.get("name") or "").lower()
        install = plugin.get("install")
        install_cli = plugin.get("installCli") or (install.get("cli") if isinstance(install, dict) else None)
        summary = {
            "slug": plugin.get("slug"),
            "name": plugin.get("name"),
            "family": plugin.get("family"),
            "category": plugin.get("category"),
            "tagline_ko": plugin.get("taglineKo"),
            "auth": plugin.get("auth"),
            "install_cli": install_cli,
            "manifest_url": f"{hub_result['hub']}{plugin['manifestHref']}" if plugin.get("manifestHref") else f"{hub_result['hub']}/api/plugins/{plugin.get('slug')}",
        }
        if slug in local_names or name in local_names:
            already_local.append(summary)
        else:
            installable.append(summary)

    return {
        "query": query,
        "local": {"count": len(local_matches), "matches": local_matches, "inventory_count": local["count"]},
        "hub": {"url": hub_result["hub"], "status": hub_result["status"], "already_local": already_local, "installable": installable},
        "unresolved": not local_matches and not already_local and not installable,
        "how_to_load": HOW_TO_LOAD,
        "search_locations": local["search_locations"],
    }


# ── Two-tier tool search over installed plugin routing cards ─────────────────
#
# Layer contract: docs 2026-08-25-workforce-routing-v2/TOOLSEARCH-SCHEMAS.md.
# Tier 1 ranks plugin/server cards by stopword-filtered keyword overlap over
# name, summary and trigger examples; tier 2 looks only at the winners'
# capability entries. The response never carries an input schema — measured on
# the 43-card corpus, a 4-candidate shortlist plus one loaded schema is ~2.4%
# of shipping everything (244 vs 9,982 estimated tokens).

_READ_PREFIXES = ("get_", "read_", "list_", "search_", "inspect_", "query_", "check_")
_DESTRUCTIVE_PREFIXES = ("delete_", "remove_", "drop_", "wipe_")


def _card_search_rows(root) -> list[dict]:
    import glob as _glob
    rows = []
    base = Path(root)
    for card_path in sorted(_glob.glob(str(base / "*" / ".agentlas" / "routing-card.json"))):
        try:
            card = json.loads(Path(card_path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(card, dict) or not card.get("id"):
            continue
        examples = [
            (entry.get("text") if isinstance(entry, dict) else str(entry)) or ""
            for entry in (card.get("trigger_examples") or [])
        ]
        rows.append({
            "slug": str(card["id"]).split("/")[-1],
            "name": card.get("name") or card["id"],
            "summary": card.get("summary") or "",
            "haystack": " ".join([
                str(card["id"]), card.get("name") or "", card.get("summary") or "",
                " ".join(examples),
                " ".join(str(c).replace("_", " ") for c in (card.get("capabilities") or [])),
            ]).lower(),
            "tools": [
                {
                    "name": cap,
                    "summary": str(cap).replace("_", " "),
                    "effects": {
                        "readOnly": str(cap).startswith(_READ_PREFIXES),
                        "destructive": str(cap).startswith(_DESTRUCTIVE_PREFIXES),
                    },
                }
                for cap in (card.get("capabilities") or [])
            ],
        })
    return rows


def tool_search(
    need: str,
    plugin_root: Path | str,
    *,
    limit: int = 4,
    forbid_destructive: bool = False,
) -> dict:
    rows = _card_search_rows(plugin_root)
    tokens = _search_tokens(need)
    if not tokens:
        return {"schemaVersion": "agentlas.tool-search-result.v1", "candidates": [], "degraded": ["empty_need"]}
    import math as _math
    df: dict[str, int] = {}
    for row in rows:
        for token in set(row["haystack"].split()):
            df[token] = df.get(token, 0) + 1
    def _idf(token: str) -> float:
        return _math.log(1 + len(rows) / (1 + df.get(token, 0)))
    ranked = sorted(
        (
            (sum(_idf(t) for t in tokens if t in row["haystack"]), row)
            for row in rows
        ),
        key=lambda pair: -pair[0],
    )
    candidates = []
    for score, row in ranked[:8]:
        if score <= 0:
            break
        tools = [
            t for t in row["tools"]
            if not (forbid_destructive and t["effects"]["destructive"])
        ]
        scored_tools = sorted(
            tools,
            key=lambda t: -sum(1 for x in tokens if x in (t["name"] + " " + t["summary"]).lower()),
        )
        for tool in scored_tools[:2] or [None]:
            candidates.append({
                "ordinal": 0,
                "server": row["slug"],
                "serverName": row["name"],
                "tool": tool["name"] if tool else None,
                "summary": tool["summary"] if tool else row["summary"],
                "effects": tool["effects"] if tool else None,
                "installed": True,
            })
            if len(candidates) >= limit:
                break
        if len(candidates) >= limit:
            break
    for index, candidate in enumerate(candidates):
        candidate["ordinal"] = index + 1
    return {"schemaVersion": "agentlas.tool-search-result.v1", "candidates": candidates, "degraded": []}
