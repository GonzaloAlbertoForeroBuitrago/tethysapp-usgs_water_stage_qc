from __future__ import annotations

import os
import threading
from collections import OrderedDict
from io import BytesIO
from pathlib import Path

import mercantile
import numpy as np
import xarray as xr
from PIL import Image

from .app import App



TILE_SIZE = 256
DILATION_RADIUS = 1
MAX_CACHE_LIMIT = 512
RAIN_DISPLAY_THRESHOLD = 3.0

RAIN_BINS = np.array([0.0, 5.0, 10.0, 20.0, 30.0, 40.0, 50.0, np.inf], dtype=np.float32)
RECURRENCE_BINS = np.array([1, 2, 3, 4, 5, 6, 8, np.inf], dtype=np.float32)

COLORS_RGBA = np.array(
    [
        (0, 0, 255, 230),      # blue
        (0, 100, 0, 255),      # dark green
        (255, 255, 0, 255),    # yellow
        (255, 165, 0, 255),    # orange
        (255, 99, 71, 255),    # tomato
        (178, 34, 34, 255),    # firebrick
        (139, 0, 0, 255),      # dark red
    ],
    dtype=np.uint8,
)

_INIT_LOCK = threading.Lock()
_RECURRENCE_LOCK = threading.Lock()

MAX_GAGE_CACHE = 5

_GAGE_CACHE: OrderedDict[str, dict] = OrderedDict()
_GAGE_LOCKS: dict[str, threading.Lock] = {}
_GAGE_LOCKS_LOCK = threading.Lock()

_DS: xr.Dataset | None = None
_RAIN = None
_LON_FLAT: np.ndarray | None = None
_LAT_FLAT: np.ndarray | None = None
_TIMES_ISO: list[str] | None = None
_NT: int | None = None

_VALID_TIME_INDICES: np.ndarray | None = None
_VALID_TIMES_ISO: list[str] | None = None

_RECURRENCE_COUNTS: np.ndarray | None = None
_RECURRENCE_MAX_COUNT: int | None = None

_WEST: float | None = None
_EAST: float | None = None
_SOUTH: float | None = None
_NORTH: float | None = None

_TRANSPARENT_TILE_BYTES: bytes | None = None
_MAX_CACHE: OrderedDict[int, tuple[float | None, float | None, float | None]] = OrderedDict()

def get_zarr_path(gage_id: str) -> Path:
    app_media_path = App.get_app_media().path
    ZARR_PATH = os.path.join(app_media_path, "zarr_files", f"{gage_id}.zarr")
    return Path(ZARR_PATH)

def _build_transparent_tile() -> bytes:
    image = Image.fromarray(np.zeros((TILE_SIZE, TILE_SIZE, 4), dtype=np.uint8), mode="RGBA")
    buffer = BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def _dilate_grid(grid: np.ndarray) -> np.ndarray:
    if DILATION_RADIUS != 1:
        return grid

    dilated = np.maximum.reduce(
        [
            grid,
            np.roll(grid, 1, axis=0),
            np.roll(grid, -1, axis=0),
            np.roll(grid, 1, axis=1),
            np.roll(grid, -1, axis=1),
            np.roll(np.roll(grid, 1, axis=0), 1, axis=1),
            np.roll(np.roll(grid, 1, axis=0), -1, axis=1),
            np.roll(np.roll(grid, -1, axis=0), 1, axis=1),
            np.roll(np.roll(grid, -1, axis=0), -1, axis=1),
        ]
    )

    dilated[0, :] = -1
    dilated[-1, :] = -1
    dilated[:, 0] = -1
    dilated[:, -1] = -1
    return dilated

def _get_gage_lock(gage_id: str) -> threading.Lock:
    if gage_id not in _GAGE_LOCKS:
        with _GAGE_LOCKS_LOCK:
            if gage_id not in _GAGE_LOCKS:
                _GAGE_LOCKS[gage_id] = threading.Lock()
    return _GAGE_LOCKS[gage_id]


def _init_once(gage_id: str) -> None:
    if gage_id in _GAGE_CACHE:
        _GAGE_CACHE.move_to_end(gage_id)
        return
    
    with _get_gage_lock(gage_id):
        if gage_id in _GAGE_CACHE:
            return

        zarr_path = get_zarr_path(gage_id)
        if not zarr_path.exists():
            raise FileNotFoundError(f"MRMS Zarr not found: {zarr_path}")

        try:
            dataset = xr.open_zarr(str(zarr_path), consolidated=True)
        except Exception:
            dataset = xr.open_zarr(str(zarr_path), consolidated=False)

        required = {"rain", "lon", "lat", "time"}
        missing = required.difference(set(dataset.variables))
        if missing:
            raise KeyError(
                f"Zarr is missing required variables: {sorted(missing)}. "
                f"Available variables: {sorted(dataset.variables)}"
            )

        rain = dataset["rain"]
        lon_flat = np.asarray(dataset["lon"].values, dtype=np.float32).reshape(-1)
        lat_flat = np.asarray(dataset["lat"].values, dtype=np.float32).reshape(-1)

        times = dataset["time"].values
        times_iso = [str(np.datetime64(t)) for t in times]
        nt = int(dataset.sizes["time"])

        spatial_dims = tuple(dim for dim in rain.dims if dim != "time")
        max_per_time = np.asarray(
            rain.max(dim=spatial_dims, skipna=True).values,
            dtype=np.float32,
        ).reshape(-1)
        valid_mask = np.isfinite(max_per_time) & (max_per_time > RAIN_DISPLAY_THRESHOLD)
        valid_time_indices = np.flatnonzero(valid_mask).astype(np.int32)
        valid_times_iso = [times_iso[i] for i in valid_time_indices.tolist()]

        finite_mask = np.isfinite(lon_flat) & np.isfinite(lat_flat)
        if finite_mask.any():
            lon_ok = lon_flat[finite_mask]
            lat_ok = lat_flat[finite_mask]
            west = float(lon_ok.min())
            east = float(lon_ok.max())
            south = float(lat_ok.min())
            north = float(lat_ok.max())
        else:
            west = east = south = north = None


        _GAGE_CACHE[gage_id] = {
            "dataset": dataset,
            "rain": rain,
            "lon_flat": lon_flat,
            "lat_flat": lat_flat,
            "times_iso": times_iso,
            "nt": nt,
            "valid_time_indices": valid_time_indices,
            "valid_times_iso": valid_times_iso,
            "west": west,
            "east": east,
            "south": south,
            "north": north,
            "transparent_tile_bytes": _build_transparent_tile(),
            "max_pixel_cache": OrderedDict()
        }

        _GAGE_CACHE.move_to_end(gage_id)
        if len(_GAGE_CACHE) > MAX_GAGE_CACHE:
            _ , evicted = _GAGE_CACHE.popitem(last=False)
            evicted["dataset"].close()

def _transparent_png_bytes(gage_id: str) -> bytes:
    _init_once(gage_id)
    return _GAGE_CACHE[gage_id]["transparent_tile_bytes"]  # type: ignore[return-value]


def _rain_time_to_1d(time_index: int, gage_id: str) -> np.ndarray:
    _init_once(gage_id)
    RAIN = _GAGE_CACHE[gage_id]["rain"]
    array_1d = np.asarray(RAIN.isel(time=time_index).values, dtype=np.float32).reshape(-1)
    
    LON_FLAT = _GAGE_CACHE[gage_id]["lon_flat"]
    expected_size = LON_FLAT.size  # type: ignore[union-attr]

    if array_1d.size != expected_size:
        raise ValueError(
            f"Grid mismatch: rain(t) has {array_1d.size} values but lon/lat have {expected_size} values."
        )

    return array_1d


def _render_flat_values_to_tile(
    values_1d: np.ndarray,
    bins: np.ndarray,
    z: int,
    x: int,
    y: int,
    gage_id: str,
) -> bytes:
    _init_once(gage_id)

    bounds = mercantile.bounds(x, y, z)
    west, south, east, north = bounds.west, bounds.south, bounds.east, bounds.north

    lon = _GAGE_CACHE[gage_id]["lon_flat"]
    lat = _GAGE_CACHE[gage_id]["lat_flat"]

    spatial_mask = (lon >= west) & (lon <= east) & (lat >= south) & (lat <= north)
    if not spatial_mask.any():
        return _transparent_png_bytes(gage_id)

    valid_mask = spatial_mask & np.isfinite(values_1d) & (values_1d > RAIN_DISPLAY_THRESHOLD)
    if not valid_mask.any():
        return _transparent_png_bytes(gage_id)

    lon_t = lon[valid_mask]
    lat_t = lat[valid_mask]
    values_t = values_1d[valid_mask]

    px = (lon_t - west) / (east - west) * (TILE_SIZE - 1)
    py = (north - lat_t) / (north - south) * (TILE_SIZE - 1)

    ix = np.clip(px.astype(np.int32), 0, TILE_SIZE - 1)
    iy = np.clip(py.astype(np.int32), 0, TILE_SIZE - 1)

    bin_index = np.clip(
        np.digitize(values_t, bins, right=False) - 1,
        0,
        len(COLORS_RGBA) - 1,
    ).astype(np.int16)

    grid = np.full((TILE_SIZE, TILE_SIZE), -1, dtype=np.int16)
    flat_index = iy * TILE_SIZE + ix
    np.maximum.at(grid.reshape(-1), flat_index, bin_index)

    rgba = np.zeros((TILE_SIZE, TILE_SIZE, 4), dtype=np.uint8)
    active = _dilate_grid(grid) >= 0
    dilated_grid = _dilate_grid(grid)
    rgba[active] = COLORS_RGBA[dilated_grid[active]]

    image = Image.fromarray(rgba, mode="RGBA")
    buffer = BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def _compute_recurrence_counts(gage_id: str) -> tuple[np.ndarray, int]:
    _init_once(gage_id)

    gage_cache = _GAGE_CACHE[gage_id]
    valid_time_indices = gage_cache["valid_time_indices"]
    
    pixel_count = gage_cache["lon_flat"].size  # type: ignore[union-attr]

    if valid_time_indices.size == 0:
        counts = np.zeros(pixel_count, dtype=np.int32)
        return counts, 0
    
    rain_valid = np.asarray(
        gage_cache["rain"].isel(time=valid_time_indices).values,
        dtype=np.float32,
    ).reshape(valid_time_indices.size, pixel_count)

    positive = np.isfinite(rain_valid) & (rain_valid > 0)
    masked = np.where(positive, rain_valid, -np.inf)
    max_pixel_index_per_time = np.argmax(masked, axis=1)

    counts = np.bincount(max_pixel_index_per_time, minlength=pixel_count).astype(np.int32)
    max_count = int(counts.max(initial=0))
    return counts, max_count


def _get_recurrence_data(gage_id: str) -> tuple[np.ndarray, int]:
    _init_once(gage_id)
    cache = _GAGE_CACHE[gage_id]

    if "recurrence_counts" in cache and "recurrence_max_count" in cache:
        return cache["recurrence_counts"], cache["recurrence_max_count"]
    
    with _get_gage_lock(gage_id):
        if "recurrence_counts" not in cache or "recurrence_max_count" not in cache:
            counts, max_count = _compute_recurrence_counts(gage_id)
            cache["recurrence_counts"] = counts
            cache["recurrence_max_count"] = max_count

    return cache["recurrence_counts"], cache["recurrence_max_count"]


def get_mrms_meta(gage_id) -> dict[str, object]:
    _init_once(gage_id)
    _, recurrence_max_count = _get_recurrence_data(gage_id)

    gage_cache = _GAGE_CACHE[gage_id]
    return {
        "nt": int(gage_cache["nt"]),
        "times_iso": gage_cache["times_iso"],
        "valid_time_indices": gage_cache["valid_time_indices"].tolist(),
        "valid_times_iso": gage_cache["valid_times_iso"],
        "zarr_path": get_zarr_path(gage_id),
        "n_pixels": int(gage_cache["lon_flat"].size),
        "west": gage_cache["west"],
        "east": gage_cache["east"],
        "south": gage_cache["south"],
        "north": gage_cache["north"],
        "recurrence_max_count": int(recurrence_max_count),
        "n_valid_times": int(gage_cache["valid_time_indices"].size),
    }


def render_tile_png(time_index: int, z: int, x: int, y: int, gage_id: str) -> bytes:
    _init_once(gage_id)

    if time_index < 0 or time_index >= int(_GAGE_CACHE[gage_id]["nt"]):
        return _transparent_png_bytes(gage_id)

    values_1d = _rain_time_to_1d(time_index, gage_id)
    return _render_flat_values_to_tile(values_1d=values_1d, bins=RAIN_BINS, z=z, x=x, y=y, gage_id=gage_id)


def render_recurrence_tile_png(z: int, x: int, y: int, gage_id: str) -> bytes:
    counts, _ = _get_recurrence_data(gage_id)
    counts = counts.astype(np.float32, copy=False)
    return _render_flat_values_to_tile(values_1d=counts, bins=RECURRENCE_BINS, z=z, x=x, y=y, gage_id=gage_id)


def value_at_latlon(time_index: int, lon: float, lat: float, gage_id: str) -> float | None:
    _init_once(gage_id)
    gage_cache = _GAGE_CACHE[gage_id]

    if time_index < 0 or time_index >= int(gage_cache["nt"]):
        return None

    values_1d = _rain_time_to_1d(time_index, gage_id)
    dx = gage_cache["lon_flat"] - float(lon)
    dy = gage_cache["lat_flat"] - float(lat)
    nearest_index = int(np.argmin(dx * dx + dy * dy))

    value = values_1d[nearest_index]
    return float(value) if np.isfinite(value) else None


def recurrence_at_latlon(lon: float, lat: float, gage_id: str) -> int:
    _init_once(gage_id)

    counts, _ = _get_recurrence_data(gage_id)
    gage_cache = _GAGE_CACHE[gage_id]
    dx = gage_cache["lon_flat"] - float(lon)
    dy = gage_cache["lat_flat"] - float(lat)
    nearest_index = int(np.argmin(dx * dx + dy * dy))
    return int(counts[nearest_index])


def max_pixel_at_time(time_index: int, gage_id: str) -> tuple[float | None, float | None, float | None]:
    _init_once(gage_id)

    gage_cache = _GAGE_CACHE[gage_id]

    ti = int(time_index)
    if ti < 0 or ti >= int(gage_cache["nt"]):
        return (None, None, None)

    cached = gage_cache["max_pixel_cache"].get(ti)
    if cached is not None:
        gage_cache["max_pixel_cache"].move_to_end(ti)
        return cached

    values_1d = _rain_time_to_1d(ti, gage_id)
    valid = np.isfinite(values_1d) & (values_1d > 5)

    if valid.any():
        masked = np.where(valid, values_1d, -np.inf)
        max_index = int(np.argmax(masked))
        result = (
            float(gage_cache["lon_flat"][max_index]),
            float(gage_cache["lat_flat"][max_index]),
            float(values_1d[max_index]),
        )
    else:
        result = (None, None, None)

    gage_cache["max_pixel_cache"][ti] = result
    gage_cache["max_pixel_cache"].move_to_end(ti)

    while len(gage_cache["max_pixel_cache"]) > MAX_CACHE_LIMIT:
        gage_cache["max_pixel_cache"].popitem(last=False)

    return result