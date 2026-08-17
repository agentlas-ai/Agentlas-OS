---
description: Use the Agentlas browser hardpoint for browser-required work.
argument-hint: '<url-or-query>'
allowed-tools: Bash, Read, Glob, Grep
---
Update fallback: 자동 업데이트가 안 되면 `hephaestus update`를 한 번 실행하세요. 업데이트하지 않아도 현재 버전 명령은 그대로 동작합니다.

# /hep-browser

Use this when the task needs a real browser, page rendering, login-visible state,
click/form behavior, or JS-heavy evidence. Prefer the Agentlas browser hardpoint
first; do not route browser work through generic research commands unless this
command reports that the hardpoint is unavailable.

Behavior:
- `/hep-browser <url>` reads a rendered browser snapshot.
- `/hep-browser <url> "<instruction>"` or `/hep-browser <url> --act "<instruction>"`
  performs browser automation through `browser.agent_cli`, then captures a
  snapshot.
- If the Agentlas Browser CDP port is already live, the command attaches to it
  by default so logged-in Desktop/browser state is reused.
- Prefer the human-facing URL a person would type over app-shell automation
  URLs. For example, use `https://mail.google.com/` instead of
  `https://mail.google.com/mail/u/0/#inbox` unless that exact deep route is
  required. Add `--raw-url` to preserve the exact URL.
- `/hep-browser <url> --click @e1` clicks an explicit snapshot ref.
- `/hep-browser <url> --click-text "Compose"` clicks visible text without an
  LLM provider.
- Add `--wait-ms 2000` when a dynamic app opens dialogs after a short delay.
- Add `--read` to force snapshot-only mode when extra text is context rather
  than an action.
- Pass `--cdp`, `--profile`, `--auto-connect`, or `--headed` only when the user
  needs an existing Desktop/browser session or a specific browser launch mode.

Raw arguments: `$ARGUMENTS`

## Run

```bash
RUNNER=""
for candidate in \
  "$HOME/.agentlas/runtime/current/bin/hephaestus" \
  "${CLAUDE_PLUGIN_ROOT:+$CLAUDE_PLUGIN_ROOT/bin/hephaestus}" \
  "${PLUGIN_ROOT:+$PLUGIN_ROOT/bin/hephaestus}" \
  "./bin/hephaestus"
do
  if [ -n "$candidate" ] && [ -x "$candidate" ]; then RUNNER="$candidate"; break; fi
done
[ -n "$RUNNER" ] || { echo "Hephaestus runtime not found. Run the installer first." >&2; exit 1; }
"$RUNNER" hep-browser "$ARGUMENTS"
```

## Answer Shape

1. Report whether `browser.agent_cli` was mounted or needs setup.
2. If setup is needed, show `hep-browser --setup` and `hep-browser --check`.
3. Include the receipt id and the browser module chain.

## Examples

```text
/hep-browser https://example.com
/hep-browser https://example.com "click the Docs link and report what changed"
/hep-browser https://example.com --act "open the pricing section" --cdp 9222 --keep-open
/hep-browser https://mail.google.com/ --click-text "Compose" --wait-ms 2000 --keep-open
/hep-browser https://example.com "summarize this page" --read
/hep-browser login page render check
/hep-browser --setup
/hep-browser --check
```
