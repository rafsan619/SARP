// Team overview for senior counsellors: every case, its AI assessment, SARP-Net prediction and flags.

import { esc, markdown } from "./markdown.js?v=20261120";

const $ = (id) => document.getElementById(id);
const pct = (x) => `${(x * 100).toFixed(1)}%`;
const when = (ts) => new Date(ts * 1000).toLocaleString([], { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
const VERDICT_CLASS = { "Likely eligible": "ok", "Potentially eligible": "maybe", "Not yet eligible": "no", "Need more information": "info" };
const SEVERITY = { blocker: "Blocker", risk: "Risk", check: "Check" };
let current = null, filter = "all", lastList = "", lastDetail = "";

function pin() { try { return sessionStorage.getItem("sarp.pin") || ""; } catch { return ""; } }

async function api(path) {
  const res = await fetch(path, { headers: { "X-Counsellor-Pin": pin() } });
  if (res.status === 401) { askPin(); throw new Error("pin"); }
  if (res.status === 503) {
    $("app").innerHTML = '<p class="c-empty">The app is turned off until a counsellor PIN is set (SARP_COUNSELLOR_PIN in the Vercel project settings).</p>';
    throw new Error("disabled");
  }
  if (!res.ok) throw new Error(String(res.status));
  return res.json();
}

function askPin() {
  $("app").innerHTML = `<div class="pin-screen"><form class="pin-card" id="pinForm">
      <h2>Counsellor sign-in</h2><p>Enter the agency's counsellor PIN.</p>
      <input type="password" name="pin" autocomplete="current-password" aria-label="Counsellor PIN" required>
      <button class="btn primary" type="submit">Open team overview</button></form></div>`;
  $("pinForm").addEventListener("submit", (e) => {
    e.preventDefault();
    try { sessionStorage.setItem("sarp.pin", e.target.pin.value); } catch { /* ignore */ }
    location.reload();
  });
}

function tier(level) {
  const label = { high: "High risk", medium: "Medium risk", low: "Low risk" }[level] || "Not scored";
  return `<span class="tier ${level || "none"}">${label}</span>`;
}
const verdict = (v) => v ? `<span class="verdict-chip ${VERDICT_CLASS[v] || "info"}">${esc(v)}</span>` : "";

async function loadList() {
  let data;
  try { data = await api("/api/counsellor/conversations"); } catch { return; }
  const card = data.model_card;
  const providers = (data.status.providers || [])
    .map((p) => `${p.name === "primary" ? "team PC" : "backup"} ${p.model} ${p.available ? "up" : `down${p.problem ? ` (${p.problem})` : ""}`}`).join("; ");
  $("modelCard").textContent = `SARP-Net ${card.model}: ${pct(card.test_accuracy)} accuracy, ROC-AUC ${card.test_roc_auc.toFixed(3)} on held-out records. `
    + `${data.status.cases || 0} past cases. AI: ${providers || "offline mode"}.`;
  const cases = data.conversations.filter((c) => filter === "all" || c.flag);
  const html = cases.length ? cases.map((c) => `
    <button class="c-item${c.id === current ? " active" : ""}" data-id="${c.id}" type="button">
      <span class="row"><span class="t">${esc(c.title)}</span>${c.flag ? '<span class="flag">Flagged</span>' : ""}</span>
      <span class="row meta">${verdict(c.verdict)}${tier(c.risk_level)}<span>${when(c.updated)}</span></span>
    </button>`).join("") : `<p class="small" style="margin:0 8px">${filter === "flagged" ? "No cases flagged for review." : "No cases yet."}</p>`;
  if (html !== lastList) { $("list").innerHTML = html; lastList = html; }
}

$("list")?.addEventListener("click", (e) => {
  const item = e.target.closest(".c-item");
  if (item) { current = item.dataset.id; lastList = ""; loadList(); loadDetail(current); }
});
document.querySelectorAll(".c-filters button").forEach((b) => b.addEventListener("click", () => {
  filter = b.dataset.filter;
  document.querySelectorAll(".c-filters button").forEach((x) => x.setAttribute("aria-checked", String(x === b)));
  lastList = "";
  loadList();
}));

async function loadDetail(id) {
  let d;
  try { d = await api(`/api/counsellor/conversations/${id}`); } catch { return; }
  const sheet = d.case, a = sheet.assessment, r = sheet.risk;
  const view = d.assessment?.counsellor_view;
  const known = sheet.profile.filter((p) => p.value);

  let prediction;
  if (view) {
    const cut = view.cutoffs;
    const maxShap = Math.max(...view.drivers.map((x) => Math.abs(x.shap)), 0.01);
    const whatIf = Object.entries(view.due_diligence_what_if.probability_if)
      .map(([lvl, p]) => `<dt>${esc(lvl)}</dt><dd>${pct(p)}</dd>`).join("");
    prediction = `
      <section class="panel">
        <h3>SARP-Net continuation probability</h3>
        <div class="prob"><b>${pct(view.probability)}</b>${tier(view.risk_level)}</div>
        <div class="bar" aria-hidden="true"><i style="width:${view.probability * 100}%"></i>
          <span class="cut" style="left:${cut.medium_risk_from * 100}%"></span><span class="cut" style="left:${cut.low_risk_from * 100}%"></span></div>
        <p class="small">${esc(view.risk_tier)}. Medium risk from ${cut.medium_risk_from}, low risk from ${cut.low_risk_from} (calibrated cut-offs).</p>
        ${whatIf ? `<h3 style="margin-top:14px">If the student's research level rose (now ${esc(view.due_diligence_what_if.current)})</h3><dl class="kv">${whatIf}</dl>` : ""}
        ${r.warnings?.length ? `<h3 style="margin-top:14px">Notes on this prediction</h3>${r.warnings.map((w) => `<p class="warn">${esc(w)}</p>`).join("")}` : ""}
      </section>
      <section class="panel">
        <h3>What drives this prediction (SHAP, with project evidence)</h3>
        ${view.drivers.map((x) => `
          <div class="driver">
            <div class="row"><span class="name">${esc(x.label)}</span>
              <span class="small">${x.direction}${x.actionable ? "" : ", not changeable by counselling"}</span>
              <span class="shap" aria-label="SHAP ${x.shap}"><i class="${x.shap < 0 ? "neg" : "pos"}" style="width:${(Math.abs(x.shap) / maxShap) * 50}%"></i></span></div>
            <ul>${x.evidence.map((ev) => `<li>${esc(ev)}</li>`).join("")}</ul>
          </div>`).join("")}
      </section>`;
  } else {
    prediction = `<section class="panel"><h3>SARP-Net continuation probability</h3>
      <p class="small">Not scored yet. Still needed: ${esc((r.needs || []).join(", ") || "details")}.</p></section>`;
  }

  const f = sheet.flag;
  const html = `<div class="wrap">
    <div class="c-head"><h2>${esc(d.title)}</h2>${verdict(a.verdict)}${tier(view?.risk_level)}<span class="small">Updated ${when(d.updated)}, language: ${esc(d.language || "unknown")}</span></div>
    ${f ? `<section class="panel flag-panel"><h3>Flagged for senior review</h3><p>${esc(f.note || "No note added.")}</p><p class="small">Flagged ${when(f.at)}</p></section>` : ""}
    <div class="c-grid">
      <div>
        <section class="panel"><h3>AI assessment</h3>
          <div class="cs-verdict ${VERDICT_CLASS[a.verdict] || "info"}"><strong>${esc(a.verdict)}</strong><p>${esc(a.reason)}</p></div>
          ${a.issues.length ? `<div class="cs-block"><h3>Problems found</h3>${a.issues.map((i) => `
            <div class="cs-issue ${i.severity}"><span class="sev">${SEVERITY[i.severity]}</span><div><strong>${esc(i.title)}</strong><p>${esc(i.summary)}</p></div><span></span></div>`).join("")}</div>` : ""}
          ${a.missing.length ? `<div class="cs-block"><h3>Missing information</h3><p class="small">${esc(a.missing.join(", "))}</p></div>` : ""}
          <div class="cs-block"><h3>Checks</h3><ul class="cs-checks">${a.checks.map((c) => `<li class="${c.state}"><span class="st"></span><b>${esc(c.area)}</b> ${esc(c.note)}</li>`).join("")}</ul></div>
        </section>
        ${prediction}
      </div>
      <div>
        <section class="panel"><h3>Student details</h3>${known.length ? `<dl class="kv">${known.map((p) => `<dt>${esc(p.label)}</dt><dd>${esc(p.value)}</dd>`).join("")}</dl>` : '<p class="small">Nothing recorded yet.</p>'}
          ${sheet.notes ? `<p class="cs-notes">${esc(sheet.notes)}</p>` : ""}</section>
        ${sheet.similar.length ? `<section class="panel"><h3>Similar past cases</h3>${sheet.similar.map((c) => `
          <details class="cs-case"><summary><span>${esc(c.title)}</span><em>${esc(c.match)}</em></summary><ul>${c.advice.map((x) => `<li>${esc(x)}</li>`).join("")}</ul></details>`).join("")}</section>` : ""}
        <section class="panel transcript"><h3>Conversation</h3>${d.messages.map((m) => `
          <div class="m ${m.role}"><div class="who">${m.role === "user" ? "Counsellor" : "SARP-Agent"}${m.feedback ? (m.feedback > 0 ? ", marked helpful" : ", marked not helpful") : ""}</div>${m.role === "user" ? esc(m.content) : `<div class="content">${markdown(m.content)}</div>`}</div>`).join("")}
        </section>
      </div>
    </div></div>`;
  if (html !== lastDetail) {
    const open = [...document.querySelectorAll("#detail details")].map((x) => x.open);
    $("detail").innerHTML = html;
    document.querySelectorAll("#detail details").forEach((x, i) => { x.open = !!open[i]; });
    lastDetail = html;
  }
}

loadList();
setInterval(() => { loadList(); if (current) loadDetail(current); }, 10000);
