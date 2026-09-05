"""Run the labelled retrieval baseline against live Databricks AI Search."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from equity_research.retrieval_evaluation import (
    RetrievedChunk,
    RetrievalEvalCase,
    aggregate_case_metrics,
    evaluate_case,
)


DEFAULT_FIXTURE_PATH = (
    PROJECT_ROOT
    / "tests"
    / "fixtures"
    / "retrieval_eval_cases.json"
)

DEFAULT_QUERY_TYPE = "ANN"
DEFAULT_NUM_RESULTS = 10

QUERY_COLUMNS = (
    "chunk_id",
    "document_id",
    "source_type",
    "configured_symbols",
    "section_code",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run the human-labelled retrieval evaluation "
            "against live Databricks AI Search."
        )
    )

    parser.add_argument(
        "--fixture",
        type=Path,
        default=DEFAULT_FIXTURE_PATH,
    )
    parser.add_argument(
        "--profile",
        default=None,
        help=(
            "Optional Databricks CLI profile. "
            "When omitted, normal CLI authentication applies."
        ),
    )
    parser.add_argument(
        "--index-name",
        required=True,
        help="Fully qualified Databricks Vector Search index name.",
    )
    parser.add_argument(
        "--query-type",
        default=DEFAULT_QUERY_TYPE,
        choices=("ANN", "HYBRID"),
    )
    parser.add_argument(
        "--num-results",
        type=int,
        default=DEFAULT_NUM_RESULTS,
    )

    return parser.parse_args()


def load_cases(path: Path) -> tuple[RetrievalEvalCase, ...]:
    payload = json.loads(
        path.read_text(encoding="utf-8")
    )

    cases: list[RetrievalEvalCase] = []

    for raw_case in payload["cases"]:
        if raw_case["label_status"] != "reviewed":
            raise ValueError(
                "All live evaluation cases must be reviewed: "
                f"{raw_case['case_id']!r} is "
                f"{raw_case['label_status']!r}."
            )

        cases.append(
            RetrievalEvalCase(
                case_id=raw_case["case_id"],
                query=raw_case["query"],
                expected_symbol=raw_case["expected_symbol"],
                expected_source_type=(
                    raw_case["expected_source_type"]
                ),
                expected_section_code=(
                    raw_case["expected_section_code"]
                ),
                relevant_chunk_ids=frozenset(
                    raw_case["relevant_chunk_ids"]
                ),
            )
        )

    if not cases:
        raise ValueError(
            "Retrieval evaluation fixture has no cases."
        )

    return tuple(cases)


def query_index(
    *,
    index_name: str,
    profile: str | None,
    query_text: str,
    query_type: str,
    num_results: int,
) -> dict[str, Any]:
    if num_results < 5:
        raise ValueError(
            "num_results must be at least 5 "
            "for the configured evaluation metrics."
        )

    request_payload = {
        "columns": list(QUERY_COLUMNS),
        "num_results": num_results,
        "query_text": query_text,
        "query_type": query_type,
    }

    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".json",
        encoding="utf-8",
        newline="\n",
        delete=False,
    ) as handle:
        json.dump(
            request_payload,
            handle,
            ensure_ascii=False,
        )
        request_path = Path(handle.name)

    try:
        command = [
            "databricks",
            "api",
            "post",
            (
                "/api/2.0/vector-search/indexes/"
                f"{index_name}/query"
            ),
        ]

        if profile is not None:
            command.extend(
                [
                    "--profile",
                    profile,
                ]
            )

        command.extend(
            [
                "--json",
                f"@{request_path}",
            ]
        )

        completed = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )

        return json.loads(completed.stdout)
    finally:
        request_path.unlink(missing_ok=True)


def parse_retrieved_chunks(
    response: dict[str, Any],
) -> tuple[RetrievedChunk, ...]:
    column_names = tuple(
        column["name"]
        for column in response["manifest"]["columns"]
    )

    chunks: list[RetrievedChunk] = []

    for row in response["result"]["data_array"]:
        values = dict(
            zip(
                column_names,
                row,
                strict=True,
            )
        )

        chunks.append(
            RetrievedChunk(
                chunk_id=values["chunk_id"],
                document_id=values["document_id"],
                source_type=values["source_type"],
                configured_symbols=tuple(
                    values["configured_symbols"]
                ),
                section_code=values["section_code"],
            )
        )

    return tuple(chunks)


def format_optional_metric(
    value: float | None,
) -> str:
    if value is None:
        return "n/a"

    return f"{value:.3f}"


def main() -> None:
    args = parse_args()

    cases = load_cases(args.fixture)
    case_metrics = []

    print(
        "RETRIEVAL_EVALUATION_START"
        f"; cases={len(cases)}"
        f"; query_type={args.query_type}"
        f"; num_results={args.num_results}"
    )

    for case in cases:
        response = query_index(
            index_name=args.index_name,
            profile=args.profile,
            query_text=case.query,
            query_type=args.query_type,
            num_results=args.num_results,
        )

        retrieved = parse_retrieved_chunks(response)

        metrics = evaluate_case(
            case,
            retrieved,
        )
        case_metrics.append(metrics)

        print(
            "CASE"
            f"; id={metrics.case_id}"
            f"; hit@1={metrics.hit_at_1:.3f}"
            f"; hit@3={metrics.hit_at_3:.3f}"
            f"; hit@5={metrics.hit_at_5:.3f}"
            f"; rr={metrics.reciprocal_rank:.3f}"
            f"; symbol@5={metrics.symbol_match_at_5:.3f}"
            f"; source@5={metrics.source_type_match_at_5:.3f}"
            f"; section@5="
            f"{format_optional_metric(metrics.section_match_at_5)}"
            f"; duplicate_document_rate@5="
            f"{metrics.duplicate_document_rate_at_5:.3f}"
        )

    suite = aggregate_case_metrics(
        tuple(case_metrics)
    )

    print(
        "SUITE"
        f"; cases={suite.case_count}"
        f"; hit@1={suite.hit_at_1:.3f}"
        f"; hit@3={suite.hit_at_3:.3f}"
        f"; hit@5={suite.hit_at_5:.3f}"
        f"; mrr={suite.mean_reciprocal_rank:.3f}"
        f"; symbol@5={suite.symbol_match_at_5:.3f}"
        f"; source@5={suite.source_type_match_at_5:.3f}"
        f"; section@5="
        f"{format_optional_metric(suite.section_match_at_5)}"
        f"; duplicate_document_rate@5="
        f"{suite.duplicate_document_rate_at_5:.3f}"
    )

if __name__ == "__main__":
    main()
