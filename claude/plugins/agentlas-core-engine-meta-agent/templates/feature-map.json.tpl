{
  "schemaVersion": "agentlas.feature-map.v1",
  "projectId": "{{projectId}}",
  "usage": "Cross-surface FEATURE-INTENT map for this project. One row = one product feature keyed by intent, not spelling: featureId + intent{ko,en} + one pointer per surface with the EXACT current identifier (symbol/route/table/wire id). Register a feature here BEFORE it exists on a second surface; when a bound identifier is renamed, update this map in the same change. A surface's repo resolves as a sibling checkout next to this project (this project's own name resolves to itself). Discipline: contracts/feature-map.md in the Agentlas engine repo. Gate: python3 scripts/verify-feature-map.py --map <this file> (rename alarm, honest SKIP for absent siblings). Query: hephaestus feature-map lookup <identifier>.",
  "features": []
}
