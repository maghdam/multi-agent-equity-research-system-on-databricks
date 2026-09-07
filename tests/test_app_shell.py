from __future__ import annotations

import sys
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
