from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class AgentResult:
    agent_name: str
    symbol: str | None
    action: str
    confidence: float
    reason: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PipelineResult:
    index: dict[str, Any]
    symbols: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def result_dict(result: AgentResult | dict[str, Any]) -> dict[str, Any]:
    if isinstance(result, AgentResult):
        return result.to_dict()
    return result
