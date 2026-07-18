import os
from pathlib import Path
import json
import shutil
from tethysapp.usgs_water_stage_qc.s3_utils import download_basin_geojson_files
import logging

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

STATES = [
    "ALABAMA", "ALASKA", "ARIZONA", "ARKANSAS", "CALIFORNIA", "COLORADO", "CONNECTICUT", "DELAWARE", "FLORIDA", "GEORGIA",
    "HAWAII", "IDAHO", "ILLINOIS", "INDIANA", "IOWA", "KANSAS", "KENTUCKY", "LOUISIANA", "MAINE", "MARYLAND",
    "MASSACHUSETTS", "MICHIGAN", "MINNESOTA", "MISSISSIPPI", "MISSOURI", "MONTANA", "NEBRASKA", "NEVADA", "NEW_HAMPSHIRE", "NEW_JERSEY",
    "NEW_MEXICO", "NEW_YORK", "NORTH_CAROLINA", "NORTH_DAKOTA", "OHIO", "OKLAHOMA", "OREGON", "PENNSYLVANIA", "RHODE_ISLAND", "SOUTH_CAROLINA",
    "SOUTH_DAKOTA", "TENNESSEE", "TEXAS", "UTAH", "VERMONT", "VIRGINIA", "WASHINGTON", "WEST_VIRGINIA", "WISCONSIN", "WYOMING"
]

def generate_extents_file():
    if not os.path.exists(Path(__file__).parent / "state_extents.json"):
        with open(Path(__file__).parent / "state_extents.json", "w") as f:
            f.write("{}")

    extents = {}
    for state in STATES:
        logger.info(f"Processing state: {state}")
        logger.info(f"Downloading basin geojson for state: {state}")
        download_basin_geojson_files(state, Path(__file__).parent)
        logger.info(f"Finished downloading basin geojson for state: {state}")
        logger.info(f"Calculating extent for state: {state}")
        current_features = []
        current_state_path = os.path.join(Path(__file__).parent, "basin_json_downloaded_files", state)
        for filename in os.listdir(current_state_path):
            if filename.endswith(".json"):
                filepath = os.path.join(current_state_path, filename)
                with open(filepath, "r") as f:
                    data = json.load(f)
                    current_features.append(data["geometry"])
        current_extents = []
        for feature in current_features:
            coords = feature["coordinates"]
            if coords:
                if feature["type"] == "Polygon":
                    flat_coords = [c for ring in coords for c in ring]
                elif feature["type"] == "MultiPolygon":
                    flat_coords = [c for poly in coords for ring in poly for c in ring]
                else:
                    flat_coords = coords                      
                    
                if flat_coords:
                    lons = [c[0] for c in flat_coords]
                    lats = [c[1] for c in flat_coords]
                    current_extents.append([min(lons), min(lats), max(lons), max(lats)])
        if current_extents:
            min_lon = min([e[0] for e in current_extents])
            min_lat = min([e[1] for e in current_extents])
            max_lon = max([e[2] for e in current_extents])
            max_lat = max([e[3] for e in current_extents])
            extents[state] = [min_lon - 1, min_lat - 1, max_lon + 1, max_lat + 1]
        else:
            extents[state] = [-180, -90, 180, 90]
            logger.warning(f"No extents found for state: {state}, defaulting to global extent [-180, -90, 180, 90]")

        # Remove the json files for the current state after processing
        shutil.rmtree(os.path.join(Path(__file__).parent, "basin_json_downloaded_files", state))
        logger.info(f"Removed basin json directory for state: {state}")
        logger.info(f"Finished processing state: {state}")

    # Remove the top-level basin_json_downloaded_files directory after all state directories have been removed
    os.removedirs(os.path.join(Path(__file__).parent, "basin_json_downloaded_files"))

    # Write the final state extents to the JSON file
    with open(Path(__file__).parent / "state_extents.json", "w") as f:
        json.dump(extents, f, indent=2)

if __name__ == "__main__":
    generate_extents_file()