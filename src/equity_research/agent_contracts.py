"""Shared contracts for deterministic worker-agent boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


AgentName = Literal["market_analyst", "company_researcher"]


class AgentContractError(ValueError):
    """Raised when worker-agent input or output violates the project contract."""


@dataclass(frozen=True)
class AgentLimitation:
    """One deterministic limitation propagated to a worker-agent result."""

    agent: AgentName
    symbol: str | None
    dimension: str
    reason_code: str
    message: str
