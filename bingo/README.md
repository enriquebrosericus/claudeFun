# Buzzword Bingo

A play-throughout-the-day bingo card. Each day you get a freshly shuffled 4×4
card. Tap a square when you hear the phrase out loud — marks persist in your
browser, so you can keep the page open all day (or revisit it) and pick up
where you left off.

## Run it

```bash
docker compose up --build
```

Then open: **https://localhost:8444**

The container generates a self-signed cert on startup, so your browser will
warn you the first time — that's expected. Plain HTTP also works at
http://localhost:8878.

## Customizing the phrase list

Edit [phrases.js](phrases.js) — it's a single array. You need at least
**16 phrases** (one per cell on the 4×4 card). More phrases = more variety in
the daily shuffle.

After editing, rebuild:

```bash
docker compose up --build
```

## How it works

- **Daily card**: phrases are shuffled deterministically using the local date
  as a seed, so the same card persists all day across reloads. At local
  midnight a new card is generated.
- **Persistence**: marks are stored in `localStorage` keyed by date.
- **Win detection**: any complete row, column, or diagonal triggers a
  celebration. Multiple bingos are tracked.
- **Reset / New Card**: `Reset` clears today's marks. `New Card` reshuffles
  to a fresh card (replaces the saved card for the day).

## Files

- [index.html](index.html) — markup
- [style.css](style.css) — styling
- [app.js](app.js) — game logic (card generation, persistence, win detection)
- [phrases.js](phrases.js) — phrase list (edit this)
- [nginx.conf](nginx.conf) — nginx config (HTTP + HTTPS, SPA-style fallback)
- [Dockerfile](Dockerfile) — nginx:1.27-alpine + app files
- [docker-compose.yml](docker-compose.yml) — generates self-signed cert at runtime
