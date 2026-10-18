/* AI Inflation Expectations Panel: renders data/*.json written by hfie/site.py. */
"use strict";

const Q = {
  q4: { short: "Q4", label: "Expected inflation, next 12 months", unit: "%" },
  q5: { short: "Q5", label: "Expected inflation, 12 months starting 4 years ahead", unit: "%" },
  q1: { short: "Q1", label: "Perceived inflation, last 12 months", unit: "%" },
  q2_mean: { short: "Q2 mean", label: "Mean of the 1-year probability distribution", unit: "%" },
  q3_mean: { short: "Q3 mean", label: "Mean of the 5-year probability distribution", unit: "%" },
  q2_sd: { short: "Q2 SD", label: "Uncertainty of the 1-year distribution (SD)", unit: "pp" },
  q3_sd: { short: "Q3 SD", label: "Uncertainty of the 5-year distribution (SD)", unit: "pp" },
};
const ARM_LABEL = { none: "No news", general: "General news", economy: "Economy news", politics: "Politics news", entertainment: "Entertainment (placebo)" };
const ARM_SHORT = { none: "No news", general: "General", economy: "Economy", politics: "Politics", entertainment: "Entertainment" };
const ARM_COLOR = { none: "var(--c-none)", general: "var(--c1)", economy: "var(--c2)", politics: "var(--c3)", entertainment: "var(--c4)" };
const PERSONA_LABEL = { generic: "Generic agent", household: "Household head", firm: "Firm CEO", forecaster: "Forecaster" };
const SERIES_COLORS = ["var(--c1)", "var(--c2)", "var(--c3)", "var(--c4)", "var(--c5)", "var(--c6)", "var(--c7)", "var(--c8)"];
const f2 = d3.format(".2f"), s2 = d3.format("+.2f"), pct = d3.format(".0%"), usd = d3.format("$.2f"), usd3 = d3.format("$.3f"), int = d3.format(",.0f");
const etFmt = new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", month: "short", day: "numeric", hour: "numeric" });
const etDay = new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", month: "short", day: "numeric" });

const S = {
  index: null, rows: new Map(), waveCache: new Map(),
  ov: { q: "q4", split: "arm", model: -1, persona: -1, arm: -1, hidden: new Set() },
  wv: { id: null, qHeat: "q4", aHeat: -1, qEff: "q4", aNews: "economy", qBins: "q2" },
};

/* ------------------------------------------------------------------ helpers */
const $ = (id) => document.getElementById(id);
const el = (tag, attrs = {}, ...kids) => {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") n.className = v; else if (k === "text") n.textContent = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v); else if (v !== undefined && v !== null) n.setAttribute(k, v);
  }
  kids.flat().forEach((c) => c != null && n.append(c instanceof Node ? c : document.createTextNode(c)));
  return n;
};
const key = (w, m, p, a) => `${w}|${m}|${p}|${a}`;
function val(w, m, p, a, q) {
  const r = S.rows.get(key(w, m, p, a));
  if (!r) return null;
  const i = S.index.series_fields.indexOf(q);
  return r[i];
}
const fmtQ = (q, v) => (v == null ? "—" : f2(v));
const tip = $("tip");
function showTip(ev, head, lines) {
  tip.replaceChildren(el("div", { class: "h", text: head }), ...lines.map(([sw, name, value]) =>
    el("div", { class: "r" }, el("span", {}, sw ? el("i", { class: "sw dot", style: `background:${sw}` }) : null, name), el("b", { text: value }))));
  tip.hidden = false;
  const w = tip.offsetWidth, h = tip.offsetHeight;
  let x = ev.clientX + 14, y = ev.clientY + 14;
  if (x + w > window.innerWidth - 8) x = ev.clientX - w - 14;
  if (y + h > window.innerHeight - 8) y = ev.clientY - h - 14;
  tip.style.left = Math.max(8, x) + "px"; tip.style.top = Math.max(8, y) + "px";
}
const hideTip = () => { tip.hidden = true; };
function seg(id, options, get, set) {
  const box = $(id);
  box.replaceChildren(...Object.entries(options).map(([k, label]) => el("button", {
    type: "button", "aria-pressed": String(String(get()) === String(k)), text: label,
    onclick: () => { set(k); box.querySelectorAll("button").forEach((b, i) => b.setAttribute("aria-pressed", String(Object.keys(options)[i] === String(k)))); },
  })));
}
function select(id, options, value, onchange) {
  const s = $(id);
  s.replaceChildren(...options.map(([v, label]) => el("option", { value: v, text: label })));
  s.value = String(value);
  s.onchange = () => onchange(s.value);
}
function tile(k, v, unit, d) {
  return el("div", { class: "tile" }, el("span", { class: "k", text: k }),
    el("span", { class: "v" }, v, unit ? el("small", { text: unit }) : null), d ? el("span", { class: "d", text: d }) : null);
}
function legend(boxId, items, hidden, onToggle) {
  $(boxId).replaceChildren(...items.map((it) => {
    const b = el("button", { type: "button", "aria-pressed": String(!(hidden && hidden.has(it.key))) },
      el("i", { class: it.dot ? "sw dot" : "sw", style: `background:${it.color}` }), it.label);
    if (onToggle) b.addEventListener("click", () => onToggle(it.key)); else b.disabled = true;
    return b;
  }));
}
function measure(svg, texts, size = 12) {
  const g = svg.append("g").attr("opacity", 0);
  const w = d3.max(texts, (t) => g.append("text").attr("font-size", size).text(t).node().getComputedTextLength()) || 0;
  g.remove();
  return w;
}

/* ------------------------------------------------------------------ line chart over waves */
function lineChart(box, { series, waves, unit, zeroLine = false }) {
  box.replaceChildren();
  const W = box.clientWidth || 600, H = Math.round(Math.max(260, Math.min(400, W * 0.42)));
  const svg = d3.select(box).append("svg").attr("width", "100%").attr("viewBox", `0 0 ${W} ${H}`).attr("height", H);
  const vis = series.filter((s) => s.points.some((p) => p.v != null));
  if (!vis.length) { svg.append("text").attr("x", 0).attr("y", 24).attr("fill", "var(--ink-3)").attr("font-size", 13).text("No answers for this selection yet."); return; }
  const times = waves.map((w) => new Date(w.slot_utc));
  const vals = vis.flatMap((s) => s.points.map((p) => p.v)).filter((v) => v != null);
  let [lo, hi] = d3.extent(zeroLine ? vals.concat([0]) : vals);
  const pad = Math.max(0.15, (hi - lo) * 0.12); lo -= pad; hi += pad;
  const y0 = d3.scaleLinear([lo, hi], [H - 30, 14]).nice(6);
  const yTicks = y0.ticks(6);
  const left = measure(svg, yTicks.map((t) => d3.format("~g")(t)), 11) + 14;
  const endLabels = vis.length <= 6;
  const right = endLabels ? Math.min(170, measure(svg, vis.map((s) => `${s.label} ${f2(s.points.at(-1)?.v ?? 0)}`), 11.5) + 16) : 12;
  let [t0, t1] = d3.extent(times);
  if (+t0 === +t1) { t0 = new Date(+t0 - 6 * 3600e3); t1 = new Date(+t1 + 6 * 3600e3); }
  const span = t1 - t0;
  const x = d3.scaleUtc([new Date(+t0 - span * 0.03), new Date(+t1 + span * 0.03)], [left, W - right]);
  const y = y0;
  const g = svg.append("g");
  g.selectAll("line.gy").data(yTicks).join("line").attr("x1", left).attr("x2", W - right).attr("y1", y).attr("y2", y)
    .attr("stroke", (t) => (zeroLine && t === 0 ? "var(--ink-3)" : "var(--line)")).attr("stroke-width", (t) => (zeroLine && t === 0 ? 1.2 : 1));
  g.selectAll("text.ty").data(yTicks).join("text").attr("x", left - 8).attr("y", y).attr("dy", "0.32em").attr("text-anchor", "end")
    .attr("font-size", 11).attr("fill", "var(--ink-3)").text((t) => d3.format("~g")(t));
  g.append("text").attr("x", left - 8).attr("y", 6).attr("text-anchor", "end").attr("font-size", 11).attr("fill", "var(--ink-3)").text(unit);
  const nTicks = Math.max(2, Math.min(7, Math.floor((W - left - right) / 110)));
  const xt = times.length <= nTicks ? times : x.ticks(nTicks);
  g.selectAll("text.tx").data(xt).join("text").attr("x", x).attr("y", H - 8).attr("text-anchor", "middle").attr("font-size", 11)
    .attr("fill", "var(--ink-3)").text((t) => (span > 3 * 864e5 ? etDay.format(t) : etFmt.format(t)));
  // design changes
  waves.forEach((w, i) => {
    if (i > 0 && w.design !== waves[i - 1].design) {
      const xm = (x(times[i]) + x(times[i - 1])) / 2;
      g.append("line").attr("x1", xm).attr("x2", xm).attr("y1", 10).attr("y2", H - 30).attr("stroke", "var(--line-2)").attr("stroke-dasharray", "4 4");
      g.append("text").attr("x", xm + 4).attr("y", 20).attr("font-size", 10.5).attr("fill", "var(--ink-3)").text(`design ${w.design.split("-").pop()}`);
    }
  });
  const line = d3.line().defined((p) => p.v != null).x((p) => x(p.t)).y((p) => y(p.v));
  for (const s of vis) {
    const pts = s.points.map((p, i) => ({ t: times[i], v: p.v }));
    g.append("path").datum(pts).attr("fill", "none").attr("stroke", s.color).attr("stroke-width", s.width || 2)
      .attr("stroke-dasharray", s.dash || null).attr("stroke-linejoin", "round").attr("stroke-linecap", "round").attr("d", line);
    g.selectAll(null).data(pts.filter((p) => p.v != null)).join("circle").attr("cx", (p) => x(p.t)).attr("cy", (p) => y(p.v))
      .attr("r", times.length > 40 ? 0 : 3.2).attr("fill", s.color).attr("stroke", "var(--surface)").attr("stroke-width", 1.2);
  }
  if (endLabels) {
    const labs = vis.map((s) => { const last = [...s.points].reverse().find((p) => p.v != null); return { s, v: last.v, y: y(last.v) }; })
      .sort((a, b) => a.y - b.y);
    for (let i = 1; i < labs.length; i++) if (labs[i].y - labs[i - 1].y < 14) labs[i].y = labs[i - 1].y + 14;
    g.selectAll("text.end").data(labs).join("text").attr("x", W - right + 8).attr("y", (d) => d.y).attr("dy", "0.32em")
      .attr("font-size", 11.5).attr("fill", "var(--ink-2)").text((d) => `${d.s.label} `)
      .append("tspan").attr("font-weight", 600).attr("fill", "var(--ink)").text((d) => f2(d.v));
  }
  // crosshair
  const rule = g.append("line").attr("y1", 10).attr("y2", H - 30).attr("stroke", "var(--ink-3)").attr("stroke-width", 1).attr("opacity", 0);
  svg.append("rect").attr("x", left).attr("y", 0).attr("width", W - left - right).attr("height", H - 24).attr("fill", "transparent")
    .on("mousemove", (ev) => {
      const [mx] = d3.pointer(ev);
      const i = d3.minIndex(times, (t) => Math.abs(x(t) - mx));
      rule.attr("x1", x(times[i])).attr("x2", x(times[i])).attr("opacity", 0.5);
      const lines = vis.map((s) => [s.color, s.label, s.points[i].v == null ? "—" : f2(s.points[i].v)])
        .sort((a, b) => (parseFloat(b[2]) || -99) - (parseFloat(a[2]) || -99));
      showTip(ev, waves[i].label, lines);
    })
    .on("mouseleave", () => { rule.attr("opacity", 0); hideTip(); });
}

/* ------------------------------------------------------------------ dot plot of effects (one wave) */
function dotPlot(box, rows, models) {
  box.replaceChildren();
  const W = box.clientWidth || 600, rowH = 30, top = 26, H = top + rowH * models.length + 6;
  const svg = d3.select(box).append("svg").attr("width", "100%").attr("viewBox", `0 0 ${W} ${H}`).attr("height", H);
  const left = measure(svg, models) + 16;
  const ext = (d3.max(rows, (r) => Math.abs(r.effect)) || 1) * 1.1;
  const x = d3.scaleLinear([-ext, ext], [left, W - 12]).nice();
  const y = (i) => top + rowH * i + rowH / 2;
  svg.selectAll("line.gx").data(x.ticks(6)).join("line").attr("x1", x).attr("x2", x).attr("y1", top - 6).attr("y2", H - 2)
    .attr("stroke", (t) => (t === 0 ? "var(--ink-3)" : "var(--line)")).attr("stroke-width", (t) => (t === 0 ? 1.3 : 1));
  svg.selectAll("text.tx").data(x.ticks(6)).join("text").attr("x", x).attr("y", top - 12).attr("text-anchor", "middle")
    .attr("font-size", 11).attr("fill", "var(--ink-3)").text((t) => (t > 0 ? "+" : "") + d3.format("~g")(t));
  models.forEach((m, i) => {
    svg.append("line").attr("x1", left).attr("x2", W - 12).attr("y1", y(i)).attr("y2", y(i)).attr("stroke", "var(--line)");
    svg.append("text").attr("x", 0).attr("y", y(i)).attr("dy", "0.33em").attr("font-size", 12)
      .attr("font-weight", m === "All models" ? 600 : 400).attr("fill", "var(--ink)").text(m);
  });
  const off = { general: -6, economy: -2, politics: 2, entertainment: 6 };
  svg.selectAll("circle").data(rows).join("circle").attr("cx", (r) => x(r.effect)).attr("cy", (r) => y(models.indexOf(r.model)) + off[r.arm])
    .attr("r", (r) => (r.model === "All models" ? 6.5 : 5)).attr("fill", (r) => ARM_COLOR[r.arm]).attr("stroke", "var(--surface)").attr("stroke-width", 1.5)
    .on("mousemove", (ev, r) => showTip(ev, `${r.model} · ${ARM_LABEL[r.arm]}`, [[null, "Effect", `${s2(r.effect)} pp`], [null, "With this news", f2(r.level)], [null, "No news", f2(r.base)]]))
    .on("mouseleave", hideTip);
}

/* ------------------------------------------------------------------ heat table */
function heatTable(table, rowsLabels, colKeys, colLabels, getV) {
  const cells = rowsLabels.map(([rk, rl]) => colKeys.map((ck) => getV(rk, ck)));
  const inner = cells.slice(0, -1).flatMap((r) => r.slice(0, -1)).filter((v) => v != null);
  const [lo, hi] = d3.extent(inner);
  const head = el("thead", {}, el("tr", {}, el("th", { text: "" }), ...colLabels.map((c) => el("th", { text: c }))));
  const body = el("tbody", {}, ...rowsLabels.map(([rk, rl], i) => el("tr", { class: i === rowsLabels.length - 1 ? "all" : "" },
    el("td", { text: rl }), ...cells[i].map((v, j) => {
      const td = el("td", { text: fmtQ(null, v) });
      const isInner = i < rowsLabels.length - 1 && j < colKeys.length - 1;
      if (v != null && isInner && hi > lo) td.style.background = `color-mix(in srgb, var(--heat) ${Math.round(5 + 42 * (v - lo) / (hi - lo))}%, transparent)`;
      return td;
    }))));
  table.replaceChildren(head, body);
}

/* ------------------------------------------------------------------ simple row table */
function rowTable(table, cols, rows, onRow) {
  table.replaceChildren(
    el("thead", {}, el("tr", {}, ...cols.map((c) => el("th", { text: c.label })))),
    el("tbody", {}, ...rows.map((r) => {
      const tr = el("tr", { class: onRow ? "link" : "" }, ...cols.map((c) => {
        const v = c.get ? c.get(r) : r[c.key];
        const out = v == null || (typeof v === "number" && Number.isNaN(v)) ? "—" : c.fmt ? c.fmt(v) : v;
        return el("td", { class: c.wrap ? "wrap" : "" }, out instanceof Node ? out : String(out));
      }));
      if (onRow) { tr.tabIndex = 0; tr.addEventListener("click", () => onRow(r)); tr.addEventListener("keydown", (e) => { if (e.key === "Enter") onRow(r); }); }
      return tr;
    })));
}

/* ================================================================== ALL WAVES */
function renderOverview() {
  const I = S.index, waves = I.waves, last = waves.at(-1), prev = waves.at(-2), wi = waves.length - 1;
  const totalTrials = d3.sum(waves, (w) => w.n_trials);
  $("ov-status").textContent = `Latest wave ${last.label} · ${waves.length} waves · ${int(totalTrials)} answers`;
  $("ov-lede").replaceChildren(
    "In the latest wave, with no news the seven models expect ", el("b", { text: `${f2(last.none_q4)}%` }),
    " inflation over the next 12 months. Economy news moves that by ", el("b", { text: `${s2(last.economy_q4)} pp` }),
    ", politics news by ", el("b", { text: `${s2(last.politics_q4)} pp` }), " and the entertainment placebo by ",
    el("b", { text: `${s2(last.entertainment_q4)} pp` }), ". Each model answers as four kinds of respondent, under five news conditions, three times per wave.");
  const delta = (a, b) => (b == null || a == null ? null : `${s2(a - b)} vs previous wave`);
  $("ov-tiles").replaceChildren(
    tile("1-year expectation, no news", f2(last.none_q4), "%", delta(last.none_q4, prev?.none_q4)),
    tile("Economy news effect", s2(last.economy_q4), "pp", delta(last.economy_q4, prev?.economy_q4)),
    tile("Politics news effect", s2(last.politics_q4), "pp", delta(last.politics_q4, prev?.politics_q4)),
    tile("Placebo effect", s2(last.entertainment_q4), "pp", "entertainment news"),
    tile("5-year expectation, no news", f2(last.none_q5), "%", delta(last.none_q5, prev?.none_q5)),
    tile("Answers fully valid", pct(last.share_ok), "", `latest wave · ${int(last.n_trials)} trials`),
  );
  seg("ov-q", Object.fromEntries(Object.entries(Q).map(([k, v]) => [k, `${v.short} · ${v.label.split(",")[0].replace("Mean of the ", "").replace("Uncertainty of the ", "")}`])),
    () => S.ov.q, (k) => { S.ov.q = k; drawOverviewCharts(); });
  seg("ov-split", { arm: "Lines by news arm", persona: "Lines by persona", model: "Lines by model" }, () => S.ov.split, (k) => {
    S.ov.split = k; S.ov.hidden.clear(); drawOverviewCharts();
  });
  select("ov-model", [[-1, "All models"], ...I.models.map((m, i) => [i, m])], S.ov.model, (v) => { S.ov.model = +v; drawOverviewCharts(); });
  select("ov-persona", [[-1, "All personas"], ...I.personas.map((p, i) => [i, PERSONA_LABEL[p]])], S.ov.persona, (v) => { S.ov.persona = +v; drawOverviewCharts(); });
  select("ov-arm", [[-1, "All arms"], ...I.arms.map((a, i) => [i, ARM_SHORT[a]])], S.ov.arm, (v) => { S.ov.arm = +v; drawOverviewCharts(); });
  rowTable($("ov-waves"), [
    { label: "Wave (New York time)", get: (w) => el("a", { href: `#wave/${w.id}`, text: w.label }) },
    { label: "Design", get: (w) => el("span", { class: "pill", text: w.design.split("-").pop() }) },
    { label: "Trials", key: "n_trials", fmt: int },
    { label: "Fully valid", key: "share_ok", fmt: pct },
    { label: "Flagged", get: (w) => (w.flag ? `${w.n_flagged} ${w.flag}` : "—") },
    { label: "1-yr, no news", key: "none_q4", fmt: f2 },
    { label: "Economy effect", key: "economy_q4", fmt: s2 },
    { label: "Politics effect", key: "politics_q4", fmt: s2 },
    { label: "Placebo effect", key: "entertainment_q4", fmt: s2 },
    { label: "Cost", key: "cost_usd", fmt: usd },
  ], [...waves].reverse(), (w) => { location.hash = `#wave/${w.id}`; });
  drawOverviewCharts();
}

function drawOverviewCharts() {
  const I = S.index, o = S.ov, waves = I.waves, q = o.q, W = waves.map((_, i) => i);
  $("ov-model").disabled = o.split === "model";
  $("ov-persona").disabled = o.split === "persona";
  $("ov-arm").disabled = o.split === "arm";
  let items;
  if (o.split === "arm") items = I.arms.map((a, ai) => ({ key: a, label: ARM_SHORT[a], color: ARM_COLOR[a], dash: a === "none" ? "5 4" : null,
    points: W.map((w) => ({ v: val(w, o.model, o.persona, ai, q) })) }));
  else if (o.split === "persona") items = I.personas.map((p, pi) => ({ key: p, label: PERSONA_LABEL[p], color: SERIES_COLORS[pi],
    points: W.map((w) => ({ v: val(w, o.model, pi, o.arm, q) })) }));
  else items = I.models.map((m, mi) => ({ key: m, label: m, color: SERIES_COLORS[mi % 8],
    points: W.map((w) => ({ v: val(w, mi, o.persona, o.arm, q) })) }));
  const toggle = (k) => { o.hidden.has(k) ? o.hidden.delete(k) : o.hidden.add(k); drawOverviewCharts(); };
  legend("ov-legend", items, o.hidden, toggle);
  lineChart($("ov-trend"), { series: items.filter((s) => !o.hidden.has(s.key)), waves, unit: Q[q].unit });

  // effect over time (always by arm), honoring model + persona filters
  const eff = I.arms.slice(1).map((a) => {
    const ai = I.arms.indexOf(a);
    return { key: a, label: ARM_SHORT[a], color: ARM_COLOR[a], points: W.map((w) => {
      const v = val(w, o.model, o.persona, ai, q), b = val(w, o.model, o.persona, 0, q);
      return { v: v == null || b == null ? null : v - b };
    }) };
  });
  legend("ov-eff-legend", eff.map((s) => ({ ...s, dot: false })), null, null);
  lineChart($("ov-effect"), { series: eff, waves, unit: "pp", zeroLine: true });

  // model x arm heat, averaged over waves
  const rowsL = I.models.map((m, i) => [i, m]).concat([[-1, "All models"]]);
  const cols = I.arms.map((_, i) => i).concat([-1]);
  heatTable($("ov-heat"), rowsL, cols, I.arms.map((a) => ARM_SHORT[a]).concat(["All arms"]),
    (m, a) => d3.mean(W, (w) => val(w, m, o.persona, a, q) ?? undefined) ?? null);
}

/* ================================================================== ONE WAVE */
async function loadWave(id) {
  if (!S.waveCache.has(id)) {
    const r = await fetch(`data/waves/${id}.json`, { cache: "no-cache" });
    if (!r.ok) throw new Error(`wave ${id}: ${r.status}`);
    S.waveCache.set(id, await r.json());
  }
  return S.waveCache.get(id);
}

async function renderWave(id) {
  const I = S.index, waves = I.waves;
  const wi = id ? waves.findIndex((w) => w.id === id) : waves.length - 1;
  const w = waves[wi < 0 ? waves.length - 1 : wi], idx = waves.indexOf(w);
  S.wv.id = w.id;
  select("wv-select", [...waves].reverse().map((x) => [x.id, x.label]), w.id, (v) => { location.hash = `#wave/${v}`; });
  $("wv-prev").disabled = idx === 0; $("wv-next").disabled = idx === waves.length - 1;
  $("wv-prev").onclick = () => { location.hash = `#wave/${waves[idx - 1].id}`; };
  $("wv-next").onclick = () => { location.hash = `#wave/${waves[idx + 1].id}`; };
  $("wv-title").textContent = w.label;
  const D = await loadWave(w.id);
  const man = D.manifest, sm = D.summary;
  const late = man.lateness_minutes != null ? `started ${Math.round(man.lateness_minutes)} min after the slot` : "";
  $("wv-meta").textContent = [`ID ${w.id}`, `design ${man.design_version}`, `${man.trials} trials per cell`, late,
    `news via ${[...new Set(Object.values(D.news_providers))].join(", ")}`].filter(Boolean).join(" · ");
  $("wv-lede").replaceChildren("With no news the models expect ", el("b", { text: `${f2(sm.none_q4)}%` }),
    " inflation over the next 12 months. Economy news moves that by ", el("b", { text: `${s2(sm.economy_q4)} pp` }),
    ", politics news by ", el("b", { text: `${s2(sm.politics_q4)} pp` }), ", general news by ", el("b", { text: `${s2(sm.general_q4)} pp` }),
    " and the entertainment placebo by ", el("b", { text: `${s2(sm.entertainment_q4)} pp` }), ".");
  const flagText = sm.flag === "rescaled" ? `${sm.n_flagged} had a list rescaled to 100` : sm.flag === "corrected" ? `${sm.n_flagged} needed a follow-up turn` : "";
  $("wv-tiles").replaceChildren(
    tile("Trials", int(sm.n_trials), "", "one conversation each"),
    tile("All five answers valid", pct(sm.share_ok), "", flagText),
    tile("1-year expectation, no news", f2(sm.none_q4), "%", ""),
    tile("Economy news effect", s2(sm.economy_q4), "pp", "Q4 vs no news"),
    tile("Placebo effect", s2(sm.entertainment_q4), "pp", "entertainment news"),
    tile("Cost of the wave", usd3(sm.cost_usd), "", "API calls incl. searches"),
  );
  const qs = Object.fromEntries(Object.entries(Q).map(([k, v]) => [k, v.short]));
  seg("wv-q-heat", qs, () => S.wv.qHeat, (k) => { S.wv.qHeat = k; drawWaveHeat(idx, D); });
  seg("wv-a-heat", Object.fromEntries([[-1, "All arms"], ...I.arms.map((a, i) => [i, ARM_SHORT[a]])]), () => S.wv.aHeat, (k) => { S.wv.aHeat = +k; drawWaveHeat(idx, D); });
  seg("wv-q-eff", { q4: "Q4", q5: "Q5", q1: "Q1", q2_mean: "Q2 mean", q3_mean: "Q3 mean" }, () => S.wv.qEff, (k) => { S.wv.qEff = k; drawWaveEffects(idx, D); });
  seg("wv-a-news", Object.fromEntries(Object.keys(D.news).map((a) => [a, ARM_SHORT[a]])), () => S.wv.aNews, (k) => { S.wv.aNews = k; drawWaveNews(D); });
  seg("wv-q-bins", { q2: "Q2 · next 12 months", q3: "Q3 · 4–5 years ahead" }, () => S.wv.qBins, (k) => { S.wv.qBins = k; drawWaveBins(D); });
  rowTable($("wv-anchor"), [
    { label: "Model", key: "model" }, { label: "No news", key: "none_q1", fmt: f2 }, { label: "Economy news", key: "econ_q1", fmt: f2 },
    { label: "Spread (SD)", key: "econ_sd", fmt: f2 }, { label: "Range", get: (r) => (r.econ_min == null ? "—" : `${f2(r.econ_min)}–${f2(r.econ_max)}`) },
  ], D.anchor);
  rowTable($("wv-cons"), [
    { label: "Model", key: "model" }, { label: "Q4 point", key: "q4", fmt: f2 }, { label: "Q2 mean", key: "q2_mean", fmt: f2 },
    { label: "Gap, 1 yr", key: "gap_1y", fmt: s2 }, { label: "Q5 point", key: "q5", fmt: f2 }, { label: "Q3 mean", key: "q3_mean", fmt: f2 },
    { label: "Gap, 5 yr", key: "gap_5y", fmt: s2 }, { label: "Chance of deflation, 1 yr", key: "p_deflation", fmt: (v) => `${d3.format(".1f")(v)}%` },
  ], D.consistency);
  $("wv-qual-note").textContent = (sm.flag === "corrected"
    ? "Design v1: an unusable answer got one follow-up turn. Flagged = trials that needed it."
    : "One call per trial. A probability list that misses 100 is rescaled to 100 (flagged); unreadable answers are invalid.")
    + " Trial spread = average SD of Q4 across the identical trials in each cell.";
  rowTable($("wv-qual"), [
    { label: "Model", key: "model" }, { label: "All 5 valid", key: "share_ok", fmt: pct }, { label: "Q2 valid", key: "valid_q2", fmt: pct },
    { label: "Q3 valid", key: "valid_q3", fmt: pct }, { label: "Flagged", key: "flagged", fmt: int }, { label: "Trial spread, Q4", key: "trial_sd_q4", fmt: f2 },
    { label: "Reasoning tokens", key: "reasoning_tokens", fmt: int }, { label: "Seconds", key: "latency_s", fmt: d3.format(".1f") },
    { label: "Cost", key: "cost_usd", fmt: usd3 }, { label: "Share of cost", key: "cost_share", fmt: pct },
  ], D.quality);
  drawWaveHeat(idx, D); drawWaveEffects(idx, D); drawWaveNews(D); drawWaveBins(D);
}

function drawWaveHeat(wi, D) {
  const I = S.index, q = S.wv.qHeat, a = S.wv.aHeat;
  $("wv-heat-note").textContent = `${Q[q].label} · ${a === -1 ? "all news arms" : ARM_LABEL[I.arms[a]]} · mean over trials, ${Q[q].unit === "pp" ? "percentage points" : "percent"}. Shading runs from the lowest to the highest cell.`;
  const models = D.models.map((m) => [I.models.indexOf(m), m]).concat([[-1, "All models"]]);
  heatTable($("wv-heat"), models, I.personas.map((_, i) => i).concat([-1]), I.personas.map((p) => PERSONA_LABEL[p]).concat(["All personas"]),
    (m, p) => val(wi, m, p, a, q));
}
function drawWaveEffects(wi, D) {
  const I = S.index, q = S.wv.qEff;
  const models = ["All models", ...D.models], rows = [];
  for (const m of models) {
    const mi = m === "All models" ? -1 : I.models.indexOf(m), base = val(wi, mi, -1, 0, q);
    I.arms.slice(1).forEach((a) => { const v = val(wi, mi, -1, I.arms.indexOf(a), q); if (v != null && base != null) rows.push({ model: m, arm: a, effect: v - base, level: v, base }); });
  }
  legend("wv-eff-legend", I.arms.slice(1).map((a) => ({ key: a, label: ARM_LABEL[a], color: ARM_COLOR[a], dot: true })), null, null);
  dotPlot($("wv-eff"), rows, models);
}
function drawWaveNews(D) {
  const a = S.wv.aNews, items = D.news[a] || [];
  $("wv-news-note").textContent = `${items.length} articles shown, identically, to every model in the ${ARM_SHORT[a].toLowerCase()} arm. Source: ${D.news_providers[a] || "—"}.`;
  rowTable($("wv-news"), [
    { label: "#", get: (r) => items.indexOf(r) + 1 },
    { label: "Article", wrap: true, get: (r) => (r.url ? el("a", { href: r.url, target: "_blank", rel: "noopener", text: r.title }) : r.title) },
    { label: "Source", key: "source" },
  ], items);
}
function drawWaveBins(D) {
  const box = $("wv-bins"), q = S.wv.qBins, rows = D.bins.filter((b) => b.q === q);
  const ymax = d3.max(rows, (r) => d3.max(r.p)) || 1;
  box.replaceChildren(...rows.map((r) => el("figure", {}, el("figcaption", { text: r.model }))));
  [...box.children].forEach((fig, k) => {
    const r = rows[k], W = Math.max(180, fig.clientWidth || 220), H = 118, pb = 18;
    const x = d3.scaleBand(d3.range(10), [0, W]).padding(0.18), y = d3.scaleLinear([0, ymax], [H - pb, 6]);
    const svg = d3.select(fig).append("svg").attr("width", "100%").attr("viewBox", `0 0 ${W} ${H}`).attr("height", H);
    svg.append("line").attr("x1", 0).attr("x2", W).attr("y1", H - pb).attr("y2", H - pb).attr("stroke", "var(--line-2)");
    const zx = (x(4) + x.bandwidth() + x(5)) / 2;
    svg.append("line").attr("x1", zx).attr("x2", zx).attr("y1", 2).attr("y2", H - pb).attr("stroke", "var(--ink-3)").attr("stroke-dasharray", "3 3");
    svg.selectAll("rect").data(r.p.map((v, i) => ({ v: v || 0, i }))).join("rect").attr("x", (d) => x(d.i)).attr("width", x.bandwidth())
      .attr("y", (d) => y(d.v)).attr("height", (d) => Math.max(0, y(0) - y(d.v))).attr("rx", 2)
      .attr("fill", (d) => (d.i < 5 ? "var(--c-none)" : "var(--c1)")).attr("opacity", (d) => (d.i < 5 ? 0.55 : 1))
      .on("mousemove", (ev, d) => showTip(ev, r.model, [[null, D.bin_labels[d.i], `${d3.format(".1f")(d.v)}%`]])).on("mouseleave", hideTip);
    svg.append("text").attr("x", 0).attr("y", H - 4).attr("font-size", 10.5).attr("fill", "var(--ink-3)").text("deflation");
    svg.append("text").attr("x", W).attr("y", H - 4).attr("text-anchor", "end").attr("font-size", 10.5).attr("fill", "var(--ink-3)").text("inflation");
  });
}

/* ================================================================== METHOD */
function renderMethod() {
  const d = S.index.design;
  $("m-models").replaceChildren(el("h3", { text: `${d.models.length} models (OpenRouter IDs)` }),
    el("ul", { class: "models" }, ...d.models.map((m) => el("li", {}, el("span", { class: "pill", text: m })))),
    el("p", { text: `${d.trials} independent trials per model × persona × news arm in every wave.` }));
  $("m-personas").replaceChildren(el("h3", { text: "Personas (added to the system prompt)" }),
    el("dl", { class: "kv" }, ...Object.entries(d.personas).flatMap(([k, v]) => [el("dt", { text: PERSONA_LABEL[k] || k }), el("dd", { text: v || "No role sentence." })])));
  $("m-arms").replaceChildren(el("dl", { class: "kv" }, ...Object.entries(d.arms).flatMap(([k, v]) => [el("dt", { text: ARM_LABEL[k] || k }),
    el("dd", { text: v ? `Search: “${v.replace("{date}", "<wave date>")}”` : "No news at all." })])));
  $("m-system").textContent = d.system_prompt;
  $("m-answer").textContent = d.answer_instruction;
  $("m-questions").replaceChildren(...Object.entries(d.questions).map(([k, v]) => el("div", { class: "qblock" }, el("span", { class: "qid", text: k }), el("pre", { class: "qtext", text: v }))));
  const R = S.index.repo;
  $("m-links").replaceChildren(
    el("a", { href: R, target: "_blank", rel: "noopener", text: "Repository ↗" }),
    el("a", { href: `${R}/tree/main/data/waves`, target: "_blank", rel: "noopener", text: "Wave folders ↗" }),
    el("a", { href: `${R}/tree/main/data/panel`, target: "_blank", rel: "noopener", text: "Monthly panel CSVs ↗" }),
    el("a", { href: `${R}/blob/main/data/waves_index.csv`, target: "_blank", rel: "noopener", text: "Wave index ↗" }),
    el("a", { href: `${R}/blob/main/config.yaml`, target: "_blank", rel: "noopener", text: "Study configuration ↗" }));
}

/* ================================================================== routing + boot */
async function route() {
  const h = location.hash.replace(/^#/, "");
  const view = h.startsWith("wave") ? "wave" : h === "method" ? "method" : "overview";
  document.querySelectorAll(".view").forEach((v) => { v.hidden = v.id !== `view-${view}`; });
  document.querySelectorAll(".nav a[data-view]").forEach((a) => (a.dataset.view === view ? a.setAttribute("aria-current", "page") : a.removeAttribute("aria-current")));
  hideTip();
  try {
    if (view === "overview") renderOverview();
    else if (view === "wave") await renderWave(h.split("/")[1]);
    else renderMethod();
  } catch (e) { console.error(e); $("load-error").hidden = false; }
}

async function boot() {
  try {
    const res = await fetch("data/index.json", { cache: "no-cache" });
    S.index = await res.json();
    const parts = await Promise.all(S.index.series_files.map((f) => fetch(`data/${f}`, { cache: "no-cache" }).then((r) => r.json())));
    for (const p of parts) for (const row of p.rows) S.rows.set(key(row[0], row[1], row[2], row[3]), row);
    $("loading").hidden = true;
    $("repo-link").href = S.index.repo;
    $("foot-updated").textContent = `Updated ${new Date(S.index.generated_utc).toLocaleString("en-US", { timeZone: "America/New_York", dateStyle: "medium", timeStyle: "short" })} ET`;
    if (!S.index.waves.length) { $("loading").hidden = false; $("loading").textContent = "No waves yet."; return; }
    window.addEventListener("hashchange", route);
    let t; window.addEventListener("resize", () => { clearTimeout(t); t = setTimeout(route, 150); });
    route();
  } catch (e) { console.error(e); $("loading").hidden = true; $("load-error").hidden = false; }
}
boot();
