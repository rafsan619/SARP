// SARP-Agent counsellor workspace. Plain ES module, no build step.

import { esc, markdown } from "./markdown.js?v=20261120";

const ICONS = {
  plus: '<path d="M12 5v14M5 12h14"/>',
  menu: '<path d="M4 7h16M4 12h16M4 17h16"/>',
  close: '<path d="M6 6l12 12M18 6 6 18"/>',
  send: '<path d="M12 19V5M5 12l7-7 7 7"/>',
  stop: '<rect x="7" y="7" width="10" height="10" rx="2" fill="currentColor" stroke="none"/>',
  copy: '<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V6a2 2 0 0 1 2-2h9"/>',
  up: '<path d="M7 11v9H4v-9zM7 11l4-7a2 2 0 0 1 3 2l-1 5h5a2 2 0 0 1 2 2.3l-1.2 6A2 2 0 0 1 16.8 21H7"/>',
  down: '<path d="M17 13V4h3v9zM17 13l-4 7a2 2 0 0 1-3-2l1-5H6a2 2 0 0 1-2-2.3l1.2-6A2 2 0 0 1 7.2 3H17"/>',
  pencil: '<path d="M4 20h4L19 9l-4-4L4 16zM14 6l4 4"/>',
  trash: '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
  moon: '<path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5"/>',
  arrowDown: '<path d="M12 5v14M5 12l7 7 7-7"/>',
  sheet: '<rect x="5" y="3" width="14" height="18" rx="2"/><path d="M9 8h6M9 12h6M9 16h4"/>',
  flag: '<path d="M5 21V4M5 4h11l-2 4 2 4H5"/>',
};
const icon = (name, cls = "") =>
  `<svg class="${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[name]}</svg>`;

const STARTERS = [
  { text: "My student wants to study in Malaysia, but their bank statement has not completed 28 days. They want to apply for the upcoming intake.", tag: "Bank statement" },
  { text: "My student has a three-year study gap. What are the possible options?", tag: "Study gap" },
  { text: "Student HSC GPA 3.2, wants a Business bachelor's in Malaysia, no IELTS. Direct entry hobe na mone hocche, ki korbo?", tag: "Banglish" },
  { text: "আমার স্টুডেন্টের আগে কানাডার ভিসা রিফিউজ হয়েছে। এখন UK-তে মাস্টার্স করতে চায়। কেসটা কীভাবে দেখব?", tag: "বাংলা" },
  { text: "I'm a new counsellor. How do I assess a student whose results don't meet direct entry?", tag: "Training", mode: "training" },
  { text: "The student wants to bring his wife and child for a master's in the UK. Which pathways should I investigate?", tag: "Dependants" },
];

const VERDICT_CLASS = { "Likely eligible": "ok", "Potentially eligible": "maybe", "Not yet eligible": "no", "Need more information": "info" };
const SEVERITY_LABEL = { blocker: "Blocker", risk: "Risk", check: "Check" };

// ------------------------------------------------------------------ state
const $ = (id) => document.getElementById(id);
const local = {
  get: (k, d) => { try { return localStorage.getItem(k) ?? d; } catch { return d; } },
  set: (k, v) => { try { localStorage.setItem(k, v); } catch { /* private mode */ } },
};
const session = {
  get: (k) => { try { return sessionStorage.getItem(k) || ""; } catch { return ""; } },
  set: (k, v) => { try { sessionStorage.setItem(k, v); } catch { /* ignore */ } },
};
const S = {
  clientId: local.get("sarp.client") || (() => { const id = (crypto.randomUUID?.() || `${Date.now()}-${Math.random()}`).replace(/[^a-z0-9-]/gi, ""); local.set("sarp.client", id); return id; })(),
  conversationId: null, language: local.get("sarp.language", "auto"), mode: local.get("sarp.mode", "case"),
  streaming: false, controller: null, pinned: true, conversations: [], sheet: null, editing: false,
};
const el = {
  app: $("app"), history: $("history"), thread: $("thread"), scroller: $("scroller"), welcome: $("welcome"),
  input: $("input"), send: $("send"), composer: $("composer"), title: $("chatTitle"), panel: $("casePanel"),
  mode: $("modePill"), jump: $("jump"), language: $("language"), theme: $("themeToggle"), flag: $("flagBtn"),
  toast: $("toast"), announcer: $("announcer"), pin: $("pinScreen"),
};

// ------------------------------------------------------------------ helpers

function headers() {
  return { "Content-Type": "application/json", "X-Counsellor-Pin": session.get("sarp.pin") };
}

async function api(path, options = {}) {
  const res = await fetch(path, { ...options, headers: headers() });
  if (res.status === 401) { showPin(); throw Object.assign(new Error("pin"), { status: 401 }); }
  if (!res.ok) throw Object.assign(new Error(`${res.status}`), { status: res.status });
  return res.json();
}

function toast(message) {
  el.toast.textContent = message;
  el.toast.classList.add("show");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => el.toast.classList.remove("show"), 2200);
}

function updateJump() {
  const gap = el.scroller.scrollHeight - el.scroller.scrollTop - el.scroller.clientHeight;
  S.pinned = gap < 80;
  el.jump.hidden = gap < 240;
}
function scrollToBottom(force = false) {
  if (force || S.pinned) el.scroller.scrollTop = el.scroller.scrollHeight;
  updateJump();
}
const q = (id) => `client_id=${encodeURIComponent(S.clientId)}`;

// ------------------------------------------------------------------ PIN sign-in
function showPin() {
  el.pin.hidden = false;
  $("pinInput").focus();
}
$("pinForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  session.set("sarp.pin", $("pinInput").value);
  const res = await fetch("/api/status", { headers: headers() });
  if (res.status === 401) { $("pinError").hidden = false; return; }
  el.pin.hidden = true;
  start();
});

// ------------------------------------------------------------------ icons, theme, mode
function paintIcons() {
  document.querySelectorAll("[data-icon]").forEach((n) => { n.outerHTML = icon(n.dataset.icon); });
  $("openSidebar").innerHTML = icon("menu");
  $("closeSidebar").innerHTML = icon("close");
  el.jump.innerHTML = icon("arrowDown");
  setSendMode(false);
  el.theme.innerHTML = icon(document.documentElement.dataset.theme === "dark" ? "sun" : "moon");
}

function setSendMode(streaming) {
  el.send.innerHTML = icon(streaming ? "stop" : "send");
  el.send.setAttribute("aria-label", streaming ? "Stop" : "Send");
  el.send.disabled = !streaming && !el.input.value.trim();
}

function setMode(mode) {
  S.mode = mode;
  local.set("sarp.mode", mode);
  document.querySelectorAll(".mode-switch button").forEach((b) => b.setAttribute("aria-checked", String(b.dataset.mode === mode)));
  el.input.placeholder = mode === "training"
    ? "Ask how to handle a type of case, e.g. a student with a study gap"
    : "Describe the student's situation or ask about the case";
  el.app.classList.toggle("training", mode === "training");
}
document.querySelectorAll(".mode-switch button").forEach((b) => b.addEventListener("click", () => setMode(b.dataset.mode)));

// ------------------------------------------------------------------ sidebar: cases
function groupOf(ts) {
  const d = new Date(ts * 1000), now = new Date();
  const start = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  if (d >= start) return "Today";
  if (d >= start - 864e5) return "Yesterday";
  if (d >= start - 7 * 864e5) return "Previous 7 days";
  return "Older";
}

async function loadHistory() {
  try { S.conversations = await api(`/api/conversations?${q()}`); } catch { S.conversations = []; }
  renderHistory();
}

function renderHistory() {
  if (!S.conversations.length) { el.history.innerHTML = '<p class="history-empty">Your student cases will appear here.</p>'; return; }
  const groups = {};
  S.conversations.forEach((c) => (groups[groupOf(c.updated)] ||= []).push(c));
  el.history.innerHTML = Object.entries(groups).map(([name, list]) => `
    <div class="history-group"><h2>${esc(name)}</h2>${list.map((c) => `
      <div class="history-item${c.id === S.conversationId ? " active" : ""}" data-id="${c.id}">
        <a href="#c/${c.id}" title="${esc(c.title)}"><span class="vdot ${VERDICT_CLASS[c.verdict] || "info"}" title="${esc(c.verdict || "")}"></span>${c.flagged ? icon("flag", "mini-flag") : ""}${esc(c.title)}</a>
        <span class="item-actions">
          <button type="button" data-act="rename" aria-label="Rename case" title="Rename case">${icon("pencil")}</button>
          <button type="button" data-act="delete" aria-label="Delete case" title="Delete case">${icon("trash")}</button>
        </span>
      </div>`).join("")}</div>`).join("");
}

el.history.addEventListener("click", async (e) => {
  const item = e.target.closest(".history-item");
  if (!item) return;
  const id = item.dataset.id;
  const btn = e.target.closest("button");
  const act = btn?.dataset.act;
  if (!act) { closeSidebar(); return; }
  e.preventDefault();
  if (act === "rename") return startRename(item, id);
  if (act === "delete") {
    btn.dataset.act = "confirm"; btn.className = "confirm-delete"; btn.textContent = "Delete";
    item.classList.add("confirming");
    setTimeout(() => { if (btn.isConnected && btn.dataset.act === "confirm") renderHistory(); }, 3500);
    return;
  }
  if (act === "confirm") {
    await api(`/api/conversations/${id}?${q()}`, { method: "DELETE" });
    S.conversations = S.conversations.filter((c) => c.id !== id);
    if (id === S.conversationId) newCase();
    renderHistory();
    toast("Case deleted");
  }
});

function startRename(item, id) {
  const conv = S.conversations.find((c) => c.id === id);
  item.innerHTML = `<input value="${esc(conv.title)}" maxlength="80" aria-label="Rename case">`;
  const input = item.querySelector("input");
  input.focus(); input.select();
  const finish = async (save) => {
    const title = input.value.trim();
    if (save && title && title !== conv.title) {
      await api(`/api/conversations/${id}?${q()}`, { method: "PATCH", body: JSON.stringify({ title }) });
      conv.title = title;
      if (id === S.conversationId) el.title.textContent = title;
    }
    renderHistory();
  };
  input.addEventListener("keydown", (ev) => { if (ev.key === "Enter") finish(true); if (ev.key === "Escape") finish(false); });
  input.addEventListener("blur", () => finish(true), { once: true });
}

// ------------------------------------------------------------------ case sheet
function pct(x) { return `${(x * 100).toFixed(1)}%`; }

function renderCase(sheet) {
  S.sheet = sheet;
  if (!sheet) {
    el.panel.innerHTML = `<div class="cs-head"><h2>Case sheet</h2></div>
      <p class="cs-empty">The case sheet fills in as you describe the student: eligibility, problems found, missing information, SARP-Net continuation risk and similar past cases.</p>`;
    renderFlag();
    return;
  }
  if (S.editing) return renderEditor(sheet);
  const a = sheet.assessment, r = sheet.risk;
  const known = sheet.profile.filter((p) => p.value);
  el.panel.innerHTML = `
    <div class="cs-head"><h2>Case sheet</h2><button class="btn-ghost small" type="button" id="editCase">${icon("pencil")} Edit details</button></div>

    <section class="cs-verdict ${VERDICT_CLASS[a.verdict] || "info"}">
      <span class="cs-label">Eligibility</span>
      <strong>${esc(a.verdict)}</strong>
      <p>${esc(a.reason)}</p>
    </section>

    ${a.issues.length ? `<section class="cs-block"><h3>Problems found</h3>${a.issues.map((i) => `
      <div class="cs-issue ${i.severity}">
        <span class="sev">${SEVERITY_LABEL[i.severity]}</span>
        <div><strong>${esc(i.title)}</strong><p>${esc(i.summary)}</p></div>
        <button type="button" class="dismiss" data-dismiss="${i.id}" title="Not a problem for this student" aria-label="Dismiss ${esc(i.title)}">${icon("close")}</button>
      </div>`).join("")}</section>` : ""}

    ${a.missing.length ? `<section class="cs-block"><h3>Missing information</h3>
      <div class="cs-missing">${a.missing.map((m) => `<button type="button" class="tag" data-ask="${esc(m)}">${esc(m)}</button>`).join("")}</div></section>` : ""}

    <section class="cs-block"><h3>Student details</h3>
      ${known.length ? `<dl class="kv">${known.map((p) => `<dt>${esc(p.label)}</dt><dd>${esc(p.value)}</dd>`).join("")}</dl>`
        : '<p class="small">Nothing recorded yet.</p>'}
      ${sheet.notes ? `<p class="cs-notes">${esc(sheet.notes)}</p>` : ""}
    </section>

    <section class="cs-block"><h3>Checks</h3>
      <ul class="cs-checks">${a.checks.map((c) => `<li class="${c.state}"><span class="st" aria-hidden="true"></span><b>${esc(c.area)}</b> ${esc(c.note)}</li>`).join("")}</ul>
    </section>

    <section class="cs-block"><h3>SARP-Net continuation risk</h3>
      ${r.status === "ok" ? `
        <div class="prob"><b>${pct(r.probability)}</b><span class="tier ${r.level}">${esc(r.tier.split(" (")[0])}</span></div>
        <div class="bar" aria-hidden="true"><i style="width:${r.probability * 100}%"></i>
          <span class="cut" style="left:${r.cutoffs.medium_risk_from * 100}%"></span><span class="cut" style="left:${r.cutoffs.low_risk_from * 100}%"></span></div>
        <p class="small">Chance the student continues with the plan, from the agency's 6,000-record model.</p>
        <ul class="cs-drivers">${r.drivers.map((d) => `<li><b>${esc(d.label)}</b> <span class="${d.shap < 0 ? "neg" : "pos"}">${esc(d.direction)}</span>${d.evidence[0] ? `<span class="ev">${esc(d.evidence[d.evidence.length > 1 ? 1 : 0])}</span>` : ""}</li>`).join("")}</ul>
        ${Object.keys(r.what_if.probability_if).length ? `<p class="small">If research rose to ${Object.entries(r.what_if.probability_if).map(([k, v]) => `${esc(k)}: ${pct(v)}`).join(", ")}</p>` : ""}
        ${r.warnings.map((w) => `<p class="small warnline">${esc(w)}</p>`).join("")}`
      : `<p class="small">Scored once these are known: ${esc(r.needs.join(", "))}.</p>
         ${r.needs.includes("research done by the student") ? `<label class="inline-field">Research done by the student
           <select id="ddQuick"><option value="">Choose</option>${sheet.options.due_diligence.map((o) => `<option>${o}</option>`).join("")}</select></label>` : ""}`}
    </section>

    ${sheet.similar.length ? `<section class="cs-block"><h3>Similar past cases</h3>${sheet.similar.map((c) => `
      <details class="cs-case"><summary><span>${esc(c.title)}</span><em>${esc(c.match)}</em></summary>
        <p class="small">What our counsellor advised:</p>
        <ul>${c.advice.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>
      </details>`).join("")}</section>` : ""}
  `;
  $("editCase").addEventListener("click", () => { S.editing = true; renderCase(S.sheet); });
  el.panel.querySelectorAll("[data-dismiss]").forEach((b) => b.addEventListener("click", () => saveProfile({}, [b.dataset.dismiss])));
  el.panel.querySelectorAll("[data-ask]").forEach((b) => b.addEventListener("click", () => { S.editing = true; renderCase(S.sheet); }));
  $("ddQuick")?.addEventListener("change", (e) => e.target.value && saveProfile({ due_diligence: e.target.value }));
  renderFlag();
}

function renderEditor(sheet) {
  const v = sheet.raw || {}, o = sheet.options;
  const sel = (name, list, value, blank = "Not known") =>
    `<select name="${name}"><option value="">${blank}</option>${list.map((x) => `<option${String(x) === String(value ?? "") ? " selected" : ""}>${esc(x)}</option>`).join("")}</select>`;
  const yesno = (name) => `<select name="${name}"><option value="">Not known</option><option value="true"${v[name] === true ? " selected" : ""}>Yes</option><option value="false"${v[name] === false ? " selected" : ""}>No</option></select>`;
  el.panel.innerHTML = `
    <div class="cs-head"><h2>Edit student details</h2></div>
    <form class="cs-form" id="caseForm">
      <label>Destination<input name="country" list="countryList" value="${esc(v.country || "")}"><datalist id="countryList">${o.countries.map((c) => `<option>${esc(c)}</option>`).join("")}</datalist></label>
      <label>Level${sel("level", o.levels, v.level)}</label>
      <label>Course<input name="course" value="${esc(v.course || "")}"></label>
      <label>University<input name="institution" value="${esc(v.institution || "")}"></label>
      <label>Intake<input name="intake" type="month" value="${esc((v.intake || "").slice(0, 7))}"></label>
      <div class="row2"><label>Latest result<input name="gpa" type="number" step="0.01" min="0" max="5" value="${v.gpa ?? ""}"></label>
        <label>Out of${sel("gpa_scale", [4, 5], v.gpa_scale ?? (v.gpa > 4 ? 5 : v.gpa ? 4 : ""), "Choose")}</label></div>
      <div class="row2"><label>English test${sel("english_test", o.english_tests, v.english_test)}</label>
        <label>Score<input name="english_score" type="number" step="0.5" min="0" value="${v.english_score ?? ""}"></label></div>
      <label>Yearly budget${sel("budget_band", ["Below 10k", "10-15K", "16-20K"], v.budget_band, v.budget_amount ? `As described (${v.budget_amount})` : "Not known")}</label>
      <div class="row2"><label>Bank statement${sel("bank_status", o.bank_states, v.bank_status)}</label>
        <label>Days held<input name="bank_days" type="number" min="0" value="${v.bank_days ?? ""}"></label></div>
      <label>Study gap (years)<input name="gap_years" type="number" min="0" value="${v.gap_years ?? ""}"></label>
      <div class="row2"><label>Visa refusal${yesno("visa_refusal")}</label><label>Dependants${yesno("dependants")}</label></div>
      <label>Research done by the student${sel("due_diligence", o.due_diligence, v.due_diligence)}</label>
      <label>Notes<textarea name="notes" rows="3">${esc(sheet.notes || "")}</textarea></label>
      <div class="dialog-actions"><button class="btn" type="button" id="cancelEdit">Cancel</button><button class="btn primary" type="submit">Save details</button></div>
    </form>`;
  $("cancelEdit").addEventListener("click", () => { S.editing = false; renderCase(S.sheet); });
  $("caseForm").addEventListener("submit", (e) => {
    e.preventDefault();
    const f = new FormData(e.target), changes = {};
    const numbers = ["gpa", "gpa_scale", "english_score", "bank_days", "gap_years"];
    for (const [k, raw] of f.entries()) {
      let val = String(raw).trim();
      if (k === "budget_band" && !val && v.budget_amount) continue; // keep the amount from the chat
      if (val === "") { changes[k] = null; continue; }
      if (numbers.includes(k)) val = Number(val);
      else if (val === "true" || val === "false") val = val === "true";
      changes[k] = val;
    }
    S.editing = false;
    saveProfile(changes);
  });
}

async function ensureCase() {
  if (S.conversationId) return S.conversationId;
  const created = await api("/api/conversations", { method: "POST", body: JSON.stringify({ client_id: S.clientId }) });
  S.conversationId = created.id;
  history.replaceState(null, "", `#c/${created.id}`);
  return created.id;
}

async function saveProfile(changes, dismiss = []) {
  try {
    const id = await ensureCase();
    const sheet = await api(`/api/conversations/${id}/profile?${q()}`, { method: "POST", body: JSON.stringify({ changes, dismiss }) });
    renderCase(sheet);
    toast("Case updated");
  } catch (e) { if (e.status !== 401) toast("Could not save the case"); }
}

function renderFlag() {
  const flagged = !!S.sheet?.flag;
  el.flag.hidden = !S.conversationId;
  el.flag.classList.toggle("on", flagged);
  el.flag.innerHTML = `${icon("flag")}<span>${flagged ? "Flagged for senior review" : "Flag for senior review"}</span>`;
}
el.flag.addEventListener("click", async () => {
  if (!S.conversationId) return;
  const flagged = !S.sheet?.flag;
  const note = flagged ? (prompt("Note for the senior counsellor (optional):") ?? "") : "";
  const res = await api(`/api/conversations/${S.conversationId}/flag?${q()}`, { method: "POST", body: JSON.stringify({ flagged, note }) });
  S.sheet = { ...(S.sheet || {}), flag: res.flag };
  renderFlag();
  loadHistory();
  toast(flagged ? "Flagged for senior review" : "Flag removed");
});

$("caseToggle").addEventListener("click", () => el.app.classList.toggle("panel-open"));

// ------------------------------------------------------------------ messages
function hideWelcome() { el.welcome.hidden = true; }

function addUserMessage(text) {
  const node = document.createElement("div");
  node.className = "msg user";
  node.innerHTML = `<div class="bubble">${esc(text)}</div>`;
  el.thread.appendChild(node);
}

function addAssistantMessage({ id = null, content = "", feedback = 0, pending = false } = {}) {
  document.querySelectorAll(".msg.assistant.latest").forEach((n) => n.classList.remove("latest"));
  const node = document.createElement("div");
  node.className = "msg assistant latest";
  node.innerHTML = `
    <svg class="avatar" viewBox="0 0 32 32" aria-hidden="true"><rect width="32" height="32" rx="9" fill="var(--green)"/><path d="M7.5 16.2 24.5 8.6l-5.6 15.6-3.3-6.3-8.1-1.7Z" fill="var(--surface)"/><circle cx="24.6" cy="23.8" r="2.6" fill="var(--marigold)"/></svg>
    <div class="msg-body"><div class="notices"></div><div class="content"></div><div class="extras"></div><div class="actions" hidden></div></div>`;
  const msg = { node, id, raw: content, feedback, body: node.querySelector(".content"), extras: node.querySelector(".extras"), actions: node.querySelector(".actions") };
  if (pending) msg.body.innerHTML = '<span class="typing" aria-label="Thinking"><i></i><i></i><i></i></span>';
  else { msg.body.innerHTML = markdown(content); renderActions(msg); }
  el.thread.appendChild(node);
  return msg;
}

function renderActions(msg) {
  if (!msg.id) { msg.actions.hidden = true; return; }
  msg.actions.hidden = false;
  msg.actions.innerHTML = `
    <button type="button" data-act="copy" aria-label="Copy reply" title="Copy reply">${icon("copy")}</button>
    <button type="button" data-act="good" aria-pressed="${msg.feedback === 1}" aria-label="Helpful" title="Helpful">${icon("up")}</button>
    <button type="button" data-act="bad" aria-pressed="${msg.feedback === -1}" aria-label="Not helpful" title="Not helpful">${icon("down")}</button>`;
  msg.actions.onclick = async (e) => {
    const act = e.target.closest("button")?.dataset.act;
    if (act === "copy") {
      try { await navigator.clipboard.writeText(msg.raw); toast("Copied"); } catch { /* blocked */ }
    } else if (act === "good" || act === "bad") {
      const value = act === "good" ? 1 : -1;
      msg.feedback = msg.feedback === value ? 0 : value;
      renderActions(msg);
      api(`/api/messages/${msg.id}/feedback`, { method: "POST", body: JSON.stringify({ client_id: S.clientId, value: msg.feedback }) }).catch(() => {});
    }
  };
}

function renderChips(msg, chips) {
  document.querySelectorAll(".chips").forEach((n) => n.remove());
  if (!chips?.length) return;
  const box = document.createElement("div");
  box.className = "chips";
  chips.forEach((chip) => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "chip suggest";
    b.textContent = chip.label;
    b.addEventListener("click", () => send(chip.label));
    box.appendChild(b);
  });
  msg.extras.appendChild(box);
}

// ------------------------------------------------------------------ sending and streaming
async function streamChat(body, onEvent, signal) {
  const res = await fetch("/api/chat", { method: "POST", headers: headers(), body: JSON.stringify(body), signal });
  if (res.status === 401) { showPin(); throw Object.assign(new Error("pin"), { status: 401 }); }
  if (!res.ok || !res.body) throw Object.assign(new Error(`HTTP ${res.status}`), { status: res.status });
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let cut;
    while ((cut = buffer.indexOf("\n\n")) >= 0) {
      const block = buffer.slice(0, cut);
      buffer = buffer.slice(cut + 2);
      let type = "message", data = "";
      for (const line of block.split("\n")) {
        if (line.startsWith("event: ")) type = line.slice(7);
        else if (line.startsWith("data: ")) data += line.slice(6);
      }
      if (data) onEvent(type, JSON.parse(data));
    }
  }
}

async function send(text, modeOverride = null) {
  text = text.trim();
  if (!text || S.streaming) return;
  hideWelcome();
  document.querySelectorAll(".chips").forEach((n) => n.remove());
  addUserMessage(text);
  el.input.value = "";
  autosize();
  const msg = addAssistantMessage({ pending: true });
  S.streaming = true; S.pinned = true;
  setSendMode(true);
  scrollToBottom(true);
  el.thread.setAttribute("aria-busy", "true");
  S.controller = new AbortController();
  let chips = [], frame = 0, started = false, offline = false;
  const paint = () => { frame = 0; msg.body.innerHTML = markdown(msg.raw); msg.body.classList.add("streaming"); scrollToBottom(); };
  try {
    await streamChat({
      client_id: S.clientId, conversation_id: S.conversationId, text,
      language: S.language === "auto" ? null : S.language, mode: modeOverride || S.mode,
    }, (type, data) => {
      if (type === "meta") {
        if (S.conversationId !== data.conversation_id) {
          S.conversationId = data.conversation_id;
          history.replaceState(null, "", `#c/${data.conversation_id}`);
        }
        if (data.title) { el.title.textContent = data.title; }
      } else if (type === "case") {
        S.editing = false;
        renderCase(data.case);
      } else if (type === "token") {
        if (!started) { started = true; msg.raw = ""; }
        msg.raw += data.text;
        if (!frame) frame = requestAnimationFrame(paint);
      } else if (type === "notice") {
        offline = true;
        msg.node.querySelector(".notices").innerHTML = `<p class="notice">${esc(data.text)}</p>`;
      } else if (type === "chips") {
        chips = data.chips;
      } else if (type === "done") {
        msg.id = data.message_id;
        if (started) el.mode.hidden = !offline; // the pill follows what actually happened on this reply
      } else if (type === "error") {
        throw new Error(data.text);
      }
    }, S.controller.signal);
  } catch (error) {
    if (error.name === "AbortError") {
      if (!msg.raw) msg.raw = "_Stopped_";
    } else if (error.status !== 401) {
      const why = error.status === 429 ? "Too many messages in a short time. Wait a few minutes, then try again."
        : "Couldn't reach SARP-Agent. Check the connection, then try again.";
      msg.extras.innerHTML = `<p class="error-line">${esc(why)} <button type="button">Try again</button></p>`;
      msg.extras.querySelector("button").addEventListener("click", () => { msg.node.previousElementSibling?.remove(); msg.node.remove(); send(text); });
    }
  } finally {
    if (frame) cancelAnimationFrame(frame);
    msg.body.classList.remove("streaming");
    msg.body.innerHTML = msg.raw ? markdown(msg.raw) : "";
    renderActions(msg);
    renderChips(msg, chips);
    S.streaming = false; S.controller = null;
    setSendMode(false);
    el.thread.removeAttribute("aria-busy");
    el.announcer.textContent = "Reply ready";
    scrollToBottom();
    loadHistory();
    if (!matchMedia("(pointer: coarse)").matches) el.input.focus();
  }
}

// ------------------------------------------------------------------ cases
function clearThread() { el.thread.querySelectorAll(".msg").forEach((n) => n.remove()); }

function newCase() {
  if (S.controller) S.controller.abort();
  S.conversationId = null; S.editing = false;
  history.replaceState(null, "", "/");
  clearThread();
  el.welcome.hidden = false;
  el.title.textContent = "New case";
  renderCase(null);
  renderHistory();
  el.input.focus();
}

async function openCase(id) {
  if (S.controller) S.controller.abort();
  let conv;
  try { conv = await api(`/api/conversations/${id}?${q()}`); } catch { newCase(); return; }
  S.conversationId = conv.id; S.editing = false;
  clearThread();
  hideWelcome();
  el.title.textContent = conv.title;
  let last = null;
  conv.messages.forEach((m) => {
    if (m.role === "user") addUserMessage(m.content);
    else last = { msg: addAssistantMessage({ id: m.id, content: m.content, feedback: m.feedback }), chips: m.chips };
  });
  if (last && conv.messages.at(-1)?.role === "assistant") renderChips(last.msg, last.chips);
  renderCase(conv.case);
  renderHistory();
  S.pinned = true;
  requestAnimationFrame(() => scrollToBottom(true));
}

function route() {
  const m = location.hash.match(/^#c\/([a-z0-9]+)$/i);
  if (m) { if (m[1] !== S.conversationId) openCase(m[1]); }
  else if (S.conversationId) newCase();
}

// ------------------------------------------------------------------ composer and controls
function autosize() {
  el.input.style.height = "auto";
  if (el.input.value) el.input.style.height = `${Math.min(el.input.scrollHeight, 220)}px`;
  el.send.disabled = !S.streaming && !el.input.value.trim();
}
el.input.addEventListener("input", autosize);
el.input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); if (!S.streaming) send(el.input.value); }
});
el.composer.addEventListener("submit", (e) => { e.preventDefault(); if (S.streaming) S.controller?.abort(); else send(el.input.value); });

$("newCase").addEventListener("click", () => { newCase(); closeSidebar(); });
el.language.value = S.language;
el.language.addEventListener("change", () => { S.language = el.language.value; local.set("sarp.language", S.language); });
el.theme.addEventListener("click", () => {
  const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  local.set("sarp.theme", next);
  el.theme.innerHTML = icon(next === "dark" ? "sun" : "moon");
});
function closeSidebar() { el.app.classList.remove("sidebar-open"); }
$("openSidebar").addEventListener("click", () => el.app.classList.add("sidebar-open"));
$("closeSidebar").addEventListener("click", closeSidebar);
$("scrim").addEventListener("click", () => { closeSidebar(); el.app.classList.remove("panel-open"); });
el.scroller.addEventListener("scroll", updateJump, { passive: true });
el.jump.addEventListener("click", () => { S.pinned = true; el.scroller.scrollTo({ top: el.scroller.scrollHeight, behavior: "smooth" }); });
document.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key.toLowerCase() === "o") { e.preventDefault(); newCase(); }
  if (e.key === "Escape") { closeSidebar(); el.app.classList.remove("panel-open"); }
});
window.addEventListener("hashchange", route);

$("starters").innerHTML = STARTERS.map((s, i) =>
  `<button class="starter" type="button" data-i="${i}">${esc(s.text)}<small>${esc(s.tag)}</small></button>`).join("");
$("starters").addEventListener("click", (e) => {
  const b = e.target.closest(".starter");
  if (!b) return;
  const s = STARTERS[Number(b.dataset.i)];
  send(s.text, s.mode || null);
});

// ------------------------------------------------------------------ start
async function loadStatus() {
  try {
    const status = await api("/api/status");
    el.mode.hidden = status.mode !== "offline";
    el.mode.textContent = "AI offline: answers from case rules";
    el.mode.title = "The AI model is not reachable, so answers come from the case rules and past cases.";
  } catch { /* handled by the PIN screen */ }
}

async function start() {
  await loadStatus();
  await loadHistory();
  route();
}

paintIcons();
setMode(S.mode);
renderCase(null);
autosize();
start();
el.input.focus();
