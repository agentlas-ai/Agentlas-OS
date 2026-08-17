---
description: Connect Agentlas agents or teams to Telegram.
---
Update fallback: 자동 업데이트가 안 되면 `hephaestus update`를 한 번 실행하세요. 업데이트하지 않아도 현재 버전 명령은 그대로 동작합니다.

# Hephaestus Connect

Raw arguments: `the request typed after the command`

Use this prompt when the operator wants Telegram to talk to one Agentlas target:
a single agent, a saved group, a local team, or a `.agentlas` org chart.

Current product contract:

1. Start with Telegram only.
2. Do not ask for a BotFather token in chat. Save it only through a
   runtime-owned secret store.
3. Prefer the Agentlas Desktop Connect surface at `/connect`; it lists saved
   groups, `.agentlas` org charts, local teams, team agents, and single agents.
4. Explain the setup in simple words:
   - choose who should answer;
   - make a Telegram bot in BotFather;
   - save the token in the local secret store;
   - pair one Telegram chat;
   - send one test message;
   - keep adding more chats as needed.
5. Session state belongs to the Telegram chat binding. Team, org, and saved
   group bindings use one session per chat. Single-agent direct chats can keep
   one session per user.

If running inside Agentlas Desktop development, report that the Desktop route is
`/connect` and use the real local Connect UI as the source of truth. Do not
pretend that Telegram delivery is live until token validation, chat pairing, and
a test message pass.

## Rules carried from the other runtime copies

These lines existed in one runtime's hand-maintained copy and not in the
longest one. They are kept verbatim rather than dropped — a rule that only
one runtime enforced was still a rule someone wrote on purpose.

- # /hep-connect Use this command when the user wants Telegram to talk to one Agentlas target:
- a single agent, a saved agent group, a local team, or a `.agentlas` org chart.
- Telegram is the only channel for this flow.
- The easiest path is Agentlas Desktop -> Connect (`/connect`).
- The Connect screen must list real local targets, not placeholder cards:
- saved groups, `.agentlas` org charts, local teams, team agents, and single agents.
- Never collect or echo a BotFather token in chat.
- A valid connection is not just a saved token.
- `Draft -> Token checked -> Chat paired -> Test passed -> Running`.
- Each binding picks one target and owns its own session state.
- If the user only asks to start, tell them to open Desktop Connect and choose the target.
- If they ask for implementation work, attach to the actual Desktop and Hephaestus codebase before editing.
- Do not claim live Telegram delivery until token validation, chat pairing, and a test message are implemented and verified.
- # /hep-connect Telegram Connect is a guided setup flow for one job:
- choose who should answer in Telegram, connect a bot, pair a chat, send a test message, and keep the receipt.
- - Telegram only until this channel is reliable.
- - Show real local targets, not mock cards.
- - Token handling must go through a runtime-owned secret store.
- Do not ask the user to paste a BotFather token into ordinary chat.
- - A user can add unlimited chat bindings.
- Session memory belongs to the binding, not to the global bot.
- - Team, org, and saved-group bindings use one session per Telegram chat.
- When the Desktop app is available, use the `/connect` surface as the operator home.
- When implementation is requested, edit the real Agentlas Desktop and Hephaestus codebase and verify token check, chat pairing, test send, and delivery receipt before claiming live Telegram delivery.
