---
name: hep-connect
description: Start the Agentlas Connect flow for Telegram.
---
Update fallback: 자동 업데이트가 안 되면 `hephaestus update`를 한 번 실행하세요. 업데이트하지 않아도 현재 버전 명령은 그대로 동작합니다.

# Hephaestus Connect

Raw arguments: everything the user typed after `/skill:hep-connect`.

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
