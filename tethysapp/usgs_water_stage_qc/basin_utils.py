import json
import os
from .app import App

def calculate_ring_area(ring):
    area = 0.0
    n = len(ring)
    for i in range(n):
        x1, y1 = ring[i][0], ring[i][1]
        x2, y2 = ring[(i + 1) % n][0], ring[(i + 1) % n][1]
        area += x1 * y2 - x2 * y1
    return abs(area) / 2.0


def calculate_basin_area(geometry):
    if not geometry:
        return 0.0
    gtype = geometry.get("type")
    coords = geometry.get("coordinates", [])
    if gtype == "Polygon" and coords:
        outer = calculate_ring_area(coords[0])
        holes = sum(calculate_ring_area(r) for r in coords[1:])
        return max(outer - holes, 0.0)
    if gtype == "MultiPolygon":
        total = 0.0
        for poly in coords:
            if not poly:
                continue
            outer = calculate_ring_area(poly[0])
            holes = sum(calculate_ring_area(r) for r in poly[1:])
            total += max(outer - holes, 0.0)
        return total
    return 0.0

def generated_json_exists(state):
    generated_json_file_path = os.path.join(App.get_app_media().path, "generated_basin_json", f"{state.upper()}.json")
    return os.path.isfile(generated_json_file_path)

def get_basin_json(state):
    generated_json_file_path = os.path.join(App.get_app_media().path, "generated_basin_json", f"{state.upper()}.json")
    with open(generated_json_file_path, "r") as f:
        return json.load(f)