#!/usr/bin/env node

import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const fixturePath = path.join(
  ROOT,
  "benchmarks",
  "workforce-ontology",
  "capability-binding-v1-vectors.json",
);
const vectors = JSON.parse(fs.readFileSync(fixturePath, "utf8"));

function canonical(value) {
  if (Array.isArray(value)) return value.map(canonical);
  if (value !== null && typeof value === "object") {
    return Object.fromEntries(
      Object.keys(value).sort().map((key) => [key, canonical(value[key])]),
    );
  }
  return value;
}

function digest(value) {
  const encoded = JSON.stringify(canonical(value));
  return `sha256:${crypto.createHash("sha256").update(encoded, "utf8").digest("hex")}`;
}

for (const vector of vectors.accepted) {
  const observedInventoryDigest = digest({
    schemaVersion: "agentlas.workforce-tool-inventory-digest.v1",
    toolInventory: vector.toolInventory,
  });
  if (observedInventoryDigest !== vector.expectedToolInventoryDigest) {
    throw new Error(`${vector.name}: tool inventory digest mismatch`);
  }
  const { bindingPlanDigest: _claimedDigest, ...bindingPlan } = vector.capabilityBindingPlan;
  const observedBindingDigest = digest({
    schemaVersion: "agentlas.workforce-capability-binding-plan-digest.v1",
    capabilityBindingPlan: bindingPlan,
  });
  if (observedBindingDigest !== vector.expectedBindingPlanDigest) {
    throw new Error(`${vector.name}: capability binding plan digest mismatch`);
  }
}

console.log(`workforce capability binding v1 vectors: PASS (${vectors.accepted.length} accepted)`);
