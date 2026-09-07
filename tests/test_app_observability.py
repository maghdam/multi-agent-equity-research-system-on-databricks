from __future__ import annotations

import json
import logging
import sys
import unittest
from io import StringIO
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from equity_research.app_observability import (  # noqa: E402
    AppEvent,
    feedback_event,
    followup_event,
    log_app_event,
    research_event,
)


class AppObservabilityTests(unittest.TestCase):
    def test_research_event_contains_only_bounded_metadata(self) -> None:
        event = research_event(
            event_type="research_completed",
            mode="comparison",
            symbols=("AAPL", "MSFT"),
            market_window_sessions=60,
            duration_ms=1234,
            report_status="ready",
            synthesis_mode="model",
            evidence_count=12,
        )

        self.assertEqual(
            event.to_dict(),
            {
                "schema_version": 1,
                "event_type": "research_completed",
                "mode": "comparison",
                "symbols": ["AAPL", "MSFT"],
                "market_window_sessions": 60,
                "report_status": "ready",
                "synthesis_mode": "model",
                "evidence_count": 12,
                "duration_ms": 1234,
            },
        )

    def test_followup_event_does_not_accept_question_or_answer_text(self) -> None:
        event = followup_event(
            event_type="followup_completed",
            research={
                "mode": "comparison",
                "symbols": ["AAPL", "MSFT"],
                "market_window_sessions": 60,
            },
            duration_ms=842,
            question_length=31,
            turn_count=2,
            source_count=2,
            limitation_present=False,
        )
        payload = event.to_dict()
        serialized = json.dumps(
            payload
        )

        self.assertEqual(
            payload["question_length"],
            31,
        )
        self.assertNotIn(
            "question",
            payload,
        )
        self.assertNotIn(
            "answer",
            payload,
        )
        self.assertNotIn(
            "Apple",
            serialized,
        )

    def test_feedback_event_is_fixed_category_only(self) -> None:
        event = feedback_event(
            research={
                "mode": "single_company",
                "symbols": ["AAPL"],
                "market_window_sessions": 20,
                "report_status": "ready",
                "synthesis_mode": "model",
            },
            feedback="helpful",
        )

        self.assertEqual(
            event.feedback,
            "helpful",
        )

        with self.assertRaisesRegex(
            ValueError,
            "feedback",
        ):
            feedback_event(
                research={
                    "mode": "single_company",
                    "symbols": ["AAPL"],
                    "market_window_sessions": 20,
                    "report_status": "ready",
                    "synthesis_mode": "model",
                },
                feedback="free text feedback",
            )

    def test_json_log_line_has_stable_prefix(self) -> None:
        stream = StringIO()
        handler = logging.StreamHandler(
            stream
        )
        logger = logging.getLogger(
            "test.app.observability"
        )
        logger.handlers = [
            handler
        ]
        logger.setLevel(
            logging.INFO
        )
        logger.propagate = False

        log_app_event(
            logger,
            AppEvent(
                event_type="feedback_submitted",
                mode="single_company",
                symbols=("AAPL",),
                market_window_sessions=60,
                feedback="needs_work",
            ),
        )

        line = stream.getvalue().strip()

        self.assertTrue(
            line.startswith(
                "APP_EVENT "
            )
        )
        self.assertIn(
            '"feedback":"needs_work"',
            line,
        )


if __name__ == "__main__":
    unittest.main()
