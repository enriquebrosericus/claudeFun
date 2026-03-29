#!/usr/bin/env python3
"""
Backfill ABS ball/strike challenge data from MLB play-by-play API.

The 2025 MLB season introduced the ABS (Automated Ball-Strike) challenge system
league-wide. Batters and managers can challenge ball/strike calls; a successful
challenge (overturned) preserves their challenge count.

Run once after backfill_game_recaps.py has populated the games table:
    python backfill_challenges.py [--season 2025] [--gamepk 778547]
"""
from __future__ import annotations

import argparse
import re
import sys
import time

import psycopg2
import requests

BASE = "https://statsapi.mlb.com/api/v1"
SEASON = 2025

DB = dict(host="localhost", dbname="mlb_stats", user="mlb", password="mlbpass", port=5433)

session = requests.Session()
session.headers["User-Agent"] = "mlb-stats-tracker/1.0"

# Patterns that indicate a ball/strike ABS challenge event.
# The event description typically reads:
#   "Ball 2 overturned to Strike 2 on ABS Challenge."
#   "Strike 3 upheld as Strike 3 on ABS Challenge."
_CHALLENGE_RE = re.compile(
    r"(Ball|Strike)\s+\d+\s+(overturned to|upheld as)\s+(Ball|Strike)",
    re.IGNORECASE,
)
_CHALLENGE_EVENTS = {
    "abs_challenge_batter", "abs challenge", "batter challenge",
    "manager challenge", "challenge", "review",
}


def api_get(path: str, **params) -> dict:
    resp = session.get(f"{BASE}{path}", params=params, timeout=20)
    resp.raise_for_status()
    return resp.json()


def fetch_play_by_play(gamepk: int) -> list:
    try:
        data = api_get(f"/game/{gamepk}/playByPlay")
        return data.get("allPlays", [])
    except Exception as e:
        print(f"  ⚠ PBP fetch failed for {gamepk}: {e}")
        return []


def parse_challenges(plays: list, game: dict) -> list[dict]:
    """Extract ABS challenge events from play-by-play data."""
    challenges = []
    home_team = game["home_team"]
    away_team = game["away_team"]

    for play in plays:
        about = play.get("about", {})
        inning = about.get("inning", 0)
        half = "top" if about.get("halfInning") == "top" else "bottom"
        at_bat_index = about.get("atBatIndex", 0)
        matchup = play.get("matchup", {})
        batter_team_id = matchup.get("batter", {}).get("id")

        for event in play.get("playEvents", []):
            if event.get("type") != "action":
                continue

            details = event.get("details", {})
            event_type = (details.get("eventType") or "").lower()
            event_name = (details.get("event") or "").lower()
            description = details.get("description") or ""

            # Check if this looks like a ball/strike challenge
            is_challenge = (
                any(kw in event_type for kw in _CHALLENGE_EVENTS)
                or any(kw in event_name for kw in _CHALLENGE_EVENTS)
            )
            if not is_challenge:
                continue

            match = _CHALLENGE_RE.search(description)
            if not match:
                continue

            call_before = match.group(1).capitalize()
            verdict     = match.group(2).lower()   # "overturned to" or "upheld as"
            call_after  = match.group(3).capitalize()
            result      = "overturned" if "overturned" in verdict else "upheld"

            # Determine which team challenged
            # If the half is 'top', the batting team is the away team
            batting_team = away_team if half == "top" else home_team
            challenging_team = batting_team  # batter challenges their own at-bat

            # Determine type: batter challenge vs manager challenge
            ch_type = "batter"
            if "manager" in event_name or "manager" in event_type:
                ch_type = "manager"

            challenges.append({
                "gamepk":           game["gamepk"],
                "date":             game["date"],
                "season":           game["season"],
                "inning":           inning,
                "inning_half":      half,
                "at_bat_index":     at_bat_index,
                "pitch_number":     event.get("pitchNumber"),
                "challenging_team": challenging_team,
                "challenging_type": ch_type,
                "call_before":      call_before,
                "call_after":       call_after,
                "challenge_result": result,
            })

    return challenges


def upsert_challenges(conn, challenges: list[dict]) -> int:
    if not challenges:
        return 0
    cur = conn.cursor()
    inserted = 0
    for c in challenges:
        cur.execute("""
            INSERT INTO game_challenges
                (gamepk, date, season, inning, inning_half, at_bat_index, pitch_number,
                 challenging_team, challenging_type, call_before, call_after, challenge_result)
            VALUES
                (%(gamepk)s, %(date)s, %(season)s, %(inning)s, %(inning_half)s,
                 %(at_bat_index)s, %(pitch_number)s,
                 %(challenging_team)s, %(challenging_type)s,
                 %(call_before)s, %(call_after)s, %(challenge_result)s)
            ON CONFLICT (gamepk, inning, inning_half, at_bat_index, pitch_number) DO NOTHING
        """, c)
        inserted += cur.rowcount
    conn.commit()
    return inserted


def get_games(conn, season: int, gamepk: int | None) -> list[dict]:
    cur = conn.cursor()
    if gamepk:
        cur.execute("""
            SELECT gamepk, date, season, home_team, away_team
            FROM games WHERE gamepk = %s
        """, (gamepk,))
    else:
        cur.execute("""
            SELECT gamepk, date, season, home_team, away_team
            FROM games
            WHERE season = %s AND game_type = 'R' AND status = 'Final'
            ORDER BY date
        """, (season,))
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def main():
    parser = argparse.ArgumentParser(description="Backfill ABS challenge data")
    parser.add_argument("--season", type=int, default=SEASON)
    parser.add_argument("--gamepk", type=int, default=None,
                        help="Process a single game instead of the full season")
    args = parser.parse_args()

    conn = psycopg2.connect(**DB)
    games = get_games(conn, args.season, args.gamepk)

    if not games:
        print("No games found.")
        sys.exit(0)

    print(f"Processing {len(games)} game(s) for season {args.season}...")
    total_inserted = 0
    errors = 0

    for i, game in enumerate(games, 1):
        print(f"  [{i:3d}/{len(games)}] {game['date']} {game['away_team']} @ {game['home_team']} ({game['gamepk']})", end=" ")
        try:
            plays      = fetch_play_by_play(game["gamepk"])
            challenges = parse_challenges(plays, game)
            inserted   = upsert_challenges(conn, challenges)
            print(f"→ {len(challenges)} challenge(s), {inserted} new")
            total_inserted += inserted
        except Exception as e:
            print(f"ERROR: {e}")
            errors += 1

        # Be polite to the API
        if i % 10 == 0:
            time.sleep(1)

    conn.close()
    print(f"\nDone. {total_inserted} challenge events inserted, {errors} errors.")
    if total_inserted == 0:
        print("\nNote: 0 challenges found. The ABS challenge system may not be")
        print("available yet for this season, or these games predate its introduction.")
        print("Check the 2025 regular season games — ABS was implemented league-wide")
        print("starting with the 2025 opening series.")


if __name__ == "__main__":
    main()
