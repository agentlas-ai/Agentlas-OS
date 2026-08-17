---
name: agentlas-upload
description: Upload an Agentlas agent after asking Cloud vs Hub first.
---
# agentlas-upload

Identical to `/skill:hep-upload` and `/agentlas upload <request>`. Locate the
sibling skill directory `hep-upload` (i.e. `../hep-upload/SKILL.md` relative to
this file, under the same `kimi/skills/` root this skill was loaded from), read
its `SKILL.md`, and follow its instructions exactly — treating everything typed
after `/skill:agentlas-upload` as that command's request.

Do not improvise a separate workflow and do not summarize `hep-upload/SKILL.md`
from memory; that file is the sole authority for this command's behavior.
