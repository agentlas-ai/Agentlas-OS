"""Platform cartridges for the Agentlas Research Engine."""

from .reddit import RedditOAuthAdapter, RedditPublicAdapter
from .threads import ThreadsPublicWebAdapter, ThreadsSearchAdapter

__all__ = ["RedditOAuthAdapter", "RedditPublicAdapter", "ThreadsPublicWebAdapter", "ThreadsSearchAdapter"]
