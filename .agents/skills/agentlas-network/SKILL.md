---
name: agentlas-network
description: "Use when the user types /agentlas-network, /agentlas network, $hephaestus-network, or /hep-network to staff a durable goal from registered Local, owner Cloud, and public Hub agents or teams."
---

# Agentlas Network Workforce (/agentlas-network, /hep-network)

Federated Local + Cloud + Hub workforce staffing orchestrator.
Alias for `hephaestus-network` and `/agentlas network`.

## Required MCP sequence
```text
workforce.search_candidates(sourceScope="network")
workforce.validate_selection(workOrder=..., selection=...)
workforce.prepare_execution(workOrder=..., selection=..., federatedSelection=..., projectDir=..., goalId=activeGoalId?)
workforce.validate_execution_receipt(receipt=..., executionPlan=..., toolInventory=...)
```

See [hephaestus-network](hephaestus-network/SKILL.md) for full execution protocol.
