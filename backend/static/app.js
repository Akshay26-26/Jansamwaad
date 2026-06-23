/* Jansamvaad 2.0+ — AI Grievance Intelligence dashboard.
   No build step: React + htm via vendored UMD globals. */
const { useState, useEffect, useCallback } = React;
const html = htm.bind(React.createElement);

const api = async (path, opts) => {
  const res = await fetch(path, opts);
  if (!res.ok) {
    const e = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(e.detail || "Request failed");
  }
  return res.json();
};
const post = (path, body) =>
  api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

const urgClass = (u) => ({ Critical: "crit", High: "high", Medium: "med", Low: "low" }[u] || "med");
const pct = (x) => Math.round((x || 0) * 100);

const SAMPLES = [
  { label: "Sparking transformer (HI, safety)", text: "रोहतक में ट्रांसफार्मर से चिंगारी निकल रही है, कभी भी आग लग सकती है, बच्चे पास में खेलते हैं।", district: "Rohtak" },
  { label: "No water (Hinglish)", text: "Sector 9 Hisar mein 6 din se paani nahi aa raha, PHED wale phone nahi uthate. Poora mohalla pareshan hai.", district: "Hisar" },
  { label: "Pension delay (Hinglish)", text: "Vridha pension 3 mahine se nahi aayi, main 72 saal ka hoon, bank ke chakkar lagate thak gaya.", district: "Bhiwani" },
  { label: "Patwari bribe (HI)", text: "पटवारी 6 महीने से इंतकाल नहीं कर रहा और रिश्वत मांग रहा है, कैथल तहसील।", district: "Kaithal" },
  { label: "Contaminated water (EN)", text: "Dirty and smelly water coming from the tap in Ambala, my children are falling sick.", district: "Ambala" },
];

/* ---------- Shared small components ---------- */
const Badge = ({ cls, children }) => html`<span class=${"badge " + cls}>${children}</span>`;
const ConfBar = ({ label, value }) => html`
  <div class="conf">
    <span class="label">${label}</span>
    <span class="track"><span class="fill" style=${{ width: pct(value) + "%" }}></span></span>
    <span class="pct">${pct(value)}%</span>
  </div>`;

/* ---------- INTAKE / TRIAGE ---------- */
function IntakeView({ districts, onPersisted }) {
  const [text, setText] = useState("");
  const [district, setDistrict] = useState("Hisar");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");

  const run = async () => {
    setLoading(true); setError(""); setResult(null);
    try {
      const r = await post("/api/triage", { text, district, persist: true });
      setResult(r); onPersisted && onPersisted();
    } catch (e) { setError(e.message); }
    setLoading(false);
  };

  const a = result && result.analysis;
  return html`
    <div class="intake-hero">
      <h2 class="intake-punchline">Right Complaint. Right Department. Right Time.</h2>
      <p class="intake-punchline-sub">Tell us your problem — we'll make sure it reaches the right hands, fast.</p>
    </div>
    <div class="grid-2">
      <div class="card">
        <h2>Citizen Complaint Intake</h2>
        <p class="sub">Paste a grievance in Hindi, English or Hinglish. The AI returns an advisory triage for officer review.</p>
        <label>Complaint text</label>
        <textarea value=${text} onInput=${(e) => setText(e.target.value)} placeholder="जैसे: सेक्टर 9 हिसार में 5 दिन से पानी नहीं आ रहा..."></textarea>
        <div class="samples">
          ${SAMPLES.map((s) => html`<button class="sample-chip" onClick=${() => { setText(s.text); setDistrict(s.district); }}>${s.label}</button>`)}
        </div>
        <div class="row" style=${{ marginTop: 14 }}>
          <div>
            <label>District</label>
            <select value=${district} onChange=${(e) => setDistrict(e.target.value)}>
              ${districts.map((d) => html`<option value=${d}>${d}</option>`)}
            </select>
          </div>
          <div style=${{ flex: "0 0 auto" }}>
            <button class="btn" disabled=${loading || !text.trim()} onClick=${run}>
              ${loading ? html`<span class="spinner"></span> Analysing…` : "Run AI Triage"}
            </button>
          </div>
        </div>
        ${error && html`<p class="notice" style=${{ marginTop: 12, borderColor: "#f0c0c0", background: "#fdecea", color: "#a03028" }}>${error}</p>`}
      </div>

      <div class="card">
        <h2>AI Recommendation <span class="muted" style=${{ fontWeight: 400, fontSize: 12 }}>(advisory)</span></h2>
        ${!result && html`<div class="empty">Run a triage to see the AI recommendation, confidence scores, reason codes and similar past cases.</div>`}
        ${result && html`
          <div class="result-head">
            <div>
              <${Badge} cls="lang">${({ hi: "हिन्दी", en: "English", mixed: "Hinglish", other: "Other" })[a.detected_language] || a.detected_language}<//>
              ${a.is_safety_critical && html` <${Badge} cls="safety">⚠ SAFETY-CRITICAL<//>`}
              ${result.is_potential_duplicate && html` <${Badge} cls="dup">Possible duplicate<//>`}
            </div>
            <${Badge} cls=${urgClass(a.urgency)}>${a.urgency} priority<//>
          </div>
          <p class="summary">${a.summary}</p>
          <div class="kv">
            <span class="k">Category</span><span class="v">${a.category}</span>
            <span class="k">Department</span><span class="v">${a.department}</span>
            <span class="k">Route to</span><span class="v">${result.routing_office}</span>
            <span class="k">Citizen-Charter SLA</span><span class="v">${result.suggested_sla_days} day(s)</span>
            <span class="k">Complaint ID</span><span class="v mono">${result.complaint_id}</span>
          </div>

          <div class="section-title">Confidence</div>
          <${ConfBar} label="Category" value=${a.confidence.category} />
          <${ConfBar} label="Department" value=${a.confidence.department} />
          <${ConfBar} label="Urgency" value=${a.confidence.urgency} />
          <${ConfBar} label="Overall" value=${a.confidence.overall} />

          <div class="section-title">Why (reason codes)</div>
          <div class="reasons">
            ${a.reason_codes.map((r) => html`<span class=${"reason-chip" + (/RULE|SAFETY|PRIORITY/.test(r) ? " rule" : "")}>${r}</span>`)}
          </div>

          ${result.similar_cases.length > 0 && html`
            <div class="section-title">Similar past complaints (RAG)</div>
            <div class="similar">
              ${result.similar_cases.map((s) => html`
                <div class="item">
                  <div>
                    <div>${s.summary}</div>
                    <div class="meta">${s.complaint_id} · ${s.category} · ${s.district} · ${s.status}</div>
                  </div>
                  <div class="sim-score">${pct(s.similarity)}%</div>
                </div>`)}
            </div>`}

          <p class="notice" style=${{ marginTop: 16 }}>Saved to the officer review queue. No complaint is routed or closed on AI output alone — an authorised officer reviews and decides.</p>
        `}
      </div>
    </div>`;
}

/* ---------- OFFICER REVIEW ---------- */
function OfficerView({ taxonomy }) {
  const [items, setItems] = useState([]);
  const [sel, setSel] = useState(null);
  const [detail, setDetail] = useState(null);
  const [audit, setAudit] = useState([]);
  const [reason, setReason] = useState("");
  const [override, setOverride] = useState({});
  const [flash, setFlash] = useState(null);
  const [busy, setBusy] = useState(false);
  const [filters, setFilters] = useState({ id: "", priority: "", status: "", dept: "" });

  const load = useCallback(async () => {
    const q = await api("/api/queue"); setItems(q.items);
    const a = await api("/api/audit"); setAudit(a.entries);
  }, []);
  useEffect(() => { load(); }, [load]);

  const setF = (k, v) => setFilters((f) => ({ ...f, [k]: v }));
  const clearFilters = () => setFilters({ id: "", priority: "", status: "", dept: "" });
  const statusOptions = ["Open", "In Progress", "Routed", "Resolved"];
  const filtered = items.filter((r) =>
    (!filters.id || (r.complaint_id || "").toLowerCase().includes(filters.id.toLowerCase())) &&
    (!filters.priority || r.urgency === filters.priority) &&
    (!filters.status || r.status === filters.status) &&
    (!filters.dept || r.department === filters.dept)
  );
  const activeFilterCount = Object.values(filters).filter(Boolean).length;

  const openItem = async (cid) => {
    setSel(cid); setReason(""); setOverride({}); setFlash(null);
    const d = await api("/api/complaint/" + cid); setDetail(d);
  };

  const decide = async (action) => {
    if (!sel || busy) return;
    setBusy(true);
    try {
      const res = await post("/api/decision", {
        complaint_id: sel, action,
        final_category: override.category || null,
        final_department: override.department || null,
        final_urgency: override.urgency || null,
        reason: reason,
      });
      await load(); await openItem(sel);
      const a = res.audit;
      const verb = action === "override" ? "Override" : action === "escalate" ? "Escalation" : "Acceptance";
      setFlash({ ok: true, text: `✓ ${verb} recorded for ${a.complaint_id} → routed to ${(a.final_department || "").split(" (")[0]} as ${a.final_category} (${a.final_urgency}). Written to the audit log below.` });
    } catch (e) {
      setFlash({ ok: false, text: "Could not record decision: " + e.message });
    }
    setBusy(false);
  };

  const ai = detail && detail.ai_result;
  const rec = detail && detail.record;
  return html`
    <div class="grid-2">
      <div class="card">
        <h2>Officer Review Queue</h2>
        <p class="sub">${filtered.length} of ${items.length} complaints${activeFilterCount ? " · filtered" : " · sorted by urgency, criticals first"}.</p>
        <div class="filter-bar">
          <input class="f-search" placeholder="🔍 Search ID (e.g. JS-1010)" value=${filters.id} onInput=${(e) => setF("id", e.target.value)} />
          <select value=${filters.priority} onChange=${(e) => setF("priority", e.target.value)}>
            <option value="">All priorities</option>
            ${["Critical", "High", "Medium", "Low"].map((p) => html`<option value=${p}>${p}</option>`)}
          </select>
          <select value=${filters.status} onChange=${(e) => setF("status", e.target.value)}>
            <option value="">All statuses</option>
            ${statusOptions.map((s) => html`<option value=${s}>${s}</option>`)}
          </select>
          <select value=${filters.dept} onChange=${(e) => setF("dept", e.target.value)}>
            <option value="">All departments</option>
            ${(taxonomy.department_names || []).map((d) => html`<option value=${d}>${shortDept(d)}</option>`)}
          </select>
          ${activeFilterCount > 0 && html`<button class="btn ghost sm" onClick=${clearFilters}>✕ Clear (${activeFilterCount})</button>`}
        </div>
        <table>
          <thead><tr><th>ID</th><th>Summary</th><th>Dept</th><th>Priority</th><th>Status</th></tr></thead>
          <tbody>
            ${filtered.length === 0 && html`<tr><td colspan="5"><div class="empty">No complaints match these filters.</div></td></tr>`}
            ${filtered.map((r) => html`
              <tr key=${r.complaint_id} class=${"clickable" + (sel === r.complaint_id ? " selected" : "")} onClick=${() => openItem(r.complaint_id)}>
                <td class="mono">${r.complaint_id}</td>
                <td>${(r.summary || r.text || "").slice(0, 60)}</td>
                <td class="muted">${shortDept(r.department)}</td>
                <td><${Badge} cls=${urgClass(r.urgency)}>${r.urgency}<//></td>
                <td class="muted">${r.status}</td>
              </tr>`)}
          </tbody>
        </table>
      </div>

      <div class="card">
        <h2>Case & Decision</h2>
        ${!detail && html`<div class="empty">Select a complaint from the queue to review the AI recommendation and record a decision.</div>`}
        ${detail && html`
          <div class="kv">
            <span class="k">Complaint</span><span class="v mono">${rec.complaint_id}</span>
            <span class="k">Text</span><span class="v" style=${{ fontWeight: 400 }}>${rec.text}</span>
            <span class="k">AI category</span><span class="v">${rec.category}</span>
            <span class="k">AI department</span><span class="v">${rec.department}</span>
            <span class="k">AI priority</span><span class="v"><${Badge} cls=${urgClass(rec.urgency)}>${rec.urgency}<//></span>
          </div>
          ${ai && ai.analysis.reason_codes && html`
            <div class="section-title">AI reason codes</div>
            <div class="reasons">${ai.analysis.reason_codes.map((r) => html`<span class=${"reason-chip" + (/RULE|SAFETY|PRIORITY/.test(r) ? " rule" : "")}>${r}</span>`)}</div>`}

          <div class="section-title">Officer action (human-in-the-loop)</div>
          <div class="notice" style=${{ marginBottom: 12 }}>Override the AI if needed — your decision and reason are written to the immutable audit log.</div>
          <div class="row">
            <div>
              <label>Override category</label>
              <select value=${override.category || ""} onChange=${(e) => setOverride({ ...override, category: e.target.value })}>
                <option value="">— keep AI (${rec.category}) —</option>
                ${taxonomy.categories.map((c) => html`<option value=${c}>${c}</option>`)}
              </select>
            </div>
            <div>
              <label>Override priority</label>
              <select value=${override.urgency || ""} onChange=${(e) => setOverride({ ...override, urgency: e.target.value })}>
                <option value="">— keep AI (${rec.urgency}) —</option>
                ${["Critical", "High", "Medium", "Low"].map((u) => html`<option value=${u}>${u}</option>`)}
              </select>
            </div>
          </div>
          <div style=${{ marginTop: 10 }}>
            <label>Reason / remarks</label>
            <input value=${reason} onInput=${(e) => setReason(e.target.value)} placeholder="e.g. Verified with JE; rerouted to sewerage wing." />
          </div>
          <div style=${{ display: "flex", gap: 8, marginTop: 12, alignItems: "center" }}>
            <button class="btn green sm" disabled=${busy} onClick=${() => decide("accept")}>${busy ? html`<span class="spinner"></span>` : "✓ Accept AI & route"}</button>
            <button class="btn amber sm" disabled=${busy} onClick=${() => decide("override")}>✎ Override & route</button>
            <button class="btn ghost sm" disabled=${busy} onClick=${() => decide("escalate")}>↑ Escalate</button>
          </div>
          ${flash && html`<div class="notice" style=${{ marginTop: 12, ...(flash.ok ? { background: "#e8f4ec", borderColor: "#bfe0ca", color: "#1a6b39" } : { background: "#fdecea", borderColor: "#f0c0c0", color: "#a03028" }) }}>${flash.text}</div>`}
        `}
      </div>

      <div class="card" style=${{ gridColumn: "1 / -1" }}>
        <h2>Audit Trail</h2>
        <p class="sub">Every AI suggestion + officer decision, with overrides flagged. This is the accountability record.</p>
        ${audit.length === 0 && html`<div class="empty">No decisions recorded yet.</div>`}
        ${audit.length > 0 && html`
          <table>
            <thead><tr><th>Time</th><th>Complaint</th><th>Officer</th><th>Action</th><th>AI → Final (category)</th><th>AI → Final (priority)</th><th>Reason</th></tr></thead>
            <tbody>
              ${audit.map((e, i) => html`
                <tr key=${i}>
                  <td class="muted mono">${new Date(e.timestamp).toLocaleString()}</td>
                  <td class="mono">${e.complaint_id}</td>
                  <td class="muted">${e.officer_id}</td>
                  <td><b style=${{ color: e.action === "override" ? "#d9a006" : "#15803d" }}>${e.action}</b></td>
                  <td>${e.ai_category === e.final_category ? e.ai_category : html`<span class="muted">${e.ai_category}</span> → <b>${e.final_category}</b>`}</td>
                  <td>${e.ai_urgency === e.final_urgency ? e.ai_urgency : html`<span class="muted">${e.ai_urgency}</span> → <b>${e.final_urgency}</b>`}</td>
                  <td class="muted">${e.reason}</td>
                </tr>`)}
            </tbody>
          </table>`}
      </div>
    </div>`;
}

/* ---------- SUPERVISOR ANALYTICS ---------- */
const shortDept = (s) => (s || "").split(" (")[0].split(" / ")[0];
const rowSummary = (r) => r.summary || r.text || "";

function BarChart({ items, max, onClick, activeKey }) {
  const [grown, setGrown] = useState(false);
  useEffect(() => { const t = setTimeout(() => setGrown(true), 30); return () => clearTimeout(t); }, []);
  const m = max || Math.max(1, ...items.map((d) => d.value));
  return html`<div class="bars">
    ${items.map((d) => html`
      <div key=${d.key} class=${"bar-row" + (onClick ? " clickable" : "") + (activeKey === d.key ? " active" : "")}
           onClick=${onClick ? (() => onClick(d)) : null}>
        <span class="name" title=${d.name}>${d.name}</span>
        <span class="bar-track"><span class=${"bar-fill" + (d.cls ? " " + d.cls : "")} style=${{ width: (grown ? (d.value / m) * 100 : 0) + "%" }}></span></span>
        <span class="val">${d.value}</span>
      </div>`)}
  </div>`;
}

function DrillTable({ rows }) {
  if (!rows || rows.length === 0) return html`<div class="empty">No matching complaints.</div>`;
  return html`<table>
    <thead><tr><th>ID</th><th>Summary</th><th>District</th><th>Dept</th><th>Priority</th><th>Status</th></tr></thead>
    <tbody>${rows.map((r) => html`
      <tr key=${r.complaint_id}>
        <td class="mono">${r.complaint_id}</td>
        <td>${rowSummary(r).slice(0, 80)}</td>
        <td>${r.district}</td>
        <td class="muted">${shortDept(r.department)}</td>
        <td><${Badge} cls=${urgClass(r.urgency)}>${r.urgency}<//></td>
        <td class="muted">${r.status}</td>
      </tr>`)}
    </tbody>
  </table>`;
}

function SupervisorView() {
  const [stats, setStats] = useState(null);
  const [clusters, setClusters] = useState([]);
  const [records, setRecords] = useState([]);
  const [drill, setDrill] = useState(null); // {title, subtitle, key, rows}
  const [q, setQ] = useState("");
  const [loadingQ, setLoadingQ] = useState(false);

  const reload = useCallback(() => {
    api("/api/analytics").then(setStats);
    api("/api/clusters").then((c) => setClusters(c.clusters));
    api("/api/queue").then((d) => setRecords(d.items));
  }, []);
  useEffect(() => { reload(); }, [reload]);

  const showDrill = (d) => {
    setDrill(d);
    setTimeout(() => { const el = document.getElementById("drill-anchor"); if (el) el.scrollIntoView({ behavior: "smooth", block: "center" }); }, 40);
  };
  const drillBy = (key, title, fn) => {
    if (drill && drill.key === key) return setDrill(null); // toggle off
    showDrill({ key, title, subtitle: "", rows: records.filter(fn) });
  };

  const ask = async () => {
    if (!q.trim()) return;
    setLoadingQ(true);
    try {
      const res = await post("/api/nlq", { question: q });
      showDrill({ key: "nlq:" + q, title: `Query · “${q}”`, subtitle: "Filters: " + res.applied_filters.join("  ·  "), rows: res.results });
    } catch (e) { showDrill({ key: "err", title: "Query error", subtitle: e.message, rows: [] }); }
    setLoadingQ(false);
  };
  const NLQ_SAMPLES = ["show pending water complaints in Hisar", "urgent safety cases", "long pending pension complaints", "all complaints in Rohtak"];

  if (!stats) return html`<div class="container"><div class="empty"><span class="spinner"></span> Loading governance dashboard…</div></div>`;

  const deptItems = stats.by_department.map(([k, v]) => ({ name: shortDept(k), value: v, key: k }));
  const urgItems = stats.by_urgency.map(([u, v]) => ({ name: u, value: v, key: u, cls: urgClass(u) }));
  const distItems = stats.by_district.slice(0, 8).map(([d, v]) => ({ name: d, value: v, key: d }));

  return html`
    <div>
      <div class="stats">
        <div class=${"stat clickable" + (drill && drill.key === "all" ? " active" : "")} onClick=${() => drillBy("all", "All complaints", () => true)}>
          <div class="n">${stats.total_complaints}</div><div class="l">Total complaints ›</div></div>
        <div class=${"stat alert clickable" + (drill && drill.key === "safety" ? " active" : "")} onClick=${() => drillBy("safety", "Safety-critical complaints", (r) => r.is_safety_critical)}>
          <div class="n">${stats.safety_critical}</div><div class="l">Safety-critical flagged ›</div></div>
        <div class=${"stat clickable" + (drill && drill.key === "open" ? " active" : "")} onClick=${() => drillBy("open", "Open / in-progress complaints", (r) => ["Open", "In Progress"].includes(r.status))}>
          <div class="n">${stats.open + stats.in_progress}</div><div class="l">Open / in progress ›</div></div>
        <div class="stat"><div class="n">${pct(stats.override_rate)}%</div><div class="l">AI override rate (${stats.ai_decisions_reviewed} reviewed)</div></div>
      </div>

      <div id="drill-anchor"></div>
      ${drill && html`
        <div class="drill" style=${{ marginTop: 20 }}>
          <div class="drill-head">
            <div class="t">${drill.title}<span class="count">${drill.rows.length} complaint(s)</span>${drill.subtitle && html`<div class="muted" style=${{ fontSize: 12, fontWeight: 500, marginTop: 2 }}>${drill.subtitle}</div>`}</div>
            <button class="drill-close" onClick=${() => setDrill(null)}>✕ Close</button>
          </div>
          <div class="drill-body"><${DrillTable} rows=${drill.rows} /></div>
        </div>`}

      <div class="grid-2" style=${{ marginTop: 20 }}>
        <div class="card">
          <h2>Complaints by Department <span class="hint">click a bar to drill in</span></h2>
          <p class="sub">Where the load is concentrated.</p>
          <${BarChart} items=${deptItems} activeKey=${drill && drill.key}
            onClick=${(d) => drillBy(d.key, "Department · " + shortDept(d.key), (r) => r.department === d.key)} />
        </div>
        <div class="card">
          <h2>Priority Mix <span class="hint">click to filter</span></h2>
          <p class="sub">Distribution of urgency across all complaints.</p>
          <${BarChart} items=${urgItems} activeKey=${drill && drill.key}
            onClick=${(d) => drillBy(d.key, "Priority · " + d.key, (r) => r.urgency === d.key)} />
          <div class="section-title">Top districts <span class="hint">click to filter</span></div>
          <${BarChart} items=${distItems} activeKey=${drill && drill.key}
            onClick=${(d) => drillBy(d.key, "District · " + d.key, (r) => r.district === d.key)} />
        </div>
      </div>

      <div class="card" style=${{ marginTop: 20 }}>
        <h2>Systemic Issue Detection (clustering) <span class="hint">click a cluster to see every complaint in it</span></h2>
        <p class="sub">Complaints automatically grouped by issue + locality, surfacing recurring failures and departmental bottlenecks before they escalate.</p>
        ${clusters.length === 0 && html`<div class="empty">No multi-complaint clusters detected yet.</div>`}
        ${clusters.map((c) => html`
          <div key=${c.cluster_id} class=${"cluster clickable" + (c.is_systemic ? " systemic" : "") + (drill && drill.key === c.cluster_id ? " active" : "")}
               onClick=${() => showDrill({ key: c.cluster_id, title: "Cluster · " + c.label, subtitle: c.districts.join(", ") + " — " + c.departments.map(shortDept).join(", "), rows: c.complaints })}>
            <div class="top">
              <div class="label">${c.label} <span class="pill">${c.size} complaints</span> ${c.is_systemic && html`<span class="pill" style=${{ background: "#fbe6c0", color: "#8a5a14" }}>⚠ systemic</span>`}</div>
              <div class="muted" style=${{ fontSize: 12 }}>${c.districts.join(", ")} · ${c.departments.map(shortDept).join(", ")} <span style=${{ color: "var(--blue)", fontWeight: 600 }}>· view ›</span></div>
            </div>
            <ul>${c.samples.map((s, i) => html`<li key=${i}>${s}</li>`)}</ul>
          </div>`)}
      </div>

      <div class="card" style=${{ marginTop: 20 }}>
        <h2>Ask the Data (Natural-Language Query)</h2>
        <p class="sub">Plain-language supervisory queries over the complaint base — results open in the panel above, with the applied filters shown (transparent, no black box).</p>
        <div class="row">
          <div><input value=${q} onInput=${(e) => setQ(e.target.value)} placeholder="e.g. show pending water complaints in Hisar" onKeyDown=${(e) => e.key === "Enter" && ask()} /></div>
          <div style=${{ flex: "0 0 auto" }}><button class="btn" disabled=${loadingQ || !q.trim()} onClick=${ask}>${loadingQ ? html`<span class="spinner"></span> Asking…` : "Ask"}</button></div>
        </div>
        <div class="samples">${NLQ_SAMPLES.map((s) => html`<button class="sample-chip" onClick=${() => { setQ(s); }}>${s}</button>`)}</div>
      </div>
    </div>`;
}

/* ---------- APP SHELL ---------- */
function App() {
  const [tab, setTab] = useState("intake");
  const [health, setHealth] = useState(null);
  const [taxonomy, setTaxonomy] = useState({ categories: [], districts: [] });
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    api("/api/health").then(setHealth);
    api("/api/taxonomy").then(setTaxonomy);
  }, []);

  const tabs = [
    ["intake", "Citizen Intake"],
    ["officer", "Officer Review"],
    ["supervisor", "Governance Dashboard"],
  ];
  return html`
    <div>
      <header class="app-header">
        <div class="bar">
          <div class="emblem">हरि</div>
          <div class="app-title">
            <h1>Jansamvaad 2.0+ · AI Grievance Intelligence</h1>
            <p>Advisory decision-support for the Haryana CM Window — Government of Haryana</p>
          </div>
          <div class="header-spacer"></div>
          ${health && html`
            <div class=${"provider-badge" + (health.sovereign_mode ? " sovereign" : "")}>
              <span class="dot"></span>
              ${health.sovereign_mode ? "On-prem" : "AI Engine"}
            </div>`}
        </div>
        <nav class="tabs">
          ${tabs.map(([k, label]) => html`<button class=${"tab" + (tab === k ? " active" : "")} onClick=${() => setTab(k)}>${label}</button>`)}
        </nav>
      </header>
      <div class="container">
        <div class="advisory-strip">🛡 Advisory only — AI augments officers; it never closes, rejects or finally routes a complaint on its own. DPDPA-2023 aligned, human-in-the-loop, fully audited.</div>
        ${tab === "intake" && html`<${IntakeView} districts=${taxonomy.districts} onPersisted=${() => setRefreshKey((k) => k + 1)} />`}
        ${tab === "officer" && html`<${OfficerView} key=${refreshKey} taxonomy=${taxonomy} />`}
        ${tab === "supervisor" && html`<${SupervisorView} key=${refreshKey} />`}
      </div>
      <div class="footer">Jansamvaad 2.0+ prototype · Built for the Haryana AI Sandbox · Synthetic data only · No real citizen records.</div>
    </div>`;
}

ReactDOM.createRoot(document.getElementById("root")).render(html`<${App} />`);
