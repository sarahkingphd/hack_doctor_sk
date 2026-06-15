"""
Pipeline + per-agent state management.

State is stored as JSON.  Two backends:
  - local (default): app/state/pipeline_{id}.json
  - workspace: Databricks Workspace API at {WORKSPACE_PATH}/state/pipeline_{id}.json

The FastAPI server always reads via the local backend (files synced by the app
or written by local asyncio tasks).  Databricks Job tasks use the workspace
backend to write back to the same path so the app can read them.
"""
from __future__ import annotations

import base64
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

APP_DIR = Path(__file__).resolve().parents[1]
STATE_DIR = APP_DIR / "state"

AGENT_NAMES = ["dedup", "geo", "shortage", "risk"]

# ── state shape ──────────────────────────────────────────────────────────────

def _empty_agent(name: str) -> dict:
    return {
        "name": name,
        "status": "pending",   # pending | running | completed | failed | skipped
        "started_at": None,
        "completed_at": None,
        "result": None,
        "error": None,
    }


def new_pipeline(pipeline_id: str) -> dict:
    return {
        "pipeline_id": pipeline_id,
        "status": "pending",   # pending | running | completed | failed
        "mode": os.getenv("PIPELINE_MODE", "local"),   # local | databricks
        "started_at": None,
        "completed_at": None,
        "agents": {name: _empty_agent(name) for name in AGENT_NAMES},
    }


# ── helpers ───────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _state_path(pipeline_id: str) -> Path:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    return STATE_DIR / f"pipeline_{pipeline_id}.json"


def _current_path() -> Path:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    return STATE_DIR / "pipeline_current.json"


# ── local backend ─────────────────────────────────────────────────────────────

def save(state: dict) -> None:
    pid = state["pipeline_id"]
    _state_path(pid).write_text(json.dumps(state, indent=2), encoding="utf-8")
    _current_path().write_text(json.dumps({"pipeline_id": pid}, encoding="utf-8"), encoding="utf-8")


def load(pipeline_id: str) -> dict | None:
    path = _state_path(pipeline_id)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def load_current() -> dict | None:
    cur = _current_path()
    if not cur.exists():
        return None
    meta = json.loads(cur.read_text(encoding="utf-8"))
    return load(meta.get("pipeline_id", ""))


# ── workspace backend (used by Databricks Job tasks) ─────────────────────────

def _workspace_state_path(pipeline_id: str) -> str:
    base = os.getenv("DATABRICKS_WORKSPACE_PATH", "").rstrip("/")
    if not base:
        raise RuntimeError("DATABRICKS_WORKSPACE_PATH not set — needed for workspace state.")
    return f"{base}/state/pipeline_{pipeline_id}.json"


def workspace_save(state: dict) -> None:
    """Write pipeline state to Databricks Workspace (for use inside job tasks)."""
    from databricks.sdk import WorkspaceClient
    w = WorkspaceClient()
    content = base64.b64encode(
        json.dumps(state, indent=2).encode()
    ).decode()
    pid = state["pipeline_id"]

    for path in [
        _workspace_state_path(pid),
        _workspace_state_path("current").replace("pipeline_current", "pipeline_current"),
    ]:
        w.workspace.import_(path=path, content=content, overwrite=True)

    # Also write the current pointer
    cur_content = base64.b64encode(
        json.dumps({"pipeline_id": pid}).encode()
    ).decode()
    cur_path = os.getenv("DATABRICKS_WORKSPACE_PATH", "").rstrip("/") + "/state/pipeline_current.json"
    w.workspace.import_(path=cur_path, content=cur_content, overwrite=True)


def workspace_load(pipeline_id: str) -> dict | None:
    """Read pipeline state from Databricks Workspace."""
    from databricks.sdk import WorkspaceClient
    try:
        w = WorkspaceClient()
        export = w.workspace.export(path=_workspace_state_path(pipeline_id))
        return json.loads(base64.b64decode(export.content or b"").decode())
    except Exception:
        return None


# ── mutation helpers (work on the dict in memory, then caller saves) ─────────

def start_pipeline(state: dict) -> dict:
    state["status"] = "running"
    state["started_at"] = _now()
    return state


def finish_pipeline(state: dict, failed: bool = False) -> dict:
    state["status"] = "failed" if failed else "completed"
    state["completed_at"] = _now()
    return state


def start_agent(state: dict, name: str) -> dict:
    state["agents"][name]["status"] = "running"
    state["agents"][name]["started_at"] = _now()
    return state


def finish_agent(state: dict, name: str, result: Any = None, error: str | None = None) -> dict:
    agent = state["agents"][name]
    agent["status"] = "failed" if error else "completed"
    agent["completed_at"] = _now()
    agent["result"] = result
    agent["error"] = error
    return state
