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

        self.assertIn(
            "Valid local preview",
            result,
        )
        self.assertIn(
            "mode=comparison",
            result,
        )
        self.assertIn(
            "symbols=AAPL,MSFT",
            result,
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
        report = SimpleNamespace(
            mode="comparison",
            symbols=("AAPL", "MSFT"),
            status="ready",
            synthesis_mode="model",
            sections=(object(), object()),
            evidence=(object(),),
        )
        session = SimpleNamespace(
            research=SimpleNamespace(
                report=report,
            )
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
        self.assertEqual(
            result,
            (
                "Research complete: mode=comparison; symbols=AAPL,MSFT; "
                "status=ready; synthesis_mode=model; sections=2; evidence=1."
            ),
        )



if __name__ == "__main__":
    unittest.main()
