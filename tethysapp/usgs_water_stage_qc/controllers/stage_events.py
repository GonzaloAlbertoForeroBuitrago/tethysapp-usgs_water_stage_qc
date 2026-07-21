from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from tethys_sdk.gizmos import PlotlyView
from tethys_sdk.routing import controller

from ..app import App


@controller(
    name="stage_events",
    url="stage-events/{state}/{gage_id}/",
    app_media=True,
)
def stage_events(request, state, gage_id, app_media):
    state_upper = state.upper().strip()
    gage_id_clean = gage_id.strip()

    data_directory = (
        Path(app_media.path)
        / "stage_data"
        / state_upper
        / gage_id_clean
        / "downloaded_data"
    )

    observations_path = data_directory / "stage_observations.parquet"
    hydro_path = data_directory / "stage_hydroeventdetector.parquet"
    station_path = data_directory / "station_metadata.parquet"
    excluded_path = data_directory / "excluded_observations.parquet"

    context = {
        "state": state_upper,
        "gage_id": gage_id_clean,
        "data_directory": str(data_directory),
    }

    required_files = [
        observations_path,
        hydro_path,
        station_path,
        excluded_path,
    ]

    missing_files = [
        path.name
        for path in required_files
        if not path.exists()
    ]

    if missing_files:
        context["data_error"] = (
            "The downloaded dataset is incomplete. Missing files: "
            + ", ".join(missing_files)
        )

        return App.render(
            request,
            "stage_events.html",
            context,
        )

    try:
        observations = pd.read_parquet(observations_path)
        hydro_data = pd.read_parquet(hydro_path)
        station_metadata = pd.read_parquet(station_path)
        excluded_observations = pd.read_parquet(excluded_path)

        if observations.empty:
            first_observation = None
            last_observation = None
            stage_min = None
            stage_max = None
        else:
            first_observation = observations["datetime"].min()
            last_observation = observations["datetime"].max()
            stage_min = observations["value"].min()
            stage_max = observations["value"].max()

        station_name = None
        unit = None
        latitude = None
        longitude = None

        if not station_metadata.empty:
            station_row = station_metadata.iloc[0]

            station_name = station_row.get("station_name")
            latitude = station_row.get("latitude")
            longitude = station_row.get("longitude")

        if not observations.empty:
            unit_values = observations["unit"].dropna()

            if not unit_values.empty:
                unit = unit_values.iloc[0]

        context["data_summary"] = {
            "station_name": station_name,
            "observation_rows": len(observations),
            "hydroeventdetector_rows": len(hydro_data),
            "excluded_rows": len(excluded_observations),
            "first_observation": first_observation,
            "last_observation": last_observation,
            "minimum_stage": stage_min,
            "maximum_stage": stage_max,
            "unit": unit,
            "latitude": latitude,
            "longitude": longitude,
        }

        if hydro_data.empty:
            context["plot_error"] = (
                "The HydroEventDetector dataset contains no observations."
            )

        elif not {"datetime", "Stage_ft"}.issubset(hydro_data.columns):
            context["plot_error"] = (
                "The HydroEventDetector dataset does not contain the "
                "required datetime and Stage_ft columns."
            )

        else:
            plot_data = (
                hydro_data[["datetime", "Stage_ft"]]
                .dropna(subset=["datetime", "Stage_ft"])
                .sort_values("datetime")
            )

            stage_figure = go.Figure()

            stage_figure.add_trace(
                go.Scattergl(
                    x=plot_data["datetime"],
                    y=plot_data["Stage_ft"],
                    mode="lines",
                    name="Stage",
                    line={
                        "width": 1.2,
                    },
                    hovertemplate=(
                        "<b>Stage</b><br>"
                        "Datetime: %{x|%Y-%m-%d %H:%M}<br>"
                        "Stage: %{y:.2f} ft"
                        "<extra></extra>"
                    ),
                )
            )

            stage_figure.update_layout(
                title={
                    "text": "USGS Water Stage Time Series",
                    "x": 0.5,
                },
                xaxis={
                    "title": "Datetime (UTC)",
                    "rangeslider": {
                        "visible": True,
                    },
                    "showgrid": True,
                },
                yaxis={
                    "title": "Stage (ft)",
                    "showgrid": True,
                },
                hovermode="x unified",
                template="plotly_white",
                height=600,
                margin={
                    "l": 70,
                    "r": 30,
                    "t": 70,
                    "b": 70,
                },
                legend={
                    "orientation": "h",
                    "yanchor": "bottom",
                    "y": 1.02,
                    "xanchor": "right",
                    "x": 1,
                },
            )

            context["stage_plot"] = PlotlyView(
                stage_figure,
                height="600px",
                width="100%",
            )

    except Exception as exc:
        context["data_error"] = str(exc)

    return App.render(
        request,
        "stage_events.html",
        context,
    )
