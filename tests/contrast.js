// The contrast audit test_contrast.py runs in each page: every visible element with text of its own, its colour
// against the background it is drawn on (the translucent layers under it blended down to an opaque one), WCAG's
// ratio, and whether it falls short (4.5:1, or 3:1 for large text: 24px, or 18.66px bold). -> [[what, ratio, need]].
// A sentence that names its element and colours, so a failure says where to look.
(() => {
  const cv = document.createElement("canvas").getContext("2d", { willReadFrequently: true });
  const rgba = (c) => {                    // any CSS colour (rgb(), color(srgb …), named) -> [r, g, b, a] in 0-255 / 0-1
    cv.clearRect(0, 0, 1, 1);
    cv.fillStyle = "#000";
    cv.fillStyle = c;
    cv.fillRect(0, 0, 1, 1);
    const d = cv.getImageData(0, 0, 1, 1).data;
    return [d[0], d[1], d[2], d[3] / 255];
  };
  const over = (top, under) => [0, 1, 2].map((i) => top[i] * top[3] + under[i] * (1 - top[3])).concat(1);
  const lum = (c) => {
    const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
    return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]);
  };
  const ratio = (a, b) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
  const backdrop = (el) => {               // the colours under el, nearest first, down to the first opaque one
    const layers = [];
    for (let n = el; n; n = n.parentElement) {
      const c = rgba(getComputedStyle(n).backgroundColor);
      if (c[3] > 0) layers.push(c);
      if (c[3] >= 1) break;
    }
    let bg = [255, 255, 255, 1];
    if (!layers.length || layers[layers.length - 1][3] < 1) bg = rgba(getComputedStyle(document.documentElement).backgroundColor);
    for (const c of layers.reverse()) bg = over(c, bg);
    return bg;
  };
  const out = [];
  const seen = new Set();
  for (const el of document.querySelectorAll("body *")) {
    if (el.closest("svg, script, style, noscript, template, .mermaid-diagram, [aria-hidden=true]")) continue;
    const own = [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim());
    const field = el.matches("input:not([type=hidden]):not([type=checkbox]):not([type=radio]), select, textarea") && (el.value || "").trim();
    if (!own && !field) continue;
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height || el.closest("[hidden], dialog:not([open])")) continue;
    const st = getComputedStyle(el);
    if (st.visibility === "hidden" || +st.opacity === 0) continue;
    let fade = 1;                          // an ancestor's opacity fades the text as well
    for (let n = el; n; n = n.parentElement) fade *= +getComputedStyle(n).opacity;
    const bg = backdrop(el);
    const fgc = rgba(st.color);
    const fg = over([fgc[0], fgc[1], fgc[2], fgc[3] * fade], bg);
    const size = parseFloat(st.fontSize), bold = +st.fontWeight >= 700;
    const need = size >= 24 || (bold && size >= 18.66) ? 3 : 4.5;
    const got = ratio(fg, bg);
    if (got + 0.005 < need) {
      const cls = typeof el.className === "string" && el.className.trim() ? "." + el.className.trim().split(/\s+/).join(".") : "";
      const parent = el.parentElement;
      const pcls = parent && typeof parent.className === "string" && parent.className.trim() ? "." + parent.className.trim().split(/\s+/)[0] : "";
      const text = (field ? el.value : el.textContent).trim().replace(/\s+/g, " ").slice(0, 24);
      const key = el.tagName + cls + "|" + st.color + "|" + bg.join(",");
      if (seen.has(key)) continue;
      seen.add(key);
      out.push([(parent ? parent.tagName.toLowerCase() + pcls + " > " : "") + el.tagName.toLowerCase() + cls + " \"" + text + "\" "
                + st.color + " on rgb(" + bg.slice(0, 3).map(Math.round).join(", ") + ")", +got.toFixed(2), need]);
    }
  }
  return out;
})()
