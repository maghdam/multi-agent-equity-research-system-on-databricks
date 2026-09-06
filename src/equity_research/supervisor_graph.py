"""LangGraph orchestration for the deterministic Supervisor worker plan."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol, TypedDict

from langgraph.graph import END, START, StateGraph

from equity_research.company_researcher import (
    CompanyResearcherResult,
    ResearchTopic,
)
from equity_research.config import Equity
from equity_research.market_analyst import MarketAnalystResult
from equity_research.supervisor_contracts import (
    SupervisorPlan,
    SupervisorRequest,
    SupervisorState,
    SupervisorWorkerOutcome,
    assemble_supervisor_state,
    build_supervisor_plan,
    failed_worker_outcome,
    successful_worker_outcome,
)


class MarketWorker(Protocol):
    """Callable boundary used by the LangGraph Market Analyst node."""

    def __call__(
        self,
        *,
        request: SupervisorRequest,
    ) -> MarketAnalystResult:
        """Return one already-validated Market Analyst result."""


class CompanyWorker(Protocol):
    """Callable boundary used by the LangGraph Company Researcher nodes."""

    def __call__(
        self,
        *,
        request: SupervisorRequest,
        topic: ResearchTopic,
    ) -> CompanyResearcherResult:
        """Return one already-validated Company Researcher result."""


class SupervisorGraphInput(TypedDict):
    """Input accepted by the compiled Supervisor graph."""

    plan: SupervisorPlan


class SupervisorGraphOutput(TypedDict):
    """Output returned by the compiled Supervisor graph."""

    supervisor_state: SupervisorState


class SupervisorGraphState(
    SupervisorGraphInput,
    SupervisorGraphOutput,
    total=False,
):
    """Internal graph state across parallel worker branches."""

    market_outcome: SupervisorWorkerOutcome
    recent_developments_outcome: SupervisorWorkerOutcome
    principal_risks_outcome: SupervisorWorkerOutcome


def build_supervisor_graph(
    *,
    market_worker: MarketWorker,
    company_worker: CompanyWorker,
):
    """Build and compile the MVP Supervisor LangGraph."""

    if not callable(market_worker):
        raise TypeError(
            "market_worker must be callable."
        )

    if not callable(company_worker):
        raise TypeError(
            "company_worker must be callable."
        )

    def market_analysis_node(
        state: SupervisorGraphState,
    ) -> dict[str, SupervisorWorkerOutcome]:
        request = _request_from_state(state)

        try:
            result = market_worker(
                request=request,
            )
        except Exception as exc:
            return {
                "market_outcome": _worker_exception_outcome(
                    route_id="market_analysis",
                    exc=exc,
                )
            }

        return {
            "market_outcome": successful_worker_outcome(
                route_id="market_analysis",
                result=result,
            )
        }

    def recent_developments_node(
        state: SupervisorGraphState,
    ) -> dict[str, SupervisorWorkerOutcome]:
        request = _request_from_state(state)

        try:
            result = company_worker(
                request=request,
                topic="recent_developments",
            )
        except Exception as exc:
            return {
                "recent_developments_outcome": _worker_exception_outcome(
                    route_id="recent_developments",
                    exc=exc,
                )
            }

        return {
            "recent_developments_outcome": successful_worker_outcome(
                route_id="recent_developments",
                result=result,
            )
        }

    def principal_risks_node(
        state: SupervisorGraphState,
    ) -> dict[str, SupervisorWorkerOutcome]:
        request = _request_from_state(state)

        try:
            result = company_worker(
                request=request,
                topic="principal_risks",
            )
        except Exception as exc:
            return {
                "principal_risks_outcome": _worker_exception_outcome(
                    route_id="principal_risks",
                    exc=exc,
                )
            }

        return {
            "principal_risks_outcome": successful_worker_outcome(
                route_id="principal_risks",
                result=result,
            )
        }

    def aggregate_node(
        state: SupervisorGraphState,
    ) -> dict[str, SupervisorState]:
        plan = state.get("plan")

        if not isinstance(
            plan,
            SupervisorPlan,
        ):
            raise TypeError(
                "Supervisor graph state is missing a valid plan."
            )

        outcomes = (
            _required_outcome(
                state,
                "market_outcome",
            ),
            _required_outcome(
                state,
                "recent_developments_outcome",
            ),
            _required_outcome(
                state,
                "principal_risks_outcome",
            ),
        )

        return {
            "supervisor_state": assemble_supervisor_state(
                plan=plan,
                outcomes=outcomes,
            )
        }

    builder = StateGraph(
        SupervisorGraphState,
        input_schema=SupervisorGraphInput,
        output_schema=SupervisorGraphOutput,
    )

    builder.add_node(
        "market_analysis",
        market_analysis_node,
    )
    builder.add_node(
        "recent_developments",
        recent_developments_node,
    )
    builder.add_node(
        "principal_risks",
        principal_risks_node,
    )
    builder.add_node(
        "aggregate",
        aggregate_node,
    )

    builder.add_edge(
        START,
        "market_analysis",
    )
    builder.add_edge(
        START,
        "recent_developments",
    )
    builder.add_edge(
        START,
        "principal_risks",
    )

    builder.add_edge(
        "market_analysis",
        "aggregate",
    )
    builder.add_edge(
        "recent_developments",
        "aggregate",
    )
    builder.add_edge(
        "principal_risks",
        "aggregate",
    )

    builder.add_edge(
        "aggregate",
        END,
    )

    return builder.compile()


def run_supervisor_graph(
    *,
    request_text: str,
    requested_symbols: Sequence[str],
    market_worker: MarketWorker,
    company_worker: CompanyWorker,
    equities: Mapping[str, Equity] | None = None,
) -> SupervisorState:
    """Validate scope, run the worker graph, and return deterministic state."""

    plan = build_supervisor_plan(
        request_text=request_text,
        requested_symbols=requested_symbols,
        equities=equities,
    )
    graph = build_supervisor_graph(
        market_worker=market_worker,
        company_worker=company_worker,
    )
    output = graph.invoke(
        {
            "plan": plan,
        }
    )
    state = output.get(
        "supervisor_state"
    )

    if not isinstance(
        state,
        SupervisorState,
    ):
        raise RuntimeError(
            "Compiled Supervisor graph did not return SupervisorState."
        )

    return state


def _request_from_state(
    state: SupervisorGraphState,
) -> SupervisorRequest:
    plan = state.get(
        "plan"
    )

    if not isinstance(
        plan,
        SupervisorPlan,
    ):
        raise TypeError(
            "Supervisor graph state is missing a valid plan."
        )

    return plan.request


def _required_outcome(
    state: SupervisorGraphState,
    key: str,
) -> SupervisorWorkerOutcome:
    outcome = state.get(key)

    if not isinstance(
        outcome,
        SupervisorWorkerOutcome,
    ):
        raise RuntimeError(
            f"Supervisor graph is missing required worker outcome {key!r}."
        )

    return outcome


def _worker_exception_outcome(
    *,
    route_id,
    exc: Exception,
) -> SupervisorWorkerOutcome:
    return failed_worker_outcome(
        route_id=route_id,
        reason_code="worker_exception",
        message=(
            f"{route_id} worker failed with "
            f"{type(exc).__name__}."
        ),
    )
