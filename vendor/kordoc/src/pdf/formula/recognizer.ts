/**
 * MFR (Mathematical Formula Recognition) — DeiT encoder + TrOCR decoder
 *
 * 모델: breezedeus/pix2text-mfr
 *   - encoder: DeiT distilled, input 384×384 → output [1, 578, 384]
 *   - decoder: TrOCR (no KV cache), vocab=1200, EOS=2
 *
 * 전처리 (DeiT): Catmull-Rom resize → /255 → (x - 0.5) / 0.5  == x*2 - 1
 *
 * 디코딩: greedy, start=[2], stop at 2 또는 max_new_tokens=256
 *         decoder 는 매 스텝 전체 시퀀스를 재계산 (no KV cache — 모델 고정)
 */

import type { InferenceSession, Tensor } from "onnxruntime-node"
import type { PreTrainedTokenizer } from "@huggingface/transformers"
import { postProcessLatex } from "./postprocess.js"
import type { PixelFrame } from "./types.js"

const MFR_IMG_SIZE = 384
const MFR_ENC_HIDDEN = 384
const MFR_MAX_NEW_TOKENS = 256
const MFR_EOS_ID = 2
const MFR_PAD_ID = 0

export interface RecognizeDeps {
  encoder: InferenceSession
  decoder: InferenceSession
  tokenizer: PreTrainedTokenizer
  ort: typeof import("onnxruntime-node")
}

/**
 * 단일 수식 crop 을 LaTeX 로 인식.
 * 입력 frame 은 이미 해당 영역만 잘린 RGBA 이미지이어야 한다 (recognizer 가 resize 수행).
 */
export async function recognizeFormula(
  deps: RecognizeDeps,
  crop: PixelFrame,
): Promise<string> {
  const tensor = deitPreprocess(crop, MFR_IMG_SIZE)
  const { ort, encoder, decoder, tokenizer } = deps

  const pixelInput = new ort.Tensor("float32", tensor, [1, 3, MFR_IMG_SIZE, MFR_IMG_SIZE])
  const encOut = await encoder.run({ pixel_values: pixelInput })

  const encKey =
    Object.keys(encOut).find((k) => k.includes("hidden")) ?? Object.keys(encOut)[0]
  const encTensor = encOut[encKey]
  if (!encTensor || encTensor.type !== "float32") {
    throw new Error("MFR encoder 출력 없음")
  }
  const encDims = encTensor.dims
  if (encDims.length !== 3) {
    throw new Error(`MFR encoder 차원 예상 3, 실제 ${encDims.length}`)
  }
  const encSeq = encDims[1]
  const encHidden = encDims[2]
  if (encHidden !== MFR_ENC_HIDDEN) {
    throw new Error(`MFR encoder hidden 예상 ${MFR_ENC_HIDDEN}, 실제 ${encHidden}`)
  }
  const encData = encTensor.data as Float32Array

  // greedy decode
  const tokens: number[] = [MFR_EOS_ID] // decoder_start_token_id

  for (let step = 0; step < MFR_MAX_NEW_TOKENS; step++) {
    const seqLen = tokens.length
    const idsArr = BigInt64Array.from(tokens.map((t) => BigInt(t)))
    const idsTensor = new ort.Tensor("int64", idsArr, [1, seqLen])

    // encoder_hidden_states 는 매 스텝 동일 — 복사 필요 (Tensor 는 buffer 소유)
    const hidCopy = new Float32Array(encData)
    const hidTensor = new ort.Tensor("float32", hidCopy, [1, encSeq, encHidden])

    const decOut = await decoder.run({
      input_ids: idsTensor,
      encoder_hidden_states: hidTensor,
    })

    const logitKey =
      Object.keys(decOut).find((k) => k.includes("logit")) ?? Object.keys(decOut)[0]
    const logitsTensor = decOut[logitKey]
    if (!logitsTensor || logitsTensor.type !== "float32") {
      throw new Error("MFR decoder logits 없음")
    }
    const dims = logitsTensor.dims
    if (dims.length !== 3) {
      throw new Error(`MFR decoder 차원 예상 3, 실제 ${dims.length}`)
    }
    const decSeq = dims[1]
    const vocab = dims[2]
    const logitsData = logitsTensor.data as Float32Array

    // 마지막 step logits 만
    const lastOffset = (decSeq - 1) * vocab
    let bestId = 0
    let bestVal = -Infinity
    for (let v = 0; v < vocab; v++) {
      const val = logitsData[lastOffset + v]
      if (val > bestVal) {
        bestVal = val
        bestId = v
      }
    }
    tokens.push(bestId)
    if (bestId === MFR_EOS_ID) break
  }

  // 첫 start 토큰 제외 + EOS/PAD 제거
  const body: number[] = []
  for (let i = 1; i < tokens.length; i++) {
    const t = tokens[i]
    if (t === MFR_EOS_ID) break
    if (t === MFR_PAD_ID) continue
    if (t < 0) continue
    body.push(t)
  }

  // Transformers.js tokenizer.decode 는 skip_special_tokens=true 기본
  const raw = tokenizer.decode(body, { skip_special_tokens: true })
  return postProcessLatex(raw)
}

/**
 * DeiT preprocess:
 *   resize to 384×384 (bilinear)
 *   (pixel/255 - 0.5) / 0.5  ==  pixel/127.5 - 1
 *   CHW layout
 */
export function deitPreprocess(crop: PixelFrame, target: number): Float32Array {
  const ts = target
  const out = new Float32Array(3 * ts * ts)
  const { data: src, width: srcW, height: srcH } = crop

  // 단순 nearest (이미 수식 crop 은 300DPI 근방이라 충분). 필요시 sharp bilinear 로 교체.
  for (let y = 0; y < ts; y++) {
    const sy = Math.min(srcH - 1, Math.max(0, Math.floor(((y + 0.5) / ts) * srcH)))
    for (let x = 0; x < ts; x++) {
      const sx = Math.min(srcW - 1, Math.max(0, Math.floor(((x + 0.5) / ts) * srcW)))
      const srcIdx = (sy * srcW + sx) * 4
      const r = src[srcIdx]
      const g = src[srcIdx + 1]
      const b = src[srcIdx + 2]

      const idx = y * ts + x
      out[idx] = r / 127.5 - 1
      out[ts * ts + idx] = g / 127.5 - 1
      out[2 * ts * ts + idx] = b / 127.5 - 1
    }
  }
  return out
}
