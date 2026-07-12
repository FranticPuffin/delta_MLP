"""
delta.py Web API wrapper.

Keeps the original implementation in delta_core.py and exposes HTTP endpoints.

Usage:
    python Scripts/delta.py [original args...]
    python Scripts/delta.py --api --host 0.0.0.0 --port 8000

Main endpoints:
    GET  /health
    POST /api/delta/run
    GET  /api/delta/functions
    POST /api/delta/call/{function_name}
    POST /api/delta/dsn-data/view-periods
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import traceback
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field, field_validator


THIS_FILE = Path(__file__).resolve()
SCRIPTS_DIR = THIS_FILE.parent
PROJECT_ROOT = SCRIPTS_DIR.parent
CORE_FILE = SCRIPTS_DIR / "delta_core.py"
DSN_DATA_FILE = PROJECT_ROOT / "Data" / "dsn_data.jsonl"


class RunRequest(BaseModel):
    args: List[str] = Field(default_factory=list)
    stdin: Optional[Any] = None
    timeout: int = Field(default=300, ge=1)
    cwd: Optional[str] = None
    parse_json: bool = True


class FunctionCallRequest(BaseModel):
    args: List[Any] = Field(default_factory=list)
    kwargs: Dict[str, Any] = Field(default_factory=dict)


class AskView(BaseModel):
    start_hr: float
    end_hr: float

    @field_validator("end_hr")
    @classmethod
    def validate_window(cls, end_hr: float, info: Any) -> float:
        start_hr = info.data.get("start_hr")
        if start_hr is not None and end_hr < start_hr:
            raise ValueError("ask_view.end_hr must be greater than or equal to ask_view.start_hr")
        return end_hr


class DsnActivityViewRequest(BaseModel):
    activity_id: str
    ask_view: AskView


class DsnDataViewPeriodsRequest(BaseModel):
    mission_id: str
    activities: List[DsnActivityViewRequest] = Field(default_factory=list)


def _ensure_core_exists() -> None:
    if not CORE_FILE.exists():
        raise FileNotFoundError(
            f"Original delta implementation was not found: {CORE_FILE}. "
            "Please ensure Scripts/delta_core.py exists."
        )


def _delegate_to_original_cli() -> None:
    _ensure_core_exists()
    sys.argv[0] = str(CORE_FILE)
    runpy.run_path(str(CORE_FILE), run_name="__main__")


def _load_core_module() -> Any:
    _ensure_core_exists()
    spec = importlib.util.spec_from_file_location("delta_core_api", CORE_FILE)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module spec from {CORE_FILE}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _round_hour(value: float) -> float:
    return round(float(value), 10)


def _clip_view_periods(view_periods: Any, ask_view: AskView) -> tuple[List[Dict[str, Any]], Dict[str, int]]:
    if not isinstance(view_periods, list):
        return [], {"original": 0, "kept": 0, "deleted": 0, "clipped": 0}

    clipped_periods: List[Dict[str, Any]] = []
    clipped_count = 0

    for period in view_periods:
        if not isinstance(period, dict):
            continue

        try:
            start_hr = float(period["start_hr"])
            end_hr = float(period["end_hr"])
        except (KeyError, TypeError, ValueError):
            continue

        if start_hr > ask_view.end_hr or end_hr < ask_view.start_hr:
            continue

        new_start = max(start_hr, ask_view.start_hr)
        new_end = min(end_hr, ask_view.end_hr)

        clipped_period = dict(period)
        clipped_period["start_hr"] = _round_hour(new_start)
        clipped_period["end_hr"] = _round_hour(new_end)

        if new_start != start_hr or new_end != end_hr:
            clipped_count += 1

        clipped_periods.append(clipped_period)

    original_count = len(view_periods)
    kept_count = len(clipped_periods)
    return clipped_periods, {
        "original": original_count,
        "kept": kept_count,
        "deleted": original_count - kept_count,
        "clipped": clipped_count,
    }


def _read_dsn_data_jsonl() -> List[Dict[str, Any]]:
    if not DSN_DATA_FILE.exists():
        raise HTTPException(status_code=404, detail=f"Data file not found: {DSN_DATA_FILE}")

    records: List[Dict[str, Any]] = []
    try:
        with DSN_DATA_FILE.open("r", encoding="utf-8") as file:
            for line_no, line in enumerate(file, start=1):
                text = line.strip()
                if not text:
                    continue
                try:
                    record = json.loads(text)
                except json.JSONDecodeError as exc:
                    raise HTTPException(
                        status_code=500,
                        detail=f"Invalid JSON in {DSN_DATA_FILE} at line {line_no}: {exc}",
                    ) from exc
                if isinstance(record, dict):
                    records.append(record)
    except HTTPException:
        raise
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read {DSN_DATA_FILE}: {exc}") from exc

    return records


def _write_dsn_data_jsonl(records: List[Dict[str, Any]]) -> None:
    tmp_file = DSN_DATA_FILE.with_suffix(DSN_DATA_FILE.suffix + ".tmp")
    try:
        with tmp_file.open("w", encoding="utf-8", newline="\n") as file:
            for record in records:
                file.write(json.dumps(record, ensure_ascii=False) + "\n")
        os.replace(tmp_file, DSN_DATA_FILE)
    except OSError as exc:
        try:
            if tmp_file.exists():
                tmp_file.unlink()
        except OSError:
            pass
        raise HTTPException(status_code=500, detail=f"Failed to write {DSN_DATA_FILE}: {exc}") from exc


def update_dsn_data_view_periods(request: DsnDataViewPeriodsRequest) -> Dict[str, Any]:
    activity_windows = {item.activity_id: item.ask_view for item in request.activities}
    records = _read_dsn_data_jsonl()

    mission_found = False
    matched_activities = 0
    missing_activities = sorted(activity_windows)
    stats: Dict[str, Any] = {
        "missions_matched": 0,
        "activities_matched": 0,
        "view_periods_original": 0,
        "view_periods_kept": 0,
        "view_periods_deleted": 0,
        "view_periods_clipped": 0,
        "activity_results": [],
    }

    for record in records:
        if record.get("mission_id") != request.mission_id:
            continue

        mission_found = True
        stats["missions_matched"] += 1
        activities = record.get("activities", [])
        if not isinstance(activities, list):
            continue

        for activity in activities:
            if not isinstance(activity, dict):
                continue
            activity_id = activity.get("activity_id")
            ask_view = activity_windows.get(activity_id)
            if ask_view is None:
                continue

            before_periods = activity.get("view_periods", [])
            clipped_periods, clip_stats = _clip_view_periods(before_periods, ask_view)
            activity["view_periods"] = clipped_periods

            matched_activities += 1
            if activity_id in missing_activities:
                missing_activities.remove(activity_id)

            stats["activities_matched"] += 1
            stats["view_periods_original"] += clip_stats["original"]
            stats["view_periods_kept"] += clip_stats["kept"]
            stats["view_periods_deleted"] += clip_stats["deleted"]
            stats["view_periods_clipped"] += clip_stats["clipped"]
            stats["activity_results"].append(
                {
                    "activity_id": activity_id,
                    "ask_view": {"start_hr": ask_view.start_hr, "end_hr": ask_view.end_hr},
                    **clip_stats,
                }
            )

    if not mission_found:
        raise HTTPException(status_code=404, detail=f"mission_id not found: {request.mission_id}")
    if activity_windows and matched_activities == 0:
        raise HTTPException(
            status_code=404,
            detail=f"No requested activity_id found for mission_id: {request.mission_id}",
        )

    _write_dsn_data_jsonl(records)
    return {
        "success": True,
        "file": str(DSN_DATA_FILE),
        "mission_id": request.mission_id,
        "requested_activities": sorted(activity_windows),
        "missing_activities": missing_activities,
        **stats,
    }


def create_app() -> FastAPI:
    app = FastAPI(title="Delta API", version="1.0.0")

    @app.get("/health")
    def health() -> Dict[str, Any]:
        return {
            "status": "ok",
            "project_root": str(PROJECT_ROOT),
            "core_file": str(CORE_FILE),
            "dsn_data_file": str(DSN_DATA_FILE),
            "core_exists": CORE_FILE.exists(),
            "dsn_data_exists": DSN_DATA_FILE.exists(),
        }

    @app.post("/api/delta/run")
    def run_delta(request: RunRequest) -> Dict[str, Any]:
        _ensure_core_exists()

        cwd = Path(request.cwd).resolve() if request.cwd else PROJECT_ROOT
        if not cwd.exists() or not cwd.is_dir():
            raise HTTPException(status_code=400, detail=f"Invalid cwd: {cwd}")

        if isinstance(request.stdin, str) or request.stdin is None:
            stdin_text = request.stdin
        else:
            stdin_text = json.dumps(request.stdin, ensure_ascii=False)

        command = [sys.executable, str(CORE_FILE), *[str(arg) for arg in request.args]]

        try:
            completed = subprocess.run(
                command,
                input=stdin_text,
                text=True,
                capture_output=True,
                timeout=request.timeout,
                cwd=str(cwd),
            )
        except subprocess.TimeoutExpired as exc:
            raise HTTPException(
                status_code=504,
                detail={
                    "message": f"delta execution timed out after {request.timeout} seconds",
                    "stdout": exc.stdout,
                    "stderr": exc.stderr,
                },
            ) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail={
                    "message": "Failed to execute delta_core.py",
                    "error": str(exc),
                    "traceback": traceback.format_exc(),
                },
            ) from exc

        stdout_json: Optional[Any] = None
        if request.parse_json and completed.stdout:
            try:
                stdout_json = json.loads(completed.stdout)
            except json.JSONDecodeError:
                stdout_json = None

        return {
            "success": completed.returncode == 0,
            "return_code": completed.returncode,
            "command": command,
            "cwd": str(cwd),
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "stdout_json": stdout_json,
        }

    @app.get("/api/delta/functions")
    def list_functions() -> Dict[str, Any]:
        try:
            module = _load_core_module()
            functions = sorted(
                name
                for name, value in vars(module).items()
                if callable(value) and not name.startswith("_")
            )
            return {"functions": functions}
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail={
                    "message": "Failed to inspect delta_core.py. Use /api/delta/run if the script is not import-safe.",
                    "error": str(exc),
                    "traceback": traceback.format_exc(),
                },
            ) from exc

    @app.post("/api/delta/call/{function_name}")
    def call_function(function_name: str, request: FunctionCallRequest) -> Dict[str, Any]:
        try:
            module = _load_core_module()
            target = getattr(module, function_name, None)
            if target is None or not callable(target) or function_name.startswith("_"):
                raise HTTPException(status_code=404, detail=f"Callable not found: {function_name}")

            result = target(*request.args, **request.kwargs)
            return {"success": True, "result": jsonable_encoder(result)}
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail={
                    "message": f"Failed to call function: {function_name}",
                    "error": str(exc),
                    "traceback": traceback.format_exc(),
                },
            ) from exc

    @app.post("/api/delta/dsn-data/view-periods")
    def clip_dsn_data_view_periods(request: DsnDataViewPeriodsRequest) -> Dict[str, Any]:
        return update_dsn_data_view_periods(request)

    return app


def start_api(host: str = "0.0.0.0", port: int = 8000, reload: bool = False) -> None:
    try:
        import uvicorn
    except ImportError as exc:
        raise RuntimeError(
            "API mode requires uvicorn. Please install dependencies with: "
            "pip install fastapi uvicorn pydantic"
        ) from exc

    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))

    if reload:
        uvicorn.run(
            "delta:create_app",
            host=host,
            port=port,
            reload=True,
            reload_dirs=[str(SCRIPTS_DIR)],
            factory=True,
        )
    else:
        app = create_app()
        uvicorn.run(app, host=host, port=port)


def _parse_wrapper_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Delta wrapper. Use --api to start HTTP service; omit --api to run original delta CLI.",
        add_help=True,
    )
    parser.add_argument("--api", action="store_true", help="Start FastAPI service instead of original CLI.")
    parser.add_argument("--host", default="0.0.0.0", help="API host, default: 0.0.0.0")
    parser.add_argument("--port", type=int, default=8000, help="API port, default: 8000")
    parser.add_argument("--reload", action="store_true", help="Enable uvicorn reload in API mode.")
    args, remaining = parser.parse_known_args(argv)
    args.remaining_args = remaining
    return args


def main() -> None:
    args = _parse_wrapper_args(sys.argv[1:])
    if args.api:
        start_api(host=args.host, port=args.port, reload=args.reload)
        return

    # Preserve the original command-line behavior when --api is not supplied.
    sys.argv = [str(CORE_FILE), *args.remaining_args]
    _delegate_to_original_cli()


if __name__ == "__main__":
    main()
