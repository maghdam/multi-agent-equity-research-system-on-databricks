"""Live smoke test for controlled Gold and HYBRID retrieval tools."""

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


DEFAULT_CATALOG = "workspace"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Live-verify controlled Gold queries and HYBRID retrieval "
            "without printing source text."
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
        help=(
            "Physical Gold schema name in the target workspace. "
            "Development-mode bundles may prefix this name."
        ),
    )
    parser.add_argument(
        "--index-name",
        required=True,
        help=(
            "Fully qualified physical Vector Search index name in the "
            "target workspace."
        ),
    )
    parser.add_argument(
        "--symbols",
        nargs="+",
        default=["AAPL", "MSFT"],
        help="One or two configured project symbols.",
    )
    parser.add_argument(
        "--retrieval-symbol",
        default="AAPL",
        help="Configured symbol used for the retrieval smoke checks.",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()
    equities = load_equities()
    now_utc = datetime.now(timezone.utc)
    requested_symbols = tuple(args.symbols)

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

    retrieval_symbol = args.retrieval_symbol

    news_payload = build_retrieval_query_payload(
        query_text="recent company developments",
        requested_symbols=(retrieval_symbol,),
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
        requested_symbols=(retrieval_symbol,),
        expected_source_type="news",
        equities=equities,
    )

    filing_payload = build_retrieval_query_payload(
        query_text="principal business risks",
        requested_symbols=(retrieval_symbol,),
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
        requested_symbols=(retrieval_symbol,),
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

    print("CONTROLLED_TOOL_SMOKE=PASSED")

    for result in market_results:
        metric = result.metric
        as_of_date = (
            metric.as_of_date
            if metric is not None
            else None
        )
        print(
            "MARKET"
            f"; symbol={result.symbol}"
            f"; status={result.status}"
            f"; reason={result.reason_code}"
            f"; as_of_date={as_of_date}"
        )

    for result in fundamental_results:
        metric = result.metric
        as_of_date = (
            metric.as_of_date
            if metric is not None
            else None
        )
        filing_form = (
            metric.latest_filing_form
            if metric is not None
            else None
        )
        print(
            "FUNDAMENTAL"
            f"; symbol={result.symbol}"
            f"; status={result.status}"
            f"; reason={result.reason_code}"
            f"; as_of_date={as_of_date}"
            f"; filing_form={filing_form}"
        )

    print(
        "NEWS_RETRIEVAL"
        f"; symbol={retrieval_symbol}"
        f"; count={len(news_evidence)}"
        f"; top_evidence_id={news_evidence[0].evidence_id}"
        f"; top_date={news_evidence[0].evidence_date}"
        f"; top_document_id={news_evidence[0].document_id}"
    )

    print(
        "FILING_RETRIEVAL"
        f"; symbol={retrieval_symbol}"
        f"; count={len(filing_evidence)}"
        f"; top_evidence_id={filing_evidence[0].evidence_id}"
        f"; top_date={filing_evidence[0].evidence_date}"
        f"; top_document_id={filing_evidence[0].document_id}"
        f"; top_section={filing_evidence[0].section_code}"
    )


if __name__ == "__main__":
    main()
