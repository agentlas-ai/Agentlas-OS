---
description: Staff a task only from public Agentlas Hub agents.
argument-hint: '<request>'
allowed-tools: Bash, Read, Glob, Grep
---
# /agentlas-hub

Identical to `/hep-hub` and `/agentlas hub <request>`. Locate the file named `hep-hub.md` in the exact same directory this file was loaded from, read it, and follow its instructions exactly — treating everything typed after `/agentlas-hub` as that command's request.

Do not improvise a separate workflow and do not summarize `hep-hub.md` from memory; that file is the sole authority for this command's behavior.
