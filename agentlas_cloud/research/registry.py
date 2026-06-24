"""Adapter registry for detachable research modules."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from .contracts import ResearchAttempt, ResearchModuleManifest, ResearchRequest, ResearchResult


class ResearchAdapter(Protocol):
    module_id: str
    capabilities: tuple[str, ...]
    weight: str
    manifest: ResearchModuleManifest

    def can_handle(self, source_hint: str, request: ResearchRequest) -> bool:
        ...

    def read(self, source_hint: str, request: ResearchRequest) -> tuple[ResearchResult | None, ResearchAttempt]:
        ...


@dataclass
class AdapterRegistry:
    adapters: list[ResearchAdapter] = field(default_factory=list)

    def register(self, adapter: ResearchAdapter) -> None:
        if any(existing.module_id == adapter.module_id for existing in self.adapters):
            self.adapters = [existing for existing in self.adapters if existing.module_id != adapter.module_id]
        self.adapters.append(adapter)

    def candidates(self, source_hint: str, request: ResearchRequest) -> list[ResearchAdapter]:
        return [adapter for adapter in self.adapters if adapter.can_handle(source_hint, request)]

    def module_manifests(self) -> list[dict]:
        return [adapter.manifest.to_dict() for adapter in self.adapters]
