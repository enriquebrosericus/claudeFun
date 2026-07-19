// The Ballpark Almanac — multi-section almanac over the Flask API (server.py).

// Nautical chart palette: navy ink on buff, sea-green accent, signal-flag red.
const C = { ink: "#16283f", muted: "#4c5b64", field: "#0f6b62", clay: "#b23a2e",
            rule: "rgba(22,40,63,0.12)", paper: "#e9e7d8" };
// Categorical palette for multi-team charts — nautical, no purple.
const SERIES = ["#0f6b62", "#b23a2e", "#16283f", "#4f6d8a", "#b0862f", "#6b7f57"];

Chart.defaults.font.family = "'IBM Plex Mono', monospace";
Chart.defaults.color = C.muted;

const $ = (id) => document.getElementById(id);
const params = new URLSearchParams(location.search);
const state = {
  season: params.get("season") || "2026",
  team: params.get("team") || "SEA",
  division: params.get("division") || "AL West",
  view: params.get("view") || "teams",
};
let charts = [];
let opener = null;
const track = (c) => (charts.push(c), c);
const clearCharts = () => { charts.forEach((c) => c.destroy()); charts = []; };

async function getJSON(path) {
  const r = await fetch(path);
  if (!r.ok) throw new Error(`${path} → ${r.status}`);
  return r.json();
}

const pct = (v) => (v == null || v === "" ? "—" : Number(v).toFixed(3).replace(/^0/, "").replace(/^-0/, "-"));
const dp = (v, n) => (v == null || v === "" ? "—" : Number(v).toFixed(n));
const mmdd = (d) => d.slice(5);
const monDay = (d) => new Date(d + "T00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" });

// ── Chart options ────────────────────────────────────────────────────
const baseOpts = (extra = {}) => {
  const base = {
    responsive: true, maintainAspectRatio: false,
    interaction: { mode: "index", intersect: false },
    plugins: {
      legend: { labels: { color: C.ink, boxWidth: 12, font: { size: 11 } } },
      tooltip: { backgroundColor: C.ink, titleColor: C.paper, bodyColor: C.paper, cornerRadius: 0, padding: 10 },
    },
    scales: {
      x: { grid: { color: C.rule }, ticks: { color: C.muted, maxRotation: 0, autoSkip: true, maxTicksLimit: window.innerWidth < 560 ? 5 : 8 } },
      y: { grid: { color: C.rule }, ticks: { color: C.muted } },
    },
  };
  const ex = { ...extra };
  if (ex.scales) {                 // shallow-merge x/y so callers override just one axis
    base.scales.x = { ...base.scales.x, ...ex.scales.x };
    base.scales.y = { ...base.scales.y, ...ex.scales.y };
    delete ex.scales;
  }
  if (ex.plugins) { base.plugins = { ...base.plugins, ...ex.plugins }; delete ex.plugins; }
  return { ...base, ...ex };
};
const line = (el, labels, ds, extra) => track(new Chart(el, { type: "line", data: { labels, datasets: ds }, options: baseOpts(extra) }));
const bars = (el, labels, ds, extra) => track(new Chart(el, { type: "bar", data: { labels, datasets: ds }, options: baseOpts(extra) }));
const series = (label, data, color, o = {}) => ({ label, data, borderColor: color, backgroundColor: color, borderWidth: 2, pointRadius: 0, tension: 0.2, spanGaps: true, ...o });

// ── Markup helpers ───────────────────────────────────────────────────
const panelHTML = (eyebrow, title, inner, o = {}) => {
  const drill = o.panel ? ` data-panel="${o.panel}" role="button" tabindex="0"` : "";
  const exp = o.panel ? '<span class="expand">Expand ↗</span>' : "";
  return `<figure class="panel${o.feature ? " panel--feature" : ""}"${drill}>
    <figcaption><span class="eyebrow">${eyebrow}</span> ${title}${exp}</figcaption>${inner}</figure>`;
};
const canvasHTML = (id) => `<div class="canvas-wrap"><canvas id="${id}"></canvas></div>`;
const tableHTML = (head, rows, o = {}) => `<div class="table-wrap"><table class="ledger-table">
    <thead><tr>${head.map((h) => `<th>${h}</th>`).join("")}</tr></thead>
    <tbody>${rows.map((r, i) => `<tr data-i="${i}"${o.rowlink ? ' class="rowlink" tabindex="0"' : ""}>${r.map((c) => `<td>${c == null ? "—" : c}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;

// ── Drill-down modal ─────────────────────────────────────────────────
let modalChart = null;
function openModal(title, drawChart, head, rows, from) {
  opener = from || null;
  $("modalTitle").textContent = title;
  $("modal").classList.add("open");
  $("modal").setAttribute("aria-hidden", "false");
  modalChart?.destroy();
  modalChart = drawChart ? drawChart($("modalCanvas")) : null;
  $("modalCanvas").parentElement.style.display = drawChart ? "" : "none";
  $("modalTable").innerHTML = `<thead><tr>${head.map((h) => `<th>${h}</th>`).join("")}</tr></thead>
    <tbody>${rows.map((r) => `<tr>${r.map((c) => `<td>${c == null ? "—" : c}</td>`).join("")}</tr>`).join("")}</tbody>`;
  $("modalClose").focus();
}
function closeModal() {
  $("modal").classList.remove("open");
  $("modal").setAttribute("aria-hidden", "true");
  modalChart?.destroy(); modalChart = null;
  opener?.focus();
}

// ── VIEWS ────────────────────────────────────────────────────────────
const views = {};

// Teams -----------------------------------------------------------------
const TEAM_PANELS = {
  record: { title: "Wins & losses", eyebrow: "Ledger", feature: true,
    draw: (el, t) => line(el, t.map((r) => mmdd(r.date)),
      [series("Wins", t.map((r) => r.wins), C.field), series("Losses", t.map((r) => r.losses), C.clay)]),
    cols: [["Date", (r) => r.date], ["W", (r) => r.wins], ["L", (r) => r.losses]] },
  runDiff: { title: "Run differential", eyebrow: "Daily",
    draw: (el, t) => bars(el, t.map((r) => mmdd(r.date)),
      [series("Run diff", t.map((r) => r.run_diff_day), C.field, { backgroundColor: t.map((r) => (r.run_diff_day >= 0 ? C.field : C.clay)) })],
      { plugins: { legend: { display: false } } }),
    cols: [["Date", (r) => r.date], ["Day ±", (r) => r.run_diff_day], ["Cum ±", (r) => r.run_diff_cum]] },
  winPct: { title: "Winning percentage", eyebrow: "Pace",
    draw: (el, t) => line(el, t.map((r) => mmdd(r.date)),
      [series("Win %", t.map((r) => r.win_pct), C.ink), series(".500", t.map(() => 0.5), C.muted, { borderDash: [4, 4], borderWidth: 1 })],
      { scales: { y: { suggestedMin: 0, suggestedMax: 1 } } }),
    cols: [["Date", (r) => r.date], ["Win %", (r) => pct(r.win_pct)]] },
  gb: { title: "Games behind", eyebrow: "Division",
    draw: (el, t) => line(el, t.map((r) => mmdd(r.date)), [series("Games behind", t.map((r) => r.games_behind), C.clay)],
      { plugins: { legend: { display: false } }, scales: { y: { reverse: true } } }),
    cols: [["Date", (r) => r.date], ["GB", (r) => r.games_behind ?? "—"]] },
};
const LEDGER = [
  ["W", (s) => s.wins], ["L", (s) => s.losses], ["PCT", (s) => pct(s.win_pct)], ["GB", (s) => s.games_behind ?? "—"],
  ["STREAK", (s) => (s.streak != null ? (s.streak > 0 ? `W${s.streak}` : `L${-s.streak}`) : "—"), (s) => s.streak < 0],
  ["LAST 10", (s) => (s.last10_wins != null ? `${s.last10_wins}–${10 - s.last10_wins}` : "—")],
  ["RS", (s) => s.runs_scored], ["RA", (s) => s.runs_allowed],
];
views.teams = async () => {
  const [summary, t] = await Promise.all([
    getJSON(`/api/teams/summary?season=${state.season}&team=${state.team}`),
    getJSON(`/api/teams/trends?season=${state.season}&team=${state.team}`),
  ]);
  const ledger = `<section class="standing">${LEDGER.map(([l, g, neg]) =>
    `<div class="stat"><div class="stat-label">${l}</div><div class="stat-value${neg && neg(summary) ? " neg" : ""}">${g(summary) ?? "—"}</div></div>`).join("")}</section>`;
  $("view").innerHTML = ledger + `<section class="dispatches">
    ${panelHTML("Ledger", "Wins &amp; losses", canvasHTML("c_record"), { feature: true, panel: "record" })}
    <div class="panel-row">
      ${panelHTML("Daily", "Run differential", canvasHTML("c_runDiff"), { panel: "runDiff" })}
      ${panelHTML("Pace", "Winning percentage", canvasHTML("c_winPct"), { panel: "winPct" })}
      ${panelHTML("Division", "Games behind", canvasHTML("c_gb"), { panel: "gb" })}
    </div></section>`;
  for (const k of Object.keys(TEAM_PANELS)) TEAM_PANELS[k].draw($("c_" + k), t);
  wirePanels((key, from) => {
    const p = TEAM_PANELS[key];
    openModal(`${p.title} — ${state.team} ${state.season}`, (el) => p.draw(el, t),
      p.cols.map((c) => c[0]), [...t].reverse().map((r) => p.cols.map((c) => c[1](r))), from);
  });
};

// Players ---------------------------------------------------------------
views.players = async () => {
  const [bat, pit] = await Promise.all([
    getJSON(`/api/teams/batting_leaders?season=${state.season}&team=${state.team}`),
    getJSON(`/api/teams/pitching_leaders?season=${state.season}&team=${state.team}`),
  ]);
  const strCol = (label, key) => ({ label, get: (p) => p[key], val: (p) => p[key] || "" });
  const numCol = (label, key, fmt) => ({ label, num: true, get: (p) => fmt(p[key]), val: (p) => (p[key] == null || p[key] === "" ? null : Number(p[key])) });
  const batCols = [strCol("Batter", "player"), strCol("POS", "position"),
    numCol("AVG", "avg", pct), numCol("OBP", "obp", pct), numCol("SLG", "slg", pct), numCol("OPS", "ops", pct),
    numCol("HR", "home_runs", (v) => v), numCol("RBI", "rbi", (v) => v), numCol("SB", "stolen_bases", (v) => v), numCol("G", "games_played", (v) => v)];
  const pitCols = [strCol("Pitcher", "player"), strCol("POS", "position"),
    numCol("ERA", "era", (v) => dp(v, 2)), numCol("WHIP", "whip", (v) => dp(v, 2)), numCol("FIP", "fip", (v) => dp(v, 2)),
    numCol("W", "wins", (v) => v), numCol("L", "losses", (v) => v), numCol("SV", "saves", (v) => v), numCol("K", "strikeouts", (v) => v), numCol("IP", "innings_pitched", (v) => v)];
  $("view").innerHTML = `<section class="dispatches">
    ${panelHTML("Lineup", `Batting &mdash; ${state.team}`, `<div id="battbl"></div>`, { feature: true })}
    ${panelHTML("Staff", `Pitching &mdash; ${state.team}`, `<div id="pittbl"></div>`, { feature: true })}
  </section>`;
  sortableTable($("battbl"), batCols, bat, async (p, from) => {
    const tr = await getJSON(`/api/players/batter_trend?season=${state.season}&player_id=${p.player_id}`);
    openModal(`${p.player} — batting trend`,
      (el) => line(el, tr.map((r) => mmdd(r.date)), [series("OPS", tr.map((r) => r.ops), C.field), series("AVG", tr.map((r) => r.avg), C.clay)]),
      ["Date", "AVG", "OBP", "SLG", "OPS", "HR", "RBI"],
      [...tr].reverse().map((r) => [r.date, pct(r.avg), pct(r.obp), pct(r.slg), pct(r.ops), r.home_runs, r.rbi]), from);
  });
  sortableTable($("pittbl"), pitCols, pit, async (p, from) => {
    const tr = await getJSON(`/api/players/pitcher_trend?season=${state.season}&player_id=${p.player_id}`);
    openModal(`${p.player} — pitching trend`,
      (el) => line(el, tr.map((r) => mmdd(r.date)), [series("ERA", tr.map((r) => r.era), C.clay), series("WHIP", tr.map((r) => r.whip), C.field)]),
      ["Date", "ERA", "WHIP", "FIP", "K", "IP"],
      [...tr].reverse().map((r) => [r.date, dp(r.era, 2), dp(r.whip, 2), dp(r.fip, 2), r.strikeouts, r.innings_pitched]), from);
  });
};

// Division race ---------------------------------------------------------
views.divisions = async () => {
  const divs = await getJSON("/api/divisions/list");
  if (!divs.includes(state.division)) state.division = divs[0];
  const d = await getJSON(`/api/divisions/all?season=${state.season}&division=${encodeURIComponent(state.division)}`);
  const teams = d.standings.map((s) => s.team);
  const labels = d.dates.map(mmdd);
  const RACES = {
    gbrace: { key: "gb", title: "Games behind", fmt: (v) => (v == null ? "—" : v),
      draw: (el) => line(el, labels, teams.map((t, i) => series(t, d.gb[t], SERIES[i % SERIES.length])), { scales: { y: { reverse: true } } }) },
    wprace: { key: "wpct", title: "Winning percentage", fmt: (v) => pct(v),
      draw: (el) => line(el, labels, teams.map((t, i) => series(t, d.wpct[t], SERIES[i % SERIES.length])), { scales: { y: { suggestedMin: 0.2, suggestedMax: 0.8 } } }) },
  };
  const picker = `<div class="subpick"><label>Division
    <select id="divsel">${divs.map((x) => `<option ${x === state.division ? "selected" : ""}>${x}</option>`).join("")}</select></label></div>`;
  const standHead = ["Team", "W", "L", "GB", "PCT"];
  const standRows = d.standings.map((s) => [s.team, s.wins, s.losses, s.games_behind ?? "—", pct(s.win_pct)]);
  $("view").innerHTML = picker + `<section class="dispatches">
    ${panelHTML("Standings", `${state.division} &mdash; ${state.season}`, tableHTML(standHead, standRows), { feature: true })}
    <div class="panel-row panel-row--2">
      ${panelHTML("Race", "Games behind", canvasHTML("c_gbrace"), { panel: "gbrace" })}
      ${panelHTML("Pace", "Winning percentage", canvasHTML("c_wprace"), { panel: "wprace" })}
    </div></section>`;
  for (const k of Object.keys(RACES)) RACES[k].draw($("c_" + k));
  $("divsel").onchange = (e) => { state.division = e.target.value; syncURL(); render(); };
  wirePanels((key, from) => {
    const r = RACES[key];
    openModal(`${r.title} — ${state.division} ${state.season}`, (el) => r.draw(el),
      ["Date", ...teams],
      d.dates.map((dt, i) => [dt, ...teams.map((t) => r.fmt(d[r.key][t][i]))]), from);
  });
};

// Game recap ------------------------------------------------------------
views.recap = async () => {
  const games = await getJSON(`/api/recap/games?season=${state.season}&team=${state.team}`);
  if (!games.length) { $("view").innerHTML = `<p class="empty">No final games recorded for ${state.team} in ${state.season}.</p>`; return; }
  const picker = `<div class="subpick"><label>Game
    <select id="gamesel">${games.map((g) => `<option value="${g.gamepk}">${g.label}</option>`).join("")}</select></label></div>`;
  $("view").innerHTML = picker + `<div id="boxscore"></div>`;
  const draw = async (pk) => {
    const g = await getJSON(`/api/recap/game?gamepk=${pk}`);
    const ls = g.linescore;
    const lsHead = ["", ...ls.innings, "R", "H", "E"];
    const lsRows = ls.rows.map((r) => [r.team, ...r.cells, r.R, r.H, r.E]);
    const batHead = ["Batter", "AB", "R", "H", "2B", "3B", "HR", "RBI", "BB", "SO", "SB"];
    const batRows = (side) => g.batting[side].map((b) => [b.player, b.ab, b.r, b.h, b.doubles, b.triples, b.hr, b.rbi, b.bb, b.so, b.sb]);
    const pitHead = ["Pitcher", "IP", "H", "R", "ER", "BB", "SO", "HR", "ERA"];
    const pitRows = (side) => g.pitching[side].map((p) => [p.player + (p.note ? ` (${p.note})` : ""), p.innings_pitched ?? p.ip, p.h, p.r, p.er, p.bb, p.so, p.hr, dp(p.era, 2)]);
    $("boxscore").innerHTML = `<section class="dispatches">
      ${panelHTML("Linescore", `${g.game.away_team} @ ${g.game.home_team}`, tableHTML(lsHead, lsRows), { feature: true })}
      ${panelHTML("Batting", g.game.away_team, tableHTML(batHead, batRows("away")))}
      ${panelHTML("Batting", g.game.home_team, tableHTML(batHead, batRows("home")))}
      ${panelHTML("Pitching", g.game.away_team, tableHTML(pitHead, pitRows("away")))}
      ${panelHTML("Pitching", g.game.home_team, tableHTML(pitHead, pitRows("home")))}
    </section>`;
  };
  $("gamesel").onchange = (e) => draw(e.target.value);
  draw(games[0].gamepk);
};

// Challenges (ABS) ------------------------------------------------------
views.challenges = async () => {
  const [sum, trend] = await Promise.all([
    getJSON(`/api/challenges/summary?season=${state.season}&team=${state.team}`),
    getJSON(`/api/challenges/trend?season=${state.season}&team=${state.team}`),
  ]);
  const cLedger = [["CHALLENGES", sum.total ?? 0], ["OVERTURNED", sum.overturned ?? 0],
    ["OVERTURN %", sum.overturn_rate != null ? sum.overturn_rate + "%" : "—"],
    ["BALL", sum.ball_challenges ?? 0], ["STRIKE", sum.strike_challenges ?? 0]];
  const ledger = `<section class="standing">${cLedger.map(([l, v]) =>
    `<div class="stat"><div class="stat-label">${l}</div><div class="stat-value">${v}</div></div>`).join("")}</section>`;
  $("view").innerHTML = ledger + `<section class="dispatches">
    ${panelHTML("Trend", "Challenges over time", canvasHTML("c_chtrend"), { feature: true })}
  </section>`;
  bars($("c_chtrend"), trend.map((r) => monDay(r.date)),
    [series("Challenges", trend.map((r) => r.total), C.muted, { type: "bar" }),
     series("Overturned", trend.map((r) => r.overturned), C.field, { type: "bar" })]);
};

// ── Wiring ───────────────────────────────────────────────────────────
function wirePanels(onOpen) {
  $("view").querySelectorAll("[data-panel]").forEach((card) => {
    const open = () => onOpen(card.dataset.panel, card);
    card.addEventListener("click", open);
    card.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(); } });
  });
}
// Sortable ledger table. columns: {label, get(row), val(row), num?}. Clicking a
// header sorts by that column (numbers desc-first, text asc-first); re-click flips.
function sortableTable(mount, columns, data, onRow) {
  let si = null, dir = 1;
  const cmp = (c) => (a, b) => {
    const va = c.val(a), vb = c.val(b);
    if (va == null) return 1;            // nulls always sink
    if (vb == null) return -1;
    return (typeof va === "string" ? va.localeCompare(vb) : va - vb) * dir;
  };
  function draw() {
    const head = columns.map((c, i) =>
      `<th class="sortable${si === i ? " sorted" : ""}" data-c="${i}" tabindex="0" role="button">${c.label}${si === i ? (dir > 0 ? " ↑" : " ↓") : ""}</th>`).join("");
    const rows = data.map((r, i) =>
      `<tr data-i="${i}"${onRow ? ' class="rowlink" tabindex="0"' : ""}>${columns.map((c) => `<td>${c.get(r) ?? "—"}</td>`).join("")}</tr>`).join("");
    mount.innerHTML = `<div class="table-wrap"><table class="ledger-table"><thead><tr>${head}</tr></thead><tbody>${rows}</tbody></table></div>`;
    mount.querySelectorAll("th.sortable").forEach((th) => {
      const sort = () => { const c = +th.dataset.c; if (si === c) dir = -dir; else { si = c; dir = columns[c].num ? -1 : 1; } data.sort(cmp(columns[c])); draw(); };
      th.onclick = sort;
      th.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); sort(); } };
    });
    if (onRow) mount.querySelectorAll("tr.rowlink").forEach((tr) => {
      const open = () => onRow(data[+tr.dataset.i], tr);
      tr.onclick = open;
      tr.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(); } };
    });
  }
  draw();
}

const NAV = [["teams", "The Club"], ["players", "Players"], ["divisions", "Division race"], ["recap", "Game recap"], ["challenges", "Challenges"]];
const syncURL = () => history.replaceState(null, "", `?view=${state.view}&season=${state.season}&team=${state.team}&division=${encodeURIComponent(state.division)}`);

function renderNav() {
  $("nav").innerHTML = NAV.map(([k, label]) =>
    `<button type="button" class="navlink${k === state.view ? " on" : ""}" data-view="${k}" ${k === state.view ? 'aria-current="page"' : ""}>${label}</button>`).join("");
  $("nav").querySelectorAll(".navlink").forEach((b) =>
    (b.onclick = () => { state.view = b.dataset.view; syncURL(); renderNav(); render(); }));
}

async function render() {
  clearCharts();
  const label = state.view === "divisions" ? state.division : "Seattle Mariners";
  $("edition").textContent = `${state.season} Season · ${label}`;
  $("view").innerHTML = `<p class="empty">Loading…</p>`;
  try { await views[state.view](); }
  catch (e) { $("view").innerHTML = `<pre class="err">${e}</pre>`; }
}

async function init() {
  const seasons = await getJSON("/api/seasons");
  $("season").innerHTML = seasons.map((s) => `<option ${s == state.season ? "selected" : ""}>${s}</option>`).join("");
  $("season").onchange = (e) => { state.season = e.target.value; syncURL(); render(); };
  $("controls").addEventListener("submit", (e) => e.preventDefault());
  $("modalClose").onclick = closeModal;
  $("modal").addEventListener("click", (e) => { if (e.target.id === "modal") closeModal(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && $("modal").classList.contains("open")) closeModal(); });
  renderNav();
  render();
}

init().catch((e) => { document.body.insertAdjacentHTML("beforeend", `<pre class="err">${e}</pre>`); });
