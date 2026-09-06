"""Run live MLflow GenAI evaluation for contract cases E1 and E2."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import mlflow
from mlflow.genai.datasets import get_dataset


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from equity_research.config import load_equities  # noqa: E402
from equity_research.mlflow_evaluation import (  # noqa: E402
    build_evaluation_scorers,
    build_live_evaluation_data,
    require_managed_evaluation_dataset_runtime,
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
        required=True,
        help="Databricks SQL warehouse ID.",
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
        required=True,
        help="Physical Gold schema name in the target workspace.",
    )
    parser.add_argument(
        "--index-name",
        required=True,
        help="Fully qualified physical Vector Search index name.",
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

    return parser.parse_args()


def main() -> None:
    args = parse_args()
    experiment_name = args.mlflow_experiment.strip()
    if not experiment_name:
        raise ValueError(
            "--mlflow-experiment must be nonblank."
        )

    equities = load_equities()
    runtime_config = SupervisorWorkerRuntimeConfig(
        warehouse_id=args.warehouse_id,
        gold_schema=args.gold_schema,
        index_name=args.index_name,
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

    def report_synthesizer(*, state):
        return run_supervisor_report_synthesis(
            state=state,
            profile=args.profile,
        )

    def predict_fn(
        request_text: str,
        requested_symbols: list[str],
    ):
        result = run_supervisor_research_graph(
            request_text=request_text,
            requested_symbols=tuple(
                requested_symbols
            ),
            market_worker=workers.market_worker,
            company_worker=workers.company_worker,
            report_synthesizer=report_synthesizer,
            equities=equities,
        )

        return serialize_supervisor_report_for_evaluation(
            result.report
        )

    dataset_name = (
        args.dataset_name.strip()
        if isinstance(args.dataset_name, str)
        and args.dataset_name.strip()
        else None
    )

    if dataset_name is not None:
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
        data = build_live_evaluation_data(
            case_ids
        )
        data_source = "repository_cases"
        case_label = ",".join(
            case.upper()
            for case in case_ids
        )

    scorers = build_evaluation_scorers(
        include_llm_judges=args.include_llm_judges,
        judge_model=args.judge_model,
    )

    print(
        "MLFLOW_EVALUATION_START"
        f"; tracking_uri={tracking_uri}"
        f"; experiment={experiment_name}"
        f"; cases={case_label}"
        f"; data_source={data_source}"
        f"; llm_judges={str(args.include_llm_judges).lower()}"
        f"; scorers={','.join(scorer.name for scorer in scorers)}"
    )

    # MLflow 3.16 uses the active experiment selected above by
    # configure_mlflow_tracing(); mlflow.genai.evaluate() does not accept an
    # experiment_name keyword in this pinned API.
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
