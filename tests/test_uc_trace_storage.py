from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from equity_research.uc_trace_storage import (  # noqa: E402
    UcTraceStorageConfig,
    configure_uc_trace_storage,
)


class UcTraceStorageTests(unittest.TestCase):
    def test_binds_unconfigured_experiment_and_selects_profile(self) -> None:
        config = UcTraceStorageConfig(
            experiment_id="123",
            catalog_name="workspace",
            schema_name="dev_ai",
            table_prefix="app_production",
            sql_warehouse_id="warehouse-1",
            profile="free-edition-us-east-2",
        )

        with (
            patch(
                "equity_research.uc_trace_storage.mlflow.set_tracking_uri"
            ) as set_tracking_uri,
            patch(
                "equity_research.uc_trace_storage.mlflow.get_experiment",
                return_value=SimpleNamespace(
                    trace_location=None
                ),
            ),
            patch(
                "equity_research.uc_trace_storage.mlflow.set_experiment"
            ) as set_experiment,
        ):
            result = configure_uc_trace_storage(
                config
            )

        self.assertEqual(
            result.action,
            "bound",
        )
        self.assertEqual(
            result.location,
            "workspace.dev_ai.app_production",
        )
        self.assertEqual(
            result.table_names,
            (
                "workspace.dev_ai.app_production_otel_annotations",
                "workspace.dev_ai.app_production_otel_logs",
                "workspace.dev_ai.app_production_otel_metrics",
                "workspace.dev_ai.app_production_otel_spans",
            ),
        )
        set_tracking_uri.assert_called_once_with(
            "databricks://free-edition-us-east-2"
        )
        self.assertEqual(
            os.environ[
                "DATABRICKS_CONFIG_PROFILE"
            ],
            "free-edition-us-east-2",
        )
        self.assertEqual(
            os.environ[
                "MLFLOW_TRACING_SQL_WAREHOUSE_ID"
            ],
            "warehouse-1",
        )
        kwargs = (
            set_experiment.call_args.kwargs
        )
        self.assertEqual(
            kwargs["experiment_id"],
            "123",
        )
        self.assertEqual(
            kwargs[
                "trace_location"
            ].table_prefix,
            "app_production",
        )

    def test_existing_matching_location_is_idempotent(self) -> None:
        existing = SimpleNamespace(
            catalog_name="workspace",
            schema_name="dev_ai",
            table_prefix="app_production",
        )

        with (
            patch(
                "equity_research.uc_trace_storage.mlflow.set_tracking_uri"
            ),
            patch(
                "equity_research.uc_trace_storage.mlflow.get_experiment",
                return_value=SimpleNamespace(
                    trace_location=existing
                ),
            ),
            patch(
                "equity_research.uc_trace_storage.mlflow.set_experiment"
            ) as set_experiment,
        ):
            result = configure_uc_trace_storage(
                UcTraceStorageConfig(
                    experiment_id="123",
                    catalog_name="workspace",
                    schema_name="dev_ai",
                    table_prefix="app_production",
                    sql_warehouse_id="warehouse-1",
                )
            )

        self.assertEqual(
            result.action,
            "unchanged",
        )
        set_experiment.assert_called_once_with(
            experiment_id="123"
        )

    def test_refuses_different_existing_location(self) -> None:
        existing = SimpleNamespace(
            catalog_name="workspace",
            schema_name="other_schema",
            table_prefix="other_prefix",
        )

        with (
            patch(
                "equity_research.uc_trace_storage.mlflow.set_tracking_uri"
            ),
            patch(
                "equity_research.uc_trace_storage.mlflow.get_experiment",
                return_value=SimpleNamespace(
                    trace_location=existing
                ),
            ),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "different Unity Catalog trace location",
            ):
                configure_uc_trace_storage(
                    UcTraceStorageConfig(
                        experiment_id="123",
                        catalog_name="workspace",
                        schema_name="dev_ai",
                        table_prefix="app_production",
                        sql_warehouse_id="warehouse-1",
                    )
                )


if __name__ == "__main__":
    unittest.main()
