-- Data Readiness Desk Unity Catalog state model.
--
-- Default recommendation:
--   1. Create a dedicated app-owned catalog if allowed.
--   2. If CREATE CATALOG is not allowed, replace `dais_readiness_desk`
--      with an existing writable catalog and create the schemas there.
--
-- Source data stays immutable. Result data is versioned and user/AI
-- mutations are append-only decisions/events.

CREATE CATALOG IF NOT EXISTS dais_readiness_desk
COMMENT 'App-owned catalog for Data Readiness Desk source snapshots, result states, and audit history';

CREATE SCHEMA IF NOT EXISTS dais_readiness_desk.source
COMMENT 'Immutable source snapshots and uploaded raw files';

CREATE SCHEMA IF NOT EXISTS dais_readiness_desk.work
COMMENT 'Intermediate parse, profiling, dedupe, and evidence extraction outputs';

CREATE SCHEMA IF NOT EXISTS dais_readiness_desk.result
COMMENT 'Versioned resulting state used by recommendations, actions, and risks';

CREATE SCHEMA IF NOT EXISTS dais_readiness_desk.audit
COMMENT 'Append-only app, import, reparse, and decision events';

CREATE TABLE IF NOT EXISTS dais_readiness_desk.source.source_snapshots (
  source_snapshot_id STRING NOT NULL,
  source_catalog STRING,
  source_schema STRING,
  source_table STRING,
  source_version STRING,
  source_type STRING,
  row_count BIGINT,
  created_at TIMESTAMP,
  created_by STRING,
  metadata_json STRING
)
USING DELTA
COMMENT 'Immutable source data snapshot metadata';

CREATE TABLE IF NOT EXISTS dais_readiness_desk.source.raw_facilities_snapshot (
  source_snapshot_id STRING NOT NULL,
  source_record_id STRING,
  raw_row_json STRING,
  created_at TIMESTAMP
)
USING DELTA
COMMENT 'Optional immutable copy of source facility rows for a source snapshot';

CREATE TABLE IF NOT EXISTS dais_readiness_desk.source.raw_uploaded_files (
  upload_id STRING NOT NULL,
  source_snapshot_id STRING,
  file_name STRING,
  source_name STRING,
  row_count BIGINT,
  parse_status STRING,
  uploaded_at TIMESTAMP,
  uploaded_by STRING,
  metadata_json STRING
)
USING DELTA
COMMENT 'Uploaded file metadata before rows are staged or parsed';

CREATE TABLE IF NOT EXISTS dais_readiness_desk.source.raw_uploaded_rows (
  upload_id STRING NOT NULL,
  row_number BIGINT,
  raw_row_json STRING,
  parse_errors_json STRING,
  created_at TIMESTAMP
)
USING DELTA
COMMENT 'Raw uploaded rows preserved as immutable JSON payloads';

CREATE TABLE IF NOT EXISTS dais_readiness_desk.work.parse_runs (
  run_id STRING NOT NULL,
  source_snapshot_id STRING NOT NULL,
  scratchpad_version_id STRING,
  run_status STRING,
  started_at TIMESTAMP,
  finished_at TIMESTAMP,
  triggered_by STRING,
  trigger_type STRING,
  error_message STRING,
  metadata_json STRING
)
USING DELTA
COMMENT 'Each re-parse attempt from source snapshot plus scratchpad context';

CREATE TABLE IF NOT EXISTS dais_readiness_desk.work.facility_records_normalized (
  run_id STRING NOT NULL,
  source_snapshot_id STRING NOT NULL,
  source_record_id STRING,
  normalized_record_id STRING,
  facility_name STRING,
  address STRING,
  city STRING,
  district STRING,
  state STRING,
  pin_code STRING,
  latitude DOUBLE,
  longitude DOUBLE,
  phone STRING,
  specialties_json STRING,
  description STRING,
  source_json STRING,
  normalized_json STRING,
  created_at TIMESTAMP
)
USING DELTA
COMMENT 'Normalized facility records produced by a parse run';

CREATE TABLE IF NOT EXISTS dais_readiness_desk.work.facility_duplicate_candidates (
  run_id STRING NOT NULL,
  candidate_id STRING NOT NULL,
  left_record_id STRING,
  right_record_id STRING,
  match_confidence DOUBLE,
  match_reasons_json STRING,
  planning_impact STRING,
  created_at TIMESTAMP
)
USING DELTA
COMMENT 'Pairwise or cluster-level duplicate candidates with explainable match reasons';

CREATE TABLE IF NOT EXISTS dais_readiness_desk.work.facility_capability_evidence (
  run_id STRING NOT NULL,
  evidence_id STRING NOT NULL,
  normalized_record_id STRING,
  capability STRING,
  claim_status STRING,
  confidence DOUBLE,
  source_field STRING,
  evidence_text STRING,
  reason STRING,
  created_at TIMESTAMP
)
USING DELTA
COMMENT 'Evidence extracted from structured and free-text facility records';

CREATE TABLE IF NOT EXISTS dais_readiness_desk.work.data_quality_findings (
  run_id STRING NOT NULL,
  finding_id STRING NOT NULL,
  normalized_record_id STRING,
  issue_type STRING,
  severity STRING,
  confidence DOUBLE,
  recommended_action STRING,
  owner STRING,
  evidence_json STRING,
  planning_impact STRING,
  created_at TIMESTAMP
)
USING DELTA
COMMENT 'Data readiness findings produced by profiling and evidence extraction';

CREATE TABLE IF NOT EXISTS dais_readiness_desk.result.scratchpad_versions (
  scratchpad_version_id STRING NOT NULL,
  parent_scratchpad_version_id STRING,
  markdown STRING,
  tags_json STRING,
  created_at TIMESTAMP,
  created_by STRING
)
USING DELTA
COMMENT 'Versioned Markdown scratchpad used to steer parse and review workflow';

CREATE TABLE IF NOT EXISTS dais_readiness_desk.result.result_state_versions (
  state_version_id STRING NOT NULL,
  parent_state_version_id STRING,
  run_id STRING NOT NULL,
  source_snapshot_id STRING NOT NULL,
  scratchpad_version_id STRING,
  state_status STRING,
  consistency_score DOUBLE,
  expected_lift_points DOUBLE,
  created_at TIMESTAMP,
  created_by STRING,
  metadata_json STRING
)
USING DELTA
COMMENT 'Materialized resulting state versions produced from parse runs and decisions';

CREATE TABLE IF NOT EXISTS dais_readiness_desk.result.facility_entities (
  state_version_id STRING NOT NULL,
  facility_entity_id STRING NOT NULL,
  canonical_name STRING,
  city STRING,
  district STRING,
  state STRING,
  pin_code STRING,
  latitude DOUBLE,
  longitude DOUBLE,
  specialties_json STRING,
  capabilities_json STRING,
  source_record_ids_json STRING,
  trust_score DOUBLE,
  updated_at TIMESTAMP
)
USING DELTA
COMMENT 'Current facility entities for a given result state version';

CREATE TABLE IF NOT EXISTS dais_readiness_desk.result.readiness_kpi_snapshot (
  state_version_id STRING NOT NULL,
  metric_name STRING NOT NULL,
  metric_value DOUBLE,
  metric_unit STRING,
  component_json STRING,
  created_at TIMESTAMP
)
USING DELTA
COMMENT 'Readiness KPI metrics for a result state version';

CREATE TABLE IF NOT EXISTS dais_readiness_desk.result.action_recommendations (
  state_version_id STRING NOT NULL,
  action_id STRING NOT NULL,
  priority STRING,
  issue_type STRING,
  recommendation STRING,
  owner STRING,
  confidence STRING,
  status STRING,
  lift_points DOUBLE,
  evidence_json STRING,
  created_at TIMESTAMP,
  updated_at TIMESTAMP
)
USING DELTA
COMMENT 'Recommended cleanup/review actions generated from resulting state';

CREATE TABLE IF NOT EXISTS dais_readiness_desk.result.geo_risk_recommendations (
  state_version_id STRING NOT NULL,
  risk_id STRING NOT NULL,
  priority STRING,
  geography_level STRING,
  geography_value STRING,
  care_need STRING,
  risk_label STRING,
  confidence STRING,
  reason STRING,
  look_at_json STRING,
  created_at TIMESTAMP
)
USING DELTA
COMMENT 'Risk recommendations generated only from resulting state';

CREATE TABLE IF NOT EXISTS dais_readiness_desk.result.reviewer_notes (
  note_id STRING NOT NULL,
  state_version_id STRING,
  target_type STRING,
  target_id STRING,
  note_markdown STRING,
  tags_json STRING,
  created_at TIMESTAMP,
  created_by STRING
)
USING DELTA
COMMENT 'Reviewer comments and tags attached to actions, risks, facilities, or state versions';

CREATE TABLE IF NOT EXISTS dais_readiness_desk.result.action_decisions (
  decision_id STRING NOT NULL,
  state_version_id STRING NOT NULL,
  action_id STRING NOT NULL,
  decision STRING,
  decision_note STRING,
  decided_at TIMESTAMP,
  decided_by STRING
)
USING DELTA
COMMENT 'Append-only human or AI decisions on generated action recommendations';

CREATE TABLE IF NOT EXISTS dais_readiness_desk.audit.app_events (
  event_id STRING NOT NULL,
  event_type STRING,
  actor STRING,
  target_type STRING,
  target_id STRING,
  event_json STRING,
  created_at TIMESTAMP
)
USING DELTA
COMMENT 'Append-only operational event stream for the app';

CREATE TABLE IF NOT EXISTS dais_readiness_desk.audit.reparse_events (
  event_id STRING NOT NULL,
  run_id STRING,
  state_version_id STRING,
  event_type STRING,
  event_json STRING,
  created_at TIMESTAMP
)
USING DELTA
COMMENT 'Append-only event stream for re-parse runs and state materialization';

CREATE TABLE IF NOT EXISTS dais_readiness_desk.audit.import_events (
  event_id STRING NOT NULL,
  upload_id STRING,
  event_type STRING,
  event_json STRING,
  created_at TIMESTAMP
)
USING DELTA
COMMENT 'Append-only import workflow events';

CREATE TABLE IF NOT EXISTS dais_readiness_desk.audit.decision_events (
  event_id STRING NOT NULL,
  decision_id STRING,
  state_version_id STRING,
  action_id STRING,
  event_type STRING,
  event_json STRING,
  created_at TIMESTAMP
)
USING DELTA
COMMENT 'Append-only decision and reviewer mutation history';
