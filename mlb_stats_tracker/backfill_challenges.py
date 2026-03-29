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
import os
import sys
import time

import psycopg2
import requests

BASE = "https://statsapi.mlb.com/api/v1"
SEASON = 2026

DB = dict(
    host=os.getenv("DB_HOST", "localhost"),
    port=int(os.getenv("DB_PORT", "5433")),
    dbname=os.getenv("DB_NAME", "mlb_stats"),
    user=os.getenv("DB_USER", "mlb"),
    password=os.getenv("DB_PASS"),
)

session = requests.Session()
session.headers["User-Agent"] = "mlb-stats-tracker/1.0"

# Ball/strike call codes in the pitch details
_BALL_CODES   = {"B", "I", "P", "V"}   # ball, intentional, pitchout, automatic ball
_STRIKE_CODES = {"C", "S", "T", "Q"}   # called, swinging, foul tip, automatic strike


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


def _normalize_call(code: str) -> str:
    """Convert pitch call code to 'Ball' or 'Strike'."""
    if code in _BALL_CODES:
        return "Ball"
    if code in _STRIKE_CODES:
        return "Strike"
    return code  # unknown — store as-is


def parse_challenges(plays: list, game: dict, team_id_map: dict) -> list[dict]:
    """Extract ABS challenge events from pitch-level reviewDetails."""
    challenges = []

    for play in plays:
        about = play.get("about", {})
        inning = about.get("inning", 0)
        half = "top" if about.get("halfInning") == "top" else "bottom"
        at_bat_index = about.get("atBatIndex", 0)

        for event in play.get("playEvents", []):
            rd = event.get("reviewDetails")
            if not rd or rd.get("inProgress"):
                continue

            details = event.get("details", {})
            call_code = details.get("call", {}).get("code", "")
            call_after = _normalize_call(call_code)

            is_overturned = rd.get("isOverturned", False)
            # If overturned, the original call was the opposite of the final call
            if is_overturned:
                call_before = "Strike" if call_after == "Ball" else "Ball"
            else:
                call_before = call_after

            challenge_team_id = rd.get("challengeTeamId")
            challenging_team = team_id_map.get(challenge_team_id, str(challenge_team_id))

            # reviewType: "MJ" = manager/player challenge (ABS system)
            ch_type = rd.get("reviewType", "MJ")

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
                "challenge_result": "overturned" if is_overturned else "upheld",
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


def get_team_id_map(conn) -> dict:
    """Return {team_id: abbreviation} from division_standings."""
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT team_id, team FROM division_standings")
    return {row[0]: row[1] for row in cur.fetchall()}


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
    team_id_map = get_team_id_map(conn)
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
            challenges = parse_challenges(plays, game, team_id_map)
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
