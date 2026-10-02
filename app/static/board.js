// Modern layer for the board and the garden. Loaded as a module, so old
// browsers never run it; the HTML forms work without it.
document.body.classList.add("js");

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const app = document.body.dataset.app || "kanban";
const gardenBase = app === "kanban" ? "/garden" : "";
const board = document.getElementById("board");
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
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || "HTTP " + r.status);
  return data;
}
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
  banner("offline", "<span><b>Offline.</b> Showing a saved copy" + (when ? " from " + when : "") + ". Is Tailscale on?</span>");
}
const ios = /iPhone|iPad|iPod/.test(navigator.userAgent);
const standalone = navigator.standalone === true || matchMedia("(display-mode: standalone)").matches;
// Installed apps have no browser chrome: give inner pages a back control.
const roots = ["/", "/now", "/calendar", "/roundup", "/garden/", "/stream", "/tags", "/queue"];
if (standalone && history.length > 1 && !roots.includes(location.pathname)) {
  const back = document.createElement("button");
  back.className = "back";
  back.type = "button";
  back.setAttribute("aria-label", "Back");
  back.textContent = "\u2039";
  back.addEventListener("click", () => history.back());
  $(".topbar")?.prepend(back);
}
if (ios && !standalone && !stored("app.hint", false)) {
  const el = banner("hint", "<span>Install this as an app: tap <b>Share</b>, then <b>Add to Home Screen</b>.</span>"
    + '<button type="button" aria-label="Dismiss">&times;</button>');
  $("button", el).addEventListener("click", () => { store("app.hint", true); el.remove(); });
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
    if (n === 0 && !empty) { const d = document.createElement("div"); d.className = "colempty"; col.append(d); }
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
function moveCard(card, to) {
  const lane = card.closest(".lane");
  const col = lane ? lane.querySelector(".col.col-" + to) : null;
  if (!col) { location.reload(); return; }
  col.append(card);
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
  const note = d.note.split("/").map(encodeURIComponent).join("/");
  sheet.innerHTML = '<div class="grip"></div><button class="close" type="button" aria-label="Close">&times;</button>'
    + "<h4>" + esc(d.title) + "</h4>"
    + '<div class="moves">' + COLS.map(([c, l]) =>
      '<button type="button" class="mv col-' + c + '" data-move="' + c + '"' + (c === d.board ? " disabled" : "") + ">" + l + "</button>").join("") + "</div>"
    + '<div class="prio">' + [["1", "P1"], ["2", "P2"], ["3", "P3"], ["", "no priority"]].map(([v, l]) =>
      '<button type="button" class="quiet" data-prio="' + v + '">' + l + '</button>').join("") + '</div>'
    + '<div class="acts"><button type="button" data-act="next">Edit next…</button>'
    + '<button type="button" data-act="note">Add a note…</button>'
    + '<a href="/p/' + encodeURIComponent(d.slug) + '">Open card</a>'
    + '<a href="/p/' + encodeURIComponent(d.slug) + '/kit">Writing kit</a>'
    + '<a href="' + gardenBase + "/n/" + note + '">' + (d.publish === "1" ? "Read in the garden" : "Garden preview / publish") + "</a>"
    + (vault ? '<a href="obsidian://open?vault=' + encodeURIComponent(vault) + '&file=' + encodeURIComponent(d.note) + '">Open in Obsidian</a>' : "") + '</div>';
  $(".close", sheet).onclick = () => sheet.close();
  for (const b of $$("[data-move]", sheet)) {
    b.onclick = async () => {
      try {
        await send("PATCH", "/api/cards/" + encodeURIComponent(d.slug), { board: b.dataset.move });
        sheet.close();
        moveCard(card, b.dataset.move);
        await refreshRev();
      } catch (e) { alert("Not saved: " + e.message); }
    };
  }
  for (const b of $$("[data-prio]", sheet)) {
    b.onclick = async () => {
      try {
        await send("PATCH", "/api/cards/" + encodeURIComponent(d.slug), { priority: b.dataset.prio ? Number(b.dataset.prio) : null });
        sheet.close();
        location.reload();
      } catch (e) { alert("Not saved: " + e.message); }
    };
  }
  $("[data-act=note]", sheet).onclick = async () => {
    const v = prompt("A line for the card's history");
    if (v === null || !v.trim()) return;
    try {
      await send("POST", "/api/cards/" + encodeURIComponent(d.slug) + "/events", { type: "comment", body: v.trim() });
      sheet.close();
      toast("Note added");
    } catch (e) { alert("Not saved: " + e.message); }
  };
  $("[data-act=next]", sheet).onclick = () => {
    sheet.close();
    const el = card.querySelector(".next");
    if (el) { el.click(); return; }
    const v = prompt("Next step", d.next || "");
    if (v === null) return;
    send("PATCH", "/api/cards/" + encodeURIComponent(d.slug), { next: v.trim() })
      .then(() => location.reload()).catch((e) => alert("Not saved: " + e.message));
  };
  sheetOpen = true;
  sheet.showModal();
}
for (const b of $$(".card .more")) {
  b.addEventListener("click", (e) => { e.preventDefault(); e.stopPropagation(); openSheet(b.closest(".card")); });
}

// -- writing kit: hand the markdown to the share sheet, or copy it ---------
function toast(text) {
  const el = document.createElement("div");
  el.className = "toast";
  el.textContent = text;
  document.body.append(el);
  setTimeout(() => el.remove(), 1800);
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
for (const el of $$(".card .next")) {
  el.addEventListener("click", (ev) => {
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
    const done = async (save) => {
      editing = false;
      if (save && input.value.trim()) {
        try {
          await send("PATCH", "/api/cards/" + encodeURIComponent(card.dataset.slug), { next: input.value.trim() });
          el.textContent = "next: " + input.value.trim();
          card.dataset.next = input.value.trim();
          await refreshRev();
        } catch (e) { alert("Not saved: " + e.message); }
      }
      input.replaceWith(el);
    };
    input.addEventListener("keydown", (k) => {
      if (k.key === "Enter") done(true);
      if (k.key === "Escape") done(false);
    });
    input.addEventListener("blur", () => done(true), { once: true });
  });
}

if (board) {
  // Phones: one column at a time, picked with the tabs or a swipe.
  const coltabs = $(".coltabs");
  if (coltabs) {
    const phone = matchMedia("(max-width: 760px)");
    const buttons = $$("button", coltabs);
    let current = new URLSearchParams(location.search).get("col") || stored("kanban.col", "ready");
    const select = (col, save) => {
      if (!phone.matches) {
        delete document.body.dataset.col;
        buttons.forEach((b) => b.setAttribute("aria-selected", "false"));
        return;
      }
      document.body.dataset.col = col;
      buttons.forEach((b) => b.setAttribute("aria-selected", String(b.dataset.col === col)));
      if (save) store("kanban.col", col);
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
        await send("PATCH", "/api/cards/" + encodeURIComponent(card.dataset.slug), { board: to });
        moveCard(card, to);
        await refreshRev();
      } catch (e) { alert("Not saved: " + e.message); }
    }
  });

  // Collapsible swimlanes, remembered per browser.
  const collapsed = new Set(stored("kanban.collapsed", []));
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
      store("kanban.collapsed", [...collapsed]);
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
    await load("/static/Sortable.min.js");
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
            const slugs = [...to.querySelectorAll(".card")].map((c) => c.dataset.slug);
            try {
              await send("POST", "/api/order", { board: to.dataset.board, slugs });
              ev.item.className = ev.item.className.replace(/\bcol-\w+/, "col-" + to.dataset.board);
              ev.item.dataset.board = to.dataset.board;
              const select = ev.item.querySelector("select[name=board]");
              if (select) select.value = to.dataset.board;
              recount();
              await refreshRev();
            } catch (e) {
              alert("Not saved: " + e.message);
              location.reload();
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
