"""Inspect MLflow evaluation assessments without rerunning the research graph."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import mlflow


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(
        0,
        str(SRC_ROOT),
    )

from equity_research.mlflow_evaluation import (  # noqa: E402
    summarize_observability_spans,
    summarize_trace_assessments,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Inspect assessment values and rationales already logged on one "
            "MLflow GenAI evaluation run without rerunning the application."
        )
    )
    parser.add_argument(
        "--run-id",
        required=True,
        help="MLflow evaluation run ID.",
    )
    parser.add_argument(
        "--profile",
        default=None,
        help="Optional Databricks CLI/SDK profile.",
    )
    parser.add_argument(
        "--name-prefix",
        default=None,
        help=(
            "Optional assessment-name prefix filter, for example 'guideline_'."
        ),
    )
    parser.add_argument(
        "--show-span-summary",
        action="store_true",
        help=(
            "Print privacy-safe summaries for project-owned Gold, retrieval, "
            "worker-model, and Supervisor spans without printing span payloads."
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.profile is not None:
        profile = args.profile.strip()
        if not profile:
            raise ValueError(
                "--profile must be nonblank when supplied."
            )
        os.environ["DATABRICKS_CONFIG_PROFILE"] = profile
        mlflow.set_tracking_uri(
            f"databricks://{profile}"
        )
    else:
        mlflow.set_tracking_uri(
            "databricks"
        )

    run_id = args.run_id.strip()
    if not run_id:
        raise ValueError(
            "--run-id must be nonblank."
        )

    prefix = (
        args.name_prefix.strip()
        if isinstance(args.name_prefix, str)
        and args.name_prefix.strip()
        else None
    )

    run = mlflow.get_run(
        run_id
    )
    experiment_id = run.info.experiment_id

    if (
        not isinstance(experiment_id, str)
        or not experiment_id.strip()
    ):
        raise RuntimeError(
            "MLflow evaluation run is missing its experiment ID."
        )

    traces = mlflow.search_traces(
        locations=[
            experiment_id.strip()
        ],
        run_id=run_id,
        return_type="list",
        include_spans=args.show_span_summary,
    )

    printed = 0
    available_names: set[str] = set()

    span_summaries = 0

    for trace in traces:
        trace_data = getattr(
            trace,
            "data",
            None,
        )
        raw_spans = getattr(
            trace_data,
            "spans",
            (),
        )
        span_names_by_id = {
            getattr(
                span,
                "span_id",
                None,
            ): getattr(
                span,
                "name",
                None,
            )
            for span in raw_spans
            if isinstance(
                getattr(
                    span,
                    "span_id",
                    None,
                ),
                str,
            )
            and isinstance(
                getattr(
                    span,
                    "name",
                    None,
                ),
                str,
            )
            and getattr(
                span,
                "parent_id",
                None,
            )
            is not None
        }
        assessments = trace.search_assessments()

        for summary in summarize_trace_assessments(
            assessments
        ):
            available_names.add(
                summary["name"]
            )

            if (
                prefix is not None
                and not summary["name"].startswith(
                    prefix
                )
            ):
                continue

            source_span = span_names_by_id.get(
                summary["span_id"]
            )
            fields = [
                "ASSESSMENT",
                f"name={summary['name']}",
                f"value={summary['value']}",
            ]
            if source_span is not None:
                fields.append(
                    f"span={source_span}"
                )

            print(
                "; ".join(
                    fields
                )
            )

            if summary["rationale"] is not None:
                print(
                    "ASSESSMENT_RATIONALE"
                    f"; name={summary['name']}"
                    f"; rationale={_single_line(summary['rationale'])}"
                )

            if summary["error"] is not None:
                print(
                    "ASSESSMENT_ERROR"
                    f"; name={summary['name']}"
                    f"; error={_single_line(summary['error'])}"
                )

            printed += 1

        if args.show_span_summary:
            for span_summary in summarize_observability_spans(
                raw_spans
            ):
                fields = [
                    "SPAN",
                    f"name={span_summary['name']}",
                    f"type={span_summary['span_type']}",
                ]
                for key in (
                    "model",
                    "authority",
                    "dataset",
                    "component",
                    "attempt",
                    "topic",
                    "repair_count",
                    "synthesis_mode",
                    "report_status",
                    "request_mode",
                    "rejection_reason",
                    "unsupported_symbol_count",
                    "evaluation_case",
                    "fixture_type",
                    "retrieval_result_count",
                    "injection_marker_present",
                    "unauthorized_tool_calls",
                    "token_usage",
                ):
                    value = span_summary[
                        key
                    ]
                    if value is not None:
                        fields.append(
                            f"{key}={value}"
                        )

                print(
                    "; ".join(
                        fields
                    )
                )
                span_summaries += 1

    if printed == 0 and available_names:
        print(
            "AVAILABLE_ASSESSMENTS"
            f"; names={','.join(sorted(available_names))}"
        )

    print(
        "MLFLOW_EVALUATION_INSPECTION=PASSED"
        f"; run_id={run_id}"
        f"; experiment_id={experiment_id}"
        f"; traces={len(traces)}"
        f"; assessments={printed}"
        f"; span_summaries={span_summaries}"
    )


def _single_line(
    value: str,
) -> str:
    return " ".join(
        value.split()
    )


if __name__ == "__main__":
    main()
