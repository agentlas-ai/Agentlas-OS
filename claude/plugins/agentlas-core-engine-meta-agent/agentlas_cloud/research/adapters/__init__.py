"""Built-in lightweight research adapters."""

from .http_reader import HttpReaderAdapter
from .agent_browser_cli import AgentBrowserCliAdapter
from .browseros_browser import BrowserOSBrowserAdapter
from .browser_use import BrowserUseAdapter
from .duckduckgo_html_search import DuckDuckGoHtmlSearchAdapter
from .github_repos_search import GitHubReposSearchAdapter
from .hyperagent_browser import HyperAgentBrowserAdapter
from .insane_fetch import InsaneFetchAdapter
from .jina_reader import JinaReaderAdapter, JinaSearchAdapter
from .news_rss_search import NewsRssSearchAdapter
from .playwright_mcp import PlaywrightMcpAdapter
from .stagehand_browser import StagehandBrowserAdapter
from .steel_browser import SteelBrowserAdapter

__all__ = [
    "AgentBrowserCliAdapter",
    "BrowserOSBrowserAdapter",
    "BrowserUseAdapter",
    "DuckDuckGoHtmlSearchAdapter",
    "GitHubReposSearchAdapter",
    "HyperAgentBrowserAdapter",
    "HttpReaderAdapter",
    "InsaneFetchAdapter",
    "JinaReaderAdapter",
    "JinaSearchAdapter",
    "NewsRssSearchAdapter",
    "PlaywrightMcpAdapter",
    "StagehandBrowserAdapter",
    "SteelBrowserAdapter",
]
