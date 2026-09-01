"""Offline tests for the shared equities configuration."""

import json
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from equity_research.config import (  # noqa: E402
    ConfigurationError,
    load_equities,
)


def _base_payload() -> dict:
    """Return a fresh, valid two-equity test fixture."""

    return {
        "equities": [
            {
                "symbol": "AAPL",
                "display_name": "Apple Inc.",
                "alpaca_symbol": "AAPL",
                "sec_cik": "0000320193",
            },
            {
                "symbol": "MSFT",
                "display_name": "Microsoft Corporation",
                "alpaca_symbol": "MSFT",
                "sec_cik": "0000789019",
            },
        ]
    }


def _load_temporary(payload: dict):
    """Write a fixture to a temporary JSON file and load it."""

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "equities.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return load_equities(path)


class EquityConfigurationTests(unittest.TestCase):
    """Verify valid, invalid, and expandable equity configurations."""

    def test_loads_project_configuration(self) -> None:
        """Load the real AAPL and MSFT project configuration."""

        equities = load_equities()

        self.assertEqual(set(equities), {"AAPL", "MSFT"})
        self.assertEqual(equities["AAPL"].sec_cik, "0000320193")
        self.assertEqual(equities["MSFT"].alpaca_symbol, "MSFT")

    def test_rejects_duplicate_project_symbol(self) -> None:
        """Reject duplicate canonical symbols before pipeline processing."""

        payload = _base_payload()
        payload["equities"].append(
            dict(payload["equities"][0])
        )

        with self.assertRaisesRegex(
            ConfigurationError,
            "Duplicate project symbol",
        ):
            _load_temporary(payload)

    def test_rejects_invalid_sec_cik(self) -> None:
        """Reject an SEC CIK that is not normalized to ten digits."""

        payload = _base_payload()
        payload["equities"][0]["sec_cik"] = "320193"

        with self.assertRaisesRegex(
            ConfigurationError,
            "exactly 10 ASCII digits",
        ):
            _load_temporary(payload)

    def test_accepts_third_equity_fixture(self) -> None:
        """Accept another valid equity without changing loader code."""

        payload = _base_payload()
        payload["equities"].append(
            {
                "symbol": "TSLA",
                "display_name": "Tesla, Inc.",
                "alpaca_symbol": "TSLA",
                "sec_cik": "0001318605",
            }
        )

        equities = _load_temporary(payload)

        self.assertEqual(set(equities), {"AAPL", "MSFT", "TSLA"})
        self.assertEqual(equities["TSLA"].sec_cik, "0001318605")


if __name__ == "__main__":
    unittest.main()
