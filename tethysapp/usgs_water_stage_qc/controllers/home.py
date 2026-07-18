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


@controller(name="download_zarr", url="download_zarr/{state}/{gage_id}/")
def download_zarr(request, state, gage_id):
    state = state.title()

    context = {
        "state": state,
        "gage_id": gage_id,
        "process_type": "zarr_download",
        "message": f"Downloading data for gage ID {gage_id} in {state}...",
    }
    
    return App.render(request, "processing.html", context)


@controller(
    name="do_download_zarr_endpoint",
    url="do_download_zarr/{state}/{gage_id}/",
    app_media=True,
)
def do_download_zarr(request, state, gage_id, app_media):
    state = state.upper()

    try:
        download_zarr_file(state, gage_id, app_media.path)

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
    app_media_path = app_media.path

    zarr_path = os.path.join(
        app_media_path,
        "zarr_files",
        f"{gage_id}.zarr",
    )

    if not os.path.exists(zarr_path):
        return redirect(
            "usgs_water_stage_qc:download_zarr",
            state=state,
            gage_id=gage_id,
        )

    meta = get_mrms_meta(gage_id)

    valid_time_indices = meta["valid_time_indices"]
    valid_times_iso = meta["valid_times_iso"]
    valid_count = len(valid_time_indices)

    slider_t0 = valid_count // 2 if valid_count else 0
    slider_max = max(valid_count - 1, 0)

    context = {
        "tile_url_template": f"/apps/usgs-water-stage-qc/mrms/tiles/{gage_id}/{{t}}/{{z}}/{{x}}/{{y}}",
        "value_url": f"/apps/usgs-water-stage-qc/mrms/value_at/{gage_id}",
        "max_pixel_url": f"/apps/usgs-water-stage-qc/mrms/max_pixel/{gage_id}",
        "recurrence_tile_url_template": f"/apps/usgs-water-stage-qc/mrms/recurrence/tiles/{gage_id}/{{z}}/{{x}}/{{y}}",
        "recurrence_value_url": f"/apps/usgs-water-stage-qc/mrms/recurrence/value_at/{gage_id}",
        "slider_t0": slider_t0,
        "slider_max": slider_max,
        "valid_time_indices_json": json.dumps(valid_time_indices),
        "valid_times_iso_json": json.dumps(valid_times_iso),
        "west": meta["west"],
        "south": meta["south"],
        "east": meta["east"],
        "north": meta["north"],
        "recurrence_max_count": meta["recurrence_max_count"],
        "n_valid_times": meta["n_valid_times"],
        "gage_id": gage_id,
    }

    return App.render(
        request,
        "leaflet_mrms.html",
        context,
    )