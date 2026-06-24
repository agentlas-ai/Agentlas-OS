"""Agentlas Research Engine phase-0 core.

The research package is intentionally small: the core owns contracts, policy,
adapter routing, and receipts. Heavy browser/platform readers register as
optional modules instead of becoming mandatory runtime dependencies.
"""

from .contracts import ResearchModuleManifest, ResearchRequest, ResearchResult, ResearchReceipt
from .credentials import run_research_credentials
from .engine import ResearchEngine, run_research
from .doctor import run_research_doctor
from .loadouts import ResearchLoadout, loadout_catalog
from .armory import run_research_armory
from .browser_candidates import run_research_browser_candidates
from .bridge_contracts import run_research_bridge_check, run_research_bridge_contracts
from .platform_contracts import run_research_platform_check, run_research_platform_contracts
from .planner import run_research_plan
from .preflight import run_research_preflight
from .profile import run_research_profile
from .proofs import run_research_proofs
from .recommend import run_research_recommendation
from .hardpoints import run_research_hardpoints
from .social_fallbacks import run_research_social_fallbacks
from .verify import run_research_verify
from .status import run_research_status

__all__ = [
    "ResearchEngine",
    "ResearchLoadout",
    "ResearchModuleManifest",
    "ResearchReceipt",
    "ResearchRequest",
    "ResearchResult",
    "loadout_catalog",
    "run_research_credentials",
    "run_research_doctor",
    "run_research_bridge_check",
    "run_research_bridge_contracts",
    "run_research_browser_candidates",
    "run_research_platform_check",
    "run_research_platform_contracts",
    "run_research_armory",
    "run_research_hardpoints",
    "run_research",
    "run_research_plan",
    "run_research_preflight",
    "run_research_proofs",
    "run_research_recommendation",
    "run_research_social_fallbacks",
    "run_research_status",
    "run_research_verify",
    "run_research_profile",
]
