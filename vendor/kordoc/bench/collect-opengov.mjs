#!/usr/bin/env node
// 서울 정보소통광장 결재문서 첨부 수집기 — 연구목적 저속 수집 (1~2초 간격)
// 사용법: node bench/collect-opengov.mjs [최대파일수] [시작페이지] [출력서브디렉토리] [추가쿼리]
// 예: node bench/collect-opengov.mjs 60 1 seoul-old "startDate=2014-01-01&endDate=2016-12-31"
import { writeFile, mkdir, readdir } from 'node:fs/promises';
import { join } from 'node:path';

const UA = 'kordoc-bench/3.0 (research; contact: ryuseungin@gmail.com)';
const BASE = 'https://opengov.seoul.go.kr';
const outDir = new URL(`./corpus/${process.argv[4] ?? 'seoul'}/`, import.meta.url).pathname;
const MAX_FILES = Number(process.argv[2] ?? 60);
const START_PAGE = Number(process.argv[3] ?? 1);
const EXTRA_QUERY = process.argv[5] ? `&${process.argv[5]}` : '';
const sleep = ms => new Promise(r => setTimeout(r, ms));
const jitter = () => 1000 + Math.random() * 1000;

await mkdir(outDir, { recursive: true });
const existing = new Set(await readdir(outDir));

let saved = 0;
for (let page = START_PAGE; page < START_PAGE + 10 && saved < MAX_FILES; page++) {
  const listUrl = `${BASE}/sanction/list?items_per_page=50&page=${page}${EXTRA_QUERY}`;
  const html = await (await fetch(listUrl, { headers: { 'User-Agent': UA } })).text();
  const nids = [...new Set([...html.matchAll(/href="\/sanction\/(\d+)"/g)].map(m => m[1]))];
  console.log(`page ${page}: 문서 ${nids.length}건`);
  await sleep(jitter());

  for (const nid of nids) {
    if (saved >= MAX_FILES) break;
    try {
      const detail = await (await fetch(`${BASE}/sanction/${nid}`, { headers: { 'User-Agent': UA } })).text();
      const links = [...new Set([...detail.matchAll(/href="(\/og\/com\/download\.php\?[^"]+)"/g)]
        .map(m => m[1].replaceAll('&amp;', '&')))];
      for (const link of links) {
        if (saved >= MAX_FILES) break;
        const dname = decodeURIComponent(link.match(/dname=([^&]+)/)?.[1] ?? '');
        if (!/\.(hwpx?|pdf)$/i.test(dname)) continue;
        const fname = `${nid}_${dname.replaceAll('/', '_')}`;
        if (existing.has(fname)) continue;
        const res = await fetch(BASE + link, { headers: { 'User-Agent': UA } });
        if (!res.ok) { console.log(`  ! ${nid} HTTP ${res.status}`); continue; }
        const buf = Buffer.from(await res.arrayBuffer());
        if (buf.length < 1000 || buf.subarray(0, 200).toString().includes('<!DOCTYPE')) continue;
        await writeFile(join(outDir, fname), buf);
        existing.add(fname);
        saved++;
        console.log(`  + [${saved}] ${fname} (${(buf.length / 1024).toFixed(0)}KB)`);
        await sleep(jitter());
      }
      await sleep(jitter());
    } catch (e) {
      console.log(`  ! ${nid}: ${e.message}`);
    }
  }
}
console.log(`완료: ${saved}건 저장 → ${outDir}`);
