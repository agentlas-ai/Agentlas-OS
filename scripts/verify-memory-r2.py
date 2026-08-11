#!/usr/bin/env python3
"""R2 memory gate — judges the recall/lifespan contract against measured conditions.

Design and thresholds: docs/2026-08-11-memory-architecture-overhaul/R2-설계와-성공조건.md.
Every condition states a measured outcome, never a code shape, so a correct repair
that reaches the outcome differently still passes.

The corpus is synthetic and built at run time in a temp workspace: a fixture file
would be ignored by /.internal/ and the gate would then be unrunnable on a fresh
clone — a gate nobody can run is a gate that does not exist. Nothing here touches
the live One drawer.

Usage:
  scripts/verify-memory-r2.py            # judge; exit 0 only when every condition passes
  scripts/verify-memory-r2.py --self-test  # prove the gate fails on an injected defect
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agentlas_cloud import one_workspace as ow  # noqa: E402

CURRENT_PROJECT = "alpha-svc"

# Four topical clusters plus unrelated filler. Each work question below should be
# answered from exactly one cluster; that is what makes cross-question overlap a
# meaningful signal instead of an artifact of a thin corpus.
TOPICS: dict[str, tuple[str, list[tuple[str, str, str]]]] = {
    "release": (CURRENT_PROJECT, [
        ("procedure", "릴리스 태그를 푸시하기 전에 버전 마커 전수 대조를 돌린다. 마커가 뒤처지면 발행이 옛 버전을 광고한다.", "버전 범프 로그"),
        ("procedure", "릴리스 순서는 코어 발행이 먼저이고 앱 배포가 나중이다. 앱은 발행되지 않은 코어를 임베드할 수 없다.", "임베드 실패 재현"),
        ("procedure", "릴리스 태그 푸시만으로는 배포가 시작되지 않는다. 서명 빌드는 수동 디스패치로 시작한다.", "워크플로 트리거"),
        ("decision", "릴리스 자산 검증은 부분집합이 아니라 집합 동등성으로 판정한다.", "검증 계약"),
        ("decision", "안정 릴리스는 배포 피드를 원자적으로 함께 갱신한다.", "사전점검 거절"),
        ("risk", "릴리스 사전점검을 건너뛰는 우회 스위치는 금지한다. 과거 차단이 전부 옳았다.", "차단 이력"),
        ("fact", "서명 릴리스 빌드는 크로스플랫폼 잡과 원자 발행 잡을 포함한다.", "잡 목록"),
        ("fact", "릴리스 발행 대상은 소스 저장소가 아니라 별도 배포 저장소다.", "발행 기본 인자"),
    ]),
    "database": ("beta-app", [
        ("procedure", "마이그레이션 사다리에 단계를 끼워 넣을 때는 이미 지나간 단계 뒤에 넣어야 기존 설치가 깨지지 않는다.", "저장 실패 재현"),
        ("procedure", "마이그레이션 스키마 상한과 하한은 함께 옮긴다. 앱이 자기를 앞지르면 스스로 막는다.", "차단 산수"),
        ("procedure", "라이브 데이터베이스를 진단할 때는 읽기 전용으로 연다. 쓰기 연결은 고아 저널을 남긴다.", "손상 사고"),
        ("decision", "데이터베이스 손상 복구는 복구 명령으로 하고 손실 0을 먼저 확인한다.", "복구 기록"),
        ("decision", "가드형 컬럼 추가는 기존 데이터베이스에도 멱등하게 적용한다.", "백필 실측"),
        ("risk", "데이터베이스에 동시 읽기와 쓰기를 반복하면 손상된다.", "손상 재현"),
        ("fact", "데이터베이스 스키마 버전과 앱의 목표 버전은 핀 쌍으로 움직인다.", "핀 정의"),
        ("fact", "마이그레이션 영수증은 별도 렛저 파일에 남는다.", "렛저 경로"),
    ]),
    "auth": ("gamma-lib", [
        ("procedure", "인증 토큰 만료 처리는 재발급 실패 시의 사용자 안내까지 포함해야 한다.", "심사 반려"),
        ("procedure", "재인증 흐름은 두 번째 시도부터 식별자가 오지 않는 경우를 다룬다.", "재현 절차"),
        ("procedure", "인증 자격 증명은 값이 아니라 참조로만 저장한다.", "차단 지점"),
        ("decision", "인증 실패는 조용한 폴백 대신 명확한 거절로 보고한다.", "거절 계약"),
        ("decision", "인증 상태는 실행 파일 존재가 아니라 실제 왕복으로 판정한다.", "판정 함수"),
        ("risk", "신뢰 해시 게이트가 있는 런타임은 신설 훅을 승인 전까지 무시한다.", "훅 상태"),
        ("fact", "인증 세션은 호스트 홈 아래 별도 디렉터리에 보관된다.", "저장 경로"),
        ("fact", "공개 인증 엔드포인트는 표준 흐름을 그대로 노출한다.", "라우트 정의"),
    ]),
    "cache": (CURRENT_PROJECT, [
        ("procedure", "캐시 무효화는 관문 한 곳에서만 한다. 갈래마다 무효화하면 어긋난다.", "초크포인트"),
        ("procedure", "캐시 폴링 주기마다 무변경 쓰기를 하지 않는다. 변경이 없으면 생략한다.", "렉 실측"),
        ("procedure", "캐시 키는 한 곳에서 만든다. 구분자가 다르면 읽기가 영구 미스한다.", "키 불일치"),
        ("decision", "캐시 읽기는 우선하되 무효화 신호를 받으면 즉시 재검증한다.", "관문 설계"),
        ("decision", "전수 스캔 질의는 인덱스를 신설해 제거한다.", "인덱스 추가"),
        ("risk", "죽은 캐시 읽기는 로그도 실패도 남기지 않는다.", "미스 실측"),
        ("fact", "캐시 계층은 관문에서 최신성을 보장하고 갱신을 뒤로 미룬다.", "계층 설명"),
        ("fact", "인덱스 추가만으로 전수 스캔 질의가 사라졌다.", "질의 계획"),
    ]),
}

FILLER: list[tuple[str, str, str, str]] = [
    ("procedure", "문서만 바꾼 커밋은 지속적 통합을 발화시키지 않는다.", "트리거 조건", "delta-doc"),
    ("procedure", "공유 작업 트리에서는 스태시 대신 필요한 조각만 스테이징한다.", "스태시 사고", "delta-doc"),
    ("decision", "산출물은 사람이 보기 전에 기계가 먼저 판정한다.", "검증 계약", "delta-doc"),
    ("decision", "되돌릴 수 없는 동작은 승인 없이 실행하지 않는다.", "승인 규약", "epsilon-ops"),
    ("risk", "숨김 경로를 기본 제외하는 검색기는 점검을 거짓 안심시킨다.", "스캔 결과", "epsilon-ops"),
    ("risk", "고정 길이 창으로 잘라 검사하면 다음 줄까지 삼켜 오탐이 난다.", "게이트 오탐", "epsilon-ops"),
    ("fact", "산출물 목록은 빌더 설정에서 파생된다.", "설정 파일", "epsilon-ops"),
    ("procedure", "임시 파일은 전용 스크래치 경로에만 만든다.", "경로 규약", "zeta-tools"),
    ("decision", "기본값은 사람이 고를 수 있었을 때만 사람의 선택으로 존중한다.", "기본값 규칙", "zeta-tools"),
    ("risk", "목 객체가 실물과 어긋나면 게이트 전체가 조용히 무력해진다.", "목 드리프트", "zeta-tools"),
]

WORK_QUESTIONS = {
    "release": "릴리스 태그 푸시와 배포 순서 절차",
    "database": "데이터베이스 마이그레이션 손상 복구",
    "auth": "인증 토큰 만료와 재인증 처리",
    "cache": "캐시 무효화와 폴링 성능",
}
OFF_TOPIC_QUESTION = "오늘 점심은 뭐 먹을까"


def build_workspace(tmp: Path) -> Path:
    """Materialise a synthetic One drawer. Never reads or writes the live drawer."""
    root = tmp / "one"
    meta = root / ow.META_DIR
    meta.mkdir(parents=True, exist_ok=True)
    (root / "state.json").write_text(json.dumps({"enabled": True}), encoding="utf-8")
    lines = ["# Synthetic R2 corpus — generated per run, no live data", ""]

    def emit(kind: str, content: str, evidence: str, project: str) -> None:
        digest = hashlib.sha256(f"{kind}{content}".encode()).hexdigest()[:16]
        lines.extend([
            f"- **[{kind}]** {content}",
            f"  - 근거: {evidence}",
            f"  - Project: {project}",
            f"  - 티켓: `one-tkt-{digest}` · 2026-08-01T00:00:00Z  <!-- h:{digest} -->",
            "",
        ])

    for _topic, (project, rows) in TOPICS.items():
        for kind, content, evidence in rows:
            emit(kind, content, evidence, project)
    for kind, content, evidence, project in FILLER:
        emit(kind, content, evidence, project)
    (meta / ow.PROJECT_SOUL_FILE).write_text("\n".join(lines), encoding="utf-8")
    return root


class Report:
    def __init__(self) -> None:
        self.rows: list[tuple[str, bool, str]] = []

    def check(self, cid: str, ok: bool, detail: str) -> None:
        self.rows.append((cid, ok, detail))

    @property
    def failed(self) -> list[tuple[str, bool, str]]:
        return [r for r in self.rows if not r[1]]

    def emit(self) -> int:
        for cid, ok, detail in self.rows:
            print(f"{'PASS' if ok else 'FAIL'}  {cid}  {detail}")
        total, bad = len(self.rows), len(self.failed)
        print(f"\n{'FAIL' if bad else 'PASS'}: R2 memory contract — {total - bad}/{total} conditions")
        return 1 if bad else 0


def jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b) if (a | b) else 0.0


def kind_of(line: str) -> str:
    return line.split("[", 1)[1].split("]", 1)[0].split(" ", 1)[0] if "[" in line else ""


def judge_recall(root: Path, report: Report) -> None:
    """C1 recall ranking + C6 fact slot — the outcomes, not the implementation."""
    recall = lambda q: ow.select_one_recall(q, workspace=CURRENT_PROJECT, root=root)  # noqa: E731

    work = {topic: set(recall(q)) for topic, q in WORK_QUESTIONS.items()}
    off = set(recall(OFF_TOPIC_QUESTION))
    empty = set(recall(""))

    worst = max((jaccard(sel, off), topic) for topic, sel in work.items())
    report.check(
        "C1.1", worst[0] <= 0.20,
        f"off-topic vs work overlap {worst[0]:.2f} (worst: {worst[1]}) — need <= 0.20 (baseline 0.67)",
    )

    exclusives = {}
    for topic, sel in work.items():
        others: set[str] = set()
        for other, sel2 in work.items():
            if other != topic:
                others |= sel2
        exclusives[topic] = len(sel - others - off)
    weakest = min(exclusives.items(), key=lambda kv: kv[1])
    report.check(
        "C1.2", weakest[1] >= 4,
        f"question-exclusive lines >= 4 for every work question; weakest {weakest[0]}={weakest[1]} "
        f"(all: {exclusives}) (baseline 1)",
    )

    report.check(
        "C1.3", len(off) <= 2,
        f"off-topic recall {len(off)} lines — need <= 2 (baseline 5)",
    )

    universe: set[str] = set()
    for sel in work.values():
        universe |= sel
    universe |= off
    report.check(
        "C1.4", len(universe) >= 20,
        f"distinct blocks reached across 5 questions = {len(universe)} — need >= 20 (baseline 10)",
    )

    start = time.perf_counter()
    for _ in range(5):
        recall(WORK_QUESTIONS["release"])
    elapsed = (time.perf_counter() - start) * 1000 / 5
    report.check("C1.5", elapsed <= 50.0, f"recall latency {elapsed:.1f}ms — need <= 50ms")

    twice = [recall(WORK_QUESTIONS["auth"]) for _ in range(2)]
    report.check("C1.6", twice[0] == twice[1], "same input returns identical output (determinism)")

    report.check(
        "C1.7", len(empty) == int(ow._rule("recallBudgets.one.l1MaxBlocks", 6)),
        f"session start (no question) fills the project-latest budget: {len(empty)} lines",
    )

    max_chars = int(ow._rule("recallBudgets.one.l1MaxChars", 1200))
    longest = max((sum(len(x) for x in sel), topic) for topic, sel in work.items())
    report.check(
        "C1.8", longest[0] <= max_chars,
        f"recall text {longest[0]} chars (worst: {longest[1]}) — need <= ruleset l1MaxChars {max_chars}",
    )

    facts_in_work = {t: sum(1 for line in sel if kind_of(line) == "fact") for t, sel in work.items()}
    report.check(
        "C6.1", all(v >= 1 for v in facts_in_work.values()),
        f"a relevant fact reaches every work question: {facts_in_work} (baseline 0)",
    )
    report.check(
        "C6.2", sum(1 for line in off if kind_of(line) == "fact") == 0,
        "no fact leaks into an off-topic recall",
    )
    l1_kinds = set(ow._rule("recallBudgets.one.l1Kinds", ["procedure", "decision", "risk"]))
    non_fact = {t: sum(1 for line in sel if kind_of(line) in l1_kinds) for t, sel in work.items()}
    report.check(
        "C6.3", all(v >= 4 for v in non_fact.values()),
        f"the fact slot does not starve the L1 budget: {non_fact} (need >= 4 each)",
    )


def judge_capsule_budget(report: Report) -> None:
    """C3 — layer budgets must not be able to oversubscribe the capsule cap."""
    try:
        from agentlas_cloud import memory_hook as mh
    except Exception as exc:  # pragma: no cover - import failure is a real failure
        report.check("C3.1", False, f"memory_hook import failed: {exc}")
        return
    cap = getattr(mh, "MAX_CAPSULE_CHARS", None)
    budgets = getattr(mh, "LAYER_BUDGETS", None)
    trim = getattr(mh, "_trim_layer", None)
    if cap is None or budgets is None:
        report.check(
            "C3.1", False,
            "no declared per-layer budget (layers must declare shares that fit) — "
            "layers currently sum to ~10250 against a 6000 cap",
        )
        return
    overhead = int(getattr(mh, "CAPSULE_FIXED_OVERHEAD_CHARS", 0))
    total = sum(int(v) for v in dict(budgets).values())
    report.check(
        "C3.1", total + overhead <= int(cap),
        f"declared layer budgets sum to {total} (+{overhead} fixed) against cap {cap}",
    )
    if not callable(trim):
        report.check("C3.2", False, "no per-layer trim — a layer cannot protect its best line")
        return
    ranked = ["A" * 100, "B" * 100, "C" * 100]
    kept = trim(ranked, 150)
    report.check(
        "C3.2", kept == ranked[:1],
        f"an overflowing layer drops its lowest-ranked lines and keeps rank 1 (kept {len(kept)})",
    )


def judge_conflict_tickets(tmp: Path, report: Report) -> None:
    """C4 — a missing learning capsule must be a receipt field, not a ticket.

    Judged by running a real stop over a synthetic workspace: a source scan would
    only prove the string moved, not that the behaviour did.
    """
    root = tmp / "gap-one"
    (root / ow.META_DIR).mkdir(parents=True, exist_ok=True)
    (root / "state.json").write_text(json.dumps({"enabled": True}), encoding="utf-8")
    workspace = tmp / "gap-project"
    workspace.mkdir(parents=True, exist_ok=True)

    receipt = ow.record_session_receipt(
        root, substantial=True, capsule_written=False, workspace=str(workspace),
        detail="host=test tool_uses=40 edits=9 harvested=0",
    )
    tickets = root / ow.META_DIR / ow.MEMORY_TICKETS_FILE
    rows = []
    if tickets.exists():
        rows = [json.loads(line) for line in tickets.read_text(encoding="utf-8").splitlines() if line.strip()]
    conflicts = [r for r in rows if (r.get("candidate") or {}).get("type") == "conflict"]
    report.check(
        "C4.1", not conflicts,
        f"a session gap creates no curator ticket ({len(conflicts)} conflict tickets after a gap stop)",
    )
    report.check(
        "C4.2", bool(receipt.get("gap")),
        "the gap stays visible on the session receipt (no information lost by dropping the ticket)",
    )


def judge_promotion(tmp: Path, report: Report) -> None:
    """C5 — a chip candidate must be decidable by a person, and countable after."""
    root = tmp / "chip-one"
    meta = root / ow.META_DIR
    meta.mkdir(parents=True, exist_ok=True)
    (root / "state.json").write_text(json.dumps({"enabled": True}), encoding="utf-8")
    ow._experience_schema(meta / ow.EXPERIENCE_DB_FILE)

    chip = ow._make_experience_chip(
        meta / ow.EXPERIENCE_DB_FILE,
        {"content": "릴리스 전에 버전 마커를 전수 대조한다", "scope": "agent_repo",
         "evidence": ["verify-memory-r2"]},
        "one-tkt-fixture",
    )
    if not chip:
        report.check("C5.1", False, "could not create a chip candidate to decide on")
        report.check("C5.2", False, "could not create a chip candidate to decide on")
        report.check("C5.3", False, "no chip to count")
        report.check("C5.4", False, "no chip store")
        return

    promoted = ow.promote_chip(root, chip, "gate")
    after = ow.status(root)
    report.check(
        "C5.1", bool(promoted.get("ok")) and after.get("promotedChips") == 1,
        f"a person can promote a candidate: {promoted.get('to')} (promoted count {after.get('promotedChips')})",
    )

    chip2 = ow._make_experience_chip(
        meta / ow.EXPERIENCE_DB_FILE,
        {"content": "캐시 무효화는 관문 한 곳에서만 한다", "scope": "agent_repo", "evidence": ["gate"]},
        "one-tkt-fixture-2",
    )
    rejected = ow.reject_chip(root, chip2 or "", "gate")
    report.check(
        "C5.2", bool(rejected.get("ok")) and rejected.get("to") == "rejected",
        f"a person can reject a candidate: {rejected.get('to')}",
    )

    report.check(
        "C5.3", ow.status(root).get("promotedChips", -1) >= 0,
        f"status() counts promoted chips (promotion is observable): {ow.status(root).get('promotedChips')}",
    )

    missing = ow.promote_chip(root, "one-chip-does-not-exist", "gate")
    report.check(
        "C5.4", not missing.get("ok"),
        f"promoting a chip that does not exist fails loudly: {missing.get('error')}",
    )


def judge_recall_observability(root: Path, report: Report) -> None:
    """C7 — recall must leave a trace, or ranking work cannot be evaluated."""
    detailed = getattr(ow, "select_one_recall_detailed", None)
    record = getattr(ow, "record_recall_receipt", None)
    coverage = getattr(ow, "recall_coverage", None)
    if not (callable(detailed) and callable(record) and callable(coverage)):
        report.check("C7.1", False, "no recall receipt path (detailed recall + record)")
        report.check("C7.2", False, "no recall coverage report")
        return

    before = coverage(root)
    lines, hashes = detailed(WORK_QUESTIONS["release"], workspace=CURRENT_PROJECT, root=root)
    record(root, hashes)
    after = coverage(root)
    report.check(
        "C7.1", len(hashes) == len(lines) and after["everRecalled"] >= len(lines) > 0,
        f"a recall is recorded block-by-block: {before['everRecalled']} -> {after['everRecalled']} "
        f"of {after['durable']} durable",
    )
    report.check(
        "C7.2", 0.0 < after["reachedPct"] <= 100.0 and after["neverRecalled"] == after["durable"] - after["everRecalled"],
        f"coverage reports the never-recalled share: {after['neverRecalled']} never, "
        f"{after['reachedPct']}% reached",
    )


RULESET_META_KEYS = {
    "schemaVersion", "rulesetVersion", "updatedAt", "description", "rationale", "sourceRef", "note",
}


def judge_ruleset_consumption(report: Report) -> None:
    """C2.3 — a value declared in the ruleset that no executor reads is not a rule.

    Measured 2026-08-11: eleven such keys existed, including the one that told
    both surfaces to fall back to `session` while both actually answered
    `team_memory`. A declaration nobody reads drifts silently and reads as policy.
    """
    import subprocess

    path = ROOT / "system-agents" / "curator-ruleset.json"
    if not path.is_file():
        report.check("C2.3", False, f"canonical ruleset missing: {path}")
        return
    ruleset = json.loads(path.read_text(encoding="utf-8"))
    leaves: set[tuple[str, str]] = set()

    def walk(node: dict, trail: list[str]) -> None:
        for key, value in node.items():
            if key in RULESET_META_KEYS:
                continue
            if isinstance(value, dict):
                walk(value, trail + [key])
            else:
                leaves.add((".".join(trail + [key]), key))

    walk(ruleset, [])
    # The Desktop surface sits beside this repo in a normal checkout and beside
    # the worktree when one is in use; an explicit path wins over both. A rule
    # consumed only by Desktop must not read as dead just because this gate ran
    # from a layout that could not see Desktop.
    desktop_roots = []
    override = os.environ.get("AGENTLAS_DESKTOP_CHECKOUT", "").strip()
    if override:
        desktop_roots.append(Path(override).expanduser())
    desktop_roots += [
        ROOT.parent / "agentlas_desktop",
        ROOT.parent.parent / "agentlas_desktop",
        ROOT.parent / "r2-desktop",
    ]
    surfaces = [
        (["--include=*.py"], ROOT / "agentlas_cloud"),
        ([], ROOT / "bin" / "agentlas-one"),
    ]
    surfaces += [
        (["--include=*.ts", "--include=*.mjs", "--include=*.cjs"], root / "electron")
        for root in desktop_roots
    ]
    if not any(target.exists() for _flags, target in surfaces[2:]):
        report.check("C2.3", False, "no Desktop surface found — cannot judge Desktop-owned rules")
        return

    def consumed(key: str) -> bool:
        for flags, target in surfaces:
            if not target.exists():
                continue
            if subprocess.run(["grep", "-rq", *flags, key, str(target)],
                              capture_output=True).returncode == 0:
                return True
        return False

    dead = sorted(full for full, key in leaves if not consumed(key))
    report.check(
        "C2.3", not dead,
        f"every ruleset value has a reader ({len(leaves)} rules, {len(dead)} unread"
        + (f": {', '.join(dead[:4])}" if dead else "") + ")",
    )


def judge_merge(tmp: Path, report: Report) -> None:
    """C8 — near-duplicate merge, and above all no false merge.

    Measured 2026-08-11: nothing in the live drawer would merge today (no pair
    above 0.4 token overlap). This exists so the rule is one shared rule instead
    of three implementations, and so a repeat is caught when it does arrive.
    """
    original = "릴리스 태그를 푸시하기 전에 버전 마커 전수 대조를 돌린다. 마커가 뒤처지면 발행이 옛 버전을 광고한다."
    soul = tmp / "merge-soul.md"
    digest = hashlib.sha256(original.encode()).hexdigest()[:16]
    soul.write_text(
        f"- **[procedure]** {original}\n  - 근거: gate\n  - Project: alpha-svc\n"
        f"  - 티켓: `one-tkt-{digest}`  <!-- h:{digest} -->\n",
        encoding="utf-8",
    )
    prefix = int(ow._rule("limits.serverMergeSimilarityPrefixChars", 40))
    heads = ow._durable_prefixes(soul, prefix)
    durable = ow._durable_hashes(soul)

    # Reword only past the prefix window: changing the opening would break the
    # precondition instead of testing the rule.
    restated = original.replace("광고한다", "광고하게 된다")
    action, _reason = ow._classify(
        {"content": restated, "type": "procedure", "evidence": ["gate"]}, durable, heads)
    report.check("C8.1", action == "merge", f"a restatement of a durable block merges (got {action})")

    diverging = original[:prefix] + " 그러나 이 항목은 캐시 무효화 관문과 폴링 주기 설계에 대한 완전히 다른 결론이다."
    action2, _r2 = ow._classify(
        {"content": diverging, "type": "procedure", "evidence": ["gate"]}, durable, heads)
    report.check(
        "C8.2", action2 != "merge",
        f"a different learning that merely opens alike is not merged (got {action2})",
    )


def judge_semantic_index(root: Path, report: Report) -> None:
    """C10 — the One drawer must use the same search engine as every other layer.

    Project, borrowed-agent and Desktop memory are all served by OntologyRuntime,
    which is what the published LoCoMo/LongMemEval retrieval numbers measured.
    The One drawer was the only layer outside it. These conditions judge the
    outcome — an index exists, recall consults it, and doing so does not make
    session start slow — not the particular way it is wired.
    """
    indexer = getattr(ow, "index_durable_blocks", None)
    if not callable(indexer):
        report.check("C10.1", False, "no durable indexing path — One stays lexical-only")
        report.check("C10.2", False, "no semantic candidates")
        report.check("C10.3", False, "not measurable")
        return

    result = indexer(root)
    indexed = int(result.get("indexed", 0))
    report.check(
        "C10.1", indexed > 0,
        f"durable blocks are projected into the shared index ({indexed} indexed, "
        f"skip reason: {result.get('skipped', '-')})",
    )

    scores = ow._semantic_candidates(root, WORK_QUESTIONS["database"], 24)
    report.check(
        "C10.2", len(scores) > 0,
        f"recall consults the semantic index ({len(scores)} candidates returned)",
    )

    # Warm the process the way a real session does, then measure steady state:
    # constructing the runtime per call cost 490ms and reusing it costs ~21ms.
    ow.select_one_recall(WORK_QUESTIONS["release"], workspace=CURRENT_PROJECT, root=root)
    start = time.perf_counter()
    for question in WORK_QUESTIONS.values():
        ow.select_one_recall(question, workspace=CURRENT_PROJECT, root=root)
    elapsed = (time.perf_counter() - start) * 1000 / len(WORK_QUESTIONS)
    report.check(
        "C10.3", elapsed <= 50.0,
        f"semantic recall stays within the latency budget: {elapsed:.0f}ms per query",
    )

    # Fail-open: a host without the engine must still get lexical recall rather
    # than an empty capsule.
    empty = Path(tempfile.mkdtemp(prefix="agentlas-r2-noidx-"))
    try:
        bare = build_workspace(empty)
        lines = ow.select_one_recall(WORK_QUESTIONS["auth"], workspace=CURRENT_PROJECT, root=bare)
        report.check(
            "C10.4", len(lines) > 0,
            f"a drawer with no index still recalls lexically ({len(lines)} lines)",
        )
    finally:
        shutil.rmtree(empty, ignore_errors=True)


def main(argv: list[str]) -> int:
    self_test = "--self-test" in argv
    report = Report()
    tmp = Path(tempfile.mkdtemp(prefix="agentlas-r2-"))
    try:
        root = build_workspace(tmp)
        if self_test:
            # Inject a defect the contract must catch: strip every topical block so
            # recall can only return project-latest noise.
            soul = root / ow.META_DIR / ow.PROJECT_SOUL_FILE
            text = soul.read_text(encoding="utf-8")
            soul.write_text(text.replace("릴리스", "").replace("인증", ""), encoding="utf-8")
        judge_recall(root, report)
        judge_capsule_budget(report)
        judge_conflict_tickets(tmp, report)
        judge_promotion(tmp, report)
        judge_recall_observability(root, report)
        judge_ruleset_consumption(report)
        judge_merge(tmp, report)
        judge_semantic_index(root, report)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    code = report.emit()
    if self_test:
        print("\nself-test: a gate that cannot fail is not a gate")
        return 0 if code != 0 else 1
    return code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
