"""App-facing LangGraph composition with terminal Supervisor report synthesis."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol, TypedDict

from langgraph.graph import END, START, StateGraph

from equity_research.config import Equity
from equity_research.supervisor_contracts import (
    SupervisorPlan,
    SupervisorState,
    build_supervisor_plan,
)
from equity_research.supervisor_graph import (
    CompanyWorker,
    MarketWorker,
    build_supervisor_graph,
)
from equity_research.supervisor_report import SupervisorReport


class ReportSynthesizer(Protocol):
    """Callable boundary for validated final-report synthesis."""

    def __call__(
        self,
        *,
        state: SupervisorState,
    ) -> SupervisorReport:
        """Return one deterministically validated Supervisor report."""


class SupervisorResearchGraphInput(TypedDict):
    """Input accepted by the app-facing research graph."""

    plan: SupervisorPlan


class SupervisorResearchGraphOutput(TypedDict):
    """Output returned by the app-facing research graph."""

    supervisor_state: SupervisorState
    report: SupervisorReport


class SupervisorResearchGraphState(
    SupervisorResearchGraphInput,
    SupervisorResearchGraphOutput,
    total=False,
):
    """Internal state spanning worker orchestration and final synthesis."""


@dataclass(frozen=True)
class SupervisorResearchResult:
    """Validated app-facing result from the complete Supervisor graph."""

    state: SupervisorState
    report: SupervisorReport


def build_supervisor_research_graph(
    *,
    market_worker: MarketWorker,
    company_worker: CompanyWorker,
    report_synthesizer: ReportSynthesizer,
):
    """Build the complete worker-orchestration + final-synthesis LangGraph."""

    if not callable(market_worker):
        raise TypeError(
            "market_worker must be callable."
        )

    if not callable(company_worker):
        raise TypeError(
            "company_worker must be callable."
        )

    if not callable(report_synthesizer):
        raise TypeError(
            "report_synthesizer must be callable."
        )

    worker_graph = build_supervisor_graph(
        market_worker=market_worker,
        company_worker=company_worker,
    )

    def worker_supervisor_node(
        graph_state: SupervisorResearchGraphState,
    ) -> dict[str, SupervisorState]:
        plan = _plan_from_state(
            graph_state
        )
        output = worker_graph.invoke(
            {
                "plan": plan,
            }
        )
        supervisor_state = output.get(
            "supervisor_state"
        )

        if not isinstance(
            supervisor_state,
            SupervisorState,
        ):
            raise RuntimeError(
                "Worker Supervisor subgraph did not return SupervisorState."
            )

        return {
            "supervisor_state": supervisor_state,
        }

    def final_report_synthesis_node(
        graph_state: SupervisorResearchGraphState,
    ) -> dict[str, SupervisorReport]:
        supervisor_state = _supervisor_state_from_state(
            graph_state
        )
        report = report_synthesizer(
            state=supervisor_state,
        )

        _validate_report_matches_state(
            report=report,
            state=supervisor_state,
        )

        return {
            "report": report,
        }

    builder = StateGraph(
        SupervisorResearchGraphState,
        input_schema=SupervisorResearchGraphInput,
        output_schema=SupervisorResearchGraphOutput,
    )

    builder.add_node(
        "worker_supervisor",
        worker_supervisor_node,
    )
    builder.add_node(
        "final_report_synthesis",
        final_report_synthesis_node,
    )

    builder.add_edge(
        START,
        "worker_supervisor",
    )
    builder.add_edge(
        "worker_supervisor",
        "final_report_synthesis",
    )
    builder.add_edge(
        "final_report_synthesis",
        END,
    )

    return builder.compile()


def run_supervisor_research_graph(
    *,
    request_text: str,
    requested_symbols: Sequence[str],
    market_worker: MarketWorker,
    company_worker: CompanyWorker,
    report_synthesizer: ReportSynthesizer,
    equities: Mapping[str, Equity] | None = None,
) -> SupervisorResearchResult:
    """Validate scope and run the complete app-facing Supervisor graph."""

    plan = build_supervisor_plan(
        request_text=request_text,
        requested_symbols=requested_symbols,
        equities=equities,
    )
    graph = build_supervisor_research_graph(
        market_worker=market_worker,
        company_worker=company_worker,
        report_synthesizer=report_synthesizer,
    )
    output = graph.invoke(
        {
            "plan": plan,
        }
    )
    supervisor_state = output.get(
        "supervisor_state"
    )
    report = output.get(
        "report"
    )

    if not isinstance(
        supervisor_state,
        SupervisorState,
    ):
        raise RuntimeError(
            "Complete Supervisor graph did not return SupervisorState."
        )

    _validate_report_matches_state(
        report=report,
        state=supervisor_state,
    )

    return SupervisorResearchResult(
        state=supervisor_state,
        report=report,
    )


def _plan_from_state(
    state: SupervisorResearchGraphState,
) -> SupervisorPlan:
    plan = state.get(
        "plan"
    )

    if not isinstance(
        plan,
        SupervisorPlan,
    ):
        raise TypeError(
            "Supervisor research graph is missing a valid plan."
        )

    return plan


def _supervisor_state_from_state(
    state: SupervisorResearchGraphState,
) -> SupervisorState:
    supervisor_state = state.get(
        "supervisor_state"
    )

    if not isinstance(
        supervisor_state,
        SupervisorState,
    ):
        raise TypeError(
            "Supervisor research graph is missing validated SupervisorState."
        )

    return supervisor_state


def _validate_report_matches_state(
    *,
    report: object,
    state: SupervisorState,
) -> None:
    if not isinstance(
        report,
        SupervisorReport,
    ):
        raise TypeError(
            "report_synthesizer must return SupervisorReport."
        )

    if report.mode != state.request.mode:
        raise RuntimeError(
            "Supervisor report mode does not match validated SupervisorState."
        )

    if report.symbols != state.request.requested_symbols:
        raise RuntimeError(
            "Supervisor report symbols do not match validated SupervisorState."
        )

    if report.status != state.status:
        raise RuntimeError(
            "Supervisor report status does not match validated SupervisorState."
        )
