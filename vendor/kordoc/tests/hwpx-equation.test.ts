import { describe, it } from "node:test"
import assert from "node:assert/strict"
import { hmlToLatex } from "../src/hwpx/equation.js"

describe("hmlToLatex — single token convert map", () => {
  it("README 예제: LEFT ⌊ a+b RIGHT ⌋", () => {
    const out = hmlToLatex("LEFT ⌊ a+b RIGHT ⌋").replace(/\s+/g, " ").trim()
    assert.equal(out, "\\left \\lfloor a+b \\right \\rfloor")
  })

  it("pm, neq, leq 등 단일 토큰", () => {
    const out = hmlToLatex("a ± b != c LEQ d").replace(/\s+/g, " ").trim()
    assert.equal(out, "a \\pm b \\neq c \\leq d")
  })

  it("그리스 문자 (소문자/대문자)", () => {
    const out = hmlToLatex("alpha + PHI").replace(/\s+/g, " ").trim()
    assert.equal(out, "\\alpha + \\Phi")
  })

  it("\\left {  / \\right } 는 \\{ / \\} 로 바뀜", () => {
    const out = hmlToLatex("LEFT { x RIGHT }").replace(/\s+/g, " ").trim()
    assert.equal(out, "\\left \\{ x \\right \\}")
  })
})

describe("hmlToLatex — frac (over)", () => {
  it("{a} over {b} → \\frac{a}{b}", () => {
    const out = hmlToLatex("{a} over {b}").replace(/\s+/g, "")
    assert.equal(out, "\\frac{a}{b}")
  })

  it("중첩 frac", () => {
    const out = hmlToLatex("{ { 1 } over { x } } over { y }").replace(/\s+/g, "")
    assert.equal(out, "\\frac{\\frac{1}{x}}{y}")
  })
})

describe("hmlToLatex — root of", () => {
  it("root {3} of {x+1} → \\sqrt[3]{x+1}", () => {
    const out = hmlToLatex("root {3} of {x+1}").replace(/\s+/g, "")
    assert.equal(out, "\\sqrt[3]{x+1}")
  })
})

describe("hmlToLatex — vec / bar", () => {
  it("{ vec {AB} } → \\overrightarrow{AB}", () => {
    const out = hmlToLatex("{ vec {AB} }").replace(/\s+/g, "")
    assert.equal(out, "\\overrightarrow{AB}")
  })

  it("{ hat {x} } → \\widehat{x}", () => {
    const out = hmlToLatex("{ hat {x} }").replace(/\s+/g, "")
    assert.equal(out, "\\widehat{x}")
  })
})

describe("hmlToLatex — matrix / cases", () => {
  it("matrix {a & b # c & d} → \\begin{matrix} a & b \\\\ c & d \\end{matrix}", () => {
    // 원본은 outer brackets 제거 → 결과는 matrix 본문만
    const out = hmlToLatex("{ matrix {a & b # c & d} }")
    assert.ok(out.includes("\\begin{matrix}"))
    assert.ok(out.includes("\\end{matrix}"))
    assert.ok(out.includes("\\\\")) // row 구분자
  })

  it("cases 변환", () => {
    const out = hmlToLatex("{ cases { 1 & x>0 # 0 & x<=0 } }")
    assert.ok(out.includes("\\begin{cases}"))
    assert.ok(out.includes("\\end{cases}"))
  })
})

describe("hmlToLatex — brace (overbrace / underbrace)", () => {
  it("OVERBRACE {x+y} {n} → \\overbrace{x+y}^{n}", () => {
    const out = hmlToLatex("OVERBRACE {x+y} {n}").replace(/\s+/g, "")
    assert.equal(out, "\\overbrace{x+y}^{n}")
  })
})

describe("hmlToLatex — 통합 케이스", () => {
  it("근의 공식", () => {
    const out = hmlToLatex("x = { -b +- SQRT { b ^2 -4ac } } over {2a}")
    // over 변환 후 { -b +- \\sqrt { ... } } 가 분자로, {2a} 가 분모로
    assert.ok(out.includes("\\frac"))
    assert.ok(out.includes("-b"))
    assert.ok(out.includes("2a"))
  })

  it("빈 문자열/공백", () => {
    assert.equal(hmlToLatex(""), "")
    assert.equal(hmlToLatex("   ").trim(), "")
  })

  it("백틱은 공백으로 치환", () => {
    const out = hmlToLatex("a`+`b").replace(/\s+/g, " ").trim()
    assert.equal(out, "a + b")
  })
})
