---
description: Update the installed Agentlas runtime and every host adapter on this machine.
argument-hint: 
---
Update fallback: 자동 업데이트가 안 되면 `hephaestus update`를 한 번 실행하세요. 업데이트하지 않아도 현재 버전 명령은 그대로 동작합니다.

Update the installed Agentlas runtime and every host adapter on this machine.

Raw request: `$ARGUMENTS`

Updates normally happen on their own. This command exists for the moment they
did not: a host still loading an old bundle, a command that should exist and
does not, an adapter that never got re-registered after a release.

## Run it

```
hephaestus update
```

Report the runtime version it moved from and to, and the per-host result it
prints. Say `already up to date` plainly when nothing moved — that is a valid
outcome, not a failure to try.

## Then check the host actually picked it up

A new runtime does not mean the host is using it. Each host caches its own copy
of the adapter, and one host lagging behind is the usual reason a command is
missing after an update that reported success.

- Codex, Gemini/Antigravity, Grok, OpenCode: the updater rewrites their adapter
  directly, so the printed result is the answer.
- Claude Code installs plugins through its own marketplace. The updater refreshes
  the source it points at, but Claude Code decides when to re-copy it into
  `~/.claude/plugins/cache/`. If a command is still missing there, the plugin
  needs reinstalling from the Agentlas marketplace inside Claude Code — the
  runtime cannot force that copy.

If the user asks why a command is missing, name the layer that is behind rather
than reporting a general failure: runtime version, host adapter, or the host's
own plugin cache. Those fail separately and the fix differs for each.

## Boundaries

Never edit files under `~/.agentlas/runtime/` by hand to make a command appear.
Two programs write that tree — the installer and the updater — so a hand-placed
file survives until the next update and then vanishes, which reads as a
regression that nobody can reproduce. Fix the source and update again.
