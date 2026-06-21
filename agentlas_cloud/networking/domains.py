"""Domain taxonomy for routing.

Single source of truth for the agent-domain vocabulary, shared by:
  - card generation/backfill (populates each routing card's ``domains``),
  - the router's domain-coherence signal (``_score_card``),
  - the Agent Ontology graph (``Domain`` nodes + ``in_domain`` edges).

Motivation: the lexical scorer matches shared tokens, so polysemous words route
across unrelated domains — a game "에셋"(art asset) request collided with a
financial "자산/운용"(asset management) team. Domains give routing a coarse
semantic frame that token overlap cannot.

Markers are matched as **case-insensitive substrings** on raw text (no
tokenizer dependency), so Korean compounds work without a morphological
analyzer. Markers are deliberately high-precision; Korean markers are preferred
(queries are Korean-first) and English markers are >=4 chars or phrases to avoid
substring collisions (e.g. bare "api" hides inside "therapist").
"""

from __future__ import annotations

import re

# domain id -> high-precision substring markers (lowercased at match time)
DOMAIN_MARKERS: dict[str, tuple[str, ...]] = {
    "finance": (
        # Bare "주식" is dropped: it is a substring of "주식회사" (Inc./Co.) and
        # would tag every corporation mention as finance. Phrase forms keep
        # stock-trading recall without that collision.
        "증권", "종목", "포트폴리오", "리밸런싱", "주식 거래", "주식 매수", "주식 투자",
        "주식 종목", "주식시장", "펀드", "투자", "매매", "운용사", "자산운용", "자산관리",
        "자산 관리", "시세", "트레이딩", "배당", "선물옵션", "환율", "재무제표",
        "portfolio", "rebalanc", "brokerage", "equities", "stock market", "investor",
        "investment", "hedge fund", "dividend", "valuation", "asset management",
    ),
    "game": (
        "게임", "스프라이트", "타일셋", "픽셀아트", "도트", "게임아트", "레벨디자인",
        "유니티", "언리얼", "로그라이크", "퀘스트", "sprite", "tileset", "gameplay",
        "gamedev", "roguelike", "game asset", "game studio", "unreal engine",
        "level design",
    ),
    "legal": (
        "소송", "준비서면", "변론", "법원", "판결", "약관", "계약서", "특허", "상표",
        "법률", "litigation", "lawsuit", "legal brief", "contract review", "patent",
        "trademark", "compliance",
    ),
    "software": (
        "코딩", "코드리뷰", "백엔드", "프론트엔드", "리팩터", "리팩토링", "디버깅",
        "라이브러리", "알고리즘", "컴파일", "refactor", "backend", "frontend",
        "code review", "debugging", "compiler", "algorithm",
    ),
    "devops": (
        "데브옵스", "배포파이프라인", "쿠버네티스", "도커", "인프라", "terraform",
        "kubernetes", "docker", "devops", "ci/cd", "infrastructure",
    ),
    "mobile": (
        "안드로이드", "아이폰", "플러터", "스위프트", "코틀린", "앱스토어", "플레이스토어",
        "android", "iphone", "flutter", "swift", "kotlin", "app store", "play store",
    ),
    "data": (
        "데이터분석", "스프레드시트", "엑셀", "대시보드", "데이터셋", "통계분석",
        "spreadsheet", "dashboard", "analytics", "dataset", "data analysis",
    ),
    "design": (
        "로고", "브랜딩", "포스터", "배너", "썸네일", "명함", "인포그래픽", "피그마",
        "캔바", "목업", "logo", "branding", "poster", "banner", "thumbnail", "figma",
        "canva", "infographic", "mockup",
    ),
    "marketing": (
        "마케팅", "광고", "캠페인", "카피라이팅", "퍼널", "그로스", "소셜", "소셜미디어",
        "campaign", "advertis", "copywrit", "growth hack", "marketing funnel",
    ),
    "ecommerce": (
        "이커머스", "쇼핑몰", "상세페이지", "스마트스토어", "쿠팡", "상품등록", "재고관리",
        "shopify", "ecommerce", "product page", "online store",
    ),
    "research": (
        "리서치", "논문", "시장조사", "경쟁분석", "인텔리전스", "research",
        "literature review", "market research", "competitive analysis",
    ),
    "security": (
        "보안취약", "취약점", "침투테스트", "펜테스트", "익스플로잇", "레드팀",
        "vulnerability", "penetration test", "pentest", "exploit",
    ),
    "writing": (
        "글쓰기", "블로그", "에세이", "소설", "번역", "교정", "윤문", "blog post",
        "essay", "translation", "proofread", "ghostwrit",
    ),
    "media": (
        "이미지생성", "영상편집", "일러스트", "동영상", "사진보정", "image generation",
        "video editing", "illustration",
    ),
    "beauty": (
        "메이크업", "화장품", "피부", "헤어", "웨딩", "퍼스널컬러", "네일", "뷰티",
        "스타일링", "makeup", "skincare", "wedding", "bridal", "cosmetic",
        "personal color",
    ),
    "health": (
        "운동루틴", "다이어트", "식단", "영양", "피트니스", "헬스장", "workout",
        "fitness", "nutrition", "meal plan",
    ),
    "business": (
        "사업계획", "창업", "비즈니스모델", "피치덱", "투자유치", "startup",
        "business model", "pitch deck", "go to market",
    ),
    "sales": (
        # Bare "영업" is dropped: it is a substring of 영업비밀(trade secret),
        # 영업이익(operating profit), 영업시간(business hours). Phrase forms only.
        "세일즈", "영업 전략", "영업 파이프라인", "영업 활동", "신규 영업", "콜드메일",
        "제안서", "리드생성", "cold email", "sales pipeline", "lead generation",
    ),
    "support": (
        "고객지원", "고객문의", "헬프데스크", "customer support", "helpdesk",
        "ticket triage",
    ),
    "productivity": (
        "회의록", "일정관리", "노션", "meeting notes", "scheduling", "notion",
    ),
}

# The canonical set of domain ids (for schema/lint validation).
DOMAIN_IDS: frozenset[str] = frozenset(DOMAIN_MARKERS)


def _ascii_pattern(marker: str) -> "re.Pattern[str] | None":
    """A boundary-anchored matcher for a pure-ASCII marker so it can never fire
    inside a larger word ('valuation' must not match 'evaluation', 'canva' must
    not match 'canvas', 'notion' must not match 'notional'). Korean markers have
    no whitespace word boundaries, so they stay plain substrings and are kept
    high-precision by phrasing instead. The ASCII-only look-arounds still let a
    marker match when it is glued directly to Korean text (no ASCII boundary)."""
    if all(ord(ch) < 128 for ch in marker):
        return re.compile(r"(?<![a-z0-9])" + re.escape(marker) + r"(?![a-z0-9])")
    return None


def _build_matchers() -> dict[str, tuple[tuple[str | None, "re.Pattern[str] | None"], ...]]:
    out: dict[str, tuple[tuple[str | None, "re.Pattern[str] | None"], ...]] = {}
    for domain, markers in DOMAIN_MARKERS.items():
        pairs: list[tuple[str | None, "re.Pattern[str] | None"]] = []
        for marker in markers:
            pattern = _ascii_pattern(marker)
            pairs.append((None, pattern) if pattern is not None else (marker, None))
        out[domain] = tuple(pairs)
    return out


# Precompiled per-domain matchers: each is (substring, None) for Korean markers
# or (None, boundary_regex) for ASCII markers.
_DOMAIN_MATCHERS = _build_matchers()


def classify_domains(*texts: str) -> list[str]:
    """Return the sorted domains whose markers appear in the given text(s).

    Korean markers match as case-insensitive substrings; ASCII markers match
    only at word boundaries (so they cannot hide inside a larger English word).
    Empty result means "no confident domain" — callers must treat that as
    *unknown*, never as a mismatch, so the routing guard stays purely additive.
    """
    blob = " ".join(t for t in texts if t).lower()
    if not blob:
        return []
    hits: set[str] = set()
    for domain, matchers in _DOMAIN_MATCHERS.items():
        for substring, pattern in matchers:
            if (substring is not None and substring in blob) or (pattern is not None and pattern.search(blob)):
                hits.add(domain)
                break
    return sorted(hits)


def is_valid_domain(domain: str) -> bool:
    return domain in DOMAIN_IDS
