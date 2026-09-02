"""Offline tests for shared Alpaca HTTP retry policy."""

import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from equity_research.alpaca_http import (  # noqa: E402
    calculate_retry_delay,
    is_retryable_http_status,
)


class AlpacaRetryPolicyTests(unittest.TestCase):
    """Verify bounded Alpaca retry classification and delay calculations."""

    def test_classifies_temporary_http_failures(self) -> None:
        """Retry rate limits, timeouts, and selected server failures."""

        for status in (408, 429, 500, 502, 503, 504):
            with self.subTest(status=status):
                self.assertTrue(is_retryable_http_status(status))

        for status in (400, 401, 403, 404):
            with self.subTest(status=status):
                self.assertFalse(is_retryable_http_status(status))

    def test_calculates_exponential_backoff(self) -> None:
        """Increase delays predictably for consecutive failed attempts."""

        self.assertEqual(calculate_retry_delay(1), 1.0)
        self.assertEqual(calculate_retry_delay(2), 2.0)
        self.assertEqual(calculate_retry_delay(3), 4.0)

    def test_respects_bounded_numeric_retry_after(self) -> None:
        """Honor numeric server guidance without exceeding the delay cap."""

        self.assertEqual(calculate_retry_delay(1, "5"), 5.0)
        self.assertEqual(calculate_retry_delay(1, "100"), 30.0)
        self.assertEqual(calculate_retry_delay(1, "invalid"), 1.0)

    def test_rejects_invalid_retry_policy_inputs(self) -> None:
        """Reject invalid attempts, status codes, and delay boundaries."""

        with self.assertRaises(ValueError):
            calculate_retry_delay(0)

        with self.assertRaises(ValueError):
            calculate_retry_delay(1, base_delay_seconds=0)

        with self.assertRaises(ValueError):
            calculate_retry_delay(
                1,
                base_delay_seconds=2,
                max_delay_seconds=1,
            )

        with self.assertRaises(ValueError):
            is_retryable_http_status(99)


if __name__ == "__main__":
    unittest.main()
