(() => {
  const SIZE = 4;
  const STORAGE_PREFIX = "bingo:";

  // ── Date & seeding ────────────────────────────────────────────
  // Uses local date so the card resets at the player's midnight.
  const todayKey = () => {
    const d = new Date();
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, "0");
    const day = String(d.getDate()).padStart(2, "0");
    return `${y}-${m}-${day}`;
  };

  // Mulberry32 — small deterministic PRNG so a given seed yields the
  // same shuffle every time the page loads on the same day.
  const mulberry32 = (seed) => () => {
    let t = (seed += 0x6D2B79F5);
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };

  const hashString = (s) => {
    let h = 2166136261 >>> 0;
    for (let i = 0; i < s.length; i++) {
      h ^= s.charCodeAt(i);
      h = Math.imul(h, 16777619);
    }
    return h >>> 0;
  };

  const shuffle = (arr, rand) => {
    const a = arr.slice();
    for (let i = a.length - 1; i > 0; i--) {
      const j = Math.floor(rand() * (i + 1));
      [a[i], a[j]] = [a[j], a[i]];
    }
    return a;
  };

  // ── Card generation ───────────────────────────────────────────
  const buildCard = (seedKey) => {
    const phrases = window.BINGO_PHRASES || [];
    const needed = SIZE * SIZE;
    if (phrases.length < needed) {
      console.warn(`Need at least ${needed} phrases, got ${phrases.length}`);
    }
    const rand = mulberry32(hashString(seedKey));
    const picked = shuffle(phrases, rand).slice(0, needed);
    return Array.from({ length: needed }, (_, i) => ({ text: picked[i] || "—" }));
  };

  // ── Persistence ───────────────────────────────────────────────
  const stateKey = (seedKey) => `${STORAGE_PREFIX}${seedKey}`;

  const loadState = (seedKey) => {
    try {
      const raw = localStorage.getItem(stateKey(seedKey));
      if (!raw) return null;
      return JSON.parse(raw);
    } catch { return null; }
  };

  const saveState = (seedKey, state) => {
    try { localStorage.setItem(stateKey(seedKey), JSON.stringify(state)); }
    catch { /* quota or disabled — silently degrade */ }
  };

  // ── Win detection ─────────────────────────────────────────────
  // Returns array of winning lines (each line is array of cell indices).
  const findBingos = (marked) => {
    const lines = [];
    // rows + cols
    for (let i = 0; i < SIZE; i++) {
      lines.push(Array.from({ length: SIZE }, (_, j) => i * SIZE + j));
      lines.push(Array.from({ length: SIZE }, (_, j) => j * SIZE + i));
    }
    // diagonals
    lines.push(Array.from({ length: SIZE }, (_, k) => k * SIZE + k));
    lines.push(Array.from({ length: SIZE }, (_, k) => k * SIZE + (SIZE - 1 - k)));
    return lines.filter((line) => line.every((idx) => marked[idx]));
  };

  // ── State ─────────────────────────────────────────────────────
  let seedKey = todayKey();
  let cells = [];
  let marked = new Array(SIZE * SIZE).fill(false);
  let lastBingoCount = 0;

  const init = () => {
    const stored = loadState(seedKey);
    if (stored && Array.isArray(stored.cells) && stored.cells.length === SIZE * SIZE) {
      cells = stored.cells;
      marked = stored.marked || new Array(SIZE * SIZE).fill(false);
    } else {
      cells = buildCard(seedKey);
      marked = new Array(SIZE * SIZE).fill(false);
    }
    persist();
    render();
    lastBingoCount = findBingos(marked).length;
  };

  const persist = () => saveState(seedKey, { cells, marked });

  // ── Render ────────────────────────────────────────────────────
  const board = document.getElementById("board");
  const dateLabel = document.getElementById("dateLabel");
  const markedCountEl = document.getElementById("markedCount");
  const bingoCountEl = document.getElementById("bingoCount");
  const bingoPluralEl = document.getElementById("bingoPlural");

  const render = () => {
    const winningLines = findBingos(marked);
    const winSet = new Set(winningLines.flat());

    board.innerHTML = "";
    cells.forEach((cell, idx) => {
      const el = document.createElement("button");
      el.type = "button";
      el.className = "cell" + (marked[idx] ? " marked" : "") + (winSet.has(idx) ? " win" : "");
      el.textContent = cell.text;
      el.setAttribute("role", "gridcell");
      el.setAttribute("aria-pressed", marked[idx] ? "true" : "false");
      el.setAttribute("aria-label", `${cell.text}${marked[idx] ? ", marked" : ""}`);
      el.addEventListener("click", () => toggle(idx));
      board.appendChild(el);
    });

    const markedTotal = marked.filter(Boolean).length;
    markedCountEl.textContent = markedTotal;
    bingoCountEl.textContent = winningLines.length;
    bingoPluralEl.textContent = winningLines.length === 1 ? "" : "s";
    dateLabel.textContent = new Date().toLocaleDateString(undefined, {
      weekday: "long", month: "long", day: "numeric",
    });
  };

  const toggle = (idx) => {
    marked[idx] = !marked[idx];
    persist();
    const before = lastBingoCount;
    const winsNow = findBingos(marked).length;
    render();
    lastBingoCount = winsNow;
    if (winsNow > before) showCelebration();
  };

  // ── Celebration ───────────────────────────────────────────────
  const celebration = document.getElementById("celebration");
  const celebrationClose = document.getElementById("celebrationClose");
  const showCelebration = () => celebration.classList.add("show");
  celebrationClose.addEventListener("click", () => celebration.classList.remove("show"));
  celebration.addEventListener("click", (e) => {
    if (e.target === celebration) celebration.classList.remove("show");
  });

  // ── Buttons ───────────────────────────────────────────────────
  document.getElementById("resetBtn").addEventListener("click", () => {
    if (!confirm("Clear all marks on today's card?")) return;
    marked = new Array(SIZE * SIZE).fill(false);
    persist();
    lastBingoCount = 0;
    render();
  });

  document.getElementById("newCardBtn").addEventListener("click", () => {
    if (!confirm("Reshuffle a brand new card? You'll lose today's marks.")) return;
    // Append a counter to today's seed to force a different shuffle.
    const bumpKey = `${seedKey}#${Date.now()}`;
    cells = buildCard(bumpKey);
    marked = new Array(SIZE * SIZE).fill(false);
    // Persist under today's key — replaces the saved card for the day.
    persist();
    lastBingoCount = 0;
    render();
  });

  // Roll over to a new card if the user keeps the page open across midnight.
  setInterval(() => {
    const k = todayKey();
    if (k !== seedKey) {
      seedKey = k;
      init();
    }
  }, 60 * 1000);

  init();
})();
