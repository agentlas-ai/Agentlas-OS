---
description: Add a plan tree and KPI check to the host /goal for long, measurable goals.
argument-hint: '<goal> | status | review'
allowed-tools: Bash, Read, Glob, Grep
---
# /agentlas-goal

Identical to `/hep-goal` and `/agentlas goal <request>`. Locate the file named `hep-goal.md` in the exact same directory this file was loaded from, read it, and follow its instructions exactly — treating everything typed after `/agentlas-goal` as that command's request.

Do not improvise a separate workflow and do not summarize `hep-goal.md` from memory; that file is the sole authority for this command's behavior.
