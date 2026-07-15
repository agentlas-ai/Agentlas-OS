#!/usr/bin/env node

import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const vectors = JSON.parse(fs.readFileSync(
  path.join(root, "benchmarks/workforce-ontology/runtime-bundle-digest-v2-vectors.json"),
  "utf8",
));

const KEY_RE = /^[A-Za-z_$][A-Za-z0-9_.$:/@+~-]*$/u;
const LONE_SURROGATE_RE = /[\uD800-\uDFFF]/u;
const MAX_DEPTH = 32;
const MAX_NODES = 10_000;

function validateDigestValue(value) {
  const state = { nodes: 0 };
  function visit(item, depth) {
    state.nodes += 1;
    if (state.nodes > MAX_NODES) throw new Error("digest value is too large");
    if (depth > MAX_DEPTH) throw new Error("digest value is too deeply nested");
    if (item === null || typeof item === "boolean") return;
    if (typeof item === "string") {
      if (LONE_SURROGATE_RE.test(item)) throw new Error("digest string has a lone surrogate");
      return;
    }
    if (typeof item === "number") throw new Error("digest numbers are forbidden");
    if (Array.isArray(item)) {
      for (const child of item) visit(child, depth + 1);
      return;
    }
    if (item && Object.getPrototypeOf(item) === Object.prototype) {
      for (const [key, child] of Object.entries(item)) {
        if (!KEY_RE.test(key)) throw new Error("digest object key is not an ASCII identifier");
        visit(child, depth + 1);
      }
      return;
    }
    throw new Error("digest value is not interoperable JSON");
  }
  visit(value, 0);
}

function encodeCanonical(value) {
  if (value === null || typeof value === "boolean" || typeof value === "string") {
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) return `[${value.map(encodeCanonical).join(",")}]`;
  return `{${Object.keys(value).sort().map(
    (key) => `${JSON.stringify(key)}:${encodeCanonical(value[key])}`,
  ).join(",")}}`;
}

function canonicalPayload(directiveBundle) {
  const payload = {
    schemaVersion: vectors.digestSchemaVersion,
    ...vectors.baseRosterRow,
    directiveBundle,
  };
  validateDigestValue(payload);
  return encodeCanonical(payload);
}

for (const vector of vectors.accepted) {
  const canonical = canonicalPayload(vector.directiveBundle);
  if (vector.canonicalJson !== undefined && canonical !== vector.canonicalJson) {
    throw new Error(`${vector.vectorId}: canonical bytes mismatch`);
  }
  const digest = `sha256:${crypto.createHash("sha256").update(canonical, "utf8").digest("hex")}`;
  if (digest !== vector.bundleDigest) throw new Error(`${vector.vectorId}: digest mismatch`);
}

for (const vector of vectors.rejected) {
  let rejected = false;
  try {
    canonicalPayload(vector.directiveBundle);
  } catch {
    rejected = true;
  }
  if (!rejected) throw new Error(`${vector.vectorId}: non-interoperable value was accepted`);
}

for (const numeric of [NaN, Infinity, -Infinity, -0]) {
  let rejected = false;
  try {
    canonicalPayload({ instructions: "x", numeric });
  } catch {
    rejected = true;
  }
  if (!rejected) throw new Error("programmatic non-finite or negative-zero number was accepted");
}

console.log(`workforce digest v2 cross-language vectors: PASS (${vectors.accepted.length} accepted, ${vectors.rejected.length} rejected)`);
