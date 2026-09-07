from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from dash import dcc


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import app as app_module  # noqa: E402


def _component_by_id(component, component_id: str):
    if getattr(component, "id", None) == component_id:
        return component

    children = getattr(component, "children", None)
    if children is None:
        return None

    if not isinstance(children, (list, tuple)):
        children = [children]

    for child in children:
        found = _component_by_id(
            child,
            component_id,
        )
        if found is not None:
            return found

    return None


class AppShellTests(unittest.TestCase):
    def test_theme_defaults_to_light_and_persists_locally(self) -> None:
        shell = _component_by_id(
            app_module.app.layout,
            "app-shell",
        )
        store = _component_by_id(
            app_module.app.layout,
            "theme-store",
        )
        toggle = _component_by_id(
            app_module.app.layout,
            "theme-toggle",
        )

        self.assertIsNotNone(shell)
        self.assertEqual(
            shell.className,
            "app-shell theme-light",
        )

        self.assertIsInstance(
            store,
            dcc.Store,
        )
        self.assertEqual(
            store.storage_type,
            "local",
        )
        self.assertEqual(
            store.data,
            "light",
        )

        self.assertIsNotNone(toggle)
        self.assertEqual(
            toggle.children,
            "Dark mode",
        )

    def test_local_run_research_stays_in_preview_mode(self) -> None:
        environment = {}

        self.assertFalse(
            app_module._databricks_app_resources_available(
                environment
            )
        )

        with patch.dict(
            app_module.os.environ,
            {},
            clear=True,
        ):
            result = app_module.run_research_action(
                1,
                "AAPL",
                "MSFT",
                60,
            )

        self.assertEqual(
            len(result),
            6,
        )
        self.assertIn(
            "Valid local preview",
            result[0],
        )
        self.assertIn(
            "mode=comparison",
            result[0],
        )
        self.assertIn(
            "symbols=AAPL,MSFT",
            result[0],
        )
        self.assertTrue(
            all(
                item is app_module.no_update
                for item in result[1:]
            )
        )

    def test_optional_daily_prices_resource_does_not_force_preview(self) -> None:
        environment = {
            app_module.WAREHOUSE_ENV: "warehouse-1",
            app_module.MARKET_METRICS_TABLE_ENV: (
                "workspace.gold.market_metrics"
            ),
            app_module.FUNDAMENTAL_METRICS_TABLE_ENV: (
                "workspace.gold.fundamental_metrics"
            ),
            app_module.VECTOR_INDEX_ENV: "workspace.ai.index",
        }

        self.assertTrue(
            app_module._databricks_app_resources_available(
                environment
            )
        )

    def test_live_failure_logs_only_bounded_metadata(self) -> None:
        environment = {
            app_module.WAREHOUSE_ENV: "warehouse-1",
            app_module.MARKET_METRICS_TABLE_ENV: (
                "workspace.gold.market_metrics"
            ),
            app_module.FUNDAMENTAL_METRICS_TABLE_ENV: (
                "workspace.gold.fundamental_metrics"
            ),
            app_module.VECTOR_INDEX_ENV: "workspace.ai.index",
        }

        with (
            patch.dict(
                app_module.os.environ,
                environment,
                clear=True,
            ),
            patch.object(
                app_module.DatabricksAppRuntimeConfig,
                "from_environment",
                return_value=object(),
            ),
            patch(
                "app.DatabricksAppResearchRuntime",
                return_value=object(),
            ),
            patch(
                "app.run_app_research",
                side_effect=RuntimeError(
                    "sensitive details that must not be logged"
                ),
            ),
            self.assertLogs(
                app_module.logger,
                level="ERROR",
            ) as captured,
        ):
            result = app_module.run_research_action(
                1,
                "AAPL",
                "MSFT",
                60,
            )

        self.assertEqual(
            len(result),
            6,
        )
        self.assertIn(
            "Research execution failed safely",
            result[0],
        )
        self.assertTrue(
            all(
                item is app_module.no_update
                for item in result[1:]
            )
        )
        log_text = "\n".join(
            captured.output
        )
        self.assertIn(
            "mode=comparison",
            log_text,
        )
        self.assertIn(
            "symbols=AAPL,MSFT",
            log_text,
        )
        self.assertIn(
            "market_window=60",
            log_text,
        )
        self.assertIn(
            "error_type=RuntimeError",
            log_text,
        )
        self.assertNotIn(
            "sensitive details",
            log_text,
        )

    def test_bound_resources_switch_callback_to_real_runtime(self) -> None:
        environment = {
            app_module.WAREHOUSE_ENV: "warehouse-1",
            app_module.MARKET_METRICS_TABLE_ENV: (
                "workspace.gold.market_metrics"
            ),
            app_module.FUNDAMENTAL_METRICS_TABLE_ENV: (
                "workspace.gold.fundamental_metrics"
            ),
            app_module.VECTOR_INDEX_ENV: "workspace.ai.index",
        }
        session = object()
        presentation = SimpleNamespace(
            mode="comparison",
            symbols=("AAPL", "MSFT"),
            report_status="ready",
            synthesis_mode="model",
            report_sections=(
                SimpleNamespace(
                    section="market_performance",
                    title="Market performance",
                    status="available",
                    text="Market text.",
                    source_finding_ids=("market:m1",),
                ),
                SimpleNamespace(
                    section="recent_developments",
                    title="Recent developments",
                    status="available",
                    text="Recent text.",
                    source_finding_ids=("recent:r1",),
                ),
            ),
            evidence=(
                SimpleNamespace(
                    evidence_id="news:e1",
                    short_evidence_id="news:e1",
                    source_finding_ids=("recent:r1",),
                    metadata_status="ready",
                    source_label="Alpaca/Benzinga news",
                    symbols=("AAPL",),
                    evidence_date="2026-08-30",
                    source_domain="www.benzinga.com",
                    source_url="https://www.benzinga.com/news/example",
                    source_business_id="101",
                    section_label=None,
                    retrieval_rank=1,
                    chunk_index=2,
                ),
            ),
            companies=(),
            market_history=(),
            limitations=(),
            market_window_sessions=60,
        )

        self.assertTrue(
            app_module._databricks_app_resources_available(
                environment
            )
        )

        with (
            patch.dict(
                app_module.os.environ,
                environment,
                clear=True,
            ),
            patch.object(
                app_module.DatabricksAppRuntimeConfig,
                "from_environment",
                return_value=object(),
            ) as config_loader,
            patch(
                "app.DatabricksAppResearchRuntime",
                return_value=object(),
            ) as runtime_factory,
            patch(
                "app.run_app_research",
                return_value=session,
            ) as research_runner,
            patch(
                "app.build_app_research_presentation",
                return_value=presentation,
            ) as presenter,
        ):
            result = app_module.run_research_action(
                1,
                "AAPL",
                "MSFT",
                60,
            )

        config_loader.assert_called_once_with()
        runtime_factory.assert_called_once()
        research_runner.assert_called_once()
        presenter.assert_called_once_with(
            session
        )
        self.assertEqual(
            len(result),
            6,
        )
        self.assertEqual(
            result[0],
            (
                "Research complete: mode=comparison; symbols=AAPL,MSFT; "
                "status=ready; synthesis_mode=model; sections=2; evidence=1."
            ),
        )
        self.assertIsInstance(
            result[1],
            list,
        )
        self.assertIsNotNone(
            result[2],
        )
        self.assertIsNotNone(
            result[3],
        )
        self.assertIsNotNone(
            result[4],
        )
        self.assertIsNotNone(
            result[5],
        )

    def test_evidence_card_renders_publication_safe_metadata(self) -> None:
        item = SimpleNamespace(
            evidence_id="a" * 64,
            short_evidence_id=("a" * 12) + "…",
            source_finding_ids=("recent:r1",),
            metadata_status="ready",
            source_label="Alpaca/Benzinga news",
            symbols=("AAPL",),
            evidence_date="2026-08-30",
            source_domain="www.benzinga.com",
            source_url="https://www.benzinga.com/news/example",
            source_business_id="101",
            section_label=None,
            retrieval_rank=1,
            chunk_index=2,
        )

        card = app_module._evidence_card(
            item
        )
        rendered = repr(
            card
        )

        self.assertIn(
            "Alpaca/Benzinga news",
            rendered,
        )
        self.assertIn(
            "www.benzinga.com",
            rendered,
        )
        self.assertIn(
            "retrieval rank 1",
            rendered,
        )
        self.assertIn(
            "Open source",
            rendered,
        )
        self.assertNotIn(
            "Synthetic licensed article text",
            rendered,
        )

    def test_market_history_panel_renders_normalized_plot(self) -> None:
        presentation = SimpleNamespace(
            market_window_sessions=5,
            market_history=(
                SimpleNamespace(
                    symbol="AAPL",
                    display_name="Apple Inc.",
                    status="ready",
                    limitation=None,
                    points=(
                        SimpleNamespace(
                            trading_date="2026-09-01",
                            indexed_close=100.0,
                        ),
                        SimpleNamespace(
                            trading_date="2026-09-04",
                            indexed_close=104.25,
                        ),
                    ),
                ),
                SimpleNamespace(
                    symbol="MSFT",
                    display_name="Microsoft Corporation",
                    status="ready",
                    limitation=None,
                    points=(
                        SimpleNamespace(
                            trading_date="2026-09-01",
                            indexed_close=100.0,
                        ),
                        SimpleNamespace(
                            trading_date="2026-09-04",
                            indexed_close=98.5,
                        ),
                    ),
                ),
            ),
        )

        panel = app_module._market_history_panel(
            presentation
        )
        graph = next(
            child
            for child in panel.children
            if isinstance(child, dcc.Graph)
        )

        self.assertEqual(
            len(graph.figure.data),
            2,
        )
        self.assertEqual(
            tuple(graph.figure.data[0].y),
            (100.0, 104.25),
        )
        self.assertEqual(
            tuple(graph.figure.data[1].y),
            (100.0, 98.5),
        )
        self.assertIn(
            "5-session normalized",
            graph.figure.layout.title.text,
        )




if __name__ == "__main__":
    unittest.main()
