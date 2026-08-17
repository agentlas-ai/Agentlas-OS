---
name: agentlas-graph
description: Build an Agentlas automation by describing it, list saved ones, or request a run.
---
# agentlas-graph

Identical to `/skill:hep-graph` and `/agentlas graph <request>`. Locate the
sibling skill directory `hep-graph` (i.e. `../hep-graph/SKILL.md` relative to
this file, under the same `kimi/skills/` root this skill was loaded from), read
its `SKILL.md`, and follow its instructions exactly — treating everything typed
after `/skill:agentlas-graph` as that command's request.

Do not improvise a separate workflow and do not summarize `hep-graph/SKILL.md`
from memory; that file is the sole authority for this command's behavior.
