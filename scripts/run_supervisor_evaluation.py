"""Run live MLflow GenAI evaluation for contract cases E1-E3."""

from __future__ import annotations

import argparse
import itertools
import os
import sys
import time
from pathlib import Path

import mlflow
from mlflow.entities import SpanType
from mlflow.genai.datasets import get_dataset


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from equity_research.config import load_equities  # noqa: E402
from equity_research.mlflow_evaluation import (  # noqa: E402
    build_evaluation_scorers,
    build_live_evaluation_data,
    build_scope_rejection_scorers,
    require_managed_evaluation_dataset_runtime,
    serialize_scope_rejection_for_evaluation,
    serialize_supervisor_report_for_evaluation,
)
from equity_research.mlflow_tracing import (  # noqa: E402
    MlflowTracingConfig,
    configure_mlflow_tracing,
)
from equity_research.supervisor_research_graph import (  # noqa: E402
    run_supervisor_research_graph,
)
from equity_research.supervisor_report_runtime import (  # noqa: E402
    run_supervisor_report_synthesis,
)
from equity_research.supervisor_worker_runtime import (  # noqa: E402
    DatabricksSupervisorWorkers,
    SupervisorWorkerRuntimeConfig,
)
from equity_research.tool_scope import ControlledToolRequestError  # noqa: E402


DEFAULT_CATALOG = "workspace"
DEFAULT_EXPERIMENT = "/Shared/equity-research-genai-evaluation"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate the live controlled equity-research graph with MLflow "
            "code-based scorers and optional Databricks LLM-as-judge scorers."
        )
    )
    parser.add_argument(
        "--warehouse-id",
        default=None,
        help=(
            "Databricks SQL warehouse ID. Required for report cases E1/E2 "
            "and managed report datasets; intentionally not required for E3."
        ),
    )
    parser.add_argument(
        "--profile",
        default=None,
        help="Optional Databricks CLI profile.",
    )
    parser.add_argument(
        "--catalog",
        default=DEFAULT_CATALOG,
        help="Databricks catalog containing the physical Gold schema.",
    )
    parser.add_argument(
        "--gold-schema",
        default=None,
        help=(
            "Physical Gold schema name. Required for report cases E1/E2 "
            "and managed report datasets; intentionally not required for E3."
        ),
    )
    parser.add_argument(
        "--index-name",
        default=None,
        help=(
            "Fully qualified physical Vector Search index name. Required for "
            "report cases E1/E2 and managed report datasets; not required for E3."
        ),
    )
    parser.add_argument(
        "--case",
        nargs="+",
        default=None,
        help=(
            "Repository-owned contract case IDs to evaluate when "
            "--dataset-name is omitted. Defaults to E1."
        ),
    )
    parser.add_argument(
        "--dataset-name",
        default=None,
        help=(
            "Optional fully qualified Unity Catalog MLflow Evaluation Dataset. "
            "When supplied, the managed dataset is evaluated directly."
        ),
    )
    parser.add_argument(
        "--mlflow-experiment",
        default=DEFAULT_EXPERIMENT,
        help="Databricks MLflow experiment path for traces and evaluation runs.",
    )
    parser.add_argument(
        "--environment",
        default="dev",
        help="Environment tag for MLflow traces.",
    )
    parser.add_argument(
        "--retrieval-results-per-symbol",
        type=int,
        default=5,
        help="Controlled HYBRID results retrieved independently per symbol/topic.",
    )
    parser.add_argument(
        "--include-llm-judges",
        action="store_true",
        help=(
            "Add Databricks RelevanceToQuery, Safety, and domain Guidelines "
            "LLM judges. Omit for deterministic code scorers only."
        ),
    )
    parser.add_argument(
        "--judge-model",
        default="databricks:/databricks-gpt-oss-120b",
        help=(
            "MLflow judge model URI. Defaults to the Databricks-hosted "
            "databricks-gpt-oss-120b serving model."
        ),
    )
    parser.add_argument(
        "--skip-trace-validation",
        action="store_true",
        help=(
            "Skip MLflow's extra first-sample prediction used only to validate "
            "trace shape. Use after the evaluation predict path has already "
            "been proven live."
        ),
    )
    parser.add_argument(
        "--llm-judge",
        nargs="+",
        default=None,
        help=(
            "Optional LLM judge names to run when --include-llm-judges is set. "
            "If omitted, all configured LLM judges run."
        ),
    )
    parser.add_argument(
        "--eval-max-workers",
        type=int,
        default=2,
        help="Maximum concurrent evaluation rows. Defaults to 2.",
    )
    parser.add_argument(
        "--eval-max-scorer-workers",
        type=int,
        default=2,
        help="Maximum concurrent scorers per evaluation row. Defaults to 2.",
    )
    parser.add_argument(
        "--llm-judge-timeout-seconds",
        type=int,
        default=90,
        help="Timeout for each MLflow LLM judge call. Defaults to 90 seconds.",
    )
    parser.add_argument(
        "--eval-max-retries",
        type=int,
        default=1,
        help="Maximum MLflow evaluation retries after rate limits. Defaults to 1.",
    )

    return parser.parse_args()


def _required_report_resource(
    value: str | None,
    flag: str,
) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(
            f"{flag} is required for report evaluation cases."
        )

    return value.strip()


def main() -> None:
    args = parse_args()

    if args.skip_trace_validation:
        os.environ[
            "MLFLOW_GENAI_EVAL_SKIP_TRACE_VALIDATION"
        ] = "True"

    for value, field in (
        (args.eval_max_workers, "--eval-max-workers"),
        (args.eval_max_scorer_workers, "--eval-max-scorer-workers"),
        (args.llm_judge_timeout_seconds, "--llm-judge-timeout-seconds"),
    ):
        if value < 1:
            raise ValueError(
                f"{field} must be at least 1."
            )

    if args.eval_max_retries < 0:
        raise ValueError(
            "--eval-max-retries must be nonnegative."
        )

    os.environ[
        "MLFLOW_GENAI_EVAL_MAX_WORKERS"
    ] = str(
        args.eval_max_workers
    )
    os.environ[
        "MLFLOW_GENAI_EVAL_MAX_SCORER_WORKERS"
    ] = str(
        args.eval_max_scorer_workers
    )
    os.environ[
        "MLFLOW_GENAI_EVAL_LLM_TIMEOUT"
    ] = str(
        args.llm_judge_timeout_seconds
    )
    os.environ[
        "MLFLOW_GENAI_EVAL_MAX_RETRIES"
    ] = str(
        args.eval_max_retries
    )

    experiment_name = args.mlflow_experiment.strip()
    if not experiment_name:
        raise ValueError(
            "--mlflow-experiment must be nonblank."
        )

    dataset_name = (
        args.dataset_name.strip()
        if isinstance(args.dataset_name, str)
        and args.dataset_name.strip()
        else None
    )

    if dataset_name is not None:
        evaluation_kind = "report"
        require_managed_evaluation_dataset_runtime()
        data = get_dataset(
            name=dataset_name
        )
        data_source = (
            f"managed_dataset:{dataset_name}"
        )
        case_label = "managed"
    else:
        case_ids = (
            args.case
            if args.case is not None
            else ["E1"]
        )
        normalized_case_ids = tuple(
            str(case).strip().upper()
            for case in case_ids
        )

        if "E3" in normalized_case_ids and normalized_case_ids != ("E3",):
            raise ValueError(
                "E3 must be evaluated separately because it uses the "
                "pre-tool scope-rejection scorer contract."
            )

        evaluation_kind = (
            "scope_rejection"
            if normalized_case_ids == ("E3",)
            else "report"
        )

        if (
            evaluation_kind == "scope_rejection"
            and args.include_llm_judges
        ):
            raise ValueError(
                "E3 is a deterministic pre-tool rejection case and must not "
                "run LLM judges."
            )

        data = build_live_evaluation_data(
            case_ids
        )
        data_source = "repository_cases"
        case_label = ",".join(
            normalized_case_ids
        )

    equities = load_equities()
    workers = None

    if evaluation_kind == "report":
        runtime_config = SupervisorWorkerRuntimeConfig(
            warehouse_id=_required_report_resource(
                args.warehouse_id,
                "--warehouse-id",
            ),
            gold_schema=_required_report_resource(
                args.gold_schema,
                "--gold-schema",
            ),
            index_name=_required_report_resource(
                args.index_name,
                "--index-name",
            ),
            profile=args.profile,
            catalog=args.catalog,
            retrieval_results_per_symbol=args.retrieval_results_per_symbol,
        )
        workers = DatabricksSupervisorWorkers(
            config=runtime_config,
            equities=equities,
        )

    tracing_config = MlflowTracingConfig(
        experiment_name=experiment_name,
        profile=args.profile,
        environment=args.environment,
    )
    tracking_uri = configure_mlflow_tracing(
        tracing_config
    )

    predict_calls = itertools.count(
        1
    )

    def predict_fn(
        request_text: str,
        requested_symbols: list[str],
    ):
        call_number = next(
            predict_calls
        )
        started_at = time.monotonic()
        symbol_label = ",".join(
            requested_symbols
        )
        downstream_calls = {
            "market_worker": 0,
            "company_worker": 0,
            "report_synthesizer": 0,
        }

        print(
            "SUPERVISOR_EVAL_PREDICT_START"
            f"; call={call_number}"
            f"; symbols={symbol_label}",
            flush=True,
        )

        def counted_market_worker(*, request):
            downstream_calls[
                "market_worker"
            ] += 1
            if workers is None:
                raise RuntimeError(
                    "E3 scope rejection reached the Market Analyst boundary."
                )
            return workers.market_worker(
                request=request
            )

        def counted_company_worker(*, request, topic):
            downstream_calls[
                "company_worker"
            ] += 1
            if workers is None:
                raise RuntimeError(
                    "E3 scope rejection reached the Company Researcher boundary."
                )
            return workers.company_worker(
                request=request,
                topic=topic,
            )

        def counted_report_synthesizer(*, state):
            downstream_calls[
                "report_synthesizer"
            ] += 1
            if evaluation_kind == "scope_rejection":
                raise RuntimeError(
                    "E3 scope rejection reached final report synthesis."
                )
            return run_supervisor_report_synthesis(
                state=state,
                profile=args.profile,
            )

        try:
            if evaluation_kind == "scope_rejection":
                with mlflow.start_span(
                    name="supervisor_scope_validation",
                    span_type=SpanType.AGENT,
                ) as scope_span:
                    scope_span.set_inputs(
                        {
                            "requested_symbols": [
                                symbol.strip().upper()
                                for symbol in requested_symbols
                            ],
                            "supported_symbols": sorted(
                                equities
                            ),
                        }
                    )
                    scope_span.set_attributes(
                        {
                            "equity_research.component": "scope_validation",
                            "equity_research.request_mode": "unsupported_scope",
                        }
                    )

                    try:
                        run_supervisor_research_graph(
                            request_text=request_text,
                            requested_symbols=tuple(
                                requested_symbols
                            ),
                            market_worker=counted_market_worker,
                            company_worker=counted_company_worker,
                            report_synthesizer=counted_report_synthesizer,
                            equities=equities,
                        )
                    except ControlledToolRequestError as exc:
                        output = serialize_scope_rejection_for_evaluation(
                            requested_symbols=requested_symbols,
                            supported_symbols=tuple(
                                equities
                            ),
                            error=exc,
                            downstream_calls=downstream_calls,
                        )
                        scope_span.set_attributes(
                            {
                                "equity_research.rejection_reason": (
                                    output["reason_code"]
                                ),
                                "equity_research.unsupported_symbol_count": len(
                                    output["unsupported_symbols"]
                                ),
                            }
                        )
                        scope_span.set_outputs(
                            {
                                "outcome": output["outcome"],
                                "reason_code": output["reason_code"],
                                "unsupported_symbols": output[
                                    "unsupported_symbols"
                                ],
                                "downstream_calls": output[
                                    "downstream_calls"
                                ],
                            }
                        )
                        return output

                    raise RuntimeError(
                        "E3 unexpectedly completed the research graph."
                    )

            result = run_supervisor_research_graph(
                request_text=request_text,
                requested_symbols=tuple(
                    requested_symbols
                ),
                market_worker=counted_market_worker,
                company_worker=counted_company_worker,
                report_synthesizer=counted_report_synthesizer,
                equities=equities,
            )

            return serialize_supervisor_report_for_evaluation(
                result.report
            )
        finally:
            elapsed = (
                time.monotonic()
                - started_at
            )
            print(
                "SUPERVISOR_EVAL_PREDICT_END"
                f"; call={call_number}"
                f"; symbols={symbol_label}"
                f"; elapsed_seconds={elapsed:.1f}",
                flush=True,
            )

    if evaluation_kind == "scope_rejection":
        scorers = build_scope_rejection_scorers()
    else:
        scorers = build_evaluation_scorers(
            include_llm_judges=args.include_llm_judges,
            judge_model=args.judge_model,
        )

    if args.llm_judge is not None:
        if evaluation_kind == "scope_rejection":
            raise ValueError(
                "--llm-judge is not applicable to deterministic E3."
            )

        if not args.include_llm_judges:
            raise ValueError(
                "--llm-judge requires --include-llm-judges."
            )

        requested_judges = {
            name.strip()
            for name in args.llm_judge
            if isinstance(name, str)
            and name.strip()
        }
        if not requested_judges:
            raise ValueError(
                "--llm-judge requires at least one nonblank judge name."
            )

        code_names = {
            "expected_request_mode",
            "expected_symbol_scope",
            "required_report_sections",
            "report_section_grounding_contract",
            "synthesis_mode",
            "report_status",
            "evidence_count",
        }
        available_judges = {
            scorer.name
            for scorer in scorers
            if scorer.name not in code_names
        }
        unknown_judges = sorted(
            requested_judges
            - available_judges
        )

        if unknown_judges:
            raise ValueError(
                "Unknown LLM judge names: "
                f"{unknown_judges}. Available: "
                f"{sorted(available_judges)}."
            )

        scorers = [
            scorer
            for scorer in scorers
            if (
                scorer.name in code_names
                or scorer.name in requested_judges
            )
        ]

    print(
        "MLFLOW_EVALUATION_START"
        f"; tracking_uri={tracking_uri}"
        f"; experiment={experiment_name}"
        f"; cases={case_label}"
        f"; data_source={data_source}"
        f"; evaluation_kind={evaluation_kind}"
        f"; llm_judges={str(args.include_llm_judges).lower()}"
        f"; skip_trace_validation={str(args.skip_trace_validation).lower()}"
        f"; eval_max_workers={args.eval_max_workers}"
        f"; eval_max_scorer_workers={args.eval_max_scorer_workers}"
        f"; llm_judge_timeout_seconds={args.llm_judge_timeout_seconds}"
        f"; eval_max_retries={args.eval_max_retries}"
        f"; scorers={','.join(scorer.name for scorer in scorers)}"
    )

    result = mlflow.genai.evaluate(
        data=data,
        predict_fn=predict_fn,
        scorers=scorers,
    )

    print(
        "MLFLOW_EVALUATION=PASSED"
        f"; run_id={result.run_id}"
    )

    metrics = getattr(
        result,
        "metrics",
        None,
    )

    if isinstance(metrics, dict):
        for name in sorted(
            metrics
        ):
            print(
                "EVAL_METRIC"
                f"; name={name}"
                f"; value={metrics[name]}"
            )


if __name__ == "__main__":
    main()
