import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

const tabs = ["Current Dataset", "Import + Actions", "Risk Recommendations"];

async function api(path, options = {}, timeoutMs = 25000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  const response = await fetch(path, { ...options, signal: controller.signal }).finally(() => clearTimeout(timer));
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || `Request failed: ${response.status}`);
  }
  return response.json();
}

function Metric({ label, value, detail, tone = "neutral" }) {
  return (
    <div className={`metric metric-${tone}`}>
      <div className="metric-label">{label}</div>
      <div className="metric-value">{value}</div>
      {detail ? <div className="metric-detail">{detail}</div> : null}
    </div>
  );
}

function ScoreBar({ label, value }) {
  return (
    <div className="score-row">
      <div className="score-label">
        <span>{label}</span>
        <b>{value}%</b>
      </div>
      <div className="bar">
        <div style={{ width: `${Math.max(0, Math.min(100, value))}%` }} />
      </div>
    </div>
  );
}

function renderMarkdown(markdown) {
  const blocks = [];
  let listItems = [];
  const flushList = () => {
    if (listItems.length) {
      blocks.push(
        <ul key={`list-${blocks.length}`}>
          {listItems.map((item, index) => (
            <li key={index}>{renderInlineMarkdown(item)}</li>
          ))}
        </ul>
      );
      listItems = [];
    }
  };

  markdown.split(/\r?\n/).forEach((rawLine, index) => {
    const line = rawLine.trim();
    if (!line) {
      flushList();
      return;
    }
    if (line.startsWith("- ") || line.startsWith("* ")) {
      listItems.push(line.slice(2));
      return;
    }
    flushList();
    if (line.startsWith("### ")) {
      blocks.push(<h4 key={index}>{renderInlineMarkdown(line.slice(4))}</h4>);
    } else if (line.startsWith("## ")) {
      blocks.push(<h3 key={index}>{renderInlineMarkdown(line.slice(3))}</h3>);
    } else if (line.startsWith("# ")) {
      blocks.push(<h2 key={index}>{renderInlineMarkdown(line.slice(2))}</h2>);
    } else {
      blocks.push(<p key={index}>{renderInlineMarkdown(line)}</p>);
    }
  });
  flushList();
  return blocks;
}

function renderInlineMarkdown(text) {
  return text.split(/(#[A-Za-z][A-Za-z0-9_-]*)/g).map((part, index) => {
    if (part.startsWith("#")) {
      return (
        <span className="inline-tag" key={index}>
          {part}
        </span>
      );
    }
    return part;
  });
}

function DataTable({ rows, columns, onRowClick, selectedId, sort, onSort }) {
  return (
    <div className="table-shell">
      <table>
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={column.key}>
                {onSort ? (
                  <button className="sort-header" onClick={() => onSort(column.key)}>
                    <span>{column.label}</span>
                    <span>{sort?.key === column.key ? (sort.direction === "asc" ? "↑" : "↓") : ""}</span>
                  </button>
                ) : (
                  column.label
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td colSpan={columns.length} className="empty-cell">
                No rows for this view.
              </td>
            </tr>
          ) : (
            rows.map((row, index) => {
              const id = row.action_id || row.location || row.name || index;
              return (
                <tr
                  key={id}
                  className={selectedId === id ? "selected" : ""}
                  onClick={onRowClick ? () => onRowClick(row) : undefined}
                >
                  {columns.map((column) => (
                    <td key={column.key}>{column.render ? column.render(row) : String(row[column.key] ?? "")}</td>
                  ))}
                </tr>
              );
            })
          )}
        </tbody>
      </table>
    </div>
  );
}

function CurrentDataset({ state, scratchpad, setScratchpad, onSaveScratchpad, onReparse, busy }) {
  const profile = state.run.profile;
  const components = profile.score_components || {};
  const previewColumns = [
    { key: "name", label: "Facility" },
    { key: "address_city", label: "City" },
    { key: "address_stateOrRegion", label: "State" },
    { key: "address_zipOrPostcode", label: "PIN" },
    { key: "organization_type", label: "Type" },
    { key: "readiness_flags", label: "Readiness flags" }
  ];
  const [scratchpadMode, setScratchpadMode] = useState("view");
  const [previewSearch, setPreviewSearch] = useState("");
  const [previewSort, setPreviewSort] = useState({ key: "name", direction: "asc" });
  const previewRows = useMemo(() => {
    const search = previewSearch.trim().toLowerCase();
    const filtered = search
      ? state.preview.filter((row) =>
          previewColumns.some((column) =>
            String(row[column.key] ?? "")
              .toLowerCase()
              .includes(search)
          )
        )
      : [...state.preview];
    filtered.sort((left, right) => {
      const leftValue = String(left[previewSort.key] ?? "").toLowerCase();
      const rightValue = String(right[previewSort.key] ?? "").toLowerCase();
      const comparison = leftValue.localeCompare(rightValue, undefined, { numeric: true });
      return previewSort.direction === "asc" ? comparison : -comparison;
    });
    return filtered;
  }, [state.preview, previewSearch, previewSort]);

  function togglePreviewSort(key) {
    setPreviewSort((current) => ({
      key,
      direction: current.key === key && current.direction === "asc" ? "desc" : "asc"
    }));
  }

  return (
    <section className="page-grid">
      <div className="full">
        <div className="metric-grid">
          <Metric label="Data consistency" value={`${profile.consistency_score}%`} detail={`+${profile.expected_lift} pts possible`} tone="warn" />
          <Metric label="Facilities" value={profile.row_count.toLocaleString()} detail="current dataset" />
          <Metric label="Duplicate clusters" value={profile.duplicate_clusters.toLocaleString()} detail="dedupe candidates" />
          <Metric label="Human review" value={profile.human_review_queue.toLocaleString()} detail="records/actions" tone="risk" />
        </div>
      </div>

      <div className="panel scratchpad">
        <div className="panel-head">
          <div>
            <h2>Scratchpad</h2>
            <p>Markdown notes, comments, and tags that steer the next parse.</p>
          </div>
          <div className="button-row wrap">
            <div className="segmented">
              <button className={scratchpadMode === "view" ? "active" : ""} onClick={() => setScratchpadMode("view")}>
                View
              </button>
              <button className={scratchpadMode === "edit" ? "active" : ""} onClick={() => setScratchpadMode("edit")}>
                Edit
              </button>
            </div>
            <button onClick={onSaveScratchpad}>Save</button>
            <button className="primary" onClick={onReparse} disabled={busy}>
              {busy ? "Parsing..." : "Trigger re-parse"}
            </button>
          </div>
        </div>
        {scratchpadMode === "edit" ? (
          <textarea value={scratchpad} onChange={(event) => setScratchpad(event.target.value)} spellCheck="false" />
        ) : (
          <div className="markdown-view">{renderMarkdown(scratchpad)}</div>
        )}
      </div>

      <div className="panel current-numbers">
        <div className="panel-head">
          <div>
            <h2>Current Numbers</h2>
            <p className="dataset-path">{state.catalog}.{state.schema}.{state.table}</p>
          </div>
        </div>
        <div className="mini-grid">
          <Metric label="States" value={profile.state_count.toLocaleString()} />
          <Metric label="Cities" value={profile.city_count.toLocaleString()} />
          <Metric label="Sparse locations" value={profile.sparse_locations.toLocaleString()} />
        </div>
        <div className="score-list">
          {Object.entries(components).map(([label, value]) => (
            <ScoreBar key={label} label={label} value={value} />
          ))}
        </div>
        <div className="tag-line">
          {(profile.tags || []).length ? profile.tags.map((tag) => <span key={tag}>#{tag}</span>) : <span>No tags yet</span>}
        </div>
      </div>

      <div className="panel full">
        <div className="panel-head">
          <div>
            <h2>Dataset Preview</h2>
            <p>Rows are sampled from the downloaded Databricks Marketplace facilities table.</p>
          </div>
          <div className="preview-controls">
            <input
              type="search"
              value={previewSearch}
              onChange={(event) => setPreviewSearch(event.target.value)}
              placeholder="Search preview"
            />
            <select
              value={previewSort.key}
              onChange={(event) => setPreviewSort({ ...previewSort, key: event.target.value })}
            >
              {previewColumns.map((column) => (
                <option key={column.key} value={column.key}>
                  Order by {column.label}
                </option>
              ))}
            </select>
            <button onClick={() => setPreviewSort({ ...previewSort, direction: previewSort.direction === "asc" ? "desc" : "asc" })}>
              {previewSort.direction === "asc" ? "Asc" : "Desc"}
            </button>
          </div>
        </div>
        <DataTable
          rows={previewRows}
          columns={previewColumns}
          sort={previewSort}
          onSort={togglePreviewSort}
        />
      </div>
    </section>
  );
}

const AGENT_NAMES = ["dedup", "geo", "shortage", "risk"];
const AGENT_LABELS = { dedup: "De-dup", geo: "Geo filter", shortage: "Shortage", risk: "Risk synthesis" };
const STATUS_TONE = { completed: "ok", failed: "risk", running: "warn", pending: "neutral", idle: "neutral" };

function AgentCard({ name, agentState }) {
  const status = agentState?.status || "pending";
  const tone = STATUS_TONE[status] || "neutral";
  const result = agentState?.result || {};
  return (
    <div className={`agent-card agent-${tone}`}>
      <div className="agent-header">
        <b>{AGENT_LABELS[name]}</b>
        <span className={`badge badge-${tone}`}>{status}</span>
      </div>
      {agentState?.error ? <p className="agent-error">{agentState.error}</p> : null}
      {status === "completed" && name === "dedup" && result.mode === "ingest" && result.summary ? (
        <p className="agent-detail">
          {result.summary.insert_count ?? 0} insert · {result.summary.update_count ?? 0} update · {result.summary.duplicate_count ?? 0} dup · {result.summary.review_count ?? 0} review
        </p>
      ) : null}
      {status === "completed" && name === "dedup" && result.mode !== "ingest" && result.summary ? (
        <p className="agent-detail">
          {result.summary.merge_count ?? "—"} merges · {result.summary.split_count ?? "—"} splits
        </p>
      ) : null}
      {status === "completed" && name === "geo" && result.summary ? (
        <p className="agent-detail">
          {result.flagged_records?.length ?? 0} flagged · {result.coverage_gaps?.length ?? 0} gaps
        </p>
      ) : null}
      {status === "completed" && name === "shortage" && result.summary ? (
        <p className="agent-detail">
          {result.shortage_areas?.filter((a) => a.severity === "critical").length ?? 0} critical areas
        </p>
      ) : null}
      {status === "completed" && name === "risk" ? (
        <p className="agent-detail">
          Data readiness: {result.data_readiness_score ?? "—"}% · Planning: {result.planning_readiness_score ?? "—"}%
        </p>
      ) : null}
    </div>
  );
}

function PipelinePanel({ pipeline, onStart, busy, ingestRecords }) {
  const status = pipeline?.status || "idle";
  const agents = pipeline?.agents || {};
  const riskResult = agents.risk?.result || {};
  const tone = STATUS_TONE[status] || "neutral";
  const isRunning = status === "running";
  const pipelineMode = pipeline?.mode || "analysis";

  return (
    <div className="panel">
      <div className="panel-head">
        <div>
          <h2>AI Pipeline</h2>
          <p>
            {ingestRecords
              ? `Ingest mode: ${ingestRecords.length} incoming records → Dedup → Geo + Shortage → Risk.`
              : "Analysis mode: Dedup → Geo + Shortage (parallel) → Risk synthesis."}
            {pipeline?.pipeline_id ? <span className="run-id"> Run: {pipeline.pipeline_id}</span> : null}
            {pipeline?.mode ? <span className="run-id"> [{pipeline.mode}]</span> : null}
          </p>
        </div>
        <div className="button-row">
          <span className={`badge badge-${tone}`}>{status}</span>
          {ingestRecords ? (
            <button className="primary" onClick={() => onStart(ingestRecords)} disabled={busy || isRunning}>
              {isRunning ? "Running…" : `Run ingestion (${ingestRecords.length} records)`}
            </button>
          ) : null}
          <button onClick={() => onStart(null)} disabled={busy || isRunning}>
            {isRunning ? "Running…" : "Run analysis"}
          </button>
        </div>
      </div>

      <div className="agent-grid">
        {AGENT_NAMES.map((name) => (
          <AgentCard key={name} name={name} agentState={agents[name]} />
        ))}
      </div>

      {status === "completed" && riskResult.executive_summary ? (
        <div className="risk-summary">
          <h3>Executive Summary</h3>
          <p>{riskResult.executive_summary}</p>
          {riskResult.top_3_priorities?.length ? (
            <ul>
              {riskResult.top_3_priorities.map((p, i) => <li key={i}>{p}</li>)}
            </ul>
          ) : null}
        </div>
      ) : null}

      {status === "failed" ? (
        <div className="error">Pipeline failed. Check server logs or retry.</div>
      ) : null}
    </div>
  );
}

function ImportActions({ state, pipeline, onPipelineStart, pipelineBusy, onDecision }) {
  const [upload, setUpload] = useState(null);
  const [uploadError, setUploadError] = useState("");
  const [uploadPreview, setUploadPreview] = useState(null);
  const [filters, setFilters] = useState({ priority: "All", owner: "All", status: "All" });
  const [selected, setSelected] = useState((state.run.actions || [])[0] || null);
  const [note, setNote] = useState("");

  const actions = state.run.actions || [];
  const filtered = actions.filter((action) => {
    return (
      (filters.priority === "All" || action.priority === filters.priority) &&
      (filters.owner === "All" || action.owner === filters.owner) &&
      (filters.status === "All" || action.status === filters.status)
    );
  });

  async function previewUpload(file) {
    setUpload(file);
    setUploadError("");
    setUploadPreview(null);
    if (!file) return;
    const formData = new FormData();
    formData.append("file", file);
    try {
      const result = await api("/api/import/preview", { method: "POST", body: formData });
      setUploadPreview(result);
    } catch (error) {
      setUploadError(error.message);
    }
  }

  return (
    <section className="page-grid">
      <div className="panel">
        <div className="panel-head">
          <div>
            <h2>Import</h2>
            <p>Stage XLS, XLSX, or CSV before it touches trusted tables.</p>
          </div>
        </div>
        <label className="dropzone">
          <input type="file" accept=".csv,.xls,.xlsx" onChange={(event) => previewUpload(event.target.files?.[0] || null)} />
          <span>{upload ? upload.name : "Drop or choose a facility file"}</span>
        </label>
        {uploadError ? <div className="error">{uploadError}</div> : null}
        {uploadPreview ? (
          <div className="import-summary">
            <Metric label="Parsed rows" value={uploadPreview.row_count.toLocaleString()} />
            <Metric label="Import readiness" value={`${uploadPreview.import_readiness}%`} />
            <Metric label="Columns" value={uploadPreview.columns.length.toLocaleString()} />
          </div>
        ) : null}
      </div>

      <PipelinePanel
        pipeline={pipeline}
        onStart={onPipelineStart}
        busy={pipelineBusy}
        ingestRecords={uploadPreview?.preview || null}
      />

      <div className="panel full">
        <div className="panel-head">
          <div>
            <h2>Recommendations / Actions</h2>
            <p>Operational queue generated from the current parse.</p>
          </div>
          <div className="filters">
            {["priority", "owner", "status"].map((key) => (
              <select key={key} value={filters[key]} onChange={(event) => setFilters({ ...filters, [key]: event.target.value })}>
                <option>All</option>
                {[...new Set(actions.map((action) => action[key]))].map((value) => (
                  <option key={value}>{value}</option>
                ))}
              </select>
            ))}
          </div>
        </div>
        <DataTable
          rows={filtered}
          selectedId={selected?.action_id}
          onRowClick={(row) => setSelected(row)}
          columns={[
            { key: "priority", label: "Priority" },
            { key: "issue_type", label: "Issue" },
            { key: "recommendation", label: "Recommendation" },
            { key: "owner", label: "Owner" },
            { key: "confidence", label: "Confidence" },
            { key: "lift_points", label: "Lift" },
            { key: "status", label: "Status" }
          ]}
        />
      </div>

      <div className="panel full detail-panel">
        <div>
          <h2>Selected Action</h2>
          {selected ? (
            <>
              <p className="recommendation">{selected.recommendation}</p>
              <dl>
                <dt>Evidence</dt>
                <dd>{selected.evidence}</dd>
                <dt>Owner</dt>
                <dd>{selected.owner}</dd>
                <dt>Confidence</dt>
                <dd>{selected.confidence}</dd>
              </dl>
            </>
          ) : (
            <p>Select an action to review evidence.</p>
          )}
        </div>
        <div>
          <h2>Comment / Tag</h2>
          <textarea value={note} onChange={(event) => setNote(event.target.value)} placeholder="Add a review note, e.g. #dedupe verify source priority..." />
          <div className="button-row">
            {["Approved", "Rejected", "Needs review"].map((status) => (
              <button key={status} disabled={!selected} onClick={() => onDecision(selected.action_id, status, note)}>
                {status}
              </button>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

function RiskRecommendations({ state }) {
  const risks = state.run.risks || [];
  const [selected, setSelected] = useState(risks[0] || null);
  const [confidence, setConfidence] = useState("All");
  const riskRows = useMemo(
    () => risks.filter((risk) => confidence === "All" || risk.confidence === confidence),
    [risks, confidence]
  );
  return (
    <section className="page-grid">
      <div className="panel full">
        <div className="panel-head">
          <div>
            <h2>Risk Recommendations</h2>
            <p>Planning output generated after dedupe, evidence scoring, and uncertainty penalties.</p>
          </div>
          <select value={confidence} onChange={(event) => setConfidence(event.target.value)}>
            <option>All</option>
            {[...new Set(risks.map((risk) => risk.confidence))].map((value) => (
              <option key={value}>{value}</option>
            ))}
          </select>
        </div>
        <DataTable
          rows={riskRows}
          selectedId={selected?.location}
          onRowClick={(row) => setSelected(row)}
          columns={[
            { key: "priority", label: "Priority" },
            { key: "state", label: "State" },
            { key: "location", label: "Location" },
            { key: "care_need", label: "Care need" },
            { key: "risk", label: "Risk" },
            { key: "confidence", label: "Confidence" },
            { key: "why", label: "Why" }
          ]}
        />
      </div>
      <div className="panel full detail-panel">
        <div>
          <h2>Recommendation Detail</h2>
          {selected ? (
            <>
              <p className="recommendation">{selected.risk} in {selected.location}, {selected.state}</p>
              <p>{selected.why}</p>
              <p>{selected.look_at}</p>
            </>
          ) : (
            <p>Select a risk row to inspect.</p>
          )}
        </div>
        <div>
          <h2>Planning Note</h2>
          <textarea placeholder="Save a note for the planning team..." />
          <button>Save planning note</button>
        </div>
      </div>
    </section>
  );
}

function App() {
  const [activeTab, setActiveTab] = useState(tabs[0]);
  const [state, setState] = useState(null);
  const [config, setConfig] = useState(null);
  const [scratchpad, setScratchpad] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [pipeline, setPipeline] = useState(null);
  const [pipelineBusy, setPipelineBusy] = useState(false);
  const pipelinePollerRef = React.useRef(null);

  async function refresh() {
    const next = await api("/api/state", {}, 25000);
    setState(next);
    setScratchpad(next.scratchpad);
  }

  function startPipelinePoller(pipelineId) {
    stopPipelinePoller();
    const poll = async () => {
      try {
        const s = await api(`/api/pipeline/status/${pipelineId}`, {}, 10000);
        setPipeline(s);
        if (s.status === "running") {
          pipelinePollerRef.current = setTimeout(poll, 3000);
        }
      } catch {
        pipelinePollerRef.current = setTimeout(poll, 5000);
      }
    };
    pipelinePollerRef.current = setTimeout(poll, 1000);
  }

  function stopPipelinePoller() {
    if (pipelinePollerRef.current) {
      clearTimeout(pipelinePollerRef.current);
      pipelinePollerRef.current = null;
    }
  }

  async function startPipeline(incomingRecords = null) {
    setPipelineBusy(true);
    try {
      const body = incomingRecords ? { incoming_records: incomingRecords } : {};
      const res = await api("/api/pipeline/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      setPipeline({ pipeline_id: res.pipeline_id, status: "running", agents: {}, mode: incomingRecords ? "ingest" : "analysis" });
      startPipelinePoller(res.pipeline_id);
    } catch (err) {
      setError(err.message);
    } finally {
      setPipelineBusy(false);
    }
  }

  useEffect(() => {
    api("/api/config", {}, 8000)
      .then(setConfig)
      .catch(() => setConfig(null));
    refresh().catch((err) => {
      setError(err.name === "AbortError" ? "Timed out loading app state. Check Unity Catalog access and SQL warehouse config." : err.message);
    });
    // Load any existing pipeline status
    api("/api/pipeline/status", {}, 5000)
      .then((s) => {
        if (s?.pipeline_id) {
          setPipeline(s);
          if (s.status === "running") startPipelinePoller(s.pipeline_id);
        }
      })
      .catch(() => {});
    return () => stopPipelinePoller();
  }, []);

  async function saveScratchpad() {
    await api("/api/scratchpad", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ markdown: scratchpad })
    });
  }

  async function reparse() {
    setBusy(true);
    setError("");
    try {
      const next = await api("/api/reparse", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ markdown: scratchpad })
      });
      setState({ ...state, ...next });
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function actionDecision(actionId, status, note) {
    await api(`/api/actions/${actionId}/decision`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status, note })
    });
    await refresh();
  }

  if (error) {
    return (
      <main className="app-shell">
        <div className="error">
          <h2>Could not load Data Readiness Desk</h2>
          <p>{error}</p>
          {config ? (
            <div className="debug-grid">
              {Object.entries(config).map(([key, value]) => (
                <div key={key}>
                  <span>{key}</span>
                  <b>{String(value || "not set")}</b>
                </div>
              ))}
            </div>
          ) : (
            <p>Could not read `/api/config`. Check the app logs and deployment environment variables.</p>
          )}
          <div className="button-row">
            <button onClick={() => window.location.reload()}>Retry</button>
          </div>
        </div>
      </main>
    );
  }

  if (!state) {
    return <main className="app-shell"><div className="loading">Loading Data Readiness Desk...</div></main>;
  }

  const backendStatus = state.run.backend_status || (state.run.fallback ? "warming" : "live");
  const backendStatusLabel =
    backendStatus === "live" ? "Live data" : backendStatus === "refreshing" ? "Refreshing cache" : "Warming cache";

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <h1>Data Readiness Desk</h1>
          <p>Track 4 cleanup workflow to Track 2 risk planning output</p>
        </div>
        <div className="run-meta">
          <span>{state.catalog}</span>
          <span>Last parse: {state.run.ran_at || "draft"}</span>
          <span>Run ID: {state.run.run_id || "none"}</span>
          <span className={`backend-pill backend-${backendStatus}`}>{backendStatusLabel}</span>
        </div>
      </header>

      <nav className="tabs">
        {tabs.map((tab) => (
          <button key={tab} className={activeTab === tab ? "active" : ""} onClick={() => setActiveTab(tab)}>
            {tab}
          </button>
        ))}
      </nav>

      {activeTab === "Current Dataset" ? (
        <CurrentDataset
          state={state}
          scratchpad={scratchpad}
          setScratchpad={setScratchpad}
          onSaveScratchpad={saveScratchpad}
          onReparse={reparse}
          busy={busy}
        />
      ) : null}
      {activeTab === "Import + Actions" ? (
        <ImportActions
          state={state}
          pipeline={pipeline}
          onPipelineStart={startPipeline}
          pipelineBusy={pipelineBusy}
          onDecision={actionDecision}
        />
      ) : null}
      {activeTab === "Risk Recommendations" ? <RiskRecommendations state={state} /> : null}
    </main>
  );
}

createRoot(document.getElementById("root")).render(<App />);
