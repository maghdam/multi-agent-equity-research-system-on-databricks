"""Dash shell for the Databricks equity-research application."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from dash import (
    Dash,
    Input,
    Output,
    State,
    clientside_callback,
    dcc,
    html,
    no_update,
)

PROJECT_ROOT = Path(__file__).resolve().parent
SRC_ROOT = PROJECT_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from equity_research.app_contracts import (  # noqa: E402
    SUPPORTED_MARKET_WINDOWS,
    build_app_research_selection,
    build_research_request_text,
    company_selector_options,
)
from equity_research.app_presenters import (  # noqa: E402
    build_app_research_presentation,
)
from equity_research.app_service import run_app_research  # noqa: E402
from equity_research.config import load_equities  # noqa: E402
from equity_research.databricks_app_runtime import (  # noqa: E402
    FUNDAMENTAL_METRICS_TABLE_ENV,
    MARKET_METRICS_TABLE_ENV,
    VECTOR_INDEX_ENV,
    WAREHOUSE_ENV,
    DatabricksAppResearchRuntime,
    DatabricksAppRuntimeConfig,
)
from equity_research.tool_scope import ControlledToolRequestError  # noqa: E402


equities = load_equities()
selector_options = company_selector_options(equities)
company_options = [
    {"label": option.label, "value": option.symbol}
    for option in selector_options
]
company_symbols = [option.symbol for option in selector_options]

primary_default = (
    "AAPL"
    if "AAPL" in company_symbols
    else company_symbols[0]
)
comparison_default = (
    "MSFT"
    if "MSFT" in company_symbols and "MSFT" != primary_default
    else ""
)

window_options = [
    {
        "label": (
            "1 trading session"
            if value == 1
            else f"{value} trading sessions"
        ),
        "value": value,
    }
    for value in SUPPORTED_MARKET_WINDOWS
]

logger = logging.getLogger(__name__)

app = Dash(__name__, title="Equity Research Workspace")
server = app.server


def placeholder_panel(title: str, body: str) -> html.Div:
    return html.Div(
        className="placeholder-panel",
        children=[
            html.H3(title, className="panel-title"),
            html.P(body, className="panel-copy"),
        ],
    )


app.layout = html.Div(
    id="app-shell",
    className="app-shell theme-light",
    children=[
        dcc.Store(
            id="theme-store",
            storage_type="local",
            data="light",
        ),
        html.Header(
            className="app-header",
            children=[
                html.Div(
                    className="header-row",
                    children=[
                        html.Div(
                            children=[
                                html.Div(
                                    "Multi-Agent Equity Research",
                                    className="eyebrow",
                                ),
                                html.H1(
                                    "Equity Research Workspace",
                                    className="app-title",
                                ),
                                html.P(
                                    (
                                        "Structured analytics, grounded evidence, "
                                        "multi-agent synthesis, and follow-up "
                                        "research."
                                    ),
                                    className="app-subtitle",
                                ),
                            ],
                        ),
                        html.Button(
                            "Dark mode",
                            id="theme-toggle",
                            n_clicks=0,
                            className="theme-toggle",
                            title="Switch color theme",
                        ),
                    ],
                ),
            ],
        ),
        html.Main(
            className="app-main",
            children=[
                html.Section(
                    className="research-controls card",
                    children=[
                        html.Div(
                            className="control-grid",
                            children=[
                                html.Div(
                                    className="control-field",
                                    children=[
                                        html.Label("Primary company"),
                                        dcc.Dropdown(
                                            id="primary-symbol",
                                            options=company_options,
                                            value=primary_default,
                                            searchable=True,
                                            clearable=False,
                                        ),
                                    ],
                                ),
                                html.Div(
                                    className="control-field",
                                    children=[
                                        html.Label("Compare with"),
                                        dcc.Dropdown(
                                            id="comparison-symbol",
                                            options=[
                                                {
                                                    "label": "No comparison",
                                                    "value": "",
                                                },
                                                *company_options,
                                            ],
                                            value=comparison_default,
                                            searchable=True,
                                            clearable=False,
                                        ),
                                    ],
                                ),
                                html.Div(
                                    className="control-field",
                                    children=[
                                        html.Label("Market window"),
                                        dcc.Dropdown(
                                            id="market-window",
                                            options=window_options,
                                            value=60,
                                            searchable=False,
                                            clearable=False,
                                        ),
                                    ],
                                ),
                                html.Button(
                                    "Run Research",
                                    id="run-research",
                                    n_clicks=0,
                                    className="primary-button",
                                ),
                            ],
                        ),
                        dcc.Loading(
                            type="circle",
                            children=html.Div(
                                id="selection-status",
                                className="selection-status",
                                children=(
                                    "The research workspace is ready. Local runs "
                                    "stay in preview mode unless Databricks App "
                                    "resources are available."
                                ),
                            ),
                        ),
                    ],
                ),
                dcc.Tabs(
                    value="overview",
                    className="research-tabs",
                    children=[
                        dcc.Tab(
                            className="research-tab",
                            selected_className="research-tab--selected",
                            label="Overview",
                            value="overview",
                            children=html.Div(
                                id="overview-content",
                                className="tab-grid",
                                children=[
                                    placeholder_panel(
                                        "Research snapshot",
                                        "Key market and fundamental metrics.",
                                    ),
                                    placeholder_panel(
                                        "Research summary",
                                        "Validated cited synthesis and limitations.",
                                    ),
                                ],
                            ),
                        ),
                        dcc.Tab(
                            className="research-tab",
                            selected_className="research-tab--selected",
                            label="Market",
                            value="market",
                            children=html.Div(
                                id="market-content",
                                children=placeholder_panel(
                                    "Market performance",
                                    (
                                        "Exact controlled Gold market metrics. "
                                        "Price-history charts are added in the "
                                        "next structured-data slice."
                                    ),
                                ),
                            ),
                        ),
                        dcc.Tab(
                            className="research-tab",
                            selected_className="research-tab--selected",
                            label="Fundamentals",
                            value="fundamentals",
                            children=html.Div(
                                id="fundamentals-content",
                                children=placeholder_panel(
                                    "Fundamental performance",
                                    (
                                        "Controlled fundamentals and comparison "
                                        "tables."
                                    ),
                                ),
                            ),
                        ),
                        dcc.Tab(
                            className="research-tab",
                            selected_className="research-tab--selected",
                            label="Research Report",
                            value="report",
                            children=html.Div(
                                id="report-content",
                                children=placeholder_panel(
                                    "Grounded cited report",
                                    (
                                        "Validated report sections, citations, "
                                        "and explicit limitations."
                                    ),
                                ),
                            ),
                        ),
                        dcc.Tab(
                            className="research-tab",
                            selected_className="research-tab--selected",
                            label="Evidence",
                            value="evidence",
                            children=html.Div(
                                id="evidence-content",
                                children=placeholder_panel(
                                    "Evidence and provenance",
                                    (
                                        "Validated citation IDs and source "
                                        "finding provenance."
                                    ),
                                ),
                            ),
                        ),
                    ],
                ),
                html.Section(
                    className="followup card",
                    children=[
                        html.Div("Follow-up research", className="eyebrow"),
                        html.H2(
                            "Ask about the active research",
                            className="section-title",
                        ),
                        html.P(
                            (
                                "Follow-up chat will reuse the validated research "
                                "session rather than become an unrestricted "
                                "general chatbot."
                            ),
                            className="section-copy",
                        ),
                        html.Div(
                            className="followup-row",
                            children=[
                                dcc.Input(
                                    id="followup-input",
                                    type="text",
                                    disabled=True,
                                    placeholder=(
                                        "Run research first, then ask a grounded "
                                        "follow-up question..."
                                    ),
                                    className="followup-input",
                                ),
                                html.Button(
                                    "Ask",
                                    disabled=True,
                                    className="secondary-button",
                                ),
                            ],
                        ),
                    ],
                ),
            ],
        ),
    ],
)


clientside_callback(
    """
    function(nClicks, currentTheme) {
        if (!nClicks) {
            return window.dash_clientside.no_update;
        }

        return currentTheme === "dark" ? "light" : "dark";
    }
    """,
    Output("theme-store", "data"),
    Input("theme-toggle", "n_clicks"),
    State("theme-store", "data"),
    prevent_initial_call=True,
)


clientside_callback(
    """
    function(theme) {
        const normalized = theme === "dark" ? "dark" : "light";
        const shellClass = "app-shell theme-" + normalized;
        const buttonLabel = normalized === "dark" ? "Light mode" : "Dark mode";

        return [shellClass, buttonLabel];
    }
    """,
    Output("app-shell", "className"),
    Output("theme-toggle", "children"),
    Input("theme-store", "data"),
)


@app.callback(
    Output("selection-status", "children"),
    Output("overview-content", "children"),
    Output("market-content", "children"),
    Output("fundamentals-content", "children"),
    Output("report-content", "children"),
    Output("evidence-content", "children"),
    Input("run-research", "n_clicks"),
    State("primary-symbol", "value"),
    State("comparison-symbol", "value"),
    State("market-window", "value"),
    prevent_initial_call=True,
)
def run_research_action(
    _n_clicks: int,
    primary_symbol: str,
    comparison_symbol: str,
    market_window: int,
) -> tuple:
    """Validate locally or run the real Databricks App research runtime."""

    try:
        selection = build_app_research_selection(
            primary_symbol=primary_symbol,
            comparison_symbol=comparison_symbol,
            market_window_sessions=market_window,
            equities=equities,
        )
    except (ControlledToolRequestError, ValueError) as exc:
        return (
            f"Selection error: {exc}",
            no_update,
            no_update,
            no_update,
            no_update,
            no_update,
        )

    if not _databricks_app_resources_available():
        request_text = build_research_request_text(
            selection,
            equities=equities,
        )
        return (
            (
                f"Valid local preview: mode={selection.mode}; "
                f"symbols={','.join(selection.requested_symbols)}; "
                f"market_window={selection.market_window_sessions}. "
                f"Supervisor request preview: {request_text}"
            ),
            no_update,
            no_update,
            no_update,
            no_update,
            no_update,
        )

    try:
        runtime = DatabricksAppResearchRuntime(
            config=DatabricksAppRuntimeConfig.from_environment(),
            equities=equities,
        )
        session = run_app_research(
            selection=selection,
            runtime=runtime,
            equities=equities,
        )
    except Exception as exc:
        logger.error(
            (
                "Research execution failed safely: mode=%s symbols=%s "
                "market_window=%s error_type=%s"
            ),
            selection.mode,
            ",".join(selection.requested_symbols),
            selection.market_window_sessions,
            type(exc).__name__,
        )
        return (
            (
                "Research execution failed safely. No partial result is shown. "
                "Check Databricks App logs and the configured workspace resources."
            ),
            no_update,
            no_update,
            no_update,
            no_update,
            no_update,
        )

    presentation = build_app_research_presentation(
        session
    )

    status = (
        f"Research complete: mode={presentation.mode}; "
        f"symbols={','.join(presentation.symbols)}; "
        f"status={presentation.report_status}; "
        f"synthesis_mode={presentation.synthesis_mode}; "
        f"sections={len(presentation.report_sections)}; "
        f"evidence={len(presentation.evidence)}."
    )

    return (
        status,
        _render_overview(presentation),
        _render_market(presentation),
        _render_fundamentals(presentation),
        _render_report(presentation),
        _render_evidence(presentation),
    )


def _metric_cards(
    metrics,
):
    return html.Div(
        className="metric-grid",
        children=[
            html.Div(
                className=(
                    "metric-card "
                    f"metric-card--{metric.status}"
                ),
                children=[
                    html.Div(
                        metric.label,
                        className="metric-label",
                    ),
                    html.Div(
                        metric.value,
                        className="metric-value",
                    ),
                ],
            )
            for metric in metrics
        ],
    )


def _render_overview(
    presentation,
):
    summary_section = next(
        (
            section
            for section in presentation.report_sections
            if section.section == "recent_developments"
        ),
        presentation.report_sections[0],
    )

    company_panels = [
        html.Div(
            className="placeholder-panel",
            children=[
                html.Div(
                    f"{company.display_name} ({company.symbol})",
                    className="eyebrow",
                ),
                html.H3(
                    "Research snapshot",
                    className="panel-title",
                ),
                html.P(
                    (
                        f"Market as of {company.market_as_of or 'unavailable'} · "
                        f"Fundamentals as of "
                        f"{company.fundamental_as_of or 'unavailable'}"
                    ),
                    className="panel-copy",
                ),
                _metric_cards(
                    (
                        *company.market_metrics[:2],
                        *company.fundamental_metrics[:3],
                    )
                ),
            ],
        )
        for company in presentation.companies
    ]

    summary = html.Div(
        className="placeholder-panel",
        children=[
            html.Div(
                presentation.report_status,
                className=(
                    "status-badge "
                    f"status-badge--{presentation.report_status}"
                ),
            ),
            html.H3(
                "Research summary",
                className="panel-title",
            ),
            html.P(
                summary_section.text,
                className="report-text",
            ),
            *(
                [
                    html.Div(
                        children=[
                            html.Strong("Limitations"),
                            html.Ul(
                                [
                                    html.Li(item)
                                    for item in presentation.limitations
                                ]
                            ),
                        ],
                        className="limitations-box",
                    )
                ]
                if presentation.limitations
                else []
            ),
        ],
    )

    return [
        *company_panels,
        summary,
    ]


def _render_market(
    presentation,
):
    return html.Div(
        className="result-stack",
        children=[
            html.Div(
                className="placeholder-panel",
                children=[
                    html.Div(
                        f"{company.display_name} ({company.symbol})",
                        className="eyebrow",
                    ),
                    html.H3(
                        "Controlled market metrics",
                        className="panel-title",
                    ),
                    html.P(
                        (
                            f"As of {company.market_as_of or 'unavailable'} · "
                            f"status={company.market_status}"
                        ),
                        className="panel-copy",
                    ),
                    _metric_cards(
                        company.market_metrics
                    ),
                ],
            )
            for company in presentation.companies
        ],
    )


def _render_fundamentals(
    presentation,
):
    return html.Div(
        className="result-stack",
        children=[
            html.Div(
                className="placeholder-panel",
                children=[
                    html.Div(
                        f"{company.display_name} ({company.symbol})",
                        className="eyebrow",
                    ),
                    html.H3(
                        "Controlled fundamental metrics",
                        className="panel-title",
                    ),
                    html.P(
                        (
                            f"As of {company.fundamental_as_of or 'unavailable'} "
                            f"· status={company.fundamental_status}"
                        ),
                        className="panel-copy",
                    ),
                    _metric_cards(
                        company.fundamental_metrics
                    ),
                ],
            )
            for company in presentation.companies
        ],
    )


def _render_report(
    presentation,
):
    children = [
        html.Div(
            className="report-header card",
            children=[
                html.Div(
                    presentation.report_status,
                    className=(
                        "status-badge "
                        f"status-badge--{presentation.report_status}"
                    ),
                ),
                html.Span(
                    f"Synthesis: {presentation.synthesis_mode}",
                    className="report-meta",
                ),
            ],
        )
    ]

    children.extend(
        html.Div(
            className="placeholder-panel report-section",
            children=[
                html.Div(
                    section.status,
                    className=(
                        "status-badge "
                        f"status-badge--{section.status}"
                    ),
                ),
                html.H3(
                    section.title,
                    className="panel-title",
                ),
                html.P(
                    section.text,
                    className="report-text",
                ),
                html.Div(
                    (
                        "Source findings: "
                        + ", ".join(section.source_finding_ids)
                    ),
                    className="source-findings",
                ),
            ],
        )
        for section in presentation.report_sections
    )

    if presentation.limitations:
        children.append(
            html.Div(
                className="placeholder-panel limitations-box",
                children=[
                    html.H3(
                        "Limitations",
                        className="panel-title",
                    ),
                    html.Ul(
                        [
                            html.Li(item)
                            for item in presentation.limitations
                        ]
                    ),
                ],
            )
        )

    return html.Div(
        className="result-stack",
        children=children,
    )


def _render_evidence(
    presentation,
):
    if not presentation.evidence:
        return placeholder_panel(
            "Evidence",
            "No narrative evidence citations are available for this report.",
        )

    return html.Div(
        className="evidence-grid",
        children=[
            html.Div(
                className="evidence-card",
                children=[
                    html.Div(
                        item.evidence_id,
                        className="evidence-id",
                    ),
                    html.Div(
                        (
                            "Supports: "
                            + ", ".join(item.source_finding_ids)
                        ),
                        className="source-findings",
                    ),
                ],
            )
            for item in presentation.evidence
        ],
    )


def _databricks_app_resources_available(
    environment: dict[str, str] | None = None,
) -> bool:
    values = os.environ if environment is None else environment

    return all(
        isinstance(values.get(name), str)
        and bool(values[name].strip())
        for name in (
            WAREHOUSE_ENV,
            MARKET_METRICS_TABLE_ENV,
            FUNDAMENTAL_METRICS_TABLE_ENV,
            VECTOR_INDEX_ENV,
        )
    )


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("DATABRICKS_APP_PORT", "8000")),
        debug=False,
    )
