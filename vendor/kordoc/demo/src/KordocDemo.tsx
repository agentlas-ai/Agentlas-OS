import {
  AbsoluteFill,
  interpolate,
  useCurrentFrame,
  spring,
  useVideoConfig,
  Sequence,
} from "remotion"

// ─── 색상 ────────────────────────────────────────────
const BG = "#0a0a0a"
const ACCENT = "#3b82f6"
const GREEN = "#22c55e"
const ORANGE = "#f97316"
const RED = "#ef4444"
const WHITE = "#ffffff"
const GRAY = "#6b7280"
const DARK_CARD = "#18181b"

// ─── Scene 1: 타이틀 (0-60) ─────────────────────────
const TitleScene: React.FC = () => {
  const frame = useCurrentFrame()
  const { fps } = useVideoConfig()

  const titleY = spring({ frame, fps, from: 40, to: 0, durationInFrames: 20 })
  const titleOpacity = interpolate(frame, [0, 15], [0, 1], { extrapolateRight: "clamp" })
  const subtitleOpacity = interpolate(frame, [20, 35], [0, 1], { extrapolateRight: "clamp" })
  const badgeOpacity = interpolate(frame, [35, 50], [0, 1], { extrapolateRight: "clamp" })

  return (
    <AbsoluteFill
      style={{
        background: BG,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        fontFamily: "'Pretendard', 'SF Pro Display', -apple-system, sans-serif",
      }}
    >
      <div
        style={{
          fontSize: 80,
          fontWeight: 800,
          color: WHITE,
          opacity: titleOpacity,
          transform: `translateY(${titleY}px)`,
          letterSpacing: "-2px",
        }}
      >
        kor<span style={{ color: ACCENT }}>doc</span>
      </div>
      <div
        style={{
          fontSize: 28,
          color: GRAY,
          opacity: subtitleOpacity,
          marginTop: 16,
          fontWeight: 500,
        }}
      >
        모두 파싱해버리겠다
      </div>
      <div
        style={{
          display: "flex",
          gap: 12,
          marginTop: 32,
          opacity: badgeOpacity,
        }}
      >
        {["npm", "CLI", "MCP"].map((label) => (
          <div
            key={label}
            style={{
              padding: "6px 18px",
              borderRadius: 20,
              border: `1px solid ${ACCENT}44`,
              color: ACCENT,
              fontSize: 16,
              fontWeight: 600,
            }}
          >
            {label}
          </div>
        ))}
      </div>
    </AbsoluteFill>
  )
}

// ─── Scene 2: 문서지옥 (60-120) ─────────────────────
const DocumentHell: React.FC = () => {
  const frame = useCurrentFrame()
  const { fps } = useVideoConfig()

  const files = [
    { name: "사업계획서.hwpx", color: ACCENT, delay: 0 },
    { name: "검토의견서.hwp", color: ORANGE, delay: 5 },
    { name: "교육과정.pdf", color: RED, delay: 10 },
    { name: "보고서_v3_최종.hwp", color: ORANGE, delay: 15 },
    { name: "운영계획(수정).hwpx", color: ACCENT, delay: 20 },
    { name: "예산서_final_진짜최종.pdf", color: RED, delay: 25 },
  ]

  const headerOpacity = interpolate(frame, [0, 10], [0, 1], { extrapolateRight: "clamp" })

  return (
    <AbsoluteFill
      style={{
        background: BG,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        fontFamily: "'Pretendard', -apple-system, sans-serif",
      }}
    >
      <div
        style={{
          fontSize: 22,
          color: GRAY,
          opacity: headerOpacity,
          marginBottom: 8,
          fontWeight: 500,
        }}
      >
        대한민국 공무원의 일상
      </div>
      <div
        style={{
          fontSize: 40,
          fontWeight: 700,
          color: WHITE,
          opacity: headerOpacity,
          marginBottom: 40,
        }}
      >
        문서지옥
      </div>

      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          gap: 12,
          maxWidth: 700,
          justifyContent: "center",
        }}
      >
        {files.map((file) => {
          const s = spring({ frame: frame - file.delay, fps, from: 0.5, to: 1, durationInFrames: 15 })
          const opacity = interpolate(frame - file.delay, [0, 10], [0, 1], { extrapolateRight: "clamp", extrapolateLeft: "clamp" })

          return (
            <div
              key={file.name}
              style={{
                background: DARK_CARD,
                border: `1px solid ${file.color}33`,
                borderRadius: 12,
                padding: "14px 24px",
                opacity,
                transform: `scale(${s})`,
              }}
            >
              <span style={{ color: file.color, fontSize: 14, fontWeight: 600 }}>
                {file.name.split(".").pop()?.toUpperCase()}
              </span>
              <span style={{ color: GRAY, fontSize: 14, marginLeft: 8 }}>
                {file.name}
              </span>
            </div>
          )
        })}
      </div>
    </AbsoluteFill>
  )
}

// ─── Scene 3: 파싱 파이프라인 (120-210) ─────────────
const ParsingPipeline: React.FC = () => {
  const frame = useCurrentFrame()
  const { fps } = useVideoConfig()

  const steps = [
    { label: "Magic Bytes", detail: "PK\\x03\\x04 → HWPX", delay: 0, color: ACCENT },
    { label: "ZIP + XML", detail: "manifest → sections", delay: 15, color: ACCENT },
    { label: "Table Builder", detail: "2-pass colSpan/rowSpan", delay: 30, color: GREEN },
    { label: "Markdown", detail: "# 교육과정 편성 계획", delay: 45, color: GREEN },
  ]

  const codeOpacity = interpolate(frame, [55, 65], [0, 1], { extrapolateRight: "clamp" })

  return (
    <AbsoluteFill
      style={{
        background: BG,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        fontFamily: "'Pretendard', -apple-system, sans-serif",
        gap: 40,
      }}
    >
      {/* 파이프라인 */}
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        {steps.map((step, i) => {
          const s = spring({ frame: frame - step.delay, fps, from: 0, to: 1, durationInFrames: 15 })
          const opacity = interpolate(frame - step.delay, [0, 10], [0, 1], {
            extrapolateRight: "clamp",
            extrapolateLeft: "clamp",
          })

          return (
            <div key={step.label} style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <div
                style={{
                  background: `${step.color}15`,
                  border: `1px solid ${step.color}44`,
                  borderRadius: 12,
                  padding: "16px 24px",
                  opacity,
                  transform: `scale(${s})`,
                  textAlign: "center",
                  minWidth: 160,
                }}
              >
                <div style={{ color: step.color, fontSize: 16, fontWeight: 700 }}>{step.label}</div>
                <div style={{ color: GRAY, fontSize: 13, marginTop: 4 }}>{step.detail}</div>
              </div>
              {i < steps.length - 1 && (
                <div style={{ color: GRAY, fontSize: 24, opacity }}>→</div>
              )}
            </div>
          )
        })}
      </div>

      {/* 코드 블록 */}
      <div
        style={{
          background: "#1e1e2e",
          borderRadius: 12,
          padding: "24px 32px",
          opacity: codeOpacity,
          fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
          fontSize: 18,
          lineHeight: 1.8,
          border: "1px solid #333",
          minWidth: 500,
        }}
      >
        <span style={{ color: "#c678dd" }}>import</span>
        <span style={{ color: WHITE }}>{" { "}</span>
        <span style={{ color: "#e5c07b" }}>parse</span>
        <span style={{ color: WHITE }}>{" } "}</span>
        <span style={{ color: "#c678dd" }}>from</span>
        <span style={{ color: "#98c379" }}> "kordoc"</span>
        <br />
        <br />
        <span style={{ color: "#c678dd" }}>const</span>
        <span style={{ color: WHITE }}> result = </span>
        <span style={{ color: "#c678dd" }}>await</span>
        <span style={{ color: "#61afef" }}> parse</span>
        <span style={{ color: WHITE }}>(buffer)</span>
        <br />
        <span style={{ color: "#7f848e" }}>// → markdown with tables preserved</span>
      </div>
    </AbsoluteFill>
  )
}

// ─── Scene 4: 결과 + CTA (210-300) ──────────────────
const ResultScene: React.FC = () => {
  const frame = useCurrentFrame()
  const { fps } = useVideoConfig()

  const tableOpacity = interpolate(frame, [0, 15], [0, 1], { extrapolateRight: "clamp" })
  const ctaScale = spring({ frame: frame - 45, fps, from: 0.8, to: 1, durationInFrames: 20 })
  const ctaOpacity = interpolate(frame, [40, 55], [0, 1], { extrapolateRight: "clamp" })

  return (
    <AbsoluteFill
      style={{
        background: BG,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        fontFamily: "'Pretendard', -apple-system, sans-serif",
        gap: 32,
      }}
    >
      {/* 마크다운 테이블 결과 */}
      <div
        style={{
          background: DARK_CARD,
          borderRadius: 12,
          padding: "20px 28px",
          opacity: tableOpacity,
          border: `1px solid ${GREEN}33`,
          fontSize: 14,
          fontFamily: "'JetBrains Mono', monospace",
          color: "#a0a0a0",
          lineHeight: 1.6,
          maxWidth: 700,
        }}
      >
        <div style={{ color: GREEN, marginBottom: 8, fontSize: 13, fontWeight: 600 }}>OUTPUT — Markdown</div>
        <span style={{ color: "#e5c07b" }}>## </span>
        <span style={{ color: WHITE }}>교육과정 편제 및 시간 운영 계획</span>
        <br /><br />
        <span style={{ color: GRAY }}>| 구분 | 1~2학년 | 3~4학년 | 5~6학년 |</span>
        <br />
        <span style={{ color: GRAY }}>| --- | --- | --- | --- |</span>
        <br />
        <span style={{ color: GRAY }}>| </span>
        <span style={{ color: WHITE }}>국어</span>
        <span style={{ color: GRAY }}> | 482 | 408 | 408 |</span>
        <br />
        <span style={{ color: GRAY }}>| </span>
        <span style={{ color: WHITE }}>수학</span>
        <span style={{ color: GRAY }}> | 256 | 272 | 272 |</span>
        <br />
        <span style={{ color: GRAY }}>| </span>
        <span style={{ color: WHITE }}>영어</span>
        <span style={{ color: GRAY }}> | — | 136 | 204 |</span>
      </div>

      {/* CTA */}
      <div
        style={{
          opacity: ctaOpacity,
          transform: `scale(${ctaScale})`,
          textAlign: "center",
        }}
      >
        <div style={{ fontSize: 48, fontWeight: 800, color: WHITE, letterSpacing: "-1px" }}>
          npm install <span style={{ color: ACCENT }}>kordoc</span>
        </div>
        <div style={{ fontSize: 20, color: GRAY, marginTop: 12 }}>
          HWP + HWPX + PDF → Markdown &nbsp;|&nbsp; Library &nbsp;|&nbsp; CLI &nbsp;|&nbsp; MCP
        </div>
      </div>
    </AbsoluteFill>
  )
}

// ─── 메인 컴포지션 ──────────────────────────────────
export const KordocDemo: React.FC = () => {
  return (
    <AbsoluteFill>
      <Sequence from={0} durationInFrames={60}>
        <TitleScene />
      </Sequence>
      <Sequence from={60} durationInFrames={60}>
        <DocumentHell />
      </Sequence>
      <Sequence from={120} durationInFrames={90}>
        <ParsingPipeline />
      </Sequence>
      <Sequence from={210} durationInFrames={90}>
        <ResultScene />
      </Sequence>
    </AbsoluteFill>
  )
}
