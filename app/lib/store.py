from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from .databricks import (
    execute_many,
    execute_sql,
    json_literal,
    read_sql,
    safe_error,
    source_table_name,
    sql_literal,
    target_table_name,
    use_unity_catalog_source,
    use_unity_catalog_state,
)


APP_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = APP_DIR.parent
STATE_DIR = APP_DIR / "state"
SCRATCHPAD_PATH = STATE_DIR / "scratchpad.md"
LAST_RUN_PATH = STATE_DIR / "last_run.json"
FACILITIES_CSV = (
    REPO_DIR
    / "data/raw/databricks_virtue_foundation_dataset_dais_2026/virtue_foundation_dataset/facilities/facilities.csv.gz"
)


DEFAULT_SCRATCHPAD = """# Data readiness notes

Use this scratchpad as the planner/data-steward working memory.

## Current focus

- Prioritize duplicate facility clusters that inflate coverage.
- Treat weak ICU/NICU/emergency claims as human-review items.
- Tag important notes with simple tags like #dedupe, #nicu, #emergency, #location.

## Questions to resolve

- Which source should win when facility records conflict?
- Which districts are planning-critical for the demo?
"""


def ensure_state() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    if not SCRATCHPAD_PATH.exists():
        SCRATCHPAD_PATH.write_text(DEFAULT_SCRATCHPAD, encoding="utf-8")
    if not LAST_RUN_PATH.exists():
        save_last_run({})


def demo_facilities() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "unique_id": "demo-1",
                "name": "City Care Hospital",
                "address_city": "Jaipur",
                "address_stateOrRegion": "Rajasthan",
                "address_zipOrPostcode": "302001",
                "specialties": '["emergencyMedicine", "internalMedicine"]',
                "capability": '["24x7 Emergency Services"]',
                "description": "Multispecialty hospital with emergency department.",
                "latitude": 26.9124,
                "longitude": 75.7873,
                "cluster_id": "cluster-demo-1",
                "source": "sample",
            },
            {
                "unique_id": "demo-2",
                "name": "City Care Hosp.",
                "address_city": "Jaipur",
                "address_stateOrRegion": "Rajasthan",
                "address_zipOrPostcode": "302001",
                "specialties": '["emergencyMedicine"]',
                "capability": '["Emergency"]',
                "description": "Emergency and trauma services.",
                "latitude": 26.9125,
                "longitude": 75.7874,
                "cluster_id": "cluster-demo-1",
                "source": "sample",
            },
            {
                "unique_id": "demo-3",
                "name": "North District Maternity Centre",
                "address_city": "Patna",
                "address_stateOrRegion": "Bihar",
                "address_zipOrPostcode": "",
                "specialties": '["obstetrics", "gynecology"]',
                "capability": '["Maternity", "NICU claimed"]',
                "description": "Delivery services listed; NICU evidence needs verification.",
                "latitude": "",
                "longitude": "",
                "cluster_id": "cluster-demo-2",
                "source": "sample",
            },
        ]
    )


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_scratchpad() -> str:
    if use_unity_catalog_state():
        table = target_table_name("result", "scratchpad_versions")
        try:
            rows = read_sql(
                f"""
                SELECT markdown
                FROM {table}
                ORDER BY created_at DESC
                LIMIT 1
                """
            )
        except Exception:
            rows = pd.DataFrame()
        if not rows.empty and rows.iloc[0].get("markdown"):
            return str(rows.iloc[0]["markdown"])
        return DEFAULT_SCRATCHPAD

    ensure_state()
    return SCRATCHPAD_PATH.read_text(encoding="utf-8")


def save_scratchpad(markdown: str) -> None:
    if use_unity_catalog_state():
        table = target_table_name("result", "scratchpad_versions")
        now = now_iso()
        version_id = f"scratchpad-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"
        actor = os.getenv("DATABRICKS_USER", os.getenv("USER", "app"))
        tags = sorted(set(part.removeprefix("#") for part in markdown.split() if part.startswith("#")))
        execute_sql(
            f"""
            INSERT INTO {table}
            (scratchpad_version_id, parent_scratchpad_version_id, markdown, tags_json, created_at, created_by)
            VALUES (
              {sql_literal(version_id)},
              NULL,
              {sql_literal(markdown)},
              {json_literal(tags)},
              timestamp({sql_literal(now)}),
              {sql_literal(actor)}
            )
            """
        )
        return

    ensure_state()
    SCRATCHPAD_PATH.write_text(markdown, encoding="utf-8")


def load_latest_scratchpad_version_id() -> str | None:
    if not use_unity_catalog_state():
        return None
    table = target_table_name("result", "scratchpad_versions")
    try:
        rows = read_sql(
            f"""
            SELECT scratchpad_version_id
            FROM {table}
            ORDER BY created_at DESC
            LIMIT 1
            """
        )
    except Exception:
        return None
    if rows.empty:
        return None
    return str(rows.iloc[0]["scratchpad_version_id"])


def load_last_run() -> dict[str, Any]:
    if use_unity_catalog_state():
        state_table = target_table_name("result", "result_state_versions")
        actions_table = target_table_name("result", "action_recommendations")
        risks_table = target_table_name("result", "geo_risk_recommendations")
        try:
            states = read_sql(
                f"""
                SELECT state_version_id, run_id, consistency_score, expected_lift_points, created_at, metadata_json
                FROM {state_table}
                ORDER BY created_at DESC
                LIMIT 1
                """
            )
        except Exception:
            return {}
        if states.empty:
            return {}

        state = states.iloc[0]
        state_version_id = str(state["state_version_id"])
        metadata = json.loads(state.get("metadata_json") or "{}")
        run = metadata.get("run", {})
        run.setdefault("run_id", str(state["run_id"]))
        run.setdefault("ran_at", str(state["created_at"]))
        run.setdefault("profile", metadata.get("profile", {}))

        actions = read_sql(
            f"""
            SELECT action_id, priority, issue_type, recommendation, owner, confidence, status,
                   lift_points, evidence_json
            FROM {actions_table}
            WHERE state_version_id = {sql_literal(state_version_id)}
            ORDER BY priority, action_id
            """
        )
        risks = read_sql(
            f"""
            SELECT risk_id, priority, geography_value AS location, geography_value, care_need,
                   risk_label AS risk, confidence, reason AS why, look_at_json
            FROM {risks_table}
            WHERE state_version_id = {sql_literal(state_version_id)}
            ORDER BY priority, risk_id
            """
        )
        run["actions"] = [
            {
                **row,
                "evidence": json.loads(row.get("evidence_json") or "{}").get("evidence", ""),
            }
            for row in actions.fillna("").to_dict(orient="records")
        ]
        run["risks"] = [
            {
                **row,
                "state": json.loads(row.get("look_at_json") or "{}").get("state", ""),
                "look_at": json.loads(row.get("look_at_json") or "{}").get("look_at", ""),
            }
            for row in risks.fillna("").to_dict(orient="records")
        ]
        return run

    ensure_state()
    try:
        return json.loads(LAST_RUN_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def save_last_run(payload: dict[str, Any]) -> None:
    if use_unity_catalog_state():
        run_id = payload.get("run_id") or f"run-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"
        state_version_id = payload.get("state_version_id") or f"state-{run_id}"
        source_snapshot_id = payload.get("source_snapshot_id") or f"source-{run_id}"
        scratchpad_version_id = payload.get("scratchpad_version_id") or load_latest_scratchpad_version_id()
        profile = payload.get("profile", {})
        actor = os.getenv("DATABRICKS_USER", os.getenv("USER", "app"))
        now = payload.get("ran_at") or now_iso()

        state_table = target_table_name("result", "result_state_versions")
        actions_table = target_table_name("result", "action_recommendations")
        risks_table = target_table_name("result", "geo_risk_recommendations")
        parse_runs_table = target_table_name("work", "parse_runs")
        event_table = target_table_name("audit", "app_events")

        statements = [
            f"""
            INSERT INTO {parse_runs_table}
            (run_id, source_snapshot_id, scratchpad_version_id, run_status, started_at, finished_at,
             triggered_by, trigger_type, error_message, metadata_json)
            VALUES (
              {sql_literal(run_id)},
              {sql_literal(source_snapshot_id)},
              {sql_literal(scratchpad_version_id)},
              'succeeded',
              CAST({sql_literal(now)} AS TIMESTAMP),
              CAST({sql_literal(now)} AS TIMESTAMP),
              {sql_literal(actor)},
              'app_reparse',
              NULL,
              {json_literal({"profile": profile})}
            )
            """,
            f"""
            INSERT INTO {state_table}
            (state_version_id, parent_state_version_id, run_id, source_snapshot_id, scratchpad_version_id,
             state_status, consistency_score, expected_lift_points, created_at, created_by, metadata_json)
            VALUES (
              {sql_literal(state_version_id)},
              NULL,
              {sql_literal(run_id)},
              {sql_literal(source_snapshot_id)},
              {sql_literal(scratchpad_version_id)},
              'active',
              {sql_literal(profile.get("consistency_score"))},
              {sql_literal(profile.get("expected_lift"))},
              CAST({sql_literal(now)} AS TIMESTAMP),
              {sql_literal(actor)},
              {json_literal({"run": payload, "profile": profile})}
            )
            """,
        ]

        for action in payload.get("actions", []):
            statements.append(
                f"""
                INSERT INTO {actions_table}
                (state_version_id, action_id, priority, issue_type, recommendation, owner, confidence,
                 status, lift_points, evidence_json, created_at, updated_at)
                VALUES (
                  {sql_literal(state_version_id)},
                  {sql_literal(action.get("action_id"))},
                  {sql_literal(action.get("priority"))},
                  {sql_literal(action.get("issue_type"))},
                  {sql_literal(action.get("recommendation"))},
                  {sql_literal(action.get("owner"))},
                  {sql_literal(action.get("confidence"))},
                  {sql_literal(action.get("status"))},
                  {sql_literal(action.get("lift_points"))},
                  {json_literal({"evidence": action.get("evidence", "")})},
                  CAST({sql_literal(now)} AS TIMESTAMP),
                  CAST({sql_literal(now)} AS TIMESTAMP)
                )
                """
            )

        for index, risk in enumerate(payload.get("risks", []), start=1):
            risk_id = risk.get("risk_id") or f"{state_version_id}-risk-{index}"
            statements.append(
                f"""
                INSERT INTO {risks_table}
                (state_version_id, risk_id, priority, geography_level, geography_value, care_need, risk_label,
                 confidence, reason, look_at_json, created_at)
                VALUES (
                  {sql_literal(state_version_id)},
                  {sql_literal(risk_id)},
                  {sql_literal(risk.get("priority"))},
                  'state',
                  {sql_literal(risk.get("location") or risk.get("state"))},
                  {sql_literal(risk.get("care_need"))},
                  {sql_literal(risk.get("risk"))},
                  {sql_literal(risk.get("confidence"))},
                  {sql_literal(risk.get("why"))},
                  {json_literal({"state": risk.get("state"), "look_at": risk.get("look_at")})},
                  CAST({sql_literal(now)} AS TIMESTAMP)
                )
                """
            )

        statements.append(
            f"""
            INSERT INTO {event_table}
            (event_id, event_type, actor, target_type, target_id, event_json, created_at)
            VALUES (
              {sql_literal(f"event-{state_version_id}")},
              'result_state_created',
              {sql_literal(actor)},
              'state_version',
              {sql_literal(state_version_id)},
              {json_literal({"run_id": run_id, "source_snapshot_id": source_snapshot_id})},
              CAST({sql_literal(now)} AS TIMESTAMP)
            )
            """
        )
        execute_many(statements)
        return

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    LAST_RUN_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def save_action_decision(action_id: str, status: str, note: str | None = None) -> bool:
    if use_unity_catalog_state():
        state_table = target_table_name("result", "result_state_versions")
        actions_table = target_table_name("result", "action_recommendations")
        decisions_table = target_table_name("result", "action_decisions")
        event_table = target_table_name("audit", "decision_events")
        states = read_sql(
            f"""
            SELECT state_version_id
            FROM {state_table}
            ORDER BY created_at DESC
            LIMIT 1
            """
        )
        if states.empty:
            return False

        state_version_id = str(states.iloc[0]["state_version_id"])
        existing = read_sql(
            f"""
            SELECT action_id
            FROM {actions_table}
            WHERE state_version_id = {sql_literal(state_version_id)}
              AND action_id = {sql_literal(action_id)}
            LIMIT 1
            """
        )
        if existing.empty:
            return False

        now = now_iso()
        actor = os.getenv("DATABRICKS_USER", os.getenv("USER", "app"))
        decision_id = f"decision-{state_version_id}-{action_id}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"
        event_id = f"event-{decision_id}"
        execute_many(
            [
                f"""
                UPDATE {actions_table}
                SET status = {sql_literal(status)},
                    updated_at = CAST({sql_literal(now)} AS TIMESTAMP)
                WHERE state_version_id = {sql_literal(state_version_id)}
                  AND action_id = {sql_literal(action_id)}
                """,
                f"""
                INSERT INTO {decisions_table}
                (decision_id, state_version_id, action_id, decision, decision_note, decided_at, decided_by)
                VALUES (
                  {sql_literal(decision_id)},
                  {sql_literal(state_version_id)},
                  {sql_literal(action_id)},
                  {sql_literal(status)},
                  {sql_literal(note or "")},
                  CAST({sql_literal(now)} AS TIMESTAMP),
                  {sql_literal(actor)}
                )
                """,
                f"""
                INSERT INTO {event_table}
                (event_id, decision_id, state_version_id, action_id, event_type, event_json, created_at)
                VALUES (
                  {sql_literal(event_id)},
                  {sql_literal(decision_id)},
                  {sql_literal(state_version_id)},
                  {sql_literal(action_id)},
                  'action_decision_saved',
                  {json_literal({"decision": status, "note": note or "", "actor": actor})},
                  CAST({sql_literal(now)} AS TIMESTAMP)
                )
                """,
            ]
        )
        return True

    run = load_last_run()
    actions = run.get("actions", [])
    for action in actions:
        if action.get("action_id") == action_id:
            action["status"] = status
            action["review_note"] = note or ""
            save_last_run(run)
            return True
    return False


def read_facilities(max_rows: int | None = None) -> pd.DataFrame:
    if use_unity_catalog_source():
        query = f"SELECT * FROM {source_table_name()}"
        if max_rows is None and os.getenv("APP_SOURCE_ROW_LIMIT"):
            max_rows = int(os.getenv("APP_SOURCE_ROW_LIMIT", "0") or "0") or None
        if max_rows is not None:
            query += f" LIMIT {int(max_rows)}"
        return read_sql(query)

    if FACILITIES_CSV.exists():
        return pd.read_csv(FACILITIES_CSV, nrows=max_rows, low_memory=False)
    return demo_facilities()


def diagnose_state_backend() -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def add_check(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"name": name, "ok": ok, "detail": detail})

    if not use_unity_catalog_source() and not use_unity_catalog_state():
        add_check("local_data_mode", True, "Using local CSV/demo source and local state.")
        add_check("local_csv_exists", FACILITIES_CSV.exists(), str(FACILITIES_CSV))
        return {"ok": all(check["ok"] for check in checks), "checks": checks}

    if use_unity_catalog_source():
        try:
            rows = read_sql(f"SELECT COUNT(*) AS row_count FROM {source_table_name()}")
            count = int(rows.iloc[0]["row_count"]) if not rows.empty else 0
            add_check("source_table_select", True, f"{source_table_name()} has {count:,} rows.")
        except Exception as exc:
            add_check("source_table_select", False, safe_error(exc))
    else:
        add_check("local_source", True, f"Using checked-in CSV/demo source at {FACILITIES_CSV}.")

    if not use_unity_catalog_state():
        add_check("local_state", True, f"Using local app state at {STATE_DIR}.")
        return {"ok": all(check["ok"] for check in checks), "checks": checks}

    result_tables = [
        target_table_name("result", "scratchpad_versions"),
        target_table_name("result", "result_state_versions"),
        target_table_name("result", "action_recommendations"),
        target_table_name("result", "geo_risk_recommendations"),
    ]
    for table in result_tables:
        try:
            read_sql(f"SELECT COUNT(*) AS row_count FROM {table}")
            add_check(f"result_table_select:{table}", True, "Readable.")
        except Exception as exc:
            add_check(f"result_table_select:{table}", False, safe_error(exc))

    return {"ok": all(check["ok"] for check in checks), "checks": checks}
