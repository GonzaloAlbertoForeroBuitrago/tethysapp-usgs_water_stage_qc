from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import plotly.graph_objects as go
from pandas import DataFrame, Series
from tethys_sdk.gizmos import PlotlyView
from tethys_sdk.routing import controller
from usgs_gage_qc.hydro_event_detector import detect_stage_events

from ..app import App


RANKING_METHODS = {
    "combined": {
        "column": "combined_rank",
        "label": "Overall importance",
        "description": (
            "Balances peak stage and stage rise above baseflow."
        ),
    },
    "flow_peak": {
        "column": "flow_peak_rank",
        "label": "Highest water stage",
        "description": "Prioritizes events with the highest peak stage.",
    },
    "peak_quick_stage": {
        "column": "peak_quick_stage_rank",
        "label": "Largest rise above baseflow",
        "description": (
            "Prioritizes events with the largest stage rise above baseflow."
        ),
    },
}
DEFAULT_RANKING_METHOD = "combined"

EVENT_DATE_COLUMNS = ("date_start", "date_peak", "date_end")
EVENT_REQUIRED_COLUMNS = {
    "event_id",
    "date_start",
    "date_peak",
    "date_end",
    "flow_peak",
    "baseflow_peak",
    "peak_quick_stage_ft",
    "combined_normalized_score",
    *(definition["column"] for definition in RANKING_METHODS.values()),
}
PLOT_COLUMNS = (
    "datetime",
    "Stage_ft",
    "baseflow_ft",
    "stage_above_baseflow_ft",
)


def _get_ranking_method(request) -> str:
    requested_method = request.GET.get(
        "ranking_method",
        DEFAULT_RANKING_METHOD,
    )
    return (
        requested_method
        if requested_method in RANKING_METHODS
        else DEFAULT_RANKING_METHOD
    )


def _format_datetime(value: Any) -> str:
    return (
        value.strftime("%Y-%m-%d %H:%M")
        if pd.notna(value)
        else "Not available"
    )


def _optional_float(value: Any, digits: int = 2) -> float | None:
    return round(float(value), digits) if pd.notna(value) else None


def _optional_int(value: Any) -> int | None:
    return int(value) if pd.notna(value) else None


def _prepare_events(
    selected_events: DataFrame,
    ranking_method: str,
) -> DataFrame:
    events = selected_events.copy()

    for column in EVENT_DATE_COLUMNS:
        events[column] = pd.to_datetime(events[column], errors="coerce")

    events["duration_hours"] = (
        events["date_end"] - events["date_start"]
    ).dt.total_seconds().div(3600)

    ranking_column = RANKING_METHODS[ranking_method]["column"]

    events = events.sort_values(
        by=[ranking_column, "date_peak", "event_id"],
        ascending=[True, True, True],
        na_position="last",
        kind="stable",
    ).reset_index(drop=True)

    # The displayed rank belongs to the active user-selected ordering.
    events["display_rank"] = pd.Series(
        range(1, len(events) + 1),
        dtype="Int64",
    )

    return events


def _serialize_event(event: Series) -> dict[str, Any]:
    return {
        "event_id": _optional_int(event["event_id"]),
        "rank": _optional_int(event["display_rank"]),
        "date_start": _format_datetime(event["date_start"]),
        "date_peak": _format_datetime(event["date_peak"]),
        "date_end": _format_datetime(event["date_end"]),
        "peak_stage_ft": _optional_float(event["flow_peak"]),
        "baseflow_at_peak_ft": _optional_float(
            event["baseflow_peak"]
        ),
        "stage_above_baseflow_ft": _optional_float(
            event["peak_quick_stage_ft"]
        ),
        "duration_hours": _optional_float(event["duration_hours"]),
        "combined_score": _optional_float(
            event["combined_normalized_score"],
            digits=4,
        ),
    }


def _find_selected_event(
    events: DataFrame,
    requested_event_id: str | None,
) -> tuple[dict[str, Any] | None, Series | None]:
    try:
        event_id = int(requested_event_id)
    except (TypeError, ValueError):
        return None, None

    matching_events = events.loc[events["event_id"].eq(event_id)]

    if matching_events.empty:
        return None, None

    event_row = matching_events.iloc[0]
    return _serialize_event(event_row), event_row


def _build_time_series_figure(
    stage_data: DataFrame,
    baseflow_data: DataFrame,
) -> go.Figure:
    figure = go.Figure()

    figure.add_trace(
        go.Scattergl(
            x=stage_data["datetime"],
            y=stage_data["Stage_ft"],
            mode="lines",
            name="Observed Stage",
            line={"width": 1.2},
            customdata=stage_data[
                ["baseflow_ft", "stage_above_baseflow_ft"]
            ],
            connectgaps=False,
            hovertemplate=(
                "<b>Observed Stage</b><br>"
                "Datetime: %{x|%Y-%m-%d %H:%M}<br>"
                "Stage: %{y:.2f} ft<br>"
                "Baseflow: %{customdata[0]:.2f} ft<br>"
                "Stage above baseflow: %{customdata[1]:.2f} ft"
                "<extra></extra>"
            ),
        )
    )

    if not baseflow_data.empty:
        figure.add_trace(
            go.Scattergl(
                x=baseflow_data["datetime"],
                y=baseflow_data["baseflow_ft"],
                mode="lines",
                name="Baseflow",
                line={"width": 1.2, "dash": "dash"},
                customdata=baseflow_data[
                    ["Stage_ft", "stage_above_baseflow_ft"]
                ],
                connectgaps=False,
                hovertemplate=(
                    "<b>Baseflow</b><br>"
                    "Datetime: %{x|%Y-%m-%d %H:%M}<br>"
                    "Baseflow: %{y:.2f} ft<br>"
                    "Observed stage: %{customdata[0]:.2f} ft<br>"
                    "Stage above baseflow: %{customdata[1]:.2f} ft"
                    "<extra></extra>"
                ),
            )
        )

    figure.update_layout(
        title={
            "text": "USGS Water Stage and Baseflow Time Series",
            "x": 0.5,
        },
        xaxis={
            "title": "Datetime (UTC)",
            "rangeslider": {"visible": True},
            "showgrid": True,
        },
        yaxis={"title": "Stage (ft)", "showgrid": True},
        hovermode="x unified",
        template="plotly_white",
        height=600,
        margin={"l": 70, "r": 30, "t": 70, "b": 70},
        legend={
            "orientation": "h",
            "yanchor": "bottom",
            "y": 1.02,
            "xanchor": "right",
            "x": 1,
        },
    )

    return figure


def _build_event_figure(
    event_data: DataFrame,
    event_peak: Any,
    peak_stage: Any,
) -> go.Figure:
    figure = go.Figure()

    figure.add_trace(
        go.Scatter(
            x=event_data["datetime"],
            y=event_data["Stage_ft"],
            mode="lines",
            name="Observed Stage",
            line={"width": 2},
            customdata=event_data[
                ["baseflow_ft", "stage_above_baseflow_ft"]
            ],
            connectgaps=False,
            hovertemplate=(
                "<b>Observed Stage</b><br>"
                "Datetime: %{x|%Y-%m-%d %H:%M}<br>"
                "Stage: %{y:.2f} ft<br>"
                "Baseflow: %{customdata[0]:.2f} ft<br>"
                "Stage above baseflow: %{customdata[1]:.2f} ft"
                "<extra></extra>"
            ),
        )
    )

    event_baseflow = event_data.dropna(subset=["baseflow_ft"])

    if not event_baseflow.empty:
        figure.add_trace(
            go.Scatter(
                x=event_baseflow["datetime"],
                y=event_baseflow["baseflow_ft"],
                mode="lines",
                name="Baseflow",
                line={"width": 1.5, "dash": "dash"},
                connectgaps=False,
                hovertemplate=(
                    "<b>Baseflow</b><br>"
                    "Datetime: %{x|%Y-%m-%d %H:%M}<br>"
                    "Baseflow: %{y:.2f} ft"
                    "<extra></extra>"
                ),
            )
        )

    if pd.notna(event_peak) and pd.notna(peak_stage):
        figure.add_trace(
            go.Scatter(
                x=[event_peak],
                y=[peak_stage],
                mode="markers",
                name="Event Peak",
                marker={"size": 11, "symbol": "diamond"},
                hovertemplate=(
                    "<b>Event Peak</b><br>"
                    "Datetime: %{x|%Y-%m-%d %H:%M}<br>"
                    "Stage: %{y:.2f} ft"
                    "<extra></extra>"
                ),
            )
        )

    figure.update_layout(
        title={"text": "Selected Water-Stage Event", "x": 0.5},
        xaxis={"title": "Datetime (UTC)", "showgrid": True},
        yaxis={"title": "Stage (ft)", "showgrid": True},
        hovermode="x unified",
        template="plotly_white",
        height=500,
        margin={"l": 70, "r": 30, "t": 70, "b": 70},
        legend={
            "orientation": "h",
            "yanchor": "bottom",
            "y": 1.02,
            "xanchor": "right",
            "x": 1,
        },
    )

    return figure


@controller(
    name="stage_events",
    url="stage-events/{state}/{gage_id}/",
    app_media=True,
)
def stage_events(request, state, gage_id, app_media):
    state_upper = state.upper().strip()
    gage_id_clean = gage_id.strip()
    ranking_method = _get_ranking_method(request)

    gage_directory = (
        Path(app_media.path)
        / "stage_data"
        / state_upper
        / gage_id_clean
    )
    data_directory = gage_directory / "downloaded_data"
    processed_directory = gage_directory / "processed_events"

    paths = {
        "observations": data_directory / "stage_observations.parquet",
        "hydro": data_directory / "stage_hydroeventdetector.parquet",
        "station": data_directory / "station_metadata.parquet",
        "excluded": data_directory / "excluded_observations.parquet",
        "baseflow": processed_directory / "stage_baseflow.parquet",
        "events": processed_directory / "stage_events_selected.parquet",
    }

    active_ranking = RANKING_METHODS[ranking_method]
    ranking_options = [
        {
            "value": value,
            "label": definition["label"],
            "description": definition["description"],
        }
        for value, definition in RANKING_METHODS.items()
    ]

    context = {
        "state": state_upper,
        "gage_id": gage_id_clean,
        "data_directory": str(data_directory),
        "ranking_method": ranking_method,
        "ranking_label": active_ranking["label"],
        "ranking_description": active_ranking["description"],
        "ranking_options": ranking_options,
    }

    required_downloads = (
        paths["observations"],
        paths["hydro"],
        paths["station"],
        paths["excluded"],
    )
    missing_files = [
        path.name for path in required_downloads if not path.exists()
    ]

    if missing_files:
        context["data_error"] = (
            "The downloaded dataset is incomplete. Missing files: "
            + ", ".join(missing_files)
        )
        return App.render(request, "stage_events.html", context)

    try:
        if not paths["baseflow"].exists() or not paths["events"].exists():
            detect_stage_events(
                input_path=paths["hydro"],
                output_directory=processed_directory,
                site_id=gage_id_clean,
            )

        observations = pd.read_parquet(paths["observations"])
        hydro_data = pd.read_parquet(paths["hydro"])
        baseflow_data = pd.read_parquet(paths["baseflow"])
        station_metadata = pd.read_parquet(paths["station"])
        excluded_observations = pd.read_parquet(paths["excluded"])
        selected_events = pd.read_parquet(paths["events"])

        missing_event_columns = sorted(
            EVENT_REQUIRED_COLUMNS.difference(selected_events.columns)
        )

        if selected_events.empty:
            context["events_error"] = (
                "No selected historical events are available for this station."
            )
            events_for_display = pd.DataFrame()
        elif missing_event_columns:
            context["events_error"] = (
                "The selected-events dataset is missing required columns: "
                + ", ".join(missing_event_columns)
            )
            events_for_display = pd.DataFrame()
        else:
            events_for_display = _prepare_events(
                selected_events,
                ranking_method,
            )

        historical_events = [
            _serialize_event(event)
            for _, event in events_for_display.iterrows()
        ]
        selected_event, selected_event_row = _find_selected_event(
            events_for_display,
            request.GET.get("event_id"),
        )

        context.update(
            {
                "historical_events": historical_events,
                "selected_event": selected_event,
            }
        )

        station_row = (
            station_metadata.iloc[0]
            if not station_metadata.empty
            else pd.Series(dtype="object")
        )
        unit_values = (
            observations["unit"].dropna()
            if "unit" in observations.columns
            else pd.Series(dtype="object")
        )

        context["data_summary"] = {
            "station_name": station_row.get("station_name"),
            "observation_rows": len(observations),
            "hydroeventdetector_rows": len(hydro_data),
            "excluded_rows": len(excluded_observations),
            "selected_events": len(selected_events),
            "first_observation": (
                observations["datetime"].min()
                if not observations.empty
                else None
            ),
            "last_observation": (
                observations["datetime"].max()
                if not observations.empty
                else None
            ),
            "minimum_stage": (
                observations["value"].min()
                if not observations.empty
                else None
            ),
            "maximum_stage": (
                observations["value"].max()
                if not observations.empty
                else None
            ),
            "unit": unit_values.iloc[0] if not unit_values.empty else None,
            "latitude": station_row.get("latitude"),
            "longitude": station_row.get("longitude"),
        }

        missing_plot_columns = sorted(
            set(PLOT_COLUMNS).difference(baseflow_data.columns)
        )

        if baseflow_data.empty:
            context["plot_error"] = (
                "The processed stage and baseflow dataset contains "
                "no observations."
            )
        elif missing_plot_columns:
            context["plot_error"] = (
                "The processed dataset is missing required columns: "
                + ", ".join(missing_plot_columns)
            )
        else:
            plot_data = baseflow_data.loc[:, PLOT_COLUMNS].copy()
            plot_data["datetime"] = pd.to_datetime(
                plot_data["datetime"],
                errors="coerce",
            )

            stage_plot_data = (
                plot_data.dropna(subset=["datetime", "Stage_ft"])
                .sort_values("datetime")
            )
            baseflow_plot_data = (
                plot_data.dropna(subset=["datetime", "baseflow_ft"])
                .sort_values("datetime")
            )

            if stage_plot_data.empty:
                context["plot_error"] = (
                    "No valid water-stage observations are available "
                    "for plotting."
                )
            else:
                context["stage_plot"] = PlotlyView(
                    _build_time_series_figure(
                        stage_plot_data,
                        baseflow_plot_data,
                    ),
                    height="600px",
                    width="100%",
                )

                if selected_event_row is not None:
                    event_start = selected_event_row["date_start"]
                    event_end = selected_event_row["date_end"]

                    valid_window = (
                        pd.notna(event_start)
                        and pd.notna(event_end)
                        and event_end >= event_start
                    )

                    if not valid_window:
                        context["selected_event_plot_error"] = (
                            "The selected event does not have a valid "
                            "start and end datetime."
                        )
                    else:
                        event_plot_data = stage_plot_data.loc[
                            stage_plot_data["datetime"].between(
                                event_start,
                                event_end,
                                inclusive="both",
                            )
                        ].copy()

                        if event_plot_data.empty:
                            context["selected_event_plot_error"] = (
                                "No processed stage observations are "
                                "available within the selected event."
                            )
                        else:
                            context["selected_event_plot"] = PlotlyView(
                                _build_event_figure(
                                    event_plot_data,
                                    selected_event_row["date_peak"],
                                    selected_event_row["flow_peak"],
                                ),
                                height="500px",
                                width="100%",
                            )

    except Exception as exc:
        context["data_error"] = (
            f"{type(exc).__name__}: {exc}"
        )

    return App.render(request, "stage_events.html", context)
