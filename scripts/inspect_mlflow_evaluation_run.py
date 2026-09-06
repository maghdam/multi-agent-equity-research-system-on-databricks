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

    traces = mlflow.search_traces(
        run_id=run_id,
        return_type="pandas",
        include_spans=False,
    )

    printed = 0

    for _, row in traces.iterrows():
        assessments = row.get(
            "assessments"
        )

        if not isinstance(
            assessments,
            list,
        ):
            continue

        for summary in summarize_trace_assessments(
            assessments
        ):
            if (
                prefix is not None
                and not summary["name"].startswith(
                    prefix
                )
            ):
                continue

            print(
                "ASSESSMENT"
                f"; name={summary['name']}"
                f"; value={summary['value']}"
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

    print(
        "MLFLOW_EVALUATION_INSPECTION=PASSED"
        f"; run_id={run_id}"
        f"; assessments={printed}"
    )


def _single_line(
    value: str,
) -> str:
    return " ".join(
        value.split()
    )


if __name__ == "__main__":
    main()
