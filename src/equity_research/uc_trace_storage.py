"""Provision Unity Catalog-backed storage for production MLflow traces."""

from __future__ import annotations

import os
from dataclasses import dataclass

import mlflow
from mlflow.entities.trace_location import UnityCatalog


@dataclass(frozen=True)
class UcTraceStorageConfig:
    """Configuration for one experiment-bound Unity Catalog trace location."""

    experiment_id: str
    catalog_name: str
    schema_name: str
    table_prefix: str
    sql_warehouse_id: str
    profile: str | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "experiment_id",
            "catalog_name",
            "schema_name",
            "table_prefix",
            "sql_warehouse_id",
        ):
            value = getattr(
                self,
                field_name,
            )
            if (
                not isinstance(value, str)
                or not value.strip()
            ):
                raise ValueError(
                    f"{field_name} must be a nonblank string."
                )

        if self.profile is not None and (
            not isinstance(self.profile, str)
            or not self.profile.strip()
        ):
            raise ValueError(
                "profile must be None or a nonblank string."
            )


@dataclass(frozen=True)
class UcTraceStorageResult:
    """Resolved production trace-storage contract."""

    action: str
    experiment_id: str
    location: str
    table_names: tuple[str, ...]


def configure_uc_trace_storage(
    config: UcTraceStorageConfig,
) -> UcTraceStorageResult:
    """Bind an existing MLflow experiment to one UC table-prefix trace location."""

    if not isinstance(
        config,
        UcTraceStorageConfig,
    ):
        raise TypeError(
            "config must be UcTraceStorageConfig."
        )

    profile = (
        config.profile.strip()
        if config.profile is not None
        else None
    )
    tracking_uri = (
        f"databricks://{profile}"
        if profile is not None
        else "databricks"
    )

    if profile is not None:
        os.environ[
            "DATABRICKS_CONFIG_PROFILE"
        ] = profile

    os.environ[
        "MLFLOW_TRACING_SQL_WAREHOUSE_ID"
    ] = config.sql_warehouse_id.strip()

    mlflow.set_tracking_uri(
        tracking_uri
    )

    experiment_id = (
        config.experiment_id.strip()
    )
    catalog_name = (
        config.catalog_name.strip()
    )
    schema_name = (
        config.schema_name.strip()
    )
    table_prefix = (
        config.table_prefix.strip()
    )
    desired = UnityCatalog(
        catalog_name=catalog_name,
        schema_name=schema_name,
        table_prefix=table_prefix,
    )

    experiment = mlflow.get_experiment(
        experiment_id
    )
    if experiment is None:
        raise RuntimeError(
            f"MLflow experiment {experiment_id} was not found."
        )

    existing = experiment.trace_location

    if existing is None:
        mlflow.set_experiment(
            experiment_id=experiment_id,
            trace_location=desired,
        )
        action = "bound"
    else:
        actual = (
            existing.catalog_name,
            existing.schema_name,
            existing.table_prefix,
        )
        expected = (
            catalog_name,
            schema_name,
            table_prefix,
        )
        if actual != expected:
            raise RuntimeError(
                "MLflow experiment is already bound to a different "
                f"Unity Catalog trace location: actual={actual!r}, "
                f"expected={expected!r}."
            )

        mlflow.set_experiment(
            experiment_id=experiment_id
        )
        action = "unchanged"

    location = (
        f"{catalog_name}.{schema_name}.{table_prefix}"
    )
    table_names = tuple(
        f"{location}_{suffix}"
        for suffix in (
            "otel_annotations",
            "otel_logs",
            "otel_metrics",
            "otel_spans",
        )
    )

    return UcTraceStorageResult(
        action=action,
        experiment_id=experiment_id,
        location=location,
        table_names=table_names,
    )
