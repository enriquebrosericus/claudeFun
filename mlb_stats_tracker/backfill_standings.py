#!/usr/bin/env python3
"""
Backfill standings for all 30 MLB teams into division_standings and team_stats.

Iterates every day of the season, fetches AL + NL standings from the MLB Stats
API, and upserts one row per team per day into both tables.

Usage (from inside scraper container or locally with port 5433 forwarded):
  python3 backfill_standings.py [SEASON]   # default: 2025

Re-running is safe — all upserts use ON CONFLICT DO UPDATE.
"""

import datetime
import os
import sys
import time

import psycopg2
import requests

SEASON       = int(sys.argv[1]) if len(sys.argv) > 1 else 2026
BASE         = "https://statsapi.mlb.com/api/v1"
SEASON_START = datetime.date(SEASON, 3, 20)
SEASON_END   = min(datetime.date(SEASON, 10, 5), datetime.date.today())

session = requests.Session()
session.headers.update({"User-Agent": "MLBStandingsBackfill/3.0", "Accept": "application/json"})


def get_db():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "5433")),
        dbname=os.getenv("DB_NAME", "mlb_stats"),
        user=os.getenv("DB_USER", "mlb"),
        password=os.getenv("DB_PASS"),
    )


def sf(val, default=0.0):
    try:
        return float(val) if val not in (None, "", "-", "-.--") else default
    except (ValueError, TypeError):
        return default


def fetch_all_standings(date_str: str) -> list:
    """Return list of teamRecord dicts for all 30 teams on the given date."""
    records = []
    for league_id in (103, 104):  # AL, NL
        try:
            resp = session.get(f"{BASE}/standings", params={
                "leagueId":      league_id,
                "season":        SEASON,
                "standingsTypes": "regularSeason",
                "date":          date_str,
                "sportId":       1,
                "hydrate":       "team(division)",
            }, timeout=15)
            resp.raise_for_status()
            for div in resp.json().get("records", []):
                records.extend(div.get("teamRecords", []))
        except Exception as e:
            print(f"  {date_str} league={league_id}: error — {e}", file=sys.stderr)
    return records


def main():
    conn = get_db()
    cur  = conn.cursor()
    print(f"Backfilling all-team standings for {SEASON} "
          f"({SEASON_START} → {SEASON_END})...", file=sys.stderr)

    current      = SEASON_START
    days_done    = 0
    rows_inserted = 0

    while current <= SEASON_END:
        date_str = current.strftime("%Y-%m-%d")
        records  = fetch_all_standings(date_str)

        if records:
            for rec in records:
                team      = rec.get("team", {})
                team_id   = team.get("id")
                team_abbr = team.get("abbreviation", "UNK")
                div_name  = team.get("division", {}).get("nameShort", "")
                wins      = rec.get("wins", 0)
                losses    = rec.get("losses", 0)
                gb_raw    = rec.get("gamesBack", "0")
                gb        = 0.0 if gb_raw in ("-", "", None) else sf(gb_raw)

                cur.execute("""
                    INSERT INTO division_standings
                        (date, season, team, team_id, game_type, division, wins, losses, games_behind)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (date, team, season, game_type) DO UPDATE SET
                        wins=EXCLUDED.wins, losses=EXCLUDED.losses,
                        games_behind=EXCLUDED.games_behind
                """, (current, SEASON, team_abbr, team_id, "R", div_name, wins, losses, gb))

                win_pct    = sf(rec.get("winningPercentage"))
                rs         = sf(rec.get("runsScored"))
                ra         = sf(rec.get("runsAllowed"))
                streak_str = rec.get("streak", {}).get("streakCode", "W0")
                try:
                    streak = int(streak_str[1:]) * (1 if streak_str[0] == "W" else -1)
                except (ValueError, IndexError):
                    streak = 0

                l10 = home_w = away_w = 0
                for split in rec.get("records", {}).get("splitRecords", []):
                    t = split.get("type")
                    if t == "lastTen":
                        l10    = split.get("wins", 0)
                    elif t == "home":
                        home_w = split.get("wins", 0)
                    elif t == "away":
                        away_w = split.get("wins", 0)

                cur.execute("""
                    INSERT INTO team_stats
                        (date, season, team, team_id, game_type, division, wins, losses, win_pct,
                         games_behind, runs_scored, runs_allowed, streak,
                         last10_wins, home_wins, away_wins)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (date, team, season, game_type) DO UPDATE SET
                        wins=EXCLUDED.wins, losses=EXCLUDED.losses,
                        win_pct=EXCLUDED.win_pct, games_behind=EXCLUDED.games_behind,
                        runs_scored=EXCLUDED.runs_scored, runs_allowed=EXCLUDED.runs_allowed,
                        streak=EXCLUDED.streak, last10_wins=EXCLUDED.last10_wins,
                        home_wins=EXCLUDED.home_wins, away_wins=EXCLUDED.away_wins
                """, (current, SEASON, team_abbr, team_id, "R", div_name, wins, losses, win_pct,
                      gb, rs, ra, streak, l10, home_w, away_w))

                rows_inserted += 1

            conn.commit()
            days_done += 1
            print(f"  {date_str}: {len(records)} teams", file=sys.stderr)
        else:
            print(f"  {date_str}: no data (off day or pre-season)", file=sys.stderr)

        current += datetime.timedelta(days=1)
        time.sleep(0.25)  # two league fetches per day, be polite

    cur.close()
    conn.close()
    print(f"\nDone: {days_done} days, {rows_inserted} rows upserted.", file=sys.stderr)


if __name__ == "__main__":
    main()
