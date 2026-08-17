---
name: hep-browser
description: Use the Agentlas browser hardpoint for browser-required work.
---
Update fallback: 자동 업데이트가 안 되면 `hephaestus update`를 한 번 실행하세요. 업데이트하지 않아도 현재 버전 명령은 그대로 동작합니다.

# Hephaestus Browser

Raw arguments: everything the user typed after `/skill:hep-browser`.

Codex plugins cannot register slash commands, so this custom prompt is the
explicit entrypoint: `/prompts:hep-browser`.

Use this when the task needs a real browser, page rendering, login-visible state,
click/form behavior, or JS-heavy evidence. Prefer the Agentlas browser hardpoint
first.

Behavior:
- `/prompts:hep-browser <url>` reads a rendered browser snapshot.
- `/prompts:hep-browser <url> "<instruction>"` or
  `/prompts:hep-browser <url> --act "<instruction>"` performs browser
  automation through `browser.agent_cli`, then captures a snapshot.
- If the Agentlas Browser CDP port is already live, the command attaches to it
  by default so logged-in Desktop/browser state is reused.
- Prefer the human-facing URL a person would type over app-shell automation
  URLs. For example, use `https://mail.google.com/` instead of
  `https://mail.google.com/mail/u/0/#inbox` unless that exact deep route is
  required. Add `--raw-url` to preserve the exact URL.
- Use `--click @e1` or `--click-text "Compose"` for LLM-free browser
  primitives after the host has selected a ref/text target.
- Add `--wait-ms 2000` when a dynamic app opens dialogs after a short delay.
- Add `--read` to force snapshot-only mode when extra text is context rather
  than an action.

```bash
RUNNER=""
for c in "$HOME/.agentlas/runtime/current/bin/hephaestus" ./bin/hephaestus; do
  [ -x "$c" ] && RUNNER="$c" && break
done
[ -n "$RUNNER" ] || { echo "Hephaestus runtime not found. Run the installer first." >&2; exit 1; }
"$RUNNER" hep-browser "$ARGUMENTS"
```

Report whether `browser.agent_cli` mounted, whether setup is needed, and the
receipt id. For automation, also report the action, whether CDP/profile flags
were used, and the final snapshot status. If setup is needed, show
`hep-browser --setup` and `hep-browser --check`.
