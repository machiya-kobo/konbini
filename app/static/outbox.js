// SPDX-License-Identifier: AGPL-3.0-or-later
// The outbox: card changes made while the board can't be reached wait here, on this device (IndexedDB, per origin), and
// are sent in order when it can be reached again. Shared by the pages (board.js) and the service worker (background
// sync), so it is a classic script that sets self.KonbiniOutbox and touches no DOM.
//
// An entry ("op"): {id, at, kind, slug, title, label, body, mine, state, note, tmp}
//   kind "form":   POST /p/<slug> with the card form's fields (body), each with what it was based on (o_<name>), so the
//                  board's own rule refuses a field somebody else changed meanwhile (409); "comment" adds a history line
//   kind "order":  POST /api/order {board, slugs, from} (a drag); the board skips a card that moved meanwhile
//   kind "create": POST /api/cards {title, area, board, summary}; `tmp` is the card's stand-in slug until the board
//                  answers with the real one, which then replaces it in the entries behind it
//   state: "waiting" (to send), "conflict" (the card changed or is gone: the person decides; `note` is the board's
//   now), "refused" (the board said no for another reason: shown until dismissed; `note` is why)
// Nothing here stores a credential: each send goes with the browser's own session cookie, as any page request does.
(function () {
  "use strict";
  const DB = "konbini-outbox", STORE = "ops", LOCK = "konbini-outbox", SYNC = "konbini-outbox";
  const FIELDS = ["board", "next", "priority", "blocked_by", "dependsOn", "stream", "goal", "due", "post", "post_url"];
  let dbp = null;

  function open() {
    if (!dbp) {
      dbp = new Promise((resolve, reject) => {
        const req = indexedDB.open(DB, 1);
        req.onupgradeneeded = () => req.result.createObjectStore(STORE, { keyPath: "id", autoIncrement: true });
        req.onsuccess = () => resolve(req.result);
        req.onerror = () => { dbp = null; reject(req.error); };
      });
    }
    return dbp;
  }
  async function tx(mode, fn) {
    const db = await open();
    return new Promise((resolve, reject) => {
      const t = db.transaction(STORE, mode);
      const out = fn(t.objectStore(STORE));
      t.oncomplete = () => resolve(out && "result" in out ? out.result : undefined);
      t.onerror = t.onabort = () => reject(t.error);
    });
  }
  const all = () => tx("readonly", (s) => s.getAll()).then((ops) => (ops || []).sort((a, b) => a.id - b.id));
  const put = (op) => tx("readwrite", (s) => s.put(op));
  const remove = (id) => tx("readwrite", (s) => s.delete(id));
  async function add(op) {
    op = Object.assign({ at: new Date().toISOString(), state: "waiting" }, op);
    op.id = await tx("readwrite", (s) => s.add(op));
    changed();
    return op;
  }
  // Other tabs (and the pages, after the worker's sync) redraw their badge
  let channel = null;
  try { channel = new BroadcastChannel(DB); } catch (e) { /* old browser */ }
  function changed() { try { channel && channel.postMessage("changed"); } catch (e) { /* closed */ } }

  // -- one entry to the board ------------------------------------------------------------------------------------
  function norm(field, value) {
    if (Array.isArray(value)) value = value.join(", ");
    value = value === null || value === undefined ? "" : String(value);
    return field === "post" && !value ? "none" : value;
  }
  // What the board's error page says (shell.message: <main class="msg">…<p>why</p>), without a DOM (the worker has none)
  function reason(html, status) {
    const m = /<main class="msg">[\s\S]*?<p>([\s\S]*?)<\/p>/.exec(html || "");
    const text = m ? m[1].replace(/<[^>]*>/g, "").replace(/&#x27;|&#39;/g, "'").replace(/&quot;/g, '"')
      .replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&amp;/g, "&") : "";
    return text || "HTTP " + status;
  }
  function request(op) {
    if (op.kind === "form") {
      return fetch("/p/" + encodeURIComponent(op.slug), {
        method: "POST", body: new URLSearchParams(op.body), credentials: "same-origin", redirect: "manual",
      });
    }
    const url = op.kind === "order" ? "/api/order" : "/api/cards";
    return fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(op.body),
                        credentials: "same-origin" });
  }
  async function card(slug) {
    const r = await fetch("/api/cards/" + encodeURIComponent(slug), { credentials: "same-origin" });
    if (r.status === 404) return null;
    if (!r.ok) throw Object.assign(new Error("HTTP " + r.status), { status: r.status });
    return r.json();
  }
  // -> "sent" | "offline" | "signin" | "conflict" | "refused" (op.note says why); a "sent" create carries op.slug
  async function sendOne(op) {
    const r = await request(op);                                  // a TypeError (never reached the board) propagates
    if (r.type === "opaqueredirect" || r.ok) {                    // the form's redirect back to the card, or 2xx
      if (op.kind === "order") {
        const data = await r.json().catch(() => ({}));
        const moved = (data.skipped || []).filter((s) => s === op.slug);
        if (moved.length) {
          const now = await card(op.slug);
          op.note = now ? { board: norm("board", now.board) } : { gone: true };
          return "conflict";
        }
      }
      if (op.kind === "create") op.created = (await r.json().catch(() => ({}))).slug || "";
      return "sent";
    }
    if (r.status === 401) return "signin";
    if (r.status >= 500 || r.status === 429) return "offline";     // a proxy with the board down, or a busy board
    const text = await r.text().catch(() => "");
    let data = {};
    try { data = JSON.parse(text); } catch (e) { /* the form's HTML answer */ }
    if (op.kind === "create" && r.status === 409 && data.code === "exists" && data.slug) {
      // a send that reached the board but whose answer was lost: the card is there already
      const now = await card(data.slug);
      if (now && now.title === op.body.title) { op.created = data.slug; return "sent"; }
    }
    if (op.kind === "form" && (r.status === 409 || r.status === 404)) {
      const now = await card(op.slug);
      if (!now) { op.note = { gone: true }; return "conflict"; }
      const mine = op.mine || {};
      const diff = Object.keys(mine).filter((k) => norm(k, now[k]) !== norm(k, mine[k]));
      if (!diff.length) return "sent";                           // the board has these values already
      op.note = {};
      for (const k of Object.keys(mine)) op.note[k] = norm(k, now[k]);
      return "conflict";
    }
    op.note = { why: data.error || reason(text, r.status) };
    return "refused";
  }

  // -- the whole queue, in order ---------------------------------------------------------------------------------
  // -> {sent, conflicts, refused, waiting, offline, signin}. An entry waits behind an earlier one for the same card
  // that needs a look (or a card not created yet), so a card's changes are never applied out of order.
  async function flushLocked() {
    const out = { sent: 0, conflicts: 0, refused: 0, waiting: 0, offline: false, signin: false };
    const held = new Set();
    for (const op of await all()) {
      if (op.state === "conflict") { held.add(op.slug); out.conflicts++; continue; }
      if (op.state === "refused") { out.refused++; continue; }
      if (out.offline || out.signin || held.has(op.slug) || /^tmp-/.test(op.slug || "") && op.kind !== "create") {
        if (/^tmp-/.test(op.slug || "")) held.add(op.slug);
        out.waiting++;
        continue;
      }
      let result;
      try { result = await sendOne(op); } catch (e) { result = "offline"; }
      if (result === "offline" || result === "signin") { out[result] = true; out.waiting++; continue; }
      if (result === "sent") {
        await remove(op.id);
        out.sent++;
        if (op.kind === "create" && op.created) {                // the stand-in slug becomes the board's
          for (const later of await all()) {
            if (later.slug === op.tmp) { later.slug = op.created; await put(later); }
          }
        }
        continue;
      }
      op.state = result;
      await put(op);
      if (result === "conflict") { held.add(op.slug); out.conflicts++; } else out.refused++;
      if (result === "refused" && op.kind === "create") {           // its card was never made: nor are its changes
        for (const later of await all()) {
          if (later.id !== op.id && later.slug === op.tmp && later.state === "waiting") {
            later.state = "refused";
            later.note = { why: "Its new card wasn't saved." };
            await put(later);
          }
        }
      }
    }
    changed();
    return out;
  }
  function flush() {
    // one sender at a time across this browser's tabs and its worker (where Web Locks exist)
    if (self.navigator && navigator.locks && navigator.locks.request) return navigator.locks.request(LOCK, flushLocked);
    return flushLocked();
  }
  // Keep Mine: send it again without what it was based on (the board then takes these values); a card that is gone
  // can't be kept. Use the Board's (or Dismiss): drop it.
  async function keep(id) {
    const op = (await all()).find((o) => o.id === id);
    if (!op) return;
    if (op.kind === "form") for (const k of Object.keys(op.body)) if (k.startsWith("o_")) delete op.body[k];
    if (op.kind === "order") delete op.body.from;
    op.state = "waiting";
    delete op.note;
    await put(op);
    changed();
  }
  async function drop(id) { await remove(id); changed(); }
  // Ask the worker to send when the connection is back (Chromium's Background Sync); elsewhere the pages send on their
  // next load, when the browser goes online, and when the tab comes back.
  async function sync() {
    try {
      const reg = await navigator.serviceWorker.ready;
      if (reg.sync) await reg.sync.register(SYNC);
    } catch (e) { /* no worker, or no Background Sync */ }
  }

  self.KonbiniOutbox = { FIELDS, SYNC, all, add, put, drop, keep, flush, sync, norm, channel };
})();
