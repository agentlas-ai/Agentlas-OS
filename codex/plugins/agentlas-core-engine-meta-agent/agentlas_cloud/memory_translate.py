"""English-only memory migration — translate once, translate on write (2026-09-23).

Owner decision (plan §9-8 + "전면 영어 마이그레이션"): every machine that takes
this update converts its accumulated non-English memory to English once, and
anything written later in another language is translated on the way in. The
English text is the SEARCH SURFACE; the original wording stays the authority
(`  - Native:` line in the soul, never overwritten, never deleted).

Shape (same as the semantic index backfill, a6c2cbb7):
  * hooks only DECIDE (a few stats) and spawn a detached worker;
  * the worker is budgeted (daily cap, per-run cap), resumable (the soul itself
    is the queue — a translated block carries its original as `Native:`, so a
    killed run is recovered by matching, not by a journal), and fail-open;
  * no new installs: the translator is whatever the machine already has —
    a host-supplied runtime, a local model that is ALREADY resident, or the
    user's signed-in CLI called headless with the cheapest model and no tools.
    With none of them, nothing changes and recall keeps working through the
    dual query (english_recall_query) — no regression.

Safety (research 2026-09-23 §5): only non-English blocks; secrets never leave
the machine to a model; every ASCII token (identifier, path, number, code span)
must survive; a multilingual-embedding back-check guards meaning; a per-drawer
glossary keeps one Korean term on one English term; every decision is logged.

Stdlib only; the ontology package is imported lazily (fail-open).
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any, Callable, Iterable

from . import one_workspace as ow

TRANSLATE_WORKER_ENV = "AGENTLAS_TRANSLATE_WORKER"
TRANSLATE_RUNTIME_ENV = "AGENTLAS_TRANSLATE_RUNTIME"
TRANSLATE_SWITCH_ENV = "AGENTLAS_TRANSLATE"  # "off" disables every spawn and run

MIGRATION_ID = "english-memory-backfill.v1"
PROJECT_MIGRATION_ID = "project-english-surface.v1"
STATE_FILE = "translation-state.json"
LEDGER_FILE = "translation-ledger.jsonl"
GLOSSARY_FILE = "translation-glossary.json"
MAP_FILE = "translation-map.json"
QUEUE_FILE = "translation-queue.json"
WORKER_LOCK_FILE = ".translation-worker.lock"
PROJECT_EN_SNAPSHOT_DIR = "ontology-project-docs-en"

# Every value is overridable from the curator ruleset under `translation.*`
# (read through one_workspace._rule, so a missing key is simply the default).
DEFAULTS: dict[str, Any] = {
    "enabled": True,
    "nonEnglishRatio": 0.6,       # _latin_ratio below this = needs English
    "englishMinRatio": 0.8,       # a translation must itself read as English
    "dailyCap": 200,              # blocks sent to a model per drawer per day
    "runCap": 100,                # blocks per detached run
    "batchSize": 20,
    "callTimeoutSeconds": 240,
    "minIntervalSeconds": 1800,   # between spawns
    "noTranslatorBackoffSeconds": 6 * 3600,
    "backcheckFloor": 0.25,       # cos(native, english); same-meaning 0.420, unrelated 0.135
    "requireBackcheck": True,
    "maxAttempts": 2,             # safety-rejected blocks get one retry, then stay native
    "glossaryInject": 40,
    "claudeModel": "haiku",
    "codexModel": "",             # empty = codex rung off (no known cheapest model)
    "ollamaResidentOnly": True,   # never load a model in the background
    "projectDailyCap": 60,        # chunks per project per day
    "projectBatchSize": 8,
    "projectRefreshSeconds": 6 * 3600,
}

_SYSTEM_PROMPT = (
    "You translate short engineering memory notes into English for a search index. "
    "Rules: (1) translate the meaning faithfully and concisely; do not add, explain, or omit. "
    "(2) Copy EVERY identifier, file name, path, number, version, hash, command, URL, code span and "
    "any other ASCII token EXACTLY as written — same spelling, same case. Numbers stay digits: "
    "write 0 as 0 and 4 as 4, never as words (not 'zero', not 'four'). "
    "(3) A proper noun with no established English name: romanize it and keep the original in parentheses. "
    "(4) Use the glossary's fixed translations whenever a glossary term appears. "
    "(5) Output ONLY one JSON object, no prose, no code fence: "
    '{"items":[{"h":"<same h>","en":"<English>","terms":[["<source term>","<English term>"]]}]} '
    "with at most 5 domain terms per item (nouns worth keeping consistent)."
)

_JSON_OBJECT_RE = re.compile(r"\{[\s\S]*\}")
_ASCII_TOKEN_RE = re.compile(r"[A-Za-z0-9_$][A-Za-z0-9_$./:@#%+=-]*")
_CODE_SPAN_RE = re.compile(r"`([^`\n]+)`")


# --------------------------------------------------------------------- config

def config() -> dict[str, Any]:
    cfg = dict(DEFAULTS)
    try:
        override = ow._rule("translation", {})
        if isinstance(override, dict):
            cfg.update(override)
    except Exception:  # noqa: BLE001 — a broken ruleset keeps the defaults
        pass
    return cfg


def switched_off(cfg: dict[str, Any] | None = None) -> bool:
    if os.environ.get(TRANSLATE_SWITCH_ENV, "").strip().lower() in ("off", "0", "false", "no"):
        return True
    return not bool((cfg or config()).get("enabled", True))


def in_translate_worker() -> bool:
    """True inside a translator child (and inside its own hooks) — the memory
    pipeline must not run there, or a translation session would mint memory
    that asks for more translation."""
    return bool(os.environ.get(TRANSLATE_WORKER_ENV))


def _today() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")


def needs_english(text: str, cfg: dict[str, Any] | None = None) -> bool:
    ratio = float((cfg or DEFAULTS).get("nonEnglishRatio", 0.6))
    return bool(text and text.strip()) and ow._latin_ratio(text) < ratio


# ----------------------------------------------------------------- translators

class Translator:
    """A text generator `(system, prompt, timeout) -> str` with a name for receipts."""

    def __init__(self, name: str, generate: Callable[[str, str, float], str]):
        self.name = name
        self._generate = generate

    def generate(self, system: str, prompt: str, timeout: float) -> str:
        return self._generate(system, prompt, timeout) or ""


def _child_env() -> dict[str, str]:
    env = os.environ.copy()
    env[TRANSLATE_WORKER_ENV] = "1"
    return env


def _env_translator(env: dict[str, str]) -> Translator | None:
    """Rung 0 — a runtime the host handed us (same JSON schema as the judge)."""
    for key in (TRANSLATE_RUNTIME_ENV, "AGENTLAS_JUDGE_RUNTIME"):
        raw = (env.get(key) or "").strip()
        if not raw:
            continue
        try:
            spec = json.loads(raw)
            from .judgment_bootstrap import _build_runner  # noqa: PLC0415

            runner = _build_runner(spec) if isinstance(spec, dict) else None
        except Exception:  # noqa: BLE001
            runner = None
        if runner is None:
            continue
        kind = str(spec.get("kind") or "env")

        def generate(system: str, prompt: str, timeout: float, _run=runner) -> str:
            return _run(system, prompt, timeout_s=timeout)

        return Translator(f"env:{kind}", generate)
    return None


def _ollama_resident_translator(endpoint: str = "http://127.0.0.1:11434") -> Translator | None:
    """Rung 1 — a local model, but only one that is ALREADY loaded (`/api/ps`).

    Loading an 18 GB model from a background worker on a laptop that is already
    short of memory is worse than not translating today."""
    try:
        with urllib.request.urlopen(endpoint + "/api/ps", timeout=0.5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:  # noqa: BLE001
        return None
    names = [str(m.get("name") or m.get("model") or "") for m in (data.get("models") or []) if isinstance(m, dict)]
    names = [n for n in names if n and "embed" not in n.lower()]
    if not names:
        return None
    model = names[0]

    def generate(system: str, prompt: str, timeout: float) -> str:
        body = json.dumps({
            "model": model, "stream": False, "think": False, "format": "json",
            "options": {"temperature": 0},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        }).encode("utf-8")
        req = urllib.request.Request(endpoint + "/api/chat", data=body, headers={"content-type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            out = json.loads(resp.read().decode("utf-8"))
        return str((out.get("message") or {}).get("content") or "")

    return Translator(f"ollama:{model}", generate)


def _scratch_dir() -> str:
    # A scratch cwd so the CLI never reads a project's CLAUDE.md/AGENTS.md and
    # never writes session files into someone's checkout.
    return tempfile.mkdtemp(prefix="agentlas-translate-")


def _claude_translator(cfg: dict[str, Any]) -> Translator | None:
    """Rung 2 — the signed-in Claude CLI, headless, cheapest model, zero tools.

    `--bare` would skip hooks too but it cannot read OAuth, so hooks are turned
    off through `--settings` and user/project settings are not loaded at all.
    `language` is forced because a user's CLI language setting beats any system
    prompt (measured 2026-09-14)."""
    exe = shutil.which("claude")
    if not exe:
        return None
    model = str(cfg.get("claudeModel") or "haiku")
    # Thinking OFF: measured 2026-09-23, haiku spent 12,080 thinking tokens on
    # a 5-item batch (116 s, $0.066) versus 0 thinking / 10 s / $0.006 with it
    # off — same five parseable translations. `--effort low` did not stop it.
    settings = json.dumps({"language": "English", "disableAllHooks": True, "alwaysThinkingEnabled": False})

    def generate(system: str, prompt: str, timeout: float) -> str:
        cwd = _scratch_dir()
        try:
            proc = subprocess.run(
                [exe, "-p", "--model", model, "--tools", "", "--setting-sources", "",
                 "--strict-mcp-config", "--no-session-persistence", "--settings", settings,
                 "--system-prompt", system, "--output-format", "json"],
                input=prompt, capture_output=True, text=True, timeout=timeout,
                cwd=cwd, env={**_child_env(), "MAX_THINKING_TOKENS": "0"},
            )
        finally:
            shutil.rmtree(cwd, ignore_errors=True)
        try:
            envelope = json.loads(proc.stdout or "{}")
        except ValueError:
            return ""
        if not isinstance(envelope, dict) or envelope.get("is_error"):
            return ""
        return str(envelope.get("result") or "")

    return Translator(f"claude-cli:{model}", generate)


def _codex_translator(cfg: dict[str, Any]) -> Translator | None:
    """Rung 2' — codex exec, ONLY with an explicitly configured model.

    A ChatGPT-account Codex rejects the "mini" API models (measured 400) and its
    default is the user's own (often xhigh) model, so the engine cannot know the
    cheapest one. Off unless the ruleset names a model."""
    model = str(cfg.get("codexModel") or "").strip()
    exe = shutil.which("codex") if model else None
    if not exe:
        return None

    def generate(system: str, prompt: str, timeout: float) -> str:
        cwd = _scratch_dir()
        out_file = Path(cwd) / "last.txt"
        try:
            subprocess.run(
                [exe, "exec", "--skip-git-repo-check", "--ephemeral", "-s", "read-only", "-m", model,
                 "-C", cwd, "--output-last-message", str(out_file), "-"],
                input=f"{system}\n\n{prompt}", capture_output=True, text=True, timeout=timeout,
                cwd=cwd, env=_child_env(),
            )
            return out_file.read_text(encoding="utf-8") if out_file.exists() else ""
        finally:
            shutil.rmtree(cwd, ignore_errors=True)

    return Translator(f"codex-cli:{model}", generate)


def translator_ladder(cfg: dict[str, Any] | None = None, env: dict[str, str] | None = None) -> list[Translator]:
    """Every rung this machine has, in order. Empty = leave memory native."""
    cfg = cfg or config()
    env = env if env is not None else dict(os.environ)
    rungs: list[Translator] = []
    for build in (
        lambda: _env_translator(env),
        lambda: _ollama_resident_translator() if cfg.get("ollamaResidentOnly", True) else None,
        lambda: _claude_translator(cfg),
        lambda: _codex_translator(cfg),
    ):
        try:
            rung = build()
        except Exception:  # noqa: BLE001 — a probe must never cost the run
            rung = None
        if rung is not None:
            rungs.append(rung)
    return rungs


# --------------------------------------------------------------------- safety

def _screen_secret(text: str) -> bool:
    """True when text must never be sent to a model / stored (curator rules)."""
    try:
        return bool(ow._rule_re("secretKeyValue").search(text) or ow._rule_re("secretValueShapes").search(text)
                    or ow._rule_re("hostAbsolutePath").search(text))
    except Exception:  # noqa: BLE001 — unknown = unsafe
        return True


def protected_tokens(text: str) -> list[str]:
    """ASCII tokens (identifiers, paths, numbers) that a translation must keep."""
    out: list[str] = []
    for raw in _ASCII_TOKEN_RE.findall(text or ""):
        tok = raw.rstrip(".:-/=+#@")
        if tok:
            out.append(tok)
    return out


def _token_count(haystack: str, token: str) -> int:
    if token.isalpha():
        return haystack.lower().count(token.lower())
    return haystack.count(token)


def missing_tokens(native: str, english: str) -> list[str]:
    """Tokens of `native` not preserved (as a multiset) in `english`."""
    need: dict[str, int] = {}
    for tok in protected_tokens(native):
        need[tok] = need.get(tok, 0) + 1
    missing = [tok for tok, count in need.items() if _token_count(english, tok) < count]
    for span in _CODE_SPAN_RE.findall(native or ""):
        if span.isascii() and span not in english:
            missing.append(f"`{span}`")
    return missing


_ADAPTER: Any = None
_ADAPTER_PROBED = False


def _embedding_adapter() -> Any:
    global _ADAPTER, _ADAPTER_PROBED
    if _ADAPTER_PROBED:
        return _ADAPTER
    _ADAPTER_PROBED = True
    try:
        from ontology.embeddings import select_vector_adapter  # noqa: PLC0415

        adapter = select_vector_adapter("auto")
        # The hashing fallback shares no space across languages — a back-check
        # through it would measure spelling, not meaning.
        _ADAPTER = None if "hash" in str(getattr(adapter, "name", "")) else adapter
    except Exception:  # noqa: BLE001
        _ADAPTER = None
    return _ADAPTER


def backcheck(native: str, english: str) -> float | None:
    adapter = _embedding_adapter()
    if adapter is None:
        return None
    try:
        from ontology.embeddings import cosine_similarity  # noqa: PLC0415

        return float(cosine_similarity(adapter.embed(native), adapter.embed(english)))
    except Exception:  # noqa: BLE001
        return None


def check_translation(native: str, english: str, cfg: dict[str, Any], *, multiline: bool = False) -> dict[str, Any]:
    """The acceptance verdict for one translation. `ok` False keeps the native."""
    english = (english or "").strip() if multiline else " ".join((english or "").split())
    verdict: dict[str, Any] = {"ok": False, "en": english}
    if not english:
        return {**verdict, "reason": "empty"}
    if ow._latin_ratio(english) < float(cfg.get("englishMinRatio", 0.8)):
        return {**verdict, "reason": "not-english"}
    if len(english) > max(6 * len(native), 240) or len(english) < 0.25 * len(native.strip()):
        return {**verdict, "reason": "length-out-of-range"}
    if _screen_secret(english):
        return {**verdict, "reason": "secret-in-output"}
    lost = missing_tokens(native, english)
    if lost:
        return {**verdict, "reason": "identifier-lost", "lost": lost[:8]}
    cosine = backcheck(native, english)
    verdict["cosine"] = None if cosine is None else round(cosine, 4)
    if cosine is None:
        if cfg.get("requireBackcheck", True):
            return {**verdict, "reason": "backcheck-unavailable"}
    elif cosine < float(cfg.get("backcheckFloor", 0.25)):
        return {**verdict, "reason": "backcheck-below-floor"}
    return {**verdict, "ok": True, "reason": "accepted"}


# ------------------------------------------------------------------- glossary

def load_glossary(path: Path) -> dict[str, dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        terms = data.get("terms") if isinstance(data, dict) else None
        return terms if isinstance(terms, dict) else {}
    except (OSError, ValueError):
        return {}


def save_glossary(path: Path, terms: dict[str, dict[str, Any]]) -> None:
    try:
        ow._atomic_write(path, json.dumps({"version": 1, "terms": terms}, ensure_ascii=False, indent=1) + "\n")
    except OSError:
        pass


def glossary_for(texts: Iterable[str], terms: dict[str, dict[str, Any]], limit: int) -> dict[str, str]:
    """The fixed translations relevant to this batch, most-used first."""
    joined = "\n".join(texts)
    hits = [(term, row) for term, row in terms.items() if term and term in joined and row.get("en")]
    hits.sort(key=lambda item: (-(10**6 if item[1].get("source") == "owner" else int(item[1].get("count", 0))), item[0]))
    return {term: str(row["en"]) for term, row in hits[: max(0, limit)]}


def learn_terms(terms: dict[str, dict[str, Any]], pairs: Any, native: str, english: str) -> int:
    """First translation seen wins (owner entries are never overwritten)."""
    added = 0
    if not isinstance(pairs, list):
        return 0
    for pair in pairs[:5]:
        if not (isinstance(pair, (list, tuple)) and len(pair) == 2):
            continue
        src, dst = (" ".join(str(part).split()) for part in pair)
        if not src or not dst or len(src) > 40 or len(dst) > 60 or src.isascii():
            continue
        if src not in native or dst.lower() not in english.lower():
            continue
        row = terms.get(src)
        if row is None:
            terms[src] = {"en": dst, "count": 1, "source": "model"}
            added += 1
        elif str(row.get("en", "")).lower() == dst.lower():
            row["count"] = int(row.get("count", 0)) + 1
    return added


def glossary_misses(native: str, english: str, fixed: dict[str, str]) -> list[str]:
    return [term for term, en in fixed.items() if term in native and en.lower() not in english.lower()]


# ---------------------------------------------------------------- batch call

def _parse_items(raw: str) -> dict[str, dict[str, Any]]:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("{"):] if "{" in text else text
    match = _JSON_OBJECT_RE.search(text)
    if not match:
        return {}
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return {}
    items = data.get("items") if isinstance(data, dict) else None
    out: dict[str, dict[str, Any]] = {}
    for item in items or []:
        if isinstance(item, dict) and item.get("h") and isinstance(item.get("en"), str):
            out[str(item["h"])] = item
    return out


def translate_batch(
    translators: list[Translator], items: list[dict[str, str]], glossary: dict[str, str], timeout: float,
) -> tuple[dict[str, dict[str, Any]], str, str]:
    """(results by h, translator name, error). Tries rungs in order until one
    returns parseable JSON; a rung that fails is dropped for the rest of the run."""
    prompt = json.dumps({
        "glossary": glossary,
        "items": [{"h": item["h"], "text": item["text"]} for item in items],
    }, ensure_ascii=False)
    last_error = "no-translator"
    while translators:
        rung = translators[0]
        try:
            raw = rung.generate(_SYSTEM_PROMPT, prompt, timeout)
        except subprocess.TimeoutExpired:
            raw, last_error = "", f"{rung.name}:timeout"
        except Exception as exc:  # noqa: BLE001
            raw, last_error = "", f"{rung.name}:{type(exc).__name__}"
        parsed = _parse_items(raw)
        if parsed:
            return parsed, rung.name, ""
        if not raw and not last_error.startswith(rung.name):
            last_error = f"{rung.name}:empty"
        elif raw:
            last_error = f"{rung.name}:unparseable"
        translators.pop(0)
    return {}, "", last_error


# -------------------------------------------------------------- state / lock

def _read_json(path: Path, default: Any) -> Any:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, type(default)) else default
    except (OSError, ValueError):
        return default


def _write_json(path: Path, value: Any) -> None:
    try:
        ow._atomic_write(path, json.dumps(value, ensure_ascii=False, sort_keys=True, indent=1) + "\n")
    except OSError:
        pass


def _append_ledger(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    try:
        with path.open("a", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError:
        pass


def _pid_alive(pid: Any) -> bool:
    try:
        value = int(pid)
    except (TypeError, ValueError):
        return False
    if value <= 0:
        return False
    if os.name == "nt":
        return True  # bounded by the stale window below
    try:
        os.kill(value, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


class _WorkerLock:
    """One worker per surface. Stale when the holder is gone or older than an hour."""

    STALE_SECONDS = 3600

    def __init__(self, directory: Path):
        self.path = directory / WORKER_LOCK_FILE
        self.fd: int | None = None

    def held_by_other(self) -> bool:
        try:
            holder = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        fresh = time.time() - float(holder.get("at", 0)) < self.STALE_SECONDS
        return fresh and _pid_alive(holder.get("pid"))

    def __enter__(self) -> bool:
        for _ in range(2):
            try:
                self.fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                os.write(self.fd, json.dumps({"pid": os.getpid(), "at": time.time()}).encode("ascii"))
                return True
            except FileExistsError:
                if self.held_by_other():
                    return False
                try:
                    self.path.unlink()
                except OSError:
                    return False
            except OSError:
                return False
        return False

    def __exit__(self, *exc: Any) -> None:
        if self.fd is not None:
            try:
                os.close(self.fd)
            except OSError:
                pass
            try:
                self.path.unlink()
            except OSError:
                pass


def _budget_left(state: dict[str, Any], cap: int) -> int:
    if state.get("day") != _today():
        state["day"], state["dayCount"] = _today(), 0
    return max(0, int(cap) - int(state.get("dayCount", 0)))


# ============================================================ One drawer (C)

def _drawer_paths(root: Path) -> dict[str, Path]:
    meta = Path(root).expanduser() / ow.META_DIR
    return {
        "meta": meta,
        "soul": meta / ow.PROJECT_SOUL_FILE,
        "state": meta / STATE_FILE,
        "ledger": meta / LEDGER_FILE,
        "glossary": meta / GLOSSARY_FILE,
        "map": meta / MAP_FILE,
        "queue": meta / QUEUE_FILE,
        "decisions": meta / ow.CURATOR_DECISIONS_FILE,
    }


def _value_order(meta: Path) -> Callable[[tuple[int, dict[str, str]]], tuple]:
    """Use-ledger (acted on) first, then deliveries, then newest."""
    uses = _read_json(meta / ow.USE_LEDGER_FILE, {})
    shown = _read_json(meta / ow.RECALL_USAGE_FILE, {})

    def key(item: tuple[int, dict[str, str]]) -> tuple:
        index, block = item
        digest = ow._content_hash(block["content"])
        used = int((uses.get(digest) or {}).get("uses", 0)) if isinstance(uses.get(digest), dict) else 0
        count = int((shown.get(digest) or {}).get("count", 0)) if isinstance(shown.get(digest), dict) else 0
        return (-used, -count, -index)

    return key


def drawer_pending(root: Path, cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """What the drawer migration still has to do — pure read."""
    cfg = cfg or config()
    paths = _drawer_paths(root)
    try:
        blocks = ow.parse_durable_blocks(paths["soul"].read_text(encoding="utf-8"))
    except OSError:
        return {"blocks": [], "recover": [], "total": 0}
    superseded = ow._superseded_hashes(paths["meta"])
    state = _read_json(paths["state"], {})
    kept = state.get("kept") if isinstance(state.get("kept"), dict) else {}
    max_attempts = int(cfg.get("maxAttempts", 2))
    translated_natives = {
        ow._normalize(block["native"]): ow._content_hash(block["content"])
        for block in blocks if block.get("native")
    }
    todo: list[tuple[int, dict[str, str]]] = []
    recover: list[tuple[str, str]] = []
    for index, block in enumerate(blocks):
        digest = ow._content_hash(block["content"])
        if digest in superseded or not needs_english(block["content"], cfg):
            continue
        twin = translated_natives.get(ow._normalize(block["content"]))
        if twin and twin != digest:
            recover.append((digest, twin))  # appended before a crash, never superseded
            continue
        row = kept.get(digest) if isinstance(kept.get(digest), dict) else None
        if row and (row.get("permanent") or int(row.get("attempts", 0)) >= max_attempts):
            continue
        todo.append((index, block))
    queue = _read_json(paths["queue"], [])
    rank = {digest: position for position, digest in enumerate(queue if isinstance(queue, list) else [])}
    value = _value_order(paths["meta"])
    todo.sort(key=lambda item: (rank.get(ow._content_hash(item[1]["content"]), len(rank)), value(item)))
    return {"blocks": todo, "recover": recover, "total": len(blocks)}


def _record_translation(paths: dict[str, Path], old: str, new: str) -> None:
    ow._record_supersede(paths["meta"], old, new)
    with ow._LedgerLock(paths["map"]) as acquired:
        if not acquired:
            return
        data = _read_json(paths["map"], {})
        data[old] = new
        _write_json(paths["map"], data)


def _english_block(block: dict[str, str], english: str) -> str:
    evidence = block.get("evidence") or ""
    candidate = {
        "content": english,
        "type": block.get("kind") or "fact",
        "evidence": [] if evidence in ("", "none") else [evidence],
        "contentNative": block["content"],
    }
    return ow._durable_block_text(candidate, block["ticket"], project_slug=block.get("project") or "")


def run_drawer(
    root: Path,
    *,
    translators: list[Translator] | None = None,
    limit: int | None = None,
    reindex: bool = True,
) -> dict[str, Any]:
    """The detached worker body for the One drawer. Never raises."""
    cfg = config()
    paths = _drawer_paths(root)
    receipt: dict[str, Any] = {"surface": "one-drawer", "translated": 0, "keptNative": 0, "recovered": 0}
    if switched_off(cfg) or not paths["soul"].exists():
        return {**receipt, "skipped": "off-or-no-soul"}
    lock = _WorkerLock(paths["meta"])
    with lock as acquired:
        if not acquired:
            return {**receipt, "skipped": "worker-busy"}
        try:
            return _run_drawer_locked(paths, cfg, receipt, translators, limit, reindex, root)
        except Exception as exc:  # noqa: BLE001 — recorded, never raised
            state = _read_json(paths["state"], {})
            state["lastError"] = f"{type(exc).__name__}:{str(exc)[:160]}"
            _write_json(paths["state"], state)
            return {**receipt, "error": state["lastError"]}


def _run_drawer_locked(paths, cfg, receipt, translators, limit, reindex, root) -> dict[str, Any]:
    started = time.monotonic()
    state = _read_json(paths["state"], {})
    state.setdefault("kept", {})
    state["lastRunAt"] = ow._now()
    pending = drawer_pending(root, cfg)
    for old, new in pending["recover"]:
        _record_translation(paths, old, new)
        receipt["recovered"] += 1
    todo = pending["blocks"]
    budget = min(_budget_left(state, int(cfg.get("dailyCap", 200))), int(limit or cfg.get("runCap", 100)))
    receipt["pendingBefore"] = len(todo)
    if not todo:
        return _finish_drawer(paths, state, receipt, root, started, reindex, complete=True)
    if budget <= 0:
        receipt["skipped"] = "daily-cap"
        return _finish_drawer(paths, state, receipt, root, started, reindex=False, complete=False)
    ladder = list(translators) if translators is not None else translator_ladder(cfg)
    if not ladder:
        state["runtime"] = "none"
        state["lastError"] = "no-translator"
        receipt["skipped"] = "no-translator"
        return _finish_drawer(paths, state, receipt, root, started, reindex=False, complete=False)

    glossary_terms = load_glossary(paths["glossary"])
    batch_size = max(1, int(cfg.get("batchSize", 20)))
    timeout = float(cfg.get("callTimeoutSeconds", 240))
    ledger_rows: list[dict[str, Any]] = []
    sent = 0
    queue_done: set[str] = set()
    work = todo[:budget]
    for start in range(0, len(work), batch_size):
        chunk = work[start:start + batch_size]
        items: list[dict[str, str]] = []
        by_h: dict[str, dict[str, str]] = {}
        for _index, block in chunk:
            digest = ow._content_hash(block["content"])
            if _screen_secret(block["content"]):
                state["kept"][digest] = {"reason": "secret", "permanent": True, "at": ow._now()}
                ledger_rows.append({"h": digest, "decision": "kept-native", "reason": "secret", "at": ow._now()})
                receipt["keptNative"] += 1
                continue
            items.append({"h": digest, "text": block["content"]})
            by_h[digest] = block
        if not items:
            continue
        fixed = glossary_for((item["text"] for item in items), glossary_terms, int(cfg.get("glossaryInject", 40)))
        call_started = time.monotonic()
        results, runtime, error = translate_batch(ladder, items, fixed, timeout)
        sent += len(items)
        state["dayCount"] = int(state.get("dayCount", 0)) + len(items)
        if not results:
            state["lastError"] = error
            ledger_rows.append({"batch": len(items), "decision": "failed", "reason": error, "at": ow._now()})
            break  # every rung failed; try again after the spawn interval
        state["runtime"] = runtime
        seconds = round(time.monotonic() - call_started, 2)
        appended: list[tuple[str, str, str]] = []
        for digest, block in by_h.items():
            item = results.get(digest) or {}
            verdict = check_translation(block["content"], str(item.get("en") or ""), cfg)
            row: dict[str, Any] = {"h": digest, "runtime": runtime, "batchSeconds": seconds, "at": ow._now(),
                                   "reason": verdict["reason"], "cosine": verdict.get("cosine")}
            if not verdict["ok"]:
                prev = state["kept"].get(digest) if isinstance(state["kept"].get(digest), dict) else {}
                state["kept"][digest] = {"reason": verdict["reason"], "attempts": int(prev.get("attempts", 0)) + 1,
                                         "at": ow._now()}
                ledger_rows.append({**row, "decision": "kept-native",
                                    **({"lost": verdict["lost"]} if verdict.get("lost") else {}),
                                    # the rejected English, for the mistranslation audit —
                                    # never when the output itself tripped the secret screen
                                    **({"en": verdict["en"][:600]} if verdict["reason"] != "secret-in-output" else {})})
                receipt["keptNative"] += 1
                continue
            english = verdict["en"]
            new = ow._content_hash(english)
            misses = glossary_misses(block["content"], english, fixed)
            learn_terms(glossary_terms, item.get("terms"), block["content"], english)
            appended.append((digest, new, _english_block(block, english)))
            ledger_rows.append({**row, "decision": "translated", "new": new,
                                **({"glossaryMiss": misses[:5]} if misses else {})})
        if appended:
            # Same lock the curator appends under, so the soul never interleaves.
            with ow._LedgerLock(paths["decisions"]) as acquired:
                if not acquired:
                    ledger_rows.append({"batch": len(appended), "decision": "failed", "reason": "soul-busy", "at": ow._now()})
                    break
                existing = ow._durable_hashes(paths["soul"])
                with paths["soul"].open("a", encoding="utf-8") as handle:
                    for _old, new, text in appended:
                        if new not in existing:
                            handle.write(text)
                            existing.add(new)
            for old, new, _text in appended:
                _record_translation(paths, old, new)
                state["kept"].pop(old, None)
                queue_done.add(old)
                receipt["translated"] += 1
        _append_ledger(paths["ledger"], ledger_rows)
        ledger_rows = []
        save_glossary(paths["glossary"], glossary_terms)
        _write_json(paths["state"], state)
    _append_ledger(paths["ledger"], ledger_rows)
    if queue_done:
        with ow._LedgerLock(paths["queue"]) as acquired:
            if acquired:
                queue = _read_json(paths["queue"], [])
                _write_json(paths["queue"], [h for h in queue if h not in queue_done])
    receipt["sent"] = sent
    remaining = drawer_pending(root, cfg)["blocks"]
    receipt["pendingAfter"] = len(remaining)
    return _finish_drawer(paths, state, receipt, root, started, reindex, complete=not remaining)


def _finish_drawer(paths, state, receipt, root, started, reindex, complete) -> dict[str, Any]:
    if complete and not state.get("completeAt"):
        state["completeAt"] = ow._now()
        try:
            ow._migration_receipt(paths["meta"], {"event": MIGRATION_ID, "status": "complete"})
        except OSError:
            pass
    if not complete:
        state.pop("completeAt", None)
    if receipt.get("translated") or receipt.get("recovered"):
        state["lastError"] = None
    state["translatedTotal"] = len(_read_json(paths["map"], {}))
    state["lastRun"] = {k: v for k, v in receipt.items() if k != "surface"}
    state["lastRun"]["seconds"] = round(time.monotonic() - started, 2)
    _write_json(paths["state"], state)
    if reindex and (receipt.get("translated") or receipt.get("recovered")):
        try:
            receipt["index"] = ow.index_durable_blocks(root)
        except Exception as exc:  # noqa: BLE001
            receipt["index"] = {"error": type(exc).__name__}
    return receipt


# --------------------------------------------------------- hook-side (D + C)

def queue_for_translation(root: Path, digests: list[str]) -> int:
    """D — an admitted non-English block is queued, never translated in a hook."""
    if not digests:
        return 0
    path = _drawer_paths(root)["queue"]
    with ow._LedgerLock(path) as acquired:
        if not acquired:
            return 0
        queue = _read_json(path, [])
        added = [digest for digest in digests if digest not in queue]
        if added:
            _write_json(path, (added + queue)[:5000])
        return len(added)


def _spawn(args: list[str], cwd: Path) -> bool:
    try:
        runtime_root = Path(__file__).resolve().parent.parent
        env = os.environ.copy()
        existing = env.get("PYTHONPATH")
        env["PYTHONPATH"] = str(runtime_root) + (os.pathsep + existing if existing else "")
        with open(os.devnull, "rb") as stdin, open(os.devnull, "wb") as out:
            subprocess.Popen(
                [sys.executable, "-m", "agentlas_cloud.memory_translate", *args],
                cwd=str(cwd), env=env, stdin=stdin, stdout=out, stderr=out,
                close_fds=True, start_new_session=True,
            )
    except Exception:  # noqa: BLE001
        return False
    return True


def _spawn_due(state: dict[str, Any], cfg: dict[str, Any], directory: Path, cap_key: str) -> str | None:
    now = time.time()
    if state.get("day") == _today() and int(state.get("dayCount", 0)) >= int(cfg.get(cap_key, 0)):
        return None
    interval = float(cfg.get("minIntervalSeconds", 1800))
    if state.get("lastError") == "no-translator":
        interval = max(interval, float(cfg.get("noTranslatorBackoffSeconds", 6 * 3600)))
    if now - float(state.get("lastSpawnEpoch", 0)) < interval:
        return None
    if _WorkerLock(directory).held_by_other():
        return None
    return "due"


def schedule_drawer_translation(root: Path) -> dict[str, Any]:
    """Hook entry: decide in a few stats, spawn detached. Never raises, never waits."""
    try:
        cfg = config()
        if switched_off(cfg) or in_translate_worker():
            return {"scheduled": "off"}
        paths = _drawer_paths(root)
        if not paths["soul"].exists():
            return {"scheduled": "no-soul"}
        state = _read_json(paths["state"], {})
        queue = _read_json(paths["queue"], [])
        # A completed migration only wakes again when the curator queued a
        # newly admitted non-English block (D).
        if state.get("completeAt") and not queue:
            return {"scheduled": "complete"}
        if _spawn_due(state, cfg, paths["meta"], "dailyCap") is None:
            return {"scheduled": "not-due"}
        state["lastSpawnEpoch"] = time.time()
        _write_json(paths["state"], state)
        spawned = _spawn(["drawer", "--root", str(Path(root).expanduser())], Path(root).expanduser())
        return {"scheduled": "detached" if spawned else "spawn-failed"}
    except Exception as exc:  # noqa: BLE001
        return {"scheduled": "failed", "error": type(exc).__name__}


def drawer_status(root: Path) -> dict[str, Any]:
    paths = _drawer_paths(root)
    state = _read_json(paths["state"], {})
    kept = state.get("kept") if isinstance(state.get("kept"), dict) else {}
    return {
        "migration": MIGRATION_ID,
        "translated": len(_read_json(paths["map"], {})),
        "keptNative": len(kept),
        "queued": len(_read_json(paths["queue"], [])),
        "runtime": state.get("runtime"),
        "dayCount": state.get("dayCount") if state.get("day") == _today() else 0,
        "completeAt": state.get("completeAt"),
        "lastRunAt": state.get("lastRunAt"),
        "lastError": state.get("lastError"),
        "glossaryTerms": len(load_glossary(paths["glossary"])),
    }


# ======================================================= project docs (E)

def _project_paths(project_root: Path) -> dict[str, Path]:
    agentlas = Path(project_root) / ".agentlas"
    return {
        "agentlas": agentlas,
        "db": agentlas / "ontology-runtime.sqlite",
        "docs": agentlas / "ontology-project-docs",
        "en": agentlas / PROJECT_EN_SNAPSHOT_DIR,
        "state": agentlas / STATE_FILE,
        "ledger": agentlas / LEDGER_FILE,
        "glossary": agentlas / GLOSSARY_FILE,
    }


def project_nonenglish_chunks(runtime: Any, docs_dir: Path, cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """Non-English chunks of the project's document snapshots, newest source first."""
    from contextlib import closing  # noqa: PLC0415

    prefix = docs_dir.resolve().as_uri() + "/"
    rows: list[dict[str, Any]] = []
    with closing(runtime.connect()) as conn:
        for row in conn.execute(
            "SELECT c.checksum AS checksum, c.text AS text, c.chunk_index AS idx, s.display_name AS name,"
            " s.updated_at AS updated FROM chunks c JOIN sources s ON s.source_id = c.source_id"
            " WHERE s.uri LIKE ? ORDER BY s.updated_at DESC, c.chunk_index ASC", (prefix + "%",)
        ):
            text = str(row["text"] or "")
            if needs_english(text, cfg):
                rows.append({"key": str(row["checksum"])[:16], "text": text, "name": str(row["name"] or ""),
                             "index": int(row["idx"] or 0)})
    return rows


def project_share(project_root: Path) -> dict[str, Any]:
    """Measurement: how much of a project's document index is non-English."""
    paths = _project_paths(project_root)
    if not paths["db"].is_file():
        return {"present": False}
    from contextlib import closing  # noqa: PLC0415
    import sqlite3  # noqa: PLC0415

    prefix = paths["docs"].resolve().as_uri() + "/"
    with closing(sqlite3.connect(f"file:{paths['db']}?mode=ro", uri=True)) as conn:
        texts = [r[0] for r in conn.execute(
            "SELECT c.text FROM chunks c JOIN sources s ON s.source_id = c.source_id WHERE s.uri LIKE ?",
            (prefix + "%",))]
    non = [t for t in texts if needs_english(t)]
    return {"present": True, "docChunks": len(texts), "nonEnglish": len(non),
            "share": round(len(non) / len(texts), 4) if texts else 0.0, "nonEnglishChars": sum(len(t) for t in non)}


def run_project(project_root: Path, *, translators: list[Translator] | None = None, limit: int | None = None) -> dict[str, Any]:
    """English index surface for non-English project document chunks.

    Human-authored files are never rewritten: each accepted translation becomes
    a snapshot under `.agentlas/ontology-project-docs-en/<chunk checksum>.md`
    ingested into the same ontology. A surface whose source chunk changed or
    vanished is removed. Holds the full ingest's lock (one ontology writer)."""
    cfg = config()
    root = Path(project_root).expanduser()
    paths = _project_paths(root)
    receipt: dict[str, Any] = {"surface": "project-docs", "translated": 0, "keptNative": 0, "removed": 0}
    if switched_off(cfg):
        return {**receipt, "skipped": "off"}
    if not paths["db"].is_file() or paths["agentlas"].is_symlink():
        return {**receipt, "skipped": "no-ontology"}
    try:
        from .project_bootstrap import _release_advisory_lock, _try_advisory_lock  # noqa: PLC0415
        from .project_full_ingest import LOCK_FILE, _open_runtime, _purge_sources, _write_snapshot  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001
        return {**receipt, "skipped": f"import:{type(exc).__name__}"}
    descriptor = os.open(paths["agentlas"] / LOCK_FILE, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        if not _try_advisory_lock(descriptor):
            return {**receipt, "skipped": "ingest-busy"}
        try:
            return _run_project_locked(root, paths, cfg, receipt, translators, limit,
                                       _open_runtime, _purge_sources, _write_snapshot)
        finally:
            _release_advisory_lock(descriptor)
    except Exception as exc:  # noqa: BLE001
        state = _read_json(paths["state"], {})
        state["lastError"] = f"{type(exc).__name__}:{str(exc)[:160]}"
        _write_json(paths["state"], state)
        return {**receipt, "error": state["lastError"]}
    finally:
        os.close(descriptor)


def _run_project_locked(root, paths, cfg, receipt, translators, limit, open_runtime, purge, write_snapshot):
    from .project_full_ingest import looks_secret  # noqa: PLC0415

    state = _read_json(paths["state"], {})
    state.setdefault("kept", {})
    state["lastRunAt"] = ow._now()
    runtime = open_runtime(root)
    chunks = project_nonenglish_chunks(runtime, paths["docs"], cfg)
    current = {chunk["key"]: chunk for chunk in chunks}
    paths["en"].mkdir(mode=0o700, exist_ok=True)
    existing = {entry.stem: entry for entry in paths["en"].glob("*.md") if entry.is_file() and not entry.is_symlink()}
    stale = [entry for key, entry in existing.items() if key not in current]
    uris = [entry.resolve().as_uri() for entry in stale]
    for entry in stale:
        try:
            entry.unlink()
        except OSError:
            pass
    receipt["removed"] = purge(runtime, uris) if uris else 0
    max_attempts = int(cfg.get("maxAttempts", 2))
    todo = []
    for key, chunk in current.items():
        if key in existing:
            continue
        row = state["kept"].get(key) if isinstance(state["kept"].get(key), dict) else None
        if row and (row.get("permanent") or int(row.get("attempts", 0)) >= max_attempts):
            continue
        todo.append(chunk)
    receipt["pendingBefore"] = len(todo)
    budget = min(_budget_left(state, int(cfg.get("projectDailyCap", 60))), int(limit or cfg.get("projectDailyCap", 60)))
    ladder = list(translators) if translators is not None else (translator_ladder(cfg) if todo and budget else [])
    if todo and budget and not ladder:
        state["lastError"] = "no-translator"
    glossary_terms = load_glossary(paths["glossary"])
    ledger_rows: list[dict[str, Any]] = []
    batch_size = max(1, int(cfg.get("projectBatchSize", 8)))
    work = todo[:budget] if ladder else []
    for start in range(0, len(work), batch_size):
        batch = []
        for chunk in work[start:start + batch_size]:
            if looks_secret(chunk["text"]) or _screen_secret(chunk["text"]):
                state["kept"][chunk["key"]] = {"reason": "secret", "permanent": True, "at": ow._now()}
                receipt["keptNative"] += 1
                continue
            batch.append(chunk)
        if not batch:
            continue
        fixed = glossary_for((c["text"] for c in batch), glossary_terms, int(cfg.get("glossaryInject", 40)))
        results, runtime_name, error = translate_batch(
            ladder, [{"h": c["key"], "text": c["text"]} for c in batch], fixed, float(cfg.get("callTimeoutSeconds", 240)))
        state["dayCount"] = int(state.get("dayCount", 0)) + len(batch)
        if not results:
            state["lastError"] = error
            break
        state["runtime"] = runtime_name
        for chunk in batch:
            item = results.get(chunk["key"]) or {}
            verdict = check_translation(chunk["text"], str(item.get("en") or ""), cfg, multiline=True)
            row = {"key": chunk["key"], "doc": chunk["name"], "reason": verdict["reason"],
                   "cosine": verdict.get("cosine"), "runtime": runtime_name, "at": ow._now()}
            if not verdict["ok"]:
                prev = state["kept"].get(chunk["key"]) or {}
                state["kept"][chunk["key"]] = {"reason": verdict["reason"], "attempts": int(prev.get("attempts", 0)) + 1,
                                               "at": ow._now()}
                ledger_rows.append({**row, "decision": "kept-native",
                                    **({"lost": verdict["lost"]} if verdict.get("lost") else {}),
                                    **({"en": verdict["en"][:600]} if verdict["reason"] != "secret-in-output" else {})})
                receipt["keptNative"] += 1
                continue
            learn_terms(glossary_terms, item.get("terms"), chunk["text"], verdict["en"])
            body = (f"English index surface of project document {chunk['name']} (chunk {chunk['index']}); "
                    f"the original document is the authority.\n\n{verdict['en']}\n")
            target = paths["en"] / f"{chunk['key']}.md"
            write_snapshot(target, body.encode("utf-8"), time.time())
            runtime.ingest_path(target, refresh_graph=False)
            state["kept"].pop(chunk["key"], None)
            ledger_rows.append({**row, "decision": "translated"})
            receipt["translated"] += 1
        _append_ledger(paths["ledger"], ledger_rows)
        ledger_rows = []
        save_glossary(paths["glossary"], glossary_terms)
        _write_json(paths["state"], state)
    remaining = [c for c in todo if not (paths["en"] / f"{c['key']}.md").exists()
                 and not (state["kept"].get(c["key"]) or {}).get("permanent")
                 and int((state["kept"].get(c["key"]) or {}).get("attempts", 0)) < max_attempts]
    receipt["pendingAfter"] = len(remaining)
    try:
        from .project_full_ingest import migration_applied  # noqa: PLC0415

        ingested = migration_applied(root)
    except Exception:  # noqa: BLE001
        ingested = False
    # Complete only once the documents are actually in the index — before the
    # full ingest lands there is nothing to measure, not nothing to do.
    if not remaining and ingested:
        state["completeAt"] = state.get("completeAt") or ow._now()
        _record_project_receipt(paths["agentlas"])
    if receipt["translated"]:
        state["lastError"] = None
    state["lastRun"] = {k: v for k, v in receipt.items() if k != "surface"}
    _write_json(paths["state"], state)
    return receipt


def _record_project_receipt(agentlas: Path) -> None:
    ledger = agentlas / "migrations.jsonl"
    try:
        if ledger.is_file():
            for line in ledger.read_text(encoding="utf-8").splitlines():
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if row.get("id") == PROJECT_MIGRATION_ID and row.get("kind") != "migration-failed":
                    return
        with ledger.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"id": PROJECT_MIGRATION_ID, "at": ow._now()}) + "\n")
    except OSError:
        pass


def schedule_project_translation(project_root: Path) -> dict[str, Any]:
    """Hook entry for the project ladder. A few stats; spawns detached."""
    try:
        cfg = config()
        if switched_off(cfg) or in_translate_worker():
            return {"scheduled": "off"}
        paths = _project_paths(Path(project_root))
        if not paths["db"].is_file() or paths["agentlas"].is_symlink():
            return {"scheduled": "no-ontology"}
        state = _read_json(paths["state"], {})
        if state.get("completeAt") and time.time() - float(state.get("lastSpawnEpoch", 0)) < float(
                cfg.get("projectRefreshSeconds", 6 * 3600)):
            return {"scheduled": "complete"}
        if _spawn_due(state, cfg, paths["agentlas"], "projectDailyCap") is None:
            return {"scheduled": "not-due"}
        state["lastSpawnEpoch"] = time.time()
        _write_json(paths["state"], state)
        spawned = _spawn(["project", "--project", str(project_root)], Path(project_root))
        return {"scheduled": "detached" if spawned else "spawn-failed"}
    except Exception as exc:  # noqa: BLE001
        return {"scheduled": "failed", "error": type(exc).__name__}


# ------------------------------------------------------------------------ CLI

def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="memory_translate")
    parser.add_argument("command", choices=["drawer", "project", "status", "share"])
    parser.add_argument("--root", default=os.path.expanduser("~/.agentlas/one"))
    parser.add_argument("--project", default="")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args(argv)
    # Every child this worker starts (a host-cmd translator, a CLI) inherits the
    # marker, so no memory hook inside a translation session mints new memory.
    os.environ[TRANSLATE_WORKER_ENV] = "1"
    if args.command == "drawer":
        out = run_drawer(Path(args.root), limit=args.limit or None)
    elif args.command == "project":
        out = run_project(Path(args.project or os.getcwd()), limit=args.limit or None)
    elif args.command == "share":
        out = project_share(Path(args.project or os.getcwd()))
    else:
        out = drawer_status(Path(args.root))
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
