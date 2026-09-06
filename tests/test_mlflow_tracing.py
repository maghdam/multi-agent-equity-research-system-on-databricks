"""Offline tests for MLflow tracing configuration and graph wrapping."""

import os
import sys
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import Mock, patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from equity_research.mlflow_tracing import (  # noqa: E402
    MlflowTracingConfig,
    configure_mlflow_tracing,
    mlflow_tracking_uri,
    research_trace_tags,
    run_traced_supervisor_research_graph,
)


class MlflowTracingConfigTests(unittest.TestCase):
    def test_tracking_uri_uses_named_databricks_profile(self) -> None:
        config = MlflowTracingConfig(
            experiment_name="/Shared/equity-research-test",
            profile="free-edition-us-east-2",
        )

        self.assertEqual(
            mlflow_tracking_uri(config),
            "databricks://free-edition-us-east-2",
        )

    def test_tracking_uri_uses_default_databricks_workspace_without_profile(
        self,
    ) -> None:
        self.assertEqual(
            mlflow_tracking_uri(
                MlflowTracingConfig(
                    experiment_name="/Shared/equity-research-test",
                )
            ),
            "databricks",
        )

    def test_config_rejects_blank_values(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "experiment_name must be a nonblank string",
        ):
            MlflowTracingConfig(
                experiment_name=" ",
            )

        with self.assertRaisesRegex(
            ValueError,
            "profile must be None or a nonblank string",
        ):
            MlflowTracingConfig(
                profile=" ",
            )

        with self.assertRaisesRegex(
            ValueError,
            "environment must be a nonblank string",
        ):
            MlflowTracingConfig(
                environment=" ",
            )

    def test_scope_tags_are_normalized_and_do_not_include_request_text(
        self,
    ) -> None:
        tags = research_trace_tags(
            requested_symbols=("aapl", " msft "),
            environment="dev",
        )

        self.assertEqual(
            tags,
            {
                "project": "multi-agent-equity-research-system",
                "component": "supervisor_research_graph",
                "environment": "dev",
                "request_mode": "comparison",
                "symbols": "AAPL,MSFT",
            },
        )
        self.assertNotIn(
            "request_text",
            tags,
        )

    def test_scope_tags_mark_invalid_arity_without_expanding_scope(self) -> None:
        tags = research_trace_tags(
            requested_symbols=("AAPL", "MSFT", "NVDA"),
            environment="dev",
        )

        self.assertEqual(
            tags["request_mode"],
            "unsupported_scope",
        )
        self.assertEqual(
            tags["symbols"],
            "AAPL,MSFT,NVDA",
        )

    def test_scope_tags_reject_blank_symbol(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "requested symbols must be nonblank strings",
        ):
            research_trace_tags(
                requested_symbols=("AAPL", " "),
                environment="dev",
            )


class MlflowTracingRuntimeTests(unittest.TestCase):
    @patch("equity_research.mlflow_tracing.mlflow_langchain_autolog")
    @patch("equity_research.mlflow_tracing.mlflow.set_experiment")
    @patch("equity_research.mlflow_tracing.mlflow.set_tracking_uri")
    def test_configure_enables_supported_langgraph_autologging(
        self,
        set_tracking_uri,
        set_experiment,
        autolog,
    ) -> None:
        config = MlflowTracingConfig(
            experiment_name="/Shared/equity-research-test",
            profile="profile-1",
        )

        with patch.dict(
            os.environ,
            {
                "DATABRICKS_CONFIG_PROFILE": "stale-profile",
            },
        ):
            tracking_uri = configure_mlflow_tracing(
                config
            )

            self.assertEqual(
                os.environ["DATABRICKS_CONFIG_PROFILE"],
                "profile-1",
            )

        self.assertEqual(
            tracking_uri,
            "databricks://profile-1",
        )
        set_tracking_uri.assert_called_once_with(
            "databricks://profile-1"
        )
        set_experiment.assert_called_once_with(
            "/Shared/equity-research-test"
        )
        autolog.assert_called_once_with(
            log_traces=True,
            silent=False,
        )

    @patch("equity_research.mlflow_tracing.mlflow_langchain_autolog")
    @patch("equity_research.mlflow_tracing.mlflow.set_experiment")
    @patch("equity_research.mlflow_tracing.mlflow.set_tracking_uri")
    def test_configure_without_profile_preserves_existing_sdk_profile(
        self,
        set_tracking_uri,
        set_experiment,
        autolog,
    ) -> None:
        config = MlflowTracingConfig(
            experiment_name="/Shared/equity-research-test",
            profile=None,
        )

        with patch.dict(
            os.environ,
            {
                "DATABRICKS_CONFIG_PROFILE": "existing-profile",
            },
        ):
            tracking_uri = configure_mlflow_tracing(
                config
            )

            self.assertEqual(
                os.environ["DATABRICKS_CONFIG_PROFILE"],
                "existing-profile",
            )

        self.assertEqual(
            tracking_uri,
            "databricks",
        )
        set_tracking_uri.assert_called_once_with(
            "databricks"
        )
        set_experiment.assert_called_once_with(
            "/Shared/equity-research-test"
        )
        autolog.assert_called_once_with(
            log_traces=True,
            silent=False,
        )

    @patch(
        "equity_research.mlflow_tracing.run_supervisor_research_graph"
    )
    @patch(
        "equity_research.mlflow_tracing.configure_mlflow_tracing"
    )
    @patch(
        "equity_research.mlflow_tracing.mlflow.tracing.context"
    )
    def test_traced_runner_wraps_existing_graph_with_safe_context(
        self,
        tracing_context,
        configure,
        run_graph,
    ) -> None:
        expected_result = Mock()
        run_graph.return_value = expected_result
        tracing_context.return_value = nullcontext()
        config = MlflowTracingConfig(
            experiment_name="/Shared/equity-research-test",
            profile="profile-1",
            environment="dev",
        )
        market_worker = Mock()
        company_worker = Mock()
        report_synthesizer = Mock()

        result = run_traced_supervisor_research_graph(
            request_text="Compare AAPL and MSFT.",
            requested_symbols=("AAPL", "MSFT"),
            market_worker=market_worker,
            company_worker=company_worker,
            report_synthesizer=report_synthesizer,
            tracing_config=config,
            equities=None,
        )

        self.assertIs(
            result,
            expected_result,
        )
        configure.assert_called_once_with(
            config
        )

        tracing_context.assert_called_once()
        kwargs = tracing_context.call_args.kwargs
        self.assertEqual(
            kwargs["tags"]["request_mode"],
            "comparison",
        )
        self.assertEqual(
            kwargs["tags"]["symbols"],
            "AAPL,MSFT",
        )
        self.assertEqual(
            kwargs["metadata"],
            {
                "privacy_boundary": (
                    "validated_graph_state_no_raw_provider_text"
                ),
                "structured_authority": "gold_metrics",
                "narrative_authority": (
                    "validated_rag_worker_findings"
                ),
            },
        )
        self.assertNotIn(
            "Compare AAPL and MSFT.",
            str(kwargs),
        )

        run_graph.assert_called_once_with(
            request_text="Compare AAPL and MSFT.",
            requested_symbols=("AAPL", "MSFT"),
            market_worker=market_worker,
            company_worker=company_worker,
            report_synthesizer=report_synthesizer,
            equities=None,
        )

    def test_traced_runner_rejects_wrong_tracing_config_type(self) -> None:
        with self.assertRaisesRegex(
            TypeError,
            "tracing_config must be MlflowTracingConfig",
        ):
            run_traced_supervisor_research_graph(
                request_text="Research AAPL.",
                requested_symbols=("AAPL",),
                market_worker=Mock(),
                company_worker=Mock(),
                report_synthesizer=Mock(),
                tracing_config=object(),  # type: ignore[arg-type]
            )


if __name__ == "__main__":
    unittest.main()
