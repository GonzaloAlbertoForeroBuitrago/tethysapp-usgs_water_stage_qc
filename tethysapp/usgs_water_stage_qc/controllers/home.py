import os
import json
from pathlib import Path
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed

from django.http import JsonResponse
from django.shortcuts import redirect
from tethys_sdk.routing import controller
from tethys_sdk.layouts import MapLayout
from tethys_sdk.gizmos import MVView

from ..app import App
from usgs_gage_qc.stage_download import download_stage_data
from ..s3_utils import download_basin_geojson_files, download_zarr_file
from ..mrms_tiles import get_mrms_meta
from ..basin_utils import (
    calculate_basin_area,
    generated_json_exists,
    get_basin_json,
)

MAX_WORKERS = 4


@controller(name="home")
def home(request):
    return App.render(request, "home.html")


@controller(name="download_basin", url="download_basin/{state}/")
def download_basin_page(request, state):
    state = state.title()
    context = {
        "state": state,
        "process_type": "basin_download",
        "message": f"Downloading data for {state}..."
    }
    return App.render(request, "processing.html", context)


def load_single_basin_json(filepath):
    with open(filepath, "r") as f:
        data = json.load(f)

    return {
        "type": "Feature",
        "geometry": data["geometry"],
        "properties": data["properties"],
    }


@controller(name="do_download_basin_endpoint", url="do_download_basin/{state}/", app_media=True)
def do_download_basin(request, state, app_media):
    state = state.upper()

    try:
        generated_json_folder_path = os.path.join(
            App.get_app_media().path,
            "generated_basin_json",
        )

        generated_json_file_path = os.path.join(
            generated_json_folder_path,
            f"{state}.json",
        )

        if os.path.isfile(generated_json_file_path):
            return JsonResponse({"status": "success"})

        os.makedirs(generated_json_folder_path, exist_ok=True)

        download_basin_geojson_files(state, app_media.path)

        folder_path = os.path.join(
            app_media.path,
            "basin_json_downloaded_files",
            state,
        )

        json_files = [
            str(filepath)
            for filepath in Path(folder_path).rglob("*.json")
        ]

        if not json_files:
            raise FileNotFoundError(
                f"No downloaded basin JSON files found for {state}"
            )

        features = []

        # ===== TU PARALELIZADO SE CONSERVA AQUÍ =====
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = [
                executor.submit(load_single_basin_json, filepath)
                for filepath in json_files
            ]

            for future in as_completed(futures):
                features.append(future.result())

        features.sort(
            key=lambda f: calculate_basin_area(f.get("geometry")),
            reverse=True,
        )

        geojson_object = {
            "type": "FeatureCollection",
            "crs": {
                "type": "name",
                "properties": {
                    "name": "EPSG:4326",
                },
            },
            "features": features,
        }

        with open(generated_json_file_path, "w") as f:
            json.dump(geojson_object, f)

        downloaded_state_folder = os.path.join(
            App.get_app_media().path,
            "basin_json_downloaded_files",
            state,
        )

        if os.path.exists(downloaded_state_folder):
            shutil.rmtree(downloaded_state_folder)

        return JsonResponse({"status": "success"})

    except FileNotFoundError as e:
        return JsonResponse(
            {"status": "error", "message": str(e)},
            status=404,
        )

    except Exception as e:
        return JsonResponse(
            {"status": "error", "message": str(e)},
            status=500,
        )


@controller(name="download_stage", url="download_stage/{state}/{gage_id}/")
def download_stage(request, state, gage_id):
    from datetime import date

    context = {
        "state": state.upper(),
        "gage_id": gage_id,
        "default_start_date": "2019-01-01",
        "default_end_date": date.today().isoformat(),
    }

    return App.render(request, "station_qc.html", context)



@controller(
    name="do_download_zarr_endpoint",
    url="do_download_stage/{state}/{gage_id}/",
    app_media=True,
)
def do_download_stage(request, state, gage_id, app_media):
    start_date = request.POST["start_date"]
    end_date = request.POST["end_date"]

    state_upper = state.upper().strip()
    gage_id_clean = gage_id.strip()

    context = {
        "state": state_upper,
        "gage_id": gage_id_clean,
        "default_start_date": start_date,
        "default_end_date": end_date,
    }

    try:
        station_directory = (
            Path(app_media.path)
            / "stage_data"
            / state_upper
            / gage_id_clean
        )

        # Directories containing stage files from previous runs.
        stage_directories = [
            station_directory / "downloaded_data",
            station_directory / "processed_events",
            station_directory / "processed_data",
        ]

        # Begin every new stage download with a clean station workspace.
        # This does not affect basin files or data from other stations.
        for directory in stage_directories:
            if directory.exists():
                shutil.rmtree(directory)

        result = download_stage_data(
            state=state_upper,
            site_id=gage_id_clean,
            start_date=start_date,
            end_date=end_date,
            output_root=Path(app_media.path) / "stage_data",
        )

        observations = result.observations

        context["download_result"] = {
            "source": result.source,
            "observation_rows": len(observations),
            "hydroeventdetector_rows": len(
                result.hydroeventdetector_input
            ),
            "excluded_rows": len(result.excluded_observations),
            "first_observation": observations["datetime"].min(),
            "last_observation": observations["datetime"].max(),
            "output_directory": result.output_directory,
        }

    except Exception as exc:
        context["download_error"] = str(exc)

    return App.render(
        request,
        "station_qc.html",
        context,
    )



@controller(name="state_basin", url="basin/{state}/", app_media=True)
class StateBasinMapLayout(MapLayout):
    app = App
    base_template = "usgs_water_stage_qc/base.html"
    back_url = "/apps/usgs-water-stage-qc/"
    basemaps = [
        "OpenStreetMap",
        "ESRI",
    ]

    show_properties_popup = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def get_context(self, request, context, *args, **kwargs):
        self.map_title = f"{kwargs.get('state', '').title()} Basins"
        return super().get_context(request, context, *args, **kwargs)

    def get(self, request, state, app_media, *args, **kwargs):
        if not generated_json_exists(state):
            return redirect("usgs_water_stage_qc:download_basin", state=state)

        self.basin_json = get_basin_json(state)

        if self.basin_json is None:
            return redirect("usgs_water_stage_qc:download_basin", state=state)

        self.state = state.upper()

        return super().get(
            request,
            state=state,
            app_media=app_media,
            *args,
            **kwargs,
        )

    def build_map_extent_and_view(self, request, *args, **kwargs):
        state_extents_file = (
            Path(__file__).parent / "../state_map_extents/state_extents.json"
        )

        state_extents_json = json.load(state_extents_file.open())

        self.map_extent = state_extents_json.get(
            self.state,
            [-180, -90, 180, 90],
        )

        self.map_center = [
            (self.map_extent[1] + self.map_extent[3]) / 2,
            (self.map_extent[0] + self.map_extent[2]) / 2,
        ]

        map_view = MVView(
            extent=self.map_extent,
            zoom=6,
        )

        return map_view, self.map_center
    

    @classmethod
    def get_vector_style_map(cls):
        return {
            'MultiPolygon': {
                'ol.style.Style': {
                    'stroke': {'ol.style.Stroke': {
                        'color': 'blue',
                    }},
                    'fill': {'ol.style.Fill': {
                        'color': 'rgba(0, 0, 255, 0.05)',
                    }},
                }
            }
        }
        

    def compose_layers(self, request, map_view, app_media, *args, **kwargs):
        state = kwargs.get("state").capitalize()

        basin_layer = self.build_geojson_layer(
            self.basin_json,
            layer_name="basins",
            layer_title=f"{state} Basins",
            layer_variable="basins",
            visible=True,
            selectable=True,
            plottable=True,
        )

        map_view.layers.append(basin_layer)

        layer_groups = [
            self.build_layer_group(
                id="basins-layer-group",
                display_name="Basins",
                layer_control="radio",
                layers=[
                    basin_layer,
                ],
            ),
        ]

        return layer_groups


@controller(
    name="zarr_viewer",
    url="basin/{state}/{gage_id}",
    login_required=False,
    app_media=True,
)
def leaflet_mrms(request, state, gage_id, app_media):
    context = {
        "state": state,
        "gage_id": gage_id,
    }

    return App.render(
        request,
        "station_qc.html",
        context,
    )