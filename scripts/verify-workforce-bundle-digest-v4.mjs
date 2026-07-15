#!/usr/bin/env node

import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const vectors = JSON.parse(fs.readFileSync(
  path.join(root, "benchmarks/workforce-ontology/runtime-bundle-digest-v4-vectors.json"),
  "utf8",
));

const KEY_RE = /^[A-Za-z_$][A-Za-z0-9_.$:/@+~-]*$/u;
const ID_RE = /^[A-Za-z0-9][A-Za-z0-9._:/@-]{1,255}$/u;
const PATH_RE = /^[A-Za-z0-9._@+~*?/-]{1,240}$/u;
const MCP_TOOL_RE = /^[A-Za-z0-9][A-Za-z0-9_.$:/@+~-]{0,127}$/u;
const LONE_SURROGATE_RE = /[\uD800-\uDFFF]/u;
const RESERVED_KEYS = new Set(["__proto__", "prototype", "constructor"]);
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
        if (!KEY_RE.test(key) || RESERVED_KEYS.has(key)) throw new Error("digest object key is unsafe");
        visit(child, depth + 1);
      }
      return;
    }
    throw new Error("digest value is not interoperable JSON");
  }
  visit(value, 0);
}

function exactKeys(value, expected) {
  const keys = Object.keys(value).sort();
  if (keys.join("\0") !== [...expected].sort().join("\0")) throw new Error("object keys differ");
}

function stringList(value, maximum, pattern) {
  if (!Array.isArray(value) || value.length > maximum || new Set(value).size !== value.length) {
    throw new Error("string list invalid");
  }
  for (const item of value) {
    if (typeof item !== "string" || !item || !pattern.test(item)) throw new Error("string item invalid");
  }
  return value;
}

function packagePatterns(value) {
  stringList(value, 128, PATH_RE);
  for (const item of value) {
    if (item.startsWith("/") || item.includes("\\") || item.split("/").includes("..")) {
      throw new Error("package pattern unsafe");
    }
  }
  return value;
}

function validatePolicy(policy) {
  if (!policy || Object.getPrototypeOf(policy) !== Object.prototype) throw new Error("policy invalid");
  exactKeys(policy, ["schemaVersion", "network", "shell", "fileRead", "mcp", "unknownTools"]);
  if (policy.schemaVersion !== vectors.permissionPolicySchemaVersion) throw new Error("policy schema invalid");
  if (!["allow", "ask", "deny"].includes(policy.network)) throw new Error("network invalid");
  if (!["allow", "ask", "deny"].includes(policy.shell)) throw new Error("shell invalid");
  if (policy.unknownTools !== "deny") throw new Error("unknown tools must deny");
  exactKeys(policy.fileRead, ["mode", "allowPatterns", "denyPatterns"]);
  const allow = packagePatterns(policy.fileRead.allowPatterns);
  const deny = packagePatterns(policy.fileRead.denyPatterns);
  if (policy.fileRead.mode === "deny") {
    if (allow.length || deny.length) throw new Error("denied file lists nonempty");
  } else if (policy.fileRead.mode === "manifest-allowlist") {
    if (!allow.length || !deny.length) throw new Error("file allowlist incomplete");
  } else throw new Error("file mode invalid");
  exactKeys(policy.mcp, ["mode", "allowedTools"]);
  const tools = stringList(policy.mcp.allowedTools, 128, MCP_TOOL_RE);
  if (policy.mcp.mode === "deny") {
    if (tools.length) throw new Error("denied MCP list nonempty");
  } else if (policy.mcp.mode === "allowlist") {
    if (!tools.length) throw new Error("MCP allowlist empty");
  } else throw new Error("MCP mode invalid");
}

function packagePath(value) {
  if (typeof value !== "string" || !PATH_RE.test(value) || value.includes("*") || value.includes("?")
      || value.startsWith("/") || value.includes("\\") || value.split("/").includes("..")) {
    throw new Error("package path invalid");
  }
}

function validateGraph(graph) {
  exactKeys(graph, ["schemaVersion", "manager", "workers"]);
  if (graph.schemaVersion !== vectors.executionGraphSchemaVersion) throw new Error("graph schema invalid");
  exactKeys(graph.manager, ["path", "content"]);
  packagePath(graph.manager.path);
  if (typeof graph.manager.content !== "string" || !graph.manager.content.trim()) throw new Error("manager missing");
  if (!Array.isArray(graph.workers) || graph.workers.length < 1 || graph.workers.length > 32) {
    throw new Error("workers invalid");
  }
  const ids = new Set();
  const paths = new Set([graph.manager.path]);
  for (const worker of graph.workers) {
    exactKeys(worker, ["id", "path", "content"]);
    if (!ID_RE.test(worker.id) || ids.has(worker.id)) throw new Error("worker id invalid");
    packagePath(worker.path);
    if (paths.has(worker.path)) throw new Error("worker path duplicate");
    if (typeof worker.content !== "string" || !worker.content.trim()) throw new Error("worker content invalid");
    ids.add(worker.id);
    paths.add(worker.path);
  }
}

function encodeCanonical(value) {
  if (value === null || typeof value === "boolean" || typeof value === "string") return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(encodeCanonical).join(",")}]`;
  return `{${Object.keys(value).sort().map(
    (key) => `${JSON.stringify(key)}:${encodeCanonical(value[key])}`,
  ).join(",")}}`;
}

function canonicalPayload(rowPatch) {
  const row = { ...vectors.baseRosterRow, ...rowPatch };
  if (!row.directiveBundle || !["systemPrompt", "instructions", "agentMd"].some(
    (key) => typeof row.directiveBundle[key] === "string" && row.directiveBundle[key].trim(),
  )) throw new Error("directive missing");
  validatePolicy(row.permissionPolicy);
  if (row.entityKind === "agent") {
    if (row.executionGraph !== null) throw new Error("agent graph forbidden");
  } else if (row.entityKind === "team") {
    if (!row.executionGraph) throw new Error("team graph missing");
    validateGraph(row.executionGraph);
  } else throw new Error("entity kind invalid");
  const payload = {
    schemaVersion: vectors.digestSchemaVersion,
    slotId: row.slotId,
    agentDefinitionId: row.agentDefinitionId,
    agentReleaseId: row.agentReleaseId,
    releaseVersion: row.releaseVersion,
    packageHash: row.packageHash,
    contentDigest: row.contentDigest,
    entityKind: row.entityKind,
    directiveBundle: row.directiveBundle,
    permissionPolicy: row.permissionPolicy,
    executionGraph: row.executionGraph,
  };
  validateDigestValue(payload);
  return encodeCanonical(payload);
}

for (const vector of vectors.accepted) {
  const canonical = canonicalPayload(vector.rosterRow);
  if (vector.canonicalJson !== undefined && canonical !== vector.canonicalJson) {
    throw new Error(`${vector.vectorId}: canonical bytes mismatch`);
  }
  const digest = `sha256:${crypto.createHash("sha256").update(canonical, "utf8").digest("hex")}`;
  if (digest !== vector.bundleDigest) throw new Error(`${vector.vectorId}: digest mismatch`);
}

for (const vector of vectors.rejected) {
  let rejected = false;
  try { canonicalPayload(vector.rosterRow); } catch { rejected = true; }
  if (!rejected) throw new Error(`${vector.vectorId}: invalid policy/graph/value was accepted`);
}

for (const numeric of [NaN, Infinity, -Infinity, -0]) {
  let rejected = false;
  try { canonicalPayload({ directiveBundle: { instructions: "x", numeric } }); } catch { rejected = true; }
  if (!rejected) throw new Error("programmatic non-finite or negative-zero number was accepted");
}

console.log(`workforce digest v4 cross-language vectors: PASS (${vectors.accepted.length} accepted, ${vectors.rejected.length} rejected)`);
