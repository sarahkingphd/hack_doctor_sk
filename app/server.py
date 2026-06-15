from __future__ import annotations

import asyncio
import io
import os
import secrets
import sys
import threading
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

if str(APP_DIR := Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from lib.databricks import app_config_summary, fallback_on_state_error, source_table_name, use_unity_catalog_source
from lib import pipeline as pl
from lib.reparser import annotate_preview, run_reparse
from lib.store import (
    DEFAULT_SCRATCHPAD,
    demo_facilities,
    diagnose_state_backend,
    load_last_run,
    load_scratchpad,
    read_facilities,
    save_action_decision,
    save_scratchpad,
)


FRONTEND_DIST = APP_DIR / "frontend" / "dist"
FRONTEND_INDEX = FRONTEND_DIST / "index.html"
STATE_CACHE: dict[str, Any] = {"state": None, "last_error": "", "refreshing": False}
STATE_CACHE_LOCK = threading.Lock()

app = FastAPI(title="Data Readiness Desk", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _basic_auth_enabled() -> bool:
    setting = os.getenv("APP_BASIC_AUTH_ENABLED", "").strip().lower()
    if setting in {"1", "true", "yes", "on"}:
        return True
    if setting in {"0", "false", "no", "off"}:
        return False
    return bool(os.getenv("APP_BASIC_AUTH_USERNAME") and os.getenv("APP_BASIC_AUTH_PASSWORD"))


def _unauthorized() -> Response:
    realm = os.getenv("APP_BASIC_AUTH_REALM", "Data Readiness Desk")
    return Response(
        "Authentication required",
        status_code=401,
        headers={"WWW-Authenticate": f'Basic realm="{realm}"'},
    )


@app.middleware("http")
async def basic_auth_gate(request: Request, call_next):
    if request.method == "OPTIONS" or request.url.path == "/api/health" or not _basic_auth_enabled():
        return await call_next(request)

    expected_username = os.getenv("APP_BASIC_AUTH_USERNAME", "")
    expected_password = os.getenv("APP_BASIC_AUTH_PASSWORD", "")
    credentials = request.headers.get("Authorization")
    if not credentials or not credentials.startswith("Basic "):
        return _unauthorized()

    import base64

    try:
        decoded = base64.b64decode(credentials.removeprefix("Basic ").strip()).decode("utf-8")
        username, password = decoded.split(":", 1)
    except Exception:
        return _unauthorized()

    valid_username = secrets.compare_digest(username, expected_username)
    valid_password = secrets.compare_digest(password, expected_password)
    if not (valid_username and valid_password):
        return _unauthorized()

    return await call_next(request)


class ScratchpadPayload(BaseModel):
    markdown: str


class ActionDecisionPayload(BaseModel):
    status: str
    note: str | None = None


def _state_cache_enabled() -> bool:
    setting = os.getenv("APP_STATE_CACHE_ENABLED", "").strip().lower()
    if setting in {"1", "true", "yes", "on"}:
        return True
    if setting in {"0", "false", "no", "off"}:
        return False
    return True


def _get_cached_state() -> dict[str, Any] | None:
    with STATE_CACHE_LOCK:
        state = STATE_CACHE.get("state")
        return dict(state) if isinstance(state, dict) else None


def _set_cached_state(state: dict[str, Any], error: str = "") -> None:
    with STATE_CACHE_LOCK:
        STATE_CACHE["state"] = state
        STATE_CACHE["last_error"] = error


def _mark_refreshing(refreshing: bool) -> None:
    with STATE_CACHE_LOCK:
        STATE_CACHE["refreshing"] = refreshing


def _start_background_refresh() -> None:
    if not _state_cache_enabled():
        return
    with STATE_CACHE_LOCK:
        if STATE_CACHE.get("refreshing"):
            return
        STATE_CACHE["refreshing"] = True

    def refresh() -> None:
        try:
            _set_cached_state(_load_app_state(), "")
        except Exception as exc:
            with STATE_CACHE_LOCK:
                STATE_CACHE["last_error"] = f"{type(exc).__name__}: {exc}"
        finally:
            _mark_refreshing(False)

    threading.Thread(target=refresh, name="state-cache-refresh", daemon=True).start()


def _source_label() -> tuple[str, str, str]:
    if use_unity_catalog_source():
        try:
            source_name = source_table_name().replace("`", "")
            return tuple(source_name.split(".", 2))  # type: ignore[return-value]
        except Exception:
            summary = app_config_summary()
            return (
                summary.get("source_catalog") or "unknown_catalog",
                summary.get("source_schema") or "unknown_schema",
                summary.get("source_table") or "facilities",
            )
    return ("local", "state", "facilities")


def _fallback_app_state(reason: str) -> dict[str, Any]:
    df = demo_facilities()
    scratchpad = DEFAULT_SCRATCHPAD
    run = run_reparse(df, scratchpad, persist=False)
    run["ephemeral"] = True
    run["fallback"] = True
    run["source_error"] = reason
    run["backend_status"] = "warming"
    preview = annotate_preview(df).head(100).fillna("").to_dict(orient="records")
    catalog, schema, table = _source_label()
    return {
        "scratchpad": scratchpad,
        "run": run,
        "preview": preview,
        "catalog": catalog,
        "schema": schema,
        "table": table,
        "diagnostics": {
            "ok": False,
            "checks": [{"name": "state_fallback", "ok": False, "detail": reason}],
        },
    }


def _load_app_state() -> dict[str, Any]:
    diagnostics: dict[str, Any] | None = None
    source_error = ""
    try:
        df = read_facilities()
    except Exception as exc:
        if not _state_fallback_enabled():
            raise
        source_error = f"{type(exc).__name__}: {exc}"
        df = demo_facilities()

    scratchpad = DEFAULT_SCRATCHPAD if source_error else load_scratchpad()
    if source_error:
        run = {}
    else:
        try:
            run = load_last_run()
        except Exception as exc:
            if not _state_fallback_enabled():
                raise
            run = {}
            source_error = source_error or f"{type(exc).__name__}: {exc}"
    if not run.get("profile"):
        run = run_reparse(df, scratchpad, persist=False)
        run["ephemeral"] = True
    if source_error:
        run["fallback"] = True
        run["source_error"] = source_error
        run["backend_status"] = "warming"
    else:
        run["backend_status"] = "live"
    preview = annotate_preview(df).head(100).fillna("").to_dict(orient="records")
    catalog, schema, table = _source_label()
    return {
        "scratchpad": scratchpad,
        "run": run,
        "preview": preview,
        "catalog": catalog,
        "schema": schema,
        "table": table,
        "diagnostics": diagnostics,
    }


def _state_fallback_enabled() -> bool:
    return fallback_on_state_error()


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/config")
def config() -> dict[str, Any]:
    return app_config_summary()


@app.get("/api/status")
def status() -> dict[str, Any]:
    with STATE_CACHE_LOCK:
        cached = isinstance(STATE_CACHE.get("state"), dict)
        return {
            "status": "ok",
            "state_cached": cached,
            "refreshing": bool(STATE_CACHE.get("refreshing")),
            "last_error": STATE_CACHE.get("last_error", ""),
            "config": app_config_summary(),
        }


@app.get("/api/diagnostics")
async def diagnostics() -> dict[str, Any]:
    timeout = float(os.getenv("APP_STATE_LOAD_TIMEOUT_SECONDS", "20"))
    try:
        return await asyncio.wait_for(asyncio.to_thread(diagnose_state_backend), timeout=timeout)
    except TimeoutError as exc:
        raise HTTPException(
            status_code=504,
            detail=f"Timed out checking Databricks state backend after {timeout:g}s.",
        ) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Diagnostics failed: {type(exc).__name__}: {exc}") from exc


@app.get("/api/state")
async def state() -> dict[str, Any]:
    timeout = float(os.getenv("APP_STATE_LOAD_TIMEOUT_SECONDS", "20"))
    try:
        next_state = await asyncio.wait_for(asyncio.to_thread(_load_app_state), timeout=timeout)
        if _state_cache_enabled():
            _set_cached_state(next_state)
        return next_state
    except TimeoutError as exc:
        if _state_fallback_enabled():
            reason = f"Timed out loading app state after {timeout:g}s."
            cached = _get_cached_state()
            if cached:
                cached["served_from_cache"] = True
                cached.setdefault("run", {})["backend_status"] = "refreshing"
                cached["run"]["source_error"] = reason
                _start_background_refresh()
                return cached
            fallback = _fallback_app_state(reason)
            if _state_cache_enabled():
                _set_cached_state(fallback, reason)
                _start_background_refresh()
            return fallback
        raise HTTPException(
            status_code=504,
            detail=f"Timed out loading app state after {timeout:g}s. Check Unity Catalog/source table, SQL warehouse, and app permissions.",
        ) from exc
    except HTTPException:
        raise
    except Exception as exc:
        if _state_fallback_enabled():
            reason = f"Could not load app state: {type(exc).__name__}: {exc}"
            cached = _get_cached_state()
            if cached:
                cached["served_from_cache"] = True
                cached.setdefault("run", {})["backend_status"] = "refreshing"
                cached["run"]["source_error"] = reason
                _start_background_refresh()
                return cached
            fallback = _fallback_app_state(reason)
            if _state_cache_enabled():
                _set_cached_state(fallback, reason)
                _start_background_refresh()
            return fallback
        raise HTTPException(
            status_code=500,
            detail=f"Could not load app state: {type(exc).__name__}: {exc}",
        ) from exc


@app.post("/api/scratchpad")
def update_scratchpad(payload: ScratchpadPayload) -> dict[str, Any]:
    save_scratchpad(payload.markdown)
    return {"scratchpad": payload.markdown, "saved": True}


@app.post("/api/reparse")
def reparse(payload: ScratchpadPayload | None = None) -> dict[str, Any]:
    try:
        df = read_facilities()
        markdown = payload.markdown if payload else load_scratchpad()
        save_scratchpad(markdown)
        run = run_reparse(df, markdown)
    except Exception as exc:
        if not _state_fallback_enabled():
            raise
        df = demo_facilities()
        markdown = payload.markdown if payload else DEFAULT_SCRATCHPAD
        run = run_reparse(df, markdown, persist=False)
        run["ephemeral"] = True
        run["fallback"] = True
        run["source_error"] = f"Could not re-parse from Databricks backend: {type(exc).__name__}: {exc}"
    preview = annotate_preview(df).head(100).fillna("").to_dict(orient="records")
    catalog, schema, table = _source_label()
    next_state = {
        "scratchpad": markdown,
        "run": run,
        "preview": preview,
        "catalog": catalog,
        "schema": schema,
        "table": table,
        "diagnostics": None,
    }
    if _state_cache_enabled():
        _set_cached_state(next_state)
    return {"scratchpad": markdown, "run": run, "preview": preview}


@app.post("/api/import/preview")
async def import_preview(file: UploadFile = File(...)) -> dict[str, Any]:
    data = await file.read()
    suffix = Path(file.filename or "").suffix.lower()
    try:
        if suffix == ".csv":
            upload_df = pd.read_csv(io.BytesIO(data))
        elif suffix in {".xls", ".xlsx"}:
            upload_df = pd.read_excel(io.BytesIO(data))
        else:
            raise HTTPException(status_code=400, detail="Upload must be CSV, XLS, or XLSX.")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not parse upload: {exc}") from exc

    required = ["name", "address_city", "address_stateOrRegion", "address_zipOrPostcode"]
    present = [column for column in required if column in upload_df.columns]
    readiness = round((len(present) / len(required)) * 100)
    return {
        "filename": file.filename,
        "row_count": len(upload_df),
        "columns": list(upload_df.columns),
        "required_fields_present": present,
        "import_readiness": readiness,
        "preview": upload_df.head(50).fillna("").to_dict(orient="records"),
    }


class PipelineStartPayload(BaseModel):
    mode: str | None = None  # "local" | "databricks" — overrides PIPELINE_MODE env var
    incoming_records: list[dict] | None = None  # if set, dedup agent runs in ingest mode


@app.post("/api/pipeline/start")
async def pipeline_start(payload: PipelineStartPayload | None = None) -> dict[str, Any]:
    try:
        if payload and payload.mode:
            os.environ["PIPELINE_MODE"] = payload.mode
        incoming = payload.incoming_records if payload else None
        pipeline_id = await asyncio.to_thread(pl.start_pipeline, incoming_records=incoming)
        return {"pipeline_id": pipeline_id, "status": "started"}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to start pipeline: {type(exc).__name__}: {exc}") from exc


@app.get("/api/pipeline/status")
def pipeline_status_current() -> dict[str, Any]:
    state = pl.get_pipeline_status()
    if state is None:
        return {"pipeline_id": None, "status": "idle"}
    return state


@app.get("/api/pipeline/status/{pipeline_id}")
def pipeline_status(pipeline_id: str) -> dict[str, Any]:
    state = pl.get_pipeline_status(pipeline_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"Pipeline {pipeline_id!r} not found.")
    return state


@app.post("/api/actions/{action_id}/decision")
def action_decision(action_id: str, payload: ActionDecisionPayload) -> dict[str, Any]:
    if not save_action_decision(action_id=action_id, status=payload.status, note=payload.note):
        raise HTTPException(status_code=404, detail="Action not found.")
    return {"action_id": action_id, "status": payload.status, "updated": True}


if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")


@app.get("/{path:path}", response_model=None)
def serve_frontend(path: str):
    if FRONTEND_INDEX.exists():
        return FileResponse(FRONTEND_INDEX)
    return {
        "message": "Frontend build not found. Run `npm install` and `npm run build` in app/frontend.",
    }
