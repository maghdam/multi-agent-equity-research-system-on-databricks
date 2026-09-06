"""Thin Databricks CLI execution adapters for controlled tools."""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Callable


QUALIFIED_INDEX_PATTERN = re.compile(
    r"[A-Za-z_][A-Za-z0-9_]*"
    r"\.[A-Za-z_][A-Za-z0-9_]*"
    r"\.[A-Za-z_][A-Za-z0-9_]*"
)

TERMINAL_SQL_STATES = frozenset(
    {
        "SUCCEEDED",
        "FAILED",
        "CANCELED",
        "CLOSED",
    }
)
RUNNING_SQL_STATES = frozenset(
    {
        "PENDING",
        "RUNNING",
    }
)


class ControlledToolExecutionError(RuntimeError):
    """Raised when the Databricks execution layer cannot complete a tool call."""


def execute_statement_via_cli(
    *,
    payload: Mapping[str, Any],
    profile: str | None = None,
    max_polls: int = 12,
    poll_interval_seconds: float = 1.0,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Execute a Statement Execution request and poll until terminal."""

    if (
        isinstance(max_polls, bool)
        or not isinstance(max_polls, int)
        or max_polls < 0
    ):
        raise ControlledToolExecutionError(
            "max_polls must be a nonnegative integer."
        )

    if poll_interval_seconds < 0:
        raise ControlledToolExecutionError(
            "poll_interval_seconds must be nonnegative."
        )

    response = _api_post_json(
        path="/api/2.0/sql/statements",
        payload=payload,
        profile=profile,
        runner=runner,
    )

    for poll_number in range(max_polls + 1):
        state = _statement_state(response)

        if state == "SUCCEEDED":
            return response

        if state in TERMINAL_SQL_STATES:
            _raise_statement_failure(response)

        if state not in RUNNING_SQL_STATES:
            raise ControlledToolExecutionError(
                "Statement Execution returned an unknown state: "
                f"{state!r}."
            )

        if poll_number == max_polls:
            break

        statement_id = _required_text(
            response.get("statement_id"),
            "statement_id",
        )

        sleeper(poll_interval_seconds)

        response = _api_get_json(
            path=f"/api/2.0/sql/statements/{statement_id}",
            profile=profile,
            runner=runner,
        )

    raise ControlledToolExecutionError(
        "Statement Execution did not reach a terminal state "
        f"after {max_polls} poll(s)."
    )


def query_chat_completions_via_cli(
    *,
    payload: Mapping[str, Any],
    profile: str | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, Any]:
    """Execute one non-streaming Databricks Chat Completions request."""

    if not isinstance(payload, Mapping):
        raise ControlledToolExecutionError(
            "chat payload must be a mapping."
        )

    if payload.get("stream") is not False:
        raise ControlledToolExecutionError(
            "Controlled worker-agent chat requests must set stream=false."
        )

    return _api_post_json(
        path="/ai-gateway/mlflow/v1/chat/completions",
        payload=payload,
        profile=profile,
        runner=runner,
    )


def query_vector_index_via_cli(
    *,
    index_name: str,
    payload: Mapping[str, Any],
    profile: str | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, Any]:
    """Execute one controlled Vector Search request."""

    normalized_index = _required_text(
        index_name,
        "index_name",
    )

    if not QUALIFIED_INDEX_PATTERN.fullmatch(normalized_index):
        raise ControlledToolExecutionError(
            "index_name must be a fully qualified Databricks identifier."
        )

    return _api_post_json(
        path=(
            "/api/2.0/vector-search/indexes/"
            f"{normalized_index}/query"
        ),
        payload=payload,
        profile=profile,
        runner=runner,
    )


def _api_post_json(
    *,
    path: str,
    payload: Mapping[str, Any],
    profile: str | None,
    runner: Callable[..., subprocess.CompletedProcess[str]],
) -> dict[str, Any]:
    request_path = _write_json_payload(payload)

    try:
        command = [
            "databricks",
            "api",
            "post",
            path,
        ]

        if profile is not None:
            command.extend(
                [
                    "--profile",
                    _required_text(profile, "profile"),
                ]
            )

        command.extend(
            [
                "--json",
                f"@{request_path}",
            ]
        )

        return _run_json_command(
            command,
            runner=runner,
        )
    finally:
        request_path.unlink(missing_ok=True)


def _api_get_json(
    *,
    path: str,
    profile: str | None,
    runner: Callable[..., subprocess.CompletedProcess[str]],
) -> dict[str, Any]:
    command = [
        "databricks",
        "api",
        "get",
        path,
    ]

    if profile is not None:
        command.extend(
            [
                "--profile",
                _required_text(profile, "profile"),
            ]
        )

    return _run_json_command(
        command,
        runner=runner,
    )


def _run_json_command(
    command: list[str],
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]],
) -> dict[str, Any]:
    try:
        completed = runner(
            command,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        stderr = getattr(exc, "stderr", None)
        detail = (
            f"; stderr={stderr.strip()}"
            if isinstance(stderr, str) and stderr.strip()
            else ""
        )

        raise ControlledToolExecutionError(
            "Databricks CLI command failed"
            f"{detail}."
        ) from exc

    try:
        response = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ControlledToolExecutionError(
            "Databricks CLI returned invalid JSON."
        ) from exc

    if not isinstance(response, dict):
        raise ControlledToolExecutionError(
            "Databricks CLI JSON response must be an object."
        )

    return response


def _write_json_payload(
    payload: Mapping[str, Any],
) -> Path:
    if not isinstance(payload, Mapping):
        raise ControlledToolExecutionError(
            "payload must be a mapping."
        )

    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".json",
        encoding="utf-8",
        newline="\n",
        delete=False,
    ) as handle:
        json.dump(
            dict(payload),
            handle,
            ensure_ascii=False,
        )
        return Path(handle.name)


def _statement_state(
    response: Mapping[str, Any],
) -> str:
    status = response.get("status")

    if not isinstance(status, Mapping):
        raise ControlledToolExecutionError(
            "Statement Execution response is missing status."
        )

    return _required_text(
        status.get("state"),
        "statement state",
    )


def _raise_statement_failure(
    response: Mapping[str, Any],
) -> None:
    state = _statement_state(response)
    status = response["status"]
    assert isinstance(status, Mapping)

    error = status.get("error")
    detail = ""

    if isinstance(error, Mapping):
        code = error.get("error_code")
        message = error.get("message")
        sql_state = error.get("sql_state")
        detail = (
            f"; error_code={code}"
            f"; sql_state={sql_state}"
            f"; message={message}"
        )

    raise ControlledToolExecutionError(
        f"Statement Execution ended in state={state}{detail}."
    )


def _required_text(
    value: object,
    field: str,
) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ControlledToolExecutionError(
            f"{field} must be a nonblank string."
        )

    return value.strip()
