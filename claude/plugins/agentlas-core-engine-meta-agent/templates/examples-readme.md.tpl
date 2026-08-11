# Examples

This folder is optional. {{PACKAGE_NAME}}'s one publish-validated example
already lives at `contracts/output.example.json` — the publish gate checks it
against `contracts/output.schema.json` with a JSON Schema validator, never a
model.

Add few-shot or reference input/output pairs here only when a single example
is not enough to show this agent's range (e.g. multiple distinct request
shapes). Keep `contracts/output.example.json` as the one example every
consumer can rely on being schema-valid; anything added here is illustrative,
not gate-checked.
