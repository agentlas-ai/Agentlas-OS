#!/usr/bin/env node
// korea.kr 정책브리핑 보도자료 첨부파일 수집기 (robots.txt 허용 확인됨: Allow /)
// 사용법: node bench/collect-korea-kr.mjs [최대파일수] [출력서브디렉토리] [RSS피드명=pressrelease]
import { writeFile, mkdir, readdir } from 'node:fs/promises';
import { join } from 'node:path';

const UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) kordoc-bench/3.0';
const outDir = new URL(`./corpus/${process.argv[3] ?? 'korea-kr'}/`, import.meta.url).pathname;
const MAX_FILES = Number(process.argv[2] ?? 100);
const sleep = ms => new Promise(r => setTimeout(r, ms));

await mkdir(outDir, { recursive: true });
const existing = new Set(await readdir(outDir));
// 신규 서브디렉토리 수집 시 기본 디렉토리와의 문서 중복 방지
const baseDir = new URL('./corpus/korea-kr/', import.meta.url).pathname;
if (outDir !== baseDir) for (const f of await readdir(baseDir).catch(() => [])) existing.add(f);

const rss = await (await fetch(`https://www.korea.kr/rss/${process.argv[4] ?? 'pressrelease'}.xml`, { headers: { 'User-Agent': UA } })).text();
const items = [...rss.matchAll(/<item>(.*?)<\/item>/gs)].map(m => {
  const link = m[1].match(/<link>(?:<!\[CDATA\[)?\s*(.*?)\s*(?:\]\]>)?<\/link>/s)?.[1];
  const title = m[1].match(/<title>(?:<!\[CDATA\[)?\s*(.*?)\s*(?:\]\]>)?<\/title>/s)?.[1];
  return { link, title };
}).filter(x => x.link?.includes('newsId='));
console.log(`RSS 항목: ${items.length}건`);

let saved = 0;
for (const { link, title } of items) {
  if (saved >= MAX_FILES) break;
  const newsId = link.match(/newsId=(\d+)/)?.[1];
  try {
    const html = await (await fetch(link, { headers: { 'User-Agent': UA } })).text();
    const fileIds = [...new Set([...html.matchAll(/download\.do\?fileId=(\d+)&(?:amp;)?tblKey=GMN/g)].map(m => m[1]))];
    for (const fid of fileIds) {
      if (saved >= MAX_FILES) break;
      const url = `https://www.korea.kr/common/download.do?fileId=${fid}&tblKey=GMN`;
      const res = await fetch(url, { headers: { 'User-Agent': UA } });
      if (!res.ok) { console.log(`  ! ${fid} HTTP ${res.status}`); continue; }
      const cd = res.headers.get('content-disposition') ?? '';
      let fname = cd.match(/filename=["']?([^"';]+)/)?.[1] ?? `${fid}.bin`;
      try { fname = decodeURIComponent(fname); } catch {} // 잘못된 % 시퀀스는 원문 유지
      try { fname = Buffer.from(fname, 'latin1').toString('utf8'); } catch {}
      if (!/\.(hwpx?|pdf)$/i.test(fname)) { continue; }
      fname = `${newsId}_${fname.replaceAll('/', '_')}`;
      if (existing.has(fname)) continue;
      const buf = Buffer.from(await res.arrayBuffer());
      if (buf.length < 1000) continue;
      await writeFile(join(outDir, fname), buf);
      existing.add(fname);
      saved++;
      console.log(`  + [${saved}] ${fname} (${(buf.length / 1024).toFixed(0)}KB)`);
      await sleep(400);
    }
    await sleep(300);
  } catch (e) {
    console.log(`  ! ${newsId}: ${e.message}`);
  }
}
console.log(`완료: ${saved}건 저장 → ${outDir}`);
