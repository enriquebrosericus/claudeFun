#!/usr/bin/env python3
"""
Backfill AL West division standings for a full season into PostgreSQL.

Usage (from inside scraper container or locally with port 5433 forwarded):
  python3 backfill_standings.py [SEASON]   # default: 2025

Run after 'docker compose up -d' so postgres is ready.
"""

import datetime
import os
import sys
import time

import psycopg2
import requests

SEASON = int(sys.argv[1]) if len(sys.argv) > 1 else 2025
BASE   = "https://statsapi.mlb.com/api/v1"
AL_WEST_DIVISION_ID = 200

TEAM_ABBR = {108: "LAA", 117: "HOU", 133: "ATH", 136: "SEA", 140: "TEX"}

SEASON_START = datetime.date(SEASON, 3, 20)
SEASON_END   = datetime.date(SEASON, 9, 30)

session = requests.Session()
session.headers.update({"User-Agent": "MLBBackfill/2.0", "Accept": "application/json"})


def get_db():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "5433")),
        dbname=os.getenv("DB_NAME", "mlb_stats"),
        user=os.getenv("DB_USER", "mlb"),
        password=os.getenv("DB_PASS", "mlbpass"),
    )


def fetch_al_west(date_str: str) -> list[dict]:
    try:
        resp = session.get(f"{BASE}/standings", params={
            "leagueId": 103, "season": SEASON,
            "standingsTypes": "regularSeason",
            "date": date_str, "sportId": 1,
        }, timeout=15)
        resp.raise_for_status()
        for div in resp.json().get("records", []):
            if div.get("division", {}).get("id") == AL_WEST_DIVISION_ID:
                return div.get("teamRecords", [])
    except Exception as e:
        print(f"  {date_str}: error — {e}", file=sys.stderr)
    return []


def main():
    conn = get_db()
    cur  = conn.cursor()
    print(f"Backfilling AL West standings for {SEASON}...", file=sys.stderr)

    current = SEASON_START
    days_inserted = 0

    while current <= SEASON_END:
        date_str = current.strftime("%Y-%m-%d")
        records  = fetch_al_west(date_str)

        if records:
            for rec in records:
                team     = rec.get("team", {})
                team_id  = team.get("id")
                team_abbr = TEAM_ABBR.get(team_id, team.get("name", "UNK"))
                wins     = rec.get("wins", 0)
                losses   = rec.get("losses", 0)
                gb_raw   = rec.get("gamesBack", "0")
                try:
                    gb = 0.0 if gb_raw in ("-", "", None) else float(gb_raw)
                except ValueError:
                    gb = 0.0

                cur.execute("""
                    INSERT INTO division_standings
                        (date, season, team, team_id, division, wins, losses, games_behind)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (date, team, season) DO UPDATE SET
                        wins = EXCLUDED.wins,
                        losses = EXCLUDED.losses,
                        games_behind = EXCLUDED.games_behind
                """, (current, SEASON, team_abbr, team_id, "AL West", wins, losses, gb))

            conn.commit()
            days_inserted += 1
            print(f"  {date_str}: {len(records)} teams inserted", file=sys.stderr)
        else:
            print(f"  {date_str}: no data", file=sys.stderr)

        current += datetime.timedelta(days=1)
        time.sleep(0.15)

    cur.close()
    conn.close()
    print(f"\nDone: {days_inserted} days inserted into division_standings.", file=sys.stderr)


if __name__ == "__main__":
    main()
