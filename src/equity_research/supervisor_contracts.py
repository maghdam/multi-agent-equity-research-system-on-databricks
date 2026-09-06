"""Deterministic request, routing, and aggregation contracts for the Supervisor."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from equity_research.agent_contracts import AgentLimitation
from equity_research.company_researcher import (
    CompanyResearcherResult,
    ResearchTopic,
)
from equity_research.config import Equity
from equity_research.market_analyst import MarketAnalystResult
from equity_research.tool_scope import resolve_requested_equities


RequestMode = Literal["single_company", "comparison"]
SupervisorRouteId = Literal[
    "market_analysis",
    "recent_developments",
    "principal_risks",
]
SupervisorWorker = Literal["market_analyst", "company_researcher"]
SupervisorOutcomeStatus = Literal["succeeded", "failed"]
SupervisorStatus = Literal["ready", "degraded", "unavailable"]


class SupervisorContractError(ValueError):
    """Raised when Supervisor request, routing, or aggregation is invalid."""


@dataclass(frozen=True)
class SupervisorRequest:
    """One normalized research request accepted by the Supervisor."""

    request_text: str
    requested_symbols: tuple[str, ...]
    mode: RequestMode


@dataclass(frozen=True)
class SupervisorRoute:
    """One deterministic worker route required for the MVP research request."""

    route_id: SupervisorRouteId
    worker: SupervisorWorker
    topic: ResearchTopic | None


@dataclass(frozen=True)
class SupervisorPlan:
    """Normalized request plus the exact worker routes required by the MVP."""

    request: SupervisorRequest
    routes: tuple[SupervisorRoute, ...]


@dataclass(frozen=True)
class SupervisorWorkerFailure:
    """One explicit worker/tool failure preserved for degraded reporting."""

    route_id: SupervisorRouteId
    reason_code: str
    message: str


WorkerResult = MarketAnalystResult | CompanyResearcherResult


@dataclass(frozen=True)
class SupervisorWorkerOutcome:
    """One succeeded or failed route outcome."""

    route_id: SupervisorRouteId
    status: SupervisorOutcomeStatus
    result: WorkerResult | None
    failure: SupervisorWorkerFailure | None


@dataclass(frozen=True)
class SupervisorState:
    """Validated aggregation state passed to later report synthesis."""

    request: SupervisorRequest
    outcomes: tuple[SupervisorWorkerOutcome, ...]
    limitations: tuple[AgentLimitation, ...]
    failures: tuple[SupervisorWorkerFailure, ...]
    status: SupervisorStatus


EXPECTED_ROUTES = (
    SupervisorRoute(
        route_id="market_analysis",
        worker="market_analyst",
        topic=None,
    ),
    SupervisorRoute(
        route_id="recent_developments",
        worker="company_researcher",
        topic="recent_developments",
    ),
    SupervisorRoute(
        route_id="principal_risks",
        worker="company_researcher",
        topic="principal_risks",
    ),
)


def build_supervisor_plan(
    *,
    request_text: str,
    requested_symbols: Sequence[str],
    equities: Mapping[str, Equity] | None = None,
) -> SupervisorPlan:
    """Validate request scope and produce the exact deterministic worker plan."""

    normalized_text = _required_text(
        request_text,
        "request_text",
    )
    requested = resolve_requested_equities(
        requested_symbols,
        equities=equities,
    )
    symbols = tuple(
        equity.symbol
        for equity in requested
    )

    mode: RequestMode = (
        "single_company"
        if len(symbols) == 1
        else "comparison"
    )

    return SupervisorPlan(
        request=SupervisorRequest(
            request_text=normalized_text,
            requested_symbols=symbols,
            mode=mode,
        ),
        routes=EXPECTED_ROUTES,
    )


def successful_worker_outcome(
    *,
    route_id: SupervisorRouteId,
    result: WorkerResult,
) -> SupervisorWorkerOutcome:
    """Create one succeeded route outcome."""

    if route_id not in {
        route.route_id
        for route in EXPECTED_ROUTES
    }:
        raise SupervisorContractError(
            f"Unknown Supervisor route_id: {route_id!r}."
        )

    if not isinstance(
        result,
        (MarketAnalystResult, CompanyResearcherResult),
    ):
        raise SupervisorContractError(
            "Succeeded Supervisor outcome requires a worker result."
        )

    return SupervisorWorkerOutcome(
        route_id=route_id,
        status="succeeded",
        result=result,
        failure=None,
    )


def failed_worker_outcome(
    *,
    route_id: SupervisorRouteId,
    reason_code: str,
    message: str,
) -> SupervisorWorkerOutcome:
    """Create one explicit failed route outcome."""

    if route_id not in {
        route.route_id
        for route in EXPECTED_ROUTES
    }:
        raise SupervisorContractError(
            f"Unknown Supervisor route_id: {route_id!r}."
        )

    failure = SupervisorWorkerFailure(
        route_id=route_id,
        reason_code=_required_text(
            reason_code,
            "reason_code",
        ),
        message=_required_text(
            message,
            "message",
        ),
    )

    return SupervisorWorkerOutcome(
        route_id=route_id,
        status="failed",
        result=None,
        failure=failure,
    )


def assemble_supervisor_state(
    *,
    plan: SupervisorPlan,
    outcomes: Sequence[SupervisorWorkerOutcome],
) -> SupervisorState:
    """Validate all route outcomes and derive ready/degraded/unavailable state."""

    if not isinstance(plan, SupervisorPlan):
        raise SupervisorContractError(
            "plan must be a SupervisorPlan."
        )

    _validate_plan(plan)

    if isinstance(outcomes, (str, bytes)):
        raise SupervisorContractError(
            "outcomes must be a sequence of SupervisorWorkerOutcome values."
        )

    indexed: dict[
        SupervisorRouteId,
        SupervisorWorkerOutcome,
    ] = {}

    for outcome in outcomes:
        if not isinstance(
            outcome,
            SupervisorWorkerOutcome,
        ):
            raise SupervisorContractError(
                "outcomes contain an invalid value."
            )

        if outcome.route_id in indexed:
            raise SupervisorContractError(
                f"Duplicate Supervisor outcome for route {outcome.route_id!r}."
            )

        indexed[outcome.route_id] = outcome

    expected_ids = tuple(
        route.route_id
        for route in EXPECTED_ROUTES
    )

    if set(indexed) != set(expected_ids):
        raise SupervisorContractError(
            "Supervisor outcomes must exactly match the planned routes."
        )

    ordered = tuple(
        indexed[route_id]
        for route_id in expected_ids
    )

    limitations: list[AgentLimitation] = []
    failures: list[SupervisorWorkerFailure] = []

    for route, outcome in zip(
        EXPECTED_ROUTES,
        ordered,
        strict=True,
    ):
        route_limitations, route_failure = _validate_outcome(
            route=route,
            outcome=outcome,
            requested_symbols=plan.request.requested_symbols,
        )
        limitations.extend(route_limitations)

        if route_failure is not None:
            failures.append(route_failure)

    if len(failures) == len(EXPECTED_ROUTES):
        status: SupervisorStatus = "unavailable"
    elif failures or limitations:
        status = "degraded"
    else:
        status = "ready"

    return SupervisorState(
        request=plan.request,
        outcomes=ordered,
        limitations=tuple(limitations),
        failures=tuple(failures),
        status=status,
    )


def _validate_plan(
    plan: SupervisorPlan,
) -> None:
    request = plan.request

    if not isinstance(request, SupervisorRequest):
        raise SupervisorContractError(
            "Supervisor plan request is invalid."
        )

    _required_text(
        request.request_text,
        "request_text",
    )

    if not request.requested_symbols:
        raise SupervisorContractError(
            "Supervisor request must contain requested symbols."
        )

    expected_mode = (
        "single_company"
        if len(request.requested_symbols) == 1
        else "comparison"
    )

    if request.mode != expected_mode:
        raise SupervisorContractError(
            "Supervisor request mode does not match requested-symbol count."
        )

    if tuple(plan.routes) != EXPECTED_ROUTES:
        raise SupervisorContractError(
            "Supervisor plan routes do not match the controlled MVP route set."
        )


def _validate_outcome(
    *,
    route: SupervisorRoute,
    outcome: SupervisorWorkerOutcome,
    requested_symbols: Sequence[str],
) -> tuple[
    tuple[AgentLimitation, ...],
    SupervisorWorkerFailure | None,
]:
    if outcome.route_id != route.route_id:
        raise SupervisorContractError(
            "Supervisor outcome route does not match its plan."
        )

    if outcome.status == "failed":
        if outcome.result is not None or outcome.failure is None:
            raise SupervisorContractError(
                "Failed Supervisor outcome must contain only failure details."
            )

        if outcome.failure.route_id != route.route_id:
            raise SupervisorContractError(
                "Worker failure route does not match its outcome."
            )

        _required_text(
            outcome.failure.reason_code,
            "reason_code",
        )
        _required_text(
            outcome.failure.message,
            "message",
        )

        return (), outcome.failure

    if outcome.status != "succeeded":
        raise SupervisorContractError(
            f"Unknown Supervisor outcome status: {outcome.status!r}."
        )

    if outcome.failure is not None or outcome.result is None:
        raise SupervisorContractError(
            "Succeeded Supervisor outcome must contain only a worker result."
        )

    if route.worker == "market_analyst":
        if not isinstance(
            outcome.result,
            MarketAnalystResult,
        ):
            raise SupervisorContractError(
                "Market-analysis route requires MarketAnalystResult."
            )

        _validate_market_result(
            outcome.result,
            requested_symbols=requested_symbols,
        )
        return outcome.result.limitations, None

    if not isinstance(
        outcome.result,
        CompanyResearcherResult,
    ):
        raise SupervisorContractError(
            "Company-research routes require CompanyResearcherResult."
        )

    if route.topic is None:
        raise SupervisorContractError(
            "Company-research route must declare a topic."
        )

    _validate_company_result(
        outcome.result,
        topic=route.topic,
        requested_symbols=requested_symbols,
    )

    return outcome.result.limitations, None


def _validate_market_result(
    result: MarketAnalystResult,
    *,
    requested_symbols: Sequence[str],
) -> None:
    requested = set(requested_symbols)
    covered: set[
        tuple[str, str]
    ] = set()

    for finding in result.findings:
        if not set(finding.symbols).issubset(
            requested
        ):
            raise SupervisorContractError(
                "Market Analyst finding is outside Supervisor request scope."
            )

        for symbol in finding.symbols:
            covered.add(
                (
                    finding.dimension,
                    symbol,
                )
            )

    limited: set[
        tuple[str, str]
    ] = set()

    for limitation in result.limitations:
        _validate_limitation(
            limitation,
            expected_agent="market_analyst",
            requested_symbols=requested,
        )

        if (
            limitation.symbol is not None
            and limitation.dimension
            in {"market", "fundamental"}
        ):
            limited.add(
                (
                    limitation.dimension,
                    limitation.symbol,
                )
            )

    for symbol in requested_symbols:
        for dimension in (
            "market",
            "fundamental",
        ):
            key = (
                dimension,
                symbol,
            )

            if key not in covered and key not in limited:
                raise SupervisorContractError(
                    "Market Analyst result silently omits requested "
                    f"{dimension} coverage for {symbol}."
                )


def _validate_company_result(
    result: CompanyResearcherResult,
    *,
    topic: ResearchTopic,
    requested_symbols: Sequence[str],
) -> None:
    requested = set(requested_symbols)
    covered: set[str] = set()

    for finding in result.findings:
        if finding.topic != topic:
            raise SupervisorContractError(
                "Company Researcher finding topic does not match its route."
            )

        if not set(finding.symbols).issubset(
            requested
        ):
            raise SupervisorContractError(
                "Company Researcher finding is outside Supervisor request scope."
            )

        covered.update(
            finding.symbols
        )

    has_topic_limitation = False

    for limitation in result.limitations:
        _validate_limitation(
            limitation,
            expected_agent="company_researcher",
            requested_symbols=requested,
        )

        if limitation.dimension != topic:
            raise SupervisorContractError(
                "Company Researcher limitation topic does not match its route."
            )

        if (
            limitation.symbol is None
            or limitation.symbol in requested
        ):
            has_topic_limitation = True

    missing_symbols = requested - covered

    if missing_symbols and not has_topic_limitation:
        raise SupervisorContractError(
            "Company Researcher result silently omits requested-symbol "
            f"coverage for {sorted(missing_symbols)} in topic {topic!r}."
        )


def _validate_limitation(
    limitation: AgentLimitation,
    *,
    expected_agent: str,
    requested_symbols: set[str],
) -> None:
    if not isinstance(
        limitation,
        AgentLimitation,
    ):
        raise SupervisorContractError(
            "Worker limitations contain an invalid value."
        )

    if limitation.agent != expected_agent:
        raise SupervisorContractError(
            "Worker limitation agent does not match its route."
        )

    if (
        limitation.symbol is not None
        and limitation.symbol not in requested_symbols
    ):
        raise SupervisorContractError(
            "Worker limitation symbol is outside Supervisor request scope."
        )

    _required_text(
        limitation.dimension,
        "limitation dimension",
    )
    _required_text(
        limitation.reason_code,
        "limitation reason_code",
    )
    _required_text(
        limitation.message,
        "limitation message",
    )


def _required_text(
    value: object,
    field: str,
) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SupervisorContractError(
            f"{field} must be a nonblank string."
        )

    return value.strip()
