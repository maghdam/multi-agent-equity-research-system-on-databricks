from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from equity_research.production_monitoring import (  # noqa: E402
    ALL_APP_TRACES_FILTER,
    RESEARCH_TRACES_FILTER,
    build_production_scorer_specs,
    configure_databricks_tracking,
    configure_production_monitoring,
)


class ProductionMonitoringTests(unittest.TestCase):
    def test_specs_cover_live_quality_without_applying_retrieval_to_followups(
        self,
    ) -> None:
        specs = build_production_scorer_specs(
            judge_model="databricks:/judge",
            sample_rate=1.0,
        )
        by_name = {
            spec.name: spec
            for spec in specs
        }

        self.assertEqual(
            set(by_name),
            {
                "safety",
                "relevance_to_query",
                "retrieval_relevance",
                "retrieval_groundedness",
            },
        )
        self.assertEqual(
            by_name[
                "safety"
            ].filter_string,
            ALL_APP_TRACES_FILTER,
        )
        self.assertEqual(
            by_name[
                "relevance_to_query"
            ].filter_string,
            ALL_APP_TRACES_FILTER,
        )
        self.assertEqual(
            by_name[
                "retrieval_relevance"
            ].filter_string,
            RESEARCH_TRACES_FILTER,
        )
        self.assertEqual(
            by_name[
                "retrieval_groundedness"
            ].filter_string,
            RESEARCH_TRACES_FILTER,
        )
        self.assertIn(
            "interaction_type = 'research_request'",
            RESEARCH_TRACES_FILTER,
        )

    def test_sample_rate_validation_is_bounded(self) -> None:
        for value in (
            -0.01,
            1.01,
            True,
        ):
            with self.subTest(
                value=value
            ):
                with self.assertRaises(
                    ValueError
                ):
                    build_production_scorer_specs(
                        sample_rate=value,
                    )

    @patch(
        "equity_research.production_monitoring.mlflow.set_experiment"
    )
    @patch(
        "equity_research.production_monitoring.mlflow.set_tracking_uri"
    )
    def test_tracking_uses_explicit_databricks_profile_and_experiment_id(
        self,
        set_tracking_uri,
        set_experiment,
    ) -> None:
        with patch.dict(
            os.environ,
            {
                "DATABRICKS_CONFIG_PROFILE": "stale-dev",
            },
        ):
            result = configure_databricks_tracking(
                experiment_id="3258224992927820",
                profile="free-edition-us-east-2",
            )

            self.assertEqual(
                os.environ[
                    "DATABRICKS_CONFIG_PROFILE"
                ],
                "free-edition-us-east-2",
            )

        self.assertEqual(
            result,
            "databricks://free-edition-us-east-2",
        )
        set_tracking_uri.assert_called_once_with(
            "databricks://free-edition-us-east-2"
        )
        set_experiment.assert_called_once_with(
            experiment_id="3258224992927820"
        )

    @patch(
        "equity_research.production_monitoring.build_production_scorer_specs"
    )
    def test_new_scorer_is_registered_and_started(
        self,
        build_specs,
    ) -> None:
        scorer = Mock()
        registered = Mock()
        scorer.register.return_value = (
            registered
        )
        build_specs.return_value = (
            SimpleNamespace(
                name="safety",
                factory=lambda: scorer,
                sample_rate=1.0,
                filter_string=ALL_APP_TRACES_FILTER,
            ),
        )

        statuses = configure_production_monitoring(
            experiment_id="123",
            existing_scorers=(),
        )

        scorer.register.assert_called_once_with(
            name="safety",
            experiment_id="123",
        )
        registered.start.assert_called_once()
        start_kwargs = (
            registered.start.call_args.kwargs
        )
        self.assertEqual(
            start_kwargs[
                "experiment_id"
            ],
            "123",
        )
        self.assertEqual(
            start_kwargs[
                "sampling_config"
            ].sample_rate,
            1.0,
        )
        self.assertEqual(
            start_kwargs[
                "sampling_config"
            ].filter_string,
            ALL_APP_TRACES_FILTER,
        )
        self.assertEqual(
            statuses[0].action,
            "registered_and_started",
        )

    @patch(
        "equity_research.production_monitoring.build_production_scorer_specs"
    )
    def test_matching_existing_scorer_is_idempotent(
        self,
        build_specs,
    ) -> None:
        build_specs.return_value = (
            SimpleNamespace(
                name="safety",
                factory=Mock(),
                sample_rate=1.0,
                filter_string=ALL_APP_TRACES_FILTER,
            ),
        )
        existing = Mock()
        existing.name = "safety"
        existing.sample_rate = 1.0
        existing.filter_string = (
            ALL_APP_TRACES_FILTER
        )

        statuses = configure_production_monitoring(
            experiment_id="123",
            existing_scorers=(
                existing,
            ),
        )

        existing.update.assert_not_called()
        self.assertEqual(
            statuses[0].action,
            "unchanged",
        )

    @patch(
        "equity_research.production_monitoring.build_production_scorer_specs"
    )
    def test_changed_sampling_policy_updates_existing_scorer(
        self,
        build_specs,
    ) -> None:
        build_specs.return_value = (
            SimpleNamespace(
                name="safety",
                factory=Mock(),
                sample_rate=1.0,
                filter_string=ALL_APP_TRACES_FILTER,
            ),
        )
        existing = Mock()
        existing.name = "safety"
        existing.sample_rate = 0.25
        existing.filter_string = None

        statuses = configure_production_monitoring(
            experiment_id="123",
            existing_scorers=(
                existing,
            ),
        )

        existing.update.assert_called_once()
        update_kwargs = (
            existing.update.call_args.kwargs
        )
        self.assertEqual(
            update_kwargs[
                "experiment_id"
            ],
            "123",
        )
        self.assertEqual(
            update_kwargs[
                "sampling_config"
            ].sample_rate,
            1.0,
        )
        self.assertEqual(
            statuses[0].action,
            "updated",
        )


if __name__ == "__main__":
    unittest.main()
