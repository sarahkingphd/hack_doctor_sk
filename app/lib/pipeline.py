"""
Pipeline orchestrator.

DAG:  dedup  →  geo + shortage (parallel)  →  risk

Two execution modes (PIPELINE_MODE env var):
  local       — asyncio tasks in the FastAPI process (default)
  databricks  — trigger a Databricks multi-task Job, poll for completion
"""
from __future__ import annotations

import asyncio
import os
from hashlib import sha1
from typing import Any

import pandas as pd

from . import pipeline_state as ps
from .agents import DedupAgent, GeoAgent, RiskAgent, ShortageAgent
from .store import read_facilities


# ── helpers ───────────────────────────────────────────────────────────────────

def _new_id() -> str:
    import time
    return sha1(str(time.time()).encode()).hexdigest()[:10]


def pipeline_mode() -> str:
    return os.getenv("PIPELINE_MODE", "local").strip().lower()


# ── local async execution ─────────────────────────────────────────────────────

def _run_agent_sync(agent, df: pd.DataFrame, state: dict, upstream: dict) -> dict:
    """Run a single agent synchronously (called from asyncio executor)."""
    return agent.run(df, state, upstream)


async def _run_pipeline_local(pipeline_id: str) -> None:
    """Full pipeline in asyncio — dedup, then geo+shortage parallel, then risk."""
    state = ps.load(pipeline_id)
    if state is None:
        return

    ps.start_pipeline(state)
    ps.save(state)

    # Seed upstream with any context stored in state (e.g. incoming_records for ingest mode)
    upstream: dict[str, Any] = dict(state.get("context", {}))

    loop = asyncio.get_event_loop()
    df = await loop.run_in_executor(None, read_facilities)

    try:
        # ── stage 1: dedup (or ingest, if incoming_records in upstream) ─────
        dedup_result = await loop.run_in_executor(
            None, _run_agent_sync, DedupAgent(), df, state, upstream
        )
        upstream["dedup"] = dedup_result

        # ── stage 2: geo + shortage in parallel ────────────────────────────
        geo_task = loop.run_in_executor(
            None, _run_agent_sync, GeoAgent(), df, state, dict(upstream)
        )
        shortage_task = loop.run_in_executor(
            None, _run_agent_sync, ShortageAgent(), df, state, dict(upstream)
        )
        geo_result, shortage_result = await asyncio.gather(geo_task, shortage_task)
        upstream["geo"] = geo_result
        upstream["shortage"] = shortage_result

        # ── stage 3: risk ───────────────────────────────────────────────────
        risk_result = await loop.run_in_executor(
            None, _run_agent_sync, RiskAgent(), df, state, upstream
        )
        upstream["risk"] = risk_result

        ps.finish_pipeline(state)
        ps.save(state)

    except Exception as exc:
        ps.finish_pipeline(state, failed=True)
        ps.save(state)
        raise


# ── databricks job execution ──────────────────────────────────────────────────

def _trigger_databricks_job(pipeline_id: str) -> str:
    """Trigger the pipeline Databricks Job and return the run_id."""
    from databricks.sdk import WorkspaceClient
    w = WorkspaceClient()

    job_id = os.getenv("DATABRICKS_PIPELINE_JOB_ID")
    if not job_id:
        raise RuntimeError(
            "DATABRICKS_PIPELINE_JOB_ID not set. Run: python scripts/setup_dbx_job.py"
        )

    run = w.jobs.run_now(
        job_id=int(job_id),
        job_parameters={"pipeline_id": pipeline_id},
    )
    return str(run.run_id)


async def _poll_databricks_job(pipeline_id: str, run_id: str) -> None:
    """Poll the Databricks Job run and mirror task states into pipeline state."""
    from databricks.sdk import WorkspaceClient
    from databricks.sdk.service.jobs import RunLifeCycleState

    w = WorkspaceClient()
    task_to_agent = {"dedup": "dedup", "geo": "geo", "shortage": "shortage", "risk": "risk"}

    while True:
        await asyncio.sleep(10)
        run = w.jobs.get_run(run_id=int(run_id))
        state = ps.load(pipeline_id) or {}

        for task in run.tasks or []:
            agent_name = task_to_agent.get(task.task_key)
            if not agent_name:
                continue
            lc = task.state.life_cycle_state if task.state else None
            result_state = task.state.result_state if task.state else None

            if lc == RunLifeCycleState.RUNNING:
                ps.start_agent(state, agent_name)
            elif lc == RunLifeCycleState.TERMINATED:
                if str(result_state) == "RunResultState.SUCCESS":
                    # Result is written to workspace state file by the task
                    ws_state = ps.workspace_load(pipeline_id)
                    if ws_state:
                        state["agents"][agent_name] = ws_state["agents"].get(agent_name, state["agents"][agent_name])
                else:
                    ps.finish_agent(state, agent_name, error=f"Job task failed: {result_state}")

        ps.save(state)

        lc = run.state.life_cycle_state if run.state else None
        if lc in (RunLifeCycleState.TERMINATED, RunLifeCycleState.SKIPPED, RunLifeCycleState.INTERNAL_ERROR):
            failed = str(run.state.result_state) != "RunResultState.SUCCESS"
            ps.finish_pipeline(state, failed=failed)
            ps.save(state)
            break


# ── public API ────────────────────────────────────────────────────────────────

def start_pipeline(incoming_records: list[dict] | None = None) -> str:
    """
    Create a new pipeline, persist initial state, kick off execution.
    Returns the pipeline_id immediately; execution is async.

    If incoming_records is provided, the dedup agent runs in ingest mode:
    it compares the incoming records against the existing dataset instead of
    deduplicating within the existing dataset.
    """
    pipeline_id = _new_id()
    state = ps.new_pipeline(pipeline_id)
    if incoming_records:
        state["context"] = {"incoming_records": incoming_records}
        state["mode"] = "ingest"
    ps.save(state)

    if pipeline_mode() == "databricks":
        run_id = _trigger_databricks_job(pipeline_id)
        state["dbx_run_id"] = run_id
        ps.save(state)
        asyncio.create_task(_poll_databricks_job(pipeline_id, run_id))
    else:
        asyncio.create_task(_run_pipeline_local(pipeline_id))

    return pipeline_id


def get_pipeline_status(pipeline_id: str | None = None) -> dict | None:
    """Return the current (or most recent) pipeline state."""
    if pipeline_id:
        return ps.load(pipeline_id)
    return ps.load_current()
