# dbx_hack_doctors

DBX 2026 hackathon workspace tooling.

This repo is configured for local exploration of this Databricks workspace:

- Workspace ID: `7474647758171864`
- Cloud/region: `aws:us-west-2`
- Workspace UUID: `22b8448d-6839-4df9-9ec6-99001c769190`
- Workspace host: `https://dbc-46f0fbb0-0c1c.cloud.databricks.com`
- Local profile name: `dbx_hack_doctors`
- Catalog: `databricks_virtue_foundation_dataset_dais_2026`
- Schema: `virtue_foundation_dataset`
- Example table: `nfhs_5_district_health_indicators`

If your Databricks browser URL changes, put the current browser URL in `.env`.

## Setup

Install the local Python dependency:

```bash
uv sync
```

Create local environment config:

```bash
cp .env.example .env
```

Preferred auth is Databricks OAuth with the Databricks CLI:

```bash
databricks auth login \
  --host https://dbc-46f0fbb0-0c1c.cloud.databricks.com \
  --profile dbx_hack_doctors
```

If the CLI is not installed yet:

```bash
brew install databricks
```

Personal access token auth also works. Add `DATABRICKS_TOKEN` to `.env`, then run scripts with `--use-env-auth`.

## Explore

OAuth/profile auth:

```bash
uv run python scripts/explore_workspace.py
```

Token/env auth:

```bash
uv run python scripts/explore_workspace.py --use-env-auth
```

The explorer prints the signed-in user plus visible clusters, SQL warehouses, jobs, Unity Catalog catalogs, and workspace root objects. Some sections may be unavailable depending on your Databricks permissions.

Explore the Marketplace catalog/schema metadata:

```bash
uv run python scripts/explore_catalog.py
```

That script lists the visible tables in `databricks_virtue_foundation_dataset_dais_2026.virtue_foundation_dataset` and describes the configured table columns. Change `DATABRICKS_TABLE` in `.env` to inspect one of the other tables.

## Download Raw Data

Download every visible table in the Marketplace schema:

```bash
uv run python scripts/download_catalog.py --overwrite
```

Files are written under:

```text
data/raw/databricks_virtue_foundation_dataset_dais_2026/virtue_foundation_dataset/
```

Each table gets a compressed CSV plus `schema.json`. A schema-level `manifest.json` records the downloaded files and row counts.

Inspect the local raw files without querying Databricks:

```bash
uv run python scripts/inspect_local_data.py
```

## Databricks App Skeleton

The clickable app skeleton lives under `app/` and uses FastAPI plus a Vite/React frontend.

Build the frontend bundle:

```bash
cd app/frontend
npm install
npm run build
```

Run the app locally from the `app/` directory:

```bash
cd app
../.venv/bin/uvicorn server:app --host 127.0.0.1 --port 8000
```

Open:

```text
http://127.0.0.1:8000
```

The Databricks App command is defined in `app/app.yaml`.

### Data Backend

The app separates the source dataset from the mutable app/result state:

- `APP_SOURCE_MODE=checked_in`: read the checked-in/downloaded facilities CSV, falling back to a tiny demo dataset.
- `APP_SOURCE_MODE=unity_catalog`: read source facilities from the Databricks Unity Catalog table.
- `APP_STATE_MODE=local`: write scratchpad, parse output, decisions, and notes to local `app/state` files.
- `APP_STATE_MODE=unity_catalog`: write scratchpad versions, result states, recommendations, risks, decisions, and audit events to Unity Catalog.

`APP_DATA_MODE` still works as a preset:

- `APP_DATA_MODE=local`: `APP_SOURCE_MODE=checked_in` + `APP_STATE_MODE=local`.
- `APP_DATA_MODE=unity_catalog`: `APP_SOURCE_MODE=unity_catalog` + `APP_STATE_MODE=unity_catalog`. This is the default.

Default DBX mode:

```text
APP_DATA_MODE=unity_catalog
APP_SOURCE_MODE=unity_catalog
APP_STATE_MODE=unity_catalog
```

Local app over the real Databricks catalog, with local scratchpad/results:

```text
APP_DATA_MODE=local
APP_SOURCE_MODE=unity_catalog
APP_STATE_MODE=local
```

Checked-in/offline click-through mode:

```text
APP_DATA_MODE=local
APP_SOURCE_MODE=checked_in
APP_STATE_MODE=local
```

Databricks source/target defaults:

```text
APP_SOURCE_CATALOG=databricks_virtue_foundation_dataset_dais_2026
APP_SOURCE_SCHEMA=virtue_foundation_dataset
APP_SOURCE_TABLE=facilities
APP_RESULT_CATALOG=dais_readiness_desk
```

Before deploying with `APP_STATE_MODE=unity_catalog`, create the app-owned UC tables using:

```text
app/sql/unity_catalog_state.sql
```

In DBX mode, `/api/state` keeps an in-memory hot state. If Unity Catalog or the SQL warehouse is slow, the app serves cached or warm demo state immediately and refreshes in the background. Use `/api/status` for the cheap cache/backend status and `/api/diagnostics` only when you want explicit catalog/table checks.

### Sharing the Deployed Databricks App

If a workspace user sees the Databricks `Permission Required` page before the app loads, they need app-level access in Databricks. This happens before FastAPI, React, or app Basic Auth runs.

UI fix:

1. Open the Databricks app overview page.
2. Click `Share`.
3. For a demo workspace, choose `Anyone in my organization can use`.
4. Save.

Per-user or per-group fix:

1. Open the Databricks app overview page.
2. Click `Share`.
3. Add the user or group.
4. Grant `CAN USE`.
5. Save.

CLI fix:

```bash
databricks apps update-permissions dbx-hack-doctors \
  --profile dbx_hack_doctors \
  --json '{"access_control_list":[{"user_name":"person@example.com","permission_level":"CAN_USE"}]}'
```

For a group:

```bash
databricks apps update-permissions dbx-hack-doctors \
  --profile dbx_hack_doctors \
  --json '{"access_control_list":[{"group_name":"my-group","permission_level":"CAN_USE"}]}'
```

Use `update-permissions` for additive changes. Avoid `set-permissions` unless intentionally replacing the app's direct permission list.

### App-level Basic Auth

Databricks App sharing is the primary access-control path for deployed demos. The FastAPI app also includes an optional Basic Auth gate if you want an extra app-level password after Databricks workspace authentication. It is disabled by default.

Local example:

```bash
cd app
APP_BASIC_AUTH_ENABLED=true \
APP_BASIC_AUTH_USERNAME=demo \
APP_BASIC_AUTH_PASSWORD='change-me' \
../.venv/bin/uvicorn server:app --host 127.0.0.1 --port 8000
```

For Databricks Apps deployment, set:

```text
APP_BASIC_AUTH_ENABLED=true
APP_BASIC_AUTH_USERNAME=<demo username>
APP_BASIC_AUTH_PASSWORD=<secret password>
```

Do not hardcode the password in `app.yaml`. Use Databricks app environment variables backed by a secret for `APP_BASIC_AUTH_PASSWORD`.
