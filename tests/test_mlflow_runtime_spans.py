"""Offline tests for privacy-safe MLflow runtime span helpers."""

import sys
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import Mock, patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from equity_research.mlflow_runtime_spans import (  # noqa: E402
    extract_chat_token_usage,
    run_traced_chat_completion,
)


def _payload():
    return {
        "model": "system.ai.gpt-oss-20b",
        "messages": [
            {
                "role": "user",
                "content": "private controlled context",
            }
        ],
    }


def _response():
    return {
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": "{}",
                },
            }
        ],
        "usage": {
            "prompt_tokens": 101,
            "completion_tokens": 23,
            "total_tokens": 124,
        },
    }


class MlflowRuntimeSpanTests(unittest.TestCase):
    @patch(
        "equity_research.mlflow_runtime_spans.mlflow.start_span"
    )
    @patch(
        "equity_research.mlflow_runtime_spans."
        "mlflow.get_current_active_span"
    )
    def test_model_query_without_active_trace_does_not_start_root_span(
        self,
        active_span,
        start_span,
    ) -> None:
        active_span.return_value = None
        model_query = Mock(
            return_value=_response()
        )

        response = run_traced_chat_completion(
            span_name="market_analyst_20b_initial",
            component="market_analyst",
            attempt="initial",
            payload=_payload(),
            profile="profile-1",
            model_query=model_query,
            safe_inputs={
                "symbols": ["AAPL"],
            },
        )

        self.assertEqual(
            response,
            _response(),
        )
        start_span.assert_not_called()
        model_query.assert_called_once_with(
            payload=_payload(),
            profile="profile-1",
        )

    @patch(
        "equity_research.mlflow_runtime_spans.mlflow.start_span"
    )
    @patch(
        "equity_research.mlflow_runtime_spans."
        "mlflow.get_current_active_span"
    )
    def test_chat_span_records_safe_scope_model_and_authoritative_usage(
        self,
        active_span,
        start_span,
    ) -> None:
        active_span.return_value = Mock()
        span = Mock()
        start_span.return_value = nullcontext(
            span
        )
        model_query = Mock(
            return_value=_response()
        )

        run_traced_chat_completion(
            span_name="company_researcher_20b",
            component="company_researcher",
            attempt="initial",
            payload=_payload(),
            profile="profile-1",
            model_query=model_query,
            safe_inputs={
                "symbols": ["AAPL"],
                "topic": "recent_developments",
                "evidence_count": 3,
            },
            safe_attributes={
                "equity_research.topic": "recent_developments",
            },
        )

        inputs = span.set_inputs.call_args.args[0]
        self.assertEqual(
            inputs,
            {
                "component": "company_researcher",
                "attempt": "initial",
                "model": "system.ai.gpt-oss-20b",
                "symbols": ["AAPL"],
                "topic": "recent_developments",
                "evidence_count": 3,
            },
        )
        self.assertNotIn(
            "messages",
            inputs,
        )
        self.assertNotIn(
            "private controlled context",
            str(inputs),
        )

        attributes = span.set_attributes.call_args.args[0]
        self.assertEqual(
            attributes["mlflow.llm.model"],
            "system.ai.gpt-oss-20b",
        )
        self.assertEqual(
            attributes["mlflow.llm.provider"],
            "databricks",
        )
        self.assertEqual(
            attributes["equity_research.attempt"],
            "initial",
        )
        span.set_attribute.assert_called_once_with(
            "mlflow.chat.tokenUsage",
            {
                "input_tokens": 101,
                "output_tokens": 23,
                "total_tokens": 124,
            },
        )
        span.set_outputs.assert_called_once_with(
            {
                "finish_reason": "stop",
                "token_usage_available": True,
            }
        )

    def test_token_usage_accepts_openai_and_normalized_field_names(self) -> None:
        self.assertEqual(
            extract_chat_token_usage(
                _response()
            ),
            {
                "input_tokens": 101,
                "output_tokens": 23,
                "total_tokens": 124,
            },
        )
        self.assertEqual(
            extract_chat_token_usage(
                {
                    "usage": {
                        "input_tokens": 7,
                        "output_tokens": 5,
                        "total_tokens": 12,
                    }
                }
            ),
            {
                "input_tokens": 7,
                "output_tokens": 5,
                "total_tokens": 12,
            },
        )

    def test_token_usage_is_omitted_when_provider_does_not_return_full_counts(
        self,
    ) -> None:
        self.assertIsNone(
            extract_chat_token_usage(
                {
                    "usage": {
                        "prompt_tokens": 7,
                    }
                }
            )
        )
        self.assertIsNone(
            extract_chat_token_usage(
                {
                    "usage": {
                        "prompt_tokens": True,
                        "completion_tokens": 3,
                        "total_tokens": 4,
                    }
                }
            )
        )


if __name__ == "__main__":
    unittest.main()
