"""Enterprise content-safety guard for cloud agent uploads.

Design goals (in priority order):
  1. Preserve agent quality — never blindly delete. Ambiguous / advisory / quoted
     mentions are FLAGGED for review, not removed. Only high-confidence malicious
     directives are redacted line-by-line.
  2. Defeat obfuscation — a normalized *detection shadow* (NFKC, invisible-char
     stripping, homoglyph + leetspeak folding, separator collapse) is scanned so
     that Cyrillic/leet/zero-width/spaced variants are caught without mutating the
     kept content.
  3. Multilingual — Korean / Chinese / Japanese injection & exfiltration concepts
     are first-class, not English-only.
  4. Multi-line — a sliding window catches injections split across lines to evade a
     per-line scanner.

Public surface:
  evaluate_line(line)            -> Reason | None      (single-line verdict)
  find_multiline_spans(lines)    -> list[SpanReason]   (cross-line verdicts)
  MAX_MULTILINE_WINDOW           -> int
Reason / SpanReason carry: rule, message, action ("redact" | "flag"), severity.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

MAX_MULTILINE_WINDOW = 5


@dataclass(frozen=True)
class Reason:
    rule: str
    message: str
    action: str  # "redact" (remove line) | "flag" (keep, needs-review)
    severity: str  # "high" | "medium" | "advice"


@dataclass(frozen=True)
class SpanReason:
    start: int  # 0-based inclusive line index
    end: int  # 0-based inclusive line index
    rule: str
    message: str
    action: str
    severity: str


# --------------------------------------------------------------------------- #
# Detection-shadow normalization
# --------------------------------------------------------------------------- #
# Common confusables folded to their ASCII base. Kept intentionally tight to
# avoid corrupting legitimate non-Latin content in the *shadow* (the original
# text is never modified by this map).
_HOMOGLYPH = {
    "а": "a", "ӓ": "a", "ɑ": "a", "α": "a", "ａ": "a", "４": "4",
    "е": "e", "ё": "e", "ε": "e", "ｅ": "e", "３": "3",
    "о": "o", "ο": "o", "օ": "o", "ｏ": "o", "０": "0",
    "р": "p", "ρ": "p", "ｐ": "p",
    "с": "c", "ϲ": "c", "ｃ": "c",
    "х": "x", "χ": "x", "ｘ": "x",
    "у": "y", "ү": "y", "ｙ": "y",
    "і": "i", "ї": "i", "ı": "i", "ⅰ": "i", "ｉ": "i", "１": "1",
    "ѕ": "s", "ｓ": "s", "５": "5",
    "ԁ": "d", "ｄ": "d",
    "ɡ": "g", "ｇ": "g",
    "ո": "n", "ｎ": "n",
    "ⅼ": "l", "ｌ": "l",
    "ᴜ": "u", "ｕ": "u",
    "ѵ": "v", "ν": "v", "ｖ": "v",
    "к": "k", "κ": "k", "ｋ": "k",
    "м": "m", "ｍ": "m",
    "т": "t", "τ": "t", "ｔ": "t", "７": "7",
    "г": "r", "ｒ": "r",
    "ь": "b", "ｂ": "b",
    "н": "h", "ｈ": "h",
    "ѡ": "w", "ｗ": "w",
    "ј": "j", "ｊ": "j",
    "ԛ": "q", "ｑ": "q",
    "ᴢ": "z", "ｚ": "z",
    "ｆ": "f",
}
_LEET = {"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s"}

# Unicode Tag block (invisible ASCII smuggling, U+E0000..U+E007F).
_TAG_LO, _TAG_HI = 0xE0000, 0xE007F


def _strip_invisible(text: str) -> str:
    out = []
    for ch in text:
        code = ord(ch)
        if _TAG_LO <= code <= _TAG_HI:
            continue
        cat = unicodedata.category(ch)
        if cat in ("Cf", "Cc") and ch not in "\t\n\r":
            continue  # zero-width, bidi overrides, other format/control
        out.append(ch)
    return "".join(out)


def _inline_decode_tags(text: str) -> str:
    """Decode Unicode Tag-block smuggling *in place* so a payload hidden between
    visible words (``Note:⟦ignore⟧ all previous``) reconstructs in the right
    order. Printable tag chars become their ASCII base; other tag chars drop."""
    out = []
    for ch in text:
        code = ord(ch)
        if _TAG_LO + 0x20 <= code <= _TAG_LO + 0x7E:
            out.append(chr(code - _TAG_LO))
        elif _TAG_LO <= code <= _TAG_HI:
            continue
        else:
            out.append(ch)
    return "".join(out)


_WS_RUN = re.compile(r"[ \t\f\v]+")
_NON_ALNUM = re.compile(r"[^0-9a-z가-힣一-鿿぀-ヿ]+", re.I)


def canonicalize(text: str) -> str:
    """Readable detection shadow: NFKC, invisible-char strip, homoglyph + leet
    fold, whitespace normalized to single spaces. Word boundaries are PRESERVED
    (spaces kept) so boundary-based concept rules still match Cyrillic/leet
    variants. Used only for matching — never written back into the package."""
    text = _inline_decode_tags(text)
    text = unicodedata.normalize("NFKC", _strip_invisible(text))
    text = "".join(_HOMOGLYPH.get(ch, ch) for ch in text).lower()
    text = "".join(_LEET.get(ch, ch) for ch in text)
    text = _WS_RUN.sub(" ", text)
    return text


def squish(text: str) -> str:
    """Aggressive shadow: canonical form with ALL separators (spaces, dots,
    dashes, punctuation) removed, leaving a pure alphanumeric stream. Defeats
    separated-letter obfuscation like ``i.g.n.o.r.e`` / ``i g n o r e`` that
    slips past boundary-based rules. Matched only by tight verb+target rules."""
    return _NON_ALNUM.sub("", canonicalize(text))


# --------------------------------------------------------------------------- #
# Concept rules (matched against the canonical shadow unless noted)
# --------------------------------------------------------------------------- #
_SENSITIVE = (
    r"(?:\.env|token|secret|password|passphrase|credentials?|cookies?|keychain|"
    r"ssh|id_rsa|api[-_ ]?keys?|openai[-_ ]?api|anthropic[-_ ]?api|agentlas[-_ ]?session|"
    r"git-credentials|login\.keychain|private[-_ ]?key|access[-_ ]?key)"
)
# High-value secrets where even bare access (no destination) is redacted — these
# are effectively never legitimate to read from a portable agent package.
_SENSITIVE_HIGH = (
    r"(?:\.env\b|id_rsa|login\.keychain|keychain|private[-_ ]?key|"
    r"agentlas[-_ ]?session|git-credentials|\.ssh/|ssh\s+keys?|document\.cookie)"
)
_EXFIL = r"(?:exfiltrate|transmit|send|post|upload|forward|phone home|collect|steal|dump|leak|copy|grab)"

# Each: (rule, regex, message, action, severity). action "redact" removes the line.
_ENGLISH_RULES: list[tuple[str, re.Pattern[str], str, str, str]] = [
    (
        "prompt-injection",
        re.compile(
            r"\b(?:ignore|disregard|override|forget|bypass|skip|drop)\w*\b.{0,120}"
            r"\b(?:system|developer|previous|prior|earlier|above|all|any|the)\b.{0,40}"
            r"\b(?:instructions?|prompts?|messages?|directives?|rules?|guidelines?|constraints?|guardrails?|safety)\b"
            r"|\b(?:reveal|print|show|expose|output|dump|leak|repeat|echo)\w*\b.{0,120}"
            r"\b(?:system prompt|hidden instructions?|developer message|chain[- ]?of[- ]?thought|reasoning|secret|api ?key)\b"
            r"|\b(?:pay no attention to|ignore|disregard)\b.{0,60}\b(?:earlier|previous|prior|above)\b.{0,40}\b(?:directives?|instructions?|rules?)\b"
            r"|\b(?:no longer apply|do not apply|are void|are revoked)\b"
            r"|\b(?:you are now|act as|pretend to be)\b.{0,30}\b(?:dan|jailbreak|unrestricted|developer mode)\b"
            r"|\bjailbreak\b|\bdan mode\b|\bdeveloper mode\b"
            # reversed order: target ("system prompt") precedes the reveal verb
            r"|\bsystem prompt\b.{0,30}\b(?:reveal|print|show|expose|output|dump|leak|repeat|echo|paste|verbatim)\w*\b",
            re.I,
        ),
        "Removed prompt-injection style instruction before upload.",
        "redact",
        "high",
    ),
    (
        "instruction-reset",
        re.compile(
            r"\b(?:set aside|put aside|ignore|abandon|discard)\b.{0,50}"
            r"\b(?:your |the )?(?:guidelines?|rules?|constraints?|restrictions?|configuration|guardrails?)\b"
            r"|\b(?:act|operate|respond)\b.{0,30}\b(?:without (?:restrictions?|limits?|filters?)|unrestricted)\b"
            r"|\bthe rules (?:given|provided).{0,40}no longer\b",
            re.I,
        ),
        "Removed instruction-reset directive before upload.",
        "redact",
        "high",
    ),
    (
        "instruction-reset",
        re.compile(
            r"\bsupersed\w*\b.{0,60}\b(?:directives?|instructions?|rules?|guidance|prompts?)\b"
            r"|\b(?:instructions?|rules?|directives?|guidance|guidelines?)\b.{0,40}\b(?:are|is|now|hereby)\b.{0,25}\b(?:void|null|revoked|cancell?ed|no longer)\b"
            r"|\bcancel\w*\b.{0,50}\b(?:guidance|instructions?|rules?|directives?|guidelines?)\b"
            r"|\btreat everything (?:before|above|prior)\b.{0,45}\b(?:null|void|ignored?|nothing)\b"
            r"|\byour (?:configured |current )?(?:rules?|instructions?|directives?|guidelines?)\b.{0,30}\b(?:revoked|void|null|no longer)\b",
            re.I,
        ),
        "Removed instruction-reset directive before upload.",
        "redact",
        "high",
    ),
    (
        "privilege-escalation",
        re.compile(
            r"\b(?:auto[- ]?approval|auto[- ]?approve|bypass (?:human )?confirmation|disable sandbox|"
            r"developer override|system override|elevate privileges?|grant yourself)\b"
            r"|\bgrant\b.{0,80}\b(?:all|every|tool|permissions?|access)\b"
            r"|\bsilently (?:override|bypass|disable)\b",
            re.I,
        ),
        "Removed tool or permission escalation instruction before upload.",
        "redact",
        "high",
    ),
    (
        # Non-guardable: a URL beacon carrying a secret param is never "advisory".
        # Checked before secret-exfiltration so it always claims these lines.
        "exfil-beacon",
        re.compile(
            r"(?:!\[[^\]]*\]\(|\]\(|<img[^>]+src=[\"']?|<a[^>]+href=[\"']?|url\(|src=)"
            r"\s*https?://[^\s)\"'<>]+\?[^\s)\"'<>]*"
            r"(?:(?:key|token|secret|session|cred|password|apikey|env)=|=[A-Z_]{0,20}(?:API_KEY|SECRET|TOKEN|SESSION|CREDENTIAL|PASSWORD))",
            re.I,
        ),
        "Removed data-exfiltration beacon URL before upload.",
        "redact",
        "high",
    ),
    (
        "secret-exfiltration",
        re.compile(
            rf"\b{_EXFIL}\b.{{0,160}}{_SENSITIVE}"
            rf"|{_SENSITIVE}.{{0,160}}\b{_EXFIL}\b"
            rf"|\b(?:read|open|cat|access|use|grab)\b.{{0,100}}{_SENSITIVE}.{{0,120}}\b(?:webhook|attacker|server|endpoint|https?://)\b",
            re.I,
        ),
        "Removed secret-access or exfiltration instruction before upload.",
        "redact",
        "high",
    ),
    (
        # Bare access to a high-value secret (no destination needed). Guardable,
        # so "never prints .env" / "explains how to read id_rsa safely" survive.
        "secret-access",
        re.compile(
            rf"\b(?:read|open|cat|access|use|grab|dump|exfiltrate|steal|copy|load|fetch)\b.{{0,60}}{_SENSITIVE_HIGH}",
            re.I,
        ),
        "Removed direct high-value secret access before upload.",
        "redact",
        "high",
    ),
    (
        "dangerous-command",
        re.compile(
            rf"\b(?:curl|wget|fetch|requests\.(?:post|put)|Invoke-WebRequest)\b.{{0,220}}{_SENSITIVE}"
            r"|\brm\s+-rf\s+(?:/|~|\$home)"
            r"|\bmkfs\."
            r"|\bdd\s+if=/dev/"
            r"|\bchmod\s+777\b"
            r"|\bsudo\b.{0,80}\b(?:sh|bash|zsh)\b"
            r"|\b(?:curl|wget)\b[^\n|&;]{0,200}\|\s*(?:sh|bash|zsh|python)\b",
            re.I,
        ),
        "Removed destructive or exfiltrating command before upload.",
        "redact",
        "high",
    ),
    (
        "encoded-execution",
        re.compile(
            r"\b(?:base64|atob|b64decode|frombase64string|fromcharcode|unescape)\b.{0,100}"
            r"\b(?:exec|execute|eval|bash|sh|powershell|zsh|command|payload|run|follow)\b"
            r"|\b(?:eval|exec)\b.{0,100}\b(?:atob|base64|b64decode|fromcharcode)\b"
            r"|\bdecode this (?:base64|payload).{0,60}\b(?:follow|run|execute|exec|eval)\b",
            re.I,
        ),
        "Removed encoded execution instruction before upload.",
        "redact",
        "high",
    ),
    (
        "persistence",
        re.compile(
            r"\b(?:create|install|add|keep|maintain|drop|register)\b.{0,80}"
            r"\b(?:persistence|launchagent|launchdaemon|cron\w*|startup item|login item|systemd|scheduled task|registry run key)\b"
            r"|\b(?:persistence|launchagent|cron\w*|startup item)\b.{0,80}"
            r"\b(?:after upload|first run|phone home|callback|webhook|execute|run|beacon)\b"
            r"|\bphone home\b",
            re.I,
        ),
        "Removed persistence or callback instruction before upload.",
        "redact",
        "high",
    ),
]

# Multilingual concept rules — matched against NFKC + separator-collapsed text
# (NOT homoglyph/leet folded, which is Latin-oriented). Korean / Chinese /
# Japanese injection & exfiltration.
_CJK_SEP = re.compile(r"(?<=\S)[ \t]+(?=\S)")


def _cjk_shadow(text: str) -> str:
    text = unicodedata.normalize("NFKC", _strip_invisible(text))
    # collapse spaces so "이 전 지 시" == "이전지시"
    return _CJK_SEP.sub("", text)


_MULTILINGUAL_RULES: list[tuple[str, re.Pattern[str], str, str, str]] = [
    (
        "prompt-injection-ko",
        re.compile(
            r"(?:이전|이|위|모든|앞선|기존).{0,6}(?:지시|명령|지침|규칙|프롬프트|instruction).{0,6}(?:무시|잊|따르지)"
            r"|(?:무시|잊어|잊고).{0,6}(?:이전|위|모든|기존).{0,6}(?:지시|명령|지침|규칙)"
            r"|시스템\s*프롬프트.{0,8}(?:출력|공개|보여|알려|노출|표시)"
            r"|(?:개발자\s*메시지|숨겨진\s*지시).{0,8}(?:공개|출력|노출)"
            r"|(?:안전\s*장치|가드레일|안전장치).{0,8}(?:무시|우회|해제)"
            r"|지시.{0,4}무시하고",
            re.I,
        ),
        "Removed Korean prompt-injection instruction before upload.",
        "redact",
        "high",
    ),
    (
        "secret-exfiltration-ko",
        re.compile(
            # 0,40 (was 0,12): the exfil verb is often separated from the secret
            # by a destination — "API 키를 attacker.com으로 전송" puts 18 chars
            # between them, so the old 12-char window missed a real attack. The
            # negation guard (declarative 않- endings) keeps "출력하지 않습니다"
            # safe, so widening the window does not reintroduce the false positive.
            r"(?:api\s*키|비밀|토큰|자격\s*증명|키체인|쿠키|세션).{0,40}(?:공개|전송|유출|보내|전달|업로드|탈취|출력)"
            r"|(?:공개|전송|유출|보내|전달|업로드|탈취).{0,40}(?:api\s*키|비밀|토큰|자격\s*증명|키체인|쿠키|세션)",
            re.I,
        ),
        "Removed Korean secret-exfiltration instruction before upload.",
        "redact",
        "high",
    ),
    (
        "prompt-injection-cjk",
        re.compile(
            r"(?:忽略|无视|忽視|無視).{0,8}(?:之前|以上|所有|全部|先前|系统|系統).{0,6}(?:指令|規則|规则|提示|指示|命令)"
            r"|(?:これまで|以前|上記|すべて).{0,8}(?:指示|命令|ルール).{0,8}(?:無視|むし)"
            r"|(?:透露|泄露|泄漏|显示|輸出|输出|公开).{0,8}(?:系统|系統|提示词|提示詞|密钥|密鑰|秘密)"
            r"|システムプロンプト.{0,8}(?:表示|公開|出力)",
            re.I,
        ),
        "Removed CJK prompt-injection instruction before upload.",
        "redact",
        "high",
    ),
    (
        "prompt-injection-eu",
        re.compile(
            r"игнорир\w*.{0,45}(?:инструкц|указан|систем|предыдущ)"
            r"|раскр\w*.{0,25}(?:систем|промпт)"
            r"|\bignora\w*\b.{0,40}\binstruccion\w*"
            r"|\brevela\w*\b.{0,25}(?:prompt|sistema)"
            r"|\bignore[zr]?\b.{0,45}instructions?\s+pr[ée]c[ée]dentes"
            r"|r[ée]v[eè]l\w*.{0,25}(?:prompt|syst[eè]me)"
            r"|ignorier\w*.{0,45}anweisung\w*"
            r"|\bzeig\w*\b.{0,25}(?:system|prompt)",
            re.I,
        ),
        "Removed non-English prompt-injection instruction before upload.",
        "redact",
        "high",
    ),
]

# Compact rules matched against the fully-squished shadow (no separators). These
# defeat separated-letter obfuscation (``i.g.n.o.r.e``, ``o_v_e_r_r_i_d_e``) that
# has no word boundaries. Kept tight (verb immediately followed by malicious
# target within a short gap) so concatenated benign prose does not match.
_SQUISH_RULES: list[tuple[str, re.Pattern[str], str, str, str]] = [
    (
        "prompt-injection",
        re.compile(
            r"(?:ignore|disregard|override|forget|bypass|skip)\w{0,3}(?:all|any|the|your|previous|prior|earlier|above|system|developer){0,4}"
            r"(?:instruction|prompt|rule|directive|guideline|guardrail|constraint|safety)",
        ),
        "Removed prompt-injection style instruction before upload.",
        "redact",
        "high",
    ),
    (
        "prompt-injection",
        re.compile(
            r"(?:reveal|print|show|expose|output|dump|leak|repeat|echo)\w{0,3}(?:the|your|me|all){0,3}"
            r"(?:systemprompt|hiddeninstruction|developermessage|secret|apikey|token|password)",
        ),
        "Removed prompt-injection style instruction before upload.",
        "redact",
        "high",
    ),
    (
        "instruction-reset",
        re.compile(r"(?:override|disable|bypass|remove)(?:the|system|all){0,3}(?:safety|guardrail|sandbox|restriction|filter)"),
        "Removed instruction-reset directive before upload.",
        "redact",
        "high",
    ),
    (
        "secret-exfiltration",
        re.compile(
            r"(?:exfiltrate|transmit|leak|steal|dump|forward|upload)(?:the|my|user){0,3}"
            r"(?:secret|token|apikey|password|credential|env|keychain|session|privatekey)",
        ),
        "Removed secret-access or exfiltration instruction before upload.",
        "redact",
        "high",
    ),
]


# Invisible-content tripwire: a line whose *rendered* form loses characters to
# invisible/format smuggling is itself suspicious. Flagged when no stronger rule
# already fired, so legitimate content survives but reviewers are alerted.
_INVISIBLE_RE = re.compile(r"[​‌‍﻿⁠‪-‮⁦-⁩]")


# --------------------------------------------------------------------------- #
# Precision guards — keep quality high, avoid over-redaction
# --------------------------------------------------------------------------- #
# Negation preceding a dangerous token turns a directive into advice.
# Kept intentionally narrow: only unambiguously *defensive* markers. Words like
# "not"/"without" were removed — attackers use them ("act without restrictions").
_NEGATION_RE = re.compile(
    # English negation. "no longer" etc. handled elsewhere; here we cover the
    # imperative and modal negations a safety instruction actually uses:
    # "never read a secret", "must not print", "do not commit", "without exposing".
    # NOTE: "without" is deliberately NOT here. It cuts both ways —
    # "without exposing the value" is safe, but "use keychain creds without
    # asking" is an approval bypass. never/not/않- already cover the safety copy,
    # so admitting "without" would only reintroduce a real-attack false negative.
    r"\b(?:never|do not|don't|dont|does not|doesn't|must not|mustn't|"
    r"should not|shouldn't|cannot|can't|won't|will not|avoid|"
    r"no\b|not\b|instead of|rather than|prefer)\b|"
    # Korean negation. The old rule only caught imperative prohibitions
    # (하지마/금지/절대); safety copy far more often uses the declarative negative
    # ENDING — "출력하지 않습니다", "읽지 않고", "요구하지 않으며". Without these,
    # "API 키 값은 출력하지 않습니다" (a security promise) was redacted as an
    # exfiltration instruction. Match the 않- negator and the 지 않 construction,
    # plus "~로만"/"이름만" (name-only) framing that safety copy uses.
    r"하지\s*마|하지마|금지|말\s*것|말아야|절대|"
    r"않\s*(?:습니다|는다|아|으며|고|은|을|다)|지\s*않|"
    r"이름(?:으로)?만|명칭(?:으로)?만|name(?:s)?\s*only|by\s*name",
    re.I,
)
# Educational / quoted context: the trigger appears inside quotes and the line is
# about language, examples, or defense — not an instruction to the model.
_EDU_CONTEXT_RE = re.compile(
    r"\b(?:translate|translation|phrase|means?|spelled|definition|"
    r"defend|defense|protect|detect|explain|lesson|teach|tutorial|what is|documentation)\b"
    # "example" but NOT the reserved domains example.com / example.invalid / …
    r"|\bexamples?\b(?!\.\w)"
    r"|번역|예시|예문|방어|설명|정의",
    re.I,
)
_QUOTED_RE = re.compile(r"""['"“”‘’「」『』]""")

# Descriptive / educational framing: the line is *talking about* an attack,
# capability, or command — not issuing one. Security-training, prompt-engineering,
# devops-docs, and audit agents legitimately mention these terms. When such
# framing co-occurs with a risky pattern the line is KEPT and flagged for review,
# never blindly deleted (quality preservation is the top priority).
# Strong meta-verbs only. Weak nouns ("example", "docs", "guide") were removed —
# they collide with payloads and domains like ``evil.example.com``. Legitimate
# quoted examples are handled by the separate quote path (_is_educational_quote).
_DESCRIPTIVE_RE = re.compile(
    r"\b(?:explains?|explained|explaining|describes?|described|teaches?|teaching|"
    r"reports? (?:whether|on|if)|detects?|detecting|defends?|defense|defensive|"
    r"awareness|tutorial|lesson|demonstrates?|audit(?:s|ing)?|reviews?|"
    r"how to (?:install|run|use|write|defend|detect|configure|set up)|"
    r"what (?:it|this|a|the)?\s*(?:does|is|means?)|why (?:you|it|this|piping|running|not))\b"
    r"|\b(?:attackers?|hackers?|adversar\w+|threat actors?|malicious (?:users?|actors?|input))\b"
    r".{0,50}\b(?:try|tries|attempt|attempts|may|might|could|would|will|can)\b"
    # list-header framing: "Today's words:", "Glossary:", "Key terms:" — an
    # enumeration of vocabulary, not a directive.
    r"|\b(?:words?|vocabulary|glossary|terms?|keywords?|lexicon)\b\s*[:：]"
    # Security-hygiene directives: a line telling the agent to PROTECT secrets —
    # rotate them, never expose them, report a found leak — reads as defensive,
    # not as an exfiltration instruction. Without this, "secrets must be rotatable
    # so a leak is recoverable" and "never expose credentials or leak data" were
    # redacted as attacks. These verbs only appear in defensive guidance.
    r"|\b(?:rotate|rotatable|rotation|recoverable|revoke|revocation|"
    r"do not expose|never expose|must not expose|not be exposed|"
    r"if you find|when you find|report (?:a|an|the|any)|flag (?:a|an|the|any))\b"
    r"|설명(?:합니다|하는|해)?|방어(?:합니다|하는|법)?|교육|점검(?:합니다|하는)?|감사(?:합니다|하는)?|튜토리얼|예문|단어\s*[:：]"
    # Korean security-hygiene directives: rotate / never expose / report a found leak.
    r"|회전|폐기|노출(?:하지|되지)\s*(?:마|않)|발견(?:하면|하거든|시)|보고(?:합니다|하세요|해)?",
    re.I,
)


def _is_negated(line: str, canon: str) -> bool:
    return bool(_NEGATION_RE.search(line)) or bool(_NEGATION_RE.search(canon))


def _is_educational_quote(line: str) -> bool:
    return bool(_QUOTED_RE.search(line)) and bool(_EDU_CONTEXT_RE.search(line))


def _is_descriptive(line: str) -> bool:
    return bool(_DESCRIPTIVE_RE.search(line))


# Prose directive families whose matches are DOWNGRADED to a kept+flagged finding
# when a precision guard fires (negation, quoted-for-teaching, or descriptive
# framing). Non-prose signals — invisible chars, exfil beacons, hard-coded
# secrets, private keys — are never downgraded.
_GUARDABLE = {
    "prompt-injection",
    "prompt-injection-ko",
    "prompt-injection-cjk",
    "prompt-injection-eu",
    "instruction-reset",
    "privilege-escalation",
    "secret-exfiltration",
    "secret-exfiltration-ko",
    "secret-access",
    "dangerous-command",
    "persistence",
    "encoded-execution",
}


def _guarded(line: str, canon: str, rule: str) -> bool:
    return rule in _GUARDABLE and (
        _is_negated(line, canon) or _is_educational_quote(line) or _is_descriptive(line)
    )


def _verdict(rule: str, message: str, action: str, severity: str, line: str, canon: str) -> Reason:
    if action == "redact" and _guarded(line, canon, rule):
        return Reason(
            rule,
            f"Flagged (kept) possible {rule}; context reads as advisory, quoted, or descriptive.",
            "flag",
            "advice",
        )
    return Reason(rule, message, action, severity)


def evaluate_line(line: str) -> Reason | None:
    """Return the highest-confidence verdict for a single line, or None."""
    canon = canonicalize(line)
    cjk = _cjk_shadow(line)

    for rule, pattern, message, action, severity in _ENGLISH_RULES:
        if pattern.search(canon) or pattern.search(line):
            return _verdict(rule, message, action, severity, line, canon)

    for rule, pattern, message, action, severity in _MULTILINGUAL_RULES:
        if pattern.search(cjk) or pattern.search(line):
            return _verdict(rule, message, action, severity, line, canon)

    sq = squish(line)
    for rule, pattern, message, action, severity in _SQUISH_RULES:
        if pattern.search(sq):
            return _verdict(rule, message, action, severity, line, canon)

    if _INVISIBLE_RE.search(line) or any(_TAG_LO <= ord(ch) <= _TAG_HI for ch in line):
        return Reason(
            "invisible-content",
            "Removed line containing hidden/invisible control characters before upload.",
            "redact",
            "high",
        )
    return None


def find_multiline_spans(lines: list[str]) -> list[SpanReason]:
    """Catch injections split across consecutive lines to evade per-line scans.

    Only high-confidence English/multilingual *injection* concepts are considered
    across a window, to keep collateral low. Returns minimal spans (>1 line)."""
    spans: list[SpanReason] = []
    n = len(lines)
    consumed = [False] * n
    combined_rules = [
        (r, p, m) for (r, p, m, a, s) in _ENGLISH_RULES if r in ("prompt-injection", "instruction-reset", "secret-exfiltration", "encoded-execution")
    ]
    combined_ml = [(r, p, m) for (r, p, m, a, s) in _MULTILINGUAL_RULES]

    for start in range(n):
        if not lines[start].strip():
            continue
        acc = lines[start].rstrip("\r\n")
        for end in range(start + 1, min(start + MAX_MULTILINE_WINDOW, n)):
            acc = acc + " " + lines[end].rstrip("\r\n")
            canon = canonicalize(acc)
            cjk = _cjk_shadow(acc)
            hit = None
            for rule, pattern, message in combined_rules:
                if pattern.search(canon):
                    hit = (rule, message)
                    break
            if hit is None:
                for rule, pattern, message in combined_ml:
                    if pattern.search(cjk):
                        hit = (rule, message)
                        break
            if hit is None:
                continue
            # only claim it if NO single line in the window already fires (true split)
            if any(evaluate_line(lines[k]) and evaluate_line(lines[k]).action == "redact" for k in range(start, end + 1)):
                break
            if all(not consumed[k] for k in range(start, end + 1)):
                rule, message = hit
                # A descriptive/quoted/negated window is kept and flagged, not
                # deleted — a split educational paragraph must survive intact.
                if _guarded(acc, canon, rule):
                    action, severity, msg = "flag", "advice", f"Flagged (kept) split {rule}; context reads as descriptive."
                else:
                    action, severity, msg = "redact", "high", f"{message} (split across lines)"
                spans.append(SpanReason(start, end, rule, msg, action, severity))
                for k in range(start, end + 1):
                    consumed[k] = True
            break
    return spans
