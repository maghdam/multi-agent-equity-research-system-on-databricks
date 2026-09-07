"""Databricks Apps-native authenticated transport and runtime configuration."""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from typing import Any

from databricks.sdk import WorkspaceClient

from equity_research.app_contracts import AppResearchSelection
from equity_research.app_market_history import (
    build_price_history_sql_request,
    prepare_market_history_series,
    unavailable_market_history_series,
)
from equity_research.app_service import AppStructuredSnapshot
from equity_research.company_researcher import (
    CompanyResearcherResult,
    ResearchTopic,
)
from equity_research.config import Equity, load_equities
from equity_research.databricks_cli_runtime import (
    RUNNING_SQL_STATES,
    TERMINAL_SQL_STATES,
    ControlledToolExecutionError,
)
from equity_research.market_analyst import MarketAnalystResult
from equity_research.mlflow_tracing import (
    MlflowTracingConfig,
    run_traced_supervisor_research_graph,
)
from equity_research.supervisor_report_runtime import (
    run_supervisor_report_synthesis,
)
from equity_research.supervisor_research_graph import (
    SupervisorResearchResult,
    run_supervisor_research_graph,
)
from equity_research.supervisor_worker_runtime import (
    DatabricksSupervisorWorkers,
    SupervisorWorkerRuntimeConfig,
)
from equity_research.worker_agent_runtime import (
    run_company_researcher,
    run_market_analyst,
)
from equity_research.structured_data_tools import ControlledToolDataError


WAREHOUSE_ENV = "EQUITY_RESEARCH_WAREHOUSE_ID"
MARKET_METRICS_TABLE_ENV = "EQUITY_RESEARCH_MARKET_METRICS_TABLE"
FUNDAMENTAL_METRICS_TABLE_ENV = "EQUITY_RESEARCH_FUNDAMENTAL_METRICS_TABLE"
DAILY_PRICES_TABLE_ENV = "EQUITY_RESEARCH_DAILY_PRICES_TABLE"
VECTOR_INDEX_ENV = "EQUITY_RESEARCH_VECTOR_SEARCH_INDEX"
GOLD_SCHEMA_ENV = "EQUITY_RESEARCH_GOLD_SCHEMA"
CATALOG_ENV = "EQUITY_RESEARCH_CATALOG"
MLFLOW_EXPERIMENT_ENV = "EQUITY_RESEARCH_MLFLOW_EXPERIMENT"

DEFAULT_CATALOG = "workspace"
DEFAULT_SQL_MAX_POLLS = 12
DEFAULT_SQL_POLL_INTERVAL_SECONDS = 1.0

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DatabricksAppRuntimeConfig:
    """Environment-resolved physical resources for the deployed app."""

    warehouse_id: str
    gold_schema: str
    index_name: str
    catalog: str = DEFAULT_CATALOG
    daily_prices_table: str | None = None
    mlflow_experiment: str | None = None

    def __post_init__(self) -> None:
        for name in (
            "warehouse_id",
            "gold_schema",
            "index_name",
            "catalog",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(
                    f"{name} must be a nonblank string."
                )

        if self.daily_prices_table is not None and (
            not isinstance(self.daily_prices_table, str)
            or not self.daily_prices_table.strip()
        ):
            raise ValueError(
                "daily_prices_table must be None or a nonblank string."
            )

        if self.mlflow_experiment is not None and (
            not isinstance(self.mlflow_experiment, str)
            or not self.mlflow_experiment.strip()
        ):
            raise ValueError(
                "mlflow_experiment must be None or a nonblank string."
            )

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str] | None = None,
    ) -> "DatabricksAppRuntimeConfig":
        """Resolve app resources without embedding environment-specific IDs."""

        values = os.environ if environment is None else environment

        catalog, gold_schema = _resolve_gold_location(
            values
        )

        return cls(
            warehouse_id=_required_environment_value(
                values,
                WAREHOUSE_ENV,
            ),
            gold_schema=gold_schema,
            index_name=_required_environment_value(
                values,
                VECTOR_INDEX_ENV,
            ),
            catalog=catalog,
            daily_prices_table=_optional_environment_value(
                values,
                DAILY_PRICES_TABLE_ENV,
                None,
            ),
            mlflow_experiment=_optional_environment_value(
                values,
                MLFLOW_EXPERIMENT_ENV,
                None,
            ),
        )


class DatabricksAppTransport:
    """Authenticated REST transport using Databricks unified authentication."""

    def __init__(
        self,
        *,
        workspace_client: WorkspaceClient | None = None,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if not callable(sleeper):
            raise TypeError(
                "sleeper must be callable."
            )

        self._workspace = (
            WorkspaceClient()
            if workspace_client is None
            else workspace_client
        )
        self._sleeper = sleeper

    def execute_statement(
        self,
        *,
        payload: Mapping[str, Any],
        profile: str | None = None,
        max_polls: int = DEFAULT_SQL_MAX_POLLS,
        poll_interval_seconds: float = (
            DEFAULT_SQL_POLL_INTERVAL_SECONDS
        ),
    ) -> dict[str, Any]:
        """Execute one Statement Execution request through app OAuth."""

        _require_no_profile(profile)
        _validate_poll_settings(
            max_polls=max_polls,
            poll_interval_seconds=poll_interval_seconds,
        )

        response = self._request_json(
            method="POST",
            path="/api/2.0/sql/statements",
            body=payload,
        )

        for poll_number in range(max_polls + 1):
            state = _statement_state(response)

            if state == "SUCCEEDED":
                return response

            if state in TERMINAL_SQL_STATES:
                raise ControlledToolExecutionError(
                    "Statement Execution failed in Databricks App runtime: "
                    f"state={state}."
                )

            if state not in RUNNING_SQL_STATES:
                raise ControlledToolExecutionError(
                    "Statement Execution returned an unknown state: "
                    f"{state!r}."
                )

            if poll_number == max_polls:
                break

            statement_id = _required_text(
                response.get("statement_id"),
                "statement_id",
            )
            self._sleeper(
                poll_interval_seconds
            )
            response = self._request_json(
                method="GET",
                path=(
                    "/api/2.0/sql/statements/"
                    f"{statement_id}"
                ),
            )

        raise ControlledToolExecutionError(
            "Statement Execution did not reach a terminal state "
            f"after {max_polls} poll(s)."
        )

    def query_vector_index(
        self,
        *,
        index_name: str,
        payload: Mapping[str, Any],
        profile: str | None = None,
    ) -> dict[str, Any]:
        """Query the configured AI Search index with app authorization."""

        _require_no_profile(profile)
        normalized_index = _required_text(
            index_name,
            "index_name",
        )

        return self._request_json(
            method="POST",
            path=(
                "/api/2.0/vector-search/indexes/"
                f"{normalized_index}/query"
            ),
            body=payload,
        )

    def query_chat_completions(
        self,
        *,
        payload: Mapping[str, Any],
        profile: str | None = None,
    ) -> dict[str, Any]:
        """Query Databricks chat models with app authorization."""

        _require_no_profile(profile)

        if not isinstance(payload, Mapping):
            raise ControlledToolExecutionError(
                "chat payload must be a mapping."
            )

        if payload.get("stream") is not False:
            raise ControlledToolExecutionError(
                "Controlled app chat requests must set stream=false."
            )

        return self._request_json(
            method="POST",
            path="/ai-gateway/mlflow/v1/chat/completions",
            body=payload,
        )

    def _request_json(
        self,
        *,
        method: str,
        path: str,
        body: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            response = self._workspace.api_client.do(
                method=method,
                path=path,
                body=(
                    dict(body)
                    if body is not None
                    else None
                ),
            )
        except Exception as exc:
            raise ControlledToolExecutionError(
                "Databricks App authenticated request failed."
            ) from exc

        if not isinstance(response, Mapping):
            raise ControlledToolExecutionError(
                "Databricks App request did not return a JSON object."
            )

        return dict(response)


class DatabricksAppResearchRuntime:
    """Run the existing research graph through Databricks Apps auth."""

    def __init__(
        self,
        *,
        config: DatabricksAppRuntimeConfig,
        transport: DatabricksAppTransport | None = None,
        equities: Mapping[str, Equity] | None = None,
    ) -> None:
        if not isinstance(
            config,
            DatabricksAppRuntimeConfig,
        ):
            raise TypeError(
                "config must be DatabricksAppRuntimeConfig."
            )

        self._config = config
        self._transport = (
            DatabricksAppTransport()
            if transport is None
            else transport
        )
        self._equities = (
            dict(load_equities())
            if equities is None
            else dict(equities)
        )

    def run_research(
        self,
        *,
        selection: AppResearchSelection,
        request_text: str,
    ) -> tuple[AppStructuredSnapshot, SupervisorResearchResult]:
        """Run one request without cross-session mutable runtime state."""

        if not isinstance(
            selection,
            AppResearchSelection,
        ):
            raise TypeError(
                "selection must be AppResearchSelection."
            )

        if not isinstance(request_text, str) or not request_text.strip():
            raise ValueError(
                "request_text must be a nonblank string."
            )

        structured_snapshot: AppStructuredSnapshot | None = None

        def market_agent_runner(
            *,
            requested_symbols,
            market_results,
            fundamental_results,
            profile=None,
            equities=None,
        ) -> MarketAnalystResult:
            nonlocal structured_snapshot

            _require_no_profile(profile)
            structured_snapshot = AppStructuredSnapshot(
                market_results=tuple(
                    market_results
                ),
                fundamental_results=tuple(
                    fundamental_results
                ),
            )

            return run_market_analyst(
                requested_symbols=requested_symbols,
                market_results=market_results,
                fundamental_results=fundamental_results,
                profile=None,
                equities=equities,
                model_query=self._transport.query_chat_completions,
            )

        def company_agent_runner(
            *,
            topic: ResearchTopic,
            requested_symbols,
            evidence,
            profile=None,
            equities=None,
        ) -> CompanyResearcherResult:
            _require_no_profile(profile)

            return run_company_researcher(
                topic=topic,
                requested_symbols=requested_symbols,
                evidence=evidence,
                profile=None,
                equities=equities,
                model_query=self._transport.query_chat_completions,
            )

        worker_config = SupervisorWorkerRuntimeConfig(
            warehouse_id=self._config.warehouse_id,
            gold_schema=self._config.gold_schema,
            index_name=self._config.index_name,
            profile=None,
            catalog=self._config.catalog,
        )
        workers = DatabricksSupervisorWorkers(
            config=worker_config,
            equities=self._equities,
            statement_executor=self._transport.execute_statement,
            vector_query=self._transport.query_vector_index,
            market_agent_runner=market_agent_runner,
            company_agent_runner=company_agent_runner,
        )

        def report_synthesizer(
            *,
            state,
        ):
            return run_supervisor_report_synthesis(
                state=state,
                profile=None,
                model_query=self._transport.query_chat_completions,
            )

        if self._config.mlflow_experiment is not None:
            tracing_config = MlflowTracingConfig(
                experiment_name=self._config.mlflow_experiment,
                profile=None,
                environment="databricks_app",
            )
            result = run_traced_supervisor_research_graph(
                request_text=request_text.strip(),
                requested_symbols=selection.requested_symbols,
                market_worker=workers.market_worker,
                company_worker=workers.company_worker,
                report_synthesizer=report_synthesizer,
                tracing_config=tracing_config,
                equities=self._equities,
            )
        else:
            result = run_supervisor_research_graph(
                request_text=request_text.strip(),
                requested_symbols=selection.requested_symbols,
                market_worker=workers.market_worker,
                company_worker=workers.company_worker,
                report_synthesizer=report_synthesizer,
                equities=self._equities,
            )

        if structured_snapshot is None:
            raise RuntimeError(
                "Market Analyst path did not capture structured app data."
            )

        market_history = self._load_market_history(
            selection=selection,
            market_results=structured_snapshot.market_results,
        )
        structured_snapshot = replace(
            structured_snapshot,
            market_history=market_history,
        )

        return (
            structured_snapshot,
            result,
        )

    def _load_market_history(
        self,
        *,
        selection: AppResearchSelection,
        market_results,
    ):
        if self._config.daily_prices_table is None:
            return unavailable_market_history_series(
                requested_symbols=selection.requested_symbols,
                limitation=(
                    "Price-history resource is not configured for this app."
                ),
                equities=self._equities,
            )

        if any(
            result.status != "ready" or result.metric is None
            for result in market_results
        ):
            return unavailable_market_history_series(
                requested_symbols=selection.requested_symbols,
                limitation=(
                    "Price history is unavailable because the controlled Gold "
                    "market snapshot is not ready for every selected company."
                ),
                equities=self._equities,
            )

        try:
            payload = build_price_history_sql_request(
                warehouse_id=self._config.warehouse_id,
                table_full_name=self._config.daily_prices_table,
                requested_symbols=selection.requested_symbols,
                market_window_sessions=selection.market_window_sessions,
                equities=self._equities,
            )
            response = self._transport.execute_statement(
                payload=payload,
                profile=None,
            )
            return prepare_market_history_series(
                response=response,
                requested_symbols=selection.requested_symbols,
                market_window_sessions=selection.market_window_sessions,
                market_results=market_results,
                equities=self._equities,
            )
        except ControlledToolDataError as exc:
            logger.warning(
                (
                    "App price-history chart unavailable: symbols=%s "
                    "window=%s error_type=%s"
                ),
                ",".join(selection.requested_symbols),
                selection.market_window_sessions,
                type(exc).__name__,
            )
            return unavailable_market_history_series(
                requested_symbols=selection.requested_symbols,
                limitation=(
                    "Validated price history is unavailable for the selected "
                    "window."
                ),
                equities=self._equities,
            )


def _resolve_gold_location(
    environment: Mapping[str, str],
) -> tuple[str, str]:
    market_table = environment.get(
        MARKET_METRICS_TABLE_ENV
    )
    fundamental_table = environment.get(
        FUNDAMENTAL_METRICS_TABLE_ENV
    )

    if market_table is None and fundamental_table is None:
        return (
            _optional_environment_value(
                environment,
                CATALOG_ENV,
                DEFAULT_CATALOG,
            ),
            _required_environment_value(
                environment,
                GOLD_SCHEMA_ENV,
            ),
        )

    market_parts = _bound_table_parts(
        market_table,
        environment_name=MARKET_METRICS_TABLE_ENV,
        expected_table="market_metrics",
    )
    fundamental_parts = _bound_table_parts(
        fundamental_table,
        environment_name=FUNDAMENTAL_METRICS_TABLE_ENV,
        expected_table="fundamental_metrics",
    )

    if market_parts[:2] != fundamental_parts[:2]:
        raise ValueError(
            "Bound market_metrics and fundamental_metrics tables "
            "must share the same catalog and schema."
        )

    return (
        market_parts[0],
        market_parts[1],
    )


def _bound_table_parts(
    value: object,
    *,
    environment_name: str,
    expected_table: str,
) -> tuple[str, str, str]:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(
            f"Missing required Databricks App environment value: "
            f"{environment_name}."
        )

    parts = tuple(
        part.strip()
        for part in value.split(".")
    )

    if (
        len(parts) != 3
        or any(not part for part in parts)
        or parts[2] != expected_table
    ):
        raise ValueError(
            f"{environment_name} must be a three-level table name ending "
            f"in {expected_table!r}."
        )

    return parts


def _required_environment_value(
    environment: Mapping[str, str],
    name: str,
) -> str:
    value = environment.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(
            f"Missing required Databricks App environment value: {name}."
        )
    return value.strip()


def _optional_environment_value(
    environment: Mapping[str, str],
    name: str,
    default: str | None,
) -> str | None:
    value = environment.get(name)

    if value is None:
        return default

    if not isinstance(value, str) or not value.strip():
        raise ValueError(
            f"Databricks App environment value {name} must be nonblank."
        )

    return value.strip()


def _require_no_profile(
    profile: str | None,
) -> None:
    if profile is not None:
        raise ControlledToolExecutionError(
            "Databricks App runtime must use unified authentication, "
            "not a Databricks CLI profile."
        )


def _validate_poll_settings(
    *,
    max_polls: int,
    poll_interval_seconds: float,
) -> None:
    if (
        isinstance(max_polls, bool)
        or not isinstance(max_polls, int)
        or max_polls < 0
    ):
        raise ControlledToolExecutionError(
            "max_polls must be a nonnegative integer."
        )

    if poll_interval_seconds < 0:
        raise ControlledToolExecutionError(
            "poll_interval_seconds must be nonnegative."
        )


def _statement_state(
    response: Mapping[str, Any],
) -> str:
    status = response.get("status")
    if not isinstance(status, Mapping):
        raise ControlledToolExecutionError(
            "Statement Execution response is missing status."
        )

    state = status.get("state")
    if not isinstance(state, str) or not state.strip():
        raise ControlledToolExecutionError(
            "Statement Execution response is missing status.state."
        )

    return state.strip().upper()


def _required_text(
    value: object,
    name: str,
) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ControlledToolExecutionError(
            f"{name} must be a nonblank string."
        )

    return value.strip()
