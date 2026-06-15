# Data Readiness Desk TODO

This is the working build-out checklist for future maintainers and AI agents. The current app is a FastAPI backend serving a Vite/React frontend.

Current local app:

```bash
cd app/frontend
npm install
npm run build
cd ..
../.venv/bin/uvicorn server:app --host 127.0.0.1 --port 8000
```

Open:

```text
http://127.0.0.1:8000
```

## Current State

Core files:
- `app/server.py`: FastAPI API + static React server. Includes pipeline endpoints.
- `app/frontend/src/main.jsx`: React app — three tabs, pipeline status panel with agent cards, ingest mode.
- `app/frontend/src/styles.css`: dashboard styling including agent card and badge system.
- `app/app.yaml`: Databricks App command and deployment env vars.
- `app/lib/databricks.py`: Databricks SQL / Unity Catalog helper, auth, config summary.
- `app/lib/store.py`: source/state loader — local checked-in, Unity Catalog, and demo modes.
- `app/lib/reparser.py`: mock profiler, action generator, and risk generator.
- `app/lib/llm.py`: Databricks Foundation Models via OpenAI SDK (`/serving-endpoints`).
- `app/lib/pipeline_state.py`: pipeline state shape, local JSON backend, Workspace API backend.
- `app/lib/pipeline.py`: pipeline orchestrator — local asyncio mode + Databricks Job mode.
- `app/lib/agents/`: four agents — DedupAgent (analysis + ingest), GeoAgent, ShortageAgent, RiskAgent.
- `app/jobs/run_agent.py`: Databricks Job task entrypoint for all four agents.
- `app/sql/unity_catalog_state.sql`: Unity Catalog DDL for source, work, result, audit schemas.
- `app/state/scratchpad.md`: seed Markdown scratchpad.
- `app/state/last_run.json`: generated local parse state, gitignored.
- `scripts/setup_dbx_job.py`: creates/updates the multi-task Databricks pipeline Job.
- `run.sh`: dev/deploy helper — `ui | api | dev | deploy [name] | open [name]`.
- `setup.sh`: teammate onboarding — venv, DBX profile, env setup.
- `data/raw/.../facilities/facilities.csv.gz`: downloaded facilities table.

Completed/working now:

- [x] FastAPI + React/Vite app skeleton.
- [x] Three app tabs: `Current Dataset`, `Import + Actions`, `Risk Recommendations`.
- [x] Local downloaded facilities source loads in local mode.
- [x] Current Dataset KPI cards and score bars.
- [x] Markdown scratchpad save and re-parse trigger.
- [x] Scratchpad View/Edit toggle.
- [x] Rendered scratchpad view for headings, paragraphs, bullets, and tags.
- [x] Dataset preview table.
- [x] Dataset preview search UI.
- [x] Dataset preview order-by column and asc/desc UI.
- [x] Recommendations/actions table with selected action detail.
- [x] Upload preview API for CSV/XLS/XLSX.
- [x] Mock re-parse flow regenerates profile/actions/risks.
- [x] Local Basic Auth gate, disabled by default.
- [x] Unity Catalog state DDL placeholder.
- [x] `APP_DATA_MODE=local` and `APP_DATA_MODE=unity_catalog` switch.
- [x] Unity Catalog source/target env placeholders in `app/app.yaml`.
- [x] Deploy diagnostics: `/api/config`, `/api/status`, bounded `/api/state`, and `/api/diagnostics`.
- [x] In-memory hot state cache so DBX mode keeps the dashboard clickable.
- [x] Compact backend status pill (live / refreshing / warming).
- [x] Ephemeral unsaved result state on first load when UC result tables are empty.
- [x] `run.sh` — ui / api / dev / deploy [name] / open [name].
- [x] `setup.sh` — teammate onboarding (venv, DBX CLI, profile, .env).
- [x] Databricks Apps deploy pipeline (sync + ensure_app state machine).
- [x] Multi-agent AI pipeline — DedupAgent, GeoAgent, ShortageAgent, RiskAgent.
- [x] Dual pipeline mode: local asyncio (default) + Databricks multi-task Job.
- [x] DedupAgent ingest mode — compares uploaded records against existing dataset.
- [x] Pipeline state API: `POST /api/pipeline/start`, `GET /api/pipeline/status[/{id}]`.
- [x] Pipeline status panel in UI with per-agent cards and 3-second polling.
- [x] "Run ingestion pipeline" button in Import panel — passes uploaded records to DedupAgent.
- [x] LLM via Databricks Foundation Models (`/serving-endpoints`, OpenAI-compatible).
- [x] Databricks Job setup script (`scripts/setup_dbx_job.py`).

## Priority Next Actions

Do these first for a clean demo and a handoff-friendly build:

- [ ] **P0 Demo access:** set Databricks App sharing to `Anyone in my organization can use`.
- [ ] **P0 UC setup:** review and execute `app/sql/unity_catalog_state.sql`, or choose an existing writable catalog fallback.
- [ ] **P0 DBX permissions:** verify the app/service principal can:
  - [ ] read `APP_SOURCE_CATALOG.APP_SOURCE_SCHEMA.APP_SOURCE_TABLE`
  - [ ] use the configured SQL warehouse
  - [ ] write `APP_RESULT_CATALOG.work/result/audit`
- [ ] **P0 deploy smoke:** open deployed `/api/status`, `/api/config`, `/api/state`, and `/api/diagnostics`.
- [ ] **P1 pipeline persistence:** persist agent outputs from `app/lib/agents/` into Unity Catalog work/result tables.
- [ ] **P1 risk UI:** wire RiskAgent output into the `Risk Recommendations` tab instead of mock rows.
- [ ] **P1 import staging:** add `POST /api/import/stage` and stage uploaded rows into source/work tables.
- [ ] **P2 UX polish:** split React components, add table pagination, add toasts, and add confidence/status chips.

## Phase 1: Make the Skeleton Feel Great

- [ ] Split `app/frontend/src/main.jsx` into components:
  - [ ] `CurrentDataset.jsx`
  - [ ] `ImportActions.jsx`
  - [ ] `RiskRecommendations.jsx`
  - [ ] `Metric.jsx`
  - [ ] `DataTable.jsx`
- [x] Add table sorting and text search for Dataset Preview.
- [ ] Add table sorting and text search for Recommendations and Risks.
- [ ] Add pagination or virtual scrolling for dataset preview and action rows.
- [ ] Add visible loading states for save, re-parse, upload preview, and action decisions.
- [ ] Add toast/banner feedback for save success and API errors.
- [ ] Add a richer selected-action side panel.
- [ ] Add confidence/status chips instead of raw text.
- [x] Add a Markdown preview toggle for the scratchpad.
- [ ] Add "jump to Import + Actions" behavior from Current Dataset drivers.

## Phase 2: Durable Local State

- [ ] Move action decisions from in-place `last_run.json` edits into a local audit log file.
- [ ] Add `app/state/audit_log.jsonl` for:
  - [ ] scratchpad saves
  - [ ] re-parse runs
  - [ ] upload previews
  - [ ] action decisions
  - [ ] planning notes
- [ ] Add API route `GET /api/audit`.
- [ ] Add API route `POST /api/planning-notes`.
- [ ] Add a small Audit section or drawer in the UI.
- [ ] Add undo/revert for recent action decisions.

## Phase 3: Real Profiling

- [ ] Replace mock consistency scoring with real field-level profiling.
- [ ] Compute completeness by canonical field groups:
  - [ ] identity
  - [ ] location
  - [ ] contact
  - [ ] specialties
  - [ ] capabilities
  - [ ] provenance
- [ ] Add duplicate candidate generation using:
  - [ ] normalized facility name similarity
  - [ ] cluster ID
  - [ ] phone overlap
  - [ ] PIN/city/state overlap
  - [ ] coordinate distance
  - [ ] specialty overlap
- [ ] Add contradiction detection between `specialties`, `procedure`, `equipment`, `capability`, and `description`.
- [ ] Add sparse/low-provenance source detection.
- [ ] Store profile outputs as structured records, not only summary metrics.

## Phase 4: Import Pipeline

- [ ] Add column mapping UI for uploaded XLS/XLSX/CSV.
- [ ] Add canonical schema validation.
- [ ] Add staged import storage.
- [ ] Add import duplicate check against existing facilities.
- [ ] Add "stage only" versus "merge into review queue" mode.
- [ ] Add upload source metadata:
  - [ ] source name
  - [ ] uploaded by
  - [ ] uploaded at
  - [ ] row count
  - [ ] parse errors
- [ ] Add API route `POST /api/import/stage`.

## Phase 5: Unity Catalog Persistence

- [ ] Decide deployment namespace:
  - [ ] preferred: create dedicated catalog `dais_readiness_desk`
  - [ ] fallback: create project schemas inside an existing writable catalog
- [x] Draft `app/sql/unity_catalog_state.sql`.
- [ ] Review and execute `app/sql/unity_catalog_state.sql`.
- [ ] Deploy app with `APP_SOURCE_MODE=unity_catalog` and `APP_STATE_MODE=unity_catalog`.
- [x] Split source backend mode from result/app state backend mode.
- [x] Make Databricks/Unity Catalog the default source and state mode.
- [x] Keep checked-in CSV/demo data as an explicit local/offline click-through source.
- [x] Support local app reads from Databricks catalog with local scratchpad/result state.
- [x] Add source env config:
  - [x] `APP_SOURCE_CATALOG`
  - [x] `APP_SOURCE_SCHEMA`
  - [x] `APP_SOURCE_TABLE`
- [x] Add target env config: `APP_RESULT_CATALOG`.
- [x] Add source/state mode env config:
  - [x] `APP_SOURCE_MODE`
  - [x] `APP_STATE_MODE`
- [ ] Confirm source reads work in deployed Databricks App.
- [ ] Confirm target writes work in deployed Databricks App.
- [ ] Set Databricks App sharing to `Anyone in my organization can use` for the demo workspace.
- [ ] If narrower sharing is needed, grant demo users or a demo group `CAN USE` on the Databricks App.
- [x] Document app-level `Permission Required` fix in README.
- [x] Add cheap deployment/cache status endpoint: `GET /api/status`.
- [ ] Use deployed `/api/config` to verify app env:
  - [ ] `data_mode=unity_catalog`
  - [ ] `source_mode=unity_catalog`
  - [ ] `state_mode=unity_catalog`
  - [ ] source catalog/schema/table are correct
  - [ ] result catalog is correct
  - [ ] SQL warehouse is configured
  - [ ] host is configured
- [ ] Keep Marketplace/source catalog read-only.
- [x] Treat source state and resulting state separately in app configuration:
  - [x] source state can come from checked-in data or Databricks catalog
  - [x] resulting state can be local files or Unity Catalog tables
  - [x] recommendations/actions/risks are computed from the current resulting parse state
- [ ] Define Bronze tables:
  - [ ] `source.source_snapshots`
  - [ ] `source.raw_facilities_snapshot`
  - [ ] `source.raw_uploaded_files`
  - [ ] `source.raw_uploaded_rows`
- [ ] Define Silver tables:
  - [ ] `work.parse_runs`
  - [ ] `work.facility_records_normalized`
  - [ ] `work.facility_duplicate_candidates`
  - [ ] `work.facility_entity_clusters`
  - [ ] `work.facility_capability_evidence`
  - [ ] `work.data_quality_findings`
- [ ] Define Gold tables:
  - [ ] `result.result_state_versions`
  - [ ] `result.facility_entities`
  - [ ] `result.readiness_kpi_snapshot`
  - [ ] `result.action_recommendations`
  - [ ] `result.geo_risk_recommendations`
  - [ ] `result.scratchpad_versions`
  - [ ] `result.reviewer_notes`
  - [ ] `result.action_decisions`
- [ ] Define audit tables:
  - [ ] `audit.app_events`
  - [ ] `audit.reparse_events`
  - [ ] `audit.import_events`
  - [ ] `audit.decision_events`
- [ ] Add version IDs everywhere:
  - [ ] `source_snapshot_id`
  - [ ] `scratchpad_version_id`
  - [ ] `run_id`
  - [ ] `state_version_id`
- [x] Add Databricks SQL connector helper in `app/lib/databricks.py`.
- [x] Add code path to read/write result state from Unity Catalog when `APP_STATE_MODE=unity_catalog`.
- [ ] Validate Unity Catalog write path against real workspace permissions.
- [ ] Replace local `last_run.json` entirely in deployed mode.
- [ ] Persist scratchpad revisions and notes in Unity Catalog.
- [ ] Persist action decisions with actor and timestamp.
- [ ] Persist hot-cache fallback events or backend warmup status to audit/telemetry.

## Phase 6: Databricks Agent Backend / Worker Flow ✅ (core done)

The multi-agent AI pipeline is implemented. Agents run locally (asyncio) or via Databricks multi-task Job.

Current agents (`app/lib/agents/`):

- [x] **DedupAgent** — analysis mode (cluster dedup) + ingest mode (incoming vs existing)
- [x] **GeoAgent** — geographic quality + coverage gap detection
- [x] **ShortageAgent** — care shortage analysis by state/care type
- [x] **RiskAgent** — synthesizes all upstream outputs into risk matrix + readiness scores

Remaining agent work:

- [ ] Persist agent outputs to Unity Catalog after pipeline completes:
  - [ ] DedupAgent → `work.facility_duplicate_candidates`
  - [ ] GeoAgent → `work.data_quality_findings` (geo section)
  - [ ] ShortageAgent → `result.geo_risk_recommendations`
  - [ ] RiskAgent → `result.readiness_kpi_snapshot` + `result.action_recommendations`
- [ ] Wire RiskAgent output into the `Risk Recommendations` tab (currently shows mock data).
- [ ] Add retry for failed pipeline runs.
- [ ] Add `GET /api/pipeline/history` to list past runs.
- [ ] Test Databricks Job mode end-to-end (requires `setup_dbx_job.py` run + deploy).

Pipeline setup steps (one-time per workspace):

```bash
python scripts/setup_dbx_job.py
./run.sh deploy
# Then set PIPELINE_MODE=databricks in .env to use Databricks Job mode
```

## Phase 7: AI Evidence Extraction

- [x] Configure Databricks Foundation Models client in `app/lib/llm.py`.
- [ ] Verify available Mosaic AI / model serving endpoint in the deployed workspace.
- [ ] Create prompt for capability extraction from free text.
- [ ] Extract evidence for:
  - [ ] ICU
  - [ ] NICU
  - [ ] Emergency
  - [ ] Maternity
  - [ ] Trauma
  - [ ] Oncology
  - [ ] Dialysis
  - [ ] Surgery
  - [ ] Radiology
  - [ ] Blood bank
- [ ] Classify each claim:
  - [ ] strong
  - [ ] partial
  - [ ] weak
  - [ ] suspicious
  - [ ] none
- [ ] Store snippets and confidence separately from conclusions.
- [ ] Add evidence drawer in UI with source snippets.
- [ ] Add human confirmation workflow for low/medium confidence claims.

## Phase 8: Risk Recommendations

- [ ] Replace mock risk rows with trust-weighted geographic aggregates.
- [ ] Support filters:
  - [ ] state
  - [ ] district
  - [ ] city
  - [ ] PIN code
  - [ ] capability/care need
  - [ ] confidence
- [ ] Add duplicate-adjusted coverage counts.
- [ ] Add sparse-data penalty.
- [ ] Add "real gap" versus "data-poor" label.
- [ ] Add export/save for risk recommendations.
- [ ] Add map only after coordinate quality is good enough.

## Phase 9: Databricks App Deployment

- [x] Confirm `app/app.yaml` command starts the deployed Databricks App shell.
- [ ] Decide whether frontend build artifacts should be committed or built during deploy.
- [x] Add deployment/data-mode instructions to README.
- [x] Add environment variable documentation.
- [x] Confirm Databricks App permission gate behavior (`Permission Required` before FastAPI).
- [x] Document `Anyone in my organization can use` for demo sharing.
- [ ] Decide whether app-level Basic Auth is still needed after Databricks App sharing:
  - [ ] set `APP_BASIC_AUTH_ENABLED=true`
  - [ ] set `APP_BASIC_AUTH_USERNAME`
  - [ ] set `APP_BASIC_AUTH_PASSWORD` from a Databricks secret
  - [ ] verify `/api/health` remains available for smoke tests
  - [ ] verify app and `/api/state` return `401` without credentials
- [ ] Confirm app can read Unity Catalog tables with app/service principal permissions.
- [x] Add basic smoke-test/status endpoints for deployment checks:
  - [x] `GET /api/health`
  - [x] `GET /api/status`
  - [x] `GET /api/config`
  - [x] `GET /api/diagnostics`

## Known Issues / Notes

- [ ] `npm install` reported 2 high-severity audit findings. Review with `npm audit` before production use.
- [ ] Current frontend is intentionally dependency-light; add table libraries only if custom tables become too limiting.
- [ ] Legacy `POST /api/reparse` is still synchronous/prototype; durable agent flow should use `POST /api/pipeline/start`.
- [ ] Pipeline outputs are not yet persisted into Unity Catalog result/work tables.
- [ ] Hot in-memory cache is process-local; use UC/state tables as source of truth for multi-user review.
- [ ] Current action generation is mock/prototype logic. Do not treat recommendations as final planning evidence yet.

## Useful Commands

Python checks:

```bash
uv sync
.venv/bin/python -m compileall app/server.py app/lib scripts
.venv/bin/python -c "from app.server import state; import asyncio; s=asyncio.run(state()); print(s['run']['profile']['row_count'], len(s['run']['actions']), len(s['run']['risks']))"
```

Frontend checks:

```bash
cd app/frontend
npm install
npm run build
```

Local API smoke test:

```bash
cd app
../.venv/bin/uvicorn server:app --host 127.0.0.1 --port 8000
curl -s http://127.0.0.1:8000/api/health
curl -s http://127.0.0.1:8000/api/state
```
