#!/usr/bin/env node
// Agentlas Browser (CDP) — 범용 엔진. 실제 로그인 Chrome 전용 프로필을 원격 디버깅 포트로 띄우고
// @playwright/mcp 를 CDP 로 붙여 MCP 브라우저 도구를 제공한다. 이 프로세스가 client ↔ @playwright/mcp
// 사이를 stdio 로 프록시하며 (1) 되돌릴 수 없는 행동 승인 게이트, (2) learn-and-replay 스킬 레이어를 얹는다.
// 의존성 0(순수 node). 개인 데이터는 로컬에서만 사용, 어디로도 전송하지 않는다.
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';
import { pathToFileURL } from 'node:url';

const PORT = Number(process.env.AGENTLAS_CDP_PORT || 9222);
const CDP_PROFILE = process.env.AGENTLAS_CDP_PROFILE || path.join(os.homedir(), '.agentlas', 'chrome-cdp-profile');
const HEADLESS = String(process.env.AGENTLAS_CDP_HEADLESS || '').toLowerCase() === '1';
const SKILLS_DIR = process.env.AGENTLAS_BROWSER_SKILLS_DIR || path.join(os.homedir(), '.agentlas', 'browser-skills');
const log = (...a) => console.error('[agentlas-browser]', ...a);

function chromeInfo() {
  const home = os.homedir();
  if (process.platform === 'darwin') {
    const exes = [
      '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
      path.join(home, 'Applications/Google Chrome.app/Contents/MacOS/Google Chrome'),
    ];
    return { userData: path.join(home, 'Library/Application Support/Google/Chrome'), exe: exes.find(fs.existsSync) || exes[0] };
  }
  if (process.platform === 'win32') {
    const lad = process.env.LOCALAPPDATA || path.join(home, 'AppData', 'Local');
    const exes = [
      path.join(process.env['PROGRAMFILES'] || 'C:\\Program Files', 'Google', 'Chrome', 'Application', 'chrome.exe'),
      path.join(process.env['PROGRAMFILES(X86)'] || 'C:\\Program Files (x86)', 'Google', 'Chrome', 'Application', 'chrome.exe'),
      path.join(lad, 'Google', 'Chrome', 'Application', 'chrome.exe'),
    ];
    return { userData: path.join(lad, 'Google', 'Chrome', 'User Data'), exe: exes.find(fs.existsSync) || exes[0] };
  }
  const exes = ['/usr/bin/google-chrome', '/usr/bin/google-chrome-stable', '/opt/google/chrome/chrome', '/usr/bin/chromium', '/usr/bin/chromium-browser'];
  return { userData: path.join(home, '.config', 'google-chrome'), exe: exes.find(fs.existsSync) || exes[0] };
}

function seedProfile(srcUserData, dst) {
  try {
    fs.mkdirSync(path.join(dst, 'Default'), { recursive: true });
    const rels = ['Local State', 'Default/Cookies', 'Default/Network/Cookies', 'Default/Login Data', 'Default/Web Data', 'Default/Preferences'];
    for (const rel of rels) {
      const s = path.join(srcUserData, ...rel.split('/'));
      const d = path.join(dst, ...rel.split('/'));
      if (fs.existsSync(s)) {
        fs.mkdirSync(path.dirname(d), { recursive: true });
        try { fs.copyFileSync(s, d); } catch (e) { log('copy skip', rel, String(e)); }
      }
    }
  } catch (e) { log('seedProfile failed', String(e)); }
}

function portReady(port) {
  return new Promise((resolve) => {
    const req = http.get({ host: '127.0.0.1', port, path: '/json/version', timeout: 1200 }, (res) => { res.resume(); resolve(res.statusCode === 200); });
    req.on('error', () => resolve(false));
    req.on('timeout', () => { req.destroy(); resolve(false); });
  });
}

function profileSeeded(dst) {
  return fs.existsSync(path.join(dst, 'Default', 'Cookies')) || fs.existsSync(path.join(dst, 'Default', 'Network', 'Cookies'));
}

async function ensureChrome() {
  if (await portReady(PORT)) { log('CDP already up on', PORT); return; }
  const { userData, exe } = chromeInfo();
  if (!fs.existsSync(exe)) throw new Error('Google Chrome executable could not be found: ' + exe);
  const force = process.env.AGENTLAS_CDP_SEED === '1';
  if (force || !profileSeeded(CDP_PROFILE)) { log(force ? 'seeding profile (forced import)' : 'seeding profile (first run)'); seedProfile(userData, CDP_PROFILE); }
  else { log('reusing persistent dedicated profile (no reseed)'); }
  const args = [
    '--user-data-dir=' + CDP_PROFILE, '--remote-debugging-port=' + PORT,
    '--no-first-run', '--no-default-browser-check', '--restore-last-session=false',
    '--disable-session-crashed-bubble', '--disable-features=Translate',
  ];
  if (HEADLESS) args.push('--headless=new');
  args.push('about:blank');
  log('launching Chrome on port', PORT, HEADLESS ? '(headless)' : '');
  const child = spawn(exe, args, { detached: true, stdio: 'ignore' });
  child.unref();
  for (let i = 0; i < 40; i++) { if (await portReady(PORT)) { log('CDP ready'); return; } await new Promise((r) => setTimeout(r, 500)); }
  throw new Error('Chrome CDP port did not open: ' + PORT);
}

// ── 승인 게이트 ──────────────────────────────────────────────────
// CONTRACT (fail-closed): the regexes below only LABEL the approval kind —
// they never make the final "no gate needed" decision for a commit-like
// action. A click/keypress/upload that submits, pays, sends, or deletes but
// misses every kind regex still raises an approval request with the generic
// 'sensitive-action' kind (deterministic conservative fallback — this process
// has no bridge to the resident judgment service). The parent client may
// supply a pre-judged classification via tools/call params._meta
// ['agentlas/actionKind'] ('payment'|'send'|'publish'|'delete'|
// 'sensitive-action'|'none'); that model-side judgment overrides the local
// lexical labeling, with 'none' meaning "judged safe, no gate". Trivial
// navigation/typing/reading stays ungated.
const PAY_RE = /(checkout|\bpay(ment)?\b|purchase|\bbuy\b|\border\b|donate|subscrib|billing|결제|구매|주문|결재)/;
const SEND_RE = /(publish|\bpost\b|\bsend\b|submit|tweet|retweet|\bshare\b|reply|\bcomment\b|delete|remove|confirm|전송|게시|삭제|제출|답글|댓글|공유|보내)/;
// Commit-shaped click text the kind regexes above do not label (fail-closed floor).
const COMMIT_RE = /(submit|confirm|proceed|continue|complete|finish|apply|save|agree|accept|register|sign\s?up|log\s?in|sign\s?in|place|transfer|wire|withdraw|확인|진행|계속|완료|저장|동의|수락|등록|가입|신청|접수|확정|송금|이체|출금|입금|이관|탈퇴|해지)/;
const APPROVAL_KINDS = new Set(['payment', 'send', 'publish', 'delete', 'sensitive-action']);
function normalizeActionKindOverride(kind) {
  const value = String(kind).toLowerCase().trim();
  if (value === 'none' || value === 'safe') return null;
  // an unknown override never widens autonomy — it degrades to the generic gate
  return APPROVAL_KINDS.has(value) ? value : 'sensitive-action';
}
function classifyAction(name, args, preJudgedKind) {
  if (preJudgedKind !== undefined && preJudgedKind !== null && preJudgedKind !== '') {
    return normalizeActionKindOverride(preJudgedKind);
  }
  let text = '';
  try { text = JSON.stringify(args || {}).toLowerCase(); } catch (e) { text = ''; }
  if (name === 'browser_navigate' || name === 'browser_navigate_back') return PAY_RE.test(text) ? 'payment' : null;
  if (name === 'browser_click' || name === 'browser_file_upload' || name === 'browser_press_key') {
    if (PAY_RE.test(text)) return 'payment';
    if (SEND_RE.test(text)) { if (/publish|\bpost\b|게시/.test(text)) return 'publish'; if (/delete|remove|삭제/.test(text)) return 'delete'; return 'send'; }
    // Fail-closed floor: commit-like action the kind regexes failed to label.
    if (name === 'browser_file_upload') return 'sensitive-action'; // local file data leaves the machine
    if (name === 'browser_press_key' && /^(enter|return|numpadenter)$/i.test(String((args || {}).key || ''))) {
      return 'sensitive-action'; // Enter submits the focused form
    }
    if (name === 'browser_click' && COMMIT_RE.test(text)) return 'sensitive-action';
  }
  return null;
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

// ── learn-and-replay 스킬 레이어 ─────────────────────────────────
// 재생/기록 대상 액션 툴(읽기 전용 snapshot/screenshot 등은 제외).
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

async function main() {
  await ensureChrome();
  const npx = process.platform === 'win32' ? 'npx.cmd' : 'npx';
  const child = spawn(npx, ['-y', '@playwright/mcp@latest', '--cdp-endpoint', 'http://127.0.0.1:' + PORT], { stdio: ['pipe', 'pipe', 'inherit'] });
  child.on('error', (e) => { log('failed to start @playwright/mcp', String(e)); process.exit(1); });
  child.on('exit', (code) => process.exit(code == null ? 0 : code));

  const recording = [];            // 이 세션에서 성공한 액션 시퀀스
  const pending = new Map();       // client 원본 tools/call: id -> {name, args}
  const waiters = new Map();       // 내부(replay) tools/call: id -> resolve
  let currentUrl = '';
  let internalSeq = 0;
  const writeClient = (obj) => { try { process.stdout.write(JSON.stringify(obj) + '\n'); } catch (e) {} };
  const forwardRaw = (line) => { try { child.stdin.write(line + '\n'); } catch (e) {} };

  // 승인 게이트 통과 여부 판정(공유). 통과=null, 거부=사유문자열.
  const gate = async (name, args, preJudgedKind) => {
    const actionType = classifyAction(name, args, preJudgedKind);
    if (!actionType) return null;
    let site = ''; try { site = new URL(currentUrl).host; } catch (e) { site = currentUrl; }
    const summaryPrefix = actionType === 'sensitive-action'
      ? 'sensitive-action (unclassified commit-like action; deterministic fallback gate): '
      : actionType + ': ';
    const decision = await requestApproval(site, actionType, summaryPrefix + (args.element || args.url || name));
    return decision === 'approved' ? null : actionType;
  };

  // 내부에서 child 에 tools/call 을 보내고 응답을 받는다(replay 용).
  const callChild = (name, args) => new Promise((resolve) => {
    const id = 'agx-' + (++internalSeq);
    waiters.set(id, resolve);
    forwardRaw(JSON.stringify({ jsonrpc: '2.0', id, method: 'tools/call', params: { name, arguments: args } }));
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

  // client → child 방향
  const handleClientLine = (line) => {
    if (!line.trim()) { forwardRaw(line); return; }
    let msg; try { msg = JSON.parse(line); } catch (e) { forwardRaw(line); return; }
    if (msg && msg.method === 'tools/call' && msg.params) {
      const name = msg.params.name || '';
      const args = msg.params.arguments || {};
      // 스킬 툴은 로컬 처리(child 로 안 보냄).
      if (name === 'browser_skill_list') { writeClient({ jsonrpc: '2.0', id: msg.id, result: { content: [{ type: 'text', text: JSON.stringify(listSkills()) }] } }); return; }
      if (name === 'browser_skill_save') {
        try { const doc = saveSkill(args.name, recording.slice(), args.description); writeClient({ jsonrpc: '2.0', id: msg.id, result: { content: [{ type: 'text', text: 'Saved skill "' + doc.name + '" with ' + doc.steps.length + ' steps → ' + skillPath(doc.name) }] } }); }
        catch (e) { writeClient({ jsonrpc: '2.0', id: msg.id, result: { content: [{ type: 'text', text: 'Save failed: ' + String(e) }], isError: true } }); }
        return;
      }
      if (name === 'browser_skill_replay') { doReplay(args.name, msg.id); return; }
      // 일반 액션: 승인 게이트 + 기록. 부모가 _meta 로 사전판정을 보냈으면 그 판정이 우선.
      if (name === 'browser_navigate' && args.url) currentUrl = String(args.url);
      const preJudgedKind = (msg.params._meta || {})['agentlas/actionKind'];
      const actionType = classifyAction(name, args, preJudgedKind);
      if (actionType) {
        gate(name, args, preJudgedKind).then((denied) => {
          if (denied) { writeClient({ jsonrpc: '2.0', id: msg.id, result: { content: [{ type: 'text', text: 'BLOCKED: The user did not approve this ' + denied + ' browser action.' }], isError: true } }); return; }
          if (RECORDABLE.has(name)) pending.set(msg.id, { name, arguments: args });
          forwardRaw(line);
        });
        return;
      }
      if (RECORDABLE.has(name)) pending.set(msg.id, { name, arguments: args });
    }
    forwardRaw(line);
  };

  // child → client 방향 (응답 가로채기: replay waiter / 기록 / tools/list 주입)
  const handleChildLine = (line) => {
    if (!line.trim()) { process.stdout.write(line + '\n'); return; }
    let msg; try { msg = JSON.parse(line); } catch (e) { process.stdout.write(line + '\n'); return; }
    // 내부 replay 응답 → waiter 로, client 로는 안 보냄.
    if (msg && typeof msg.id === 'string' && waiters.has(msg.id)) { const r = waiters.get(msg.id); waiters.delete(msg.id); r(msg); return; }
    // client 원본 액션 응답 → 성공 시 기록.
    if (msg && msg.id != null && pending.has(msg.id)) {
      const call = pending.get(msg.id); pending.delete(msg.id);
      const isErr = msg.result && msg.result.isError;
      if (!isErr && !msg.error) recording.push(call);
    }
    // tools/list 응답 → 스킬 툴 주입.
    if (msg && msg.result && Array.isArray(msg.result.tools)) {
      const have = new Set(msg.result.tools.map((t) => t.name));
      for (const st of SKILL_TOOLS) if (!have.has(st.name)) msg.result.tools.push(st);
      process.stdout.write(JSON.stringify(msg) + '\n'); return;
    }
    process.stdout.write(line + '\n');
  };

  let cbuf = '';
  child.stdout.on('data', (chunk) => {
    cbuf += chunk.toString('utf8'); let i;
    while ((i = cbuf.indexOf('\n')) >= 0) { const line = cbuf.slice(0, i); cbuf = cbuf.slice(i + 1); handleChildLine(line); }
  });
  let buf = '';
  process.stdin.on('data', (chunk) => {
    buf += chunk.toString('utf8'); let idx;
    while ((idx = buf.indexOf('\n')) >= 0) { const line = buf.slice(0, idx); buf = buf.slice(idx + 1); handleClientLine(line); }
  });
  process.stdin.on('end', () => { try { child.stdin.end(); } catch (e) {} });
}
// Run only when executed directly; importing the module (tests) must stay
// side-effect free so classifyAction can be unit-tested without a browser.
const invokedDirectly = (() => {
  try { return !!process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href; }
  catch (e) { return true; }
})();
if (invokedDirectly) {
  main().catch((e) => { console.error('[agentlas-browser] fatal', e && e.stack || e); process.exit(1); });
}

export { classifyAction, normalizeActionKindOverride };
