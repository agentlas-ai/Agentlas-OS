#!/usr/bin/env node
// 벤치 러너 — corpus 전체 파싱 후 문서별 품질 신호 리포트
// 사용법: node bench/run.mjs [corpus하위경로] [--md]  (--md: 변환 md를 bench/out에 저장)
import { readdir, readFile, writeFile, mkdir } from 'node:fs/promises';
import { join, extname, basename, relative } from 'node:path';
import { parse } from '../dist/index.js';

const root = new URL('.', import.meta.url).pathname;
const corpusDir = join(root, 'corpus', process.argv[2] ?? '');
const saveMd = process.argv.includes('--md');
const outDir = join(root, 'out');

async function* walk(dir) {
  for (const e of await readdir(dir, { withFileTypes: true })) {
    const p = join(dir, e.name);
    if (e.isDirectory()) yield* walk(p);
    else if (/\.(hwpx?|pdf|docx?|xlsx?|hml)$/i.test(e.name)) yield p;
  }
}

const rows = [];
for await (const file of walk(corpusDir)) {
  const rel = relative(join(root, 'corpus'), file);
  const buf = await readFile(file);
  const t0 = performance.now();
  let row = { file: rel, ext: extname(file).slice(1).toLowerCase() };
  try {
    const res = await parse(buf, { filename: basename(file) });
    const md = res.markdown ?? '';
    const blocks = res.blocks ?? [];
    const tables = blocks.filter(b => b.type === 'table');
    const nested = tables.reduce((n, t) => n + (t.rows ?? []).flat().filter(c => (c?.blocks ?? []).some(b => b.type === 'table')).length, 0);
    row = {
      ...row,
      ok: true,
      ms: Math.round(performance.now() - t0),
      mdLen: md.length,
      blocks: blocks.length,
      tables: tables.length,
      nestedTables: nested,
      images: blocks.filter(b => b.type === 'image').length,
      warnings: res.warnings ?? [],
      // 품질 휴리스틱 신호
      emptyMd: md.trim().length < 20,
      replacementChars: (md.match(/�/g) ?? []).length,
      puaChars: (md.match(/[-]/g) ?? []).length,
      brokenTableRows: (md.match(/^\|.*[^|]\s*$/gm) ?? []).length,
    };
    if (saveMd) {
      const outPath = join(outDir, rel.replaceAll('/', '__') + '.md');
      await mkdir(outDir, { recursive: true });
      await writeFile(outPath, md);
    }
  } catch (err) {
    row = { ...row, ok: false, ms: Math.round(performance.now() - t0), error: String(err?.message ?? err).slice(0, 200) };
  }
  rows.push(row);
}

const fails = rows.filter(r => !r.ok);
const empty = rows.filter(r => r.ok && r.emptyMd);
const warned = rows.filter(r => r.ok && r.warnings.length);
const repl = rows.filter(r => r.ok && (r.replacementChars > 0 || r.puaChars > 0));

console.log(JSON.stringify({
  total: rows.length,
  parsed: rows.length - fails.length,
  failed: fails.length,
  emptyOutput: empty.length,
  withWarnings: warned.length,
  withBadChars: repl.length,
  totalTables: rows.reduce((n, r) => n + (r.tables ?? 0), 0),
  totalNestedTables: rows.reduce((n, r) => n + (r.nestedTables ?? 0), 0),
}, null, 2));
console.log('\n--- 문제 문서 ---');
for (const r of [...fails, ...empty, ...warned, ...repl]) {
  console.log(JSON.stringify(r));
}
await mkdir(outDir, { recursive: true });
await writeFile(join(outDir, 'report.json'), JSON.stringify(rows, null, 2));
console.log('\nreport → bench/out/report.json');
