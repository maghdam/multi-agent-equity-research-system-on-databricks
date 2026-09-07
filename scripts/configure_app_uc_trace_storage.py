"""Bind the production app MLflow experiment to Unity Catalog trace storage."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(
    0,
    str(PROJECT_ROOT / "src"),
)

from equity_research.uc_trace_storage import (  # noqa: E402
    UcTraceStorageConfig,
    configure_uc_trace_storage,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Bind an existing MLflow experiment to a Unity Catalog "
            "table-prefix trace location."
        )
    )
    parser.add_argument(
        "--experiment-id",
        required=True,
    )
    parser.add_argument(
        "--catalog",
        required=True,
    )
    parser.add_argument(
        "--schema",
        required=True,
    )
    parser.add_argument(
        "--table-prefix",
        default="app_production",
    )
    parser.add_argument(
        "--warehouse-id",
        required=True,
    )
    parser.add_argument(
        "--profile",
    )
    return parser


def main() -> None:
    args = _parser().parse_args()
    result = configure_uc_trace_storage(
        UcTraceStorageConfig(
            experiment_id=args.experiment_id,
            catalog_name=args.catalog,
            schema_name=args.schema,
            table_prefix=args.table_prefix,
            sql_warehouse_id=args.warehouse_id,
            profile=args.profile,
        )
    )

    print(
        "MLFLOW_UC_TRACE_STORAGE=PASSED; "
        f"action={result.action}; "
        f"experiment_id={result.experiment_id}; "
        f"location={result.location}"
    )
    for table_name in result.table_names:
        print(
            "TRACE_TABLE; "
            f"name={table_name}"
        )


if __name__ == "__main__":
    main()
