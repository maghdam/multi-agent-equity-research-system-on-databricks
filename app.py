"""Dash shell for the Databricks equity-research application."""

from __future__ import annotations

import logging
import os
import secrets
import sys
from pathlib import Path

import plotly.graph_objects as go

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

from equity_research.app_followup import (  # noqa: E402
    FollowupQuestionError,
    FollowupSessionError,
    build_followup_session_payload,
    conversation_from_envelope,
    run_followup_turn,
    sign_followup_session,
    verify_followup_session,
)
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
    DatabricksAppTransport,
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
FOLLOWUP_SIGNING_KEY = secrets.token_bytes(32)

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
        dcc.Store(
            id="followup-session-store",
            storage_type="memory",
            data=None,
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
                                "Follow-up chat reuses only the active validated "
                                "research session, its controlled structured facts, "
                                "report findings, and cited provenance."
                            ),
                            className="section-copy",
                        ),
                        dcc.Loading(
                            type="circle",
                            children=html.Div(
                                id="followup-conversation",
                                className="followup-conversation",
                                children=html.P(
                                    (
                                        "Run research first to create a grounded "
                                        "follow-up session."
                                    ),
                                    className="followup-empty",
                                ),
                            ),
                        ),
                        html.Div(
                            className="followup-row",
                            children=[
                                dcc.Input(
                                    id="followup-input",
                                    type="text",
                                    value="",
                                    disabled=True,
                                    debounce=False,
                                    placeholder=(
                                        "Run research first, then ask a grounded "
                                        "follow-up question..."
                                    ),
                                    className="followup-input",
                                ),
                                html.Button(
                                    "Ask",
                                    id="followup-ask",
                                    n_clicks=0,
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
    Output("followup-session-store", "data"),
    Output("followup-input", "disabled"),
    Output("followup-ask", "disabled"),
    Output("followup-conversation", "children"),
    Output("followup-input", "value"),
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
            None,
            True,
            True,
            _followup_empty_state(
                "Run research again after correcting the selection."
            ),
            "",
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
            None,
            True,
            True,
            _followup_empty_state(
                "Follow-up chat is available only after a live research run."
            ),
            "",
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
            None,
            True,
            True,
            _followup_empty_state(
                "Follow-up chat was reset because the research run failed."
            ),
            "",
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

    followup_envelope = sign_followup_session(
        build_followup_session_payload(
            session
        ),
        signing_key=FOLLOWUP_SIGNING_KEY,
    )

    return (
        status,
        _render_overview(presentation),
        _render_market(presentation),
        _render_fundamentals(presentation),
        _render_report(presentation),
        _render_evidence(presentation),
        followup_envelope,
        False,
        False,
        _followup_empty_state(
            "Active research is ready. Ask a question about this session."
        ),
        "",
    )


@app.callback(
    Output(
        "followup-session-store",
        "data",
        allow_duplicate=True,
    ),
    Output(
        "followup-conversation",
        "children",
        allow_duplicate=True,
    ),
    Output(
        "followup-input",
        "value",
        allow_duplicate=True,
    ),
    Output(
        "followup-input",
        "disabled",
        allow_duplicate=True,
    ),
    Output(
        "followup-ask",
        "disabled",
        allow_duplicate=True,
    ),
    Input("followup-ask", "n_clicks"),
    State("followup-input", "value"),
    State("followup-session-store", "data"),
    prevent_initial_call=True,
)
def run_followup_action(
    _n_clicks: int,
    question: str,
    envelope,
) -> tuple:
    """Run one signed, session-bound grounded follow-up turn."""

    if not isinstance(question, str) or not question.strip():
        return (
            no_update,
            no_update,
            "",
            no_update,
            no_update,
        )

    if not _databricks_app_resources_available():
        return (
            None,
            _followup_empty_state(
                "Follow-up research requires the deployed Databricks App."
            ),
            "",
            True,
            True,
        )

    try:
        transport = DatabricksAppTransport()
        result = run_followup_turn(
            envelope,
            question=question,
            signing_key=FOLLOWUP_SIGNING_KEY,
            profile=None,
            model_query=transport.query_chat_completions,
        )
        conversation = _render_followup_conversation(
            result.envelope
        )
    except FollowupQuestionError as exc:
        return (
            no_update,
            _followup_empty_state(
                f"Follow-up question error: {exc}"
            ),
            "",
            no_update,
            no_update,
        )
    except FollowupSessionError:
        return (
            None,
            _followup_empty_state(
                "The active research session expired or changed. Run research "
                "again before asking another question."
            ),
            "",
            True,
            True,
        )
    except Exception as exc:
        logger.error(
            (
                "Follow-up execution failed safely: error_type=%s "
                "question_length=%s"
            ),
            type(exc).__name__,
            len(question.strip()),
        )
        return (
            no_update,
            _followup_empty_state(
                "Follow-up execution failed safely. The active research result "
                "is unchanged; check the Databricks App logs."
            ),
            "",
            no_update,
            no_update,
        )

    return (
        result.envelope,
        conversation,
        "",
        False,
        False,
    )


def _followup_empty_state(
    message: str,
):
    return html.P(
        message,
        className="followup-empty",
    )


def _render_followup_conversation(
    envelope,
):
    payload = verify_followup_session(
        envelope,
        signing_key=FOLLOWUP_SIGNING_KEY,
    )
    turns = conversation_from_envelope(
        envelope,
        signing_key=FOLLOWUP_SIGNING_KEY,
    )
    evidence_by_id = {
        item["evidence_id"]: item
        for item in payload["evidence"]
    }

    if not turns:
        return _followup_empty_state(
            "Active research is ready. Ask a question about this session."
        )

    children = []

    for turn in turns:
        children.append(
            html.Div(
                className="followup-message followup-message--user",
                children=[
                    html.Div(
                        "You",
                        className="followup-message-label",
                    ),
                    html.P(
                        turn["question"],
                        className="followup-message-text",
                    ),
                ],
            )
        )

        citation_children = [
            html.Span(
                source_id,
                className="followup-source-chip",
            )
            for source_id in turn["source_ids"]
        ]

        for evidence_id in turn["evidence_ids"]:
            evidence = evidence_by_id.get(
                evidence_id
            )

            if (
                evidence is not None
                and evidence.get("source_url")
            ):
                citation_children.append(
                    html.A(
                        evidence.get("short_evidence_id")
                        or evidence_id[:12],
                        href=evidence["source_url"],
                        target="_blank",
                        rel="noopener noreferrer",
                        className="followup-evidence-link",
                    )
                )

        assistant_children = [
            html.Div(
                "Grounded research",
                className="followup-message-label",
            ),
            html.P(
                turn["answer"],
                className="followup-message-text",
            ),
        ]

        if turn["limitation"]:
            assistant_children.append(
                html.Div(
                    turn["limitation"],
                    className="followup-limitation",
                )
            )

        if citation_children:
            assistant_children.append(
                html.Div(
                    citation_children,
                    className="followup-citations",
                )
            )

        children.append(
            html.Div(
                className="followup-message followup-message--assistant",
                children=assistant_children,
            )
        )

    return children


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
            _market_history_panel(
                presentation
            ),
            *[
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
        ],
    )


def _market_history_panel(
    presentation,
):
    series_values = presentation.market_history

    if not series_values:
        return placeholder_panel(
            "Normalized price history",
            "Validated Silver price history is not available for this run.",
        )

    unavailable = tuple(
        series
        for series in series_values
        if series.status != "ready" or not series.points
    )

    if unavailable:
        limitation = unavailable[0].limitation or (
            "Validated price history is unavailable for the selected window."
        )
        return placeholder_panel(
            "Normalized price history",
            limitation,
        )

    figure = go.Figure()

    for series in series_values:
        figure.add_trace(
            go.Scatter(
                x=[
                    point.trading_date
                    for point in series.points
                ],
                y=[
                    point.indexed_close
                    for point in series.points
                ],
                mode="lines",
                name=f"{series.display_name} ({series.symbol})",
                hovertemplate=(
                    "%{x}<br>Indexed close: %{y:.2f}"
                    "<extra>%{fullData.name}</extra>"
                ),
            )
        )

    figure.update_layout(
        title=(
            f"{presentation.market_window_sessions}-session normalized "
            "price history"
        ),
        xaxis_title="Trading date",
        yaxis_title="Indexed close (start = 100)",
        hovermode="x unified",
        margin={
            "l": 48,
            "r": 24,
            "t": 56,
            "b": 48,
        },
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={
            "color": "#9aa7c0",
        },
        legend={
            "orientation": "h",
            "yanchor": "bottom",
            "y": 1.02,
            "xanchor": "left",
            "x": 0,
        },
    )
    figure.update_xaxes(
        gridcolor="rgba(128,128,128,0.18)",
    )
    figure.update_yaxes(
        gridcolor="rgba(128,128,128,0.18)",
        zeroline=False,
    )

    return html.Div(
        className="placeholder-panel market-chart-panel",
        children=[
            html.Div(
                "Validated Silver daily prices",
                className="eyebrow",
            ),
            html.P(
                (
                    "Each series is indexed to 100 at the first close so "
                    "cross-company performance is comparable."
                ),
                className="panel-copy",
            ),
            dcc.Graph(
                figure=figure,
                config={
                    "displayModeBar": False,
                    "responsive": True,
                },
                className="market-history-chart",
            ),
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
            _evidence_card(
                item
            )
            for item in presentation.evidence
        ],
    )


def _evidence_card(
    item,
):
    if item.metadata_status != "ready":
        return html.Div(
            className="evidence-card",
            children=[
                html.Div(
                    "Citation",
                    className="evidence-source-badge",
                ),
                html.Div(
                    item.short_evidence_id,
                    className="evidence-id",
                    title=item.evidence_id,
                ),
                html.P(
                    (
                        "Validated citation metadata was not captured for "
                        "this render."
                    ),
                    className="evidence-copy",
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

    metadata_parts = [
        ", ".join(item.symbols),
        item.evidence_date,
        item.source_domain,
    ]
    metadata = " · ".join(
        part
        for part in metadata_parts
        if part
    )

    detail_parts = []

    if item.section_label:
        detail_parts.append(
            item.section_label
        )

    if item.retrieval_rank is not None:
        detail_parts.append(
            f"retrieval rank {item.retrieval_rank}"
        )

    if item.chunk_index is not None:
        detail_parts.append(
            f"chunk {item.chunk_index + 1}"
        )

    children = [
        html.Div(
            className="evidence-card-header",
            children=[
                html.Div(
                    item.source_label,
                    className="evidence-source-badge",
                ),
                html.Div(
                    item.short_evidence_id,
                    className="evidence-short-id",
                    title=item.evidence_id,
                ),
            ],
        ),
        html.Div(
            metadata,
            className="evidence-meta",
        ),
    ]

    if detail_parts:
        children.append(
            html.Div(
                " · ".join(detail_parts),
                className="evidence-detail",
            )
        )

    if item.source_business_id:
        children.append(
            html.Div(
                [
                    html.Span(
                        "Source record: ",
                        className="evidence-record-label",
                    ),
                    html.Span(
                        item.source_business_id,
                        className="evidence-record-value",
                    ),
                ],
                className="evidence-record",
            )
        )

    children.append(
        html.Div(
            (
                "Supports: "
                + ", ".join(item.source_finding_ids)
            ),
            className="source-findings",
        )
    )

    if item.source_url:
        children.append(
            html.A(
                "Open source",
                href=item.source_url,
                target="_blank",
                rel="noopener noreferrer",
                className="evidence-source-link",
            )
        )

    return html.Div(
        className="evidence-card",
        children=children,
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
