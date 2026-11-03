"""Session-local core commands backed by structured Agentlas MCP tools."""
from __future__ import annotations

from .prompt_order import compose_prompt

COMMANDS = {
    'hep-search': {
        'module_id': 'host.standalone.command.hep-search',
        'description': 'Search Agentlas Cloud and Hub candidates without invoking an agent.',
        'body': '''# /hep-search

The operation is search, not an agent call. Find agents without invoking them.
Use the available `hephaestus_search` MCP tool with the exact text the user supplied after the command as `request` and
`limit` 10. Pass a project directory only when relevant to the request. Pass
arguments as structured tool input; do not interpolate the user's text into a
shell command. This is a search, not permission to call an agent or change a
source repository.

Show the owner's Cloud results first, followed by public Hub results. For each
candidate show its rank, name, slug, description, callability/routing status,
and why it matched when those fields were actually returned. Include saved
bookmarks if returned. Include the
returned `receipt_id`. If search is unavailable or fails, report its real
status; do not invent results, receipts, agent calls, or repository changes.
''',
    },
    'hep-call': {
        'module_id': 'host.standalone.command.hep-call',
        'description': 'Prepare the exact named Agentlas Hub or Cloud agents.',
        'body': '''# /hep-call

Call only the exact agent slugs named by the user. Syntax is
`/hep-call agent-a, agent-b {context}`; when braces are omitted, the first
space-delimited token is the agent list and the rest is context. Pass the
slugs and exact context as structured `agents` and `context` inputs to the
available `hephaestus_call` MCP tool. Do not interpolate user input into a
shell command or substitute other agents.

A `prepared` result supplies a BYOM bundle: the host model still performs the
actual work. Follow the returned `output.entry_excerpt` and
`output.grounding.directive` for prepared agents, subject to the host's own
permissions and the user's request. Do not claim completion without execution
evidence. If a legacy response says `insufficient_credits`, do not run that
agent or suggest a top-up. Continue with any other prepared agents, list each
failure and its real status, and never fabricate an agent run by role-playing
from local files. Include the top-level `receipt_id` and each prepared
`execution_id` when returned. Scheduled work uses the host's own model, keys,
permissions, and runtime capacity; do not purchase a retired Hub lease.
''',
    },
    'hep-goal': {
        'module_id': 'host.standalone.command.hep-goal',
        'description': 'Create and review a goal plan tree using the host goal and observed evidence.',
        'body': '''# /hep-goal

Add a plan tree and KPI checks to the host's goal; the host still decides when
work is complete. The first operation is `action: schema` using the available
`goal.strategy` MCP tool. Obtain and follow its field lists before `start`. Choose `single_tactic`
for a short task with one clear check, `tactic_list` for several known steps,
or `mission_tree` for a longer goal with a target the owner actually supplied.
Use the owner's exact goal text and never invent a target or owner boundary.
Pass all values as structured tool arguments, not shell-interpolated text.

Use `action: start` with `projectDir`, the exact `goalText`, and the plan as
`payload` to store the requested plan. For subsequent actions, pass the same
`projectDir` and returned `goalId`. After storing a `single_tactic`, continue
with the host goal. For another explicitly active goal, read `context` before a turn, do the named tactics, and record KPI readings
with the observed value, time, source, and evidence. A second independent
reading may be marked reobserved; never invent a reading. When review is due,
use `review` and cite the relevant samples for one of `hold`, `pivot`,
`double_down`, or `escalate_owner`. If the result holds for the owner, report
the current, needed-per-day, and observed-per-day values and wait for their
answer before replanning; use `owner_answer` for that response. Supply a
unique idempotency `key` for calls that may be retried. Report the actual
strategy mode and any tool failure without claiming unobserved changes.
''',
    },
}


def command_payloads(root, host: str, read) -> dict[str, bytes]:
    """Render the same registered command body for either supported host."""
    if host not in ('claude', 'codex'):
        raise ValueError('unsupported_host')
    result = {}
    for name, spec in COMMANDS.items():
        body = compose_prompt([{'id': spec['module_id'],
            'revision': 1, 'stability': 'versioned-content',
            'changeTriggers': ['release', 'skill-package'], 'channel': 'user',
            'order': 0, 'text': spec['body']}])
        if host == 'claude':
            front = '---\ndescription: ' + spec['description'] + '\n---\n\n'
            path = 'commands/' + name + '.md'
        else:
            front = '---\nname: ' + name + '\ndescription: ' + spec['description'] + '\n---\n\n'
            path = 'skills/' + name + '/SKILL.md'
        result[path] = (front + body).encode('utf-8')
    return result
