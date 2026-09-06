"""Live Databricks-backed worker adapters for the Supervisor graph."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any

from equity_research.company_researcher import (
    CompanyResearcherResult,
    ResearchTopic,
)
from equity_research.config import Equity, load_equities
from equity_research.databricks_cli_runtime import (
    execute_statement_via_cli,
    query_vector_index_via_cli,
)
from equity_research.market_analyst import MarketAnalystResult
from equity_research.retrieval_tools import (
    EvidenceRecord,
    MAX_RETRIEVAL_RESULTS,
    build_retrieval_query_payload,
    parse_retrieval_response,
)
from equity_research.structured_data_access import (
    build_fundamental_metrics_sql_request,
    build_market_metrics_sql_request,
    parse_fundamental_metrics_statement_response,
    parse_market_metrics_statement_response,
)
from equity_research.structured_data_tools import (
    prepare_fundamental_metrics_results,
    prepare_market_metrics_results,
)
from equity_research.supervisor_contracts import SupervisorRequest
from equity_research.worker_agent_runtime import (
    run_company_researcher,
    run_market_analyst,
)


DEFAULT_CATALOG = "workspace"
DEFAULT_RETRIEVAL_RESULTS_PER_SYMBOL = 3


@dataclass(frozen=True)
class SupervisorWorkerRuntimeConfig:
    """Physical Databricks resources used by live Supervisor worker nodes."""

    warehouse_id: str
    gold_schema: str
    index_name: str
    profile: str | None = None
    catalog: str = DEFAULT_CATALOG
    retrieval_results_per_symbol: int = DEFAULT_RETRIEVAL_RESULTS_PER_SYMBOL

    def __post_init__(self) -> None:
        for field_name in (
            "warehouse_id",
            "gold_schema",
            "index_name",
            "catalog",
        ):
            value = getattr(
                self,
                field_name,
            )

            if not isinstance(value, str) or not value.strip():
                raise ValueError(
                    f"{field_name} must be a nonblank string."
                )

        if (
            isinstance(
                self.retrieval_results_per_symbol,
                bool,
            )
            or not isinstance(
                self.retrieval_results_per_symbol,
                int,
            )
            or not 1
            <= self.retrieval_results_per_symbol
            <= MAX_RETRIEVAL_RESULTS
        ):
            raise ValueError(
                "retrieval_results_per_symbol must be an integer between "
                f"1 and {MAX_RETRIEVAL_RESULTS}."
            )

        if self.profile is not None:
            if (
                not isinstance(self.profile, str)
                or not self.profile.strip()
            ):
                raise ValueError(
                    "profile must be a nonblank string or None."
                )


class DatabricksSupervisorWorkers:
    """Concrete controlled-tool + GPT OSS 20B worker dependencies."""

    def __init__(
        self,
        *,
        config: SupervisorWorkerRuntimeConfig,
        equities: Mapping[str, Equity] | None = None,
        statement_executor: Callable[..., Mapping[str, Any]] = (
            execute_statement_via_cli
        ),
        vector_query: Callable[..., Mapping[str, Any]] = (
            query_vector_index_via_cli
        ),
        market_agent_runner: Callable[..., MarketAnalystResult] = (
            run_market_analyst
        ),
        company_agent_runner: Callable[..., CompanyResearcherResult] = (
            run_company_researcher
        ),
        clock: Callable[[], datetime] = (
            lambda: datetime.now(timezone.utc)
        ),
    ) -> None:
        if not isinstance(
            config,
            SupervisorWorkerRuntimeConfig,
        ):
            raise TypeError(
                "config must be SupervisorWorkerRuntimeConfig."
            )

        for name, dependency in (
            ("statement_executor", statement_executor),
            ("vector_query", vector_query),
            ("market_agent_runner", market_agent_runner),
            ("company_agent_runner", company_agent_runner),
            ("clock", clock),
        ):
            if not callable(dependency):
                raise TypeError(
                    f"{name} must be callable."
                )

        self._config = config
        self._equities = (
            dict(load_equities())
            if equities is None
            else dict(equities)
        )
        self._statement_executor = statement_executor
        self._vector_query = vector_query
        self._market_agent_runner = market_agent_runner
        self._company_agent_runner = company_agent_runner
        self._clock = clock

    def market_worker(
        self,
        *,
        request: SupervisorRequest,
    ) -> MarketAnalystResult:
        """Load controlled Gold metrics and run the validated Market Analyst."""

        _require_request(request)
        now_utc = self._clock()

        market_payload = build_market_metrics_sql_request(
            warehouse_id=self._config.warehouse_id,
            catalog=self._config.catalog,
            gold_schema=self._config.gold_schema,
            requested_symbols=request.requested_symbols,
            equities=self._equities,
        )
        market_response = self._statement_executor(
            payload=market_payload,
            profile=self._config.profile,
        )
        market_metrics = parse_market_metrics_statement_response(
            market_response
        )
        market_results = prepare_market_metrics_results(
            metrics=market_metrics,
            requested_symbols=request.requested_symbols,
            now_utc=now_utc,
            equities=self._equities,
        )

        fundamental_payload = build_fundamental_metrics_sql_request(
            warehouse_id=self._config.warehouse_id,
            catalog=self._config.catalog,
            gold_schema=self._config.gold_schema,
            requested_symbols=request.requested_symbols,
            equities=self._equities,
        )
        fundamental_response = self._statement_executor(
            payload=fundamental_payload,
            profile=self._config.profile,
        )
        fundamental_metrics = (
            parse_fundamental_metrics_statement_response(
                fundamental_response
            )
        )
        fundamental_results = prepare_fundamental_metrics_results(
            metrics=fundamental_metrics,
            requested_symbols=request.requested_symbols,
            now_utc=now_utc,
            equities=self._equities,
        )

        return self._market_agent_runner(
            requested_symbols=request.requested_symbols,
            market_results=market_results,
            fundamental_results=fundamental_results,
            profile=self._config.profile,
            equities=self._equities,
        )

    def company_worker(
        self,
        *,
        request: SupervisorRequest,
        topic: ResearchTopic,
    ) -> CompanyResearcherResult:
        """Retrieve scoped evidence per company and run Company Researcher."""

        _require_request(request)

        if topic == "recent_developments":
            source_type = "news"
            section_code = None
            query_focus = (
                "Important recent company developments, especially products, "
                "operations, strategy, corporate actions, and material legal "
                "or regulatory events."
            )
        elif topic == "principal_risks":
            source_type = "filing"
            section_code = "item_1a"
            query_focus = (
                "Principal business and operating risks disclosed by the "
                "company in SEC Risk Factors."
            )
        else:
            raise ValueError(
                "topic must be 'recent_developments' or 'principal_risks'."
            )

        results: list[tuple[str, CompanyResearcherResult]] = []

        for symbol in request.requested_symbols:
            payload = build_retrieval_query_payload(
                query_text=(
                    f"{request.request_text}\n"
                    f"Research focus: {query_focus}"
                ),
                requested_symbols=(symbol,),
                source_type=source_type,
                section_code=section_code,
                num_results=self._config.retrieval_results_per_symbol,
                equities=self._equities,
            )
            response = self._vector_query(
                index_name=self._config.index_name,
                payload=payload,
                profile=self._config.profile,
            )
            symbol_evidence = parse_retrieval_response(
                response,
                requested_symbols=(symbol,),
                expected_source_type=source_type,
                equities=self._equities,
            )

            ranked_evidence = tuple(
                replace(
                    item,
                    retrieval_rank=rank,
                )
                for rank, item in enumerate(
                    symbol_evidence,
                    start=1,
                )
            )
            result = self._company_agent_runner(
                topic=topic,
                requested_symbols=(symbol,),
                evidence=ranked_evidence,
                profile=self._config.profile,
                equities=self._equities,
            )
            results.append(
                (
                    symbol,
                    result,
                )
            )

        return _merge_company_results(
            topic=topic,
            requested_symbols=request.requested_symbols,
            results=results,
        )


def _merge_company_results(
    *,
    topic: ResearchTopic,
    requested_symbols: tuple[str, ...],
    results: list[tuple[str, CompanyResearcherResult]],
) -> CompanyResearcherResult:
    if tuple(
        symbol
        for symbol, _ in results
    ) != requested_symbols:
        raise RuntimeError(
            "Company Researcher per-symbol results do not match request order."
        )

    findings = []
    limitations = []
    comparison = len(requested_symbols) > 1

    for symbol, result in results:
        if not isinstance(
            result,
            CompanyResearcherResult,
        ):
            raise TypeError(
                "company_agent_runner must return CompanyResearcherResult."
            )

        for finding in result.findings:
            if finding.topic != topic:
                raise RuntimeError(
                    "Per-symbol Company Researcher result has wrong topic."
                )

            if finding.symbols != (symbol,):
                raise RuntimeError(
                    "Per-symbol Company Researcher result has wrong symbol scope."
                )

            findings.append(
                replace(
                    finding,
                    finding_id=(
                        f"{symbol}:{finding.finding_id}"
                        if comparison
                        else finding.finding_id
                    ),
                )
            )

        for limitation in result.limitations:
            limitations.append(
                replace(
                    limitation,
                    symbol=(
                        symbol
                        if limitation.symbol is None
                        else limitation.symbol
                    ),
                )
            )

    finding_ids = [
        finding.finding_id
        for finding in findings
    ]

    if len(set(finding_ids)) != len(finding_ids):
        raise RuntimeError(
            "Merged Company Researcher finding IDs must be unique."
        )

    return CompanyResearcherResult(
        findings=tuple(findings),
        limitations=tuple(limitations),
    )


def _require_request(
    request: SupervisorRequest,
) -> None:
    if not isinstance(
        request,
        SupervisorRequest,
    ):
        raise TypeError(
            "request must be SupervisorRequest."
        )
