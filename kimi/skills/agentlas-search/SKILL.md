---
name: agentlas-search
description: Search Agentlas Cloud and Hub candidates without invoking agents.
---
# agentlas-search

Identical to `/skill:hep-search` and `/agentlas search <request>`. Locate the
sibling skill directory `hep-search` (i.e. `../hep-search/SKILL.md` relative to
this file, under the same `kimi/skills/` root this skill was loaded from), read
its `SKILL.md`, and follow its instructions exactly — treating everything typed
after `/skill:agentlas-search` as that command's request.

Do not improvise a separate workflow and do not summarize `hep-search/SKILL.md`
from memory; that file is the sole authority for this command's behavior.
