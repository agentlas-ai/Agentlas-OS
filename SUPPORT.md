# Support

## Install or setup not working

1. Re-run the installer and check which runtime failed:
   ```bash
   curl -fsSL https://raw.githubusercontent.com/agentlas-ai/Hephaestus/main/scripts/install-all-runtimes.sh | bash
   ```
2. Check the runtime support matrix: [docs/runtime-fallback-adapters.md](docs/runtime-fallback-adapters.md)
3. Still stuck? Open a thread in
   [Discussions → Help / Install](https://github.com/agentlas-ai/Hephaestus/discussions)
   with the failing runtime, your OS, and the installer output.

## Something is broken (bug)

Open a [GitHub Issue](https://github.com/agentlas-ai/Hephaestus/issues/new/choose)
with a repro — the command you ran and what happened instead of what you
expected. Run `scripts/verify-package.sh` first; if it fails, paste that
output too.

## Questions, ideas, "can it do X"

[Discussions](https://github.com/agentlas-ai/Hephaestus/discussions) —
`Ideas / RFC` for feature proposals, `Show and Tell` if you built something
on top of this, `Adapters` for runtime-specific questions (Claude Code,
Codex, Gemini, Cursor, Ollama).

## Security issue

Do not open a public issue. See [SECURITY.md](SECURITY.md).
