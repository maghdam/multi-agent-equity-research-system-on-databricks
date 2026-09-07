"""Configure automatic MLflow quality scoring for live app traces."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(
        0,
        str(SRC_ROOT),
    )

from equity_research.production_monitoring import (  # noqa: E402
    DEFAULT_PRODUCTION_JUDGE_MODEL,
    configure_databricks_tracking,
    configure_production_monitoring,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Register and start built-in MLflow production scorers against "
            "the deployed Databricks App trace experiment."
        )
    )
    parser.add_argument(
        "--experiment-id",
        required=True,
        help="MLflow experiment ID receiving live Databricks App traces.",
    )
    parser.add_argument(
        "--profile",
        default=None,
        help="Optional Databricks CLI/SDK profile.",
    )
    parser.add_argument(
        "--judge-model",
        default=DEFAULT_PRODUCTION_JUDGE_MODEL,
        help=(
            "Databricks model URI used by built-in production judges. "
            f"Defaults to {DEFAULT_PRODUCTION_JUDGE_MODEL}."
        ),
    )
    parser.add_argument(
        "--sample-rate",
        type=float,
        default=1.0,
        help=(
            "Fraction of matching future traces to score automatically. "
            "Defaults to 1.0 for this low-volume portfolio app."
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    tracking_uri = configure_databricks_tracking(
        experiment_id=args.experiment_id,
        profile=args.profile,
    )

    try:
        statuses = configure_production_monitoring(
            experiment_id=args.experiment_id,
            judge_model=args.judge_model,
            sample_rate=args.sample_rate,
        )
    except ImportError as exc:
        raise RuntimeError(
            "Databricks production scorer registration requires the "
            "databricks-agents package. Install "
            "'requirements-evaluation-dataset.txt' and rerun."
        ) from exc

    print(
        "MLFLOW_PRODUCTION_MONITORING=PASSED"
        f"; tracking_uri={tracking_uri}"
        f"; experiment_id={args.experiment_id}"
        f"; sample_rate={args.sample_rate}"
        f"; judge_model={args.judge_model}"
    )

    for status in statuses:
        print(
            "PRODUCTION_SCORER"
            f"; name={status.name}"
            f"; action={status.action}"
            f"; sample_rate={status.sample_rate}"
            f"; filter={status.filter_string}"
        )


if __name__ == "__main__":
    main()
