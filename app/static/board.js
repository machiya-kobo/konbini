// Modern layer for the board and the garden. Loaded as a module, so old
// browsers never run it; the HTML forms work without it.
document.body.classList.add("js");

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
// The board's own <main id="board"> (the board, a stream's board, Now, Review): not Settings' "Board" section, whose
// heading is <h2 id="board"> since vaultkit 0.13 (and which would reload Settings in a loop on every revision).
const board = document.querySelector("main#board");
const vault = ($('meta[name="obsidian-vault"]') || {}).content || "";   // KANBAN_OBSIDIAN_VAULT; empty = no Obsidian links
const main = $("main");
let rev = board ? board.dataset.rev : "";
let dragging = false;
let editing = false;
let sheetOpen = false;

function stored(key, fallback) {
  try { return JSON.parse(localStorage.getItem(key)) ?? fallback; } catch (e) { return fallback; }
}
function store(key, value) {
  try { localStorage.setItem(key, JSON.stringify(value)); } catch (e) { /* private mode */ }
}
// This browser's own choices live under konbini.* (the room's name). Values saved under the old kanban.* names (and
// app.hint) move over once; a value already saved under the new name wins.
for (const [from, to] of [["kanban.col", "konbini.col"], ["kanban.collapsed", "konbini.collapsed"], ["app.hint", "konbini.hint"]]) {
  try {
    const old = localStorage.getItem(from);
    if (old !== null) {
      if (localStorage.getItem(to) === null) localStorage.setItem(to, old);
      localStorage.removeItem(from);
    }
  } catch (e) { /* private mode */ }
}
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function load(src) {
  return new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = src;
    s.onload = resolve;
    s.onerror = reject;
    document.head.appendChild(s);
  });
}
async function send(method, url, body) {
  const r = await fetch(url, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (r.status >= 502 && r.status <= 504) throw new TypeError("unreachable");     // the proxy, with the board down
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || "HTTP " + r.status);
  return data;
}
// A write that didn't go through: "offline" when the request never reached the board (fetch throws a TypeError) and
// the outbox couldn't keep it either (a tag change, or no IndexedDB), else the board's reason.
function notSavedText(e) {
  return e instanceof TypeError ? "You're offline, so this wasn't saved." : "Not saved: " + (e && e.message || e);
}
function notSaved(e) { toast(notSavedText(e), 4000); }
async function refreshRev() {
  try { rev = (await (await fetch("/api/rev")).json()).rev; } catch (e) { /* next poll catches up */ }
}
function banner(cls, html) {
  const el = document.createElement("div");
  el.className = "banner " + cls;
  el.innerHTML = html;
  (main || document.body).prepend(el);
  return el;
}

// A card's column select posts its form when it changes (the page has no inline handlers: the CSP allows only
// scripts from this site). requestSubmit, unlike submit(), fires the form's submit event.
// Delegated, like the card menu and the inline edit below: the header's search pill swaps <main> for live results
// (vaultkit 0.17), and those cards must work too.
document.addEventListener("change", (ev) => {
  const s = ev.target;
  if (s instanceof HTMLSelectElement && s.matches("select[data-submit]")) s.form.requestSubmit ? s.form.requestSubmit() : s.form.submit();
});

// Forms that change the board (card moves, edits, tags, new cards, capture) post with fetch, so a lost connection
// leaves the page as it is with a line saying nothing was saved, instead of the browser's error page. The board's
// answer is followed as before: its redirect (back to the page, or to the new card), or its "Not Saved" reason
// shown under the form. Sign-in and sign-out stay ordinary posts (machiya.js handles sign-out).
document.addEventListener("submit", async (ev) => {
  const form = ev.target;
  if (ev.defaultPrevented || !(form instanceof HTMLFormElement) || form.method.toLowerCase() !== "post") return;
  const action = new URL(form.action, location.href);
  if (action.origin !== location.origin || ["/signin", "/signout"].includes(action.pathname)) return;
  ev.preventDefault();
  const data = new FormData(form);
  if (ev.submitter && ev.submitter.name) data.append(ev.submitter.name, ev.submitter.value);
  const controls = $$("button, select, input", form).filter((c) => !c.disabled);
  controls.forEach((c) => { c.disabled = true; });
  const say = (text) => {
    let msg = form.nextElementSibling;
    if (!msg || !msg.classList.contains("formmsg")) {
      msg = document.createElement("p");
      msg.className = "formmsg";
      msg.setAttribute("role", "alert");
      form.after(msg);
    }
    msg.textContent = text;
  };
  // a move, a card's fields and note, a new card: kept in the outbox when the board can't be reached
  const op = formOp(form, action, data);
  const kept = async () => {
    if (!op || !(await queue(op, true))) return false;
    say("Saved on this device. It sends when you're online.");
    if (op.kind === "create") form.reset();
    for (const [k, v] of Object.entries(op.mine || {})) {         // the next change is based on this one
      const o = form.querySelector('[name="o_' + k + '"]');
      if (o) o.value = v;
    }
    const note = form.querySelector("[name=comment]");
    if (note) note.value = "";
    if (form.matches("form.moves") && op.mine) {                  // the card page's column buttons
      form.dataset.board = op.mine.board;
      for (const btn of $$("button[name=board]", form)) btn.disabled = btn.value === op.mine.board;
    }
    controls.forEach((c) => { c.disabled = form.matches("form.moves") && op.mine && c.value === op.mine.board; });
    return true;
  };
  try {
    if (op && OB && (navigator.onLine === false || await busy()) && await kept()) return;
    const r = await fetch(action, { method: "POST", body: new URLSearchParams(data), credentials: "same-origin" });
    if (r.ok) { location.assign(r.url); return; }              // the redirect fetch followed: the page to show
    if (r.status >= 502 && r.status <= 504 && await kept()) return;
    const page = new DOMParser().parseFromString(await r.text(), "text/html");
    say(notSavedText(new Error((page.querySelector("main.msg p") || {}).textContent || "HTTP " + r.status)));
  } catch (e) {
    if (e instanceof TypeError && await kept()) return;
    say(notSavedText(e));
  }
  controls.forEach((c) => { c.disabled = false; });
});
// The outbox entry for a form, or null for one that isn't kept offline (tags, settings, sign-in)
function formOp(form, action, data) {
  if (!OB) return null;
  const path = action.pathname, get = (k) => String(data.get(k) ?? "").trim();
  if (path === "/move") {
    const el = form.closest(".card");
    const d = el ? el.dataset : { slug: get("slug"), title: ($("h1.ntitle") || {}).textContent, board: form.dataset.board };
    return get("board") && get("board") !== d.board ? cardOp(d, { board: get("board") }) : null;
  }
  const m = /^\/p\/([^/]+)$/.exec(path);
  if (m) {                                                     // the card page's form: it carries its own o_<name>
    const body = {}, mine = {};
    for (const [k, v] of data.entries()) body[k] = String(v);
    for (const k of OB.FIELDS) if (k in body && "o_" + k in body && body[k] !== body["o_" + k]) mine[k] = body[k];
    const comment = (body.comment || "").trim();
    if (!Object.keys(mine).length && !comment) return null;
    const slug = decodeURIComponent(m[1]);
    return { kind: "form", slug, title: ($("h1.ntitle") || {}).textContent || slug, label: labelOf(mine, comment), body, mine };
  }
  if (path === "/new" || path === "/share") {
    const url = get("url"), text = get("text");
    const title = (get("title") || url || text.slice(0, 80)).slice(0, 120);
    if (!title) return null;
    const tmp = "tmp-" + Date.now().toString(36) + Math.random().toString(36).slice(2, 7);
    return { kind: "create", slug: tmp, tmp, title, label: "New card",
             body: { title, area: get("area") || "projects", board: "backlog",
                     summary: path === "/share" ? [text, url].filter(Boolean).join(" ").slice(0, 300) : "",
                     confirm_new_tags: ["1", "true"].includes(get("confirm_new_tags")) } };
  }
  return null;
}

// -- PWA: service worker, offline copy, install hint ----------------------
if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/sw.js").catch(() => { /* http on the LAN, or blocked */ });
}
if (document.body.dataset.offline !== undefined) {
  const at = Date.parse(document.body.dataset.offline || "");
  let when = "";
  if (!isNaN(at)) {
    const mins = Math.max(1, Math.round((Date.now() - at) / 60000));
    when = mins < 60 ? mins + " min ago" : mins < 1440 ? Math.round(mins / 60) + " h ago" : Math.round(mins / 1440) + " d ago";
  }
  banner("offline", "<span><b>Offline.</b> Showing a copy saved " + (when || "earlier")
    + ". Your changes wait on this device until you're back online.</span>");
}
const ios = /iPhone|iPad|iPod/.test(navigator.userAgent);
const standalone = navigator.standalone === true || matchMedia("(display-mode: standalone)").matches;
// Installed apps have no browser chrome: give inner pages a back control (not the top-level pages in the nav).
const roots = ["/", "/now", "/review", "/plan", "/posts", "/calendar", "/roundup"];
if (standalone && history.length > 1 && !roots.includes(location.pathname)) {
  const back = document.createElement("button");
  back.className = "back";
  back.type = "button";
  back.setAttribute("aria-label", "Back");
  back.textContent = "\u2039";
  back.addEventListener("click", () => history.back());
  $(".topbar")?.prepend(back);
}
if (ios && !standalone && !stored("konbini.hint", false)) {
  const el = banner("hint", "<span>Install this as an app: tap <b>Share</b>, then <b>Add to Home Screen</b>.</span>"
    + '<button type="button" aria-label="Dismiss">&times;</button>');
  $("button", el).addEventListener("click", () => { store("konbini.hint", true); el.remove(); });
}

// -- action sheet: everything you can do to a card, thumb-sized -----------
const COLS = [["backlog", "Backlog"], ["ready", "Ready"], ["wip", "WIP"], ["blocked", "Blocked"], ["done", "Done"]];
let sheet;
function recount() {
  // Column, lane, header and tab counts follow the DOM after a move, so the
  // page never has to reload for its own changes.
  const totals = {};
  for (const col of $$(".col")) {
    const more = col.querySelector(":scope > .colmore");        // Done cards hidden by the Done Cards setting
    const n = col.querySelectorAll(":scope > .card").length + (more ? +more.dataset.more || 0 : 0);
    const cc = col.querySelector(".colcount");
    if (cc) cc.textContent = n;
    totals[col.dataset.board] = (totals[col.dataset.board] || 0) + n;
    const empty = col.querySelector(":scope > .colempty");
    if (n === 0 && !empty) { const p = document.createElement("p"); p.className = "colempty"; p.textContent = "No cards"; col.append(p); }
    if (n > 0 && empty) empty.remove();
  }
  for (const lane of $$("section.lane")) {
    const lc = lane.querySelector(".lanecount");
    if (lc) lc.textContent = lane.querySelectorAll(".card").length;
  }
  for (const [b, n] of Object.entries(totals)) {
    const s = $(".stat.col-" + b + " b");
    if (s) s.textContent = n;
    const t = $(".coltabs button[data-col=" + b + "] .n");
    if (t) t.textContent = n;
  }
}
function moveCard(card, to, quiet) {
  const lane = card.closest(".lane");
  const col = lane ? lane.querySelector(".col.col-" + to) : null;
  if (!col && !quiet) { location.reload(); return; }
  if (col) col.append(card);
  card.className = card.className.replace(/\bcol-\w+/, "col-" + to);
  card.dataset.board = to;
  const select = card.querySelector("select[name=board]");
  if (select) select.value = to;
  recount();
}
function openSheet(card) {
  if (!sheet) {
    sheet = document.createElement("dialog");
    sheet.className = "sheet";
    document.body.append(sheet);
    sheet.addEventListener("click", (e) => { if (e.target === sheet) sheet.close(); });
    sheet.addEventListener("close", () => { sheetOpen = false; });
  }
  const d = card.dataset;
  sheet.innerHTML = '<div class="grip"></div><button class="close" type="button" aria-label="Close">&times;</button>'
    + "<h4>" + esc(d.title) + "</h4>"
    + '<div class="moves">' + COLS.map(([c, l]) =>
      '<button type="button" class="mv col-' + c + '" data-move="' + c + '"' + (c === d.board ? " disabled" : "") + ">" + l + "</button>").join("") + "</div>"
    + '<div class="prio">' + [["1", "P1"], ["2", "P2"], ["3", "P3"], ["", "no priority"]].map(([v, l]) =>
      '<button type="button" class="quiet" data-prio="' + v + '">' + l + '</button>').join("") + '</div>'
    + '<div class="acts"><button type="button" data-act="next">Edit next…</button>'
    + '<button type="button" data-act="note">Add a note…</button>'
    + (/^tmp-/.test(d.slug) ? "" : '<a href="/p/' + encodeURIComponent(d.slug) + '">Open card</a>'
      + '<a href="/p/' + encodeURIComponent(d.slug) + '/kit">Writing kit</a>')
    + (d.garden ? '<a href="' + esc(d.garden) + '">Read in the Garden</a>' : "")
    + (d.kura ? '<a href="' + esc(d.kura) + '">View in Kura</a>' : "")
    + (vault ? '<a href="obsidian://open?vault=' + encodeURIComponent(vault) + '&file=' + encodeURIComponent(d.note) + '">Open in Obsidian</a>' : "") + '</div>';
  $(".close", sheet).onclick = () => sheet.close();
  for (const b of $$("[data-move]", sheet)) {
    b.onclick = async () => {
      const to = b.dataset.move;
      try {
        const how = await attempt(cardOp(d, { board: to }),
                                  () => send("PATCH", "/api/cards/" + encodeURIComponent(d.slug), { board: to }));
        sheet.close();
        moveCard(card, to, how === "queued");
        if (how === "queued") markCard(card, "waiting"); else await refreshRev();
      } catch (e) { notSaved(e); }
    };
  }
  for (const b of $$("[data-prio]", sheet)) {
    b.onclick = async () => {
      const v = b.dataset.prio;
      try {
        const how = await attempt(cardOp(d, { priority: v }),
                                  () => send("PATCH", "/api/cards/" + encodeURIComponent(d.slug), { priority: v ? Number(v) : null }));
        sheet.close();
        if (how === "queued") { setPriority(card, v); markCard(card, "waiting"); } else location.reload();
      } catch (e) { notSaved(e); }
    };
  }
  $("[data-act=note]", sheet).onclick = async () => {
    const v = prompt("A line for the card's history");
    if (v === null || !v.trim()) return;
    try {
      const how = await attempt(cardOp(d, {}, v.trim()),
                                () => send("POST", "/api/cards/" + encodeURIComponent(d.slug) + "/events", { type: "comment", body: v.trim() }));
      sheet.close();
      if (how === "queued") markCard(card, "waiting"); else toast("Note added");
    } catch (e) { notSaved(e); }
  };
  $("[data-act=next]", sheet).onclick = async () => {
    sheet.close();
    const el = card.querySelector(".next");
    if (el) { el.click(); return; }
    const v = prompt("Next step", d.next || "");
    if (v === null) return;
    try {
      const how = await attempt(cardOp(d, { next: v.trim() }),
                                () => send("PATCH", "/api/cards/" + encodeURIComponent(d.slug), { next: v.trim() }));
      if (how === "queued") { setNext(card, v.trim()); markCard(card, "waiting"); } else location.reload();
    } catch (e) { notSaved(e); }
  };
  sheetOpen = true;
  sheet.showModal();
}
document.addEventListener("click", (e) => {
  const b = e.target instanceof Element ? e.target.closest(".card .more") : null;
  if (b) { e.preventDefault(); e.stopPropagation(); openSheet(b.closest(".card")); }
});

// -- writing kit: hand the markdown to the share sheet, or copy it ---------
function toast(text, ms = 1800) {
  const el = document.createElement("div");
  el.className = "toast";
  el.setAttribute("role", "status");
  el.textContent = text;
  document.body.append(el);
  setTimeout(() => el.remove(), ms);
}

// -- the outbox: card changes made while the board can't be reached wait on this device (outbox.js) -----------------
// Moves, field edits, notes and new cards go in when a request never reached the board (or others already wait), show
// on the page at once with a "waiting" mark, and are sent in order on the next load, when the browser goes online,
// when the tab comes back, every 30 s while any wait, and from the worker (Background Sync). A conflict or a refusal
// stays until the person picks; nothing is dropped unseen. Tag changes aren't queued (a new tag needs a confirmation).
const OB = self.KonbiniOutbox || null;
const COLNAME = Object.fromEntries(COLS.concat([["archived", "Archived"]]));
let outbox = [];
let flushing = false, signinNeeded = false, outDlg = null;

function labelOf(mine, comment) {
  const parts = Object.entries(mine).map(([k, v]) => k === "board" ? "Move to " + (COLNAME[v] || v)
    : k === "priority" ? (v ? "P" + v : "No priority") : k === "next" ? "Next: " + v : "Edit " + k.replace("_", " "));
  if (comment) parts.push("Note: " + comment);
  return parts.join(" · ");
}
// A change to a card, with what the page showed for each field (o_<name>: the board refuses it if that changed since)
function cardOp(d, fields, comment) {
  const body = {}, mine = {};
  for (const [k, v] of Object.entries(fields)) { body[k] = String(v ?? ""); body["o_" + k] = String(d[k] ?? ""); mine[k] = body[k]; }
  if (comment) body.comment = comment;
  return { kind: "form", slug: d.slug, title: d.title || d.slug, label: labelOf(mine, comment), body, mine };
}
async function busy() {
  try { return !!OB && (await OB.all()).some((o) => o.state !== "refused"); } catch (e) { return false; }
}
async function queue(op, quiet) {
  if (!OB) return false;
  try { await OB.add(op); } catch (e) { return false; }      // private mode without IndexedDB: not saved, as before
  OB.sync();
  await showOutbox();
  if (!quiet) toast("Saved on this device. It sends when you're online.", 3000);
  return true;
}
// Today's request, or the outbox when offline (or when changes already wait, so they keep their order).
// -> "sent" | "queued"; a refusal from the board is thrown as before.
async function attempt(op, online) {
  if (OB && (navigator.onLine === false || await busy())) {
    if (await queue(op)) return "queued";
    throw new TypeError("offline");
  }
  try { await online(); return "sent"; } catch (e) {
    if (e instanceof TypeError && await queue(op)) return "queued";
    throw e;
  }
}
function setNext(el, v) {
  el.dataset.next = v;
  const p = el.querySelector(".next");
  if (p) p.textContent = "next: " + v;
}
function setPriority(el, v) {
  el.dataset.priority = v;
  for (const c of el.querySelectorAll(".meta .chip.p1, .meta .chip.p2, .meta .chip.p3")) c.remove();
  if (v) {
    const chip = document.createElement("span");
    chip.className = "chip p" + v;
    chip.textContent = "P" + v;
    metaOf(el).prepend(chip);
  }
}
function metaOf(el) {
  let meta = el.querySelector(".meta");
  if (!meta) {
    meta = document.createElement("div");
    meta.className = "meta";
    el.insertBefore(meta, el.querySelector(".more"));
  }
  return meta;
}
function markCard(el, state) {
  el.classList.add("queued");
  let chip = el.querySelector(".chip.waiting");
  if (!chip) { chip = document.createElement("span"); chip.className = "chip waiting"; metaOf(el).prepend(chip); }
  chip.classList.toggle("attention", state !== "waiting");
  chip.textContent = state === "conflict" ? "check" : state === "refused" ? "not saved" : "waiting";
}
// A new card made offline: a stand-in at the top of its lane's Backlog until the board has it
function stubCard(op) {
  let el = $$(".card").find((c) => c.dataset.slug === op.tmp);
  if (!el) {
    const lane = $$("section.lane").find((l) => l.dataset.lane === op.body.area);
    const col = lane && lane.querySelector(".col.col-backlog");
    if (!col) return;
    el = document.createElement("article");
    el.className = "card is-card col-backlog";
    Object.assign(el.dataset, { slug: op.tmp, board: "backlog", title: op.title, next: "", priority: "" });
    el.innerHTML = '<span class="title">' + esc(op.title) + '</span><button class="more" type="button" aria-label="Actions for '
      + esc(op.title) + '">&#8943;</button>';
    col.prepend(el);
    recount();
  }
  markCard(el, op.state);
}
// What a waiting change looks like on this page: applied (it hasn't reached the board yet) and marked; a conflict or a
// refusal only marked, since the page shows the board's own state again after the reload that found it
function applyOp(op) {
  if (op.kind === "create") { stubCard(op); return; }
  for (const el of $$(".card").filter((c) => c.dataset.slug === op.slug)) {
    if (op.state === "waiting") {
      const to = op.body.board;
      if (to && el.dataset.board !== to) moveCard(el, to, true);
      if (op.mine && "next" in op.mine) setNext(el, op.mine.next);
      if (op.mine && "priority" in op.mine) setPriority(el, op.mine.priority);
    }
    markCard(el, op.state);
  }
}
async function showOutbox() {
  if (!OB) return;
  try { outbox = await OB.all(); } catch (e) { outbox = []; }
  for (const el of $$(".card.queued")) {
    if (!outbox.some((o) => o.slug === el.dataset.slug)) { el.classList.remove("queued"); el.querySelector(".chip.waiting")?.remove(); }
  }
  for (const op of outbox) applyOp(op);
  const waiting = outbox.filter((o) => o.state === "waiting").length, check = outbox.length - waiting;
  let b = $(".outboxbadge");
  if (!outbox.length) b?.remove();
  else {
    if (!b) {
      b = document.createElement("button");
      b.type = "button";
      b.className = "outboxbadge";
      b.addEventListener("click", openOutbox);
      document.body.append(b);
    }
    b.classList.toggle("attention", check > 0);
    b.textContent = [waiting ? waiting + " waiting" : "", check ? check + " to check" : ""].filter(Boolean).join(" · ");
    b.title = "Changes not on the board yet";
  }
  // a card's own page says what of it is waiting
  const m = /^\/p\/([^/]+)$/.exec(location.pathname), h = $("main.detail h1.ntitle");
  if (m && h) {
    const mine = outbox.filter((o) => o.slug === decodeURIComponent(m[1]));
    let p = $(".waitmsg");
    if (!mine.length) p?.remove();
    else {
      if (!p) { p = document.createElement("p"); p.className = "waitmsg"; p.setAttribute("role", "status"); h.after(p); }
      p.textContent = "Not on the board yet: " + mine.map((o) => o.label).join("; ");
    }
  }
  if (outDlg && outDlg.open) drawOutbox();
}
function nowText(op) {
  const n = op.note || {};
  if (n.gone) return "This card is gone from the board.";
  if (n.why) return "Not saved: " + n.why;
  return "The board now has " + Object.entries(n).map(([k, v]) => k === "board" ? (COLNAME[v] || v)
    : k === "priority" ? (v ? "P" + v : "no priority") : k.replace("_", " ") + " " + (v ? "“" + v + "”" : "empty")).join(", ") + ".";
}
function drawOutbox() {
  const rows = outbox.map((op) => {
    const acts = op.state === "refused" || (op.note && op.note.gone) ? '<button type="button" class="quiet" data-drop>Dismiss</button>'
      : op.state === "conflict" ? '<button type="button" data-keep>Keep Mine</button><button type="button" class="quiet" data-drop>Use the Board’s</button>' : "";
    return '<li data-id="' + op.id + '" class="' + op.state + '"><b>' + esc(op.title) + "</b> " + esc(op.label)
      + '<span class="why">' + esc(op.state === "waiting" ? "Waiting" : nowText(op)) + "</span>"
      + (acts ? '<span class="row">' + acts + "</span>" : "") + "</li>";
  }).join("");
  outDlg.innerHTML = '<div class="grip"></div><button class="close" type="button" aria-label="Close">&times;</button><h4>Waiting to Send</h4>'
    + (signinNeeded ? '<p class="why"><a href="/signin">Sign in</a> to send these.</p>' : "")
    + (rows ? '<ul class="outlist">' + rows + "</ul>" : '<p class="why">Everything is on the board.</p>')
    + (outbox.some((o) => o.state === "waiting") ? '<p class="row"><button type="button" data-send>Send Now</button></p>' : "");
  $(".close", outDlg).onclick = () => outDlg.close();
  for (const li of $$("li[data-id]", outDlg)) {
    const id = Number(li.dataset.id);
    const keep = $("[data-keep]", li), drop = $("[data-drop]", li);
    if (keep) keep.onclick = async () => { await OB.keep(id); await showOutbox(); flushNow(); };
    if (drop) drop.onclick = async () => { await OB.drop(id); await showOutbox(); };
  }
  const go = $("[data-send]", outDlg);
  if (go) go.onclick = () => flushNow();
}
function openOutbox() {
  if (!outDlg) {
    outDlg = document.createElement("dialog");
    outDlg.className = "sheet outbox";
    document.body.append(outDlg);
    outDlg.addEventListener("click", (e) => { if (e.target === outDlg) outDlg.close(); });
    outDlg.addEventListener("close", () => { sheetOpen = false; });
  }
  drawOutbox();
  sheetOpen = true;
  outDlg.showModal();
}
async function flushNow() {
  if (!OB || flushing) return;
  let before;
  try { before = (await OB.all()).filter((o) => o.state === "waiting").length; } catch (e) { return; }
  if (!before) { await showOutbox(); return; }
  flushing = true;
  let r = null;
  try { r = await OB.flush(); } catch (e) { /* the next try */ }
  flushing = false;
  if (!r) return;
  signinNeeded = r.signin;
  await showOutbox();
  const fresh = before - r.sent - r.waiting;                   // changes that now need a look
  const say = [];
  if (r.sent) say.push(r.sent === 1 ? "Sent 1 change." : "Sent " + r.sent + " changes.");
  if (fresh > 0) say.push(fresh === 1 ? "A change needs a look." : fresh + " changes need a look.");
  if (r.signin) say.push("Sign in to send your changes.");
  if (say.length) toast(say.join(" "), 3500);
  const typing = document.activeElement && /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName);
  if ((r.sent || fresh > 0) && !editing && !dragging && !sheetOpen && !typing) setTimeout(() => location.reload(), 1500);
}
if (OB) {
  showOutbox().then(() => { if (navigator.onLine !== false) flushNow(); });
  addEventListener("online", flushNow);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) flushNow(); });
  setInterval(() => { if (outbox.some((o) => o.state === "waiting")) flushNow(); }, 30000);
  if (OB.channel) OB.channel.addEventListener("message", () => { if (!flushing) showOutbox(); });
}
for (const b of $$(".kit-share, .kit-copy")) {
  b.addEventListener("click", async () => {
    try {
      const md = await (await fetch(b.dataset.url)).text();
      const file = new File([md], b.dataset.name || "kit.md", { type: "text/markdown" });
      if (b.classList.contains("kit-share") && navigator.canShare && navigator.canShare({ files: [file] })) {
        await navigator.share({ files: [file], title: file.name });
        return;
      }
      await navigator.clipboard.writeText(md);
      toast("Markdown copied");
    } catch (e) {
      if (e && e.name !== "AbortError") toast("Couldn't share: " + e.message);
    }
  });
}
if (!(navigator.canShare)) for (const b of $$(".kit-share")) b.remove();

// -- inline edit: click a card's "next:" line to change it in place -------
document.addEventListener("click", (ev) => {
  const el = ev.target instanceof Element ? ev.target.closest(".card .next") : null;
  if (!el) return;
  {
    ev.preventDefault();
    const card = el.closest(".card");
    const input = document.createElement("input");
    input.type = "text";
    input.className = "inline-next";
    input.value = el.textContent.replace(/^next:\s*/, "");
    el.replaceWith(input);
    input.focus();
    input.select();
    editing = true;
    let finished = false;
    const done = async (save) => {
      if (finished) return;            // Enter, then the blur that taking the field away fires: save once
      finished = true;
      editing = false;
      if (save && input.value.trim() && input.value.trim() !== card.dataset.next) {
        const v = input.value.trim();
        try {
          const how = await attempt(cardOp(card.dataset, { next: v }),
                                    () => send("PATCH", "/api/cards/" + encodeURIComponent(card.dataset.slug), { next: v }));
          el.textContent = "next: " + v;
          card.dataset.next = v;
          if (how === "queued") markCard(card, "waiting"); else await refreshRev();
        } catch (e) { notSaved(e); }
      }
      input.replaceWith(el);
    };
    input.addEventListener("keydown", (k) => {
      if (k.key === "Enter") done(true);
      if (k.key === "Escape") done(false);
    });
    input.addEventListener("blur", () => done(true), { once: true });
  }
});

// The header's search pill (vaultkit 0.17) swaps <main> for live results and, when cleared, puts the page's own markup
// back. The cards in results work through the delegated handlers above; a board that comes back has lost the lanes' and
// columns' bindings (tabs, drag and drop, the filter sheet), so it reloads instead of binding twice.
if (board && main && $(".lane .col, .coltabs")) {
  let away = false;
  new MutationObserver(() => {
    if (!$(".lane .col, .coltabs", main)) away = true;
    else if (away) location.reload();
  }).observe(main, { childList: true });
}

if (board) {
  // Phones: one column at a time, picked with the tabs or a swipe.
  const coltabs = $(".coltabs");
  if (coltabs) {
    const phone = matchMedia("(max-width: 760px)");
    const buttons = $$("button", coltabs);
    let current = new URLSearchParams(location.search).get("col") || stored("konbini.col", "ready");
    const select = (col, save) => {
      if (!phone.matches) {
        delete document.body.dataset.col;
        buttons.forEach((b) => b.setAttribute("aria-selected", "false"));
        return;
      }
      document.body.dataset.col = col;
      buttons.forEach((b) => b.setAttribute("aria-selected", String(b.dataset.col === col)));
      if (save) store("konbini.col", col);
    };
    buttons.forEach((b) => b.addEventListener("click", () => { current = b.dataset.col; select(current, true); }));
    select(current, false);
    phone.addEventListener("change", () => select(current, false));
    let x0 = null, y0 = null;
    board.addEventListener("touchstart", (e) => { x0 = e.touches[0].clientX; y0 = e.touches[0].clientY; }, { passive: true });
    board.addEventListener("touchend", (e) => {
      if (x0 === null || dragging || !phone.matches) { x0 = null; return; }
      const dx = e.changedTouches[0].clientX - x0, dy = e.changedTouches[0].clientY - y0;
      x0 = null;
      if (Math.abs(dx) < 70 || Math.abs(dy) > 60) return;
      const i = buttons.findIndex((b) => b.dataset.col === current);
      const next = buttons[i + (dx < 0 ? 1 : -1)];
      if (next) { current = next.dataset.col; select(current, true); }
    }, { passive: true });
  }

  // Filters: inline on desktop, a sheet on phones.
  const fbtn = $(".filterbtn"), fbar = $(".filterbar");
  if (fbtn && fbar) {
    fbtn.addEventListener("click", () => {
      let dlg = $("dialog.filters");
      if (!dlg) {
        dlg = document.createElement("dialog");
        dlg.className = "sheet filters";
        dlg.innerHTML = '<div class="grip"></div><button class="close" type="button" aria-label="Close">&times;</button><h4>Filters</h4>';
        dlg.append(fbar);
        document.body.append(dlg);
        $(".close", dlg).onclick = () => dlg.close();
        dlg.addEventListener("click", (e) => { if (e.target === dlg) dlg.close(); });
      }
      dlg.showModal();
    });
  }

  // Keyboard: j/k select, 1-5 move the selected card, / search, n new card, Enter opens.
  let selected = -1;
  const visible = () => $$(".card").filter((c) => c.offsetParent !== null);
  const select = (i) => {
    const cards = visible();
    if (!cards.length) return;
    selected = Math.max(0, Math.min(cards.length - 1, i));
    for (const c of cards) c.classList.remove("selected");
    cards[selected].classList.add("selected");
    cards[selected].scrollIntoView({ block: "nearest" });
  };
  document.addEventListener("keydown", async (k) => {
    const t = k.target;
    if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable)) {
      if (k.key === "Escape") t.blur();
      return;
    }
    if (k.metaKey || k.ctrlKey || k.altKey || sheetOpen) return;
    if (k.key === "j") { select(selected + 1); k.preventDefault(); }
    else if (k.key === "k") { select(selected - 1); k.preventDefault(); }
    else if (k.key === "n") { const t2 = $(".newform input[name=title]"); if (t2) { t2.focus(); k.preventDefault(); } }
    else if (k.key === "Enter" && selected >= 0) { const c = visible()[selected]; if (c) location.href = "/p/" + encodeURIComponent(c.dataset.slug); }
    else if (k.key === "Escape") { for (const c of $$(".card.selected")) c.classList.remove("selected"); selected = -1; }
    else if (/^[1-5]$/.test(k.key) && selected >= 0) {
      const card = visible()[selected];
      const to = COLS[Number(k.key) - 1][0];
      if (!card || card.dataset.board === to) return;
      try {
        const how = await attempt(cardOp(card.dataset, { board: to }),
                                  () => send("PATCH", "/api/cards/" + encodeURIComponent(card.dataset.slug), { board: to }));
        moveCard(card, to, how === "queued");
        if (how === "queued") markCard(card, "waiting"); else await refreshRev();
      } catch (e) { notSaved(e); }
    }
  });

  // Collapsible swimlanes, remembered per browser.
  const collapsed = new Set(stored("konbini.collapsed", []));
  for (const lane of $$("section.lane")) {
    const head = lane.querySelector(".lanehead");
    if (!head) continue;
    const btn = document.createElement("button");
    btn.className = "lanetoggle";
    btn.type = "button";
    const sync = () => {
      const closed = collapsed.has(lane.dataset.lane);
      lane.classList.toggle("collapsed", closed);
      btn.textContent = closed ? "▸" : "▾";
      btn.setAttribute("aria-expanded", String(!closed));
      btn.title = closed ? "expand" : "collapse";
    };
    btn.addEventListener("click", () => {
      collapsed.has(lane.dataset.lane) ? collapsed.delete(lane.dataset.lane) : collapsed.add(lane.dataset.lane);
      store("konbini.collapsed", [...collapsed]);
      sync();
    });
    head.prepend(btn);
    sync();
  }

  // Done columns: the newest five, then "show N more".
  for (const col of $$(".col.col-done")) {
    const hidden = col.querySelectorAll(":scope > .card").length - 5;
    if (hidden > 0) {
      const more = document.createElement("button");
      more.className = "moreb";
      more.type = "button";
      more.textContent = "show " + hidden + " more";
      more.addEventListener("click", () => {
        const open = col.classList.toggle("expanded");
        more.textContent = open ? "show less" : "show " + hidden + " more";
      });
      col.append(more);
    }
  }

  // Drag and drop within a swimlane (long press on touch); the drop sends the
  // column's new order and the server writes board + rank.
  if ($(".lane .col")) {
    await load(board.dataset.sortable || "/static/Sortable.min.js");   // the versioned URL the worker precached
    for (const lane of $$("section.lane")) {
      for (const col of lane.querySelectorAll(".col")) {
        window.Sortable.create(col, {
          group: "lane-" + lane.dataset.lane,
          draggable: ".card",
          filter: "select, input, button",
          preventOnFilter: false,
          animation: 150,
          ghostClass: "ghost",
          delay: 150,
          delayOnTouchOnly: true,
          onStart() { dragging = true; },
          async onEnd(ev) {
            setTimeout(() => { dragging = false; }, 50);
            if (ev.from === ev.to && ev.oldIndex === ev.newIndex) return;
            const to = ev.to;
            const cards = [...to.querySelectorAll(".card")];
            const slugs = cards.map((c) => c.dataset.slug);
            // where each card was when this page showed it (the moved one came from the other column): the board leaves a
            // card alone that somebody moved meanwhile, and the page reloads to show what is true
            const from = {};
            for (const c of cards) from[c.dataset.slug] = c === ev.item ? ev.from.dataset.board : c.dataset.board;
            // offline it waits in the outbox; a card made offline isn't on the board to order yet, so only its column goes
            const item = ev.item, real = slugs.filter((x) => !/^tmp-/.test(x));
            const op = /^tmp-/.test(item.dataset.slug)
              ? cardOp(Object.assign({}, item.dataset, { board: ev.from.dataset.board }), { board: to.dataset.board })
              : { kind: "order", slug: item.dataset.slug, title: item.dataset.title, label: labelOf({ board: to.dataset.board }),
                  body: { board: to.dataset.board, slugs: real, from: Object.fromEntries(real.map((x) => [x, from[x]])) },
                  mine: { board: to.dataset.board } };
            let r = {};
            try {
              const how = await attempt(op, async () => { r = await send("POST", "/api/order", { board: to.dataset.board, slugs, from }); });
              if (r.skipped && r.skipped.length) { location.reload(); return; }
              item.className = item.className.replace(/\bcol-\w+/, "col-" + to.dataset.board);
              item.dataset.board = to.dataset.board;
              const select = item.querySelector("select[name=board]");
              if (select) select.value = to.dataset.board;
              recount();
              if (how === "queued") markCard(item, "waiting"); else await refreshRev();
            } catch (e) {
              notSaved(e);
              if (!(e instanceof TypeError)) { location.reload(); return; }
              ev.from.insertBefore(item, ev.from.children[ev.oldIndex] || null);   // not kept: put it back
              recount();
            }
          },
        });
      }
    }
  }

  // Changes from agents and other devices: reload when the board's revision
  // moves. Server-sent events when they work; polling every 30 s otherwise.
  const maybeReload = (next) => {
    if (next && next !== rev && !dragging && !editing && !sheetOpen && !document.hidden) location.reload();
  };
  let streaming = false;
  if (window.EventSource) {
    const es = new EventSource("/api/stream");
    es.onmessage = (m) => { streaming = true; maybeReload(m.data); };
    es.onerror = () => { streaming = false; };
  }
  setInterval(async () => {
    if (streaming) return;
    try { maybeReload((await (await fetch("/api/rev")).json()).rev); } catch (e) { /* offline */ }
  }, 30000);
  document.addEventListener("visibilitychange", async () => {
    if (!document.hidden) {
      try { maybeReload((await (await fetch("/api/rev")).json()).rev); } catch (e) { /* ignore */ }
    }
  });
}

// Mermaid diagrams in notes (Niwa; Obsidian's ```mermaid blocks, which python-markdown renders as
// <pre><code class="language-mermaid">). The vendored library (static/mermaid.min.js, ~5.5 MB, MIT) is fetched only
// on a page that has a diagram, and cached for a year (bump MERMAID_V with the file). Colours follow the page theme
// (Tokyo Night / Day). securityLevel "strict": no scripts or click handlers from note text. A diagram that fails to
// render keeps its source visible.
const MERMAID_V = "12.0.0";
let mermaidN = 0, mermaidLoad = null;
function mermaidDiagrams(root = document) {
  const blocks = [...root.querySelectorAll("pre > code.language-mermaid")];
  if (!blocks.length) return;
  const body = document.body.classList;
  const dark = body.contains("theme-night") ||
    (!body.contains("theme-day") && window.matchMedia("(prefers-color-scheme: dark)").matches);
  const vars = dark
    ? {background: "#1a1b26", primaryColor: "#24283b", primaryTextColor: "#c0caf5", primaryBorderColor: "#7aa2f7",
       secondaryColor: "#1f2335", tertiaryColor: "#16161e", lineColor: "#7aa2f7", textColor: "#c0caf5",
       clusterBkg: "#1f2335", clusterBorder: "#3b4261", edgeLabelBackground: "#1f2335", noteBkgColor: "#292e42",
       noteTextColor: "#c0caf5", actorBkg: "#24283b", actorBorder: "#7aa2f7", actorTextColor: "#c0caf5",
       signalColor: "#c0caf5", signalTextColor: "#c0caf5"}
    : {background: "#e1e2e7", primaryColor: "#e9e9ed", primaryTextColor: "#343b58", primaryBorderColor: "#2e7de9",
       secondaryColor: "#d5d8e4", tertiaryColor: "#eef0f5", lineColor: "#2e7de9", textColor: "#343b58",
       clusterBkg: "#eef0f5", clusterBorder: "#c4c8da", edgeLabelBackground: "#eef0f5", noteBkgColor: "#d5d8e4",
       noteTextColor: "#343b58", actorBkg: "#e9e9ed", actorBorder: "#2e7de9", actorTextColor: "#343b58",
       signalColor: "#343b58", signalTextColor: "#343b58"};
  mermaidLoad = mermaidLoad || new Promise((ok) => {      // the library loads once per page
    const s = document.createElement("script");
    s.src = "/static/mermaid.min.js?v=" + MERMAID_V;
    s.onload = () => {
      window.mermaid.initialize({startOnLoad: false, securityLevel: "strict", theme: "base", themeVariables: vars,
                                 fontFamily: "inherit", flowchart: {htmlLabels: true, useMaxWidth: true}});
      ok(window.mermaid);
    };
    document.head.appendChild(s);
  });
  mermaidLoad.then(async (mm) => {
    for (const code of blocks) {
      const n = ++mermaidN;
      const pre = code.parentElement;
      try {
        const {svg} = await mm.render("mmd-" + n, code.textContent);
        const div = document.createElement("div");
        div.className = "mermaid-diagram";
        div.innerHTML = svg;
        pre.replaceWith(div);
      } catch (err) {
        pre.title = "Mermaid couldn't render this diagram: " + (err && err.message || err);
        document.querySelectorAll("#dmmd-" + n).forEach((x) => x.remove());   // mermaid's error box
      }
    }
  });
}
mermaidDiagrams();
