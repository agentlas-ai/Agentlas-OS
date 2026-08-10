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

## Agentlas One session checkpoint

`hooks/agentlas-one/` is a hook pack for the Agentlas One memory checkpoint.
The installer registers it with `openclaw hooks install`, falling back to a copy
into `~/.openclaw/hooks/agentlas-one` when the CLI is unavailable.

OpenClaw has no session-end event. `/new` and `/reset` are the points where a
session stops growing, so the pack listens on `command:new` and
`command:reset` and reads `context.previousSessionEntry.sessionFile` — the
transcript of the session that just closed, not the one starting now.

Only `## Memory Events` envelopes written by the assistant are read. Raw
prompts and transcripts are never stored or sent anywhere. Every failure path
is silent: a missing runner or transcript harvests nothing and never interrupts
a session. `agentlas-one off` removes the pack.
