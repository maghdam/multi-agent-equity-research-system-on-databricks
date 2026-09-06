"""Live Databricks-backed worker adapters for the Supervisor graph."""

from __future__ import annotations

import re
from contextlib import nullcontext
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any

import mlflow
from mlflow.entities import SpanType

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
from equity_research.mlflow_runtime_spans import (
    optional_mlflow_span,
)
from equity_research.retrieval_tools import (
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
DEFAULT_RETRIEVAL_RESULTS_PER_SYMBOL = 5

RECENT_DEVELOPMENT_NOISE_PATTERNS = (
    re.compile(r"\brule\s+10b5-1\b", re.IGNORECASE),
    re.compile(r"\b13f\b", re.IGNORECASE),
    re.compile(r"\binstitutional\s+holdings?\b", re.IGNORECASE),
    re.compile(r"\bgolden\s+cross\b", re.IGNORECASE),
    re.compile(r"\bmoving\s+averages?\b", re.IGNORECASE),
    re.compile(r"\btechnical[-\s]+analysis\b", re.IGNORECASE),
    re.compile(r"\bprice\s+targets?\b", re.IGNORECASE),
    re.compile(r"\banalyst\s+ratings?\b", re.IGNORECASE),
    re.compile(
        r"\binsider\b.{0,40}\b(sale|sold|purchase|bought)\b",
        re.IGNORECASE,
    ),
)


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

        with optional_mlflow_span(
            name="gold_market_metrics_access",
            span_type=SpanType.TOOL,
        ) as market_span:
            if market_span is not None:
                market_span.set_inputs(
                    {
                        "dataset": "market_metrics",
                        "symbols": list(
                            request.requested_symbols
                        ),
                    }
                )
                market_span.set_attributes(
                    {
                        "equity_research.authority": "gold",
                        "equity_research.dataset": "market_metrics",
                    }
                )

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

            if market_span is not None:
                market_span.set_outputs(
                    _gold_tool_result_summary(
                        market_results
                    )
                )

        with optional_mlflow_span(
            name="gold_fundamental_metrics_access",
            span_type=SpanType.TOOL,
        ) as fundamental_span:
            if fundamental_span is not None:
                fundamental_span.set_inputs(
                    {
                        "dataset": "fundamental_metrics",
                        "symbols": list(
                            request.requested_symbols
                        ),
                    }
                )
                fundamental_span.set_attributes(
                    {
                        "equity_research.authority": "gold",
                        "equity_research.dataset": "fundamental_metrics",
                    }
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

            if fundamental_span is not None:
                fundamental_span.set_outputs(
                    _gold_tool_result_summary(
                        fundamental_results
                    )
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
            query_text = _company_retrieval_query_text(
                request=request,
                symbol=symbol,
                topic=topic,
                query_focus=query_focus,
                equities=self._equities,
            )
            retrieval_candidate_limit = (
                min(
                    MAX_RETRIEVAL_RESULTS,
                    self._config.retrieval_results_per_symbol * 2,
                )
                if (
                    request.mode == "comparison"
                    and topic == "recent_developments"
                )
                else self._config.retrieval_results_per_symbol
            )
            payload = build_retrieval_query_payload(
                query_text=query_text,
                requested_symbols=(symbol,),
                source_type=source_type,
                section_code=section_code,
                num_results=retrieval_candidate_limit,
                equities=self._equities,
            )
            active_span = mlflow.get_current_active_span()
            span_context = (
                mlflow.start_span(
                    name=(
                        "company_researcher_retrieval_"
                        f"{topic}_{symbol.lower()}"
                    ),
                    span_type=SpanType.RETRIEVER,
                )
                if active_span is not None
                else nullcontext(
                    None
                )
            )

            with span_context as retrieval_span:
                if retrieval_span is not None:
                    retrieval_span.set_inputs(
                        {
                            "query": payload["query_text"],
                            "symbol": symbol,
                            "topic": topic,
                            "source_type": source_type,
                            "section_code": section_code,
                            "num_results": retrieval_candidate_limit,
                            "worker_evidence_limit": (
                                self._config.retrieval_results_per_symbol
                            ),
                        }
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

                if topic == "recent_developments":
                    symbol_evidence = _filter_recent_development_evidence(
                        symbol_evidence
                    )

                symbol_evidence = symbol_evidence[
                    : self._config.retrieval_results_per_symbol
                ]

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

                if retrieval_span is not None:
                    retrieval_span.set_attributes(
                        {
                            "equity_research.symbol": symbol,
                            "equity_research.topic": topic,
                            "equity_research.source_type": source_type,
                            "equity_research.filtered_evidence_count": len(
                                ranked_evidence
                            ),
                        }
                    )
                    retrieval_span.set_outputs(
                        _mlflow_retriever_documents(
                            ranked_evidence
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


def _company_retrieval_query_text(
    *,
    request: SupervisorRequest,
    symbol: str,
    topic: ResearchTopic,
    query_focus: str,
    equities: Mapping[str, Equity],
) -> str:
    """Build a symbol-specific semantic query without cross-company contamination."""

    if request.mode == "single_company":
        return (
            f"{request.request_text}\n"
            f"Research focus: {query_focus}"
        )

    equity = equities[symbol]

    if topic == "recent_developments":
        return (
            "What important recent business developments at "
            f"{equity.display_name} ({symbol}) could matter to an equity "
            "researcher? Focus on products, operations, strategy, corporate "
            "actions, and material legal or regulatory events."
        )

    return (
        "What principal business and operating risks has "
        f"{equity.display_name} ({symbol}) disclosed in SEC Risk Factors?"
    )


def _gold_tool_result_summary(
    results: Sequence,
) -> dict[str, Any]:
    """Return Gold readiness/provenance summary without duplicating metric values."""

    return {
        "result_count": len(
            results
        ),
        "ready_symbols": [
            result.symbol
            for result in results
            if result.status == "ready"
        ],
        "unavailable": [
            {
                "symbol": result.symbol,
                "reason_code": result.reason_code,
            }
            for result in results
            if result.status != "ready"
        ],
        "as_of_dates": {
            result.symbol: (
                result.metric.as_of_date.isoformat()
                if result.metric is not None
                else None
            )
            for result in results
        },
    }


def _mlflow_retriever_documents(
    evidence: Sequence,
) -> list[dict[str, Any]]:
    """Render validated RAG evidence using MLflow's RETRIEVER span schema."""

    return [
        {
            "id": item.evidence_id,
            "page_content": item.text,
            "metadata": {
                "doc_uri": item.source_url,
                "chunk_id": item.chunk_id,
                "document_id": item.document_id,
                "document_version_id": item.document_version_id,
                "source_type": item.source_type,
                "configured_symbols": list(
                    item.configured_symbols
                ),
                "evidence_date": item.evidence_date.isoformat(),
                "retrieval_rank": item.retrieval_rank,
            },
        }
        for item in evidence
    ]


def _filter_recent_development_evidence(
    evidence,
):
    filtered = []

    for item in evidence:
        searchable_text = (
            f"{item.title}\n{item.text}"
        )

        if any(
            pattern.search(searchable_text)
            for pattern in RECENT_DEVELOPMENT_NOISE_PATTERNS
        ):
            continue

        filtered.append(
            item
        )

    return tuple(filtered)


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
