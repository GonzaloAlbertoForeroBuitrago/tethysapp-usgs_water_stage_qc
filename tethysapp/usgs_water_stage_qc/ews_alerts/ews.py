from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import zarr


pd.options.display.float_format = "{:.6f}".format


# ======================================================================================
# PATHS
# ======================================================================================

def find_one(root: Path, pattern: str) -> Path:
    path = next(root.rglob(pattern), None)
    if path is None:
        raise FileNotFoundError(f"Could not find {pattern} under {root}")
    return path


def find_site_paths(base: Path, site_id: str) -> dict[str, Path]:
    roots = {
        "events": base / "events",
        "stage": base / "stage_parquet",
        "rain": base / "rain_zarr",
        "meta": base / "site_meta",
    }

    missing = [str(v) for v in roots.values() if not v.exists()]
    if missing:
        raise FileNotFoundError("Missing required folders:\n" + "\n".join(missing))

    return {
        "events_fp": find_one(roots["events"], f"{site_id}_rain_windows.csv"),
        "stage_fp": find_one(roots["stage"], f"{site_id}.parquet"),
        "zarr_fp": find_one(roots["rain"], f"{site_id}.zarr"),
        "meta_fp": find_one(roots["meta"], f"{site_id}_monitoring_location.json"),
    }


# ======================================================================================
# HELPERS
# ======================================================================================

def to_naive_timestamp(value) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    return ts.tz_convert(None) if ts.tzinfo is not None else ts


def build_window_indices(
    time_index: pd.DatetimeIndex,
    starts: pd.Series | np.ndarray,
    ends: pd.Series | np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    arr = time_index.to_numpy(dtype="datetime64[ns]")
    starts_arr = pd.to_datetime(starts).to_numpy(dtype="datetime64[ns]")
    ends_arr = pd.to_datetime(ends).to_numpy(dtype="datetime64[ns]")

    i0 = arr.searchsorted(starts_arr, side="left")
    i1 = arr.searchsorted(ends_arr, side="right")
    return i0.astype(np.int64), i1.astype(np.int64)


def hours_between_vectorized(t0: np.ndarray, t1: np.ndarray) -> np.ndarray:
    return (t1 - t0).astype("timedelta64[s]").astype(np.float64) / 3600.0


def haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0

    lat1 = np.radians(lat1)
    lon1 = np.radians(lon1)
    lat2 = np.radians(lat2)
    lon2 = np.radians(lon2)

    dlat = lat2 - lat1
    dlon = lon2 - lon1

    a = np.sin(dlat / 2.0) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2.0) ** 2
    return 2.0 * r * np.arctan2(np.sqrt(a), np.sqrt(1.0 - a))


# ======================================================================================
# LOADERS
# ======================================================================================

def load_events(events_fp: Path) -> pd.DataFrame:
    print("=" * 100)
    print("LOADING EVENTS")
    print("=" * 100)

    events = pd.read_csv(events_fp, parse_dates=["date_peak", "start_rain", "end_rain"])
    if events.empty:
        raise ValueError(f"Events file is empty: {events_fp}")

    for col in ["date_peak", "start_rain", "end_rain"]:
        events[col] = pd.to_datetime(events[col], errors="coerce").map(to_naive_timestamp)

    events["flow_peak"] = pd.to_numeric(events.get("flow_peak", np.nan), errors="coerce")
    events = events.sort_values("date_peak").reset_index(drop=True)
    events["event_id"] = np.arange(1, len(events) + 1, dtype=np.int64)

    print(f"Events loaded: {len(events)}")
    print(f"First date_peak: {events['date_peak'].min()}")
    print(f"Last date_peak : {events['date_peak'].max()}")

    return events


def load_stage(stage_fp: Path) -> pd.DataFrame:
    print("=" * 100)
    print("LOADING STAGE")
    print("=" * 100)

    stage = pd.read_parquet(stage_fp, columns=["datetime", "Stage_ft"])
    stage["datetime"] = pd.to_datetime(stage["datetime"], errors="coerce").map(to_naive_timestamp)
    stage["Stage_ft"] = pd.to_numeric(stage["Stage_ft"], errors="coerce")
    stage = stage.dropna(subset=["datetime"]).sort_values("datetime").reset_index(drop=True)

    if stage.empty:
        raise ValueError(f"Stage parquet has no valid rows: {stage_fp}")

    print(f"Stage rows loaded: {len(stage)}")
    print(f"First stage datetime: {stage['datetime'].min()}")
    print(f"Last stage datetime : {stage['datetime'].max()}")

    return stage


def load_meta(meta_fp: Path) -> tuple[float, float]:
    print("=" * 100)
    print("LOADING GAUGE LOCATION")
    print("=" * 100)

    with open(meta_fp, "r", encoding="utf-8") as f:
        meta = json.load(f)

    lon, lat = meta["geometry"]["coordinates"][:2]
    gauge_lat, gauge_lon = float(lat), float(lon)

    print(f"Gauge latitude : {gauge_lat}")
    print(f"Gauge longitude: {gauge_lon}")

    return gauge_lat, gauge_lon


def load_rain_zarr(zarr_fp: Path) -> dict[str, np.ndarray | pd.DatetimeIndex]:
    print("=" * 100)
    print("LOADING RAIN ZARR")
    print("=" * 100)

    root = zarr.open_group(str(zarr_fp), mode="r")

    time_raw = root["time"][:]
    lat = np.asarray(root["lat"][:], dtype=np.float64)
    lon = np.asarray(root["lon"][:], dtype=np.float64)
    rain = np.asarray(root["rain"][:], dtype=np.float32)

    if np.issubdtype(time_raw.dtype, np.datetime64):
        time = pd.to_datetime(time_raw)
    elif np.issubdtype(time_raw.dtype, np.integer):
        time = pd.to_datetime(time_raw.astype("int64"), unit="ns")
    else:
        time = pd.to_datetime(time_raw.astype("U"), errors="coerce")

    time = pd.DatetimeIndex(time).map(to_naive_timestamp)
    rain = np.where(np.isfinite(rain), rain, 0.0).astype(np.float32, copy=False)

    print(f"Rain shape  : {rain.shape}")
    print(f"Pixels      : {rain.shape[1]}")
    print(f"Time steps  : {rain.shape[0]}")
    print(f"Start time  : {time.min()}")
    print(f"End time    : {time.max()}")

    return {
        "time": time,
        "lat": lat,
        "lon": lon,
        "rain": rain,
    }


# ======================================================================================
# STEP 1. MATCH
# ======================================================================================

def build_match(events: pd.DataFrame, rain_time: pd.DatetimeIndex, rain: np.ndarray) -> pd.DataFrame:
    print("=" * 100)
    print("STEP 1 | MATCH")
    print("=" * 100)

    matched = events.copy()
    matched["prev_stage_peak_time"] = matched["date_peak"].shift(1)
    matched["effective_start_rain"] = matched[["start_rain", "prev_stage_peak_time"]].max(axis=1)
    matched["effective_start_rain"] = matched["effective_start_rain"].fillna(matched["start_rain"])
    matched["overlap_trimmed"] = matched["effective_start_rain"] > matched["start_rain"]

    r0, r1 = build_window_indices(rain_time, matched["effective_start_rain"], matched["date_peak"])
    matched["rain_window_start_idx"] = r0
    matched["rain_window_end_idx"] = r1
    matched["rain_window_n_steps"] = np.maximum(r1 - r0, 0).astype(np.int32)

    has_positive = np.fromiter(
        ((b > a) and np.any(rain[a:b] > 0.0) for a, b in zip(r0, r1)),
        dtype=bool,
        count=len(matched),
    )
    matched["window_has_positive_rain"] = has_positive

    print(f"Total events                    : {len(matched)}")
    print(f"Events trimmed                  : {int(matched['overlap_trimmed'].sum())}")
    print(f"Events with positive rain       : {int(matched['window_has_positive_rain'].sum())}")
    print(f"Events without positive rain    : {int((~matched['window_has_positive_rain']).sum())}")

    return matched


# ======================================================================================
# STEP 2-7. COMPUTE COMPACT EWS METRICS
# ======================================================================================

def compute_compact_ews_arrays(
    *,
    site_id: str,
    matched: pd.DataFrame,
    stage_df: pd.DataFrame,
    rain_time: pd.DatetimeIndex,
    rain: np.ndarray,
    pixel_lat: np.ndarray,
    pixel_lon: np.ndarray,
    gauge_lat: float,
    gauge_lon: float,
) -> dict[str, np.ndarray]:
    print("=" * 100)
    print("STEP 2-7 | COMPUTING COMPACT EWS METRICS")
    print("=" * 100)

    n_events = len(matched)
    n_pixels = rain.shape[1]

    peak_times = matched["date_peak"].to_numpy(dtype="datetime64[ns]")
    start_times = matched["effective_start_rain"].to_numpy(dtype="datetime64[ns]")
    rain_time_arr = rain_time.to_numpy(dtype="datetime64[ns]")

    stage_time = pd.DatetimeIndex(stage_df["datetime"])
    stage_vals = stage_df["Stage_ft"].to_numpy(dtype=np.float64)

    s0, _ = build_window_indices(stage_time, matched["effective_start_rain"], matched["date_peak"])
    flow_start = np.full(n_events, np.nan, dtype=np.float64)

    valid_stage = s0 < len(stage_vals)
    clipped_stage_idx = np.clip(s0, 0, max(len(stage_vals) - 1, 0))
    flow_start[valid_stage] = stage_vals[clipped_stage_idx[valid_stage]]

    flow_peak = matched["flow_peak"].to_numpy(dtype=np.float64)
    delta_flow = flow_peak - flow_start
    peak_time_delta = hours_between_vectorized(start_times, peak_times)

    distance_to_gauge = haversine_km(gauge_lat, gauge_lon, pixel_lat, pixel_lon).astype(np.float64)

    row_id = np.arange(1, n_events * n_pixels + 1, dtype=np.int64).reshape(n_events, n_pixels)

    max_rain = np.full((n_events, n_pixels), np.nan, dtype=np.float32)
    time_rain_to_peak = np.full((n_events, n_pixels), np.nan, dtype=np.float32)
    delta_rain_pixel_acc = np.full((n_events, n_pixels), np.nan, dtype=np.float32)

    delta_rain_event_acc = np.full(n_events, np.nan, dtype=np.float32)
    time_event_acc_to_peak = np.full(n_events, np.nan, dtype=np.float32)

    r0 = matched["rain_window_start_idx"].to_numpy(dtype=np.int64)
    r1 = matched["rain_window_end_idx"].to_numpy(dtype=np.int64)

    processed_events = 0

    for i, (a, b) in enumerate(zip(r0, r1)):
        if b <= a:
            continue

        block = np.where(rain[a:b, :] > 0.0, rain[a:b, :], 0.0)
        if not np.any(block):
            continue

        block_time = rain_time_arr[a:b]

        pixel_acc = np.cumsum(block, axis=0, dtype=np.float64)
        event_acc = np.cumsum(block.sum(axis=1, dtype=np.float64), dtype=np.float64)

        idx_max_rain = np.argmax(block, axis=0)
        idx_max_pixel_acc = np.argmax(pixel_acc, axis=0)
        idx_min_pixel_acc = np.argmin(pixel_acc, axis=0)
        idx_max_event_acc = int(np.argmax(event_acc))

        rain_peak_times = block_time[idx_max_rain]
        max_rain[i, :] = block[idx_max_rain, np.arange(n_pixels)].astype(np.float32)
        time_rain_to_peak[i, :] = hours_between_vectorized(
            rain_peak_times,
            np.full(n_pixels, peak_times[i], dtype="datetime64[ns]"),
        ).astype(np.float32)

        delta_rain_pixel_acc[i, :] = (
            pixel_acc[idx_max_pixel_acc, np.arange(n_pixels)] - pixel_acc[idx_min_pixel_acc, np.arange(n_pixels)]
        ).astype(np.float32)

        delta_rain_event_acc[i] = np.float32(event_acc[idx_max_event_acc] - event_acc.min())
        time_event_acc_to_peak[i] = np.float32(
            hours_between_vectorized(
                np.array([block_time[idx_max_event_acc]], dtype="datetime64[ns]"),
                np.array([peak_times[i]], dtype="datetime64[ns]"),
            )[0]
        )

        processed_events += 1

    print(f"Processed events with valid rain : {processed_events}")
    print(f"Event x pixel shape              : ({n_events}, {n_pixels})")
    print(f"Finite max_rain values           : {int(np.isfinite(max_rain).sum())}")
    print(f"Finite delta_rain_pixel_acc      : {int(np.isfinite(delta_rain_pixel_acc).sum())}")
    print(f"Finite delta_rain_event_acc      : {int(np.isfinite(delta_rain_event_acc).sum())}")

    return {
        "site_id": np.array([site_id], dtype=object),
        "event_id": matched["event_id"].to_numpy(dtype=np.int64),
        "date_peak": peak_times,
        "flow_peak": flow_peak.astype(np.float32),
        "delta_flow": delta_flow.astype(np.float32),
        "peak_time_delta": peak_time_delta.astype(np.float32),
        "pixel_id": np.arange(n_pixels, dtype=np.int32),
        "lat": pixel_lat.astype(np.float32),
        "long": pixel_lon.astype(np.float32),
        "distance_to_gauge": distance_to_gauge.astype(np.float32),
        "id": row_id,
        "max_rain": max_rain,
        "time_rain_to_peak": time_rain_to_peak,
        "delta_rain_pixel_acc": delta_rain_pixel_acc,
        "delta_rain_event_acc": delta_rain_event_acc,
        "time_event_acc_to_peak": time_event_acc_to_peak,
    }


# ======================================================================================
# STEP 8. EXPORT COMPACT PIXEL-ORGANIZED ZARR
# ======================================================================================

def export_compact_pixel_zarr(
    *,
    arrays: dict[str, np.ndarray],
    out_dir: Path,
    site_id: str,
) -> Path:
    print("=" * 100)
    print("STEP 8 | EXPORTING COMPACT PIXEL-ORGANIZED ZARR")
    print("=" * 100)

    out_dir.mkdir(parents=True, exist_ok=True)
    out_fp = out_dir / f"{site_id}_ews.zarr"

    if out_fp.exists():
        shutil.rmtree(out_fp)

    root = zarr.open_group(str(out_fp), mode="w")
    root.attrs["description"] = (
        "Compact pixel-organized EWS dataset with only operational variables."
    )
    root.attrs["site_id"] = site_id
    root.attrs["layout"] = "pixel -> events"
    root.attrs["schema"] = [
        "id",
        "event_id",
        "lat",
        "long",
        "distance_to_gauge",
        "date_peak",
        "flow_peak",
        "delta_flow",
        "peak_time_delta",
        "max_rain",
        "time_rain_to_peak",
        "delta_rain_pixel_acc",
        "delta_rain_event_acc",
        "time_event_acc_to_peak",
    ]
    root.attrs["n_events"] = int(len(arrays["event_id"]))
    root.attrs["n_pixels"] = int(len(arrays["pixel_id"]))

    n_events = len(arrays["event_id"])
    n_pixels = len(arrays["pixel_id"])

    # Root-level lookup arrays
    root.create_array("pixel_id", data=arrays["pixel_id"], chunks=(min(n_pixels, 1024),), overwrite=True)
    root.create_array("lat", data=arrays["lat"], chunks=(min(n_pixels, 1024),), overwrite=True)
    root.create_array("long", data=arrays["long"], chunks=(min(n_pixels, 1024),), overwrite=True)
    root.create_array("distance_to_gauge", data=arrays["distance_to_gauge"], chunks=(min(n_pixels, 1024),), overwrite=True)

    root.create_array("event_id", data=arrays["event_id"], chunks=(min(n_events, 512),), overwrite=True)
    root.create_array("date_peak", data=arrays["date_peak"], chunks=(min(n_events, 512),), overwrite=True)
    root.create_array("flow_peak", data=arrays["flow_peak"], chunks=(min(n_events, 512),), overwrite=True)
    root.create_array("delta_flow", data=arrays["delta_flow"], chunks=(min(n_events, 512),), overwrite=True)
    root.create_array("peak_time_delta", data=arrays["peak_time_delta"], chunks=(min(n_events, 512),), overwrite=True)
    root.create_array("delta_rain_event_acc", data=arrays["delta_rain_event_acc"], chunks=(min(n_events, 512),), overwrite=True)
    root.create_array("time_event_acc_to_peak", data=arrays["time_event_acc_to_peak"], chunks=(min(n_events, 512),), overwrite=True)

    pixels_group = root.create_group("pixels", overwrite=True)

    for pix in range(n_pixels):
        g = pixels_group.create_group(f"{pix:06d}", overwrite=True)

        lat_scalar = np.float32(arrays["lat"][pix])
        lon_scalar = np.float32(arrays["long"][pix])
        dist_scalar = np.float32(arrays["distance_to_gauge"][pix])

        g.attrs["pixel_id"] = int(arrays["pixel_id"][pix])
        g.attrs["lat"] = float(lat_scalar)
        g.attrs["long"] = float(lon_scalar)
        g.attrs["distance_to_gauge_km"] = float(dist_scalar)

        g.create_array("id", data=arrays["id"][:, pix], chunks=(min(n_events, 512),), overwrite=True)
        g.create_array("event_id", data=arrays["event_id"], chunks=(min(n_events, 512),), overwrite=True)
        g.create_array("lat", data=np.full(n_events, lat_scalar, dtype=np.float32), chunks=(min(n_events, 512),), overwrite=True)
        g.create_array("long", data=np.full(n_events, lon_scalar, dtype=np.float32), chunks=(min(n_events, 512),), overwrite=True)
        g.create_array("distance_to_gauge", data=np.full(n_events, dist_scalar, dtype=np.float32), chunks=(min(n_events, 512),), overwrite=True)
        g.create_array("date_peak", data=arrays["date_peak"], chunks=(min(n_events, 512),), overwrite=True)
        g.create_array("flow_peak", data=arrays["flow_peak"], chunks=(min(n_events, 512),), overwrite=True)
        g.create_array("delta_flow", data=arrays["delta_flow"], chunks=(min(n_events, 512),), overwrite=True)
        g.create_array("peak_time_delta", data=arrays["peak_time_delta"], chunks=(min(n_events, 512),), overwrite=True)
        g.create_array("max_rain", data=arrays["max_rain"][:, pix], chunks=(min(n_events, 512),), overwrite=True)
        g.create_array("time_rain_to_peak", data=arrays["time_rain_to_peak"][:, pix], chunks=(min(n_events, 512),), overwrite=True)
        g.create_array("delta_rain_pixel_acc", data=arrays["delta_rain_pixel_acc"][:, pix], chunks=(min(n_events, 512),), overwrite=True)
        g.create_array("delta_rain_event_acc", data=arrays["delta_rain_event_acc"], chunks=(min(n_events, 512),), overwrite=True)
        g.create_array("time_event_acc_to_peak", data=arrays["time_event_acc_to_peak"], chunks=(min(n_events, 512),), overwrite=True)

    print(f"Output written to: {out_fp}")
    print(f"Pixel groups created: {n_pixels}")
    print(f"Events stored per pixel: {n_events}")

    return out_fp


# ======================================================================================
# MAIN
# ======================================================================================

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Build a compact pixel-organized site_id_ews.zarr for operational early warning queries."
    )
    ap.add_argument(
        "--base",
        type=str,
        default="/data/repository_code/original_code/data",
        help="Base folder containing events/, stage_parquet/, rain_zarr/, site_meta/.",
    )
    ap.add_argument(
        "--site",
        type=str,
        required=True,
        help="USGS site id.",
    )
    ap.add_argument(
        "--out-dir",
        type=str,
        required=True,
        help="Output folder where site_id_ews.zarr will be written.",
    )
    args = ap.parse_args()

    base = Path(args.base)
    site_id = args.site.strip()
    out_dir = Path(args.out_dir)

    print("=" * 100)
    print("INPUT FILES")
    print("=" * 100)

    paths = find_site_paths(base, site_id)
    for key, value in paths.items():
        print(f"{key:10s}: {value}")

    events = load_events(paths["events_fp"])
    stage_df = load_stage(paths["stage_fp"])
    gauge_lat, gauge_lon = load_meta(paths["meta_fp"])
    rain_data = load_rain_zarr(paths["zarr_fp"])

    matched = build_match(events, rain_data["time"], rain_data["rain"])

    arrays = compute_compact_ews_arrays(
        site_id=site_id,
        matched=matched,
        stage_df=stage_df,
        rain_time=rain_data["time"],
        rain=rain_data["rain"],
        pixel_lat=rain_data["lat"],
        pixel_lon=rain_data["lon"],
        gauge_lat=gauge_lat,
        gauge_lon=gauge_lon,
    )

    out_fp = export_compact_pixel_zarr(
        arrays=arrays,
        out_dir=out_dir,
        site_id=site_id,
    )

    print("=" * 100)
    print("FINAL SUMMARY")
    print("=" * 100)
    print(f"Site id        : {site_id}")
    print(f"Output Zarr    : {out_fp}")
    print(f"Events         : {len(arrays['event_id'])}")
    print(f"Pixels         : {len(arrays['pixel_id'])}")
    print("Schema         : compact operational EWS")
    print("Done.")


if __name__ == "__main__":
    main()