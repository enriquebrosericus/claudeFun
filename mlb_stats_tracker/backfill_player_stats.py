#!/usr/bin/env python3
"""
Backfill 2025 Mariners player stats (game-by-game progression) into PostgreSQL.

Fetches each player's game log from MLB Stats API, accumulates counting stats
game-by-game, and inserts one row per game date into player_batting / player_pitching.

Usage (from inside scraper container or locally with port 5433 forwarded):
  python3 backfill_player_stats.py [SEASON]   # default: 2025
"""

import datetime
import os
import sys
import time

import psycopg2
import requests

SEASON    = int(sys.argv[1]) if len(sys.argv) > 1 else 2025
TEAM_ID   = 136
TEAM_ABBR = "SEA"
BASE      = "https://statsapi.mlb.com/api/v1"

session = requests.Session()
session.headers.update({"User-Agent": "MLBPlayerBackfill/2.0", "Accept": "application/json"})


def get_db():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "5433")),
        dbname=os.getenv("DB_NAME", "mlb_stats"),
        user=os.getenv("DB_USER", "mlb"),
        password=os.getenv("DB_PASS", "mlbpass"),
    )


def api_get(path, **params):
    resp = session.get(f"{BASE}{path}", params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()


def sf(val, default=0.0):
    try:
        return float(val) if val not in (None, "", "-.--", "--", ".---") else default
    except (ValueError, TypeError):
        return default


def ip_to_thirds(ip_str) -> int:
    try:
        s = str(ip_str); whole, frac = s.split(".")
        return int(whole) * 3 + int(frac)
    except Exception:
        return 0


def thirds_to_ip(thirds: int) -> float:
    return round(thirds // 3 + (thirds % 3) / 10, 1)


def get_roster():
    data = api_get(f"/teams/{TEAM_ID}/roster", rosterType="active", season=SEASON)
    return data.get("roster", [])


# ── Batter backfill ───────────────────────────────────────────────────────────

def backfill_batter(cur, person_id: int, name: str, pos: str) -> int:
    data = api_get(f"/people/{person_id}/stats",
                   stats="gameLog", season=SEASON, group="hitting", sportId=1)
    splits = (data.get("stats") or [{}])[0].get("splits", [])
    if not splits:
        return 0

    cum_hr = cum_rbi = cum_h = cum_ab = cum_r = cum_bb = 0
    cum_k = cum_sb = cum_2b = cum_3b = cum_g = 0
    rows = 0

    for game in splits:
        st  = game.get("stat", {})
        date = datetime.date.fromisoformat(game.get("date", "2025-01-01"))

        cum_hr  += int(st.get("homeRuns", 0))
        cum_rbi += int(st.get("rbi", 0))
        cum_h   += int(st.get("hits", 0))
        cum_ab  += int(st.get("atBats", 0))
        cum_r   += int(st.get("runs", 0))
        cum_bb  += int(st.get("baseOnBalls", 0))
        cum_k   += int(st.get("strikeOuts", 0))
        cum_sb  += int(st.get("stolenBases", 0))
        cum_2b  += int(st.get("doubles", 0))
        cum_3b  += int(st.get("triples", 0))
        cum_g   += int(st.get("gamesPlayed", 1))

        avg  = sf(st.get("avg"))
        slg  = sf(st.get("slg"))
        obp  = sf(st.get("obp"))
        ops  = sf(st.get("ops"))
        babip = sf(st.get("babip"))

        cur.execute("""
            INSERT INTO player_batting
                (date, season, player, player_id, team, game_type, position,
                 games_played, at_bats, hits, home_runs, rbi, runs,
                 walks, strikeouts, stolen_bases, doubles, triples,
                 avg, obp, slg, ops, babip, iso)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (date, player_id, season, game_type) DO UPDATE SET
                games_played=EXCLUDED.games_played, at_bats=EXCLUDED.at_bats,
                hits=EXCLUDED.hits, home_runs=EXCLUDED.home_runs, rbi=EXCLUDED.rbi,
                runs=EXCLUDED.runs, walks=EXCLUDED.walks, strikeouts=EXCLUDED.strikeouts,
                stolen_bases=EXCLUDED.stolen_bases, doubles=EXCLUDED.doubles,
                triples=EXCLUDED.triples, avg=EXCLUDED.avg, obp=EXCLUDED.obp,
                slg=EXCLUDED.slg, ops=EXCLUDED.ops, babip=EXCLUDED.babip,
                iso=EXCLUDED.iso
        """, (date, SEASON, name, person_id, TEAM_ABBR, "R", pos,
              cum_g, cum_ab, cum_h, cum_hr, cum_rbi, cum_r,
              cum_bb, cum_k, cum_sb, cum_2b, cum_3b,
              avg, obp, slg, ops, babip, round(slg - avg, 3)))
        rows += 1

    return rows


# ── Pitcher backfill ──────────────────────────────────────────────────────────

def backfill_pitcher(cur, person_id: int, name: str, pos: str) -> int:
    data = api_get(f"/people/{person_id}/stats",
                   stats="gameLog", season=SEASON, group="pitching", sportId=1)
    splits = (data.get("stats") or [{}])[0].get("splits", [])
    if not splits:
        return 0

    cum_so = cum_bb = cum_thirds = cum_w = cum_l = 0
    cum_sv = cum_hld = cum_g = cum_qs = cum_hr = cum_er = 0
    rows = 0

    for game in splits:
        st   = game.get("stat", {})
        date = datetime.date.fromisoformat(game.get("date", "2025-01-01"))

        cum_so     += int(st.get("strikeOuts", 0))
        cum_bb     += int(st.get("baseOnBalls", 0))
        cum_thirds += ip_to_thirds(st.get("inningsPitched", "0.0"))
        cum_w      += int(st.get("wins", 0))
        cum_l      += int(st.get("losses", 0))
        cum_sv     += int(st.get("saves", 0))
        cum_hld    += int(st.get("holds", 0))
        cum_g      += int(st.get("gamesPitched", st.get("gamesPlayed", 1)))
        cum_hr     += int(st.get("homeRuns", 0))
        cum_er     += int(st.get("earnedRuns", 0))

        if ip_to_thirds(st.get("inningsPitched", "0.0")) >= 18 and int(st.get("earnedRuns", 0)) <= 3:
            cum_qs += 1

        cum_ip = thirds_to_ip(cum_thirds)
        era    = sf(st.get("era"))
        whip   = sf(st.get("whip"))
        k9     = sf(st.get("strikeoutsPer9Inn"))
        bb9    = sf(st.get("walksPer9Inn"))
        hr9    = sf(st.get("homeRunsPer9"))
        fip    = round(((13 * cum_hr + 3 * cum_bb - 2 * cum_so) / cum_ip) + 3.10, 2) \
                 if cum_ip > 0 else None

        cur.execute("""
            INSERT INTO player_pitching
                (date, season, player, player_id, team, game_type, position,
                 games, wins, losses, saves, holds, quality_starts,
                 innings_pitched, strikeouts, walks, home_runs_allowed, earned_runs,
                 era, whip, k9, bb9, hr9, fip)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (date, player_id, season, game_type) DO UPDATE SET
                games=EXCLUDED.games, wins=EXCLUDED.wins, losses=EXCLUDED.losses,
                saves=EXCLUDED.saves, holds=EXCLUDED.holds,
                quality_starts=EXCLUDED.quality_starts,
                innings_pitched=EXCLUDED.innings_pitched, strikeouts=EXCLUDED.strikeouts,
                walks=EXCLUDED.walks, home_runs_allowed=EXCLUDED.home_runs_allowed,
                earned_runs=EXCLUDED.earned_runs, era=EXCLUDED.era, whip=EXCLUDED.whip,
                k9=EXCLUDED.k9, bb9=EXCLUDED.bb9, hr9=EXCLUDED.hr9, fip=EXCLUDED.fip
        """, (date, SEASON, name, person_id, TEAM_ABBR, "R", pos,
              cum_g, cum_w, cum_l, cum_sv, cum_hld, cum_qs,
              cum_ip, cum_so, cum_bb, cum_hr, cum_er,
              era, whip, k9, bb9, hr9, fip))
        rows += 1

    return rows


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    conn = get_db()
    cur  = conn.cursor()

    roster = get_roster()
    print(f"Roster: {len(roster)} players for {SEASON}", file=sys.stderr)

    batters = pitchers = total_rows = 0

    for entry in roster:
        person    = entry.get("person", {})
        pid       = person.get("id")
        name      = person.get("fullName", "Unknown")
        pos       = entry.get("position", {})
        pos_code  = pos.get("code", "")
        is_pitcher = pos.get("type") == "Pitcher"

        print(f"  {'P' if is_pitcher else 'B'}  {name} ({pid})", file=sys.stderr)
        try:
            if is_pitcher:
                rows = backfill_pitcher(cur, pid, name, pos_code)
                pitchers += 1
            else:
                rows = backfill_batter(cur, pid, name, pos_code)
                batters += 1
            total_rows += rows
        except Exception as e:
            print(f"     ERROR: {e}", file=sys.stderr)

        conn.commit()
        time.sleep(0.2)

    cur.close()
    conn.close()
    print(f"\nDone: {batters} batters, {pitchers} pitchers, {total_rows} rows inserted.",
          file=sys.stderr)


if __name__ == "__main__":
    main()
