# Schemas

This folder is optional. {{PACKAGE_NAME}}'s actual input/output JSON Schemas
already live at `contracts/intake.schema.json` and `contracts/output.schema.json`
— that pair is what the brief compiler and the publish-time example validator
both read, so it is the one source of truth for this package's I/O shape.

Add fixed schema files here only for I/O shapes those two files cannot express
on their own — e.g. a multimodal request/response envelope, a table format, or
a document layout a single JSON Schema pair does not capture. Do not duplicate
`contracts/*.schema.json` here: a second copy of the same shape is a drift
vector, not a safety net.
