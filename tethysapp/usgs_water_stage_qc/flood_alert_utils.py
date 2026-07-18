from __future__ import annotations

from datetime import datetime
from pathlib import Path


def get_times_from_run_id(run_id: str) -> tuple[str, str]:
    """
    Get start/end datetimes from a run identifier.
    """
    try:
        dates = run_id.split("_")
        start_str = "_".join(dates[0:2])
        end_str = "_".join(dates[2:4])
        start_dt = datetime.strptime(start_str, "%Y%m%d_%H%M%S")
        end_dt = datetime.strptime(end_str, "%Y%m%d_%H%M%S")
        return start_dt.isoformat(), end_dt.isoformat()
    except Exception as e:
        raise ValueError(f"Invalid run_id format: {run_id}") from e

def build_run_id(start_dt: str, end_dt: str) -> str:
    """
    Build a stable run identifier from start/end datetimes.
    """
    start_fmt = datetime.fromisoformat(start_dt).strftime("%Y%m%d_%H%M%S")
    end_fmt = datetime.fromisoformat(end_dt).strftime("%Y%m%d_%H%M%S")

    return f"{start_fmt}_{end_fmt}"


def build_run_directory(
    base_dir: Path,
    state: str,
    start_dt: str,
    end_dt: str,
) -> Path:
    """
    Build the output directory for a Flood Alert run.
    """
    run_id = build_run_id(start_dt, end_dt)

    run_dir = (
        Path(base_dir)
        / "flood_alert_runs"
        / state.upper()
        / run_id
    )

    run_dir.mkdir(parents=True, exist_ok=True)

    return run_dir