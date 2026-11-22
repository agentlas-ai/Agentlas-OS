#!/usr/bin/env bash
# Follow-up ranker URL contract.
#
# `_canonicalize_url` is the one place every search adapter's citation URL passes
# through before it is ranked. `urlsplit()` parses a netloc it cannot use and
# raises nothing; only `.port` validates the port, so `example.com:99999` and
# `example.com:abc` raised ValueError out of a plain ranking pass. That escaped
# `ResearchEngine.run` and ended `agentlas research search`/`gather` with a
# traceback instead of a receipt.
#
# A URL that cannot be used is not a crash: it is simply not a candidate. This
# gate asserts that contract, and that an IPv6 authority keeps its brackets in
# the canonical form (hostname strips them; rebuilding the netloc must put them
# back or `https://[::1]:8080/x` became `https://::1:8080/x`).
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

python3 - <<'PY' || failures=$(( ${failures:-0} + 1 ))
import sys

from agentlas_cloud.research.contracts import (
    ResearchAttempt,
    ResearchModuleManifest,
    ResearchRequest,
    ResearchResult,
)
from agentlas_cloud.research.engine import ResearchEngine
from agentlas_cloud.research.registry import AdapterRegistry
from agentlas_cloud.research.search_ranker import _canonicalize_url

SEARCH_URL = "https://lite.duckduckgo.com/lite/?q=widget"
problems = []

# An authority the URL parser accepts but cannot use is not a candidate.
for url in (
    "https://example.com:99999/x",
    "https://example.com:abc/x",
    "https://example.com:-1/x",
    "https://example.com:65536/x",
    "https://[2001:db8::1]:99999/x",
):
    try:
        actual = _canonicalize_url(url)
    except ValueError as exc:
        problems.append(f"{url}: raised ValueError out of ranking ({exc})")
        continue
    if actual != "":
        problems.append(f"{url}: expected no candidate, got {actual!r}")

# A usable authority is canonicalised as before, brackets included.
for url, expected in (
    ("https://example.com/a", "https://example.com/a"),
    ("https://example.com:8080/a", "https://example.com:8080/a"),
    ("https://example.com:65535/a", "https://example.com:65535/a"),
    ("https://[::1]:8080/x", "https://[::1]:8080/x"),
    ("https://[::1]/x", "https://[::1]/x"),
    ("https://example.com:/x", "https://example.com/x"),
    ("https://example.com:0/x", "https://example.com/x"),
    ("https://Example.COM:8080/A/?utm_source=s&z=1", "https://example.com:8080/A?z=1"),
):
    try:
        actual = _canonicalize_url(url)
    except ValueError as exc:
        problems.append(f"{url}: raised ValueError out of ranking ({exc})")
        continue
    if actual != expected:
        problems.append(f"{url}: expected {expected!r}, got {actual!r}")


class StubSearch:
    """A search adapter returning one real-shaped citation."""

    module_id = "search.ddg_html"
    capabilities = ("web_search",)
    weight = "light"
    manifest = ResearchModuleManifest(
        module_id="search.ddg_html",
        capabilities=["web_search"],
        weight="light",
        slot="search",
    )

    def __init__(self, citation_url):
        self.citation_url = citation_url

    def can_handle(self, source_hint, request):
        return True

    def read(self, source_hint, request):
        result = ResearchResult(
            source_id="search:ddg_html:widget",
            url=SEARCH_URL,
            title="DuckDuckGo HTML search: widget",
            platform="web_search",
            confidence="usable",
            limits=["public_html_search"],
            citations=[
                {"label": "duckduckgo-html-search", "url": SEARCH_URL},
                {"label": "Product page", "url": self.citation_url},
            ],
        )
        return result, ResearchAttempt(self.module_id, "ok", "", source_hint, weight=self.weight)


# The whole point: a ranking pass over such a citation finishes.
for citation_url in (
    "https://example.com:99999/product-page",
    "https://example.com:abc/product-page",
):
    engine = ResearchEngine(registry=AdapterRegistry([StubSearch(citation_url)]))
    request = ResearchRequest(
        query="widget",
        source_hints=["search:ddg_html:widget"],
        follow_results=1,
        allowed_modules=["search.ddg_html"],
    )
    try:
        engine.run(request)
    except ValueError as exc:
        problems.append(f"{citation_url}: research run raised ValueError ({exc})")

if problems:
    print("verify-research-ranker-urls: " + "\n  ".join(problems), file=sys.stderr)
    raise SystemExit(1)
print("verify-research-ranker-urls: passed")
PY

if [[ "${failures:-0}" -ne 0 ]]; then
  exit 1
fi
