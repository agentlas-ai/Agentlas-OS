#!/usr/bin/env node
// @agentlas-browser-cdp-contract 10
// @agentlas-browser-cdp-writer agentlas-core
// Agentlas Browser (CDP) — general-purpose engine. Launches an Agentlas-owned
// Chrome for Testing profile with a remote debugging port, then attaches
// @playwright/mcp over CDP to provide MCP browser tools. This process proxies
// stdio between the client and @playwright/mcp, layering on (1) an approval
// gate for irreversible actions, and (2) a learn-and-replay skill layer.
// Zero dependencies (pure node). Personal data is used locally only and never sent anywhere.
import { execFile, spawn } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';
import { pathToFileURL, fileURLToPath } from 'node:url';

const PORT = Number(process.env.AGENTLAS_CDP_PORT || 9222);
const CDP_PROFILE = process.env.AGENTLAS_CDP_PROFILE || path.join(os.homedir(), '.agentlas', 'chrome-cdp-profile');
const OWNER_FILE = path.join(CDP_PROFILE, '.agentlas-cdp-owner.json');
const EXCLUSIVE_LEASE_FILE = path.join(CDP_PROFILE, '.agentlas-cdp-standalone-lease.json');
const HEADLESS = String(process.env.AGENTLAS_CDP_HEADLESS || '1').toLowerCase() !== '0';
const SKILLS_DIR = process.env.AGENTLAS_BROWSER_SKILLS_DIR || path.join(os.homedir(), '.agentlas', 'browser-skills');
const log = (...a) => console.error('[agentlas-browser]', ...a);

function createOwnedChildDrain(child) {
    let ended = false, stopping = false, termRequested = false, forceRequested = false;
    let graceTimer, forceTimer;
    const timers = new Set();
    let resolveClosed;
    const closed = new Promise(resolve => { resolveClosed = resolve; });
    child.on("error", () => { });
    child.once("close", () => {
        if (ended)
            return;
        ended = true;
        for (const timer of timers)
            clearTimeout(timer);
        timers.clear();
        resolveClosed();
    });
    const schedule = (delay, action) => {
        const timer = setTimeout(() => { timers.delete(timer); if (!ended)
            action(); }, delay);
        timers.add(timer);
        return timer;
    };
    const kill = (signal) => { if (!ended) {
        try {
            child.kill(signal);
        }
        catch { /* Request failure never proves death. */ }
    } };
    return {
        closed,
        stop(options = {}) {
            if (ended)
                return closed;
            const term = () => {
                if (!termRequested) {
                    termRequested = true;
                    kill("SIGTERM");
                }
                if (options.forceAfterMs !== undefined && !ended && forceTimer === undefined && !forceRequested) {
                    forceTimer = schedule(Math.max(0, options.forceAfterMs), () => { forceRequested = true; kill("SIGKILL"); });
                }
            };
            if ((options.graceMs ?? 0) > 0) {
                if (!stopping)
                    graceTimer = schedule(options.graceMs, term);
            }
            else {
                // An explicit Stop must not wait behind an earlier stdin-close grace.
                if (graceTimer !== undefined) {
                    clearTimeout(graceTimer);
                    timers.delete(graceTimer);
                    graceTimer = undefined;
                }
                term();
            }
            stopping = true;
            return closed;
        },
    };
}

const ownedChildDrains = new WeakMap();

function processIsLive(pid) {
  if (!Number.isInteger(pid) || pid <= 0) return false;
  try { process.kill(pid, 0); return true; }
  catch (error) { return error && error.code === 'EPERM'; }
}

function ensurePrivateProfile() {
  fs.mkdirSync(CDP_PROFILE, { recursive: true, mode: 0o700 });
  try { fs.chmodSync(CDP_PROFILE, 0o700); } catch (error) {}
}

function manifestRuntime(root) {
  try {
    const manifest = JSON.parse(fs.readFileSync(path.join(root, 'agentlas-browser-runtime.json'), 'utf8'));
    if (manifest.schemaVersion !== 'agentlas.browser-runtime.v1' || manifest.runtime !== 'playwright-chrome-for-testing') return null;
    const executable = path.resolve(root, ...String(manifest.executableRelativePath || '').split('/'));
    const relative = path.relative(path.resolve(root), executable);
    if (!relative || relative === '..' || relative.startsWith('..' + path.sep) || path.isAbsolute(relative)) return null;
    return fs.statSync(executable, { throwIfNoEntry: false })?.isFile() ? executable : null;
  } catch (error) { return null; }
}

function newestCacheRuntime(root) {
  let entries = [];
  try { entries = fs.readdirSync(root).filter((entry) => /^chromium-\d+$/.test(entry)).sort().reverse(); }
  catch (error) { return null; }
  for (const entry of entries) {
    const base = path.join(root, entry);
    const candidates = process.platform === 'darwin'
      ? [
        path.join(base, 'chrome-mac-arm64', 'Google Chrome for Testing.app', 'Contents', 'MacOS', 'Google Chrome for Testing'),
        path.join(base, 'chrome-mac', 'Google Chrome for Testing.app', 'Contents', 'MacOS', 'Google Chrome for Testing'),
      ]
      : process.platform === 'win32'
        ? [path.join(base, 'chrome-win64', 'chrome.exe'), path.join(base, 'chrome-win', 'chrome.exe')]
        : [path.join(base, 'chrome-linux', 'chrome'), path.join(base, 'chrome-linux64', 'chrome')];
    const executable = candidates.find((candidate) => fs.statSync(candidate, { throwIfNoEntry: false })?.isFile());
    if (executable) return executable;
  }
  return null;
}

function resolveAgentlasBrowserRuntime() {
  const override = process.env.AGENTLAS_BROWSER_RUNTIME_EXECUTABLE;
  if (override && path.isAbsolute(override) && fs.statSync(override, { throwIfNoEntry: false })?.isFile()) return override;

  let cursor = path.dirname(fileURLToPath(import.meta.url));
  while (true) {
    const packaged = manifestRuntime(path.join(cursor, 'browser-runtime'));
    if (packaged) return packaged;
    const parent = path.dirname(cursor);
    if (parent === cursor) break;
    cursor = parent;
  }

  const cacheRoot = process.env.PLAYWRIGHT_BROWSERS_PATH
    || (process.platform === 'darwin'
      ? path.join(os.homedir(), 'Library', 'Caches', 'ms-playwright')
      : process.platform === 'win32'
        ? path.join(process.env.LOCALAPPDATA || path.join(os.homedir(), 'AppData', 'Local'), 'ms-playwright')
        : path.join(os.homedir(), '.cache', 'ms-playwright'));
  return newestCacheRuntime(cacheRoot);
}

function acquireExclusiveLease() {
  ensurePrivateProfile();
  try {
    const existing = JSON.parse(fs.readFileSync(EXCLUSIVE_LEASE_FILE, 'utf8'));
    if (processIsLive(Number(existing.pid))) {
      throw new Error('Another Agentlas Browser task is already active. Wait for it to finish instead of launching a second browser.');
    }
  } catch (error) {
    if (error instanceof Error && error.message.startsWith('Another Agentlas Browser task')) throw error;
  }
  fs.writeFileSync(EXCLUSIVE_LEASE_FILE, JSON.stringify({ pid: process.pid, createdAt: Date.now() }), { encoding: 'utf8', mode: 0o600 });
}

function releaseExclusiveLease() {
  try {
    const existing = JSON.parse(fs.readFileSync(EXCLUSIVE_LEASE_FILE, 'utf8'));
    if (Number(existing.pid) === process.pid) fs.rmSync(EXCLUSIVE_LEASE_FILE, { force: true });
  } catch (error) {}
}

function writeOwner(pid) {
  ensurePrivateProfile();
  fs.writeFileSync(OWNER_FILE, JSON.stringify({ pid, port: PORT, profile: path.resolve(CDP_PROFILE) }), { encoding: 'utf8', mode: 0o600 });
}

function clearOwner(pid) {
  try {
    const existing = JSON.parse(fs.readFileSync(OWNER_FILE, 'utf8'));
    if (Number(existing.pid) === pid) fs.rmSync(OWNER_FILE, { force: true });
  } catch (error) {}
}

function resetSessionRestoreArtifacts() {
  for (const relative of [
    path.join('Default', 'Sessions'),
    path.join('Default', 'Current Session'),
    path.join('Default', 'Current Tabs'),
    path.join('Default', 'Last Session'),
    path.join('Default', 'Last Tabs'),
  ]) {
    try { fs.rmSync(path.join(CDP_PROFILE, relative), { recursive: true, force: true }); } catch (error) {}
  }
}

function portReady(port) {
  return new Promise((resolve) => {
    const req = http.get({ host: '127.0.0.1', port, path: '/json/version', timeout: 1200 }, (res) => { res.resume(); resolve(res.statusCode === 200); });
    req.on('error', () => resolve(false));
    req.on('timeout', () => { req.destroy(); resolve(false); });
  });
}

function waitForProcessExit(pid, timeoutMs) {
  return new Promise((resolve) => {
    const deadline = Date.now() + timeoutMs;
    const poll = () => {
      if (!processIsLive(pid) || Date.now() >= deadline) return resolve(!processIsLive(pid));
      setTimeout(poll, 100);
    };
    poll();
  });
}

async function terminateOwnedBrowser(child) {
  if (!child) return;
  const drain = ownedChildDrains.get(child);
  if (!drain) throw new Error('Agentlas browser cleanup requires its original owned child.');
  if (child.exitCode !== null || child.signalCode !== null || !child.pid || !processIsLive(child.pid)) { await drain.closed; return; }
  try {
    if (process.platform === 'win32') {
      await new Promise((resolve) => execFile('taskkill.exe', ['/PID', String(child.pid), '/T'], { windowsHide: true, timeout: 3000 }, () => resolve()));
    } else process.kill(child.pid, 'SIGTERM');
  } catch (error) {}
  if (await waitForProcessExit(child.pid, 2500)) { await drain.closed; return; }
  if (child.exitCode !== null || child.signalCode !== null) { await drain.closed; return; }
  try {
    if (process.platform === 'win32') {
      await new Promise((resolve) => execFile('taskkill.exe', ['/PID', String(child.pid), '/T', '/F'], { windowsHide: true, timeout: 3000 }, () => resolve()));
    } else process.kill(child.pid, 'SIGKILL');
  } catch (error) {}
  await waitForProcessExit(child.pid, 2500);
  // Failed final polling never proves death or permits lease/owner removal.
  await drain.closed;
}

async function ensureChrome() {
  if (await portReady(PORT)) {
    throw new Error('CDP port ' + PORT + ' is already in use. Agentlas will not attach to or terminate an unverified browser.');
  }
  const exe = resolveAgentlasBrowserRuntime();
  if (!exe) throw new Error('Agentlas Chrome for Testing runtime is missing. Install or repair Agentlas Desktop/runtime; system Chrome is never used as an automation fallback.');
  ensurePrivateProfile();
  resetSessionRestoreArtifacts();
  const args = [
    '--user-data-dir=' + CDP_PROFILE, '--remote-debugging-port=' + PORT,
    '--remote-debugging-address=127.0.0.1',
    '--no-first-run', '--no-default-browser-check',
    '--disable-session-crashed-bubble',
    // One --disable-features value (Chrome keeps the last). The OptimizationGuide
    // features stop the ~4 GB on-device AI model download into this profile (2026-10-16).
    '--disable-features=Translate,OptimizationGuideModelDownloading,OptimizationGuideOnDeviceModel,OptimizationHints,OptimizationHintsFetching,OptimizationTargetPrediction',
    // HTTP cache ceiling shared with Agentlas Desktop (the profile's cache reached 1.4 GB without one).
    '--disk-cache-size=268435456',
    '--disable-component-update', '--disable-background-networking',
    '--disable-backgrounding-occluded-windows', '--disable-renderer-backgrounding',
    '--disable-background-timer-throttling',
  ];
  if (HEADLESS) args.push('--headless=new');
  args.push('--no-startup-window');
  log('launching Agentlas Chrome for Testing on port', PORT, HEADLESS ? '(headless)' : '');
  const child = spawn(exe, args, { detached: false, stdio: 'ignore' });
  ownedChildDrains.set(child, createOwnedChildDrain(child));
  let launchError = null;
  child.once('error', (error) => { launchError = error; });
  writeOwner(child.pid);
  for (let i = 0; i < 40; i++) {
    if (launchError) break;
    if (await portReady(PORT)) { log('CDP ready', child.pid); return child; }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  await terminateOwnedBrowser(child);
  clearOwner(child.pid);
  throw new Error('Agentlas Chrome for Testing did not open CDP port ' + PORT + (launchError ? ': ' + launchError.message : '.'));
}

// ── approval gate ──────────────────────────────────────────────────
// CONTRACT (owner rule 2026-10-13: the host never decides meaning from words; native-harness notyet NH25). The approval
// kind comes, in order, from
//   1. the parent's pre-judged classification via tools/call params._meta['agentlas/actionKind'] ('payment'|'send'|
//      'publish'|'delete'|'sensitive-action'|'none') — a model's judgment; 'none' means judged safe, no gate;
//   2. the effect the model declares on browser_click (a typed argument advertised in tools/list and stripped before
//      the Playwright child sees the call);
//   3. the tool's own semantics, the same classes as the Desktop launcher (browser-cdp-launcher.ts classifyAction /
//      approvalFor): Enter or type-with-submit is a send, accepting a dialog is a send, a click with no valid declared
//      effect is not known to be harmless and asks as a send;
//   4. typed page structure read from the action's target just before it runs (form method, W3C cc-* autofill tokens),
//      which can only raise: a submit of a POST form is at least send, of a form with card fields payment; typing into a
//      card field is payment. An unreadable target is neutral.
// One deliberate difference: a file upload asks (send). The Desktop launcher stages uploads only from the run's own
// folders and refuses others before dispatch; this launcher has no such root list, so local data leaving needs approval.
// Labels, element descriptions and URLs are never read. Navigation, typing and reading stay ungated.
const APPROVAL_KINDS = new Set(['payment', 'send', 'publish', 'delete', 'sensitive-action']);
const CLICK_EFFECT_KIND = { none: null, like: null, follow: null, repost: null, reply: 'send', message: 'send', post: 'publish', send: 'send', publish: 'publish', delete: 'delete', payment: 'payment' };
const CLICK_EFFECT_DESCRIPTION = 'What this click does, declared by you: none (tab, filter, menu, expand, open a composer, pick a file; nothing is sent), like, follow, repost, or the effect this click finalizes: reply, message, post, send, publish, delete, payment. A click without a valid effect always asks the owner for approval.';
function normalizeActionKindOverride(kind) {
  const value = String(kind).toLowerCase().trim();
  if (value === 'none' || value === 'safe') return null;
  // an unknown override never widens autonomy — it degrades to the generic gate
  return APPROVAL_KINDS.has(value) ? value : 'sensitive-action';
}
function declaredClickEffect(args) {
  const raw = args && typeof args === 'object' && typeof args.effect === 'string' ? args.effect.trim().toLowerCase() : '';
  return Object.prototype.hasOwnProperty.call(CLICK_EFFECT_KIND, raw) ? raw : null;
}
const SUBMIT_KEY_RE = /^(enter|return|numpadenter)$/i;
const CLASS_RANK = { send: 1, publish: 2, delete: 3, payment: 4 };
function higherApprovalClass(a, b) {
  if (!a) return b || null;
  if (!b) return a;
  return (CLASS_RANK[b] || 0) > (CLASS_RANK[a] || 0) ? b : a;
}
// Same page-side probe as the Desktop launcher (ACTION_STRUCTURE_PROBE): typed DOM facts only, never the element's text.
const ACTION_STRUCTURE_PROBE = "(el) => { el = el || document.activeElement; if (!el || !el.getAttribute) return { found: false };"
  + " const card = (n) => !!(n && n.getAttribute && String(n.getAttribute('autocomplete') || '').toLowerCase().split(' ').some((t) => t.indexOf('cc-') === 0));"
  + " const form = el.form || (el.closest ? el.closest('form') : null); const tag = String(el.tagName || '').toLowerCase(); const type = String(el.getAttribute('type') || '').toLowerCase();"
  + " const submitControl = (tag === 'button' && !!form && (type === '' || type === 'submit')) || (tag === 'input' && (type === 'submit' || type === 'image'));"
  + " return { found: true, submitControl, formMethod: form ? String(form.getAttribute('method') || 'get').toLowerCase() : null,"
  + " paymentField: card(el), paymentForm: !!form && Array.prototype.some.call(form.elements || [], card) }; }";
function actionStructureTargets(name, args) {
  const input = args && typeof args === 'object' ? args : {};
  if (name === 'browser_click') return CLICK_EFFECT_KIND[declaredClickEffect(input)] === 'payment' ? [] : [typeof input.target === 'string' ? input.target : null];
  if (name === 'browser_type' || name === 'browser_fill') return [typeof input.target === 'string' ? input.target : null];
  if (name === 'browser_press_key') return SUBMIT_KEY_RE.test(String(input.key || '')) ? [''] : [];
  if (name === 'browser_fill_form' && Array.isArray(input.fields)) {
    return input.fields.slice(0, 12).map((field) => field && typeof (field.target || field.ref) === 'string' ? (field.target || field.ref) : null);
  }
  return [];
}
function mergeActionStructure(results) {
  const found = (results || []).filter((row) => row && row.found === true);
  if (!found.length) return null;
  return {
    found: true,
    submitControl: found.some((row) => row.submitControl === true),
    formMethod: found.map((row) => row.formMethod).find((method) => typeof method === 'string') || null,
    paymentField: found.some((row) => row.paymentField === true),
    paymentForm: found.some((row) => row.paymentForm === true),
  };
}
function structuralClass(name, structure, submitting) {
  if (!structure || structure.found !== true) return null;
  if (name === 'browser_type' || name === 'browser_fill' || name === 'browser_fill_form') {
    if (structure.paymentField) return 'payment';
    if (!submitting) return null;
  }
  if (structure.submitControl || submitting) {
    if (structure.paymentForm || structure.paymentField) return 'payment';
    if (structure.formMethod === 'post') return 'send';
  }
  return null;
}
function classifyAction(name, args, preJudgedKind, structure = null) {
  if (preJudgedKind !== undefined && preJudgedKind !== null && preJudgedKind !== '') {
    return normalizeActionKindOverride(preJudgedKind);
  }
  const input = args && typeof args === 'object' ? args : {};
  if (name === 'browser_click') {
    const effect = declaredClickEffect(input);
    return higherApprovalClass(effect ? CLICK_EFFECT_KIND[effect] : 'send', structuralClass(name, structure, false));
  }
  if (name === 'browser_file_upload') return 'send';
  const submitByKey = name === 'browser_press_key' && SUBMIT_KEY_RE.test(String(input.key || ''));
  const submitByType = name === 'browser_type' && input.submit === true;
  if (submitByKey || submitByType) return higherApprovalClass('send', structuralClass(name, structure, true));
  if (name === 'browser_handle_dialog' && input.accept === true) return 'send';
  if (name === 'browser_type' || name === 'browser_fill' || name === 'browser_fill_form') return structuralClass(name, structure, false);
  return null;
}
// The declared effect is for this gate only; the Playwright child keeps its own schema.
function stripClickEffect(name, args) {
  if (name !== 'browser_click' || !args || typeof args !== 'object' || !Object.prototype.hasOwnProperty.call(args, 'effect')) return args;
  const { effect: _declared, ...rest } = args;
  return rest;
}
function withClickEffectSchema(tool) {
  const schema = tool && tool.inputSchema && typeof tool.inputSchema === 'object' ? tool.inputSchema : null;
  if (!schema) return;
  schema.properties = { ...(schema.properties || {}), effect: { type: 'string', enum: Object.keys(CLICK_EFFECT_KIND), description: CLICK_EFFECT_DESCRIPTION } };
  const required = Array.isArray(schema.required) ? schema.required : [];
  if (!required.includes('effect')) schema.required = [...required, 'effect'];
}
function readApprovalInfo() {
  try { const p = path.join(os.homedir(), '.agentlas', 'browser-approval.json'); if (!fs.existsSync(p)) return null; return JSON.parse(fs.readFileSync(p, 'utf8')); } catch (e) { return null; }
}
function requestApproval(site, actionType, summary) {
  return new Promise((resolve) => {
    const autonomy = process.env.AGENTLAS_BROWSER_AUTONOMY || 'gated';
    const info = readApprovalInfo();
    if (!info || !info.port) { log('no approver (app not running); autonomy=' + autonomy + ' action=' + actionType); return resolve(autonomy === 'trust' ? 'approved' : 'denied'); }
    const payload = JSON.stringify({ site, actionType, summary });
    const req = http.request({ host: '127.0.0.1', port: info.port, path: '/approve', method: 'POST', headers: { 'content-type': 'application/json', 'content-length': Buffer.byteLength(payload), 'authorization': 'Bearer ' + info.token }, timeout: 125000 }, (res) => {
      let b = ''; res.on('data', (d) => { b += d; }); res.on('end', () => { try { resolve(JSON.parse(b).decision === 'approved' ? 'approved' : 'denied'); } catch (e) { resolve('denied'); } });
    });
    req.on('error', () => resolve(autonomy === 'trust' ? 'approved' : 'denied'));
    req.on('timeout', () => { req.destroy(); resolve('denied'); });
    req.write(payload); req.end();
  });
}

// ── learn-and-replay skill layer ─────────────────────────────────
// Action tools eligible for recording/replay (excludes read-only ones like snapshot/screenshot).
const RECORDABLE = new Set(['browser_navigate', 'browser_navigate_back', 'browser_click', 'browser_type', 'browser_fill', 'browser_fill_form', 'browser_select_option', 'browser_press_key', 'browser_hover', 'browser_file_upload', 'browser_drag']);
const SKILL_TOOLS = [
  { name: 'browser_skill_list', description: 'List saved Agentlas browser skills (learned action sequences).', inputSchema: { type: 'object', properties: {} } },
  { name: 'browser_skill_save', description: 'Save the actions performed so far in this session as a reusable skill. Use after successfully completing a task (e.g. an Instagram upload) so it can be replayed deterministically next time.', inputSchema: { type: 'object', properties: { name: { type: 'string', description: 'Skill name, e.g. "instagram-upload"' }, description: { type: 'string' } }, required: ['name'] } },
  { name: 'browser_skill_replay', description: 'Replay a previously saved skill by name — re-runs its recorded action sequence deterministically (no reasoning needed).', inputSchema: { type: 'object', properties: { name: { type: 'string' } }, required: ['name'] } },
];
function skillPath(name) { return path.join(SKILLS_DIR, String(name).replace(/[^a-zA-Z0-9._-]/g, '_') + '.json'); }
function listSkills() { try { return fs.readdirSync(SKILLS_DIR).filter((f) => f.endsWith('.json')).map((f) => f.slice(0, -5)); } catch (e) { return []; } }
function saveSkill(name, steps, description) {
  fs.mkdirSync(SKILLS_DIR, { recursive: true });
  const doc = { name, description: description || '', steps, savedAt: new Date().toISOString() };
  fs.writeFileSync(skillPath(name), JSON.stringify(doc, null, 2));
  return doc;
}
function loadSkill(name) { const p = skillPath(name); if (!fs.existsSync(p)) return null; return JSON.parse(fs.readFileSync(p, 'utf8')); }

// @agentlas-site-learning-core begin
const SITE_LEARNING_SCHEMA = 'agentlas.site-learning.v1';
const SITE_LEARNING_ID = /^[a-z0-9][a-z0-9-]{1,38}[a-z0-9]$/;
const SITE_LEARNING_HOST_PART = /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/;
const SITE_LEARNING_NOTE = /^[a-z][a-z0-9_-]{0,31}: \S[^\u0000-\u001f\u007f]*$/;
const SITE_LEARNING_LINE = /^[^\u0000-\u001f\u007f]+$/;
const SITE_LEARNING_CSS = /^[A-Za-z0-9_#.\[\]=~|^$*:"'(),>+ @\/\\-]{1,200}$/;
const SITE_LEARNING_PATH = /^\/[A-Za-z0-9_.\/{}?=&%:@~+,-]{0,198}$/;
const SITE_LEARNING_PARAM = /^[a-z][A-Za-z0-9_]{0,23}$/;
const SITE_LEARNING_TOOL = /^[a-z][a-z0-9_]{1,39}$/;
const SITE_LEARNING_FIELD = /^[a-z][a-z0-9_]{0,23}$/;
const SITE_LEARNING_ATTR = /^[a-z][a-z-]{0,23}$/;
const SITE_LEARNING_ROLE = /^[a-z]{3,24}$/;
const SITE_LEARNING_KEY = /^[A-Za-z0-9+]{1,24}$/;
const SITE_LEARNING_TIME = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,3})?Z$/;
const SITE_LEARNING_RUN = /^[A-Za-z0-9_.:-]{1,64}$/;
const SITE_LEARNING_SHA = /^[a-f0-9]{64}$/;
const SITE_LEARNING_LIMITS = { domains: 8, notes: 12, noteText: 240, tools: 8, description: 120, params: 6, steps: 20, fields: 12, rowLimit: 100, json: 24000 };
const SITE_LEARNING_STATUS = ['proposed', 'active', 'disabled'];
const SITE_LEARNING_ORIGIN = ['agent', 'owner', 'release'];
const SITE_LEARNING_NOTE_KINDS = ['selector', 'url-pattern', 'quirk', 'flow'];
const SITE_LEARNING_CLICK_EFFECTS = ['none', 'like', 'follow', 'repost', 'reply', 'message', 'post', 'send', 'publish', 'delete', 'payment'];
const SITE_LEARNING_STEP_KEYS = {
  browser_navigate: ['tool', 'url'],
  browser_click: ['tool', 'target', 'effect'],
  browser_type: ['tool', 'target', 'value'],
  browser_select_option: ['tool', 'target', 'value'],
  browser_press_key: ['tool', 'key'],
  browser_wait_for: ['tool', 'text', 'time'],
};
// Not a full public-suffix list. A wildcard under one of these would span unrelated owners, so it is refused;
// an exact host under them stays allowed. The owner sees every domain on the approval card either way.
const SITE_LEARNING_SHARED_SUFFIXES = new Set([
  'co.kr', 'or.kr', 'ne.kr', 'go.kr', 'ac.kr', 're.kr', 'pe.kr', 'co.uk', 'org.uk', 'ac.uk', 'gov.uk', 'com.au', 'net.au',
  'org.au', 'co.jp', 'ne.jp', 'or.jp', 'com.br', 'com.cn', 'com.tw', 'com.hk', 'com.sg', 'com.mx', 'co.in', 'co.nz', 'co.za',
  'github.io', 'gitlab.io', 'vercel.app', 'netlify.app', 'pages.dev', 'workers.dev', 'web.app', 'firebaseapp.com',
  'herokuapp.com', 'blogspot.com', 'wordpress.com', 'appspot.com', 'azurewebsites.net', 'cloudfront.net', 'amazonaws.com',
  'fly.dev', 'onrender.com', 'notion.site', 'substack.com', 'myshopify.com', 'wixsite.com',
]);

/** One domain entry: exact host or '*.' + base. Canonical lowercase only; null when it is not a site. */
function siteLearningNormalizeDomain(entry) {
  if (typeof entry !== 'string' || entry.length < 3 || entry.length > 100) return null;
  const wildcard = entry.startsWith('*.');
  const host = wildcard ? entry.slice(2) : entry;
  const parts = host.split('.');
  if (parts.length < 2 || parts.length > 8) return null;
  if (!parts.every((part) => SITE_LEARNING_HOST_PART.test(part))) return null;
  const last = parts[parts.length - 1];
  if (/^\d+$/.test(last) || last === 'localhost') return null;
  if (SITE_LEARNING_SHARED_SUFFIXES.has(host)) return null;
  return { kind: wildcard ? 'wildcard' : 'exact', host: host };
}

/** The host the browser is on, from a URL the HOST observed (never one the model typed). https, no port, no userinfo. */
function siteLearningParseObservedUrl(value) {
  if (typeof value !== 'string' || value.length > 2048) return null;
  let parsed;
  try { parsed = new URL(value); } catch (error) { return null; }
  if (parsed.protocol !== 'https:' || parsed.username !== '' || parsed.password !== '' || parsed.port !== '') return null;
  const host = parsed.hostname.endsWith('.') ? parsed.hostname.slice(0, -1) : parsed.hostname;
  const normalized = siteLearningNormalizeDomain(host);
  return normalized && normalized.kind === 'exact' ? { host: host, path: parsed.pathname } : null;
}

function siteLearningDomainMatches(patterns, host) {
  if (!Array.isArray(patterns) || typeof host !== 'string') return false;
  return patterns.some((entry) => {
    const normalized = siteLearningNormalizeDomain(entry);
    if (!normalized) return false;
    return normalized.kind === 'exact' ? host === normalized.host : host.endsWith('.' + normalized.host);
  });
}

function siteLearningCanonicalJson(value) {
  if (Array.isArray(value)) return '[' + value.map(siteLearningCanonicalJson).join(',') + ']';
  if (value && typeof value === 'object') {
    return '{' + Object.keys(value).sort().map((key) => JSON.stringify(key) + ':' + siteLearningCanonicalJson(value[key])).join(',') + '}';
  }
  return JSON.stringify(value);
}

/** What the SHA-256 covers: the content an owner approved, not its status or bookkeeping. */
function siteLearningContentJson(doc) {
  return siteLearningCanonicalJson({ schema: doc.schema, id: doc.id, domains: doc.domains, notes: doc.notes || [], tools: doc.tools || [] });
}

function siteLearningParamRef(value, declared) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const keys = Object.keys(value);
  return keys.length === 1 && keys[0] === 'param' && typeof value.param === 'string' && declared.has(value.param);
}

function siteLearningCheckTarget(ctx, target, where) {
  if (!ctx.isObject(target)) return ctx.bad(where + ':target');
  const keys = Object.keys(target);
  if (keys.length === 1 && keys[0] === 'css') {
    if (!ctx.fits(SITE_LEARNING_CSS, target.css)) ctx.bad(where + ':target-css');
  } else if (keys.length === 2 && keys.includes('role') && keys.includes('name')) {
    if (!ctx.fits(SITE_LEARNING_ROLE, target.role)) ctx.bad(where + ':target-role');
    if (!ctx.line(target.name, 120)) ctx.bad(where + ':target-name');
  } else {
    ctx.bad(where + ':target-shape');
  }
}

function siteLearningCheckUrlTemplate(ctx, value, declared, domains, where) {
  if (!ctx.line(value, 400)) return ctx.bad(where + ':url');
  const slots = value.match(/\{[^{}]*\}/g) || [];
  for (const slot of slots) {
    const name = slot.slice(1, -1);
    if (!SITE_LEARNING_PARAM.test(name) || !declared.has(name)) ctx.bad(where + ':url-slot');
  }
  const hostEnd = value.indexOf('/', 8);
  const hostPart = hostEnd === -1 ? value : value.slice(0, hostEnd);
  if (hostPart.indexOf('{') !== -1 || hostPart.indexOf('}') !== -1) return ctx.bad(where + ':url-host-slot');
  const probe = value.replace(/\{[^{}]*\}/g, 'x');
  if (probe.indexOf('{') !== -1 || probe.indexOf('}') !== -1) return ctx.bad(where + ':url-braces');
  const parsed = siteLearningParseObservedUrl(probe);
  if (!parsed) return ctx.bad(where + ':url-grammar');
  if (!siteLearningDomainMatches(domains, parsed.host)) ctx.bad(where + ':url-domain');
}

function siteLearningCheckSteps(ctx, steps, declared, domains, at) {
  if (!Array.isArray(steps) || steps.length < 1 || steps.length > SITE_LEARNING_LIMITS.steps) return ctx.bad(at + ':steps');
  steps.forEach((step, index) => {
    const where = at + ':step:' + index;
    if (!ctx.isObject(step)) return ctx.bad(where);
    if (typeof step.tool !== 'string' || !Object.prototype.hasOwnProperty.call(SITE_LEARNING_STEP_KEYS, step.tool)) return ctx.bad(where + ':tool');
    ctx.onlyKeys(step, SITE_LEARNING_STEP_KEYS[step.tool], where);
    if (step.tool === 'browser_navigate') {
      siteLearningCheckUrlTemplate(ctx, step.url, declared, domains, where);
    } else if (step.tool === 'browser_click') {
      siteLearningCheckTarget(ctx, step.target, where);
      if (!SITE_LEARNING_CLICK_EFFECTS.includes(step.effect)) ctx.bad(where + ':effect');
    } else if (step.tool === 'browser_type') {
      siteLearningCheckTarget(ctx, step.target, where);
      // Typed text always arrives as a run-time argument; a literal would persist whatever the model typed.
      if (!siteLearningParamRef(step.value, declared)) ctx.bad(where + ':type-needs-param');
    } else if (step.tool === 'browser_select_option') {
      siteLearningCheckTarget(ctx, step.target, where);
      if (!siteLearningParamRef(step.value, declared) && !ctx.line(step.value, 80)) ctx.bad(where + ':value');
    } else if (step.tool === 'browser_press_key') {
      if (!ctx.fits(SITE_LEARNING_KEY, step.key)) ctx.bad(where + ':key');
    } else if (step.tool === 'browser_wait_for') {
      const hasText = step.text !== undefined;
      const hasTime = step.time !== undefined;
      if (hasText === hasTime) ctx.bad(where + ':wait-shape');
      else if (hasText && !ctx.line(step.text, 120)) ctx.bad(where + ':wait-text');
      else if (hasTime && !(Number.isInteger(step.time) && step.time >= 1 && step.time <= 10)) ctx.bad(where + ':wait-time');
    }
  });
}

function siteLearningCheckExtract(ctx, spec, at) {
  if (!ctx.isObject(spec)) return ctx.bad(at + ':extract');
  ctx.onlyKeys(spec, ['rows', 'fields', 'limit'], at + ':extract');
  if (!ctx.fits(SITE_LEARNING_CSS, spec.rows)) ctx.bad(at + ':rows');
  if (spec.limit !== undefined && !(Number.isInteger(spec.limit) && spec.limit >= 1 && spec.limit <= SITE_LEARNING_LIMITS.rowLimit)) ctx.bad(at + ':limit');
  if (!Array.isArray(spec.fields) || spec.fields.length < 1 || spec.fields.length > SITE_LEARNING_LIMITS.fields) return ctx.bad(at + ':fields');
  const names = new Set();
  spec.fields.forEach((field, index) => {
    const where = at + ':field:' + index;
    if (!ctx.isObject(field)) return ctx.bad(where);
    ctx.onlyKeys(field, ['name', 'css', 'text', 'attr'], where);
    if (!ctx.fits(SITE_LEARNING_FIELD, field.name) || names.has(field.name)) ctx.bad(where + ':name');
    else names.add(field.name);
    if (!ctx.fits(SITE_LEARNING_CSS, field.css)) ctx.bad(where + ':css');
    const hasText = field.text !== undefined;
    const hasAttr = field.attr !== undefined;
    if (hasText === hasAttr) return ctx.bad(where + ':read-shape');
    if (hasText && field.text !== true) ctx.bad(where + ':text');
    // The value attribute of a form control is what a person typed, a password included; a text read never is.
    if (hasAttr && (!ctx.fits(SITE_LEARNING_ATTR, field.attr) || field.attr === 'value')) ctx.bad(where + ':attr');
  });
}

/**
 * Strict structural check. Returns { ok: true, value } with a deep copy, or { ok: false, errors: [machine codes] }.
 * deps.sha256Hex (optional): when given, an active learning's sha256 must equal the hash of its content JSON.
 */
function siteLearningValidate(doc, deps) {
  const errors = [];
  const ctx = {
    bad: function (code) { if (errors.length < 24) errors.push(code); },
    isObject: function (value) { return Boolean(value) && typeof value === 'object' && !Array.isArray(value); },
    fits: function (pattern, value) { return typeof value === 'string' && pattern.test(value); },
    line: function (value, max) { return typeof value === 'string' && value.length >= 1 && value.length <= max && SITE_LEARNING_LINE.test(value); },
    onlyKeys: function (value, allowed, where) {
      for (const key of Object.keys(value)) if (!allowed.includes(key)) ctx.bad('unknown-key:' + where + ':' + String(key).slice(0, 40));
    },
  };
  if (!ctx.isObject(doc)) return { ok: false, errors: ['doc-not-object'] };
  ctx.onlyKeys(doc, ['schema', 'id', 'domains', 'revision', 'status', 'provenance', 'sha256', 'notes', 'tools'], 'doc');
  if (doc.schema !== SITE_LEARNING_SCHEMA) ctx.bad('schema');
  if (!ctx.fits(SITE_LEARNING_ID, doc.id)) ctx.bad('id');
  if (!Number.isInteger(doc.revision) || doc.revision < 1 || doc.revision > 1000000) ctx.bad('revision');
  if (!SITE_LEARNING_STATUS.includes(doc.status)) ctx.bad('status');

  if (!Array.isArray(doc.domains) || doc.domains.length < 1 || doc.domains.length > SITE_LEARNING_LIMITS.domains) {
    ctx.bad('domains');
  } else {
    const seen = new Set();
    doc.domains.forEach((entry, index) => {
      if (!siteLearningNormalizeDomain(entry)) ctx.bad('domain:' + index);
      else if (seen.has(entry)) ctx.bad('domain-duplicate:' + index);
      seen.add(entry);
    });
  }

  const provenance = doc.provenance;
  if (!ctx.isObject(provenance)) {
    ctx.bad('provenance');
  } else {
    ctx.onlyKeys(provenance, ['origin', 'createdAt', 'runId', 'sourceHost'], 'provenance');
    if (!SITE_LEARNING_ORIGIN.includes(provenance.origin)) ctx.bad('provenance-origin');
    if (!ctx.fits(SITE_LEARNING_TIME, provenance.createdAt)) ctx.bad('provenance-created-at');
    if (provenance.runId !== undefined && !ctx.fits(SITE_LEARNING_RUN, provenance.runId)) ctx.bad('provenance-run-id');
    if (provenance.sourceHost !== undefined) {
      const source = siteLearningNormalizeDomain(provenance.sourceHost);
      if (!source || source.kind !== 'exact') ctx.bad('provenance-source-host');
    }
  }

  const notes = doc.notes === undefined ? [] : doc.notes;
  if (!Array.isArray(notes) || notes.length > SITE_LEARNING_LIMITS.notes) {
    ctx.bad('notes');
  } else {
    notes.forEach((note, index) => {
      const where = 'note:' + index;
      if (!ctx.isObject(note)) return ctx.bad(where);
      ctx.onlyKeys(note, ['kind', 'text'], where);
      if (!SITE_LEARNING_NOTE_KINDS.includes(note.kind)) ctx.bad(where + ':kind');
      if (!ctx.fits(SITE_LEARNING_NOTE, note.text) || note.text.length > SITE_LEARNING_LIMITS.noteText) return ctx.bad(where + ':text');
      const noteValue = note.text.slice(note.text.indexOf(': ') + 2);
      if (note.kind === 'selector' && !SITE_LEARNING_CSS.test(noteValue)) ctx.bad(where + ':selector');
      if (note.kind === 'url-pattern' && !SITE_LEARNING_PATH.test(noteValue)) ctx.bad(where + ':path');
    });
  }

  const tools = doc.tools === undefined ? [] : doc.tools;
  if (!Array.isArray(tools) || tools.length > SITE_LEARNING_LIMITS.tools) {
    ctx.bad('tools');
  } else {
    const names = new Set();
    tools.forEach((tool, index) => {
      const at = 'tool:' + index;
      if (!ctx.isObject(tool)) return ctx.bad(at);
      ctx.onlyKeys(tool, ['name', 'description', 'kind', 'params', 'steps', 'extract'], at);
      if (!ctx.fits(SITE_LEARNING_TOOL, tool.name)) ctx.bad(at + ':name');
      else if (names.has(tool.name)) ctx.bad(at + ':name-duplicate');
      else names.add(tool.name);
      if (!ctx.line(tool.description, SITE_LEARNING_LIMITS.description)) ctx.bad(at + ':description');
      const params = tool.params === undefined ? {} : tool.params;
      const declared = new Set();
      if (!ctx.isObject(params) || Object.keys(params).length > SITE_LEARNING_LIMITS.params) {
        ctx.bad(at + ':params');
      } else {
        for (const name of Object.keys(params)) {
          const spec = params[name];
          if (!SITE_LEARNING_PARAM.test(name) || !ctx.isObject(spec)) { ctx.bad(at + ':param'); continue; }
          declared.add(name);
          ctx.onlyKeys(spec, ['type', 'required', 'maxLength', 'max'], at + ':param:' + name);
          if (spec.required !== undefined && typeof spec.required !== 'boolean') ctx.bad(at + ':param-required');
          if (spec.type === 'string') {
            if (spec.max !== undefined) ctx.bad(at + ':param-max');
            if (spec.maxLength !== undefined && !(Number.isInteger(spec.maxLength) && spec.maxLength >= 1 && spec.maxLength <= 500)) ctx.bad(at + ':param-max-length');
          } else if (spec.type === 'integer') {
            if (spec.maxLength !== undefined) ctx.bad(at + ':param-max-length');
            if (spec.max !== undefined && !(Number.isInteger(spec.max) && spec.max >= 1 && spec.max <= 1000000000)) ctx.bad(at + ':param-max');
          } else {
            ctx.bad(at + ':param-type');
          }
        }
      }
      if (tool.kind === 'steps') {
        if (tool.extract !== undefined) ctx.bad(at + ':extract-on-steps');
        siteLearningCheckSteps(ctx, tool.steps, declared, doc.domains, at);
      } else if (tool.kind === 'extract') {
        if (tool.steps !== undefined) ctx.bad(at + ':steps-on-extract');
        siteLearningCheckExtract(ctx, tool.extract, at);
      } else {
        ctx.bad(at + ':kind');
      }
    });
  }

  if (doc.status === 'active' && !ctx.fits(SITE_LEARNING_SHA, doc.sha256)) ctx.bad('sha256');
  else if (doc.sha256 !== undefined && !ctx.fits(SITE_LEARNING_SHA, doc.sha256)) ctx.bad('sha256');

  if (!errors.length) {
    const canonical = siteLearningCanonicalJson(doc);
    if (canonical.length > SITE_LEARNING_LIMITS.json) ctx.bad('too-large');
    else if (doc.status === 'active' && deps && typeof deps.sha256Hex === 'function' && deps.sha256Hex(siteLearningContentJson(doc)) !== doc.sha256) ctx.bad('sha256-mismatch');
  }
  return errors.length ? { ok: false, errors: errors } : { ok: true, value: JSON.parse(JSON.stringify(doc)) };
}

/** The active learnings whose domains cover the host-observed URL. Input must already be validated. */
function siteLearningMatch(docs, observedUrl) {
  const parsed = siteLearningParseObservedUrl(observedUrl);
  if (!parsed || !Array.isArray(docs)) return [];
  return docs.filter((doc) => doc && doc.status === 'active' && siteLearningDomainMatches(doc.domains, parsed.host));
}
// @agentlas-site-learning-core end

async function main() {
  let browserChild = null;
  let browserReadyPromise = null;
  let browserLaunchPromise = null;
  let leaseHeld = false;
  let closing = false;
  let cleanupFlight = null;
  const cleanup = () => {
    if (cleanupFlight) return cleanupFlight;
    closing = true;
    cleanupFlight = (async () => {
      try { child.stdin.end(); } catch (error) { /* The exact child may already be closing. */ }
      const stopped = childDrain.stop({ forceAfterMs: 2000 });
      // Await the original launch, not its catch wrapper (which awaits cleanup).
      if (browserLaunchPromise) browserChild = await browserLaunchPromise.catch(() => null);
      await terminateOwnedBrowser(browserChild);
      await stopped;
      if (browserChild?.pid) clearOwner(browserChild.pid);
      if (leaseHeld) {
        releaseExclusiveLease();
        leaseHeld = false;
      }
    })();
    return cleanupFlight;
  };
  const ensureBrowserForTool = () => {
    if (browserReadyPromise) return browserReadyPromise;
    const flight = (async () => {
      acquireExclusiveLease();
      leaseHeld = true;
      if (closing) throw new Error('Agentlas Browser client closed before launch.');
      browserLaunchPromise = ensureChrome();
      browserChild = await browserLaunchPromise;
      if (closing) throw new Error('Agentlas Browser client closed during launch.');
    })().catch(async (error) => {
      await cleanup();
      throw error;
    });
    browserReadyPromise = flight;
    return flight;
  };
  const npx = process.platform === 'win32' ? 'npx.cmd' : 'npx';
  const child = spawn(npx, ['-y', '@playwright/mcp@latest', '--cdp-endpoint', 'http://127.0.0.1:' + PORT], { stdio: ['pipe', 'pipe', 'inherit'], windowsHide: true });
  const childDrain = createOwnedChildDrain(child);
  let finishing = false;
  const finish = (code) => {
    if (finishing) return;
    finishing = true;
    void cleanup().then(() => process.exit(code));
  };
  child.on('error', (error) => { log('failed to start @playwright/mcp', String(error)); finish(1); });
  child.on('close', (code) => finish(code == null ? 0 : code));
  child.stdin.on('error', () => finish(1));
  process.stdin.on('error', () => finish(1));
  process.stdout.on('error', () => finish(1));

  const recording = [];            // sequence of actions that succeeded in this session
  const pending = new Map();       // client's original tools/call: id -> {name, args}
  const waiters = new Map();       // internal (replay) tools/call: id -> resolve
  let currentUrl = '';
  let internalSeq = 0;
  const writeClient = (obj) => { try { process.stdout.write(JSON.stringify(obj) + '\n'); } catch (e) {} };
  const forwardRaw = (line) => { if (closing) return; try { child.stdin.write(line + '\n'); } catch (e) {} };
  const writeBrowserStartFailure = (id, error) => writeClient({
    jsonrpc: '2.0',
    id,
    result: {
      content: [{ type: 'text', text: 'Agentlas Browser could not start safely: ' + String(error?.message || error) }],
      isError: true,
    },
  });

  // Shared approval-gate verdict. Pass = null, refuse = reason string.
  const gate = async (name, args, preJudgedKind, structure) => {
    const actionType = classifyAction(name, args, preJudgedKind, structure === undefined ? await readActionStructure(name, args, preJudgedKind) : structure);
    if (!actionType) return null;
    let site = ''; try { site = new URL(currentUrl).host; } catch (e) { site = currentUrl; }
    const summaryPrefix = actionType === 'sensitive-action'
      ? 'sensitive-action (unclassified commit-like action; deterministic fallback gate): '
      : actionType + ': ';
    const decision = await requestApproval(site, actionType, summaryPrefix + (args.element || args.url || name));
    return decision === 'approved' ? null : actionType;
  };

  // Typed DOM facts of the action's target for the classifier (form method, card autofill); never its text.
  const readActionStructure = async (name, args, preJudgedKind) => {
    if (preJudgedKind !== undefined && preJudgedKind !== null && preJudgedKind !== '') return null;
    const results = [];
    for (const target of actionStructureTargets(name, args)) {
      if (target === null) continue;
      const reply = await Promise.race([
        callChild('browser_evaluate', target ? { element: String((args && args.element) || 'action target'), target, function: ACTION_STRUCTURE_PROBE } : { function: ACTION_STRUCTURE_PROBE }),
        new Promise((resolve) => setTimeout(() => resolve(null), 2000)),
      ]).catch(() => null);
      results.push(structureFromReply(reply));
    }
    return mergeActionStructure(results);
  };

  // Internally sends a tools/call to the child and gets the response (for replay).
  const callChild = (name, args) => new Promise((resolve) => {
    const id = 'agx-' + (++internalSeq);
    waiters.set(id, resolve);
    forwardRaw(JSON.stringify({ jsonrpc: '2.0', id, method: 'tools/call', params: { name, arguments: stripClickEffect(name, args) } }));
  });

  const doReplay = async (name, replyId) => {
    const skill = loadSkill(name);
    if (!skill) { writeClient({ jsonrpc: '2.0', id: replyId, result: { content: [{ type: 'text', text: 'Skill not found: ' + name }], isError: true } }); return; }
    const results = [];
    for (const step of (skill.steps || [])) {
      const denied = await gate(step.name, step.arguments || {});
      if (denied) { results.push(step.name + ': BLOCKED(' + denied + ')'); writeClient({ jsonrpc: '2.0', id: replyId, result: { content: [{ type: 'text', text: 'Replay stopped — ' + denied + ' action needs approval (set AGENTLAS_BROWSER_AUTONOMY=trust for unattended replay).' }], isError: true } }); return; }
      if (step.name === 'browser_navigate' && step.arguments && step.arguments.url) currentUrl = String(step.arguments.url);
      const resp = await callChild(step.name, step.arguments || {});
      const isErr = resp && resp.result && resp.result.isError;
      results.push(step.name + (isErr ? ': error' : ': ok'));
      if (isErr) { writeClient({ jsonrpc: '2.0', id: replyId, result: { content: [{ type: 'text', text: 'Replay failed at ' + step.name + '. The page may have changed — re-explore and re-save the skill.\n' + results.join('\n') }], isError: true } }); return; }
    }
    writeClient({ jsonrpc: '2.0', id: replyId, result: { content: [{ type: 'text', text: 'Replayed skill "' + name + '" (' + (skill.steps || []).length + ' steps):\n' + results.join('\n') }] } });
  };

  // client -> child direction
  const handleClientLine = (line) => {
    if (closing) return;
    if (!line.trim()) { forwardRaw(line); return; }
    let msg; try { msg = JSON.parse(line); } catch (e) { forwardRaw(line); return; }
    if (msg && msg.method === 'tools/call' && msg.params) {
      const name = msg.params.name || '';
      const args = msg.params.arguments || {};
      // Skill tools are handled locally (not sent to the child).
      if (name === 'browser_skill_list') { writeClient({ jsonrpc: '2.0', id: msg.id, result: { content: [{ type: 'text', text: JSON.stringify(listSkills()) }] } }); return; }
      if (name === 'browser_skill_save') {
        try { const doc = saveSkill(args.name, recording.slice(), args.description); writeClient({ jsonrpc: '2.0', id: msg.id, result: { content: [{ type: 'text', text: 'Saved skill "' + doc.name + '" with ' + doc.steps.length + ' steps → ' + skillPath(doc.name) }] } }); }
        catch (e) { writeClient({ jsonrpc: '2.0', id: msg.id, result: { content: [{ type: 'text', text: 'Save failed: ' + String(e) }], isError: true } }); }
        return;
      }
      void ensureBrowserForTool().then(() => {
        if (closing) return;
        if (name === 'browser_skill_replay') { void doReplay(args.name, msg.id); return; }
        // Ordinary action: approval gate + record. If the parent sent a pre-judged verdict via _meta, that verdict wins.
        if (name === 'browser_navigate' && args.url) currentUrl = String(args.url);
        const preJudgedKind = (msg.params._meta || {})['agentlas/actionKind'];
        const childArgs = stripClickEffect(name, args);
        const childLine = childArgs === args ? line : JSON.stringify({ ...msg, params: { ...msg.params, arguments: childArgs } });
        void readActionStructure(name, args, preJudgedKind).then((structure) => {
          if (closing) return;
          if (classifyAction(name, args, preJudgedKind, structure)) {
            gate(name, args, preJudgedKind, structure).then((denied) => {
              if (denied) { writeClient({ jsonrpc: '2.0', id: msg.id, result: { content: [{ type: 'text', text: 'BLOCKED: The user did not approve this ' + denied + ' browser action.' }], isError: true } }); return; }
              if (RECORDABLE.has(name)) pending.set(msg.id, { name, arguments: args });
              forwardRaw(childLine);
            });
            return;
          }
          if (RECORDABLE.has(name)) pending.set(msg.id, { name, arguments: args });
          forwardRaw(childLine);
        });
      }).catch((error) => writeBrowserStartFailure(msg.id, error));
      return;
    }
    forwardRaw(line);
  };

  // child -> client direction (intercepts responses: replay waiter / recording / tools/list injection)
  const handleChildLine = (line) => {
    if (!line.trim()) { process.stdout.write(line + '\n'); return; }
    let msg; try { msg = JSON.parse(line); } catch (e) { process.stdout.write(line + '\n'); return; }
    // An internal replay response goes to the waiter, never to the client.
    if (msg && typeof msg.id === 'string' && waiters.has(msg.id)) { const r = waiters.get(msg.id); waiters.delete(msg.id); r(msg); return; }
    // Response to the client's original action -> record it on success.
    if (msg && msg.id != null && pending.has(msg.id)) {
      const call = pending.get(msg.id); pending.delete(msg.id);
      const isErr = msg.result && msg.result.isError;
      if (!isErr && !msg.error) recording.push(call);
    }
    // tools/list response -> inject skill tools.
    if (msg && msg.result && Array.isArray(msg.result.tools)) {
      for (const tool of msg.result.tools) if (tool && tool.name === 'browser_click') withClickEffectSchema(tool);
      const have = new Set(msg.result.tools.map((t) => t.name));
      for (const st of SKILL_TOOLS) if (!have.has(st.name)) msg.result.tools.push(st);
      process.stdout.write(JSON.stringify(msg) + '\n'); return;
    }
    process.stdout.write(line + '\n');
  };

  let cbuf = '';
  child.stdout.on('error', () => finish(1));
  child.stdout.on('data', (chunk) => {
    cbuf += chunk.toString('utf8'); let i;
    while ((i = cbuf.indexOf('\n')) >= 0) { const line = cbuf.slice(0, i); cbuf = cbuf.slice(i + 1); handleChildLine(line); }
  });
  let buf = '';
  process.stdin.on('data', (chunk) => {
    buf += chunk.toString('utf8'); let idx;
    while ((idx = buf.indexOf('\n')) >= 0) { const line = buf.slice(0, idx); buf = buf.slice(idx + 1); handleClientLine(line); }
  });
  process.stdin.on('end', () => {
    closing = true;
    try { child.stdin.end(); } catch (error) {}
    void childDrain.stop({ graceMs: 1500, forceAfterMs: 2000 });
  });
  const stopForSignal = (code) => {
    void childDrain.stop({ forceAfterMs: 2000 });
    finish(code);
  };
  process.once('SIGINT', () => stopForSignal(130));
  process.once('SIGTERM', () => stopForSignal(143));
}
// Run only when executed directly; importing the module (tests) must stay
// side-effect free so classifyAction can be unit-tested without a browser.
const invokedDirectly = (() => {
  /*
   * ★ 심볼릭 링크를 지나 실행돼도 자기 자신을 알아봐야 한다.
   *
   * `import.meta.url` 은 실제 경로로 풀려 오는데 `process.argv[1]` 은 사용자가 적은
   * 그대로다. 런타임은 `~/.agentlas/runtime/current` 라는 링크로 설치되므로, 그 경로로
   * 부르면 두 값이 달라 "임포트된 모듈" 로 판정되고 main() 이 아예 돌지 않는다.
   * 프로세스는 아무 말 없이 종료 0 으로 끝난다 — 오류도, 로그도 없다.
   *
   * 실측(2026-08-24): `current/...` 로 부르면 도구 0개·stderr 없음, 같은 파일을
   * `1.2.16/...` 실제 경로로 부르면 도구 27개. 이것이 호스트 CLI 가 브라우저를
   * 잡지 못하던 이유다. 양쪽을 실제 경로로 풀어서 비교한다.
   */
  try {
    if (!process.argv[1]) return false;
    const here = fs.realpathSync(fileURLToPath(import.meta.url));
    const invoked = fs.realpathSync(process.argv[1]);
    return here === invoked;
  } catch (e) {
    // 경로를 풀 수 없으면 예전 비교로 물러난다 — 못 푸는 것이 실행하지 않을 이유는 아니다.
    try { return !!process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href; }
    catch (e2) { return true; }
  }
})();
if (invokedDirectly) {
  main().catch((e) => { console.error('[agentlas-browser] fatal', e && e.stack || e); process.exit(1); });
}

/** Parse browser_evaluate's "### Result" block into the probe's facts (null when unreadable). */
function structureFromReply(reply) {
  const content = reply && reply.result && !reply.result.isError && Array.isArray(reply.result.content) ? reply.result.content : null;
  if (!content) return null;
  const text = content.filter((item) => item && item.type === 'text').map((item) => String(item.text || '')).join('\n');
  const at = text.indexOf('### Result');
  const body = (at >= 0 ? text.slice(at + 10) : text).split('\n### ')[0].trim();
  try { const value = JSON.parse(body); return value && typeof value === 'object' && value.found === true ? value : null; } catch (e) { return null; }
}

export { classifyAction, normalizeActionKindOverride, stripClickEffect, withClickEffectSchema, actionStructureTargets, mergeActionStructure, structureFromReply, ACTION_STRUCTURE_PROBE, siteLearningValidate, siteLearningMatch, siteLearningNormalizeDomain, siteLearningParseObservedUrl, siteLearningDomainMatches, siteLearningCanonicalJson, siteLearningContentJson };
