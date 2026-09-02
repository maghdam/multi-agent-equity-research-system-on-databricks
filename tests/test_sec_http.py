"""Offline tests for SEC HTTP access-policy and retry helpers."""

import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from equity_research.sec_http import (  # noqa: E402
    MIN_SEC_REQUEST_INTERVAL_SECONDS,
    build_sec_request_headers,
    calculate_sec_retry_delay,
    calculate_sec_spacing_delay,
    is_retryable_sec_http_status,
)


class SecRequestHeaderTests(unittest.TestCase):
    """Verify identified SEC request headers."""

    def test_builds_identified_json_request_headers(self) -> None:
        """Declare the automated client and accepted response format."""

        headers = build_sec_request_headers(
            "equity-research-system contact@example.com"
        )

        self.assertEqual(
            headers,
            {
                "User-Agent": (
                    "equity-research-system contact@example.com"
                ),
                "Accept": "application/json",
                "Accept-Encoding": "identity",
            },
        )

    def test_rejects_blank_user_agent(self) -> None:
        """Never send an undeclared automated SEC request."""

        with self.assertRaisesRegex(
            ValueError,
            "user_agent must be nonblank",
        ):
            build_sec_request_headers("  ")


class SecRetryPolicyTests(unittest.TestCase):
    """Verify bounded SEC retry behavior."""

    def test_classifies_temporary_http_failures(self) -> None:
        """Retry rate limits and selected temporary server failures."""

        for status in (429, 500, 502, 503, 504):
            with self.subTest(status=status):
                self.assertTrue(
                    is_retryable_sec_http_status(status)
                )

        for status in (400, 401, 403, 404):
            with self.subTest(status=status):
                self.assertFalse(
                    is_retryable_sec_http_status(status)
                )

    def test_calculates_exponential_backoff(self) -> None:
        """Increase delays predictably across consecutive failures."""

        self.assertEqual(calculate_sec_retry_delay(1), 1.0)
        self.assertEqual(calculate_sec_retry_delay(2), 2.0)
        self.assertEqual(calculate_sec_retry_delay(3), 4.0)

    def test_respects_bounded_retry_after(self) -> None:
        """Honor numeric server guidance without exceeding the cap."""

        self.assertEqual(
            calculate_sec_retry_delay(1, "5"),
            5.0,
        )
        self.assertEqual(
            calculate_sec_retry_delay(1, "100"),
            30.0,
        )
        self.assertEqual(
            calculate_sec_retry_delay(1, "invalid"),
            1.0,
        )

    def test_rejects_invalid_retry_inputs(self) -> None:
        """Reject malformed retry-policy parameters."""

        with self.assertRaises(ValueError):
            calculate_sec_retry_delay(0)

        with self.assertRaises(ValueError):
            calculate_sec_retry_delay(
                1,
                base_delay_seconds=0,
            )

        with self.assertRaises(ValueError):
            calculate_sec_retry_delay(
                1,
                base_delay_seconds=2,
                max_delay_seconds=1,
            )

        with self.assertRaises(ValueError):
            is_retryable_sec_http_status(99)


class SecRequestSpacingTests(unittest.TestCase):
    """Verify conservative SEC request pacing."""

    def test_returns_remaining_spacing_delay(self) -> None:
        """Delay only for the unelapsed part of the minimum interval."""

        self.assertAlmostEqual(
            calculate_sec_spacing_delay(0.05),
            MIN_SEC_REQUEST_INTERVAL_SECONDS - 0.05,
        )

        self.assertEqual(
            calculate_sec_spacing_delay(
                MIN_SEC_REQUEST_INTERVAL_SECONDS
            ),
            0.0,
        )

        self.assertEqual(
            calculate_sec_spacing_delay(1.0),
            0.0,
        )

    def test_rejects_invalid_spacing_inputs(self) -> None:
        """Reject negative elapsed time or invalid spacing limits."""

        with self.assertRaises(ValueError):
            calculate_sec_spacing_delay(-0.1)

        with self.assertRaises(ValueError):
            calculate_sec_spacing_delay(
                0.1,
                minimum_interval_seconds=0,
            )


if __name__ == "__main__":
    unittest.main()