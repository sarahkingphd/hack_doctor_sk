#!/usr/bin/env python
"""
Creates (or updates) the Databricks multi-task pipeline Job.

DAG:
  dedup  →  geo + shortage (parallel)  →  risk

Run once after deploy:
    python scripts/setup_dbx_job.py

Writes DATABRICKS_PIPELINE_JOB_ID to .env on success.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

# Load .env
ENV_FILE = Path(__file__).resolve().parents[1] / ".env"
if ENV_FILE.exists():
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.jobs import (
    JobCluster,
    JobSettings,
    PythonWheelTask,
    SparkPythonTask,
    Task,
    TaskDependency,
)

WORKSPACE_PATH = os.environ["DATABRICKS_WORKSPACE_PATH"]
JOB_NAME = os.environ.get("DATABRICKS_APP_NAME", "dbx-hack-doctors") + "-pipeline"


def task(
    key: str,
    depends_on: list[str] | None = None,
) -> Task:
    return Task(
        task_key=key,
        depends_on=[TaskDependency(task_key=d) for d in (depends_on or [])],
        spark_python_task=SparkPythonTask(
            python_file=f"{WORKSPACE_PATH}/jobs/run_agent.py",
            parameters=[key],
        ),
        environment_key="pipeline_env",
    )


def build_job_settings() -> JobSettings:
    return JobSettings(
        name=JOB_NAME,
        environments=[
            {
                "environment_key": "pipeline_env",
                "spec": {
                    "client": "1",
                    "dependencies": [
                        "fastapi", "uvicorn", "pandas", "openpyxl", "pyarrow",
                        "python-multipart", "databricks-sdk", "databricks-sql-connector",
                        "openai",
                    ],
                },
            }
        ],
        tasks=[
            task("dedup"),
            task("geo",      depends_on=["dedup"]),
            task("shortage", depends_on=["dedup"]),
            task("risk",     depends_on=["geo", "shortage"]),
        ],
        parameters=[
            {"name": "pipeline_id", "default": ""},
        ],
        # Serverless compute — no cluster config needed
        queue={"enabled": True},
    )


def upsert_job(w: WorkspaceClient) -> int:
    existing = [j for j in w.jobs.list(name=JOB_NAME)]
    if existing:
        job_id = existing[0].job_id
        print(f"Updating existing job '{JOB_NAME}' (id={job_id}) ...")
        w.jobs.reset(job_id=job_id, new_settings=build_job_settings())
    else:
        print(f"Creating job '{JOB_NAME}' ...")
        job = w.jobs.create(**build_job_settings().__dict__)
        job_id = job.job_id

    print(f"Job id: {job_id}")
    return job_id


def write_env(job_id: int) -> None:
    key = "DATABRICKS_PIPELINE_JOB_ID"
    text = ENV_FILE.read_text()
    if re.search(rf"^{key}=", text, re.MULTILINE):
        text = re.sub(rf"^{key}=.*", f"{key}={job_id}", text, flags=re.MULTILINE)
    else:
        text = text.rstrip() + f"\n\n# Pipeline Job\n{key}={job_id}\n"
    ENV_FILE.write_text(text)
    print(f"Written {key}={job_id} to .env")


if __name__ == "__main__":
    w = WorkspaceClient()
    job_id = upsert_job(w)
    write_env(job_id)
    print("Done. Run './run.sh deploy' then trigger via POST /api/pipeline/start")
