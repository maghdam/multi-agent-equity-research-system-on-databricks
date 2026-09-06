"""Live end-to-end smoke runner for the LangGraph Supervisor worker layer."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from equity_research.company_researcher import (  # noqa: E402
    CompanyResearcherResult,
)
from equity_research.config import load_equities  # noqa: E402
from equity_research.market_analyst import MarketAnalystResult  # noqa: E402
from equity_research.supervisor_graph import run_supervisor_graph  # noqa: E402
from equity_research.supervisor_worker_runtime import (  # noqa: E402
    DatabricksSupervisorWorkers,
    SupervisorWorkerRuntimeConfig,
)


DEFAULT_CATALOG = "workspace"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Live-verify the Supervisor LangGraph over controlled Databricks "
            "Gold/retrieval inputs and GPT OSS 20B workers without printing "
            "provider source text."
        )
    )

    parser.add_argument(
        "--warehouse-id",
        required=True,
        help="Databricks SQL warehouse ID.",
    )
    parser.add_argument(
        "--profile",
        default=None,
        help="Optional Databricks CLI profile.",
    )
    parser.add_argument(
        "--catalog",
        default=DEFAULT_CATALOG,
        help="Databricks catalog containing the physical Gold schema.",
    )
    parser.add_argument(
        "--gold-schema",
        required=True,
        help="Physical Gold schema name in the target workspace.",
    )
    parser.add_argument(
        "--index-name",
        required=True,
        help="Fully qualified physical Vector Search index name.",
    )
    parser.add_argument(
        "--symbols",
        nargs="+",
        required=True,
        help="One or two configured project symbols.",
    )
    parser.add_argument(
        "--request",
        default=None,
        help=(
            "Optional research request text. A safe default is generated "
            "from --symbols when omitted."
        ),
    )
    parser.add_argument(
        "--retrieval-results-per-symbol",
        type=int,
        default=3,
        help="Controlled HYBRID results retrieved independently per symbol/topic.",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()
    symbols = tuple(
        symbol.strip().upper()
        for symbol in args.symbols
    )
    request_text = (
        args.request.strip()
        if isinstance(args.request, str) and args.request.strip()
        else _default_request(symbols)
    )

    config = SupervisorWorkerRuntimeConfig(
        warehouse_id=args.warehouse_id,
        gold_schema=args.gold_schema,
        index_name=args.index_name,
        profile=args.profile,
        catalog=args.catalog,
        retrieval_results_per_symbol=args.retrieval_results_per_symbol,
    )
    workers = DatabricksSupervisorWorkers(
        config=config,
        equities=load_equities(),
    )

    state = run_supervisor_graph(
        request_text=request_text,
        requested_symbols=symbols,
        market_worker=workers.market_worker,
        company_worker=workers.company_worker,
        equities=load_equities(),
    )

    print("SUPERVISOR_GRAPH_SMOKE=PASSED")
    print(
        "SUPERVISOR_STATE"
        f"; mode={state.request.mode}"
        f"; symbols={','.join(state.request.requested_symbols)}"
        f"; status={state.status}"
        f"; limitations={len(state.limitations)}"
        f"; failures={len(state.failures)}"
    )

    for outcome in state.outcomes:
        result = outcome.result

        print(
            "ROUTE"
            f"; id={outcome.route_id}"
            f"; status={outcome.status}"
            f"; result_type={type(result).__name__ if result is not None else None}"
        )

        if isinstance(result, MarketAnalystResult):
            _print_market_result(result)
        elif isinstance(result, CompanyResearcherResult):
            _print_company_result(
                route_id=outcome.route_id,
                result=result,
            )

    for limitation in state.limitations:
        print(
            "LIMITATION"
            f"; agent={limitation.agent}"
            f"; symbol={limitation.symbol}"
            f"; dimension={limitation.dimension}"
            f"; reason={limitation.reason_code}"
            f"; message={limitation.message}"
        )

    for failure in state.failures:
        print(
            "FAILURE"
            f"; route={failure.route_id}"
            f"; reason={failure.reason_code}"
            f"; message={failure.message}"
        )


def _print_market_result(
    result: MarketAnalystResult,
) -> None:
    print(
        "MARKET_ANALYST_RESULT"
        f"; findings={len(result.findings)}"
        f"; limitations={len(result.limitations)}"
    )

    for finding in result.findings:
        references = ",".join(
            (
                f"{reference.dataset}:"
                f"{reference.symbol}:"
                f"{reference.as_of_date}:"
                f"{'|'.join(reference.fields)}"
            )
            for reference in finding.metric_references
        )
        print(
            "MARKET_FINDING"
            f"; id={finding.finding_id}"
            f"; dimension={finding.dimension}"
            f"; symbols={','.join(finding.symbols)}"
            f"; refs={references}"
        )


def _print_company_result(
    *,
    route_id: str,
    result: CompanyResearcherResult,
) -> None:
    print(
        "COMPANY_RESEARCHER_RESULT"
        f"; route={route_id}"
        f"; findings={len(result.findings)}"
        f"; limitations={len(result.limitations)}"
    )

    for finding in result.findings:
        print(
            "RESEARCH_FINDING"
            f"; id={finding.finding_id}"
            f"; topic={finding.topic}"
            f"; characterization={finding.characterization}"
            f"; symbols={','.join(finding.symbols)}"
            f"; evidence_ids={','.join(finding.evidence_ids)}"
        )


def _default_request(
    symbols: tuple[str, ...],
) -> str:
    if len(symbols) == 1:
        return (
            f"Research {symbols[0]}. Summarize recent market and financial "
            "performance, important recent developments, and principal risks."
        )

    if len(symbols) == 2:
        return (
            f"Compare {symbols[0]} and {symbols[1]}. Summarize recent market "
            "and financial performance, important recent developments, and "
            "principal risks for both companies."
        )

    return "Research the requested configured companies."


if __name__ == "__main__":
    main()
