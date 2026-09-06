"""MLflow tracing setup for the app-facing equity-research graph.

Tracing is opt-in. This module configures Databricks-managed MLflow and enables
MLflow's supported LangGraph tracing integration through LangChain autologging.

The graph state intentionally contains validated request/worker/report objects rather
than raw provider article or filing bodies. Trace tags and metadata added here are
limited to project/runtime scope and do not include provider source text.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import mlflow

from equity_research.config import Equity
from equity_research.supervisor_graph import CompanyWorker, MarketWorker
from equity_research.supervisor_research_graph import (
    ReportSynthesizer,
    SupervisorResearchResult,
    run_supervisor_research_graph,
)


DEFAULT_TRACE_EXPERIMENT = "/Shared/equity-research-genai"
TRACE_PROJECT = "multi-agent-equity-research-system"
TRACE_COMPONENT = "supervisor_research_graph"
TRACE_PRIVACY_BOUNDARY = "validated_graph_state_no_raw_provider_text"


@dataclass(frozen=True)
class MlflowTracingConfig:
    """Configuration for Databricks-managed MLflow tracing."""

    experiment_name: str = DEFAULT_TRACE_EXPERIMENT
    profile: str | None = None
    environment: str = "dev"

    def __post_init__(self) -> None:
        if not isinstance(self.experiment_name, str) or not self.experiment_name.strip():
            raise ValueError(
                "experiment_name must be a nonblank string."
            )

        if self.profile is not None and (
            not isinstance(self.profile, str)
            or not self.profile.strip()
        ):
            raise ValueError(
                "profile must be None or a nonblank string."
            )

        if not isinstance(self.environment, str) or not self.environment.strip():
            raise ValueError(
                "environment must be a nonblank string."
            )


def mlflow_tracking_uri(
    config: MlflowTracingConfig,
) -> str:
    """Return the Databricks tracking URI for one tracing configuration."""

    if not isinstance(config, MlflowTracingConfig):
        raise TypeError(
            "config must be MlflowTracingConfig."
        )

    if config.profile is None:
        return "databricks"

    return f"databricks://{config.profile.strip()}"


def configure_mlflow_tracing(
    config: MlflowTracingConfig,
) -> str:
    """Configure Databricks MLflow and enable unified LangGraph tracing."""

    tracking_uri = mlflow_tracking_uri(
        config
    )

    mlflow.set_tracking_uri(
        tracking_uri
    )
    mlflow.set_experiment(
        config.experiment_name.strip()
    )

    # MLflow documents LangGraph tracing through the LangChain integration.
    # This is intentionally called once per process entry point rather than
    # decorating individual graph nodes, which could create disconnected roots.
    mlflow.langchain.autolog(
        log_traces=True,
        silent=False,
    )

    return tracking_uri


def research_trace_tags(
    *,
    requested_symbols: Sequence[str],
    environment: str,
) -> dict[str, str]:
    """Build privacy-safe trace tags from request scope only."""

    if not isinstance(environment, str) or not environment.strip():
        raise ValueError(
            "environment must be a nonblank string."
        )

    symbols = tuple(
        _normalized_symbol(symbol)
        for symbol in requested_symbols
    )

    if len(symbols) == 1:
        request_mode = "single_company"
    elif len(symbols) == 2:
        request_mode = "comparison"
    else:
        request_mode = "unsupported_scope"

    return {
        "project": TRACE_PROJECT,
        "component": TRACE_COMPONENT,
        "environment": environment.strip(),
        "request_mode": request_mode,
        "symbols": ",".join(symbols),
    }


def run_traced_supervisor_research_graph(
    *,
    request_text: str,
    requested_symbols: Sequence[str],
    market_worker: MarketWorker,
    company_worker: CompanyWorker,
    report_synthesizer: ReportSynthesizer,
    tracing_config: MlflowTracingConfig,
    equities: Mapping[str, Equity] | None = None,
) -> SupervisorResearchResult:
    """Run the existing research graph inside an MLflow tracing context."""

    if not isinstance(tracing_config, MlflowTracingConfig):
        raise TypeError(
            "tracing_config must be MlflowTracingConfig."
        )

    configure_mlflow_tracing(
        tracing_config
    )

    tags = research_trace_tags(
        requested_symbols=requested_symbols,
        environment=tracing_config.environment,
    )
    metadata = {
        "privacy_boundary": TRACE_PRIVACY_BOUNDARY,
        "structured_authority": "gold_metrics",
        "narrative_authority": "validated_rag_worker_findings",
    }

    with mlflow.tracing.context(
        tags=tags,
        metadata=metadata,
    ):
        return run_supervisor_research_graph(
            request_text=request_text,
            requested_symbols=requested_symbols,
            market_worker=market_worker,
            company_worker=company_worker,
            report_synthesizer=report_synthesizer,
            equities=equities,
        )


def _normalized_symbol(
    value: Any,
) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(
            "requested symbols must be nonblank strings."
        )

    return value.strip().upper()
