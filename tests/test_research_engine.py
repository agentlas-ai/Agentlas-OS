import json
import subprocess
import sys
from pathlib import Path
from urllib.error import HTTPError

from agentlas_cloud.cli import main
from agentlas_cloud.networking.bootstrap import append_jsonl, utc_now
from agentlas_cloud.research import (
    ResearchModuleManifest,
    ResearchRequest,
    ResearchResult,
    run_research,
    run_research_armory,
    run_research_browser_candidates,
    run_research_bridge_check,
    run_research_bridge_contracts,
    run_research_credentials,
    run_research_doctor,
    run_research_hardpoints,
    run_research_platform_check,
    run_research_platform_contracts,
    run_research_plan,
    run_research_preflight,
    run_research_proofs,
    run_research_recommendation,
    run_research_social_fallbacks,
    run_research_status,
    run_research_verify,
    run_research_profile,
)
from agentlas_cloud.research.contracts import ResearchAttempt
from agentlas_cloud.research.adapters.agent_browser_cli import AgentBrowserCliAdapter
from agentlas_cloud.research.adapters.browseros_browser import BrowserOSBrowserAdapter
from agentlas_cloud.research.adapters.browser_use import BrowserUseAdapter
from agentlas_cloud.research.adapters.duckduckgo_html_search import DuckDuckGoHtmlSearchAdapter
from agentlas_cloud.research.adapters.github_repos_search import GitHubReposSearchAdapter
from agentlas_cloud.research.adapters.hyperagent_browser import HyperAgentBrowserAdapter
from agentlas_cloud.research.adapters.http_reader import HttpReaderAdapter
from agentlas_cloud.research.adapters.insane_fetch import InsaneFetchAdapter
from agentlas_cloud.research.adapters.jina_reader import JinaReaderAdapter, JinaSearchAdapter
from agentlas_cloud.research.adapters.news_rss_search import NewsRssSearchAdapter
from agentlas_cloud.research.adapters.playwright_mcp import PlaywrightMcpAdapter
from agentlas_cloud.research.adapters.stagehand_browser import StagehandBrowserAdapter
from agentlas_cloud.research.adapters.steel_browser import SteelBrowserAdapter
from agentlas_cloud.research.engine import ResearchEngine
from agentlas_cloud.research.policy import classify_url, module_allowed, weight_allowed
from agentlas_cloud.research.platforms.reddit import RedditOAuthAdapter, RedditPublicAdapter
from agentlas_cloud.research.platforms.threads import ThreadsPublicWebAdapter, ThreadsSearchAdapter
from agentlas_cloud.research.registry import AdapterRegistry
from agentlas_cloud.research.redaction import redact_secret_values


class FakeReader(HttpReaderAdapter):
    def __init__(self):
        super().__init__()

    def _fetch(self, url):
        return (
            200,
            "<html><head><title>Example</title></head><body><main>Hello research</main></body></html>",
            url,
            "text/html; charset=utf-8",
        )


class FailingReader(HttpReaderAdapter):
    def _fetch(self, url):
        raise HTTPError(url, 403, "Forbidden", hdrs=None, fp=None)


class ExplodingReader(HttpReaderAdapter):
    def read(self, source_hint, request):
        raise UnicodeEncodeError("ascii", source_hint, 8, 9, "ordinal not in range(128)")


def clear_reddit_oauth_env(monkeypatch):
    for name in (
        "AGENTLAS_REDDIT_BEARER_TOKEN",
        "REDDIT_BEARER_TOKEN",
        "AGENTLAS_REDDIT_CLIENT_ID",
        "AGENTLAS_REDDIT_CLIENT_SECRET",
        "REDDIT_CLIENT_ID",
        "REDDIT_CLIENT_SECRET",
    ):
        monkeypatch.delenv(name, raising=False)


def test_research_request_hash_is_stable():
    first = ResearchRequest(query="Read", source_hints=["https://example.com"])
    second = ResearchRequest(query="Read", source_hints=["https://example.com"])
    assert first.request_hash == second.request_hash


def test_http_reader_contains_non_ascii_request_target_failure(monkeypatch):
    def fail_non_ascii_url(self, url):
        raise UnicodeEncodeError("ascii", url, 8, 9, "ordinal not in range(128)")

    monkeypatch.setattr(HttpReaderAdapter, "_fetch", fail_non_ascii_url)
    result, attempt = HttpReaderAdapter().read("https://example.com/한글", ResearchRequest(query="read"))

    assert result is None
    assert attempt.status == "error"
    assert "UnicodeEncodeError" in attempt.reason


def test_research_engine_contains_unexpected_adapter_failure(tmp_path):
    engine = ResearchEngine(registry=AdapterRegistry([ExplodingReader()]), home=tmp_path)

    result = engine.run(
        ResearchRequest(
            query="read",
            source_hints=["https://example.com/한글"],
            allowed_modules=["read.http"],
        )
    )

    assert result["status"] == "partial"
    assert result["results"] == []
    attempt = result["receipt"]["attempts"][0]
    assert attempt["module"] == "read.http"
    assert attempt["status"] == "error"
    assert "UnicodeEncodeError" in attempt["reason"]


def test_research_request_hash_includes_cost_boundary():
    first = ResearchRequest(query="Read", source_hints=["https://example.com"], max_cost={"requests": 1})
    second = ResearchRequest(query="Read", source_hints=["https://example.com"], max_cost={"requests": 2})

    assert first.request_hash != second.request_hash


def test_research_request_hash_includes_query_variants():
    first = ResearchRequest(query="Read", source_hints=["search:auto:agent browser"], query_variants=["docs"])
    second = ResearchRequest(query="Read", source_hints=["search:auto:agent browser"], query_variants=["reddit"])

    assert first.request_hash != second.request_hash


def test_hephaestus_help_mentions_public_web_research_loadout():
    help_text = (Path(__file__).resolve().parents[1] / "bin" / "hephaestus").read_text()

    assert "--research-loadout auto|safe|public-web|social|browser|full|recommended" in help_text
    assert "bin/hephaestus hep-browser <url-or-query> [--setup|--check]" in help_text
    assert 'research search "<query>" [--variant reddit] [--loadout safe|public-web|social]' in help_text


def test_research_redaction_hides_inline_and_environment_secrets(monkeypatch):
    monkeypatch.setenv("AGENTLAS_STAGEHAND_SNAPSHOT_CMD", "stagehand --api-key secret-stagehand-token {url}")
    monkeypatch.setenv("AGENTLAS_TEST_TOKEN", "secret-env-token")

    redacted = redact_secret_values(
        "failed Bearer secret-stagehand-token api_key=secret-api-token "
        "--token secret-flag-token secret-env-token"
    )

    assert "[redacted]" in redacted
    assert "secret-stagehand-token" not in redacted
    assert "secret-api-token" not in redacted
    assert "secret-flag-token" not in redacted
    assert "secret-env-token" not in redacted


def test_research_request_accepts_scalar_module_fields():
    request = ResearchRequest.from_value(
        {
            "query": "Read",
            "source_hints": "https://example.com",
            "allowed_modules": "read.http",
            "forbidden_modules": "read.jina",
        }
    )

    assert request.source_hints == ["https://example.com"]
    assert request.allowed_modules == ["read.http"]
    assert request.forbidden_modules == ["read.jina"]


def test_research_request_clamps_follow_results():
    assert ResearchRequest.from_value({"query": "x", "follow_results": 99}).follow_results == 10
    assert ResearchRequest.from_value({"query": "x", "follow_results": -4}).follow_results == 0


def test_policy_blocks_private_hosts():
    ok, reason = classify_url("http://127.0.0.1:8000")
    assert ok is False
    assert reason.startswith("ip_blocked")


def test_module_policy_respects_allowed_and_forbidden():
    assert module_allowed("read.http", ["read.http"], [])[0] is True
    assert module_allowed("read.http", [], ["read.http"]) == (False, "forbidden_module")
    assert module_allowed("read.http", ["platform.reddit"], []) == (False, "not_in_allowed_modules")


def test_weight_policy_blocks_overweight_modules():
    assert weight_allowed("read.http", "") == (True, "allowed")
    assert weight_allowed("browser_heavy", "credentialed_medium")[0] is False
    assert weight_allowed("browser_heavy", "credentialed_medium")[1].startswith("weight_exceeds_max:")
    assert weight_allowed("adaptive_medium", "credentialed_medium") == (True, "allowed")


def test_research_engine_reads_url_and_writes_receipt(tmp_path):
    registry = AdapterRegistry([FakeReader(), JinaReaderAdapter()])
    result = ResearchEngine(registry=registry, home=tmp_path).run(
        {
            "query": "Read example",
            "source_hints": ["https://example.com"],
            "allowed_modules": ["read.http"],
        }
    )

    assert result["schema"] == "agentlas.research.v0"
    assert result["status"] == "ok"
    assert result["results"][0]["title"] == "Example"
    assert "Hello research" in result["results"][0]["content_markdown"]
    assert result["receipt"]["module_chain"] == ["read.http"]
    assert result["receipt"]["policy"]["registered_module_count"] == 2
    assert result["receipt"]["policy"]["mounted_module_ids"] == ["read.http"]
    assert result["receipt"]["policy"]["mounted_module_slots"] == {"reader": ["read.http"]}
    assert len(result["receipt"]["policy"]["module_manifests"]) == 1
    assert result["receipt"]["policy"]["module_manifests"][0]["id"] == "read.http"
    assert result["capability_summary"]["status"] == "ready"
    assert result["capability_summary"]["mounted_slots"] == {"reader": ["read.http"]}
    assert result["capability_summary"]["browser"]["status"] == "not_requested"
    assert result["capability_summary"]["trust"]["can_use_for_build_context"] is True
    assert result["receipt"]["policy"]["capability_summary"] == result["capability_summary"]
    assert result["results"][0]["receipt_id"] == result["receipt"]["receipt_id"]
    assert (tmp_path / "ledgers" / "research-receipts.jsonl").exists()


def test_research_loadout_expands_allowed_modules(tmp_path):
    registry = AdapterRegistry([FakeReader()])
    result = ResearchEngine(registry=registry, home=tmp_path).run(
        {
            "query": "Read example",
            "source_hints": "https://example.com",
            "loadout": "public-web",
        }
    )

    assert result["status"] == "ok"
    assert result["request"]["loadout"] == "public-web"
    assert result["request"]["allowed_modules"] == [
        "search.ddg_html",
        "search.news_rss",
        "search.github_repos",
        "read.http",
        "platform.reddit",
        "platform.threads.public",
        "read.insane_fetch",
    ]
    assert result["receipt"]["policy"]["loadout"]["name"] == "public-web"


def test_auto_loadout_defaults_to_public_web_without_browser(tmp_path):
    class BrowserProbe(StagehandBrowserAdapter):
        def read(self, source_hint, request):
            raise AssertionError("auto loadout must not execute browser modules")

    registry = AdapterRegistry([FailingReader(), BrowserProbe()])
    result = ResearchEngine(registry=registry, home=tmp_path).run(
        {
            "query": "Auto should stay light",
            "source_hints": ["https://example.com/blocked"],
        }
    )

    assert result["request"]["loadout"] == "auto"
    assert result["request"]["max_weight"] == "light"
    assert "read.http" in result["request"]["allowed_modules"]
    assert "read.insane_fetch" not in result["request"]["allowed_modules"]
    assert not any(module.startswith("browser.") for module in result["request"]["allowed_modules"])
    assert not any(attempt["module"].startswith("browser.") for attempt in result["receipt"]["attempts"])
    assert result["receipt"]["policy"]["browser_execution"]["attempted"] is False
    assert result["receipt"]["policy"]["browser_execution"]["status"] == "not_requested"
    assert result["receipt"]["policy"]["read_strategy"] == "first_success"


def test_auto_loadout_uses_public_threads_search_fallback_without_api(tmp_path):
    class ThreadsDuckDuckGoFallback(DuckDuckGoHtmlSearchAdapter):
        def _fetch_text(self, url):
            assert url == "https://lite.duckduckgo.com/lite/?q=agent+browser+Threads+site%3Athreads.com"
            return """<html><body>
            <a rel="nofollow" href="/l/?uddg=https%3A%2F%2Fwww.threads.net%2F%40agentlas%2Fpost%2Fabc">Threads public fallback</a>
            </body></html>"""

    registry = AdapterRegistry([ThreadsSearchAdapter(), ThreadsDuckDuckGoFallback(), FakeThreadsPublic()])
    result = ResearchEngine(registry=registry, home=tmp_path).run(
        {
            "query": "Read Threads without explicit loadout",
            "source_hints": ["threads:keyword:agent browser"],
        }
    )

    assert result["status"] == "ok"
    assert result["request"]["loadout"] == "auto"
    assert result["request"]["max_weight"] == "adaptive_medium"
    assert "platform.threads" not in result["request"]["allowed_modules"]
    assert "platform.threads.public" in result["request"]["allowed_modules"]
    assert result["receipt"]["module_chain"] == ["search.ddg_html"]
    assert not any(attempt["module"] == "platform.threads" for attempt in result["receipt"]["attempts"])


def test_auto_loadout_allows_explicit_reddit_hint_without_browser(tmp_path):
    registry = AdapterRegistry([FakeRedditOAuth(), FakeReddit(), StagehandBrowserAdapter()])
    result = ResearchEngine(registry=registry, home=tmp_path).run(
        {
            "query": "Read Reddit without explicit loadout",
            "source_hints": ["https://www.reddit.com/r/Agentlas/comments/abc/agent_browsers/"],
        }
    )

    assert result["status"] == "ok"
    assert result["request"]["max_weight"] == "adaptive_medium"
    assert "platform.reddit.oauth" not in result["request"]["allowed_modules"]
    assert "platform.reddit" in result["request"]["allowed_modules"]
    assert not any(module.startswith("browser.") for module in result["request"]["allowed_modules"])
    assert result["receipt"]["module_chain"] == ["platform.reddit"]
    assert "test-reddit-token" not in str(result)


def test_research_engine_keeps_optional_modules_nonfatal(tmp_path):
    result = run_research(
        {
            "query": "Read example",
            "source_hints": ["https://example.com"],
            "allowed_modules": ["platform.reddit"],
        },
        home=tmp_path,
    )

    assert result["status"] == "partial"
    assert result["results"] == []
    assert result["receipt"]["attempts"][0]["status"] == "module_unavailable"
    assert result["receipt"]["attempts"][0]["reason"] == "not_in_allowed_modules"


def test_research_escalation_suggests_public_web_after_static_block(tmp_path):
    result = ResearchEngine(registry=AdapterRegistry([FailingReader()]), home=tmp_path).run(
        {
            "query": "Blocked public page",
            "source_hints": ["https://example.com/blocked"],
        }
    )

    advice = result["receipt"]["policy"]["escalation_advice"]
    assert advice["status"] == "suggested"
    assert advice["auto_escalated"] is False
    suggestion = advice["suggestions"][0]
    assert suggestion["reason"] == "static_http_blocked"
    assert suggestion["loadout"] == "public-web"
    assert suggestion["modules"] == ["read.insane_fetch"]
    assert suggestion["request_patch"] == {
        "loadout": "public-web",
        "allowed_modules": ["read.insane_fetch"],
        "max_weight": "adaptive_medium",
    }
    assert suggestion["approval_required"] is False
    assert suggestion["run_after_config"] is True
    assert suggestion["auto_apply"] is False
    assert suggestion["safety_boundary"] == "advisory_only"


def test_research_escalation_suggests_browser_configuration_when_requested(tmp_path, monkeypatch):
    monkeypatch.delenv("AGENTLAS_STAGEHAND_SNAPSHOT_CMD", raising=False)
    result = ResearchEngine(registry=AdapterRegistry([StagehandBrowserAdapter()]), home=tmp_path).run(
        {
            "query": "Browser requested",
            "source_hints": ["https://example.com"],
            "allowed_modules": ["browser.stagehand"],
        }
    )

    advice = result["receipt"]["policy"]["escalation_advice"]
    assert advice["status"] == "suggested"
    assert advice["auto_escalated"] is False
    suggestion = advice["suggestions"][0]
    assert suggestion["reason"] == "browser_hardpoint_unavailable"
    assert suggestion["modules"] == ["browser.stagehand"]
    assert suggestion["request_patch"] == {
        "loadout": "browser",
        "allowed_modules": ["browser.stagehand"],
        "max_weight": "browser_heavy",
        "depth": "deep",
    }
    assert suggestion["approval_required"] is True
    assert suggestion["run_after_config"] is False
    assert suggestion["auto_apply"] is False


def test_research_escalation_suggests_threads_credentials(tmp_path, monkeypatch):
    monkeypatch.delenv("AGENTLAS_THREADS_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("THREADS_ACCESS_TOKEN", raising=False)
    result = ResearchEngine(registry=AdapterRegistry([ThreadsSearchAdapter()]), home=tmp_path).run(
        {
            "query": "Threads search",
            "source_hints": ["threads:keyword:agent browser"],
            "loadout": "social",
        }
    )

    advice = result["receipt"]["policy"]["escalation_advice"]
    assert advice["status"] == "suggested"
    assert advice["auto_escalated"] is False
    suggestion = advice["suggestions"][0]
    assert suggestion["reason"] == "threads_token_missing"
    assert suggestion["modules"] == ["platform.threads"]
    assert suggestion["request_patch"] == {
        "loadout": "social",
        "allowed_modules": ["platform.threads"],
        "max_weight": "credentialed_medium",
    }
    assert suggestion["approval_required"] is False
    assert suggestion["run_after_config"] is False
    assert suggestion["auto_apply"] is False
    assert "THREADS_ACCESS_TOKEN" not in str(result["results"])


def test_research_cli_reads_url(tmp_path, monkeypatch, capsys):
    def fake_fetch(self, url):
        return (
            200,
            "<html><head><title>CLI</title></head><body>Research CLI works</body></html>",
            url,
            "text/html",
        )

    monkeypatch.setattr(HttpReaderAdapter, "_fetch", fake_fetch)
    code = main(["research", "read", "https://example.com", "--home", str(tmp_path)])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "agentlas.research.v0"
    assert payload["results"][0]["title"] == "CLI"
    assert (tmp_path / "ledgers" / "research-receipts.jsonl").exists()


def test_research_cli_deep_read_collects_browser_when_mounted(tmp_path, monkeypatch, capsys):
    def fake_fetch(self, url):
        return (
            200,
            "<html><head><title>Static CLI</title></head><body>Static source</body></html>",
            url,
            "text/html",
        )

    def fake_snapshot_argv(self, url):
        return ["stagehand-snapshot", url]

    def fake_run(self, argv):
        assert argv == ["stagehand-snapshot", "https://example.com"]
        return subprocess.CompletedProcess(
            argv,
            0,
            '{"title":"Deep Browser","extraction":"# Deep Browser\\n\\nBrowser source","limits":["dom_extract"]}',
            "",
        )

    monkeypatch.setattr(HttpReaderAdapter, "_fetch", fake_fetch)
    monkeypatch.setattr(StagehandBrowserAdapter, "_snapshot_argv", fake_snapshot_argv)
    monkeypatch.setattr(StagehandBrowserAdapter, "_run", fake_run)
    code = main(
        [
            "research",
            "read",
            "https://example.com",
            "--loadout",
            "browser",
            "--depth",
            "deep",
            "--home",
            str(tmp_path),
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["request"]["depth"] == "deep"
    assert payload["receipt"]["policy"]["read_strategy"] == "deep_static_plus_browser"
    assert payload["receipt"]["module_chain"][0] == "read.http"
    assert "browser.stagehand" in payload["receipt"]["module_chain"]
    assert [item["title"] for item in payload["results"]] == ["Static CLI", "Deep Browser"]
    assert payload["receipt"]["policy"]["browser_used"] is True
    assert payload["receipt"]["policy"]["browser_execution"]["status"] == "used"
    assert payload["receipt"]["policy"]["browser_execution"]["succeeded"] is True
    assert payload["capability_summary"]["browser"]["used"] is True
    assert payload["capability_summary"]["browser"]["status"] == "used"
    assert payload["capability_summary"]["status"] == "ready"


def test_research_cli_max_weight_override_allows_heavy_browser(tmp_path, monkeypatch, capsys):
    def fake_fetch(self, url):
        return (
            200,
            "<html><head><title>Static CLI</title></head><body>Static source</body></html>",
            url,
            "text/html",
        )

    def fake_snapshot_argv(self, url):
        return ["stagehand-snapshot", url]

    def fake_run(self, argv):
        return subprocess.CompletedProcess(
            argv,
            0,
            '{"title":"Override Browser","extraction":"# Override Browser\\n\\nHeavy allowed"}',
            "",
        )

    monkeypatch.setattr(HttpReaderAdapter, "_fetch", fake_fetch)
    monkeypatch.setattr(StagehandBrowserAdapter, "_snapshot_argv", fake_snapshot_argv)
    monkeypatch.setattr(StagehandBrowserAdapter, "_run", fake_run)
    code = main(
        [
            "research",
            "read",
            "https://example.com",
            "--loadout",
            "safe",
            "--allow-module",
            "browser.stagehand",
            "--depth",
            "deep",
            "--max-weight",
            "browser_heavy",
            "--home",
            str(tmp_path),
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["request"]["max_weight"] == "browser_heavy"
    assert payload["receipt"]["policy"]["max_weight"] == "browser_heavy"
    assert [item["platform"] for item in payload["results"]] == ["web", "browser"]
    assert payload["receipt"]["policy"]["browser_used"] is True
    assert payload["receipt"]["policy"]["browser_execution"]["status"] == "used"


def test_research_plan_previews_weight_blocks_without_running():
    payload = run_research_plan(
        {
            "query": "Preview browser hardpoint",
            "source_hints": "https://example.com",
            "loadout": "safe",
            "depth": "deep",
            "allowed_modules": ["browser.stagehand"],
        }
    )

    assert payload["schema"] == "agentlas.research.plan.v0"
    assert payload["policy"]["network_will_run"] is False
    assert payload["policy"]["receipt_will_be_written"] is False
    assert payload["request"]["max_weight"] == "adaptive_medium"
    assert payload["policy"]["read_strategy"] == "first_success"
    assert payload["mounted_modules"] == ["read.http"]
    stagehand = next(
        candidate
        for candidate in payload["sources"][0]["candidates"]
        if candidate["id"] == "browser.stagehand"
    )
    assert stagehand["status"] == "blocked_by_weight"
    assert stagehand["reason"].startswith("weight_exceeds_max:")
    assert stagehand["readiness"]["state"] == "needs_config"


def test_research_plan_browser_loadout_mounts_but_does_not_assume_browser_ready(monkeypatch):
    for name in (
        "AGENTLAS_PLAYWRIGHT_MCP_SNAPSHOT_CMD",
        "AGENTLAS_BROWSER_USE_SNAPSHOT_CMD",
        "AGENTLAS_STAGEHAND_SNAPSHOT_CMD",
        "AGENTLAS_STEEL_SNAPSHOT_CMD",
        "AGENTLAS_BROWSEROS_SNAPSHOT_CMD",
        "AGENTLAS_AGENT_BROWSER_BIN",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr("agentlas_cloud.research.armory.shutil.which", lambda name: None)

    payload = run_research_plan(
        {
            "query": "Preview deep browser",
            "source_hints": "https://example.com",
            "loadout": "browser",
            "depth": "deep",
        }
    )

    assert payload["request"]["max_weight"] == "browser_heavy"
    assert payload["policy"]["read_strategy"] == "first_success"
    assert payload["policy"]["browser_modules_mounted"] is True
    assert payload["policy"]["browser_modules_ready"] is False
    assert "browser.stagehand" in payload["mounted_modules"]
    assert "read.insane_fetch" in payload["mounted_modules"]
    assert any(item["id"] == "browser.stagehand" for item in payload["unready_mounted_modules"])


def test_research_plan_uses_deep_strategy_when_browser_hardpoint_ready(monkeypatch):
    monkeypatch.setenv("AGENTLAS_STAGEHAND_SNAPSHOT_CMD", "stagehand-snapshot {url}")
    monkeypatch.setattr("agentlas_cloud.research.armory.shutil.which", lambda name: None)
    payload = run_research_plan(
        {
            "query": "Preview ready browser",
            "source_hints": "https://example.com",
            "loadout": "browser",
            "depth": "deep",
        }
    )

    assert payload["policy"]["read_strategy"] == "deep_static_plus_browser"
    assert payload["policy"]["browser_modules_ready"] is True
    stagehand = next(
        candidate
        for candidate in payload["sources"][0]["candidates"]
        if candidate["id"] == "browser.stagehand"
    )
    assert stagehand["readiness"]["state"] == "ready"


def test_research_plan_applies_source_hint_budget_before_mounting():
    payload = run_research_plan(
        {
            "query": "agent browser modules",
            "intent": "plan",
            "source_hints": ["search:ddg_html:agent browser modules"],
            "query_variants": ["docs", "reddit", "github"],
            "allowed_modules": ["search.ddg_html"],
            "max_cost": {"requests": 2},
        }
    )

    assert payload["source_hints_before_budget"] == [
        "search:ddg_html:agent browser modules",
        "search:ddg_html:agent browser modules documentation docs",
        "search:ddg_html:agent browser modules reddit",
        "search:ddg_html:agent browser modules GitHub",
    ]
    assert payload["source_hints_used"] == [
        "search:ddg_html:agent browser modules",
        "search:ddg_html:agent browser modules documentation docs",
    ]
    assert payload["source_hints_dropped_by_budget"] == [
        "search:ddg_html:agent browser modules reddit",
        "search:ddg_html:agent browser modules GitHub",
    ]
    assert payload["policy"]["max_cost_requests"] == 2
    assert payload["policy"]["source_hint_count_before_budget"] == 4
    assert payload["policy"]["source_hint_count_after_budget"] == 2
    assert payload["policy"]["source_hint_budget_limited"] is True
    assert len(payload["sources"]) == 2


def test_research_cli_plan_search_preview_does_not_write_receipt(tmp_path, capsys):
    code = main(
        [
            "research",
            "plan",
            "--search",
            "--query",
            "agent browser modules",
            "--loadout",
            "public-web",
            "--home",
            str(tmp_path),
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "agentlas.research.plan.v0"
    assert payload["source_hints_used"] == [
        "search:ddg_html:agent browser modules",
        "search:news_rss:agent browser modules",
    ]
    assert payload["policy"]["network_will_run"] is False
    assert payload["policy"]["auto_search_modules"] == ["search.ddg_html", "search.news_rss"]
    assert not (tmp_path / "ledgers" / "research-receipts.jsonl").exists()


def test_research_cli_plan_accepts_max_requests_budget(capsys):
    code = main(
        [
            "research",
            "plan",
            "--search",
            "--query",
            "agent browser modules",
            "--provider",
            "ddg-html",
            "--variant",
            "docs",
            "--variant",
            "reddit",
            "--max-requests",
            "1",
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["request"]["max_cost"]["requests"] == 1
    assert payload["policy"]["source_hint_count_before_budget"] == 3
    assert payload["policy"]["source_hint_count_after_budget"] == 1
    assert payload["policy"]["source_hint_budget_limited"] is True
    assert payload["source_hints_used"] == ["search:ddg_html:agent browser modules"]


def test_research_armory_reports_readiness_without_secret_values(monkeypatch):
    monkeypatch.setenv("AGENTLAS_STAGEHAND_SNAPSHOT_CMD", "stagehand --api-key secret-stagehand")
    monkeypatch.setenv("AGENTLAS_JINA_API_KEY", "secret-jina")
    monkeypatch.delenv("AGENTLAS_AGENT_BROWSER_BIN", raising=False)
    monkeypatch.setattr("agentlas_cloud.research.armory.shutil.which", lambda name: None)

    payload = run_research_armory(loadout="full")

    assert payload["schema"] == "agentlas.research.armory.v0"
    assert payload["commands_will_run"] is False
    assert payload["network_will_run"] is False
    modules = {item["id"]: item for item in payload["modules"]}
    assert payload["slot_counts"]["browser"] == 7
    assert payload["mounted_slot_counts"]["browser"] == 7
    assert payload["mounted_slot_counts"]["platform"] == 4
    assert modules["search.jina"]["readiness"]["state"] == "ready"
    assert modules["browser.stagehand"]["readiness"]["state"] == "ready"
    assert modules["browser.hyperagent"]["readiness"]["state"] == "needs_config"
    assert modules["browser.browseros"]["readiness"]["state"] == "needs_config"
    assert modules["browser.agent_cli"]["readiness"]["state"] == "needs_binary"
    assert "secret-jina" not in str(payload)
    assert "secret-stagehand" not in str(payload)


def test_research_cli_armory_filters_browser_slot(monkeypatch, capsys):
    monkeypatch.setenv("AGENTLAS_STAGEHAND_SNAPSHOT_CMD", "stagehand --token secret-stagehand")
    monkeypatch.setattr("agentlas_cloud.research.armory.shutil.which", lambda name: None)

    code = main(["research", "armory", "--loadout", "browser", "--slot", "browser"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "agentlas.research.armory.v0"
    assert payload["slot"] == "browser"
    assert payload["slot_counts"] == {"browser": 7}
    assert payload["mounted_slot_counts"] == {"browser": 7}
    assert all(item["slot"] == "browser" for item in payload["modules"])
    modules = {item["id"]: item for item in payload["modules"]}
    assert modules["browser.stagehand"]["in_loadout"] is True
    assert modules["browser.stagehand"]["readiness"]["state"] == "ready"
    assert modules["browser.hyperagent"]["in_loadout"] is True
    assert modules["browser.hyperagent"]["readiness"]["state"] == "needs_config"
    assert "secret-stagehand" not in str(payload)


def test_research_armory_auto_marks_public_web_default():
    payload = run_research_armory(loadout="auto")
    modules = {item["id"]: item for item in payload["modules"]}

    assert payload["loadout"]["status"] == "source_aware_default"
    assert modules["read.http"]["in_loadout"] is True
    assert modules["read.insane_fetch"]["in_loadout"] is False
    assert modules["browser.stagehand"]["in_loadout"] is False


def test_research_profile_compares_loadout_footprints(monkeypatch):
    clear_reddit_oauth_env(monkeypatch)
    monkeypatch.delenv("AGENTLAS_THREADS_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("THREADS_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("AGENTLAS_STAGEHAND_SNAPSHOT_CMD", raising=False)
    monkeypatch.setattr("agentlas_cloud.research.armory.shutil.which", lambda name: None)
    monkeypatch.setattr("agentlas_cloud.research.armory.active_hardpoint_summary", lambda *args, **kwargs: {"enabled": False})

    payload = run_research_profile()

    assert payload["schema"] == "agentlas.research.profile.v0"
    assert payload["commands_will_run"] is False
    assert payload["network_will_run"] is False
    profiles = {item["name"]: item for item in payload["profiles"]}
    assert profiles["auto"]["footprint"]["browser_module_count"] == 0
    assert profiles["auto"]["boundaries"]["browser_requires_explicit_loadout_or_allow"] is True
    assert profiles["auto"]["operator_summary"]["posture"] == "source_aware_light_default"
    assert profiles["auto"]["operator_summary"]["heavy_modules_detached"] is True
    assert profiles["browser"]["footprint"]["browser_module_count"] == 7
    assert profiles["browser"]["footprint"]["mounted_slot_counts"]["browser"] == 7
    assert profiles["browser"]["footprint"]["heaviest_mounted_weight"] == "browser_heavy"
    assert profiles["browser"]["operator_summary"]["posture"] == "browser_heavy"
    assert profiles["browser"]["operator_summary"]["operator_approval_recommended"] is True
    assert any(
        action["action"] == "configure_browser_hardpoint"
        for action in profiles["browser"]["operator_summary"]["next_actions"]
    )
    assert profiles["social"]["operator_summary"]["missing_credential_modules"] == [
        "platform.reddit.oauth",
        "platform.threads",
    ]
    assert profiles["full"]["footprint"]["mounted_module_count"] > profiles["safe"]["footprint"]["mounted_module_count"]


def test_research_profile_auto_is_source_aware_for_threads(monkeypatch):
    monkeypatch.delenv("AGENTLAS_THREADS_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("THREADS_ACCESS_TOKEN", raising=False)

    payload = run_research_profile(loadout="auto", source_hints=["threads:keyword:agent browser"])

    profile = payload["profiles"][0]
    mounted_ids = {item["id"] for item in profile["mounted_modules"]}
    assert profile["name"] == "auto"
    assert "platform.threads" not in mounted_ids
    assert "platform.threads.public" in mounted_ids
    assert profile["operator_summary"]["posture"] == "adaptive_public"
    assert profile["operator_summary"]["missing_credential_modules"] == []
    assert profile["footprint"]["source_hints_considered"] == ["threads:keyword:agent browser"]
    assert profile["footprint"]["unready_mounted_module_count"] == 0


def test_research_recommendation_auto_selects_agent_browser_for_browser_work(tmp_path, monkeypatch):
    monkeypatch.delenv("AGENTLAS_STAGEHAND_SNAPSHOT_CMD", raising=False)
    monkeypatch.setattr("agentlas_cloud.research.armory.shutil.which", lambda name: None)

    payload = run_research_recommendation(
        query="agent browser modules 찾아봐",
        home=tmp_path,
    )

    assert payload["schema"] == "agentlas.research.recommendation.v0"
    assert payload["commands_will_run"] is False
    assert payload["network_will_run"] is False
    assert payload["recommendation"]["loadout"] == "browser"
    assert "agentlas_browser_hardpoint_auto_selected" in payload["recommendation"]["reasons"]
    assert payload["recommendation"]["suggested_command"].startswith("bin/hep-browser '<query>'")
    assert payload["recommendation"]["mount_decision"]["browser_hardpoints"] == "mounted"
    assert payload["recommendation"]["mount_decision"]["adaptive_public_reader"] == "mounted"
    assert payload["recommendation"]["mount_decision"]["operator_approval_recommended"] is True
    assert payload["footprint"]["browser_module_count"] == 7
    profile_modules = [module["id"] for module in payload["loadout_profile"]["mounted_modules"]]
    assert profile_modules.index("browser.agent_cli") < profile_modules.index("browser.playwright_mcp")
    assert "read.insane_fetch" in set(profile_modules)


def test_research_recommendation_prefers_public_social_without_api(monkeypatch):
    monkeypatch.delenv("AGENTLAS_THREADS_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("THREADS_ACCESS_TOKEN", raising=False)
    clear_reddit_oauth_env(monkeypatch)

    payload = run_research_recommendation(query="Threads와 Reddit 반응까지 조사")

    assert payload["recommendation"]["loadout"] == "public-web"
    assert payload["recommendation"]["query_variants"] == ["reddit", "threads"]
    assert "public_social_research_requested" in payload["recommendation"]["reasons"]
    assert "official_social_apis_not_mounted_by_default" in payload["recommendation"]["reasons"]
    assert payload["recommendation"]["mount_decision"]["credentialed_social"] == "detached"
    assert payload["recommendation"]["mount_decision"]["public_social_fallbacks"] == "mounted"
    assert payload["recommendation"]["mount_decision"]["browser_hardpoints"] == "detached"
    selected = [item for item in payload["boundaries"]["operator_can_escalate"] if item["selected"]]
    assert selected == [{"loadout": "public-web", "use_when": "blocked public pages, feeds, metadata, and adaptive public fallback", "selected": True}]
    mounted = payload["plan_preview"]["mounted_modules"]
    assert "platform.reddit.oauth" not in mounted
    assert "platform.threads" not in mounted
    profile_mounted = {module["id"] for module in payload["loadout_profile"]["mounted_modules"]}
    assert "platform.reddit" in profile_mounted
    assert "platform.threads.public" in profile_mounted
    assert not any(module.startswith("browser.") for module in mounted)
    assert payload["boundaries"]["recommended_avoids_social_api_tokens"] is True


def test_research_preflight_recommended_uses_public_social_without_api(monkeypatch):
    monkeypatch.delenv("AGENTLAS_THREADS_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("THREADS_ACCESS_TOKEN", raising=False)
    clear_reddit_oauth_env(monkeypatch)

    payload = run_research_preflight(query="Threads와 Reddit 반응까지 조사")

    assert payload["requested_loadout"] == "recommended"
    assert payload["resolved_loadout"] == "public-web"
    assert payload["recommendation"]["query_variants"] == ["reddit", "threads"]
    mounted_ids = {module["id"] for module in payload["mounted_modules"]}
    assert "platform.reddit.oauth" not in mounted_ids
    assert "platform.threads" not in mounted_ids
    assert "platform.reddit" in mounted_ids
    assert "platform.threads.public" in mounted_ids
    assert "read.insane_fetch" in mounted_ids
    assert payload["mount_decision"]["credentialed_social"] == "detached"
    assert payload["mount_decision"]["public_social_fallbacks"] == "mounted"
    assert payload["mount_decision"]["readiness"] == "ready_or_optional"
    assert payload["readiness_blockers"] == []
    assert not any(hint.startswith("reddit:search:") for hint in payload["plan_preview"]["source_hints_before_budget"])
    assert not any(hint.startswith("threads:keyword:") for hint in payload["plan_preview"]["source_hints_before_budget"])


def test_research_preflight_recommended_mounts_agent_browser_for_browser_work(tmp_path, monkeypatch):
    monkeypatch.setattr("agentlas_cloud.research.armory.shutil.which", lambda name: None)

    payload = run_research_preflight(query="agent browser modules 찾아봐", home=tmp_path)

    assert payload["schema"] == "agentlas.research.preflight.v0"
    assert payload["commands_will_run"] is False
    assert payload["network_will_run"] is False
    assert payload["browser_will_run"] is False
    assert payload["requested_loadout"] == "recommended"
    assert payload["resolved_loadout"] == "browser"
    assert payload["summary"]["browser_modules_mounted"] is True
    assert payload["summary"]["browser_module_count"] == 7
    assert payload["slot_summary"]["browser"]["mounted_count"] == 7
    assert payload["slot_summary"]["browser"]["detached_count"] == 0
    assert payload["recommendation"]["mount_decision"]["browser_hardpoints"] == "mounted"
    assert payload["mount_decision"]["source"] == "recommendation"
    assert payload["mount_decision"]["browser_hardpoints"] == "mounted"
    assert payload["mount_decision"]["adaptive_public_reader"] == "mounted"
    assert payload["mount_decision"]["operator_approval_recommended"] is True
    mounted_ids = {module["id"] for module in payload["mounted_modules"]}
    assert "read.insane_fetch" in mounted_ids
    assert "browser.agent_cli" in mounted_ids
    assert payload["boundaries"]["heavy_modules_are_detachable"] is True


def test_research_preflight_social_mounts_social_without_browser(monkeypatch):
    monkeypatch.delenv("AGENTLAS_THREADS_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("THREADS_ACCESS_TOKEN", raising=False)
    clear_reddit_oauth_env(monkeypatch)

    payload = run_research_preflight(query="Threads와 Reddit 반응까지 조사", loadout="social")

    assert payload["resolved_loadout"] == "social"
    assert payload["recommendation"] is None
    mounted_ids = {module["id"] for module in payload["mounted_modules"]}
    assert "platform.reddit.oauth" in mounted_ids
    assert "platform.reddit" in mounted_ids
    assert "platform.threads" in mounted_ids
    assert "platform.threads.public" in mounted_ids
    assert not any(module_id.startswith("browser.") for module_id in mounted_ids)
    assert payload["summary"]["browser_modules_mounted"] is False
    assert payload["mount_decision"]["credentialed_social"] == "mounted"
    assert payload["mount_decision"]["public_social_fallbacks"] == "mounted"
    assert payload["mount_decision"]["browser_hardpoints"] == "detached"
    assert payload["mount_decision"]["readiness"] == "blocked_by_config"
    assert any(hint.startswith("reddit:search:") for hint in payload["plan_preview"]["source_hints_before_budget"])
    assert any(hint.startswith("threads:keyword:") for hint in payload["plan_preview"]["source_hints_before_budget"])
    blockers = {item["id"]: item for item in payload["readiness_blockers"]}
    assert blockers["platform.reddit.oauth"]["missing_env"] == ["AGENTLAS_REDDIT_BEARER_TOKEN", "REDDIT_BEARER_TOKEN"]
    assert [
        "AGENTLAS_REDDIT_CLIENT_ID",
        "AGENTLAS_REDDIT_CLIENT_SECRET",
    ] in blockers["platform.reddit.oauth"]["accepted_env_sets"]
    assert blockers["platform.threads"]["missing_env"] == ["AGENTLAS_THREADS_ACCESS_TOKEN", "THREADS_ACCESS_TOKEN"]
    assert payload["boundaries"]["social_credentials_checked_by_readiness_not_exposed"] is True


def test_research_cli_preflight_reports_browser_loadout_without_running(capsys):
    code = main(["research", "preflight", "403", "blocked", "dynamic", "browser", "page"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "agentlas.research.preflight.v0"
    assert payload["resolved_loadout"] == "browser"
    assert payload["summary"]["browser_modules_mounted"] is True
    assert payload["slot_summary"]["browser"]["mounted_count"] == 7
    assert payload["browser_will_run"] is False
    assert payload["commands_will_run"] is False


def test_research_cli_recommend_reports_browser_escalation(capsys):
    code = main(["research", "recommend", "403", "blocked", "dynamic", "browser", "page"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "agentlas.research.recommendation.v0"
    assert payload["recommendation"]["loadout"] == "browser"
    assert payload["recommendation"]["depth"] == "deep"
    assert "browser_escalation_requested_for_blocked_or_dynamic_page" in payload["recommendation"]["reasons"]
    assert payload["footprint"]["browser_module_count"] == 7


def test_research_doctor_reports_readiness_and_missing_live_proofs(tmp_path, monkeypatch):
    monkeypatch.delenv("AGENTLAS_THREADS_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("THREADS_ACCESS_TOKEN", raising=False)
    clear_reddit_oauth_env(monkeypatch)
    monkeypatch.setattr("agentlas_cloud.research.armory.shutil.which", lambda name: None)

    payload = run_research_doctor(home=tmp_path)

    assert payload["schema"] == "agentlas.research.doctor.v0"
    assert payload["status"] == "partial"
    assert payload["commands_will_run"] is False
    assert payload["network_will_run"] is False
    assert payload["credentials_exposed_to_model"] is False
    checks = {item["id"]: item for item in payload["checks"]}
    assert checks["core_registry"]["status"] == "ok"
    assert checks["auto_loadout_boundary"]["status"] == "ok"
    assert checks["browser_modularity"]["status"] == "ok"
    assert checks["web_search_recall"]["status"] == "ok"
    assert checks["evidence_quality"]["status"] == "ok"
    assert checks["reddit_public_fallback"]["status"] == "ok"
    assert checks["threads_public_fallback"]["status"] == "ok"
    assert checks["threads_public_fallback"]["evidence"]["keyword_web_search_fallback_modules"] == ["search.ddg_html", "search.news_rss"]
    assert checks["platform.threads"]["status"] == "needs_config"
    assert checks["platform.reddit.oauth"]["status"] == "needs_config"
    assert checks["browser_hardpoints"]["status"] == "needs_config"
    assert payload["completion"]["goal_ready"] is False
    assert payload["completion"]["public_social_fallbacks_ok"] is True
    assert payload["completion"]["credentialed_social_ok"] is False
    assert payload["completion"]["browser_hardpoint_ok"] is False
    assert payload["coverage"]["public_social_fallbacks_ok"] is True
    assert payload["coverage"]["credentialed_social_missing"] == [
        "platform.reddit.oauth",
        "platform.threads",
    ]
    assert payload["coverage"]["browser_hardpoint_status"] == "needs_config"
    assert payload["completion"]["incomplete_checks"]
    assert set(payload["completion"]["missing_proofs"]) == {
        "reddit_oauth_live_check",
        "threads_live_graph_check",
        "browser_hardpoint_live_check",
    }
    assert set(payload["completion"]["missing_or_unready_proofs"]) == {
        "reddit_oauth_live_check",
        "threads_live_graph_check",
        "browser_hardpoint_live_check",
    }
    assert any("platform-check --module platform.threads" in command for command in payload["next_commands"])
    assert any("bridge-check --module browser.agent_cli" in command for command in payload["next_commands"])


def test_research_doctor_recommends_ready_browser_hardpoint(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTLAS_STAGEHAND_SNAPSHOT_CMD", "stagehand-snapshot {url}")
    monkeypatch.delenv("AGENTLAS_PLAYWRIGHT_MCP_SNAPSHOT_CMD", raising=False)
    monkeypatch.delenv("AGENTLAS_BROWSER_USE_SNAPSHOT_CMD", raising=False)
    monkeypatch.delenv("AGENTLAS_STEEL_SNAPSHOT_CMD", raising=False)
    monkeypatch.delenv("AGENTLAS_HYPERAGENT_SNAPSHOT_CMD", raising=False)
    monkeypatch.delenv("AGENTLAS_BROWSEROS_SNAPSHOT_CMD", raising=False)
    monkeypatch.delenv("AGENTLAS_AGENT_BROWSER_BIN", raising=False)
    monkeypatch.setattr("agentlas_cloud.research.armory.shutil.which", lambda name: None)

    payload = run_research_doctor(home=tmp_path)
    checks = {item["id"]: item for item in payload["checks"]}

    assert checks["browser_hardpoints"]["status"] == "needs_live_proof"
    assert checks["browser_hardpoints"]["evidence"]["ready_modules"] == ["browser.stagehand"]
    assert checks["browser_hardpoints"]["check_command"] == "bin/hephaestus research bridge-check --module browser.stagehand --url https://example.com"
    assert "bin/hephaestus research bridge-check --module browser.stagehand --url https://example.com" in payload["next_commands"]


def test_research_doctor_accepts_live_proof_receipts(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTLAS_THREADS_ACCESS_TOKEN", "test-threads-token")
    monkeypatch.setenv("AGENTLAS_REDDIT_BEARER_TOKEN", "test-reddit-token")
    monkeypatch.setattr("agentlas_cloud.research.armory.shutil.which", lambda name: "/usr/local/bin/agent-browser" if name == "agent-browser" else None)
    ledger = tmp_path / "ledgers" / "research-receipts.jsonl"
    for record in (
        {
            "ts": utc_now(),
            "receipt_id": "research_reddit_oauth",
            "request_hash": "hash_reddit",
            "module_chain": ["platform.reddit.oauth"],
            "attempts": [{"module": "platform.reddit.oauth", "status": "ok", "reason": "oauth_read"}],
            "policy": {},
        },
        {
            "ts": utc_now(),
            "receipt_id": "research_threads",
            "request_hash": "hash_threads",
            "module_chain": ["platform.threads"],
            "attempts": [{"module": "platform.threads", "status": "ok", "reason": "keyword_search"}],
            "policy": {},
        },
        {
            "ts": utc_now(),
            "receipt_id": "research_browser",
            "request_hash": "hash_browser",
            "module_chain": ["browser.agent_cli"],
            "attempts": [{"module": "browser.agent_cli", "status": "ok", "reason": "agent_browser_snapshot"}],
            "policy": {"browser_execution": {"status": "used"}},
        },
    ):
        append_jsonl(ledger, record)

    payload = run_research_doctor(home=tmp_path)

    assert payload["status"] == "ok"
    assert payload["completion"]["goal_ready"] is True
    assert payload["completion"]["missing_proofs"] == []
    assert payload["completion"]["missing_or_unready_proofs"] == []
    assert payload["completion"]["incomplete_checks"] == []
    assert payload["completion"]["credentialed_social_ok"] is True
    assert payload["completion"]["browser_hardpoint_ok"] is True
    assert payload["coverage"]["goal_blocked_by"] == []
    checks = {item["id"]: item for item in payload["checks"]}
    assert checks["platform.reddit.oauth"]["status"] == "ok"
    assert checks["platform.threads"]["status"] == "ok"
    assert checks["browser_hardpoints"]["status"] == "ok"
    assert payload["live_proofs"]["reddit_oauth_live_check"]["receipt_id"] == "research_reddit_oauth"
    assert payload["live_proofs"]["threads_live_graph_check"]["receipt_id"] == "research_threads"
    assert payload["live_proofs"]["browser_hardpoint_live_check"]["receipt_id"] == "research_browser"
    assert "test-threads-token" not in str(payload)
    assert "test-reddit-token" not in str(payload)


def test_research_doctor_and_proofs_reject_stale_live_proof_receipts(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTLAS_THREADS_ACCESS_TOKEN", "test-threads-token")
    monkeypatch.setenv("AGENTLAS_REDDIT_BEARER_TOKEN", "test-reddit-token")
    monkeypatch.setattr("agentlas_cloud.research.armory.shutil.which", lambda name: "/usr/local/bin/agent-browser" if name == "agent-browser" else None)
    ledger = tmp_path / "ledgers" / "research-receipts.jsonl"
    for record in (
        {
            "ts": "2000-01-01T00:00:00+00:00",
            "receipt_id": "research_old_reddit_oauth",
            "request_hash": "hash_old_reddit",
            "module_chain": ["platform.reddit.oauth"],
            "attempts": [{"module": "platform.reddit.oauth", "status": "ok", "reason": "oauth_read"}],
            "policy": {},
        },
        {
            "ts": "2000-01-01T00:00:00+00:00",
            "receipt_id": "research_old_threads",
            "request_hash": "hash_old_threads",
            "module_chain": ["platform.threads"],
            "attempts": [{"module": "platform.threads", "status": "ok", "reason": "keyword_search"}],
            "policy": {},
        },
        {
            "ts": "2000-01-01T00:00:00+00:00",
            "receipt_id": "research_old_browser",
            "request_hash": "hash_old_browser",
            "module_chain": ["browser.agent_cli"],
            "attempts": [{"module": "browser.agent_cli", "status": "ok", "reason": "agent_browser_snapshot"}],
            "policy": {"browser_execution": {"status": "used"}},
        },
    ):
        append_jsonl(ledger, record)

    proofs_payload = run_research_proofs(home=tmp_path)
    proof_states = {item["id"]: item for item in proofs_payload["required_proofs"]}

    assert proofs_payload["status"] == "partial"
    assert proofs_payload["completion"]["goal_ready"] is False
    assert proof_states["reddit_oauth_live_check"]["status"] == "stale_live_proof"
    assert proof_states["threads_live_graph_check"]["status"] == "stale_live_proof"
    assert proof_states["browser_hardpoint_live_check"]["status"] == "stale_live_proof"
    assert proof_states["threads_live_graph_check"]["live_proof"]["freshness"]["status"] == "stale"
    assert set(proofs_payload["completion"]["stale_or_unknown_proofs"]) == {
        "reddit_oauth_live_check",
        "threads_live_graph_check",
        "browser_hardpoint_live_check",
    }
    assert proofs_payload["coverage"]["required_ok"] == []

    doctor_payload = run_research_doctor(home=tmp_path)
    doctor_checks = {item["id"]: item for item in doctor_payload["checks"]}

    assert doctor_payload["status"] == "partial"
    assert doctor_payload["completion"]["goal_ready"] is False
    assert doctor_checks["platform.reddit.oauth"]["status"] == "stale_live_proof"
    assert doctor_checks["platform.threads"]["status"] == "stale_live_proof"
    assert doctor_checks["browser_hardpoints"]["status"] == "stale_live_proof"
    assert set(doctor_payload["completion"]["stale_or_unknown_proofs"]) == {
        "reddit_oauth_live_check",
        "threads_live_graph_check",
        "browser_hardpoint_live_check",
    }


def test_research_cli_doctor(tmp_path, capsys):
    code = main(["research", "doctor", "--home", str(tmp_path)])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "agentlas.research.doctor.v0"
    assert "completion" in payload
    assert "next_commands" in payload


def test_research_status_summarizes_goal_readiness(tmp_path, monkeypatch):
    monkeypatch.delenv("AGENTLAS_THREADS_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("THREADS_ACCESS_TOKEN", raising=False)
    clear_reddit_oauth_env(monkeypatch)
    monkeypatch.setattr("agentlas_cloud.research.armory.shutil.which", lambda name: None)

    payload = run_research_status(home=tmp_path)

    assert payload["schema"] == "agentlas.research.status.v0"
    assert payload["status"] == "partial"
    assert payload["goal_ready"] is False
    assert payload["commands_will_run"] is False
    assert payload["network_will_run"] is False
    assert payload["credentials_exposed_to_model"] is False
    assert payload["summary"]["core_engine_ok"] is True
    assert payload["summary"]["public_social_fallbacks_ok"] is True
    assert payload["summary"]["browser_hardpoint_ok"] is False
    assert payload["summary"]["credentialed_social_ok"] is False
    assert payload["summary"]["official_social_missing"] == [
        "platform.reddit.oauth",
        "platform.threads",
    ]
    requirements = {item["id"]: item for item in payload["requirements"]}
    assert requirements["core_registry"]["status"] == "ok"
    assert requirements["auto_loadout_boundary"]["status"] == "ok"
    assert requirements["platform.reddit.oauth"]["status"] == "needs_config"
    assert requirements["platform.threads"]["status"] == "needs_config"
    assert requirements["browser_hardpoints"]["status"] == "needs_config"
    assert requirements["credential_safety"]["status"] == "ok"
    assert requirements["platform.reddit.oauth"]["setup"]["missing_env"] == [
        "AGENTLAS_REDDIT_BEARER_TOKEN",
        "REDDIT_BEARER_TOKEN",
    ]
    assert [
        "AGENTLAS_REDDIT_CLIENT_ID",
        "AGENTLAS_REDDIT_CLIENT_SECRET",
    ] in requirements["platform.reddit.oauth"]["setup"]["accepted_env_sets"]
    assert requirements["platform.threads"]["setup"]["missing_env"] == [
        "AGENTLAS_THREADS_ACCESS_TOKEN",
        "THREADS_ACCESS_TOKEN",
    ]
    assert requirements["platform.reddit.oauth"]["setup"]["secret_values_exposed"] is False
    assert requirements["platform.threads"]["setup"]["secret_values_exposed"] is False
    assert "AGENTLAS_REDDIT_BEARER_TOKEN" in payload["summary"]["missing_env"]
    assert "AGENTLAS_THREADS_ACCESS_TOKEN" in payload["summary"]["missing_env"]
    assert "AGENTLAS_AGENT_BROWSER_BIN" in payload["summary"]["missing_env"]
    assert any("platform-check --module platform.threads" in command for command in payload["next_commands"])


def test_research_credentials_reports_missing_env_without_secret_values(tmp_path, monkeypatch):
    monkeypatch.delenv("AGENTLAS_THREADS_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("THREADS_ACCESS_TOKEN", raising=False)
    clear_reddit_oauth_env(monkeypatch)

    payload = run_research_credentials(home=tmp_path)

    assert payload["schema"] == "agentlas.research.credentials.v0"
    assert payload["commands_will_run"] is False
    assert payload["network_will_run"] is False
    assert payload["credentials_exposed_to_model"] is False
    providers = {item["id"]: item for item in payload["providers"]}
    assert providers["reddit_oauth"]["status"] == "needs_config"
    assert providers["reddit_oauth"]["missing_env"] == ["AGENTLAS_REDDIT_BEARER_TOKEN", "REDDIT_BEARER_TOKEN"]
    assert [
        "AGENTLAS_REDDIT_CLIENT_ID",
        "AGENTLAS_REDDIT_CLIENT_SECRET",
    ] in providers["reddit_oauth"]["env_alternatives"]
    assert providers["reddit_oauth"]["minimum_permissions"] == ["read"]
    assert providers["threads_graph"]["status"] == "needs_config"
    assert providers["threads_graph"]["missing_env"] == ["AGENTLAS_THREADS_ACCESS_TOKEN", "THREADS_ACCESS_TOKEN"]
    assert providers["threads_graph"]["minimum_permissions"] == ["threads_basic", "threads_keyword_search"]
    assert "export AGENTLAS_REDDIT_BEARER_TOKEN='<OAuth2 bearer token>'" in payload["next_commands"]
    assert "export AGENTLAS_REDDIT_CLIENT_ID='<Reddit app client id>'" in payload["next_commands"]
    assert "export AGENTLAS_REDDIT_CLIENT_SECRET='<Reddit app client secret>'" in payload["next_commands"]
    assert "export AGENTLAS_THREADS_ACCESS_TOKEN='<Meta Threads access token>'" in payload["next_commands"]
    assert payload["safety"]["prints_token_values"] is False


def test_research_credentials_redacts_present_secret_values(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTLAS_REDDIT_BEARER_TOKEN", "reddit-secret-should-not-appear")
    monkeypatch.setenv("AGENTLAS_THREADS_ACCESS_TOKEN", "threads-secret-should-not-appear")

    payload = run_research_credentials(home=tmp_path)
    encoded = json.dumps(payload, sort_keys=True)

    assert "reddit-secret-should-not-appear" not in encoded
    assert "threads-secret-should-not-appear" not in encoded
    providers = {item["id"]: item for item in payload["providers"]}
    assert providers["reddit_oauth"]["present_env"] == ["AGENTLAS_REDDIT_BEARER_TOKEN"]
    assert providers["reddit_oauth"]["missing_env"] == []
    assert providers["reddit_oauth"]["status"] == "needs_live_proof"
    assert providers["threads_graph"]["present_env"] == ["AGENTLAS_THREADS_ACCESS_TOKEN"]
    assert providers["threads_graph"]["missing_env"] == []
    assert providers["threads_graph"]["status"] == "needs_live_proof"
    assert all(not command.startswith("export ") for command in payload["next_commands"])


def test_research_credentials_accepts_reddit_app_only_env_pair(tmp_path, monkeypatch):
    clear_reddit_oauth_env(monkeypatch)
    monkeypatch.setenv("AGENTLAS_REDDIT_CLIENT_ID", "client-id-secret")
    monkeypatch.setenv("AGENTLAS_REDDIT_CLIENT_SECRET", "client-secret-secret")

    payload = run_research_credentials(home=tmp_path)
    encoded = json.dumps(payload, sort_keys=True)

    providers = {item["id"]: item for item in payload["providers"]}
    assert providers["reddit_oauth"]["status"] == "needs_live_proof"
    assert providers["reddit_oauth"]["present_env"] == [
        "AGENTLAS_REDDIT_CLIENT_ID",
        "AGENTLAS_REDDIT_CLIENT_SECRET",
    ]
    assert providers["reddit_oauth"]["missing_env"] == []
    assert "client-id-secret" not in encoded
    assert "client-secret-secret" not in encoded


def test_research_cli_credentials(capsys, tmp_path, monkeypatch):
    monkeypatch.delenv("AGENTLAS_THREADS_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("THREADS_ACCESS_TOKEN", raising=False)
    clear_reddit_oauth_env(monkeypatch)

    code = main(["research", "credentials", "--home", str(tmp_path)])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "agentlas.research.credentials.v0"
    assert payload["summary"]["secret_values_exposed"] is False
    assert payload["summary"]["missing_provider_ids"] == ["reddit_oauth", "threads_graph"]


def test_research_status_accepts_complete_live_proof_receipts(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTLAS_THREADS_ACCESS_TOKEN", "test-threads-token")
    monkeypatch.setenv("AGENTLAS_REDDIT_BEARER_TOKEN", "test-reddit-token")
    monkeypatch.setattr("agentlas_cloud.research.armory.shutil.which", lambda name: "/usr/local/bin/agent-browser" if name == "agent-browser" else None)
    ledger = tmp_path / "ledgers" / "research-receipts.jsonl"
    for record in (
        {
            "ts": utc_now(),
            "receipt_id": "research_reddit_oauth",
            "request_hash": "hash_reddit",
            "module_chain": ["platform.reddit.oauth"],
            "attempts": [{"module": "platform.reddit.oauth", "status": "ok", "reason": "oauth_read"}],
            "policy": {},
        },
        {
            "ts": utc_now(),
            "receipt_id": "research_threads",
            "request_hash": "hash_threads",
            "module_chain": ["platform.threads"],
            "attempts": [{"module": "platform.threads", "status": "ok", "reason": "keyword_search"}],
            "policy": {},
        },
        {
            "ts": utc_now(),
            "receipt_id": "research_browser",
            "request_hash": "hash_browser",
            "module_chain": ["browser.agent_cli"],
            "attempts": [{"module": "browser.agent_cli", "status": "ok", "reason": "agent_browser_snapshot"}],
            "policy": {"browser_execution": {"status": "used"}},
        },
    ):
        append_jsonl(ledger, record)

    payload = run_research_status(home=tmp_path)

    assert payload["status"] == "ok"
    assert payload["goal_ready"] is True
    assert payload["summary"]["credentialed_social_ok"] is True
    assert payload["summary"]["browser_hardpoint_ok"] is True
    assert payload["summary"]["missing_or_unready_proofs"] == []
    assert payload["summary"]["missing_env"] == []
    assert all(item["status"] == "ok" for item in payload["requirements"])
    assert all("setup" not in item for item in payload["requirements"])
    assert "test-threads-token" not in str(payload)
    assert "test-reddit-token" not in str(payload)


def test_research_cli_status(tmp_path, capsys):
    code = main(["research", "status", "--home", str(tmp_path)])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "agentlas.research.status.v0"
    assert "requirements" in payload
    assert "next_commands" in payload


def test_research_proofs_reports_receipts_and_readiness(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTLAS_THREADS_ACCESS_TOKEN", "secret-threads-token")
    clear_reddit_oauth_env(monkeypatch)
    monkeypatch.setattr("agentlas_cloud.research.armory.shutil.which", lambda name: "/usr/local/bin/agent-browser" if name == "agent-browser" else None)
    ledger = tmp_path / "ledgers" / "research-receipts.jsonl"
    append_jsonl(
        ledger,
        {
            "ts": utc_now(),
            "receipt_id": "research_threads",
            "request_hash": "hash_threads",
            "module_chain": ["platform.threads"],
            "attempts": [{"module": "platform.threads", "status": "ok", "reason": "keyword_search"}],
            "policy": {},
        },
    )
    append_jsonl(
        ledger,
        {
            "ts": utc_now(),
            "receipt_id": "research_browser",
            "request_hash": "hash_browser",
            "module_chain": ["browser.agent_cli"],
            "attempts": [{"module": "browser.agent_cli", "status": "ok", "reason": "agent_browser_snapshot"}],
            "policy": {"browser_execution": {"status": "used"}},
        },
    )

    payload = run_research_proofs(home=tmp_path)

    assert payload["schema"] == "agentlas.research.proofs.v0"
    assert payload["status"] == "partial"
    assert payload["commands_will_run"] is False
    assert payload["network_will_run"] is False
    assert payload["credentials_exposed_to_model"] is False
    proofs = {item["id"]: item for item in payload["required_proofs"]}
    assert proofs["threads_live_graph_check"]["status"] == "ok"
    assert proofs["browser_hardpoint_live_check"]["status"] == "ok"
    assert proofs["reddit_oauth_live_check"]["status"] == "needs_config"
    assert proofs["threads_live_graph_check"]["live_proof"]["receipt_id"] == "research_threads"
    assert payload["completion"]["missing_or_unready_proofs"] == ["reddit_oauth_live_check"]
    assert payload["completion"]["satisfied_required_proofs"] == [
        "threads_live_graph_check",
        "browser_hardpoint_live_check",
    ]
    assert payload["coverage"]["required_ok"] == [
        "threads_live_graph_check",
        "browser_hardpoint_live_check",
    ]
    assert payload["coverage"]["credentialed_missing_config"] == ["reddit_oauth_live_check"]
    assert payload["coverage"]["browser_hardpoint_ok"] is True
    assert any(item["proof_id"] == "browser_hardpoint_live_check" for item in payload["recent_receipts"])
    assert "secret-threads-token" not in str(payload)


def test_research_proofs_recommends_ready_browser_hardpoint(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTLAS_STAGEHAND_SNAPSHOT_CMD", "stagehand-snapshot {url}")
    monkeypatch.delenv("AGENTLAS_PLAYWRIGHT_MCP_SNAPSHOT_CMD", raising=False)
    monkeypatch.delenv("AGENTLAS_BROWSER_USE_SNAPSHOT_CMD", raising=False)
    monkeypatch.delenv("AGENTLAS_STEEL_SNAPSHOT_CMD", raising=False)
    monkeypatch.delenv("AGENTLAS_HYPERAGENT_SNAPSHOT_CMD", raising=False)
    monkeypatch.delenv("AGENTLAS_BROWSEROS_SNAPSHOT_CMD", raising=False)
    monkeypatch.delenv("AGENTLAS_AGENT_BROWSER_BIN", raising=False)
    monkeypatch.setattr("agentlas_cloud.research.armory.shutil.which", lambda name: None)

    payload = run_research_proofs(home=tmp_path)
    proofs = {item["id"]: item for item in payload["required_proofs"]}

    assert proofs["browser_hardpoint_live_check"]["status"] == "needs_live_proof"
    assert proofs["browser_hardpoint_live_check"]["readiness"]["ready_modules"] == ["browser.stagehand"]
    assert proofs["browser_hardpoint_live_check"]["check_command"] == "bin/hephaestus research bridge-check --module browser.stagehand --url https://example.com"
    assert "bin/hephaestus research bridge-check --module browser.stagehand --url https://example.com" in payload["next_commands"]


def test_research_proofs_rejects_failed_platform_receipt_as_live_proof(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTLAS_THREADS_ACCESS_TOKEN", "secret-threads-token")
    ledger = tmp_path / "ledgers" / "research-receipts.jsonl"
    append_jsonl(
        ledger,
        {
            "ts": utc_now(),
            "receipt_id": "research_failed_threads",
            "request_hash": "hash_failed_threads",
            "module_chain": ["platform.threads"],
            "attempts": [{"module": "platform.threads", "status": "module_unavailable", "reason": "THREADS_ACCESS_TOKEN not configured"}],
            "policy": {},
        },
    )

    payload = run_research_proofs(home=tmp_path)

    proofs = {item["id"]: item for item in payload["required_proofs"]}
    assert proofs["threads_live_graph_check"]["status"] == "needs_live_proof"
    assert proofs["threads_live_graph_check"]["live_proof"] is None
    assert payload["recent_receipts"][0]["proof_id"] == ""


def test_research_proofs_reports_public_social_fallback_proofs(tmp_path, monkeypatch):
    clear_reddit_oauth_env(monkeypatch)
    monkeypatch.delenv("AGENTLAS_THREADS_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("THREADS_ACCESS_TOKEN", raising=False)
    ledger = tmp_path / "ledgers" / "research-receipts.jsonl"
    append_jsonl(
        ledger,
        {
            "ts": utc_now(),
            "receipt_id": "research_reddit_public",
            "request_hash": "hash_reddit_public",
            "module_chain": ["platform.reddit"],
            "attempts": [{"module": "platform.reddit", "status": "ok", "reason": "public_rss_fallback"}],
            "policy": {},
        },
    )
    append_jsonl(
        ledger,
        {
            "ts": utc_now(),
            "receipt_id": "research_threads_public",
            "request_hash": "hash_threads_public",
            "module_chain": ["platform.threads.public"],
            "attempts": [{"module": "platform.threads.public", "status": "ok", "reason": "public_html_status=200"}],
            "policy": {},
        },
    )

    payload = run_research_proofs(home=tmp_path)

    public_proofs = {item["id"]: item for item in payload["public_fallback_proofs"]}
    assert public_proofs["reddit_public_live_check"]["status"] == "ok"
    assert public_proofs["threads_public_live_check"]["status"] == "ok"
    assert public_proofs["reddit_public_live_check"]["live_proof"]["receipt_id"] == "research_reddit_public"
    assert public_proofs["threads_public_live_check"]["live_proof"]["receipt_id"] == "research_threads_public"
    assert payload["completion"]["satisfied_public_fallback_proofs"] == [
        "reddit_public_live_check",
        "threads_public_live_check",
    ]
    assert payload["coverage"]["public_fallback_ok"] == [
        "reddit_public_live_check",
        "threads_public_live_check",
    ]
    assert payload["coverage"]["required_missing"] == [
        "reddit_oauth_live_check",
        "threads_live_graph_check",
        "browser_hardpoint_live_check",
    ]
    assert payload["completion"]["missing_or_unready_proofs"] == [
        "reddit_oauth_live_check",
        "threads_live_graph_check",
        "browser_hardpoint_live_check",
    ]


def test_research_cli_proofs(tmp_path, capsys):
    code = main(["research", "proofs", "--home", str(tmp_path), "--limit", "0"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "agentlas.research.proofs.v0"
    assert payload["recent_receipts"] == []
    assert "required_proofs" in payload


def test_research_verify_runs_public_checks_and_updates_public_proofs(tmp_path, monkeypatch):
    def fake_platform_check(*, module_id, source_hint, home=None, registry=None):
        receipt_id = f"receipt_{module_id.replace('.', '_')}"
        append_jsonl(
            tmp_path / "ledgers" / "research-receipts.jsonl",
            {
                "ts": utc_now(),
                "receipt_id": receipt_id,
                "request_hash": f"hash_{module_id}",
                "module_chain": [module_id],
                "attempts": [{"module": module_id, "status": "ok", "reason": "fake_ok"}],
                "policy": {},
            },
        )
        return {
            "schema": "agentlas.research.platform_check.v0",
            "status": "ok",
            "module": module_id,
            "source_hint": source_hint,
            "receipt_id": receipt_id,
            "attempts": [{"module": module_id, "status": "ok", "reason": "fake_ok"}],
            "result_summaries": [{"title": module_id}],
        }

    monkeypatch.setattr("agentlas_cloud.research.verify.run_research_platform_check", fake_platform_check)

    payload = run_research_verify(home=tmp_path, include_browser=False, include_credentialed=False)

    assert payload["schema"] == "agentlas.research.verify.v0"
    assert payload["status"] == "partial"
    checks = {item["id"]: item for item in payload["checks"]}
    assert checks["reddit_public_live_check"]["status"] == "ok"
    assert checks["threads_public_live_check"]["status"] == "ok"
    assert checks["browser_hardpoint_live_check"]["status"] == "skipped"
    public = {item["id"]: item for item in payload["proofs"]["public_fallback_proofs"]}
    assert public["reddit_public_live_check"]["status"] == "ok"
    assert public["threads_public_live_check"]["status"] == "ok"
    assert payload["credentials_exposed_to_model"] is False


def test_research_verify_skips_unready_credentialed_modules(tmp_path, monkeypatch):
    clear_reddit_oauth_env(monkeypatch)
    monkeypatch.delenv("AGENTLAS_THREADS_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("THREADS_ACCESS_TOKEN", raising=False)

    payload = run_research_verify(home=tmp_path, include_public=False, include_browser=False)

    checks = {item["id"]: item for item in payload["checks"]}
    assert checks["reddit_oauth_live_check"]["status"] == "skipped_not_ready"
    assert checks["threads_live_graph_check"]["status"] == "skipped_not_ready"
    assert checks["reddit_oauth_live_check"]["readiness"]["state"] == "needs_config"
    assert checks["threads_live_graph_check"]["readiness"]["state"] == "needs_config"
    assert payload["status"] == "partial"


def test_research_verify_uses_ready_browser_hardpoint(tmp_path, monkeypatch):
    script = tmp_path / "stagehand_snapshot.py"
    script.write_text(
        "import json, sys\n"
        "assert sys.argv[1] == 'https://example.com'\n"
        "print(json.dumps({'title': 'Stagehand Proof', 'snapshot': '# Stagehand Proof'}))\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AGENTLAS_STAGEHAND_SNAPSHOT_CMD", f"{sys.executable} {script} {{url}}")
    monkeypatch.delenv("AGENTLAS_PLAYWRIGHT_MCP_SNAPSHOT_CMD", raising=False)
    monkeypatch.delenv("AGENTLAS_BROWSER_USE_SNAPSHOT_CMD", raising=False)
    monkeypatch.delenv("AGENTLAS_STEEL_SNAPSHOT_CMD", raising=False)
    monkeypatch.delenv("AGENTLAS_HYPERAGENT_SNAPSHOT_CMD", raising=False)
    monkeypatch.delenv("AGENTLAS_AGENT_BROWSER_BIN", raising=False)
    monkeypatch.setattr("agentlas_cloud.research.armory.shutil.which", lambda name: None)

    payload = run_research_verify(home=tmp_path, include_public=False, include_credentialed=False)
    checks = {item["id"]: item for item in payload["checks"]}
    proofs = {item["id"]: item for item in payload["proofs"]["required_proofs"]}

    assert checks["browser_hardpoint_live_check"]["status"] == "ok"
    assert checks["browser_hardpoint_live_check"]["selected_module_id"] == "browser.stagehand"
    assert checks["browser_hardpoint_live_check"]["attempts"][0]["module"] == "browser.stagehand"
    assert checks["browser_hardpoint_live_check"]["readiness"]["selected_module"] == "browser.stagehand"
    assert proofs["browser_hardpoint_live_check"]["status"] == "ok"
    assert proofs["browser_hardpoint_live_check"]["live_proof"]["receipt_id"] == checks["browser_hardpoint_live_check"]["receipt_id"]
    assert payload["status"] == "partial"


def test_research_cli_verify_all_skipped(tmp_path, capsys):
    code = main(
        [
            "research",
            "verify",
            "--home",
            str(tmp_path),
            "--skip-public",
            "--skip-browser",
            "--skip-credentialed",
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "agentlas.research.verify.v0"
    assert all(item["status"] == "skipped" for item in payload["checks"])


def test_research_cli_profile_filters_loadout(capsys):
    code = main(["research", "profile", "--loadout", "browser"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "agentlas.research.profile.v0"
    assert payload["loadout"] == "browser"
    assert len(payload["profiles"]) == 1
    assert payload["profiles"][0]["name"] == "browser"
    assert payload["profiles"][0]["footprint"]["browser_module_count"] == 7
    assert payload["profiles"][0]["operator_summary"]["posture"] == "browser_heavy"


def test_research_cli_lists_detachable_modules(capsys):
    code = main(["research", "modules"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    modules = {item["id"]: item for item in payload["modules"]}
    assert modules["search.ddg_html"]["weight"] == "light"
    assert modules["search.ddg_html"]["slot"] == "search"
    assert modules["search.ddg_html"]["activation"] == "auto"
    assert modules["search.news_rss"]["weight"] == "light"
    assert modules["search.news_rss"]["slot"] == "search"
    assert modules["search.news_rss"]["activation"] == "auto"
    assert modules["read.http"]["weight"] == "light"
    assert modules["read.insane_fetch"]["default_state"] == "available_if_allowed"
    assert modules["read.insane_fetch"]["activation"] == "explicit_allow"
    assert modules["read.jina"]["default_state"] == "available_if_allowed"
    assert modules["search.jina"]["default_state"] == "available_if_configured"
    assert modules["platform.reddit.oauth"]["default_state"] == "available_if_configured"
    assert modules["platform.reddit.oauth"]["activation"] == "configured"
    assert modules["platform.reddit"]["weight"] == "adaptive_medium"
    assert modules["platform.threads"]["slot"] == "platform"
    assert modules["platform.threads.public"]["default_state"] == "public_fallback_available"
    assert modules["platform.threads.public"]["activation"] == "auto_for_threads_urls"
    assert modules["browser.agent_cli"]["weight"] == "browser_heavy"
    assert modules["browser.agent_cli"]["slot"] == "browser"
    assert modules["browser.playwright_mcp"]["default_state"] == "available_if_configured"
    assert modules["browser.playwright_mcp"]["slot"] == "browser"
    assert modules["browser.browser_use"]["default_state"] == "available_if_configured"
    assert modules["browser.browser_use"]["slot"] == "browser"
    assert modules["browser.stagehand"]["default_state"] == "available_if_configured"
    assert modules["browser.stagehand"]["slot"] == "browser"
    assert modules["browser.steel"]["default_state"] == "available_if_configured"
    assert modules["browser.steel"]["slot"] == "browser"
    assert modules["browser.hyperagent"]["default_state"] == "available_if_configured"
    assert modules["browser.hyperagent"]["slot"] == "browser"


def test_research_bridge_contracts_describe_browser_hardpoints_without_secrets(monkeypatch):
    monkeypatch.setenv("AGENTLAS_STAGEHAND_SNAPSHOT_CMD", "stagehand --api-key secret-stagehand {url}")

    payload = run_research_bridge_contracts(module_id="browser.stagehand")

    assert payload["schema"] == "agentlas.research.bridge_contracts.v0"
    assert payload["status"] == "ok"
    assert payload["commands_will_run"] is False
    assert payload["network_will_run"] is False
    assert payload["credentials_exposed_to_model"] is False
    assert len(payload["contracts"]) == 1
    contract = payload["contracts"][0]
    assert contract["id"] == "browser.stagehand"
    assert contract["bridge_kind"] == "snapshot_command"
    assert contract["configured_by"] == {"env": "AGENTLAS_STAGEHAND_SNAPSHOT_CMD"}
    assert "extraction" in contract["output_contract"]["accepted_content_fields"]
    assert contract["output_contract"]["sample_json"]["limits"] == ["stagehand_snapshot"]
    assert contract["security_boundary"]["provider_tokens_stay_outside_engine"] is True
    assert "secret-stagehand" not in str(payload)


def test_research_cli_bridge_contract_filters_module(capsys):
    code = main(["research", "bridge-contract", "--module", "browser.agent_cli"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "agentlas.research.bridge_contracts.v0"
    assert payload["module"] == "browser.agent_cli"
    assert payload["contracts"][0]["bridge_kind"] == "agent_browser_cli"
    assert payload["contracts"][0]["configured_by"] == {
        "env": "AGENTLAS_AGENT_BROWSER_BIN",
        "local_hardpoint_config": "policies/research-hardpoints.json",
        "binary": "agent-browser",
    }
    assert payload["contracts"][0]["command_sequence"] == [
        "agent-browser open <url>",
        "agent-browser chat <instruction>",
        "agent-browser snapshot -i",
        "agent-browser close",
    ]
    assert payload["contracts"][0]["capabilities"] == ["browser.snapshot", "browser.automation", "read.url"]
    recipes = {item["name"]: item for item in payload["contracts"][0]["setup_recipes"]}
    assert recipes["installed_binary"]["command"] == "npm install -g agent-browser"
    assert recipes["npx_agent_browser_hardpoint"]["command"] == "bin/hephaestus research hardpoints --arm browser.agent_cli --recipe npx-agent-browser"
    assert recipes["npx_one_shot"]["env"] == {"AGENTLAS_AGENT_BROWSER_BIN": "npx -y agent-browser"}


def test_research_hardpoints_arm_agent_browser_recipe(tmp_path, monkeypatch):
    monkeypatch.delenv("AGENTLAS_AGENT_BROWSER_BIN", raising=False)
    monkeypatch.setattr("agentlas_cloud.research.armory.shutil.which", lambda name: None)

    payload = run_research_hardpoints(
        action="arm",
        module_id="browser.agent_cli",
        recipe="npx-agent-browser",
        home=tmp_path,
    )

    assert payload["schema"] == "agentlas.research.hardpoints.v0"
    assert payload["status"] == "ok"
    assert payload["commands_will_run"] is False
    assert payload["network_will_run"] is False
    assert payload["credentials_exposed_to_model"] is False
    assert payload["hardpoints"][0]["module_id"] == "browser.agent_cli"
    assert payload["hardpoints"][0]["command_display"] == "npx -y agent-browser"
    assert "argv" not in str(payload["hardpoints"][0])

    armory = run_research_armory(loadout="browser", slot="browser", home=str(tmp_path))
    modules = {module["id"]: module for module in armory["modules"]}
    readiness = modules["browser.agent_cli"]["readiness"]
    assert readiness["state"] == "ready"
    assert readiness["checks"][0]["configured_hardpoint"]["recipe"] == "npx-agent-browser"


def test_research_cli_hardpoints_arm_and_disarm(tmp_path, capsys):
    code = main(
        [
            "research",
            "hardpoints",
            "--home",
            str(tmp_path),
            "--arm",
            "browser.agent_cli",
            "--recipe",
            "npx-agent-browser",
        ]
    )

    assert code == 0
    armed = json.loads(capsys.readouterr().out)
    assert armed["status"] == "ok"
    assert armed["hardpoints"][0]["enabled"] is True

    code = main(["research", "hardpoints", "--home", str(tmp_path), "--disarm", "browser.agent_cli"])

    assert code == 0
    disarmed = json.loads(capsys.readouterr().out)
    assert disarmed["status"] == "ok"
    assert disarmed["hardpoints"][0]["enabled"] is False


def test_research_bridge_check_runs_configured_snapshot_command(tmp_path, monkeypatch):
    script = tmp_path / "stagehand_snapshot.py"
    script.write_text(
        "import json, sys\n"
        "assert sys.argv[1] == 'https://example.com'\n"
        "print(json.dumps({\n"
        "  'title': 'Bridge Check Title',\n"
        "  'extraction': '# Bridge Check Title\\n\\nLoaded through subprocess',\n"
        "  'limits': ['test_bridge']\n"
        "}))\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AGENTLAS_STAGEHAND_SNAPSHOT_CMD", f"{sys.executable} {script} {{url}}")

    payload = run_research_bridge_check(
        module_id="browser.stagehand",
        url="https://example.com",
        home=tmp_path / "home",
    )

    assert payload["schema"] == "agentlas.research.bridge_check.v0"
    assert payload["status"] == "ok"
    assert payload["command_execution_requested"] is True
    assert payload["commands_will_run"] is True
    assert payload["network_will_run"] is True
    assert payload["url_policy"] == {"safe": True, "reason": "public"}
    assert payload["credentials_exposed_to_model"] is False
    assert payload["contract"]["id"] == "browser.stagehand"
    assert payload["attempts"][0]["module"] == "browser.stagehand"
    assert payload["browser_execution"]["status"] == "used"
    assert payload["result_summaries"][0]["title"] == "Bridge Check Title"
    assert "Loaded through subprocess" in payload["result_summaries"][0]["content_preview"]
    assert (tmp_path / "home" / "ledgers" / "research-receipts.jsonl").exists()


def test_research_cli_bridge_check_reports_missing_command(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("AGENTLAS_STAGEHAND_SNAPSHOT_CMD", raising=False)

    code = main(
        [
            "research",
            "bridge-check",
            "--module",
            "browser.stagehand",
            "--url",
            "https://example.com",
            "--home",
            str(tmp_path),
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "agentlas.research.bridge_check.v0"
    assert payload["status"] == "not_ready"
    assert payload["command_execution_requested"] is True
    assert payload["commands_will_run"] is False
    assert payload["network_will_run"] is False
    assert payload["attempts"][0]["status"] == "module_unavailable"
    assert payload["browser_execution"]["status"] == "unavailable"


def test_research_browser_candidates_lists_detached_hardpoints_without_running(monkeypatch):
    monkeypatch.delenv("AGENTLAS_STAGEHAND_SNAPSHOT_CMD", raising=False)

    payload = run_research_browser_candidates()

    assert payload["schema"] == "agentlas.research.browser_candidates.v0"
    assert payload["status"] == "ok"
    assert payload["commands_will_run"] is False
    assert payload["network_will_run"] is False
    assert payload["credentials_exposed_to_model"] is False
    ids = [item["module_id"] for item in payload["candidates"]]
    assert ids == [
        "browser.agent_cli",
        "browser.playwright_mcp",
        "browser.browser_use",
        "browser.stagehand",
        "browser.steel",
        "browser.hyperagent",
        "browser.browseros",
    ]
    stagehand = next(item for item in payload["candidates"] if item["module_id"] == "browser.stagehand")
    assert stagehand["registered"] is True
    assert stagehand["slot"] == "browser"
    assert stagehand["weight"] == "browser_heavy"
    assert stagehand["readiness"]["state"] == "needs_config"
    assert "https://github.com/browserbase/stagehand" in stagehand["primary_sources"]
    assert "behind an explicit command bridge" in stagehand["why_detached"]
    assert stagehand["mount_plan"]["proof_id"] == "browser_hardpoint_live_check"
    assert stagehand["mount_plan"]["check_command"] == "bin/hephaestus research bridge-check --module browser.stagehand --url https://example.com"
    assert stagehand["mount_plan"]["commands_will_run"] is False
    browseros = next(item for item in payload["candidates"] if item["module_id"] == "browser.browseros")
    assert browseros["registered"] is True
    assert browseros["readiness"]["state"] == "needs_config"
    assert browseros["mount_plan"]["status"] == "bridge_ready"
    assert browseros["mount_plan"]["check_command"] == "bin/hephaestus research bridge-check --module browser.browseros --url https://example.com"
    assert browseros["setup_env"] == "AGENTLAS_BROWSEROS_SNAPSHOT_CMD"
    assert "future_bridge_candidate" in browseros["recommended_for"]
    assert payload["recommendation"]["status"] == "not_requested"


def test_research_browser_candidates_recognizes_english_agent_browser_query():
    payload = run_research_browser_candidates(query="agent browser modules")

    assert payload["recommendation"]["status"] in {"ready", "needs_setup"}
    assert payload["recommendation"]["module_id"] == "browser.agent_cli"
    assert payload["recommendation"]["reason"] == "agent_browser_first_for_browser_task"
    assert payload["recommendation"]["preferred_loadout"] == "browser"
    assert payload["recommendation"]["mount_browser"] is True


def test_research_cli_browser_candidates_can_filter_agent_browser(tmp_path, capsys):
    code = main(
        [
            "research",
            "browser-candidates",
            "--module",
            "browser.agent_cli",
            "--query",
            "로컬 브라우저 스냅샷",
            "--home",
            str(tmp_path),
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "agentlas.research.browser_candidates.v0"
    assert payload["module"] == "browser.agent_cli"
    assert payload["query"] == "로컬 브라우저 스냅샷"
    assert payload["home"] == str(tmp_path)
    assert payload["commands_will_run"] is False
    assert payload["network_will_run"] is False
    assert len(payload["candidates"]) == 1
    candidate = payload["candidates"][0]
    assert candidate["name"] == "agent-browser"
    assert candidate["setup_env"] == "AGENTLAS_AGENT_BROWSER_BIN"
    assert candidate["mount_plan"]["check_command"] == "bin/hephaestus research bridge-check --module browser.agent_cli --url https://example.com"
    assert candidate["mount_plan"]["setup_commands"][0] == "bin/hephaestus research hardpoints --arm browser.agent_cli --recipe npx-agent-browser"
    assert "https://github.com/vercel-labs/agent-browser" in candidate["primary_sources"]
    assert payload["recommendation"]["module_id"] == "browser.agent_cli"
    assert payload["recommendation"]["mount_browser"] is True
    assert payload["recommendation"]["proof_id"] == "browser_hardpoint_live_check"
    assert payload["recommendation"]["check_command"] == "bin/hephaestus research bridge-check --module browser.agent_cli --url https://example.com"
    assert payload["recommendation"]["status"] in {"ready", "needs_setup"}


def test_hep_browser_cli_reads_url_with_agent_browser_first(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AGENTLAS_AGENT_BROWSER_BIN", "agent-browser")
    monkeypatch.setenv("AGENTLAS_BROWSER_ENGINE", "agent-browser")
    monkeypatch.setenv("HEPHAESTUS_BROWSER_AUTO_CDP", "0")

    def fake_run(self, argv, *, timeout=None):
        if argv[-1] == "close":
            return subprocess.CompletedProcess(argv, 0, "", "")
        if "snapshot" in argv:
            return subprocess.CompletedProcess(argv, 0, '- heading "Agentlas Browser Page" [ref=e1]', "")
        assert argv == ["agent-browser", "open", "https://example.com"]
        return subprocess.CompletedProcess(argv, 0, "opened", "")

    monkeypatch.setattr(AgentBrowserCliAdapter, "_run", fake_run)

    code = main(["hep-browser", "https://example.com", "--home", str(tmp_path)])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "agentlas.research.v0"
    assert payload["status"] == "ok"
    assert payload["surface"]["command"] == "hep-browser"
    assert payload["surface"]["default_browser_module"] == "browser.agent_cli"
    assert payload["request"]["allowed_modules"] == ["browser.agent_cli"]
    assert payload["request"]["max_weight"] == "browser_heavy"
    assert payload["results"][0]["platform"] == "browser"
    assert payload["results"][0]["title"] == "Agentlas Browser Page"
    assert payload["receipt"]["module_chain"] == ["browser.agent_cli"]


def test_hep_browser_cli_prefers_human_gmail_url(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AGENTLAS_AGENT_BROWSER_BIN", "agent-browser")
    monkeypatch.setenv("AGENTLAS_BROWSER_ENGINE", "agent-browser")
    monkeypatch.setenv("HEPHAESTUS_BROWSER_AUTO_CDP", "0")
    calls = []

    def fake_run(self, argv, *, timeout=None):
        calls.append(argv)
        if argv[-1] == "close":
            return subprocess.CompletedProcess(argv, 0, "", "")
        if "snapshot" in argv:
            return subprocess.CompletedProcess(argv, 0, '- button "Compose" [ref=e1]', "")
        assert argv == ["agent-browser", "open", "https://mail.google.com/"]
        return subprocess.CompletedProcess(argv, 0, "opened", "")

    monkeypatch.setattr(AgentBrowserCliAdapter, "_run", fake_run)

    code = main(["hep-browser", "https://mail.google.com/mail/u/0/#inbox", "--home", str(tmp_path)])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["request"]["source_hints"] == ["https://mail.google.com/"]
    assert payload["surface"]["original_urls"] == ["https://mail.google.com/mail/u/0/#inbox"]
    assert payload["surface"]["url_rewrites"] == [
        {
            "from": "https://mail.google.com/mail/u/0/#inbox",
            "to": "https://mail.google.com/",
            "reason": "human_entry_url",
        }
    ]
    assert calls[0] == ["agent-browser", "open", "https://mail.google.com/"]


def test_hep_browser_cli_raw_url_preserves_gmail_shell_url(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AGENTLAS_AGENT_BROWSER_BIN", "agent-browser")
    monkeypatch.setenv("AGENTLAS_BROWSER_ENGINE", "agent-browser")
    monkeypatch.setenv("HEPHAESTUS_BROWSER_AUTO_CDP", "0")
    calls = []

    def fake_run(self, argv, *, timeout=None):
        calls.append(argv)
        if argv[-1] == "close":
            return subprocess.CompletedProcess(argv, 0, "", "")
        if "snapshot" in argv:
            return subprocess.CompletedProcess(argv, 0, '- button "Compose" [ref=e1]', "")
        assert argv == ["agent-browser", "open", "https://mail.google.com/mail/u/0/#inbox"]
        return subprocess.CompletedProcess(argv, 0, "opened", "")

    monkeypatch.setattr(AgentBrowserCliAdapter, "_run", fake_run)

    code = main([
        "hep-browser",
        "https://mail.google.com/mail/u/0/#inbox",
        "--raw-url",
        "--home",
        str(tmp_path),
    ])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["request"]["source_hints"] == ["https://mail.google.com/mail/u/0/#inbox"]
    assert payload["surface"]["url_rewrites"] == []
    assert calls[0] == ["agent-browser", "open", "https://mail.google.com/mail/u/0/#inbox"]


def test_hep_browser_cli_read_forwards_cdp_and_keep_open(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AGENTLAS_AGENT_BROWSER_BIN", "agent-browser")
    monkeypatch.setenv("AGENTLAS_BROWSER_ENGINE", "agent-browser")
    calls = []

    def fake_run(self, argv, *, timeout=None):
        calls.append(argv)
        if "snapshot" in argv:
            return subprocess.CompletedProcess(argv, 0, '- heading "CDP Page" [ref=e1]', "")
        assert argv == ["agent-browser", "--cdp", "9222", "open", "https://example.com"]
        return subprocess.CompletedProcess(argv, 0, "opened", "")

    monkeypatch.setattr(AgentBrowserCliAdapter, "_run", fake_run)

    code = main([
        "hep-browser",
        "https://example.com",
        "--read",
        "--cdp",
        "9222",
        "--keep-open",
        "--home",
        str(tmp_path),
    ])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "agentlas.research.v0"
    assert payload["request"]["browser_args"] == ["--cdp", "9222"]
    assert payload["request"]["browser_keep_open"] is True
    assert payload["results"][0]["title"] == "CDP Page"
    assert "browser_cdp_attach" in payload["results"][0]["limits"]
    assert "browser_left_open" in payload["results"][0]["limits"]
    assert calls == [
        ["agent-browser", "--cdp", "9222", "open", "https://example.com"],
        ["agent-browser", "--cdp", "9222", "snapshot", "-i"],
    ]


def test_hep_browser_cli_automates_url_when_instruction_is_present(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AGENTLAS_AGENT_BROWSER_BIN", "agent-browser")
    monkeypatch.setenv("AGENTLAS_BROWSER_ENGINE", "agent-browser")
    calls = []

    def fake_run(self, argv, *, timeout=None):
        calls.append(argv)
        if argv[-1] == "close":
            return subprocess.CompletedProcess(argv, 0, "", "")
        if "snapshot" in argv:
            return subprocess.CompletedProcess(argv, 0, '- button "Done" [ref=e2]', "")
        if "chat" in argv:
            return subprocess.CompletedProcess(argv, 0, "Clicked the CTA.", "")
        assert argv == ["agent-browser", "--cdp", "9222", "open", "https://example.com"]
        return subprocess.CompletedProcess(argv, 0, "opened", "")

    monkeypatch.setattr(AgentBrowserCliAdapter, "_run", fake_run)

    code = main([
        "hep-browser",
        "https://example.com",
        "click the CTA",
        "--cdp",
        "9222",
        "--home",
        str(tmp_path),
    ])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "agentlas.research.hep_browser.v0"
    assert payload["status"] == "ok"
    assert payload["mode"] == "automation"
    assert payload["surface"]["automation"] is True
    assert payload["request"]["instruction"] == "click the CTA"
    assert payload["request"]["browser_args"] == ["--cdp", "9222"]
    assert payload["runs"][0]["status"] == "ok"
    assert payload["runs"][0]["chat_text"] == "Clicked the CTA."
    assert payload["runs"][0]["snapshot"] == '- button "Done" [ref=e2]'
    assert calls[0] == ["agent-browser", "--cdp", "9222", "open", "https://example.com"]
    assert calls[1] == ["agent-browser", "--cdp", "9222", "-q", "chat", "click the CTA"]
    assert calls[2] == ["agent-browser", "--cdp", "9222", "snapshot", "-i"]
    assert calls[3] == ["agent-browser", "--cdp", "9222", "close"]


def test_hep_browser_cli_clicks_explicit_ref_without_llm(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AGENTLAS_AGENT_BROWSER_BIN", "agent-browser")
    monkeypatch.setenv("AGENTLAS_BROWSER_ENGINE", "agent-browser")
    calls = []

    def fake_run(self, argv, *, timeout=None):
        calls.append(argv)
        if argv[-1] == "close":
            return subprocess.CompletedProcess(argv, 0, "", "")
        if "snapshot" in argv:
            return subprocess.CompletedProcess(argv, 0, '- dialog "New Message" [ref=e9]', "")
        if "click" in argv:
            return subprocess.CompletedProcess(argv, 0, "clicked", "")
        assert argv == ["agent-browser", "--cdp", "9222", "open", "https://example.com"]
        return subprocess.CompletedProcess(argv, 0, "opened", "")

    monkeypatch.setattr(AgentBrowserCliAdapter, "_run", fake_run)

    code = main([
        "hep-browser",
        "https://example.com",
        "--click",
        "@e1",
        "--cdp",
        "9222",
        "--home",
        str(tmp_path),
    ])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "agentlas.research.hep_browser.v0"
    assert payload["status"] == "ok"
    assert payload["mode"] == "primitive"
    assert payload["surface"]["llm_required"] is False
    assert payload["request"]["actions"] == [{"type": "click", "target": "@e1"}]
    assert payload["runs"][0]["snapshot"] == '- dialog "New Message" [ref=e9]'
    assert calls == [
        ["agent-browser", "--cdp", "9222", "open", "https://example.com"],
        ["agent-browser", "--cdp", "9222", "snapshot", "-i"],
        ["agent-browser", "--cdp", "9222", "click", "@e1"],
        ["agent-browser", "--cdp", "9222", "snapshot", "-i"],
        ["agent-browser", "--cdp", "9222", "close"],
    ]


def test_hep_browser_cli_clicks_visible_text_without_llm(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AGENTLAS_AGENT_BROWSER_BIN", "agent-browser")
    monkeypatch.setenv("AGENTLAS_BROWSER_ENGINE", "agent-browser")
    calls = []

    def fake_run(self, argv, *, timeout=None):
        calls.append(argv)
        if argv[-1] == "close":
            return subprocess.CompletedProcess(argv, 0, "", "")
        if "snapshot" in argv:
            return subprocess.CompletedProcess(argv, 0, '- dialog "New Message" [ref=e9]', "")
        if "find" in argv:
            return subprocess.CompletedProcess(argv, 0, "clicked", "")
        assert argv == ["agent-browser", "--cdp", "9222", "open", "https://example.com"]
        return subprocess.CompletedProcess(argv, 0, "opened", "")

    monkeypatch.setattr(AgentBrowserCliAdapter, "_run", fake_run)

    code = main([
        "hep-browser",
        "https://example.com",
        "--click-text",
        "Compose",
        "--cdp",
        "9222",
        "--home",
        str(tmp_path),
    ])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "ok"
    assert payload["mode"] == "primitive"
    assert payload["request"]["actions"] == [{"type": "find_text_click", "target": "Compose"}]
    assert calls == [
        ["agent-browser", "--cdp", "9222", "open", "https://example.com"],
        ["agent-browser", "--cdp", "9222", "find", "text", "Compose", "click"],
        ["agent-browser", "--cdp", "9222", "snapshot", "-i"],
        ["agent-browser", "--cdp", "9222", "close"],
    ]


def test_research_browser_candidates_prefers_agent_browser_for_structured_extract(monkeypatch):
    monkeypatch.setenv("AGENTLAS_STAGEHAND_SNAPSHOT_CMD", "stagehand-snapshot {url}")
    monkeypatch.setattr("agentlas_cloud.research.armory.shutil.which", lambda name: None)

    payload = run_research_browser_candidates(query="dynamic page structured extraction")

    assert payload["recommendation"]["module_id"] == "browser.agent_cli"
    assert payload["recommendation"]["status"] == "needs_setup"
    assert payload["recommendation"]["reason"] == "agent_browser_first_for_browser_task"
    assert payload["recommendation"]["check_command"] == "bin/hephaestus research bridge-check --module browser.agent_cli --url https://example.com"
    assert payload["recommendation"]["setup_commands"][0] == "bin/hephaestus research hardpoints --arm browser.agent_cli --recipe npx-agent-browser"
    assert payload["recommendation"]["operator_approval_required"] is False


def test_research_platform_contracts_describe_threads_without_secrets(monkeypatch):
    monkeypatch.setenv("AGENTLAS_THREADS_ACCESS_TOKEN", "secret-threads-token")

    payload = run_research_platform_contracts(module_id="platform.threads")

    assert payload["schema"] == "agentlas.research.platform_contracts.v0"
    assert payload["status"] == "ok"
    assert payload["commands_will_run"] is False
    assert payload["network_will_run"] is False
    assert payload["credentials_exposed_to_model"] is False
    assert len(payload["contracts"]) == 1
    contract = payload["contracts"][0]
    assert contract["id"] == "platform.threads"
    assert contract["credential_env"] == ["AGENTLAS_THREADS_ACCESS_TOKEN", "THREADS_ACCESS_TOKEN"]
    assert "threads:keyword:<query>" in contract["source_hints"]
    assert contract["readiness"]["state"] == "ready"
    assert contract["credential_boundary"]["secret_values_printed"] is False
    assert "secret-threads-token" not in str(payload)


def test_research_platform_contracts_describe_threads_public_fallback():
    payload = run_research_platform_contracts(module_id="platform.threads.public")

    assert payload["schema"] == "agentlas.research.platform_contracts.v0"
    assert payload["status"] == "ok"
    contract = payload["contracts"][0]
    assert contract["id"] == "platform.threads.public"
    assert contract["credential_env"] == []
    assert "threads:lookup:<username>" in contract["source_hints"]
    assert contract["readiness"]["state"] == "ready"
    assert any("public Threads HTML" in note for note in contract["runtime_notes"])


def test_research_cli_platform_contract_filters_reddit_public(capsys):
    code = main(["research", "platform-contract", "--module", "platform.reddit"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "agentlas.research.platform_contracts.v0"
    assert payload["module"] == "platform.reddit"
    contract = payload["contracts"][0]
    assert contract["id"] == "platform.reddit"
    assert contract["credential_env"] == []
    assert "reddit:search:<query>" in contract["source_hints"]
    assert any("public fallback" in note for note in contract["runtime_notes"])


def test_research_social_fallbacks_summarizes_no_token_modules(monkeypatch):
    clear_reddit_oauth_env(monkeypatch)
    monkeypatch.delenv("AGENTLAS_THREADS_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("THREADS_ACCESS_TOKEN", raising=False)

    payload = run_research_social_fallbacks()

    assert payload["schema"] == "agentlas.research.social_fallbacks.v0"
    assert payload["commands_will_run"] is False
    assert payload["network_will_run"] is False
    assert payload["credentials_exposed_to_model"] is False
    assert payload["decision"]["insane_search_fit"] == "detachable_reader_cartridge"
    assert payload["recommended_loadouts"]["blocked_public_pages"] == "public-web"
    assert "threads_live_graph_check" in payload["official_api_required_for"]
    modules = {module["id"]: module for module in payload["modules"]}
    assert modules["platform.reddit"]["weight"] == "adaptive_medium"
    assert modules["platform.reddit"]["no_token"] is True
    assert modules["platform.threads.public"]["no_token"] is True
    assert modules["read.insane_fetch"]["role"] == "adaptive_public_page_reader"
    assert modules["platform.reddit.oauth"]["token_required"] is True
    assert modules["platform.threads"]["readiness"]["state"] == "needs_config"


def test_research_cli_social_fallbacks(capsys):
    code = main(["research", "social-fallbacks"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "agentlas.research.social_fallbacks.v0"
    assert payload["decision"]["stormbreaker_fit"] == "mount_public_web_by_default; social_loadout_only_when_official_api_is_explicitly_allowed"
    assert "reddit" in payload["no_token_coverage"]


def test_research_platform_check_reports_missing_threads_token(tmp_path, monkeypatch):
    monkeypatch.delenv("THREADS_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("AGENTLAS_THREADS_ACCESS_TOKEN", raising=False)

    payload = run_research_platform_check(
        module_id="platform.threads",
        source_hint="threads:keyword:agent browser",
        home=tmp_path,
    )

    assert payload["schema"] == "agentlas.research.platform_check.v0"
    assert payload["status"] == "not_ready"
    assert payload["commands_will_run"] is False
    assert payload["network_will_run"] is False
    assert payload["source_policy"] == {"safe": True, "reason": "platform_hint", "supported": True, "kind": "platform_hint"}
    assert payload["attempts"][0]["module"] == "platform.threads"
    assert payload["attempts"][0]["status"] == "module_unavailable"
    assert payload["credentials_exposed_to_model"] is False


def test_research_cli_lists_loadouts(capsys):
    code = main(["research", "loadouts"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    loadouts = {item["name"]: item for item in payload["loadouts"]}
    assert payload["schema"] == "agentlas.research.loadouts.v0"
    assert loadouts["safe"]["allowed_modules"] == ["search.ddg_html", "search.news_rss", "read.http", "platform.reddit"]
    assert loadouts["safe"]["max_weight"] == "adaptive_medium"
    assert loadouts["auto"]["status"] == "source_aware_default"
    assert loadouts["auto"]["max_weight"] == "source_aware"
    assert "platform.reddit.oauth" in loadouts["social"]["allowed_modules"]
    assert "browser.playwright_mcp" in loadouts["browser"]["allowed_modules"]
    assert "browser.browser_use" in loadouts["browser"]["allowed_modules"]
    assert "browser.stagehand" in loadouts["browser"]["allowed_modules"]
    assert "browser.steel" in loadouts["browser"]["allowed_modules"]
    assert "browser.hyperagent" in loadouts["browser"]["allowed_modules"]
    assert "browser.agent_cli" in loadouts["browser"]["allowed_modules"]
    assert loadouts["browser"]["allowed_modules"].index("browser.agent_cli") < loadouts["browser"]["allowed_modules"].index("browser.playwright_mcp")
    assert loadouts["full"]["max_weight"] == "browser_heavy"


class FakeJinaReader(JinaReaderAdapter):
    def _fetch_text(self, url):
        assert url == "https://r.jina.ai/https://example.com/article"
        return "# Jina Article\n\nReadable markdown"


class FakeJinaSearch(JinaSearchAdapter):
    def _api_key(self):
        return "test-jina-key"

    def _fetch_text(self, url, *, api_key):
        assert api_key == "test-jina-key"
        assert url == "https://s.jina.ai/?q=agent%20browser%20modules"
        return "# Search Results\n\n- [Agent browser modules](https://example.com/jina-agent-browser)\n- https://example.com/raw-result"


class FakeNewsRssSearch(NewsRssSearchAdapter):
    def _fetch_text(self, url):
        assert url == "https://news.google.com/rss/search?q=agent+browser+modules&hl=en-US&gl=US&ceid=US:en"
        return """<?xml version="1.0"?><rss><channel><title>agent browser modules - Google News</title><item><title>Agent browsers get modular</title><link>https://example.com/agent-browser</link><pubDate>Wed, 24 Jun 2026 00:00:00 GMT</pubDate><source>Example</source><description>Research modules can be detachable.</description></item></channel></rss>"""


class FakeGitHubReposSearch(GitHubReposSearchAdapter):
    def _fetch_json(self, url):
        assert url.startswith("https://api.github.com/search/repositories?q=")
        assert url.endswith("&per_page=10")
        return {
            "total_count": 1,
            "incomplete_results": False,
            "items": [
                {
                    "full_name": "example/agent-browser",
                    "html_url": "https://github.com/example/agent-browser",
                    "description": "Composable browser hardpoints for agents.",
                    "stargazers_count": 123,
                    "language": "TypeScript",
                    "updated_at": "2026-06-24T00:00:00Z",
                }
            ],
        }


class FakeDuckDuckGoSearch(DuckDuckGoHtmlSearchAdapter):
    def _fetch_text(self, url):
        assert url == "https://lite.duckduckgo.com/lite/?q=agent+browser+modules"
        return """<html><body>
        <a rel="nofollow" href="/l/?uddg=https%3A%2F%2Fexample.com%2Fddg-agent-browser">Agent browser modules</a>
        <a href="https://duckduckgo.com/about">About DuckDuckGo</a>
        </body></html>"""


def test_jina_reader_requires_explicit_allowance(tmp_path):
    result = ResearchEngine(registry=AdapterRegistry([FakeJinaReader()]), home=tmp_path).run(
        {
            "query": "Read with default policy",
            "source_hints": ["https://example.com/article"],
        }
    )

    assert result["status"] == "partial"
    assert result["results"] == []
    assert result["receipt"]["attempts"][0]["module"] == "research.core"
    assert result["receipt"]["attempts"][0]["reason"] == "no_adapter_for_source_hint"


def test_jina_reader_reads_when_explicitly_allowed(tmp_path):
    result = ResearchEngine(registry=AdapterRegistry([FakeJinaReader()]), home=tmp_path).run(
        {
            "query": "Read with Jina",
            "source_hints": ["https://example.com/article"],
            "allowed_modules": ["read.jina"],
        }
    )

    assert result["status"] == "ok"
    item = result["results"][0]
    assert item["title"] == "Jina Article"
    assert item["content_markdown"].startswith("# Jina Article")
    assert "external_reader" in item["limits"]
    assert result["receipt"]["module_chain"] == ["read.jina"]


def test_jina_search_reads_explicit_search_hint(tmp_path):
    result = ResearchEngine(registry=AdapterRegistry([FakeJinaSearch()]), home=tmp_path).run(
        {
            "query": "agent browser modules",
            "intent": "search",
            "source_hints": ["search:jina:agent browser modules"],
            "allowed_modules": ["search.jina"],
        }
    )

    assert result["status"] == "ok"
    item = result["results"][0]
    assert item["platform"] == "web_search"
    assert item["title"] == "Jina search: agent browser modules"
    assert "jina_search" in item["limits"]
    assert {"label": "Agent browser modules", "url": "https://example.com/jina-agent-browser"} in item["citations"]
    assert {"label": "https://example.com/raw-result", "url": "https://example.com/raw-result"} in item["citations"]
    assert "test-jina-key" not in str(result)


def test_news_rss_search_reads_public_feed(tmp_path):
    result = ResearchEngine(registry=AdapterRegistry([FakeNewsRssSearch()]), home=tmp_path).run(
        {
            "query": "agent browser modules",
            "intent": "search",
            "source_hints": ["search:news_rss:agent browser modules"],
            "allowed_modules": ["search.news_rss"],
        }
    )

    assert result["status"] == "ok"
    item = result["results"][0]
    assert item["platform"] == "web_search"
    assert item["title"] == "News RSS search: agent browser modules"
    assert "Agent browsers get modular" in item["content_markdown"]
    assert "public_rss_search" in item["limits"]
    assert "search_results_not_deep_read" in item["limits"]


def test_duckduckgo_html_search_reads_public_results(tmp_path):
    result = ResearchEngine(registry=AdapterRegistry([FakeDuckDuckGoSearch()]), home=tmp_path).run(
        {
            "query": "agent browser modules",
            "intent": "search",
            "source_hints": ["search:ddg_html:agent browser modules"],
            "allowed_modules": ["search.ddg_html"],
        }
    )

    assert result["status"] == "ok"
    item = result["results"][0]
    assert item["platform"] == "web_search"
    assert item["title"] == "DuckDuckGo HTML search: agent browser modules"
    assert {"label": "Agent browser modules", "url": "https://example.com/ddg-agent-browser"} in item["citations"]
    assert "public_html_search" in item["limits"]


def test_github_repos_search_reads_public_results(tmp_path):
    result = ResearchEngine(registry=AdapterRegistry([FakeGitHubReposSearch()]), home=tmp_path).run(
        {
            "query": "agent browser modules",
            "intent": "search",
            "source_hints": ["search:github:agent browser modules"],
            "allowed_modules": ["search.github_repos"],
        }
    )

    assert result["status"] == "ok"
    item = result["results"][0]
    assert item["platform"] == "web_search"
    assert item["title"] == "GitHub repository search: agent browser modules"
    assert {"label": "example/agent-browser", "url": "https://github.com/example/agent-browser"} in item["citations"]
    assert "github_repository_search" in item["limits"]
    assert "Composable browser hardpoints for agents." in item["content_markdown"]


def test_search_auto_expands_to_allowed_search_modules(tmp_path):
    result = ResearchEngine(registry=AdapterRegistry([FakeDuckDuckGoSearch(), FakeNewsRssSearch(), FakeJinaSearch()]), home=tmp_path).run(
        {
            "query": "agent browser modules",
            "intent": "gather",
            "source_hints": ["search:auto:agent browser modules"],
            "allowed_modules": ["search.ddg_html", "search.news_rss", "search.jina"],
        }
    )

    assert result["status"] == "ok"
    assert result["receipt"]["module_chain"] == ["search.ddg_html", "search.news_rss", "search.jina"]
    assert result["receipt"]["policy"]["source_hints_used"] == [
        "search:ddg_html:agent browser modules",
        "search:news_rss:agent browser modules",
        "search:jina:agent browser modules",
    ]
    assert result["receipt"]["policy"]["auto_search_modules"] == ["search.ddg_html", "search.news_rss", "search.jina"]
    assert [item["platform"] for item in result["results"]] == ["web_search", "web_search", "web_search"]


def test_search_auto_expands_github_only_when_github_is_requested(tmp_path):
    result = ResearchEngine(registry=AdapterRegistry([FakeGitHubReposSearch()]), home=tmp_path).run(
        {
            "query": "agent browser modules GitHub",
            "intent": "gather",
            "source_hints": ["search:auto:agent browser modules GitHub"],
            "allowed_modules": ["search.github_repos"],
        }
    )

    assert result["status"] == "ok"
    assert result["receipt"]["module_chain"] == ["search.github_repos"]
    assert result["receipt"]["policy"]["source_hints_used"] == ["search:github:agent browser modules GitHub"]
    assert result["receipt"]["policy"]["auto_search_modules"] == ["search.github_repos"]


def test_search_auto_social_loadout_adds_platform_hints(tmp_path, monkeypatch):
    class FakeRedditSearchOAuth(RedditOAuthAdapter):
        def _bearer_token(self):
            return "test-reddit-token"

        def _fetch_oauth_json(self, url, *, token):
            assert token == "test-reddit-token"
            assert url == "https://oauth.reddit.com/search.json?q=agent+browser+modules&sort=relevance&t=month&limit=100&raw_json=1"
            return (
                {
                    "data": {
                        "children": [
                            {
                                "kind": "t3",
                                "data": {
                                    "title": "Agent browser modules",
                                    "subreddit": "Agentlas",
                                    "author": "mason",
                                    "permalink": "/r/Agentlas/comments/abc/agent_browser_modules/",
                                    "selftext": "Use detachable browser hardpoints.",
                                },
                            }
                        ]
                    }
                },
                ["reddit_rate_remaining:99"],
            )

    monkeypatch.setenv("AGENTLAS_REDDIT_BEARER_TOKEN", "test-reddit-token")
    monkeypatch.setenv("AGENTLAS_THREADS_ACCESS_TOKEN", "test-token")
    registry = AdapterRegistry([FakeDuckDuckGoSearch(), FakeRedditSearchOAuth(), FakeReddit(), FakeThreads(), ThreadsPublicWebAdapter()])

    result = ResearchEngine(registry=registry, home=tmp_path).run(
        {
            "query": "agent browser modules",
            "intent": "gather",
            "source_hints": ["search:auto:agent browser modules"],
            "loadout": "social",
            "query_variants": ["reddit", "threads"],
            "max_cost": {"requests": 4},
        }
    )

    assert result["status"] == "ok"
    assert result["request"]["loadout"] == "social"
    assert result["receipt"]["policy"]["source_hints_used"] == [
        "search:ddg_html:agent browser modules",
        "search:news_rss:agent browser modules",
        "reddit:search:agent browser modules",
        "threads:keyword:agent browser modules",
    ]
    assert result["receipt"]["policy"]["source_hint_budget_limited"] is True
    assert result["receipt"]["module_chain"] == ["search.ddg_html", "platform.reddit.oauth", "platform.threads"]
    assert "platform.reddit.oauth" in result["request"]["allowed_modules"]
    assert "platform.threads" in result["request"]["allowed_modules"]


def test_social_source_budget_keeps_reddit_threads_and_public_threads_fallback(tmp_path, monkeypatch):
    class FlexibleDuckDuckGo(DuckDuckGoHtmlSearchAdapter):
        def _fetch_text(self, url):
            if url == "https://lite.duckduckgo.com/lite/?q=agent+browser+Threads+site%3Athreads.com":
                return """<html><body>
                <a rel="nofollow" href="/l/?uddg=https%3A%2F%2Fwww.threads.com%2F%40agentlas%2Fpost%2Fabc">Threads fallback</a>
                </body></html>"""
            assert url == "https://lite.duckduckgo.com/lite/?q=agent+browser"
            return """<html><body>
            <a rel="nofollow" href="/l/?uddg=https%3A%2F%2Fexample.com%2Fddg-agent-browser">Agent browser modules</a>
            </body></html>"""

    monkeypatch.delenv("THREADS_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("AGENTLAS_THREADS_ACCESS_TOKEN", raising=False)
    result = ResearchEngine(
        registry=AdapterRegistry([FlexibleDuckDuckGo(), FakeRedditListing(), ThreadsSearchAdapter()]),
        home=tmp_path,
    ).run(
        {
            "query": "agent browser",
            "intent": "gather",
            "source_hints": ["search:auto:agent browser"],
            "loadout": "social",
            "query_variants": ["reddit", "threads"],
            "max_cost": {"requests": 4},
        }
    )

    assert result["status"] == "ok"
    assert result["receipt"]["policy"]["source_hints_used"] == [
        "search:ddg_html:agent browser",
        "reddit:search:agent browser",
        "threads:keyword:agent browser",
        "search:ddg_html:agent browser Threads site:threads.com",
    ]
    assert result["receipt"]["policy"]["source_hints_dropped_by_budget"] == [
        "search:news_rss:agent browser",
        "search:ddg_html:agent browser Reddit site:reddit.com",
        "search:news_rss:agent browser Reddit site:reddit.com",
        "search:news_rss:agent browser Threads site:threads.com",
        "search:ddg_html:agent browser reddit",
        "search:news_rss:agent browser reddit",
    ]
    assert result["receipt"]["attempts"][1]["module"] == "platform.reddit"
    assert result["receipt"]["attempts"][2]["module"] == "platform.threads"
    assert result["receipt"]["attempts"][2]["status"] == "module_unavailable"
    assert result["results"][1]["platform"] == "reddit"
    assert result["results"][2]["platform"] == "web_search"
    coverage = result["receipt"]["policy"]["evidence_coverage"]
    assert coverage["public_social_fallback_evidence"] is True
    assert coverage["public_social_fallback_platforms"] == ["reddit", "threads"]
    assert coverage["social_platforms"] == ["reddit", "threads"]
    assert coverage["official_social_modules_missing"] == ["platform.reddit.oauth", "platform.threads"]
    assert coverage["completion_blockers"] == ["reddit_oauth_live_check", "threads_live_graph_check"]


def test_social_budget_reserves_followup_reads_for_public_threads_fallback(tmp_path, monkeypatch):
    class SearchWithThreadsFallback(DuckDuckGoHtmlSearchAdapter):
        def _fetch_text(self, url):
            if url == "https://lite.duckduckgo.com/lite/?q=agent+browser+Threads+site%3Athreads.com":
                return """<html><body>
                <a rel="nofollow" href="/l/?uddg=https%3A%2F%2Fwww.threads.com%2F%40agentlas%2Fpost%2Fabc">Threads fallback</a>
                </body></html>"""
            assert url == "https://lite.duckduckgo.com/lite/?q=agent+browser"
            return "<html><body>No direct results here.</body></html>"

    class FollowThreadsPublic(ThreadsPublicWebAdapter):
        def _fetch(self, url):
            assert url == "https://www.threads.com/@agentlas/post/abc"
            return (
                200,
                """
                <html>
                  <head>
                    <title>Agentlas on Threads</title>
                    <meta property="og:title" content="Agentlas on Threads" />
                    <meta property="og:description" content="A public Threads result was followed." />
                  </head>
                  <body>Followed Threads post.</body>
                </html>
                """,
                url,
                "text/html; charset=utf-8",
            )

    monkeypatch.delenv("THREADS_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("AGENTLAS_THREADS_ACCESS_TOKEN", raising=False)
    result = ResearchEngine(
        registry=AdapterRegistry([SearchWithThreadsFallback(), FakeRedditListing(), ThreadsSearchAdapter(), FollowThreadsPublic()]),
        home=tmp_path,
    ).run(
        {
            "query": "agent browser",
            "intent": "gather",
            "source_hints": ["search:auto:agent browser"],
            "loadout": "social",
            "query_variants": ["reddit", "threads"],
            "follow_results": 3,
            "max_cost": {"requests": 7},
        }
    )

    assert result["status"] == "ok"
    assert result["receipt"]["policy"]["source_hints_used"] == [
        "search:ddg_html:agent browser",
        "reddit:search:agent browser",
        "threads:keyword:agent browser",
        "search:ddg_html:agent browser Threads site:threads.com",
    ]
    assert result["receipt"]["policy"]["source_hint_count_after_budget"] == 4
    assert result["receipt"]["policy"]["request_budget"]["followup_limit_after_budget"] == 3
    assert result["receipt"]["policy"]["followup_count"] == 1
    assert result["receipt"]["policy"]["followup_budget_limited"] is False
    assert "platform.threads.public" in result["receipt"]["module_chain"]
    followed = next(item for item in result["results"] if item["platform"] == "threads")
    assert followed["title"] == "Agentlas on Threads"
    assert "followup_read" in followed["limits"]
    coverage = result["receipt"]["policy"]["evidence_coverage"]
    assert coverage["public_social_fallback_platforms"] == ["reddit", "threads"]


def test_search_auto_expands_query_variants_without_new_modules(tmp_path):
    seen_urls: list[str] = []

    class VariantDuckDuckGo(DuckDuckGoHtmlSearchAdapter):
        def _fetch_text(self, url):
            seen_urls.append(url)
            return f"""<html><body><a href="/l/?uddg=https%3A%2F%2Fexample.com%2F{len(seen_urls)}">Variant {len(seen_urls)}</a></body></html>"""

    result = ResearchEngine(registry=AdapterRegistry([VariantDuckDuckGo()]), home=tmp_path).run(
        {
            "query": "agent browser modules",
            "intent": "gather",
            "source_hints": ["search:auto:agent browser modules"],
            "allowed_modules": ["search.ddg_html"],
            "query_variants": ["docs", "reddit", "threads"],
        }
    )

    assert result["status"] == "ok"
    assert seen_urls == [
        "https://lite.duckduckgo.com/lite/?q=agent+browser+modules",
        "https://lite.duckduckgo.com/lite/?q=agent+browser+modules+documentation+docs",
        "https://lite.duckduckgo.com/lite/?q=agent+browser+modules+reddit",
        "https://lite.duckduckgo.com/lite/?q=agent+browser+modules+Threads+site%3Athreads.com",
    ]
    assert result["request"]["query_variants"] == ["docs", "reddit", "threads"]
    assert result["receipt"]["module_chain"] == ["search.ddg_html"]
    assert result["receipt"]["policy"]["source_hints_used"] == [
        "search:ddg_html:agent browser modules",
        "search:ddg_html:agent browser modules documentation docs",
        "search:ddg_html:agent browser modules reddit",
        "search:ddg_html:agent browser modules Threads site:threads.com",
    ]
    assert result["receipt"]["policy"]["query_variants"] == ["docs", "reddit", "threads"]


def test_search_query_variants_respect_source_request_budget(tmp_path):
    seen_urls: list[str] = []

    class VariantDuckDuckGo(DuckDuckGoHtmlSearchAdapter):
        def _fetch_text(self, url):
            seen_urls.append(url)
            return """<html><body><a href="/l/?uddg=https%3A%2F%2Fexample.com%2Fbudget">Budgeted</a></body></html>"""

    result = ResearchEngine(registry=AdapterRegistry([VariantDuckDuckGo()]), home=tmp_path).run(
        {
            "query": "agent browser modules",
            "intent": "gather",
            "source_hints": ["search:auto:agent browser modules"],
            "allowed_modules": ["search.ddg_html"],
            "query_variants": ["docs", "reddit", "github"],
            "max_cost": {"requests": 2, "tokens": 2000, "seconds": 30},
        }
    )

    assert len(seen_urls) == 2
    assert result["receipt"]["policy"]["source_hint_count_before_budget"] == 4
    assert result["receipt"]["policy"]["source_hint_count_after_budget"] == 2
    assert result["receipt"]["policy"]["source_hint_budget_limited"] is True
    assert result["receipt"]["policy"]["source_hints_used"] == [
        "search:ddg_html:agent browser modules",
        "search:ddg_html:agent browser modules documentation docs",
    ]
    assert result["receipt"]["policy"]["source_hints_dropped_by_budget"] == [
        "search:ddg_html:agent browser modules reddit",
        "search:ddg_html:agent browser modules GitHub",
    ]
    assert result["receipt"]["policy"]["request_budget"] == {
        "max_requests": 2,
        "source_hint_count_before_budget": 4,
        "source_hint_count_after_budget": 2,
        "source_hint_budget_limited": True,
        "source_hints_dropped_by_budget": [
            "search:ddg_html:agent browser modules reddit",
            "search:ddg_html:agent browser modules GitHub",
        ],
        "followup_requested": 0,
        "followup_limit_after_budget": 0,
        "followup_count": 0,
        "followup_budget_limited": False,
    }


def test_search_follow_results_reads_top_urls(tmp_path):
    class FollowReader(HttpReaderAdapter):
        manifest = HttpReaderAdapter.manifest

        def _fetch(self, url):
            assert url == "https://example.com/agent-browser"
            return (
                200,
                "<html><head><title>Followed</title></head><body>Full source evidence</body></html>",
                url,
                "text/html",
            )

    result = ResearchEngine(registry=AdapterRegistry([FakeNewsRssSearch(), FollowReader()]), home=tmp_path).run(
        {
            "query": "agent browser modules",
            "intent": "search",
            "source_hints": ["search:news_rss:agent browser modules"],
            "loadout": "safe",
            "follow_results": 1,
        }
    )

    assert result["status"] == "ok"
    assert result["request"]["follow_results"] == 1
    assert result["receipt"]["policy"]["followup_count"] == 1
    assert result["receipt"]["module_chain"] == ["search.news_rss", "read.http"]
    followed = next(item for item in result["results"] if item["platform"] == "web")
    assert followed["title"] == "Followed"
    assert "Full source evidence" in followed["content_markdown"]
    assert "followup_read" in followed["limits"]
    assert any(
        attempt["module"] == "read.http" and attempt["reason"].startswith("followup:")
        for attempt in result["receipt"]["attempts"]
    )
    quality = result["receipt"]["policy"]["evidence_quality"]
    assert quality["status"] in {"usable", "strong"}
    assert quality["direct_read_count"] == 1
    assert quality["search_result_count"] == 1
    assert quality["source_class_counts"]["web"] >= 1


def test_evidence_quality_marks_search_snippets_as_thin(tmp_path):
    result = ResearchEngine(registry=AdapterRegistry([FakeDuckDuckGoSearch()]), home=tmp_path).run(
        {
            "query": "agent browser modules",
            "intent": "search",
            "source_hints": ["search:ddg_html:agent browser modules"],
            "allowed_modules": ["search.ddg_html"],
        }
    )

    quality = result["receipt"]["policy"]["evidence_quality"]
    assert quality["status"] == "thin"
    assert quality["direct_read_count"] == 0
    assert quality["search_result_count"] == 1
    assert "search_snippet" in quality["source_class_counts"]
    assert "increase_follow_results_to_read_cited_pages" in quality["recommendations"]
    coverage = result["receipt"]["policy"]["evidence_coverage"]
    assert coverage["status"] == "search_only"
    assert coverage["search_only"] is True
    assert coverage["direct_read_evidence"] is False
    assert "search_snippets_need_followup" in coverage["warnings"]


def test_search_followup_ranks_direct_urls_over_search_shells(tmp_path):
    class SearchWithShellFirst:
        module_id = "search.fake"
        capabilities = ("search.web",)
        weight = "light"
        manifest = ResearchModuleManifest(module_id=module_id, capabilities=list(capabilities), slot="search")

        def can_handle(self, source_hint, request):
            return source_hint == "search:fake:agent browser modules"

        def read(self, source_hint, request):
            result = ResearchResult(
                source_id="fake_search",
                url="https://search.example.test?q=agent+browser+modules",
                title="Fake search",
                platform="web_search",
                content_markdown="- search shell\n- direct source",
                confidence="usable",
                limits=["public_html_search"],
                citations=[
                    {"label": "fake search", "url": "https://search.example.test?q=agent+browser+modules"},
                    {"label": "Google News shell", "url": "https://news.google.com/rss/articles/abc?oc=5"},
                    {"label": "Agent browser modules", "url": "https://example.com/agent-browser"},
                ],
            )
            return result, ResearchAttempt(self.module_id, "ok", "fake_search", source_hint, weight=self.weight)

    class FollowReader(HttpReaderAdapter):
        manifest = HttpReaderAdapter.manifest

        def _fetch(self, url):
            assert url == "https://example.com/agent-browser"
            return (
                200,
                "<html><head><title>Direct</title></head><body>Direct source</body></html>",
                url,
                "text/html",
            )

    result = ResearchEngine(registry=AdapterRegistry([SearchWithShellFirst(), FollowReader()]), home=tmp_path).run(
        {
            "query": "agent browser modules",
            "intent": "search",
            "source_hints": ["search:fake:agent browser modules"],
            "follow_results": 1,
            "allowed_modules": ["search.fake", "read.http"],
        }
    )

    assert result["status"] == "ok"
    assert result["receipt"]["policy"]["followup_ranker"] == "score_v3_social_diverse"
    assert result["receipt"]["policy"]["followup_candidates"][0]["url"] == "https://example.com/agent-browser"
    assert "direct_url" in result["receipt"]["policy"]["followup_candidates"][0]["reasons"]
    assert result["receipt"]["policy"]["search_candidate_report"]["direct_candidates"] == 1
    assert result["receipt"]["policy"]["search_candidate_report"]["search_shell_candidates"] == 1
    followed = next(item for item in result["results"] if item["platform"] == "web")
    assert followed["title"] == "Direct"


def test_search_followup_prioritizes_requested_social_hosts(tmp_path):
    class MixedSocialSearch:
        module_id = "search.fake"
        capabilities = ("search.web",)
        weight = "light"
        manifest = ResearchModuleManifest(module_id=module_id, capabilities=list(capabilities), slot="search")

        def can_handle(self, source_hint, request):
            return source_hint == "search:fake:agent browser Reddit site:reddit.com"

        def read(self, source_hint, request):
            result = ResearchResult(
                source_id="fake_social_search",
                url="https://search.example.test?q=agent+browser+Reddit",
                title="Fake social search",
                platform="web_search",
                content_markdown="- generic article\n- reddit reaction thread",
                confidence="usable",
                limits=["public_html_search"],
                citations=[
                    {"label": "Generic agent browser article", "url": "https://example.com/agent-browser"},
                    {"label": "Reddit reaction thread", "url": "https://www.reddit.com/r/Agentlas/comments/abc/agent_browser/"},
                ],
            )
            return result, ResearchAttempt(self.module_id, "ok", "fake_search", source_hint, weight=self.weight)

    result = ResearchEngine(registry=AdapterRegistry([MixedSocialSearch(), FakeReddit(), FakeReader()]), home=tmp_path).run(
        {
            "query": "agent browser Reddit 반응",
            "intent": "search",
            "source_hints": ["search:fake:agent browser Reddit site:reddit.com"],
            "follow_results": 1,
            "allowed_modules": ["search.fake", "read.http", "platform.reddit"],
            "max_cost": {"requests": 3},
        }
    )

    candidates = result["receipt"]["policy"]["followup_candidates"]
    assert candidates[0]["url"] == "https://www.reddit.com/r/Agentlas/comments/abc/agent_browser"
    assert "social_host_requested" in candidates[0]["reasons"]
    assert result["receipt"]["policy"]["followup_count"] == 1
    assert result["receipt"]["attempts"][-1]["module"] == "platform.reddit"
    followed = next(item for item in result["results"] if item["platform"] == "reddit")
    assert followed["title"] == "Agent browsers?"
    assert "followup_read" in followed["limits"]


def test_search_followup_uses_search_source_social_context(tmp_path):
    class ThreadsContextSearch:
        module_id = "search.fake"
        capabilities = ("search.web",)
        weight = "light"
        manifest = ResearchModuleManifest(module_id=module_id, capabilities=list(capabilities), slot="search")

        def can_handle(self, source_hint, request):
            return source_hint == "search:fake:agent browser Threads site:threads.com"

        def read(self, source_hint, request):
            result = ResearchResult(
                source_id="fake_threads_search",
                url="https://search.example.test?q=agent+browser+Threads+site%3Athreads.com",
                title="Fake search: agent browser Threads site:threads.com",
                platform="web_search",
                content_markdown="- generic article\n- threads source",
                confidence="usable",
                limits=["public_html_search"],
                citations=[
                    {"label": "Generic agent browser article", "url": "https://example.com/agent-browser"},
                    {"label": "Threads source", "url": "https://www.threads.com/@agentlas/post/abc"},
                ],
            )
            return result, ResearchAttempt(self.module_id, "ok", "fake_search", source_hint, weight=self.weight)

    class FollowThreadsPost(ThreadsPublicWebAdapter):
        def _fetch(self, url):
            assert url == "https://www.threads.com/@agentlas/post/abc"
            return (
                200,
                """
                <html>
                  <head>
                    <title>Agentlas post on Threads</title>
                    <meta property="og:title" content="Agentlas post on Threads" />
                    <meta property="og:description" content="Threads source was followed." />
                  </head>
                  <body>Threads post body.</body>
                </html>
                """,
                url,
                "text/html; charset=utf-8",
            )

    result = ResearchEngine(registry=AdapterRegistry([ThreadsContextSearch(), FollowThreadsPost(), FakeReader()]), home=tmp_path).run(
        {
            "query": "agent browser",
            "intent": "search",
            "source_hints": ["search:fake:agent browser Threads site:threads.com"],
            "follow_results": 1,
            "allowed_modules": ["search.fake", "read.http", "platform.threads.public"],
            "max_cost": {"requests": 3},
        }
    )

    candidates = result["receipt"]["policy"]["followup_candidates"]
    assert candidates[0]["url"] == "https://www.threads.com/@agentlas/post/abc"
    assert "social_host_requested" in candidates[0]["reasons"]
    assert result["receipt"]["attempts"][-1]["module"] == "platform.threads.public"


def test_search_followup_diversifies_hosts_before_second_same_domain(tmp_path):
    class SearchWithDominantHost:
        module_id = "search.fake"
        capabilities = ("search.web",)
        weight = "light"
        manifest = ResearchModuleManifest(module_id=module_id, capabilities=list(capabilities), slot="search")

        def can_handle(self, source_hint, request):
            return source_hint == "search:fake:agent browser modules"

        def read(self, source_hint, request):
            result = ResearchResult(
                source_id="fake_search",
                url="https://search.example.test?q=agent+browser+modules",
                title="Fake search",
                platform="web_search",
                confidence="usable",
                limits=["public_html_search"],
                citations=[
                    {"label": "Agent browser alpha", "url": "https://dominant.example/alpha"},
                    {"label": "Agent browser beta", "url": "https://dominant.example/beta"},
                    {"label": "Agent browser outside", "url": "https://outside.example/research"},
                ],
            )
            return result, ResearchAttempt(self.module_id, "ok", "fake_search", source_hint, weight=self.weight)

    class FollowReader(HttpReaderAdapter):
        def _fetch(self, url):
            assert url in {"https://dominant.example/alpha", "https://outside.example/research"}
            title = "Dominant" if "dominant" in url else "Outside"
            return 200, f"<html><head><title>{title}</title></head><body>{title}</body></html>", url, "text/html"

    result = ResearchEngine(registry=AdapterRegistry([SearchWithDominantHost(), FollowReader()]), home=tmp_path).run(
        {
            "query": "agent browser modules",
            "intent": "search",
            "source_hints": ["search:fake:agent browser modules"],
            "follow_results": 2,
            "allowed_modules": ["search.fake", "read.http"],
        }
    )

    candidates = result["receipt"]["policy"]["followup_candidates"]
    assert [candidate["host"] for candidate in candidates] == ["dominant.example", "outside.example"]
    report = result["receipt"]["policy"]["search_candidate_report"]
    assert report["total_candidates"] == 3
    assert report["unique_hosts"] == 2
    assert report["host_counts"]["dominant.example"] == 2
    assert report["diversity_strategy"] == "host_round_robin_v1"


def test_search_followup_respects_request_budget(tmp_path):
    result = ResearchEngine(registry=AdapterRegistry([FakeDuckDuckGoSearch(), FakeReader()]), home=tmp_path).run(
        {
            "query": "agent browser modules",
            "intent": "search",
            "source_hints": ["search:ddg_html:agent browser modules"],
            "follow_results": 3,
            "allowed_modules": ["search.ddg_html", "read.http"],
            "max_cost": {"requests": 1, "tokens": 2000, "seconds": 30},
        }
    )

    assert result["status"] == "ok"
    assert result["receipt"]["policy"]["followup_requested"] == 3
    assert result["receipt"]["policy"]["followup_count"] == 0
    assert result["receipt"]["policy"]["followup_budget_limited"] is True
    assert result["receipt"]["policy"]["followup_candidates"] == []
    assert result["receipt"]["policy"]["request_budget"]["followup_requested"] == 3
    assert result["receipt"]["policy"]["request_budget"]["followup_limit_after_budget"] == 0
    assert result["receipt"]["policy"]["request_budget"]["followup_budget_limited"] is True
    assert result["receipt"]["policy"]["search_candidate_report"]["total_candidates"] == 1
    assert result["receipt"]["module_chain"] == ["search.ddg_html"]


def test_research_cli_search_defaults_to_duckduckgo_html(tmp_path, monkeypatch, capsys):
    def fake_fetch_text(self, url):
        assert url == "https://lite.duckduckgo.com/lite/?q=agent+browser+modules"
        return """<html><body><a href="/l/?uddg=https%3A%2F%2Fexample.com%2Fsearch">CLI web search works</a></body></html>"""

    monkeypatch.setattr(DuckDuckGoHtmlSearchAdapter, "_fetch_text", fake_fetch_text)
    code = main(["research", "search", "agent", "browser", "modules", "--home", str(tmp_path)])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "agentlas.research.v0"
    assert payload["request"]["intent"] == "search"
    assert payload["request"]["allowed_modules"] == ["search.ddg_html"]
    assert payload["results"][0]["platform"] == "web_search"
    assert "CLI web search works" in payload["results"][0]["content_markdown"]


def test_research_cli_search_accepts_query_variants(tmp_path, monkeypatch, capsys):
    seen_urls: list[str] = []

    def fake_fetch_text(self, url):
        seen_urls.append(url)
        return """<html><body><a href="/l/?uddg=https%3A%2F%2Fexample.com%2Fvariant">CLI variant search works</a></body></html>"""

    monkeypatch.setattr(DuckDuckGoHtmlSearchAdapter, "_fetch_text", fake_fetch_text)
    code = main(
        [
            "research",
            "search",
            "agent",
            "browser",
            "modules",
            "--variant",
            "docs",
            "--home",
            str(tmp_path),
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert seen_urls == [
        "https://lite.duckduckgo.com/lite/?q=agent+browser+modules",
        "https://lite.duckduckgo.com/lite/?q=agent+browser+modules+documentation+docs",
    ]
    assert payload["request"]["query_variants"] == ["docs"]
    assert payload["receipt"]["policy"]["source_hints_used"] == [
        "search:ddg_html:agent browser modules",
        "search:ddg_html:agent browser modules documentation docs",
    ]


def test_research_cli_search_can_follow_results(tmp_path, monkeypatch, capsys):
    def fake_fetch_text(self, url):
        assert url == "https://news.google.com/rss/search?q=agent+browser+modules&hl=en-US&gl=US&ceid=US:en"
        return """<?xml version="1.0"?><rss><channel><title>agent browser modules</title><item><title>Follow me</title><link>https://example.com/follow</link><description>Read the full source.</description></item></channel></rss>"""

    def fake_fetch(self, url):
        assert url == "https://example.com/follow"
        return (
            200,
            "<html><head><title>Follow CLI</title></head><body>CLI followed result</body></html>",
            url,
            "text/html",
        )

    monkeypatch.setattr(NewsRssSearchAdapter, "_fetch_text", fake_fetch_text)
    monkeypatch.setattr(HttpReaderAdapter, "_fetch", fake_fetch)
    code = main(
        [
            "research",
            "search",
            "agent",
            "browser",
            "modules",
            "--provider",
            "news-rss",
            "--loadout",
            "safe",
            "--follow-results",
            "1",
            "--home",
            str(tmp_path),
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["request"]["follow_results"] == 1
    assert payload["receipt"]["policy"]["followup_count"] == 1
    assert any(item["title"] == "Follow CLI" for item in payload["results"])


def test_research_cli_plan_resolves_recommended_social_query_to_public_web(tmp_path, capsys):
    code = main(
        [
            "research",
            "plan",
            "--search",
            "--query",
            "Threads와 Reddit 반응까지 조사",
            "--loadout",
            "recommended",
            "--home",
            str(tmp_path),
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "agentlas.research.plan.v0"
    assert payload["request"]["loadout"] == "public-web"
    assert payload["request"]["follow_results"] == 3
    assert payload["request"]["query_variants"] == ["reddit", "threads"]
    assert payload["request"]["max_cost"]["requests"] == 7
    assert not any(hint.startswith("reddit:search:") for hint in payload["source_hints_before_budget"])
    assert not any(hint.startswith("threads:keyword:") for hint in payload["source_hints_before_budget"])
    assert any("reddit" in hint.lower() for hint in payload["source_hints_before_budget"])
    assert any("threads" in hint.lower() for hint in payload["source_hints_before_budget"])


def test_research_cli_gather_recommended_resolves_before_running(tmp_path, monkeypatch, capsys):
    seen_requests = []

    def fake_research(request, *, home=None):
        seen_requests.append(request)
        return {
            "schema": "agentlas.research.v0",
            "status": "ok",
            "request": {**ResearchRequest.from_value(request).to_dict()},
            "results": [],
            "receipt": {
                "receipt_id": "fake_recommended",
                "module_chain": [],
                "attempts": [],
                "policy": {"evidence_quality": {"status": "missing", "score": 0}},
            },
        }

    monkeypatch.setattr("agentlas_cloud.research.run_research", fake_research)
    code = main(
        [
            "research",
            "gather",
            "agent",
            "browser",
            "modules",
            "--loadout",
            "recommended",
            "--home",
            str(tmp_path),
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["request"]["loadout"] == "browser"
    assert len(seen_requests) == 1
    assert seen_requests[0]["loadout"] == "browser"
    assert seen_requests[0]["follow_results"] == 3
    assert seen_requests[0]["max_cost"]["requests"] == 6
    assert not any(str(key).startswith("_") for key in seen_requests[0])


def test_research_cli_read_can_follow_threads_public_search_fallback(tmp_path, monkeypatch, capsys):
    def fake_ddg_fetch_text(self, url):
        assert url == "https://lite.duckduckgo.com/lite/?q=agent+browser+Threads+site%3Athreads.com"
        return """<html><body>
        <a rel="nofollow" href="/l/?uddg=https%3A%2F%2Fwww.threads.com%2F%40agentlas%2Fpost%2Fabc">Agent browser on Threads</a>
        </body></html>"""

    def fake_threads_fetch(self, url):
        assert url == "https://www.threads.com/@agentlas/post/abc"
        return (
            200,
            """
            <html>
              <head>
                <title>Agentlas on Threads</title>
                <meta property="og:title" content="Agentlas on Threads" />
                <meta property="og:description" content="Public Threads post about agent browsers." />
              </head>
              <body><main>Public Threads page body.</main></body>
            </html>
            """,
            url,
            "text/html; charset=utf-8",
        )

    monkeypatch.delenv("THREADS_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("AGENTLAS_THREADS_ACCESS_TOKEN", raising=False)
    monkeypatch.setattr(DuckDuckGoHtmlSearchAdapter, "_fetch_text", fake_ddg_fetch_text)
    monkeypatch.setattr(ThreadsPublicWebAdapter, "_fetch", fake_threads_fetch)

    code = main(
        [
            "research",
            "read",
            "threads:keyword:agent browser",
            "--loadout",
            "auto",
            "--follow-results",
            "1",
            "--max-requests",
            "3",
            "--forbid-module",
            "search.news_rss",
            "--home",
            str(tmp_path),
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["request"]["follow_results"] == 1
    assert payload["receipt"]["policy"]["source_hints_used"] == [
        "search:ddg_html:agent browser Threads site:threads.com",
    ]
    assert payload["receipt"]["policy"]["followup_count"] == 1
    assert payload["receipt"]["module_chain"] == ["search.ddg_html", "platform.threads.public"]
    assert any(item["platform"] == "threads" and item["title"] == "Agentlas on Threads" for item in payload["results"])


def test_research_cli_gather_defaults_to_public_web_followup(tmp_path, monkeypatch, capsys):
    def fake_news_fetch_text(self, url):
        assert url == "https://news.google.com/rss/search?q=agent+browser+modules&hl=en-US&gl=US&ceid=US:en"
        return """<?xml version="1.0"?><rss><channel><title>agent browser modules</title><item><title>Gather news</title><link>https://example.com/gather-news</link><description>Read this gathered result.</description></item></channel></rss>"""

    def fake_ddg_fetch_text(self, url):
        assert url == "https://lite.duckduckgo.com/lite/?q=agent+browser+modules"
        return """<html><body><a href="/l/?uddg=https%3A%2F%2Fexample.com%2Fgather-ddg">Gather web</a></body></html>"""

    def fake_fetch(self, url):
        assert url in {"https://example.com/gather-ddg", "https://example.com/gather-news"}
        title = "Gather DDG" if url.endswith("gather-ddg") else "Gather News"
        return (
            200,
            f"<html><head><title>{title}</title></head><body>Gather followed result</body></html>",
            url,
            "text/html",
        )

    monkeypatch.setattr(DuckDuckGoHtmlSearchAdapter, "_fetch_text", fake_ddg_fetch_text)
    monkeypatch.setattr(NewsRssSearchAdapter, "_fetch_text", fake_news_fetch_text)
    monkeypatch.setattr(HttpReaderAdapter, "_fetch", fake_fetch)
    code = main(["research", "gather", "agent", "browser", "modules", "--home", str(tmp_path)])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["request"]["intent"] == "gather"
    assert payload["request"]["loadout"] == "public-web"
    assert payload["request"]["follow_results"] == 3
    assert payload["receipt"]["policy"]["source_hints_used"] == [
        "search:ddg_html:agent browser modules",
        "search:news_rss:agent browser modules",
    ]
    assert payload["receipt"]["policy"]["followup_count"] == 2
    assert payload["receipt"]["module_chain"] == ["search.ddg_html", "search.news_rss", "read.http"]
    assert any(item["title"] == "Gather DDG" for item in payload["results"])
    assert any(item["title"] == "Gather News" for item in payload["results"])


def test_research_cli_gather_can_mount_multiple_search_providers(tmp_path, monkeypatch, capsys):
    def fake_news_fetch_text(self, url):
        assert url == "https://news.google.com/rss/search?q=agent+browser+modules&hl=en-US&gl=US&ceid=US:en"
        return """<?xml version="1.0"?><rss><channel><title>agent browser modules</title><item><title>News result</title><link>https://example.com/news</link></item></channel></rss>"""

    def fake_jina_fetch_text(self, url, *, api_key):
        assert api_key == "test-jina-key"
        assert url == "https://s.jina.ai/?q=agent%20browser%20modules"
        return "# Search Results\n\n- [Jina result](https://example.com/jina)"

    monkeypatch.setenv("AGENTLAS_JINA_API_KEY", "test-jina-key")
    monkeypatch.setattr(NewsRssSearchAdapter, "_fetch_text", fake_news_fetch_text)
    monkeypatch.setattr(JinaSearchAdapter, "_fetch_text", fake_jina_fetch_text)
    code = main(
        [
            "research",
            "gather",
            "agent",
            "browser",
            "modules",
            "--provider",
            "news-rss",
            "--provider",
            "jina",
            "--follow-results",
            "0",
            "--home",
            str(tmp_path),
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["receipt"]["module_chain"] == ["search.news_rss", "search.jina"]
    assert payload["receipt"]["policy"]["source_hints_used"] == [
        "search:news_rss:agent browser modules",
        "search:jina:agent browser modules",
    ]
    assert "search.jina" in payload["request"]["allowed_modules"]
    assert "test-jina-key" not in str(payload)


def test_research_cli_search_uses_jina_provider_when_selected(tmp_path, monkeypatch, capsys):
    def fake_fetch_text(self, url, *, api_key):
        assert api_key == "test-jina-key"
        assert url == "https://s.jina.ai/?q=agent%20browser%20modules"
        return "# Search Results\n\n- CLI search works"

    monkeypatch.setenv("AGENTLAS_JINA_API_KEY", "test-jina-key")
    monkeypatch.setattr(JinaSearchAdapter, "_fetch_text", fake_fetch_text)
    code = main(["research", "search", "agent", "browser", "modules", "--provider", "jina", "--home", str(tmp_path)])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "agentlas.research.v0"
    assert payload["request"]["intent"] == "search"
    assert payload["request"]["allowed_modules"] == ["search.jina"]
    assert payload["results"][0]["platform"] == "web_search"
    assert "CLI search works" in payload["results"][0]["content_markdown"]
    assert "test-jina-key" not in str(payload)


def test_research_cli_search_uses_github_provider_when_selected(tmp_path, monkeypatch, capsys):
    def fake_fetch_json(self, url):
        assert url == "https://api.github.com/search/repositories?q=agent+browser+modules&per_page=10"
        return {
            "total_count": 1,
            "incomplete_results": False,
            "items": [
                {
                    "full_name": "example/agent-browser",
                    "html_url": "https://github.com/example/agent-browser",
                    "description": "CLI GitHub provider works.",
                    "stargazers_count": 42,
                    "language": "Python",
                    "updated_at": "2026-06-24T00:00:00Z",
                }
            ],
        }

    monkeypatch.setattr(GitHubReposSearchAdapter, "_fetch_json", fake_fetch_json)
    code = main(["research", "search", "agent", "browser", "modules", "--provider", "github", "--home", str(tmp_path)])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "agentlas.research.v0"
    assert payload["request"]["intent"] == "search"
    assert payload["request"]["allowed_modules"] == ["search.github_repos"]
    assert payload["results"][0]["platform"] == "web_search"
    assert "CLI GitHub provider works." in payload["results"][0]["content_markdown"]


def test_jina_search_missing_key_is_nonfatal(tmp_path, monkeypatch):
    monkeypatch.delenv("AGENTLAS_JINA_API_KEY", raising=False)
    monkeypatch.delenv("JINA_API_KEY", raising=False)
    result = ResearchEngine(registry=AdapterRegistry([JinaSearchAdapter()]), home=tmp_path).run(
        {
            "query": "agent browser modules",
            "intent": "search",
            "source_hints": ["search:jina:agent browser modules"],
            "allowed_modules": ["search.jina"],
        }
    )

    assert result["status"] == "partial"
    assert result["results"] == []
    assert result["receipt"]["attempts"][0]["module"] == "search.jina"
    assert result["receipt"]["attempts"][0]["status"] == "module_unavailable"


def test_external_search_error_redacts_api_key(tmp_path, monkeypatch):
    class FailingJinaSearch(JinaSearchAdapter):
        def _fetch_text(self, url, *, api_key):
            assert api_key == "secret-jina-token"
            raise OSError("search failed Bearer secret-jina-token token=secret-jina-token")

    monkeypatch.setenv("AGENTLAS_JINA_API_KEY", "secret-jina-token")

    result = ResearchEngine(registry=AdapterRegistry([FailingJinaSearch()]), home=tmp_path).run(
        {
            "query": "agent browser modules",
            "intent": "search",
            "source_hints": ["search:jina:agent browser modules"],
            "allowed_modules": ["search.jina"],
        }
    )

    attempt = result["receipt"]["attempts"][0]
    assert result["status"] == "partial"
    assert attempt["module"] == "search.jina"
    assert attempt["status"] == "error"
    assert "[redacted]" in attempt["reason"]
    assert "secret-jina-token" not in str(result)


class FakeInsaneFetch(InsaneFetchAdapter):
    def __init__(self, responses):
        super().__init__()
        self.responses = responses
        self.seen = []

    def _fetch(self, url):
        self.seen.append(url)
        response = self.responses[url]
        if isinstance(response, Exception):
            raise response
        return response


def test_insane_fetch_requires_explicit_allowance(tmp_path):
    adapter = FakeInsaneFetch({})
    result = ResearchEngine(registry=AdapterRegistry([adapter]), home=tmp_path).run(
        {
            "query": "Adaptive read",
            "source_hints": ["https://example.com/blocked"],
        }
    )

    assert result["status"] == "partial"
    assert result["results"] == []
    assert result["receipt"]["attempts"][0]["module"] == "research.core"
    assert adapter.seen == []


def test_insane_fetch_uses_reddit_rss_public_route(tmp_path):
    source_url = "https://www.reddit.com/r/Agentlas/"
    rss_url = "https://www.reddit.com/r/Agentlas.rss?limit=100"
    adapter = FakeInsaneFetch(
        {
            source_url: (403, "blocked", source_url, "text/html"),
            rss_url: (
                200,
                """<?xml version="1.0"?><rss><channel><title>r/Agentlas</title><item><title>Agent browser modules</title><link>https://www.reddit.com/r/Agentlas/comments/1</link><description>Use detachable research hardpoints.</description></item></channel></rss>""",
                rss_url,
                "application/rss+xml",
            ),
        }
    )

    result = ResearchEngine(registry=AdapterRegistry([adapter]), home=tmp_path).run(
        {
            "query": "Adaptive reddit read",
            "source_hints": [source_url],
            "allowed_modules": ["read.insane_fetch"],
        }
    )

    assert result["status"] == "ok"
    item = result["results"][0]
    assert item["platform"] == "reddit"
    assert item["title"] == "r/Agentlas"
    assert "Agent browser modules" in item["content_markdown"]
    assert "route:reddit_rss" in item["limits"]
    assert "stop_reason:route_success" in item["limits"]
    assert "trace:reddit_rss=ok:200" in item["limits"]
    assert "untried_routes:direct,jina_reader" in item["limits"]
    assert result["receipt"]["attempts"][0]["module"] == "read.insane_fetch"
    assert "route=reddit_rss" in result["receipt"]["attempts"][0]["reason"]
    assert result["receipt"]["attempts"][0]["next_allowed"] == ["direct", "jina_reader"]


def test_insane_fetch_can_fall_back_to_jina_reader(tmp_path):
    source_url = "https://example.com/blocked"
    jina_url = "https://r.jina.ai/https://example.com/blocked"
    adapter = FakeInsaneFetch(
        {
            source_url: (403, "blocked", source_url, "text/html"),
            jina_url: (200, "# Jina Fallback\n\nReadable text", jina_url, "text/plain"),
        }
    )

    result = ResearchEngine(registry=AdapterRegistry([adapter]), home=tmp_path).run(
        {
            "query": "Adaptive generic read",
            "source_hints": [source_url],
            "allowed_modules": ["read.insane_fetch"],
        }
    )

    assert result["status"] == "ok"
    item = result["results"][0]
    assert item["title"] == "Jina Fallback"
    assert "external_reader" in item["limits"]
    assert "route:jina_reader" in item["limits"]
    assert "stop_reason:route_success" in item["limits"]
    assert "trace:direct=blocked" in item["limits"]
    assert "trace:jina_reader=ok:200" in item["limits"]
    assert result["receipt"]["attempts"][0]["next_allowed"] == []


def test_insane_fetch_skips_thin_threads_shell_and_labels_public_fallback(tmp_path):
    source_url = "https://www.threads.com/@agentlas"
    jina_url = "https://r.jina.ai/https://www.threads.com/@agentlas"
    adapter = FakeInsaneFetch(
        {
            source_url: (200, "<html><head><title>Threads</title></head><body>Threads</body></html>", source_url, "text/html"),
            jina_url: (200, "# Agentlas on Threads\n\nPublic thread text from the fallback reader.", jina_url, "text/plain"),
        }
    )

    result = ResearchEngine(registry=AdapterRegistry([adapter]), home=tmp_path).run(
        {
            "query": "Adaptive Threads read",
            "source_hints": [source_url],
            "allowed_modules": ["read.insane_fetch"],
        }
    )

    assert result["status"] == "ok"
    item = result["results"][0]
    assert item["platform"] == "threads"
    assert item["title"] == "Agentlas on Threads"
    assert "public_html_fallback" in item["limits"]
    assert "official_api_preferred" in item["limits"]
    assert "external_reader" in item["limits"]
    assert "trace:direct=thin_public_shell" in item["limits"]
    assert "trace:jina_reader=ok:200" in item["limits"]
    coverage = result["receipt"]["policy"]["evidence_coverage"]
    assert coverage["public_social_fallback_platforms"] == ["threads"]
    assert coverage["official_social_modules_missing"] == ["platform.threads"]
    assert coverage["completion_blockers"] == ["threads_live_graph_check"]


def test_insane_fetch_blocks_threads_login_markdown_from_external_reader(tmp_path):
    source_url = "https://www.threads.net/@agentlas"
    jina_url = "https://r.jina.ai/https://www.threads.net/@agentlas"
    adapter = FakeInsaneFetch(
        {
            source_url: (200, "<html><head><title>Threads</title></head><body>Threads</body></html>", source_url, "text/html"),
            jina_url: (200, "Title: Threads • Log in\n\nScan to get the app", jina_url, "text/plain"),
        }
    )

    result = ResearchEngine(registry=AdapterRegistry([adapter]), home=tmp_path).run(
        {
            "query": "Adaptive Threads read",
            "source_hints": [source_url],
            "allowed_modules": ["read.insane_fetch"],
        }
    )

    assert result["status"] == "partial"
    attempt = result["receipt"]["attempts"][0]
    assert attempt["status"] == "blocked"
    assert "auth_required:route=jina_reader" in attempt["reason"]
    assert "direct=thin_public_shell" in attempt["reason"]
    assert "jina_reader=auth_required" in attempt["reason"]
    assert result["results"][0]["confidence"] == "blocked"
    assert "stop_reason:auth_required" in result["results"][0]["limits"]


def test_insane_fetch_stops_at_paywall_or_login_wall(tmp_path):
    source_url = "https://example.com/paywalled"
    adapter = FakeInsaneFetch(
        {
            source_url: (200, "<html><title>Paywall</title><body>Subscribe to continue</body></html>", source_url, "text/html"),
        }
    )

    result = ResearchEngine(registry=AdapterRegistry([adapter]), home=tmp_path).run(
        {
            "query": "Adaptive read",
            "source_hints": [source_url],
            "allowed_modules": ["read.insane_fetch"],
        }
    )

    assert result["status"] == "partial"
    assert result["results"][0]["confidence"] == "blocked"
    assert "paywall_detected" in result["results"][0]["limits"]
    assert "stop_reason:paywall_detected" in result["results"][0]["limits"]
    assert "trace:direct=paywall_detected" in result["results"][0]["limits"]
    assert "untried_routes:jina_reader" in result["results"][0]["limits"]
    assert result["receipt"]["attempts"][0]["status"] == "blocked"
    assert result["receipt"]["attempts"][0]["next_allowed"] == ["jina_reader"]


def test_insane_fetch_blocks_private_sources_before_external_routes(tmp_path):
    adapter = FakeInsaneFetch({})
    result = ResearchEngine(registry=AdapterRegistry([adapter]), home=tmp_path).run(
        {
            "query": "Adaptive read",
            "source_hints": ["http://127.0.0.1:8000/private"],
            "allowed_modules": ["read.insane_fetch"],
        }
    )

    assert result["status"] == "partial"
    assert result["receipt"]["attempts"][0]["status"] == "blocked"
    assert result["results"][0]["confidence"] == "blocked"
    assert adapter.seen == []


class FakeAgentBrowser(AgentBrowserCliAdapter):
    def _find_binary(self):
        return ["agent-browser"]

    def _run(self, argv, *, timeout=None):
        if argv[-1] == "close":
            return subprocess.CompletedProcess(argv, 0, "", "")
        if "snapshot" in argv:
            return subprocess.CompletedProcess(argv, 0, '- heading "Browser Title" [ref=e1]\n- text "Loaded"', "")
        return subprocess.CompletedProcess(argv, 0, "opened", "")


class FakeConfiguredAgentBrowser(AgentBrowserCliAdapter):
    def _run(self, argv, *, timeout=None):
        assert argv[:3] == ["npx", "-y", "agent-browser"]
        if argv[-1] == "close":
            return subprocess.CompletedProcess(argv, 0, "", "")
        if "snapshot" in argv:
            return subprocess.CompletedProcess(argv, 0, '- heading "Configured Browser" [ref=e1]\n- text "Loaded"', "")
        return subprocess.CompletedProcess(argv, 0, "opened", "")


def test_agent_browser_adapter_is_optional_hardpoint(tmp_path):
    registry = AdapterRegistry([FakeAgentBrowser()])
    result = ResearchEngine(registry=registry, home=tmp_path).run(
        {
            "query": "Browser read",
            "source_hints": ["https://example.com"],
            "allowed_modules": ["browser.agent_cli"],
        }
    )

    assert result["status"] == "ok"
    assert result["results"][0]["platform"] == "browser"
    assert result["results"][0]["title"] == "Browser Title"
    assert result["receipt"]["policy"]["browser_used"] is True
    assert result["receipt"]["module_chain"] == ["browser.agent_cli"]


def test_agent_browser_adapter_uses_approved_hardpoint_recipe(tmp_path, monkeypatch):
    monkeypatch.delenv("AGENTLAS_AGENT_BROWSER_BIN", raising=False)
    monkeypatch.setattr("agentlas_cloud.research.adapters.agent_browser_cli.shutil.which", lambda name: None)
    run_research_hardpoints(action="arm", module_id="browser.agent_cli", recipe="npx-agent-browser", home=tmp_path)
    registry = AdapterRegistry([FakeConfiguredAgentBrowser(home=tmp_path)])

    result = ResearchEngine(registry=registry, home=tmp_path).run(
        {
            "query": "Browser read",
            "source_hints": ["https://example.com"],
            "allowed_modules": ["browser.agent_cli"],
        }
    )

    assert result["status"] == "ok"
    assert result["results"][0]["title"] == "Configured Browser"
    assert result["receipt"]["policy"]["browser_used"] is True


def test_run_research_uses_default_networking_home_hardpoint(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTLAS_NETWORKING_HOME", str(tmp_path))
    monkeypatch.delenv("AGENTLAS_AGENT_BROWSER_BIN", raising=False)
    monkeypatch.setattr("agentlas_cloud.research.adapters.agent_browser_cli.shutil.which", lambda name: None)

    def fake_run(self, argv, *, timeout=None):
        assert argv[:3] == ["npx", "-y", "agent-browser"]
        if argv[-1] == "close":
            return subprocess.CompletedProcess(argv, 0, "", "")
        if "snapshot" in argv:
            return subprocess.CompletedProcess(argv, 0, '- heading "Default Home Browser" [ref=e1]', "")
        return subprocess.CompletedProcess(argv, 0, "opened", "")

    monkeypatch.setattr(AgentBrowserCliAdapter, "_run", fake_run)
    run_research_hardpoints(action="arm", module_id="browser.agent_cli", recipe="npx-agent-browser")

    result = run_research(
        {
            "query": "Browser read",
            "source_hints": ["https://example.com"],
            "allowed_modules": ["browser.agent_cli"],
            "max_weight": "browser_heavy",
        }
    )

    assert result["status"] == "ok"
    assert result["results"][0]["title"] == "Default Home Browser"
    assert result["receipt"]["policy"]["browser_execution"]["status"] == "used"


def test_agent_browser_missing_binary_is_nonfatal(tmp_path):
    result = ResearchEngine(registry=AdapterRegistry([AgentBrowserCliAdapter()]), home=tmp_path).run(
        {
            "query": "Browser read",
            "source_hints": ["https://example.com"],
            "allowed_modules": ["browser.agent_cli"],
        }
    )

    assert result["status"] == "partial"
    assert result["results"] == []
    assert result["receipt"]["attempts"][0]["module"] == "browser.agent_cli"
    assert result["receipt"]["attempts"][0]["status"] == "module_unavailable"
    assert result["receipt"]["policy"]["browser_used"] is False


class FailingAgentBrowser(AgentBrowserCliAdapter):
    def _find_binary(self):
        return ["agent-browser", "--token", "secret-browser-token"]

    def _run(self, argv, *, timeout=None):
        if argv[-1] == "close":
            return subprocess.CompletedProcess(argv, 0, "", "")
        return subprocess.CompletedProcess(
            argv,
            1,
            "",
            "open failed Bearer secret-browser-token token=secret-browser-token",
        )


def test_agent_browser_adapter_redacts_failed_command_stderr(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTLAS_AGENT_BROWSER_TOKEN", "secret-browser-token")

    result = ResearchEngine(registry=AdapterRegistry([FailingAgentBrowser()]), home=tmp_path).run(
        {
            "query": "Browser read",
            "source_hints": ["https://example.com"],
            "allowed_modules": ["browser.agent_cli"],
        }
    )

    attempt = result["receipt"]["attempts"][0]
    assert result["status"] == "partial"
    assert attempt["module"] == "browser.agent_cli"
    assert attempt["status"] == "error"
    assert "[redacted]" in attempt["reason"]
    assert "secret-browser-token" not in str(result)


class FakePlaywrightMcp(PlaywrightMcpAdapter):
    def _snapshot_argv(self, url):
        assert url == "https://example.com"
        return ["playwright-mcp-snapshot", url]

    def _run(self, argv):
        assert argv == ["playwright-mcp-snapshot", "https://example.com"]
        return subprocess.CompletedProcess(
            argv,
            0,
            '{"title":"Playwright Title","snapshot":"- heading \\"Playwright Title\\" [ref=e1]\\n- text \\"Loaded\\"","limits":["isolated_session"]}',
            "",
        )


def test_playwright_mcp_adapter_is_configured_hardpoint(tmp_path):
    registry = AdapterRegistry([FakePlaywrightMcp()])
    result = ResearchEngine(registry=registry, home=tmp_path).run(
        {
            "query": "Browser read",
            "source_hints": ["https://example.com"],
            "allowed_modules": ["browser.playwright_mcp"],
        }
    )

    assert result["status"] == "ok"
    item = result["results"][0]
    assert item["platform"] == "browser"
    assert item["title"] == "Playwright Title"
    assert "Loaded" in item["content_markdown"]
    assert "playwright_mcp_snapshot" in item["limits"]
    assert "isolated_session" in item["limits"]
    assert result["receipt"]["policy"]["browser_used"] is True
    assert result["receipt"]["module_chain"] == ["browser.playwright_mcp"]


def test_playwright_mcp_missing_command_is_nonfatal(tmp_path, monkeypatch):
    monkeypatch.delenv("AGENTLAS_PLAYWRIGHT_MCP_SNAPSHOT_CMD", raising=False)
    result = ResearchEngine(registry=AdapterRegistry([PlaywrightMcpAdapter()]), home=tmp_path).run(
        {
            "query": "Browser read",
            "source_hints": ["https://example.com"],
            "allowed_modules": ["browser.playwright_mcp"],
        }
    )

    assert result["status"] == "partial"
    assert result["results"] == []
    assert result["receipt"]["attempts"][0]["module"] == "browser.playwright_mcp"
    assert result["receipt"]["attempts"][0]["status"] == "module_unavailable"
    assert result["receipt"]["policy"]["browser_used"] is False


class FakeBrowserUse(BrowserUseAdapter):
    def _snapshot_argv(self, url):
        assert url == "https://example.com"
        return ["browser-use-snapshot", url]

    def _run(self, argv):
        assert argv == ["browser-use-snapshot", "https://example.com"]
        return subprocess.CompletedProcess(
            argv,
            0,
            '{"title":"Browser Use Title","result":"- heading \\"Browser Use Title\\" [ref=e1]\\n- text \\"Loaded\\"","limits":["cloud_or_local_session"]}',
            "",
        )


def test_browser_use_adapter_is_configured_hardpoint(tmp_path):
    registry = AdapterRegistry([FakeBrowserUse()])
    result = ResearchEngine(registry=registry, home=tmp_path).run(
        {
            "query": "Browser read",
            "source_hints": ["https://example.com"],
            "allowed_modules": ["browser.browser_use"],
        }
    )

    assert result["status"] == "ok"
    item = result["results"][0]
    assert item["platform"] == "browser"
    assert item["title"] == "Browser Use Title"
    assert "Loaded" in item["content_markdown"]
    assert "browser_use_snapshot" in item["limits"]
    assert "cloud_or_local_session" in item["limits"]
    assert result["receipt"]["policy"]["browser_used"] is True
    assert result["receipt"]["module_chain"] == ["browser.browser_use"]


def test_browser_use_missing_command_is_nonfatal(tmp_path, monkeypatch):
    monkeypatch.delenv("AGENTLAS_BROWSER_USE_SNAPSHOT_CMD", raising=False)
    result = ResearchEngine(registry=AdapterRegistry([BrowserUseAdapter()]), home=tmp_path).run(
        {
            "query": "Browser read",
            "source_hints": ["https://example.com"],
            "allowed_modules": ["browser.browser_use"],
        }
    )

    assert result["status"] == "partial"
    assert result["results"] == []
    assert result["receipt"]["attempts"][0]["module"] == "browser.browser_use"
    assert result["receipt"]["attempts"][0]["status"] == "module_unavailable"
    assert result["receipt"]["policy"]["browser_used"] is False


class FakeStagehand(StagehandBrowserAdapter):
    def _snapshot_argv(self, url):
        assert url == "https://example.com"
        return ["stagehand-snapshot", url]

    def _run(self, argv):
        assert argv == ["stagehand-snapshot", "https://example.com"]
        return subprocess.CompletedProcess(
            argv,
            0,
            '{"title":"Stagehand Title","extraction":"# Stagehand Title\\n\\nLoaded with structured extraction","limits":["dom_extract"]}',
            "",
        )


def test_stagehand_adapter_is_configured_hardpoint(tmp_path):
    registry = AdapterRegistry([FakeStagehand()])
    result = ResearchEngine(registry=registry, home=tmp_path).run(
        {
            "query": "Browser read",
            "source_hints": ["https://example.com"],
            "allowed_modules": ["browser.stagehand"],
        }
    )

    assert result["status"] == "ok"
    item = result["results"][0]
    assert item["platform"] == "browser"
    assert item["title"] == "Stagehand Title"
    assert "structured extraction" in item["content_markdown"]
    assert "stagehand_snapshot" in item["limits"]
    assert "dom_extract" in item["limits"]
    assert result["receipt"]["policy"]["browser_used"] is True
    assert result["receipt"]["module_chain"] == ["browser.stagehand"]


def test_deep_read_collects_static_and_browser_when_browser_is_mounted(tmp_path):
    registry = AdapterRegistry([FakeReader(), FakeStagehand()])
    result = ResearchEngine(registry=registry, home=tmp_path).run(
        {
            "query": "Deep browser read",
            "source_hints": ["https://example.com"],
            "allowed_modules": ["read.http", "browser.stagehand"],
            "depth": "deep",
        }
    )

    assert result["status"] == "ok"
    assert result["receipt"]["policy"]["read_strategy"] == "deep_static_plus_browser"
    assert result["receipt"]["module_chain"] == ["read.http", "browser.stagehand"]
    assert [item["platform"] for item in result["results"]] == ["web", "browser"]
    assert [item["title"] for item in result["results"]] == ["Example", "Stagehand Title"]
    assert result["receipt"]["policy"]["browser_used"] is True
    assert result["receipt"]["policy"]["browser_execution"]["status"] == "used"


def test_deep_read_without_browser_mount_stays_first_success(tmp_path):
    registry = AdapterRegistry([FakeReader(), FakeStagehand()])
    result = ResearchEngine(registry=registry, home=tmp_path).run(
        {
            "query": "Deep without browser",
            "source_hints": ["https://example.com"],
            "allowed_modules": ["read.http"],
            "depth": "deep",
        }
    )

    assert result["status"] == "ok"
    assert result["receipt"]["policy"]["read_strategy"] == "first_success"
    assert result["receipt"]["module_chain"] == ["read.http"]
    assert len(result["results"]) == 1
    assert result["results"][0]["title"] == "Example"
    assert result["receipt"]["policy"]["browser_used"] is False
    assert result["receipt"]["policy"]["browser_execution"]["status"] == "not_requested"


def test_loadout_weight_ceiling_blocks_explicit_heavy_module(tmp_path):
    registry = AdapterRegistry([FakeReader(), FakeStagehand()])
    result = ResearchEngine(registry=registry, home=tmp_path).run(
        {
            "query": "Safe should stay light",
            "source_hints": ["https://example.com"],
            "loadout": "safe",
            "depth": "deep",
            "allowed_modules": ["browser.stagehand"],
        }
    )

    assert result["status"] == "ok"
    assert result["request"]["max_weight"] == "adaptive_medium"
    assert result["receipt"]["policy"]["max_weight"] == "adaptive_medium"
    assert result["results"][0]["platform"] == "web"
    assert len(result["results"]) == 1
    assert any(
        attempt["module"] == "browser.stagehand"
        and attempt["status"] == "module_unavailable"
        and attempt["reason"].startswith("weight_exceeds_max:")
        for attempt in result["receipt"]["attempts"]
    )
    assert result["receipt"]["policy"]["browser_used"] is False
    assert result["receipt"]["policy"]["read_strategy"] == "first_success"
    assert result["receipt"]["policy"]["browser_execution"]["status"] == "blocked_by_policy"
    assert result["receipt"]["policy"]["browser_execution"]["unavailable_count"] == 1


def test_max_weight_override_allows_explicit_heavy_module(tmp_path):
    registry = AdapterRegistry([FakeReader(), FakeStagehand()])
    result = ResearchEngine(registry=registry, home=tmp_path).run(
        {
            "query": "Operator approved heavy read",
            "source_hints": ["https://example.com"],
            "loadout": "safe",
            "depth": "deep",
            "allowed_modules": ["browser.stagehand"],
            "max_weight": "browser_heavy",
        }
    )

    assert result["status"] == "ok"
    assert result["request"]["max_weight"] == "browser_heavy"
    assert result["receipt"]["policy"]["max_weight"] == "browser_heavy"
    assert [item["platform"] for item in result["results"]] == ["web", "browser"]
    assert result["receipt"]["policy"]["browser_used"] is True


def test_stagehand_missing_command_is_nonfatal(tmp_path, monkeypatch):
    monkeypatch.delenv("AGENTLAS_STAGEHAND_SNAPSHOT_CMD", raising=False)
    result = ResearchEngine(registry=AdapterRegistry([StagehandBrowserAdapter()]), home=tmp_path).run(
        {
            "query": "Browser read",
            "source_hints": ["https://example.com"],
            "allowed_modules": ["browser.stagehand"],
        }
    )

    assert result["status"] == "partial"
    assert result["results"] == []
    assert result["receipt"]["attempts"][0]["module"] == "browser.stagehand"
    assert result["receipt"]["attempts"][0]["status"] == "module_unavailable"
    assert result["receipt"]["policy"]["browser_used"] is False
    assert result["receipt"]["policy"]["browser_execution"]["status"] == "unavailable"
    assert result["receipt"]["policy"]["browser_execution"]["attempt_count"] == 1


class FailingStagehand(StagehandBrowserAdapter):
    def _snapshot_argv(self, url):
        assert url == "https://example.com"
        return ["stagehand-snapshot", "--api-key", "secret-stagehand-token", url]

    def _run(self, argv):
        return subprocess.CompletedProcess(
            argv,
            1,
            "",
            "snapshot failed --api-key secret-stagehand-token Bearer secret-stagehand-token",
        )


def test_command_snapshot_adapter_redacts_failed_stderr(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTLAS_STAGEHAND_SNAPSHOT_CMD", "stagehand --api-key secret-stagehand-token {url}")

    result = ResearchEngine(registry=AdapterRegistry([FailingStagehand()]), home=tmp_path).run(
        {
            "query": "Browser read",
            "source_hints": ["https://example.com"],
            "allowed_modules": ["browser.stagehand"],
        }
    )

    attempt = result["receipt"]["attempts"][0]
    assert result["status"] == "partial"
    assert attempt["module"] == "browser.stagehand"
    assert attempt["status"] == "error"
    assert "[redacted]" in attempt["reason"]
    assert "secret-stagehand-token" not in str(result)


class FakeSteel(SteelBrowserAdapter):
    def _snapshot_argv(self, url):
        assert url == "https://example.com"
        return ["steel-snapshot", url]

    def _run(self, argv):
        assert argv == ["steel-snapshot", "https://example.com"]
        return subprocess.CompletedProcess(
            argv,
            0,
            '{"title":"Steel Title","snapshot":"- heading \\"Steel Title\\" [ref=e1]\\n- text \\"Remote loaded\\"","limits":["remote_session"]}',
            "",
        )


def test_steel_adapter_is_configured_hardpoint(tmp_path):
    registry = AdapterRegistry([FakeSteel()])
    result = ResearchEngine(registry=registry, home=tmp_path).run(
        {
            "query": "Browser read",
            "source_hints": ["https://example.com"],
            "allowed_modules": ["browser.steel"],
        }
    )

    assert result["status"] == "ok"
    item = result["results"][0]
    assert item["platform"] == "browser"
    assert item["title"] == "Steel Title"
    assert "Remote loaded" in item["content_markdown"]
    assert "steel_remote_browser" in item["limits"]
    assert "remote_session" in item["limits"]
    assert result["receipt"]["policy"]["browser_used"] is True
    assert result["receipt"]["module_chain"] == ["browser.steel"]


def test_steel_missing_command_is_nonfatal(tmp_path, monkeypatch):
    monkeypatch.delenv("AGENTLAS_STEEL_SNAPSHOT_CMD", raising=False)
    result = ResearchEngine(registry=AdapterRegistry([SteelBrowserAdapter()]), home=tmp_path).run(
        {
            "query": "Browser read",
            "source_hints": ["https://example.com"],
            "allowed_modules": ["browser.steel"],
        }
    )

    assert result["status"] == "partial"
    assert result["results"] == []
    assert result["receipt"]["attempts"][0]["module"] == "browser.steel"
    assert result["receipt"]["attempts"][0]["status"] == "module_unavailable"
    assert result["receipt"]["policy"]["browser_used"] is False


class FakeHyperAgent(HyperAgentBrowserAdapter):
    def _snapshot_argv(self, url):
        assert url == "https://example.com"
        return ["hyperagent-snapshot", url]

    def _run(self, argv):
        assert argv == ["hyperagent-snapshot", "https://example.com"]
        return subprocess.CompletedProcess(
            argv,
            0,
            '{"title":"HyperAgent Title","result":"# HyperAgent Title\\n\\nLoaded with HyperAgent","limits":["cloud_or_local_session"]}',
            "",
        )


def test_hyperagent_adapter_is_configured_hardpoint(tmp_path):
    registry = AdapterRegistry([FakeHyperAgent()])
    result = ResearchEngine(registry=registry, home=tmp_path).run(
        {
            "query": "Browser read",
            "source_hints": ["https://example.com"],
            "allowed_modules": ["browser.hyperagent"],
        }
    )

    assert result["status"] == "ok"
    item = result["results"][0]
    assert item["platform"] == "browser"
    assert item["title"] == "HyperAgent Title"
    assert "Loaded with HyperAgent" in item["content_markdown"]
    assert "hyperagent_snapshot" in item["limits"]
    assert "cloud_or_local_session" in item["limits"]
    assert result["receipt"]["policy"]["browser_used"] is True
    assert result["receipt"]["module_chain"] == ["browser.hyperagent"]


def test_hyperagent_missing_command_is_nonfatal(tmp_path, monkeypatch):
    monkeypatch.delenv("AGENTLAS_HYPERAGENT_SNAPSHOT_CMD", raising=False)
    result = ResearchEngine(registry=AdapterRegistry([HyperAgentBrowserAdapter()]), home=tmp_path).run(
        {
            "query": "Browser read",
            "source_hints": ["https://example.com"],
            "allowed_modules": ["browser.hyperagent"],
        }
    )

    assert result["status"] == "partial"
    assert result["results"] == []
    assert result["receipt"]["attempts"][0]["module"] == "browser.hyperagent"
    assert result["receipt"]["attempts"][0]["status"] == "module_unavailable"
    assert result["receipt"]["policy"]["browser_used"] is False


class FakeBrowserOS(BrowserOSBrowserAdapter):
    def _snapshot_argv(self, url):
        assert url == "https://example.com"
        return ["browseros-snapshot", url]

    def _run(self, argv):
        assert argv == ["browseros-snapshot", "https://example.com"]
        return subprocess.CompletedProcess(
            argv,
            0,
            '{"title":"BrowserOS Title","snapshot":"# BrowserOS Title\\n\\nLoaded from BrowserOS","limits":["desktop_profile"]}',
            "",
        )


def test_browseros_adapter_is_configured_hardpoint(tmp_path):
    registry = AdapterRegistry([FakeBrowserOS()])
    result = ResearchEngine(registry=registry, home=tmp_path).run(
        {
            "query": "Browser read",
            "source_hints": ["https://example.com"],
            "allowed_modules": ["browser.browseros"],
        }
    )

    assert result["status"] == "ok"
    item = result["results"][0]
    assert item["platform"] == "browser"
    assert item["title"] == "BrowserOS Title"
    assert "Loaded from BrowserOS" in item["content_markdown"]
    assert "browseros_snapshot" in item["limits"]
    assert "desktop_profile" in item["limits"]
    assert result["receipt"]["policy"]["browser_used"] is True
    assert result["receipt"]["module_chain"] == ["browser.browseros"]


def test_browseros_missing_command_is_nonfatal(tmp_path, monkeypatch):
    monkeypatch.delenv("AGENTLAS_BROWSEROS_SNAPSHOT_CMD", raising=False)
    result = ResearchEngine(registry=AdapterRegistry([BrowserOSBrowserAdapter()]), home=tmp_path).run(
        {
            "query": "Browser read",
            "source_hints": ["https://example.com"],
            "allowed_modules": ["browser.browseros"],
        }
    )

    assert result["status"] == "partial"
    assert result["results"] == []
    assert result["receipt"]["attempts"][0]["module"] == "browser.browseros"
    assert result["receipt"]["attempts"][0]["status"] == "module_unavailable"
    assert result["receipt"]["policy"]["browser_used"] is False


class FakeReddit(RedditPublicAdapter):
    def _fetch_json(self, url):
        return [
            {
                "data": {
                    "children": [
                        {
                            "kind": "t3",
                            "data": {
                                "title": "Agent browsers?",
                                "subreddit": "Agentlas",
                                "author": "mason",
                                "selftext": "Should browser modules be detachable?",
                            },
                        }
                    ]
                }
            },
            {
                "data": {
                    "children": [
                        {
                            "kind": "t1",
                            "data": {
                                "author": "codex",
                                "body": "Yes, mount them as optional hardpoints.",
                            },
                        }
                    ]
                }
            },
        ]


class FakeRedditListing(RedditPublicAdapter):
    def _fetch_json(self, url):
        assert url in {
            "https://www.reddit.com/r/Agentlas.json?limit=100&raw_json=1",
            "https://www.reddit.com/search.json?q=agent+browser&sort=relevance&t=month&limit=100&raw_json=1",
        }
        return {
            "data": {
                "children": [
                    {
                        "kind": "t3",
                        "data": {
                            "title": "Agent browser modules",
                            "subreddit": "Agentlas",
                            "author": "mason",
                            "permalink": "/r/Agentlas/comments/abc/agent_browser_modules/",
                            "selftext": "Use detachable browser hardpoints.",
                        },
                    },
                    {
                        "kind": "t3",
                        "data": {
                            "title": "Research engine loadouts",
                            "subreddit": "Agentlas",
                            "author": "codex",
                            "permalink": "/r/Agentlas/comments/def/research_engine_loadouts/",
                        },
                    },
                ]
            }
        }


class FakeRedditOAuth(RedditOAuthAdapter):
    def _bearer_token(self):
        return "test-reddit-token"

    def _fetch_oauth_json(self, url, *, token):
        assert token == "test-reddit-token"
        assert url == "https://oauth.reddit.com/r/Agentlas/comments/abc/agent_browsers.json?limit=100&raw_json=1"
        return (
            [
                {
                    "data": {
                        "children": [
                            {
                                "kind": "t3",
                                "data": {
                                    "title": "OAuth agent browsers",
                                    "subreddit": "Agentlas",
                                    "author": "mason",
                                    "selftext": "OAuth reads are durable.",
                                },
                            }
                        ]
                    }
                },
                {
                    "data": {
                        "children": [
                            {
                                "kind": "t1",
                                "data": {
                                    "author": "codex",
                                    "body": "Rate-limit receipts are useful.",
                                },
                            }
                        ]
                    }
                },
            ],
            ["reddit_rate_remaining:99", "reddit_rate_reset:60"],
        )


class FakeRedditRssFallback(RedditPublicAdapter):
    def _fetch_json(self, url):
        raise HTTPError(url, 403, "Forbidden", hdrs=None, fp=None)

    def _fetch_text(self, url):
        assert url == "https://www.reddit.com/r/Agentlas.rss?limit=100"
        return """<?xml version="1.0"?><rss><channel><title>r/Agentlas</title><item><title>Research hardpoints</title><link>https://www.reddit.com/r/Agentlas/comments/abc</link><description>RSS fallback works.</description></item></channel></rss>"""


class BlockedRedditSearch(RedditPublicAdapter):
    def _fetch_json(self, url):
        raise HTTPError(url, 403, "Forbidden", hdrs=None, fp=None)

    def _fetch_text(self, url):
        raise HTTPError(url, 429, "Too Many Requests", hdrs=None, fp=None)


def test_reddit_public_adapter_reads_post_and_comments(tmp_path):
    registry = AdapterRegistry([FakeReddit()])
    result = ResearchEngine(registry=registry, home=tmp_path).run(
        {
            "query": "Read reddit",
            "source_hints": ["https://www.reddit.com/r/Agentlas/comments/abc/agent_browsers/"],
            "allowed_modules": ["platform.reddit"],
        }
    )

    assert result["status"] == "ok"
    item = result["results"][0]
    assert item["platform"] == "reddit"
    assert item["title"] == "Agent browsers?"
    assert "optional hardpoints" in item["content_markdown"]
    assert "public_json_fallback" in item["limits"]
    assert "oauth_preferred" in item["limits"]
    coverage = result["receipt"]["policy"]["evidence_coverage"]
    assert coverage["status"] == "public_social_fallback"
    assert coverage["public_social_fallback_evidence"] is True
    assert coverage["official_social_evidence"] is False
    assert coverage["official_social_modules_missing"] == ["platform.reddit.oauth"]
    assert coverage["completion_blockers"] == ["reddit_oauth_live_check"]
    assert "official_reddit_missing" in coverage["warnings"]
    assert "public_social_fallback_not_official" in coverage["warnings"]


def test_reddit_public_adapter_reads_subreddit_hint(tmp_path):
    registry = AdapterRegistry([FakeRedditListing()])
    result = ResearchEngine(registry=registry, home=tmp_path).run(
        {
            "query": "Read subreddit",
            "source_hints": ["reddit:subreddit:Agentlas"],
            "allowed_modules": ["platform.reddit"],
        }
    )

    assert result["status"] == "ok"
    item = result["results"][0]
    assert item["platform"] == "reddit"
    assert item["url"] == "https://www.reddit.com/r/Agentlas/"
    assert "Agent browser modules" in item["content_markdown"]
    assert "Research engine loadouts" in item["content_markdown"]
    assert "public_json_fallback" in item["limits"]


def test_reddit_public_adapter_reads_search_hint(tmp_path):
    registry = AdapterRegistry([FakeRedditListing()])
    result = ResearchEngine(registry=registry, home=tmp_path).run(
        {
            "query": "Search reddit",
            "source_hints": ["reddit:search:agent browser"],
            "allowed_modules": ["platform.reddit"],
        }
    )

    assert result["status"] == "ok"
    item = result["results"][0]
    assert item["platform"] == "reddit"
    assert item["url"] == "https://www.reddit.com/search/?q=agent+browser&sort=relevance&t=month"
    assert "Agent browser modules" in item["content_markdown"]


def test_reddit_search_uses_public_web_fallback_when_reddit_blocks(tmp_path, monkeypatch):
    class RedditDuckDuckGoFallback(DuckDuckGoHtmlSearchAdapter):
        def _fetch_text(self, url):
            assert url == "https://lite.duckduckgo.com/lite/?q=agent+browser+Reddit+site%3Areddit.com"
            return """<html><body>
            <a rel="nofollow" href="/l/?uddg=https%3A%2F%2Fwww.reddit.com%2Fr%2FAgentlas%2Fcomments%2Fabc%2Fagent_browser%2F">Reddit fallback result</a>
            </body></html>"""

    clear_reddit_oauth_env(monkeypatch)
    result = ResearchEngine(registry=AdapterRegistry([BlockedRedditSearch(), RedditDuckDuckGoFallback()]), home=tmp_path).run(
        {
            "query": "Search reddit",
            "source_hints": ["reddit:search:agent browser"],
            "loadout": "auto",
            "max_cost": {"requests": 3},
        }
    )

    assert result["status"] == "ok"
    assert result["receipt"]["policy"]["source_hints_used"] == [
        "reddit:search:agent browser",
        "search:ddg_html:agent browser Reddit site:reddit.com",
        "search:news_rss:agent browser Reddit site:reddit.com",
    ]
    assert result["receipt"]["attempts"][0]["module"] == "platform.reddit"
    assert result["receipt"]["attempts"][0]["status"] == "blocked"
    assert result["receipt"]["attempts"][1]["module"] == "search.ddg_html"
    assert result["results"][0]["confidence"] == "blocked"
    assert result["results"][1]["platform"] == "web_search"
    assert "Reddit fallback result" in result["results"][1]["content_markdown"]


def test_research_platform_check_runs_reddit_public_hint(tmp_path):
    registry = AdapterRegistry([FakeRedditListing()])
    payload = run_research_platform_check(
        module_id="platform.reddit",
        source_hint="reddit:search:agent browser",
        home=tmp_path,
        registry=registry,
    )

    assert payload["schema"] == "agentlas.research.platform_check.v0"
    assert payload["status"] == "ok"
    assert payload["commands_will_run"] is False
    assert payload["network_will_run"] is True
    assert payload["source_policy"] == {"safe": True, "reason": "platform_hint", "supported": True, "kind": "platform_hint"}
    assert payload["attempts"][0]["module"] == "platform.reddit"
    assert payload["attempts"][0]["status"] == "ok"
    assert payload["contract"]["id"] == "platform.reddit"
    assert payload["result_summaries"][0]["platform"] == "reddit"
    assert "Agent browser modules" in payload["result_summaries"][0]["content_preview"]
    assert (tmp_path / "ledgers" / "research-receipts.jsonl").exists()


def test_auto_loadout_allows_reddit_source_hint(tmp_path):
    registry = AdapterRegistry([FakeRedditListing()])
    result = ResearchEngine(registry=registry, home=tmp_path).run(
        {
            "query": "Auto reddit source",
            "source_hints": ["reddit:subreddit:Agentlas"],
        }
    )

    assert "platform.reddit" in result["request"]["allowed_modules"]
    assert result["request"]["max_weight"] == "adaptive_medium"
    assert result["status"] == "ok"


def test_reddit_oauth_adapter_reads_with_token_and_hides_secret(tmp_path):
    registry = AdapterRegistry([FakeRedditOAuth(), RedditPublicAdapter()])
    result = ResearchEngine(registry=registry, home=tmp_path).run(
        {
            "query": "Read reddit",
            "source_hints": ["https://www.reddit.com/r/Agentlas/comments/abc/agent_browsers/"],
            "loadout": "social",
        }
    )

    assert result["status"] == "ok"
    item = result["results"][0]
    assert item["platform"] == "reddit"
    assert item["title"] == "OAuth agent browsers"
    assert "OAuth reads are durable" in item["content_markdown"]
    assert "reddit_oauth" in item["limits"]
    assert "reddit_rate_remaining:99" in item["limits"]
    assert result["receipt"]["module_chain"] == ["platform.reddit.oauth"]
    assert "test-reddit-token" not in str(result)
    coverage = result["receipt"]["policy"]["evidence_coverage"]
    assert coverage["status"] == "official_social"
    assert coverage["official_social_evidence"] is True
    assert coverage["public_social_fallback_evidence"] is False


def test_reddit_oauth_adapter_reads_with_app_only_client_credentials(tmp_path, monkeypatch):
    class FakeRedditAppOnlyOAuth(FakeRedditOAuth):
        def _bearer_token(self):
            return ""

        def _fetch_app_only_token(self, *, client_id, client_secret):
            assert client_id == "client-id-secret"
            assert client_secret == "client-secret-secret"
            return "app-only-token-secret"

        def _fetch_oauth_json(self, url, *, token):
            assert token == "app-only-token-secret"
            return super()._fetch_oauth_json(url, token="test-reddit-token")

    clear_reddit_oauth_env(monkeypatch)
    monkeypatch.setenv("AGENTLAS_REDDIT_CLIENT_ID", "client-id-secret")
    monkeypatch.setenv("AGENTLAS_REDDIT_CLIENT_SECRET", "client-secret-secret")

    result = ResearchEngine(registry=AdapterRegistry([FakeRedditAppOnlyOAuth()]), home=tmp_path).run(
        {
            "query": "Read reddit",
            "source_hints": ["https://www.reddit.com/r/Agentlas/comments/abc/agent_browsers/"],
            "allowed_modules": ["platform.reddit.oauth"],
        }
    )

    assert result["status"] == "ok"
    item = result["results"][0]
    assert item["platform"] == "reddit"
    assert "reddit_oauth" in item["limits"]
    assert "reddit_app_only_oauth" in item["limits"]
    assert result["receipt"]["attempts"][0]["status"] == "ok"
    encoded = json.dumps(result, sort_keys=True)
    assert "client-id-secret" not in encoded
    assert "client-secret-secret" not in encoded
    assert "app-only-token-secret" not in encoded


def test_reddit_oauth_missing_token_falls_through_to_public_fallback(tmp_path, monkeypatch):
    clear_reddit_oauth_env(monkeypatch)
    registry = AdapterRegistry([RedditOAuthAdapter(), FakeReddit()])
    result = ResearchEngine(registry=registry, home=tmp_path).run(
        {
            "query": "Read reddit",
            "source_hints": ["https://www.reddit.com/r/Agentlas/comments/abc/agent_browsers/"],
            "loadout": "social",
        }
    )

    assert result["status"] == "ok"
    assert result["results"][0]["title"] == "Agent browsers?"
    attempts = result["receipt"]["attempts"]
    assert attempts[0]["module"] == "platform.reddit.oauth"
    assert attempts[0]["status"] == "module_unavailable"
    assert attempts[1]["module"] == "platform.reddit"
    assert attempts[1]["status"] == "ok"
    assert result["receipt"]["module_chain"] == ["platform.reddit.oauth", "platform.reddit"]
    capability = result["capability_summary"]
    assert capability["status"] == "partial_public_social_fallback"
    assert capability["social"]["requested"] is True
    assert capability["social"]["official_evidence"] is False
    assert capability["social"]["public_fallback_evidence"] is True
    assert capability["social"]["official_missing_modules"] == ["platform.reddit.oauth"]
    assert capability["social"]["missing_proofs"] == ["reddit_oauth_live_check"]


def test_credentialed_platform_errors_redact_tokens(tmp_path, monkeypatch):
    class FailingRedditOAuth(RedditOAuthAdapter):
        def _fetch_oauth_json(self, url, *, token):
            assert token == "secret-reddit-token"
            raise OSError("reddit failed Bearer secret-reddit-token token=secret-reddit-token")

    class FailingThreads(ThreadsSearchAdapter):
        def _search(self, query, *, mode, token):
            assert token == "secret-threads-token"
            raise OSError("threads failed Bearer secret-threads-token token=secret-threads-token")

    monkeypatch.setenv("AGENTLAS_REDDIT_BEARER_TOKEN", "secret-reddit-token")
    monkeypatch.setenv("AGENTLAS_THREADS_ACCESS_TOKEN", "secret-threads-token")

    reddit_result = ResearchEngine(registry=AdapterRegistry([FailingRedditOAuth()]), home=tmp_path).run(
        {
            "query": "Read reddit",
            "source_hints": ["reddit:search:agent browser"],
            "allowed_modules": ["platform.reddit.oauth"],
        }
    )
    threads_result = ResearchEngine(registry=AdapterRegistry([FailingThreads()]), home=tmp_path).run(
        {
            "query": "Search Threads",
            "source_hints": ["threads:keyword:agent browser"],
            "allowed_modules": ["platform.threads"],
        }
    )

    assert reddit_result["receipt"]["attempts"][0]["status"] == "error"
    assert threads_result["receipt"]["attempts"][0]["status"] == "error"
    assert "[redacted]" in reddit_result["receipt"]["attempts"][0]["reason"]
    assert "[redacted]" in threads_result["receipt"]["attempts"][0]["reason"]
    assert "secret-reddit-token" not in str(reddit_result)
    assert "secret-threads-token" not in str(threads_result)


def test_reddit_adapter_falls_back_to_public_rss_when_json_is_blocked(tmp_path):
    registry = AdapterRegistry([FakeRedditRssFallback()])
    result = ResearchEngine(registry=registry, home=tmp_path).run(
        {
            "query": "Read reddit",
            "source_hints": ["https://www.reddit.com/r/Agentlas/"],
            "allowed_modules": ["platform.reddit"],
        }
    )

    assert result["status"] == "ok"
    item = result["results"][0]
    assert item["platform"] == "reddit"
    assert item["title"] == "r/Agentlas"
    assert "Research hardpoints" in item["content_markdown"]
    assert "public_rss_fallback" in item["limits"]
    assert "listing_only" in item["limits"]
    assert result["receipt"]["attempts"][0]["status"] == "ok"
    assert "json_blocked:403" in result["receipt"]["attempts"][0]["reason"]


class FakeThreads(ThreadsSearchAdapter):
    def _access_token(self):
        return "test-token"

    def _search(self, query, *, mode, token):
        assert token == "test-token"
        return {
            "data": [
                {
                    "id": "123",
                    "text": "Agent browsers should be modular.",
                    "permalink": "https://www.threads.net/@agentlas/post/abc",
                    "timestamp": "2026-06-24T00:00:00+0000",
                    "username": "agentlas",
                }
            ]
        }

    def _profile(self, user_id, *, token):
        assert token == "test-token"
        assert user_id == "me"
        return {
            "id": "17841400000000000",
            "username": "agentlas",
            "name": "Agentlas",
            "threads_biography": "Modular agent research engine.",
            "threads_profile_picture_url": "https://example.com/avatar.jpg",
            "is_verified": True,
        }

    def _profile_lookup(self, username, *, token):
        assert token == "test-token"
        assert username == "agentlas"
        return {
            "id": "17841400000000000",
            "username": "agentlas",
            "name": "Agentlas",
            "threads_biography": "Lookup works.",
        }

    def _user_posts(self, user_id, *, token):
        assert token == "test-token"
        assert user_id == "me"
        return {
            "data": [
                {
                    "id": "post_1",
                    "text": "Research loadouts are spaceship hardpoints.",
                    "permalink": "https://www.threads.net/@agentlas/post/abc",
                    "timestamp": "2026-06-24T00:00:00+0000",
                    "username": "agentlas",
                    "media_type": "TEXT_POST",
                }
            ]
        }

    def _user_replies(self, user_id, *, token):
        assert token == "test-token"
        assert user_id == "me"
        return {
            "data": [
                {
                    "id": "reply_1",
                    "text": "Replies are readable too.",
                    "permalink": "https://www.threads.net/@agentlas/post/reply",
                    "timestamp": "2026-06-24T00:10:00+0000",
                    "username": "agentlas",
                    "media_type": "TEXT_POST",
                }
            ]
        }


class FakeThreadsPublic(ThreadsPublicWebAdapter):
    def _fetch(self, url):
        assert url == "https://www.threads.net/@agentlas"
        return (
            200,
            """
            <html>
              <head>
                <title>Agentlas (@agentlas) on Threads</title>
                <meta property="og:title" content="Agentlas (@agentlas) on Threads" />
                <meta property="og:description" content="Modular research hardpoints for agents." />
              </head>
              <body><main>Latest public Threads profile text.</main></body>
            </html>
            """,
            url,
            "text/html; charset=utf-8",
        )


class LoginWallThreadsPublic(ThreadsPublicWebAdapter):
    def _fetch(self, url):
        assert url == "https://www.threads.net/@agentlas"
        return (
            200,
            """
            <html>
              <head>
                <title>Threads • Log in</title>
                <meta property="og:title" content="Threads • Log in" />
                <meta property="og:description" content="Join Threads to share ideas. Log in with your Instagram." />
              </head>
              <body>Threads • Log in Scan to get the app Log in with your Instagram.</body>
            </html>
            """,
            "https://www.threads.com/login/?next=https%3A%2F%2Fwww.threads.com%2F%40agentlas%2F",
            "text/html; charset=utf-8",
        )


def test_threads_adapter_requires_token_nonfatally(tmp_path, monkeypatch):
    monkeypatch.delenv("THREADS_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("AGENTLAS_THREADS_ACCESS_TOKEN", raising=False)
    result = ResearchEngine(registry=AdapterRegistry([ThreadsSearchAdapter()]), home=tmp_path).run(
        {
            "query": "Search Threads",
            "source_hints": ["threads:keyword:agent browser"],
            "allowed_modules": ["platform.threads"],
        }
    )

    assert result["status"] == "partial"
    assert result["results"] == []
    assert result["receipt"]["attempts"][0]["module"] == "platform.threads"
    assert result["receipt"]["attempts"][0]["status"] == "module_unavailable"


def test_threads_keyword_without_token_uses_public_search_fallback(tmp_path, monkeypatch):
    class ThreadsDuckDuckGoFallback(DuckDuckGoHtmlSearchAdapter):
        def _fetch_text(self, url):
            assert url == "https://lite.duckduckgo.com/lite/?q=agent+browser+Threads+site%3Athreads.com"
            return """<html><body>
            <a rel="nofollow" href="/l/?uddg=https%3A%2F%2Fwww.threads.com%2F%40agentlas%2Fpost%2Fabc">Agent browser on Threads</a>
            </body></html>"""

    monkeypatch.delenv("THREADS_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("AGENTLAS_THREADS_ACCESS_TOKEN", raising=False)
    result = ResearchEngine(registry=AdapterRegistry([ThreadsSearchAdapter(), ThreadsDuckDuckGoFallback()]), home=tmp_path).run(
        {
            "query": "Search Threads",
            "source_hints": ["threads:keyword:agent browser"],
            "loadout": "auto",
            "max_cost": {"requests": 2},
        }
    )

    assert result["status"] == "ok"
    assert result["receipt"]["policy"]["source_hints_used"] == [
        "search:ddg_html:agent browser Threads site:threads.com",
        "search:news_rss:agent browser Threads site:threads.com",
    ]
    assert result["receipt"]["module_chain"] == ["search.ddg_html"]
    assert not any(attempt["module"] == "platform.threads" for attempt in result["receipt"]["attempts"])
    assert result["results"][0]["platform"] == "web_search"
    assert "Agent browser on Threads" in result["results"][0]["content_markdown"]


def test_threads_keyword_with_token_still_uses_public_search_fallback_in_auto(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTLAS_THREADS_ACCESS_TOKEN", "test-token")

    payload = run_research_plan(
        {
            "query": "Search Threads",
            "source_hints": ["threads:keyword:agent browser"],
            "loadout": "auto",
            "max_cost": {"requests": 5},
        }
    )

    assert payload["source_hints_used"] == [
        "search:ddg_html:agent browser Threads site:threads.com",
        "search:news_rss:agent browser Threads site:threads.com",
    ]
    assert payload["policy"]["source_hint_count_before_budget"] == 2
    assert "platform.threads" not in payload["mounted_modules"]


def test_threads_public_adapter_reads_profile_without_token(tmp_path, monkeypatch):
    monkeypatch.delenv("THREADS_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("AGENTLAS_THREADS_ACCESS_TOKEN", raising=False)
    result = ResearchEngine(registry=AdapterRegistry([ThreadsSearchAdapter(), FakeThreadsPublic()]), home=tmp_path).run(
        {
            "query": "Read public Threads profile",
            "source_hints": ["threads:lookup:agentlas"],
            "loadout": "auto",
        }
    )

    assert result["status"] == "ok"
    assert result["request"]["loadout"] == "auto"
    assert "platform.threads.public" in result["request"]["allowed_modules"]
    assert result["receipt"]["attempts"][0]["module"] == "platform.threads"
    assert result["receipt"]["attempts"][0]["status"] == "module_unavailable"
    assert result["receipt"]["attempts"][1]["module"] == "platform.threads.public"
    assert result["receipt"]["attempts"][1]["status"] == "ok"
    item = result["results"][0]
    assert item["platform"] == "threads"
    assert item["title"] == "Agentlas (@agentlas) on Threads"
    assert "Modular research hardpoints for agents." in item["content_markdown"]
    assert "public_html_fallback" in item["limits"]
    assert "official_api_preferred" in item["limits"]
    coverage = result["receipt"]["policy"]["evidence_coverage"]
    assert coverage["status"] == "public_social_fallback"
    assert coverage["public_social_fallback_evidence"] is True
    assert coverage["official_social_modules_missing"] == ["platform.threads"]
    assert coverage["completion_blockers"] == ["threads_live_graph_check"]
    assert "official_threads_missing" in coverage["warnings"]
    assert "public_social_fallback_not_official" in coverage["warnings"]


def test_threads_public_web_loadout_still_marks_official_graph_gap(tmp_path, monkeypatch):
    monkeypatch.delenv("THREADS_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("AGENTLAS_THREADS_ACCESS_TOKEN", raising=False)
    result = ResearchEngine(registry=AdapterRegistry([FakeThreadsPublic()]), home=tmp_path).run(
        {
            "query": "Read public Threads profile",
            "source_hints": ["https://www.threads.net/@agentlas"],
            "loadout": "public-web",
        }
    )

    assert result["status"] == "ok"
    assert result["receipt"]["attempts"][0]["module"] == "platform.threads.public"
    item = result["results"][0]
    assert item["platform"] == "threads"
    assert "public_html_fallback" in item["limits"]
    coverage = result["receipt"]["policy"]["evidence_coverage"]
    assert coverage["status"] == "public_social_fallback"
    assert coverage["official_social_modules_missing"] == ["platform.threads"]
    assert coverage["missing_credentials"] == ["AGENTLAS_THREADS_ACCESS_TOKEN", "THREADS_ACCESS_TOKEN"]
    assert coverage["completion_blockers"] == ["threads_live_graph_check"]
    assert "official_threads_missing" in coverage["warnings"]


def test_threads_public_adapter_marks_login_wall_blocked(tmp_path, monkeypatch):
    monkeypatch.delenv("THREADS_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("AGENTLAS_THREADS_ACCESS_TOKEN", raising=False)
    result = ResearchEngine(registry=AdapterRegistry([ThreadsSearchAdapter(), LoginWallThreadsPublic()]), home=tmp_path).run(
        {
            "query": "Read public Threads profile",
            "source_hints": ["threads:lookup:agentlas"],
            "loadout": "auto",
        }
    )

    assert result["status"] == "partial"
    assert result["receipt"]["attempts"][0]["module"] == "platform.threads"
    assert result["receipt"]["attempts"][0]["status"] == "module_unavailable"
    assert result["receipt"]["attempts"][1]["module"] == "platform.threads.public"
    assert result["receipt"]["attempts"][1]["status"] == "blocked"
    assert result["receipt"]["attempts"][1]["reason"] == "auth_required;public_html_status=200"
    assert result["results"][0]["confidence"] == "blocked"
    assert result["results"][0]["limits"] == ["auth_required"]
    coverage = result["receipt"]["policy"]["evidence_coverage"]
    assert coverage["official_social_modules_missing"] == ["platform.threads"]
    assert coverage["completion_blockers"] == ["threads_live_graph_check"]
    suggestions = result["receipt"]["policy"]["escalation_advice"]["suggestions"]
    assert any(suggestion["reason"] == "threads_token_missing" for suggestion in suggestions)


def test_threads_login_wall_is_not_promoted_by_generic_http_reader(tmp_path, monkeypatch):
    monkeypatch.delenv("THREADS_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("AGENTLAS_THREADS_ACCESS_TOKEN", raising=False)
    result = ResearchEngine(
        registry=AdapterRegistry([LoginWallThreadsPublic(), HttpReaderAdapter(), StagehandBrowserAdapter()]),
        home=tmp_path,
    ).run(
        {
            "query": "Read public Threads profile",
            "source_hints": ["https://www.threads.net/@agentlas"],
            "loadout": "public-web",
        }
    )

    assert result["status"] == "partial"
    attempts = result["receipt"]["attempts"]
    assert attempts[0]["module"] == "platform.threads.public"
    assert attempts[0]["status"] == "blocked"
    assert attempts[1]["module"] == "read.http"
    assert attempts[1]["status"] == "blocked"
    assert attempts[1]["reason"] == "auth_required;status=200"
    assert not any(attempt["module"].startswith("browser.") for attempt in attempts)
    browser_execution = result["receipt"]["policy"]["browser_execution"]
    assert browser_execution["attempted"] is False
    assert browser_execution["status"] == "not_requested"
    assert result["results"][0]["confidence"] == "blocked"
    assert not any(item["title"] == "Threads • Log in" and item["confidence"] == "usable" for item in result["results"])
    coverage = result["receipt"]["policy"]["evidence_coverage"]
    assert coverage["official_social_modules_missing"] == ["platform.threads"]
    assert coverage["missing_credentials"] == ["AGENTLAS_THREADS_ACCESS_TOKEN", "THREADS_ACCESS_TOKEN"]
    assert coverage["completion_blockers"] == ["threads_live_graph_check"]
    suggestions = result["receipt"]["policy"]["escalation_advice"]["suggestions"]
    assert any(suggestion["reason"] == "threads_token_missing" for suggestion in suggestions)
    assert any(
        suggestion["reason"] == "browser_loadout_available_after_public_routes_blocked"
        for suggestion in suggestions
    )


def test_threads_public_adapter_rejects_keyword_scraping(tmp_path, monkeypatch):
    monkeypatch.delenv("THREADS_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("AGENTLAS_THREADS_ACCESS_TOKEN", raising=False)
    result = ResearchEngine(registry=AdapterRegistry([ThreadsPublicWebAdapter()]), home=tmp_path).run(
        {
            "query": "Search Threads",
            "source_hints": ["threads:keyword:agent browser"],
            "allowed_modules": ["platform.threads.public"],
        }
    )

    assert result["status"] == "partial"
    assert result["results"] == []
    assert result["receipt"]["attempts"][0]["module"] == "research.core"
    assert result["receipt"]["attempts"][0]["reason"] == "no_adapter_for_source_hint"


def test_threads_adapter_reads_official_search_payload(tmp_path):
    result = ResearchEngine(registry=AdapterRegistry([FakeThreads()]), home=tmp_path).run(
        {
            "query": "Search Threads",
            "source_hints": ["threads:keyword:agent browser"],
            "allowed_modules": ["platform.threads"],
        }
    )

    assert result["status"] == "ok"
    item = result["results"][0]
    assert item["platform"] == "threads"
    assert "Agent browsers should be modular." in item["content_markdown"]
    assert "official_api" in item["limits"]
    assert "permission_gated" in item["limits"]
    assert "test-token" not in str(result)
    coverage = result["receipt"]["policy"]["evidence_coverage"]
    assert coverage["status"] == "official_social"
    assert coverage["official_social_evidence"] is True
    assert coverage["completion_blockers"] == []


def test_threads_adapter_reads_profile_payload(tmp_path):
    result = ResearchEngine(registry=AdapterRegistry([FakeThreads()]), home=tmp_path).run(
        {
            "query": "Read Threads profile",
            "source_hints": ["threads:profile:me"],
            "loadout": "social",
        }
    )

    assert result["status"] == "ok"
    item = result["results"][0]
    assert item["platform"] == "threads"
    assert item["title"] == "Threads profile: @agentlas"
    assert "Modular agent research engine." in item["content_markdown"]
    assert "profile_read" in item["limits"]
    assert result["receipt"]["module_chain"] == ["platform.threads"]
    assert "test-token" not in str(result)


def test_threads_adapter_reads_profile_lookup_payload(tmp_path):
    result = ResearchEngine(registry=AdapterRegistry([FakeThreads()]), home=tmp_path).run(
        {
            "query": "Lookup Threads profile",
            "source_hints": ["threads:lookup:agentlas"],
            "loadout": "social",
        }
    )

    assert result["status"] == "ok"
    item = result["results"][0]
    assert item["title"] == "Threads profile: @agentlas"
    assert "Lookup works." in item["content_markdown"]
    assert "profile_lookup" in item["limits"]


def test_threads_adapter_reads_posts_and_replies(tmp_path):
    result = ResearchEngine(registry=AdapterRegistry([FakeThreads()]), home=tmp_path).run(
        {
            "query": "Read Threads posts",
            "source_hints": ["threads:posts:me", "threads:replies:me"],
            "loadout": "social",
        }
    )

    assert result["status"] == "ok"
    assert len(result["results"]) == 2
    posts = result["results"][0]
    replies = result["results"][1]
    assert "Research loadouts are spaceship hardpoints." in posts["content_markdown"]
    assert "Replies are readable too." in replies["content_markdown"]
    assert "posts_read" in posts["limits"]
    assert "replies_read" in replies["limits"]
