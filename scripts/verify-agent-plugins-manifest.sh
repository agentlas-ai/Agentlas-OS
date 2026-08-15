#!/usr/bin/env bash
# Agent Plugins 1.0 manifest gate (PRD 2026-08-15 OS-8).
#
# The spec (agent-plugins.org, v1.0.0, 2026-08-06) fixes three things a client
# relies on: plugin.json at the plugin root with $schema + name, skills under
# skills/<name>/SKILL.md, and MCP servers in mcp.json whose stdio command stays
# inside the plugin root (./... or ${PLUGIN_ROOT}/...). Anything else here is a
# runtime-specific adapter and is checked by its own gate.
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

fail() { echo "verify-agent-plugins-manifest: $*" >&2; exit 1; }

[ -f plugin.json ] || fail "plugin.json missing at plugin root"
[ -f mcp.json ] || fail "mcp.json missing at plugin root"
[ -d skills ] || fail "skills/ missing"

python3 - <<'PY' || exit 1
import json, os, re, sys

def die(msg):
    sys.stderr.write("verify-agent-plugins-manifest: %s\n" % msg)
    sys.exit(1)

plugin = json.load(open("plugin.json", encoding="utf-8"))
if plugin.get("$schema") != "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json":
    die("plugin.json $schema must be the Agent Plugins 1.0.0 plugin schema")
name = plugin.get("name")
if not isinstance(name, str) or not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", name):
    die("plugin.json name must be a lowercase slug")
version = plugin.get("version")
if version is not None and not re.fullmatch(r"\d+\.\d+\.\d+([-+][0-9A-Za-z.-]+)?", str(version)):
    die("plugin.json version must be semver when present")

# Version stays in lock-step with the other manifests (a drift here means the
# Agent Plugins surface silently advertises an older engine).
for sibling in ("manifest.json", "gemini/extension/gemini-extension.json",
                "claude/plugins/agentlas-core-engine-meta-agent/.claude-plugin/plugin.json"):
    if os.path.isfile(sibling):
        other = json.load(open(sibling, encoding="utf-8")).get("version")
        if other and version and other != version:
            die("plugin.json version %s != %s version %s" % (version, sibling, other))

mcp = json.load(open("mcp.json", encoding="utf-8"))
if mcp.get("$schema") != "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json":
    die("mcp.json $schema must be the Agent Plugins 1.0.0 mcp schema")
servers = mcp.get("mcpServers")
if not isinstance(servers, dict) or not servers:
    die("mcp.json mcpServers must be a non-empty object")
for sid, server in servers.items():
    kind = server.get("type")
    if kind == "stdio":
        cmd = str(server.get("command", ""))
        if not (cmd.startswith("./") or cmd == "${PLUGIN_ROOT}" or cmd.startswith("${PLUGIN_ROOT}/")):
            die("mcp server %s command must stay inside the plugin root: %r" % (sid, cmd))
        if ".." in cmd.split("/"):
            die("mcp server %s command escapes the plugin root: %r" % (sid, cmd))
        local = cmd.replace("${PLUGIN_ROOT}/", "./")
        if not os.path.isfile(local):
            die("mcp server %s command does not exist: %s" % (sid, local))
        if not os.access(local, os.X_OK):
            die("mcp server %s command is not executable: %s" % (sid, local))
        cwd = server.get("cwd")
        if cwd is not None and not (str(cwd).startswith("./") or str(cwd) in ("${PLUGIN_ROOT}", "${PLUGIN_DATA}")
                                    or str(cwd).startswith("${PLUGIN_ROOT}/") or str(cwd).startswith("${PLUGIN_DATA}/")):
            die("mcp server %s cwd has an unsupported form: %r" % (sid, cwd))
    elif kind in ("streamable-http", "sse"):
        if not str(server.get("url", "")).startswith("https://"):
            die("mcp server %s remote url must be https" % sid)
    else:
        die("mcp server %s has unknown type %r" % (sid, kind))

skills = [d for d in sorted(os.listdir("skills")) if os.path.isfile(os.path.join("skills", d, "SKILL.md"))]
if not skills:
    die("no skills/<name>/SKILL.md found")
print("verify-agent-plugins-manifest: ok (%s v%s, %d skills, %d mcp servers)" % (name, version, len(skills), len(servers)))
PY
