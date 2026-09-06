"""Live end-to-end smoke runner for final GPT OSS 120B Supervisor reports."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from equity_research.config import load_equities  # noqa: E402
from equity_research.supervisor_research_graph import (  # noqa: E402
    run_supervisor_research_graph,
)
from equity_research.supervisor_report_runtime import (  # noqa: E402
    run_supervisor_report_synthesis,
)
from equity_research.supervisor_worker_runtime import (  # noqa: E402
    DatabricksSupervisorWorkers,
    SupervisorWorkerRuntimeConfig,
)


DEFAULT_CATALOG = "workspace"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Live-verify the complete controlled research path through "
            "GPT OSS 20B workers, LangGraph aggregation, and GPT OSS 120B "
            "final synthesis without printing raw provider source text."
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
            "Optional research request text. A controlled default is generated "
            "from --symbols when omitted."
        ),
    )
    parser.add_argument(
        "--retrieval-results-per-symbol",
        type=int,
        default=5,
        help="Controlled HYBRID results retrieved independently per symbol/topic.",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()
    equities = load_equities()
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
        equities=equities,
    )

    def report_synthesizer(*, state):
        return run_supervisor_report_synthesis(
            state=state,
            profile=args.profile,
        )

    result = run_supervisor_research_graph(
        request_text=request_text,
        requested_symbols=symbols,
        market_worker=workers.market_worker,
        company_worker=workers.company_worker,
        report_synthesizer=report_synthesizer,
        equities=equities,
    )
    report = result.report

    print("SUPERVISOR_REPORT_SMOKE=PASSED")
    print(
        "REPORT"
        f"; mode={report.mode}"
        f"; symbols={','.join(report.symbols)}"
        f"; status={report.status}"
        f"; synthesis_mode={report.synthesis_mode}"
        f"; sections={len(report.sections)}"
        f"; limitations={len(report.limitations)}"
        f"; evidence={len(report.evidence)}"
    )

    for section in report.sections:
        print(
            "SECTION"
            f"; name={section.section}"
            f"; status={section.status}"
            f"; source_finding_ids={','.join(section.source_finding_ids)}"
        )
        print(
            "SECTION_TEXT"
            f"; name={section.section}"
            f"; text={_single_line(section.text)}"
        )

    for limitation in report.limitations:
        print(
            "REPORT_LIMITATION"
            f"; text={_single_line(limitation)}"
        )

    for citation in report.evidence:
        print(
            "EVIDENCE"
            f"; id={citation.evidence_id}"
            f"; source_finding_ids={','.join(citation.source_finding_ids)}"
        )


def _single_line(
    value: str,
) -> str:
    return " ".join(
        value.split()
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
            "and financial performance, important recent developments, "
            "principal risks, and a balanced comparative assessment."
        )

    return "Research the requested configured companies."


if __name__ == "__main__":
    main()
