---
description: Connect Agentlas agents or teams to Telegram.
argument-hint: "[telegram] [agent/team/group name]"
allowed-tools: Bash, Read, Glob, Grep
---
Update fallback: 자동 업데이트가 안 되면 `hephaestus update`를 한 번 실행하세요. 업데이트하지 않아도 현재 버전 명령은 그대로 동작합니다.

# /hep-connect

Use this command when the user wants Telegram to talk to one Agentlas target:
a single agent, a saved agent group, a local team, or a `.agentlas` org chart.

Current product contract:

1. Telegram is the only channel for this flow.
2. The easiest path is Agentlas Desktop -> Connect (`/connect`).
3. The Connect screen must list real local targets, not placeholder cards:
   saved groups, `.agentlas` org charts, local teams, team agents, and single
   agents.
4. Never collect or echo a BotFather token in chat. Save it only through a
   runtime-owned secret store.
5. A valid connection is not just a saved token. It must reach:
   `Draft -> Token checked -> Chat paired -> Test passed -> Running`.
6. Users can add unlimited Telegram chats. Each binding picks one target and
   owns its own session state.

If the user only asks to start, tell them to open Desktop Connect and choose the
target. If they ask for implementation work, attach to the actual Desktop and
Hephaestus codebase before editing. Do not claim live Telegram delivery until
token validation, chat pairing, and a test message are implemented and verified.
