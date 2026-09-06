"""Live smoke test for validated Market Analyst and Company Researcher workers."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from equity_research.config import load_equities  # noqa: E402
from equity_research.databricks_cli_runtime import (  # noqa: E402
    execute_statement_via_cli,
    query_vector_index_via_cli,
)
from equity_research.retrieval_tools import (  # noqa: E402
    build_retrieval_query_payload,
    parse_retrieval_response,
)
from equity_research.structured_data_access import (  # noqa: E402
    build_fundamental_metrics_sql_request,
    build_market_metrics_sql_request,
    parse_fundamental_metrics_statement_response,
    parse_market_metrics_statement_response,
)
from equity_research.structured_data_tools import (  # noqa: E402
    prepare_fundamental_metrics_results,
    prepare_market_metrics_results,
)
from equity_research.worker_agent_runtime import (  # noqa: E402
    run_company_researcher,
    run_market_analyst,
)


DEFAULT_CATALOG = "workspace"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Live-verify GPT OSS 20B worker agents over controlled Gold "
            "and HYBRID retrieval inputs without printing provider text."
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
        "--symbol",
        default="AAPL",
        help="One configured project symbol for the first worker smoke test.",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()
    equities = load_equities()
    symbol = args.symbol.strip().upper()
    requested_symbols = (symbol,)
    now_utc = datetime.now(timezone.utc)

    market_payload = build_market_metrics_sql_request(
        warehouse_id=args.warehouse_id,
        catalog=args.catalog,
        gold_schema=args.gold_schema,
        requested_symbols=requested_symbols,
        equities=equities,
    )
    market_response = execute_statement_via_cli(
        payload=market_payload,
        profile=args.profile,
    )
    market_metrics = parse_market_metrics_statement_response(
        market_response
    )
    market_results = prepare_market_metrics_results(
        metrics=market_metrics,
        requested_symbols=requested_symbols,
        now_utc=now_utc,
        equities=equities,
    )

    fundamental_payload = build_fundamental_metrics_sql_request(
        warehouse_id=args.warehouse_id,
        catalog=args.catalog,
        gold_schema=args.gold_schema,
        requested_symbols=requested_symbols,
        equities=equities,
    )
    fundamental_response = execute_statement_via_cli(
        payload=fundamental_payload,
        profile=args.profile,
    )
    fundamental_metrics = (
        parse_fundamental_metrics_statement_response(
            fundamental_response
        )
    )
    fundamental_results = prepare_fundamental_metrics_results(
        metrics=fundamental_metrics,
        requested_symbols=requested_symbols,
        now_utc=now_utc,
        equities=equities,
    )

    news_payload = build_retrieval_query_payload(
        query_text="important recent company developments",
        requested_symbols=requested_symbols,
        source_type="news",
        num_results=3,
        equities=equities,
    )
    news_response = query_vector_index_via_cli(
        index_name=args.index_name,
        payload=news_payload,
        profile=args.profile,
    )
    news_evidence = parse_retrieval_response(
        news_response,
        requested_symbols=requested_symbols,
        expected_source_type="news",
        equities=equities,
    )

    filing_payload = build_retrieval_query_payload(
        query_text="principal business and operating risks",
        requested_symbols=requested_symbols,
        source_type="filing",
        section_code="item_1a",
        num_results=3,
        equities=equities,
    )
    filing_response = query_vector_index_via_cli(
        index_name=args.index_name,
        payload=filing_payload,
        profile=args.profile,
    )
    filing_evidence = parse_retrieval_response(
        filing_response,
        requested_symbols=requested_symbols,
        expected_source_type="filing",
        equities=equities,
    )

    if not news_evidence:
        raise RuntimeError(
            "Controlled news retrieval returned no evidence."
        )

    if not filing_evidence:
        raise RuntimeError(
            "Controlled filing retrieval returned no evidence."
        )

    market_agent = run_market_analyst(
        requested_symbols=requested_symbols,
        market_results=market_results,
        fundamental_results=fundamental_results,
        profile=args.profile,
        equities=equities,
    )

    developments_agent = run_company_researcher(
        topic="recent_developments",
        requested_symbols=requested_symbols,
        evidence=news_evidence,
        profile=args.profile,
        equities=equities,
    )

    risks_agent = run_company_researcher(
        topic="principal_risks",
        requested_symbols=requested_symbols,
        evidence=filing_evidence,
        profile=args.profile,
        equities=equities,
    )

    print("WORKER_AGENT_SMOKE=PASSED")
    print(
        "MARKET_ANALYST"
        f"; symbol={symbol}"
        f"; findings={len(market_agent.findings)}"
        f"; limitations={len(market_agent.limitations)}"
    )

    for finding in market_agent.findings:
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
            f"; statement={finding.statement}"
        )

    for limitation in market_agent.limitations:
        print(
            "MARKET_LIMITATION"
            f"; symbol={limitation.symbol}"
            f"; dimension={limitation.dimension}"
            f"; reason={limitation.reason_code}"
            f"; message={limitation.message}"
        )

    print(
        "RECENT_DEVELOPMENTS"
        f"; symbol={symbol}"
        f"; findings={len(developments_agent.findings)}"
        f"; limitations={len(developments_agent.limitations)}"
    )

    _print_research_findings(
        prefix="DEVELOPMENT_FINDING",
        result=developments_agent,
    )

    print(
        "PRINCIPAL_RISKS"
        f"; symbol={symbol}"
        f"; findings={len(risks_agent.findings)}"
        f"; limitations={len(risks_agent.limitations)}"
    )

    _print_research_findings(
        prefix="RISK_FINDING",
        result=risks_agent,
    )


def _print_research_findings(
    *,
    prefix: str,
    result,
) -> None:
    for finding in result.findings:
        print(
            prefix
            f"; id={finding.finding_id}"
            f"; characterization={finding.characterization}"
            f"; symbols={','.join(finding.symbols)}"
            f"; evidence_ids={','.join(finding.evidence_ids)}"
            f"; statement={finding.statement}"
        )

    for limitation in result.limitations:
        print(
            f"{prefix}_LIMITATION"
            f"; reason={limitation.reason_code}"
            f"; message={limitation.message}"
        )


if __name__ == "__main__":
    main()
