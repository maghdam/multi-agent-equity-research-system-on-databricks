"""Managed MLflow production monitoring configuration for live app traces."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable, Sequence

import mlflow
from mlflow.genai import list_scorers
from mlflow.genai.scorers import (
    RelevanceToQuery,
    RetrievalGroundedness,
    RetrievalRelevance,
    Safety,
    ScorerSamplingConfig,
)


DEFAULT_PRODUCTION_JUDGE_MODEL = "databricks:/databricks-gpt-oss-120b"

ALL_APP_TRACES_FILTER = (
    "trace.status = 'OK' "
    "AND tag.environment = 'databricks_app'"
)
RESEARCH_TRACES_FILTER = (
    ALL_APP_TRACES_FILTER
    + " AND tag.interaction_type = 'research_request'"
)


@dataclass(frozen=True)
class ProductionScorerSpec:
    """One built-in scorer plus its production sampling policy."""

    name: str
    factory: Callable[[], object]
    sample_rate: float
    filter_string: str


@dataclass(frozen=True)
class ProductionScorerStatus:
    """Configuration result for one production scorer."""

    name: str
    action: str
    sample_rate: float
    filter_string: str


def build_production_scorer_specs(
    *,
    judge_model: str = DEFAULT_PRODUCTION_JUDGE_MODEL,
    sample_rate: float = 1.0,
) -> tuple[ProductionScorerSpec, ...]:
    """Return the production scorer set for live app traces."""

    normalized_model = _required_text(
        judge_model,
        "judge_model",
    )
    normalized_sample_rate = _sample_rate(
        sample_rate
    )

    return (
        ProductionScorerSpec(
            name="safety",
            factory=lambda: Safety(
                model=normalized_model
            ),
            sample_rate=normalized_sample_rate,
            filter_string=ALL_APP_TRACES_FILTER,
        ),
        ProductionScorerSpec(
            name="relevance_to_query",
            factory=lambda: RelevanceToQuery(
                model=normalized_model
            ),
            sample_rate=normalized_sample_rate,
            filter_string=ALL_APP_TRACES_FILTER,
        ),
        ProductionScorerSpec(
            name="retrieval_relevance",
            factory=lambda: RetrievalRelevance(
                model=normalized_model
            ),
            sample_rate=normalized_sample_rate,
            filter_string=RESEARCH_TRACES_FILTER,
        ),
        ProductionScorerSpec(
            name="retrieval_groundedness",
            factory=lambda: RetrievalGroundedness(
                model=normalized_model
            ),
            sample_rate=normalized_sample_rate,
            filter_string=RESEARCH_TRACES_FILTER,
        ),
    )


def configure_production_monitoring(
    *,
    experiment_id: str,
    judge_model: str = DEFAULT_PRODUCTION_JUDGE_MODEL,
    sample_rate: float = 1.0,
    existing_scorers: Sequence[object] | None = None,
) -> tuple[ProductionScorerStatus, ...]:
    """Register/start or update production scorers idempotently."""

    normalized_experiment_id = _required_text(
        experiment_id,
        "experiment_id",
    )
    specs = build_production_scorer_specs(
        judge_model=judge_model,
        sample_rate=sample_rate,
    )
    current = (
        tuple(
            list_scorers(
                experiment_id=normalized_experiment_id
            )
        )
        if existing_scorers is None
        else tuple(
            existing_scorers
        )
    )
    existing_by_name = {
        _required_text(
            getattr(
                scorer,
                "name",
                None,
            ),
            "registered scorer name",
        ): scorer
        for scorer in current
    }

    statuses: list[
        ProductionScorerStatus
    ] = []

    for spec in specs:
        sampling_config = ScorerSamplingConfig(
            sample_rate=spec.sample_rate,
            filter_string=spec.filter_string,
        )
        existing = existing_by_name.get(
            spec.name
        )

        if existing is None:
            scorer = spec.factory()
            registered = scorer.register(
                name=spec.name,
                experiment_id=normalized_experiment_id,
            )
            registered.start(
                experiment_id=normalized_experiment_id,
                sampling_config=sampling_config,
            )
            action = "registered_and_started"
        else:
            existing_rate = getattr(
                existing,
                "sample_rate",
                None,
            )
            existing_filter = getattr(
                existing,
                "filter_string",
                None,
            )

            if (
                existing_rate == spec.sample_rate
                and existing_filter
                == spec.filter_string
            ):
                action = "unchanged"
            else:
                existing.update(
                    experiment_id=normalized_experiment_id,
                    sampling_config=sampling_config,
                )
                action = "updated"

        statuses.append(
            ProductionScorerStatus(
                name=spec.name,
                action=action,
                sample_rate=spec.sample_rate,
                filter_string=spec.filter_string,
            )
        )

    return tuple(
        statuses
    )


def configure_databricks_tracking(
    *,
    experiment_id: str,
    profile: str | None = None,
) -> str:
    """Configure MLflow tracking for scorer lifecycle operations."""

    normalized_experiment_id = _required_text(
        experiment_id,
        "experiment_id",
    )
    normalized_profile = (
        _required_text(
            profile,
            "profile",
        )
        if profile is not None
        else None
    )
    tracking_uri = (
        f"databricks://{normalized_profile}"
        if normalized_profile is not None
        else "databricks"
    )

    if normalized_profile is not None:
        os.environ[
            "DATABRICKS_CONFIG_PROFILE"
        ] = normalized_profile

    mlflow.set_tracking_uri(
        tracking_uri
    )
    mlflow.set_experiment(
        experiment_id=normalized_experiment_id
    )

    return tracking_uri


def _required_text(
    value: object,
    field: str,
) -> str:
    if not isinstance(
        value,
        str,
    ) or not value.strip():
        raise ValueError(
            f"{field} must be a nonblank string."
        )

    return value.strip()


def _sample_rate(
    value: object,
) -> float:
    if isinstance(
        value,
        bool,
    ) or not isinstance(
        value,
        (
            int,
            float,
        ),
    ):
        raise ValueError(
            "sample_rate must be a number between 0 and 1."
        )

    normalized = float(
        value
    )

    if not 0.0 <= normalized <= 1.0:
        raise ValueError(
            "sample_rate must be between 0 and 1."
        )

    return normalized
