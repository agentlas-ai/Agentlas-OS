/** kordoc CLI — 모두 파싱해버리겠다 */

import { readFileSync, writeFileSync, mkdirSync, statSync } from "fs"
import { basename, dirname, resolve, extname } from "path"
import { Command } from "commander"
import { parse, detectFormat, detectZipFormat, fillFormFields, extractFormFields, blocksToMarkdown, markdownToHwpx, fillHwpx } from "./index.js"
import type { ParseOptions } from "./types.js"
import { VERSION, toArrayBuffer, sanitizeError } from "./utils.js"

const program = new Command()

program
  .name("kordoc")
  .description("모두 파싱해버리겠다 — HWP, HWPX, PDF, XLSX, DOCX → Markdown")
  .version(VERSION)
  .argument("<files...>", "변환할 파일 경로 (HWP, HWPX, PDF, XLSX, DOCX)")
  .option("-o, --output <path>", "출력 파일 경로 (단일 파일 시)")
  .option("-d, --out-dir <dir>", "출력 디렉토리 (다중 파일 시)")
  .option("-p, --pages <range>", "페이지/섹션 범위 (예: 1-3, 1,3,5)")
  .option("--format <type>", "출력 형식: markdown (기본) 또는 json", "markdown")
  .option("--no-header-footer", "PDF 머리글/바닥글 자동 제거")
  .option("--formula-ocr", "PDF 수식 OCR 활성화 (MFD+MFR ONNX, 첫 사용 시 모델 ~155MB 자동 다운로드)")
  .option("--silent", "진행 메시지 숨기기")
  .action(async (files: string[], opts) => {
    const validFormats = ["markdown", "json"]
    if (!validFormats.includes(opts.format)) {
      process.stderr.write(`[kordoc] 지원하지 않는 형식: ${opts.format} (markdown 또는 json)\n`)
      process.exit(1)
    }
    for (let fi = 0; fi < files.length; fi++) {
      const filePath = files[fi]
      const absPath = resolve(filePath)
      const fileName = basename(absPath)
      const filePrefix = files.length > 1 ? `[${fi + 1}/${files.length}] ` : ""

      try {
        const fileSize = statSync(absPath).size
        if (fileSize > 500 * 1024 * 1024) {
          process.stderr.write(`\n[kordoc] SKIP: ${fileName} — 파일이 너무 큽니다 (${(fileSize / 1024 / 1024).toFixed(1)}MB)\n`)
          process.exitCode = 1
          continue
        }
        const buffer = readFileSync(absPath)
        const arrayBuffer = toArrayBuffer(buffer)
        const format = detectFormat(arrayBuffer)

        if (!opts.silent) {
          process.stderr.write(`[kordoc] ${filePrefix}${fileName} (${format}) ...`)
        }

        const parseOptions: ParseOptions = { filePath: absPath }
        if (opts.pages) parseOptions.pages = opts.pages as string
        if (opts.headerFooter === false) parseOptions.removeHeaderFooter = false
        if (opts.formulaOcr) parseOptions.formulaOcr = true
        if (!opts.silent) {
          parseOptions.onProgress = (current: number, total: number) => {
            process.stderr.write(`\r[kordoc] ${filePrefix}${fileName} (${format}) [${current}/${total}]`)
          }
        }
        const result = await parse(arrayBuffer, parseOptions)

        if (!result.success) {
          process.stderr.write(` FAIL\n`)
          process.stderr.write(`  → ${result.error}\n`)
          process.exitCode = 1
          continue
        }

        if (!opts.silent) process.stderr.write(` OK\n`)

        let markdown = result.markdown
        // --out-dir 시 이미지 참조 경로에 images/ 접두사 추가
        if (opts.outDir && result.images?.length) {
          markdown = markdown.replace(/!\[image\]\(image_/g, "![image](images/image_")
        }
        const output = opts.format === "json"
          ? JSON.stringify(result, (_key, value) =>
              value instanceof Uint8Array ? Buffer.from(value).toString("base64") : value
            , 2)
          : markdown

        // 이미지 저장 (--out-dir 또는 --output 시)
        const saveImages = (dir: string) => {
          if (!result.images?.length) return
          const imgDir = resolve(dir, "images")
          mkdirSync(imgDir, { recursive: true })
          for (const img of result.images) {
            writeFileSync(resolve(imgDir, img.filename), img.data)
          }
          if (!opts.silent) process.stderr.write(`  → ${result.images.length}개 이미지 → ${imgDir}\n`)
        }

        if (opts.output && files.length === 1) {
          writeFileSync(opts.output, output, "utf-8")
          if (!opts.silent) process.stderr.write(`  → ${opts.output}\n`)
          saveImages(resolve(opts.output, ".."))
        } else if (opts.outDir) {
          mkdirSync(opts.outDir, { recursive: true })
          const outExt = opts.format === "json" ? ".json" : ".md"
          const outPath = resolve(opts.outDir, fileName.replace(/\.[^.]+$/, outExt))
          writeFileSync(outPath, output, "utf-8")
          if (!opts.silent) process.stderr.write(`  → ${outPath}\n`)
          saveImages(opts.outDir)
        } else {
          process.stdout.write(output + "\n")
        }
      } catch (err) {
        process.stderr.write(`\n[kordoc] ERROR: ${fileName} — ${sanitizeError(err)}\n`)
        process.exitCode = 1
      }
    }
  })

program
  .command("watch <dir>")
  .description("디렉토리 감시 — 새 문서 자동 변환")
  .option("--webhook <url>", "결과 전송 웹훅 URL")
  .option("-d, --out-dir <dir>", "변환 결과 출력 디렉토리")
  .option("-p, --pages <range>", "페이지/섹션 범위")
  .option("--format <type>", "출력 형식: markdown 또는 json", "markdown")
  .option("--silent", "진행 메시지 숨기기")
  .action(async (dir: string, opts) => {
    const { watchDirectory } = await import("./watch.js")
    await watchDirectory({
      dir,
      outDir: opts.outDir,
      webhook: opts.webhook,
      format: opts.format,
      pages: opts.pages,
      silent: opts.silent,
    })
  })

program
  .command("fill <template>")
  .description("서식 문서의 빈칸을 채워서 출력 — kordoc fill 신청서.hwpx -f '성명=홍길동,전화=010-1234-5678' -o 결과.hwpx")
  .option("-f, --fields <pairs>", "채울 필드 (key=value 쉼표 구분 또는 JSON)")
  .option("-j, --json <path>", "채울 필드 JSON 파일 경로")
  .option("-o, --output <path>", "출력 파일 경로 (확장자로 포맷 결정: .md, .hwpx)")
  .option("--format <type>", "출력 포맷: hwpx-preserve (기본, 원본 스타일 보존), hwpx, markdown", "hwpx-preserve")
  .option("--dry-run", "채우지 않고 서식 필드 목록만 출력")
  .option("--silent", "진행 메시지 숨기기")
  .action(async (template: string, opts) => {
    try {
      const absPath = resolve(template)
      const fileSize = statSync(absPath).size
      if (fileSize > 500 * 1024 * 1024) {
        process.stderr.write(`[kordoc] 파일이 너무 큽니다 (${(fileSize / 1024 / 1024).toFixed(1)}MB)\n`)
        process.exit(1)
      }

      const buffer = readFileSync(absPath)
      const arrayBuffer = toArrayBuffer(buffer)

      if (!opts.silent) process.stderr.write(`[kordoc] ${basename(absPath)} 파싱 중...\n`)

      // --dry-run: 필드 목록만 출력
      if (opts.dryRun) {
        const result = await parse(arrayBuffer)
        if (!result.success) {
          process.stderr.write(`[kordoc] 파싱 실패: ${result.error}\n`)
          process.exit(1)
        }
        const formInfo = extractFormFields(result.blocks)
        if (formInfo.fields.length === 0) {
          process.stderr.write(`[kordoc] 서식 필드를 찾을 수 없습니다.\n`)
          process.exit(1)
        }
        process.stdout.write(JSON.stringify(formInfo, null, 2) + "\n")
        return
      }

      // 필드 값 파싱
      let values: Record<string, string> = {}
      if (opts.json) {
        const jsonPath = resolve(opts.json)
        const jsonContent = readFileSync(jsonPath, "utf-8")
        values = JSON.parse(jsonContent)
      } else if (opts.fields) {
        const fieldsStr: string = opts.fields
        if (fieldsStr.startsWith("{")) {
          values = JSON.parse(fieldsStr)
        } else {
          // "key1=value1,key2=value2" 파싱 — 값에 쉼표가 있을 수 있으므로
          // '=' 앞의 키를 기준으로 분리 (쉼표+한글/영문+= 패턴)
          const pairs = fieldsStr.split(/,(?=[가-힣A-Za-z][가-힣A-Za-z\s]*=)/)
          for (const pair of pairs) {
            const eqIdx = pair.indexOf("=")
            if (eqIdx > 0) {
              const key = pair.slice(0, eqIdx).trim()
              const val = pair.slice(eqIdx + 1).trim()
              values[key] = val
            }
          }
        }
      } else {
        process.stderr.write(`[kordoc] 채울 필드를 지정해주세요 (-f 또는 -j 옵션)\n`)
        process.exit(1)
      }

      // 출력 포맷 결정
      let outputFormat = opts.format as string
      if (opts.output) {
        const ext = extname(opts.output).toLowerCase()
        if (ext === ".hwpx") outputFormat = outputFormat === "markdown" ? "hwpx-preserve" : outputFormat
        else if (ext === ".md") outputFormat = "markdown"
      }

      // ─── hwpx-preserve: 원본 ZIP 직접 수정 ───
      if (outputFormat === "hwpx-preserve") {
        const format = detectFormat(arrayBuffer)
        let isHwpx = format === "hwpx"
        if (isHwpx) {
          const zipFormat = await detectZipFormat(arrayBuffer)
          isHwpx = zipFormat === "hwpx"
        }
        if (!isHwpx) {
          if (!opts.silent) process.stderr.write(`[kordoc] HWPX가 아니므로 hwpx 모드로 전환합니다\n`)
          outputFormat = "hwpx"
        } else {
          const hwpxResult = await fillHwpx(arrayBuffer, values)
          if (!opts.silent) {
            process.stderr.write(`[kordoc] ${hwpxResult.filled.length}개 필드 채움 (원본 스타일 보존)\n`)
            if (hwpxResult.unmatched.length > 0) {
              process.stderr.write(`[kordoc] ⚠️ 매칭 실패: ${hwpxResult.unmatched.join(", ")}\n`)
            }
          }
          if (opts.output) {
            mkdirSync(dirname(resolve(opts.output)), { recursive: true })
            writeFileSync(resolve(opts.output), Buffer.from(hwpxResult.buffer))
            if (!opts.silent) process.stderr.write(`[kordoc] → ${resolve(opts.output)}\n`)
          } else {
            process.stdout.write(Buffer.from(hwpxResult.buffer))
          }
          return
        }
      }

      // ─── 일반 경로: parse → fill → output ───
      const result = await parse(arrayBuffer)
      if (!result.success) {
        process.stderr.write(`[kordoc] 파싱 실패: ${result.error}\n`)
        process.exit(1)
      }

      const formInfo = extractFormFields(result.blocks)
      if (!opts.silent) {
        process.stderr.write(`[kordoc] 서식 필드 ${formInfo.fields.length}개 감지 (확신도 ${(formInfo.confidence * 100).toFixed(0)}%)\n`)
      }

      const fillResult = fillFormFields(result.blocks, values)
      if (!opts.silent) {
        process.stderr.write(`[kordoc] ${fillResult.filled.length}개 필드 채움\n`)
        if (fillResult.unmatched.length > 0) {
          process.stderr.write(`[kordoc] ⚠️ 매칭 실패: ${fillResult.unmatched.join(", ")}\n`)
        }
      }

      const markdown = blocksToMarkdown(fillResult.blocks)

      if (outputFormat === "hwpx") {
        const hwpxBuffer = await markdownToHwpx(markdown)
        if (opts.output) {
          mkdirSync(dirname(resolve(opts.output)), { recursive: true })
          writeFileSync(resolve(opts.output), Buffer.from(hwpxBuffer))
          if (!opts.silent) process.stderr.write(`[kordoc] → ${resolve(opts.output)}\n`)
        } else {
          process.stdout.write(Buffer.from(hwpxBuffer))
        }
      } else {
        if (opts.output) {
          mkdirSync(dirname(resolve(opts.output)), { recursive: true })
          writeFileSync(resolve(opts.output), markdown, "utf-8")
          if (!opts.silent) process.stderr.write(`[kordoc] → ${resolve(opts.output)}\n`)
        } else {
          process.stdout.write(markdown + "\n")
        }
      }
    } catch (err) {
      process.stderr.write(`[kordoc] 오류: ${sanitizeError(err)}\n`)
      process.exit(1)
    }
  })

program
  .command("patch <original> <edited>")
  .description("서식 보존 라운드트립 패치 — 편집된 마크다운을 원본 HWPX/HWP에 in-place 반영 (kordoc patch 원본.hwpx 편집.md -o 출력.hwpx)")
  .option("-o, --output <path>", "출력 경로 (기본: <원본>.patched.hwpx|.hwp)")
  .option("--no-verify", "패치 후 재파싱 자동 검증 생략")
  .option("--silent", "진행 메시지 숨기기")
  .action(async (original: string, edited: string, opts) => {
    try {
      const { patchHwpx, patchHwp, detectFormat } = await import("./index.js")
      // 루트 커맨드의 동명 옵션(-o/--silent)이 서브커맨드 옵션을 가로채는 commander 동작 보완
      const rootOpts = program.opts()
      const output: string | undefined = opts.output ?? rootOpts.output
      const silent: boolean = opts.silent ?? rootOpts.silent
      const originalBuf = new Uint8Array(readFileSync(resolve(original)))
      const editedMarkdown = readFileSync(resolve(edited), "utf-8")

      const format = detectFormat(originalBuf.buffer as ArrayBuffer)
      const result = format === "hwp"
        ? await patchHwp(originalBuf, editedMarkdown, { verify: opts.verify !== false })
        : await patchHwpx(originalBuf, editedMarkdown, { verify: opts.verify !== false })
      if (!result.success || !result.data) {
        process.stderr.write(`[kordoc] 패치 실패: ${result.error ?? "알 수 없는 오류"}\n`)
        process.exit(1)
      }

      const ext = format === "hwp" ? ".hwp" : ".hwpx"
      const outPath = resolve(output ?? original.replace(/\.hwpx?$/i, "") + ".patched" + ext)
      mkdirSync(dirname(outPath), { recursive: true })
      writeFileSync(outPath, result.data)

      if (!silent) {
        process.stderr.write(`[kordoc] ${result.applied}개 변경 적용 (원본 서식 보존) → ${outPath}\n`)
        for (const s of result.skipped) {
          process.stderr.write(`[kordoc] ⚠️ SKIP: ${s.reason}${s.before ? ` | ${s.before}` : ""}\n`)
        }
        if (result.verification) {
          const v = result.verification.stats
          const residual = v.added + v.removed + v.modified
          process.stderr.write(residual === 0
            ? `[kordoc] ✓ 검증: 편집 마크다운과 재파싱 결과 완전 일치 (${v.unchanged}블록)\n`
            : `[kordoc] ⚠️ 검증 잔차: 수정 ${v.modified}, 추가 ${v.added}, 삭제 ${v.removed} (미지원 변경은 skip 목록 참조)\n`)
        }
      }
      if (result.skipped.length > 0) process.exitCode = 2
    } catch (err) {
      process.stderr.write(`[kordoc] 오류: ${sanitizeError(err)}\n`)
      process.exit(1)
    }
  })

program
  .command("mcp")
  .description("MCP 서버 실행 (Claude / Cursor / Windsurf 연동)")
  .action(async () => {
    await import("./mcp.js")
  })

program
  .command("setup")
  .description("대화형 설치 마법사 — AI 클라이언트 자동 등록 (Mac/Win/Linux)")
  .action(async () => {
    const { runSetup } = await import("./setup.js")
    await runSetup()
  })

program
  .command("check-formula-models")
  .description("PDF 수식 OCR 모델(MFD + MFR + tokenizer, ~155MB) 상태 확인 — 없거나 SHA 불일치면 다운로드")
  .option("--status-only", "상태만 JSON 으로 출력 (다운로드 안 함)")
  .action(async (opts) => {
    try {
      const { getFormulaModelStatus, ensureFormulaModels, getFormulaModelsDir } = await import(
        "./pdf/formula/index.js"
      )
      const dir = getFormulaModelsDir()
      if (opts.statusOnly) {
        const status = await getFormulaModelStatus()
        process.stdout.write(
          JSON.stringify(
            {
              modelsDir: dir,
              allReady: status.every((s) => s.verified),
              models: status.map((s) => ({
                name: s.spec.name,
                filename: s.spec.filename,
                sizeMb: s.spec.sizeMb,
                exists: s.exists,
                verified: s.verified,
                invalidReason: s.invalidReason,
                path: s.localPath,
              })),
            },
            null,
            2,
          ) + "\n",
        )
        return
      }
      process.stderr.write(`[kordoc-formula] 캐시 디렉토리: ${dir}\n`)
      await ensureFormulaModels((p) => {
        if (p.phase === "download" && p.total) {
          const pct = Math.floor((p.downloaded / p.total) * 100)
          process.stderr.write(
            `\r[kordoc-formula] ${p.spec.name} ${pct}% (${(p.downloaded / 1024 / 1024).toFixed(1)}/${(p.total / 1024 / 1024).toFixed(1)}MB)`,
          )
          if (p.downloaded >= p.total) process.stderr.write("\n")
        } else if (p.phase === "verify") {
          process.stderr.write(`[kordoc-formula] ${p.spec.name} SHA-256 검증 중...\n`)
        } else if (p.phase === "done") {
          process.stderr.write(`[kordoc-formula] ${p.spec.name} 준비 완료\n`)
        } else if (p.phase === "skip") {
          process.stderr.write(`[kordoc-formula] ${p.spec.name} 이미 존재 (skip)\n`)
        }
      })
      process.stdout.write("ok\n")
    } catch (err) {
      process.stderr.write(`[kordoc] 수식 모델 준비 실패: ${sanitizeError(err)}\n`)
      process.exit(1)
    }
  })

program.parse()
