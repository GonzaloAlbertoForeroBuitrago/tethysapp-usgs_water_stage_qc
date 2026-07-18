from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import boto3
from dotenv import load_dotenv


load_dotenv(Path(__file__).resolve().parents[2] / ".env")

BUCKET_NAME = "usgs-mrms-explorer"


def get_bucket():
    key = os.getenv("KEY")
    secret = os.getenv("SECRET")

    if not key or not secret:
        raise RuntimeError("Missing S3 credentials. Expected KEY and SECRET in the app .env file.")

    s3 = boto3.resource(
        "s3",
        aws_access_key_id=key,
        aws_secret_access_key=secret,
        region_name="us-east-1",
    )
    return s3.Bucket(BUCKET_NAME)


def download_s3_file_if_missing(*, s3_key: str, local_fp: Path) -> Path:
    local_fp = Path(local_fp)
    local_fp.parent.mkdir(parents=True, exist_ok=True)

    if local_fp.exists() and local_fp.stat().st_size > 0:
        print(f"[SKIP] exists: {local_fp}", flush=True)
        return local_fp

    bucket = get_bucket()
    print(f"[DOWNLOAD] s3://{BUCKET_NAME}/{s3_key} -> {local_fp}", flush=True)
    bucket.download_file(s3_key, str(local_fp))
    return local_fp


def _download_one_json(obj_key: str, local_fp: Path) -> Path:
    local_fp = Path(local_fp)
    local_fp.parent.mkdir(parents=True, exist_ok=True)

    if local_fp.exists() and local_fp.stat().st_size > 0:
        return local_fp

    bucket = get_bucket()
    bucket.download_file(obj_key, str(local_fp))
    return local_fp


def download_s3_prefix_jsons(
    *,
    s3_prefix: str,
    local_dir: Path,
    workers: int = 4,
) -> list[Path]:
    local_dir = Path(local_dir)
    local_dir.mkdir(parents=True, exist_ok=True)

    bucket = get_bucket()
    objects = [obj for obj in bucket.objects.filter(Prefix=s3_prefix) if obj.key.endswith(".json")]

    if not objects:
        raise FileNotFoundError(f"No JSON files found in s3://{BUCKET_NAME}/{s3_prefix}")

    tasks = []
    downloaded: list[Path] = []

    for obj in objects:
        local_fp = local_dir / Path(obj.key).name

        if local_fp.exists() and local_fp.stat().st_size > 0:
            downloaded.append(local_fp)
        else:
            tasks.append((obj.key, local_fp))

    print(
        f"[BASIN JSON] prefix=s3://{BUCKET_NAME}/{s3_prefix} "
        f"total={len(objects)} existing={len(downloaded)} to_download={len(tasks)} workers={workers}",
        flush=True,
    )

    if not tasks:
        return downloaded

    workers = max(1, min(int(workers), len(tasks)))

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(_download_one_json, obj_key, local_fp): (obj_key, local_fp)
            for obj_key, local_fp in tasks
        }

        for n, future in enumerate(as_completed(futures), start=1):
            obj_key, local_fp = futures[future]
            try:
                fp = future.result()
                downloaded.append(fp)

                if n % 25 == 0 or n == len(tasks):
                    print(f"[BASIN JSON] downloaded {n}/{len(tasks)}", flush=True)

            except Exception as e:
                raise RuntimeError(f"Failed downloading s3://{BUCKET_NAME}/{obj_key} -> {local_fp}: {e}") from e

    return downloaded


def download_flood_alert_inputs(
    *,
    base_dir: Path,
    state: str,
    workers: int = 4,
) -> dict[str, Path]:
    base_dir = Path(base_dir)
    state = state.upper()

    state_mask_fp = download_s3_file_if_missing(
        s3_key=f"state_masks/{state}_mrms_mask.npz",
        local_fp=base_dir / "state_masks" / f"{state}_mrms_mask.npz",
    )

    state_basin_index_fp = download_s3_file_if_missing(
        s3_key=f"state_basin_index/{state}_state_basin_index.npz",
        local_fp=base_dir / "state_basin_index" / f"{state}_state_basin_index.npz",
    )

    hydro_history_s3_prefix = os.getenv(
        "HYDRO_HISTORY_S3_PREFIX",
        "experiments/hydro_history_3mm_all_stage",
    ).strip("/")

    pixel_event_index_fp = download_s3_file_if_missing(
        s3_key=f"{hydro_history_s3_prefix}/state_pixel_event_index/{state}_pixel_event_index.npz",
        local_fp=base_dir / "hydro_history" / "state_pixel_event_index" / f"{state}_pixel_event_index.npz",
    )

    efficient_event_reference_fp = download_s3_file_if_missing(
        s3_key=f"{hydro_history_s3_prefix}/state_efficient_event_reference/{state}_efficient_event_reference.npz",
        local_fp=base_dir / "hydro_history" / "state_efficient_event_reference" / f"{state}_efficient_event_reference.npz",
    )

    basin_json_dir = base_dir / "basins_json" / state
    download_s3_prefix_jsons(
        s3_prefix=f"basins_json/{state}/",
        local_dir=basin_json_dir,
        workers=workers,
    )

    return {
        "state_mask_fp": state_mask_fp,
        "state_basin_index_fp": state_basin_index_fp,
        "pixel_event_index_fp": pixel_event_index_fp,
        "efficient_event_reference_fp": efficient_event_reference_fp,
        "basin_json_dir": basin_json_dir,
    }