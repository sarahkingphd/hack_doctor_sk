#!/usr/bin/env python
"""
Databricks Job task entrypoint.

Each task in the multi-task Job runs:
    python jobs/run_agent.py <agent_name>

The pipeline_id is passed as a Databricks Job parameter and read from env:
    PIPELINE_ID  (set by the job runner via job_parameters)

State is written back via the Workspace API so the FastAPI app can read it.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure app/ is on sys.path regardless of CWD
APP_DIR = Path(__file__).resolve().parent.parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import pandas as pd

from lib import pipeline_state as ps
from lib.store import read_facilities


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python run_agent.py <agent_name>", file=sys.stderr)
        sys.exit(1)

    agent_name = sys.argv[1].lower()
    pipeline_id = os.environ.get("PIPELINE_ID") or (sys.argv[2] if len(sys.argv) > 2 else None)
    if not pipeline_id:
        print("ERROR: PIPELINE_ID env var or second CLI arg required", file=sys.stderr)
        sys.exit(1)

    print(f"[{agent_name}] pipeline={pipeline_id}")

    # Load state from workspace (written by FastAPI when job was triggered)
    state = ps.workspace_load(pipeline_id) or ps.new_pipeline(pipeline_id)
    df = read_facilities()

    # Collect upstream results from already-completed agents
    upstream: dict = {}
    for name, agent_state in state.get("agents", {}).items():
        if agent_state.get("status") == "completed" and agent_state.get("result"):
            upstream[name] = agent_state["result"]

    # Instantiate and run the requested agent
    agent = _get_agent(agent_name)
    agent.run(df, state, upstream)

    # Write updated state back to workspace
    ps.workspace_save(state)
    print(f"[{agent_name}] done — status: {state['agents'][agent_name]['status']}")


def _get_agent(name: str):
    from lib.agents import DedupAgent, GeoAgent, RiskAgent, ShortageAgent

    agents = {
        "dedup": DedupAgent,
        "geo": GeoAgent,
        "shortage": ShortageAgent,
        "risk": RiskAgent,
    }
    cls = agents.get(name)
    if cls is None:
        raise ValueError(f"Unknown agent: {name!r}. Choose from: {list(agents)}")
    return cls()


if __name__ == "__main__":
    main()
