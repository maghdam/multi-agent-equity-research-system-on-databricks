"""Create or update the managed Supervisor MLflow evaluation dataset."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import mlflow
from databricks.sdk.errors.platform import NotFound
from mlflow.genai.datasets import get_dataset


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(
        0,
        str(SRC_ROOT),
    )

from equity_research.mlflow_evaluation import (  # noqa: E402
    build_live_evaluation_data,
    require_managed_evaluation_dataset_runtime,
)


DEFAULT_EXPERIMENT = "/Shared/equity-research-genai-evaluation"
DEFAULT_DATASET = (
    "workspace.dev_mohammad_m_aghdam_equity_research_ai."
    "supervisor_evaluation_dataset"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create or update the Unity Catalog-backed MLflow evaluation "
            "dataset from repository-owned contract cases."
        )
    )
    parser.add_argument(
        "--profile",
        default=None,
        help="Optional Databricks CLI/SDK profile.",
    )
    parser.add_argument(
        "--mlflow-experiment",
        default=DEFAULT_EXPERIMENT,
        help="MLflow experiment associated with the evaluation dataset.",
    )
    parser.add_argument(
        "--dataset-name",
        default=DEFAULT_DATASET,
        help="Fully qualified Unity Catalog evaluation dataset name.",
    )
    parser.add_argument(
        "--case",
        nargs="+",
        default=["E1", "E2"],
        help="Repository-owned contract case IDs to merge. Supported: E1 E2.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    profile = _optional_text(
        args.profile
    )
    experiment_name = _required_text(
        args.mlflow_experiment,
        "--mlflow-experiment",
    )
    dataset_name = _required_text(
        args.dataset_name,
        "--dataset-name",
    )

    if profile is not None:
        os.environ[
            "DATABRICKS_CONFIG_PROFILE"
        ] = profile
        mlflow.set_tracking_uri(
            f"databricks://{profile}"
        )
    else:
        mlflow.set_tracking_uri(
            "databricks"
        )

    experiment = mlflow.set_experiment(
        experiment_name
    )
    experiment_id = experiment.experiment_id

    require_managed_evaluation_dataset_runtime()

    records = build_live_evaluation_data(
        args.case
    )

    try:
        dataset = get_dataset(
            name=dataset_name
        )
    except NotFound as exc:
        raise RuntimeError(
            "Managed evaluation dataset does not exist. Create it once from "
            "the Databricks experiment UI because this project currently runs "
            "locally on Python 3.14, while Databricks Connect serverless "
            "provisioning requires Python 3.12. In Databricks, open experiment "
            f"'{experiment_name}', choose Datasets > Create dataset, select the "
            "Unity Catalog schema from the requested dataset name, and create "
            f"table '{dataset_name.rsplit('.', 1)[-1]}'. Then rerun this sync "
            "command; repository-owned records remain the source of truth."
        ) from exc

    dataset = dataset.merge_records(
        records
    )
    frame = dataset.to_df()

    print(
        "MLFLOW_EVALUATION_DATASET_SYNC=PASSED"
        "; action=synced"
        f"; name={dataset_name}"
        f"; experiment_id={experiment_id}"
        f"; merged_cases={','.join(case.upper() for case in args.case)}"
        f"; rows={len(frame)}"
    )


def _required_text(
    value: object,
    field: str,
) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(
            f"{field} must be a nonblank string."
        )

    return value.strip()


def _optional_text(
    value: object,
) -> str | None:
    if value is None:
        return None

    if not isinstance(value, str) or not value.strip():
        raise ValueError(
            "--profile must be nonblank when supplied."
        )

    return value.strip()


if __name__ == "__main__":
    main()
