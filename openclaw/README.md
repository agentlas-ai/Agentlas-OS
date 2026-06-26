# OpenClaw Adapter

OpenClaw loads skills from `~/.openclaw/skills` and `~/.agents/skills`
(AgentSkills spec). User-invocable skills are exposed as slash commands —
`/skill hephaestus-network <request>` always works; native `/hep-network`
registration follows the gateway's `commands.nativeSkills` setting.

`scripts/install-all-runtimes.sh` installs the skill automatically. Manual
install options:

```bash
# via the OpenClaw skills installer (preferred)
openclaw skills install ./openclaw/skills/hephaestus-network --global

# or plain copy
mkdir -p ~/.openclaw/skills
cp -R openclaw/skills/hephaestus-network ~/.openclaw/skills/
```

This copy differs from the canonical `skills/hephaestus-network/SKILL.md` only
by the OpenClaw `metadata` frontmatter line (binary gating + emoji). Keep the
body in sync when the canonical skill changes.

The runner itself is installed by the one-touch installer to
`~/.agentlas/runtime/current/bin/hephaestus`; the skill gates on `python3`
being available on PATH.

The OpenClaw skills include the app-host auto-update preflight. When OpenClaw's
`exec` tool is available, the skill tries to refresh
`~/.agentlas/runtime/current` from inside OpenClaw before resolving the runner,
without asking the user to open a separate terminal.
