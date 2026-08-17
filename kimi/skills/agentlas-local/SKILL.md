---
name: agentlas-local
description: Staff a task only from Agentlas agents registered on this machine.
---
# agentlas-local

Identical to `/skill:hep-local` and `/agentlas local <request>`. Locate the
sibling skill directory `hep-local` (i.e. `../hep-local/SKILL.md` relative to
this file, under the same `kimi/skills/` root this skill was loaded from), read
its `SKILL.md`, and follow its instructions exactly — treating everything typed
after `/skill:agentlas-local` as that command's request.

Do not improvise a separate workflow and do not summarize `hep-local/SKILL.md`
from memory; that file is the sole authority for this command's behavior.
