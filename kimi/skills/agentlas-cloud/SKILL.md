---
name: agentlas-cloud
description: Staff a task only from the signed-in owner's Agent Cloud agents.
---
# agentlas-cloud

Identical to `/skill:hep-cloud` and `/agentlas cloud <request>`. Locate the
sibling skill directory `hep-cloud` (i.e. `../hep-cloud/SKILL.md` relative to
this file, under the same `kimi/skills/` root this skill was loaded from), read
its `SKILL.md`, and follow its instructions exactly — treating everything typed
after `/skill:agentlas-cloud` as that command's request.

Do not improvise a separate workflow and do not summarize `hep-cloud/SKILL.md`
from memory; that file is the sole authority for this command's behavior.
