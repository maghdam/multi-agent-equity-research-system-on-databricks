"""Privacy-safe MLflow spans for controlled tools and model calls."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import contextmanager
from typing import Any, Iterator

import mlflow
from mlflow.entities import Span, SpanType


@contextmanager
def optional_mlflow_span(
    *,
    name: str,
    span_type: SpanType | str,
) -> Iterator[Span | None]:
    """Create a child span only when an application trace is already active."""

    if not isinstance(name, str) or not name.strip():
        raise ValueError(
            "name must be a nonblank string."
        )

    if mlflow.get_current_active_span() is None:
        yield None
        return

    with mlflow.start_span(
        name=name.strip(),
        span_type=span_type,
    ) as span:
        yield span


def run_traced_chat_completion(
    *,
    span_name: str,
    component: str,
    attempt: str,
    payload: Mapping[str, Any],
    profile: str | None,
    model_query: Callable[..., Mapping[str, Any]],
    safe_inputs: Mapping[str, Any] | None = None,
    safe_attributes: Mapping[str, Any] | None = None,
) -> Mapping[str, Any]:
    """Run one chat completion inside a privacy-safe CHAT_MODEL span."""

    if not callable(model_query):
        raise TypeError(
            "model_query must be callable."
        )

    model = payload.get(
        "model"
    )
    if not isinstance(model, str) or not model.strip():
        raise ValueError(
            "payload.model must be a nonblank string."
        )

    if not isinstance(component, str) or not component.strip():
        raise ValueError(
            "component must be a nonblank string."
        )

    if not isinstance(attempt, str) or not attempt.strip():
        raise ValueError(
            "attempt must be a nonblank string."
        )

    with optional_mlflow_span(
        name=span_name,
        span_type=SpanType.CHAT_MODEL,
    ) as span:
        if span is not None:
            inputs = {
                "component": component.strip(),
                "attempt": attempt.strip(),
                "model": model.strip(),
            }
            if safe_inputs is not None:
                inputs.update(
                    dict(safe_inputs)
                )

            attributes = {
                "mlflow.llm.model": model.strip(),
                "mlflow.llm.provider": "databricks",
                "equity_research.component": component.strip(),
                "equity_research.attempt": attempt.strip(),
            }
            if safe_attributes is not None:
                attributes.update(
                    dict(safe_attributes)
                )

            span.set_inputs(
                inputs
            )
            span.set_attributes(
                attributes
            )

        response = model_query(
            payload=dict(payload),
            profile=profile,
        )

        if span is not None:
            token_usage = extract_chat_token_usage(
                response
            )
            if token_usage is not None:
                span.set_attribute(
                    "mlflow.chat.tokenUsage",
                    token_usage,
                )

            span.set_outputs(
                {
                    "finish_reason": _finish_reason(
                        response
                    ),
                    "token_usage_available": (
                        token_usage is not None
                    ),
                }
            )

        return response


def extract_chat_token_usage(
    response: Mapping[str, Any],
) -> dict[str, int] | None:
    """Map authoritative chat-completion usage fields to MLflow token usage."""

    if not isinstance(response, Mapping):
        return None

    usage = response.get(
        "usage"
    )
    if not isinstance(usage, Mapping):
        return None

    input_tokens = _usage_int(
        usage,
        "prompt_tokens",
        "input_tokens",
    )
    output_tokens = _usage_int(
        usage,
        "completion_tokens",
        "output_tokens",
    )
    total_tokens = _usage_int(
        usage,
        "total_tokens",
    )

    if (
        input_tokens is None
        or output_tokens is None
        or total_tokens is None
    ):
        return None

    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }


def _usage_int(
    usage: Mapping[str, Any],
    *keys: str,
) -> int | None:
    for key in keys:
        value = usage.get(
            key
        )
        if (
            isinstance(value, int)
            and not isinstance(value, bool)
            and value >= 0
        ):
            return value

    return None


def _finish_reason(
    response: Mapping[str, Any],
) -> str | None:
    choices = response.get(
        "choices"
    )
    if not isinstance(choices, list) or not choices:
        return None

    first = choices[0]
    if not isinstance(first, Mapping):
        return None

    value = first.get(
        "finish_reason"
    )
    return (
        value
        if isinstance(value, str)
        else None
    )
