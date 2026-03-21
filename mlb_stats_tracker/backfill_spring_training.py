#!/usr/bin/env python3
"""
Backfill spring training player stats into PostgreSQL.

Fetches season-total spring training stats (gameType=S) for each player
on the 2026 Mariners roster and inserts a single snapshot row per player
with today's date and game_type='S'.

Re-run any time to refresh the snapshot (ON CONFLICT DO UPDATE).

Usage (from inside scraper container or locally with port 5433 forwarded):
  python3 backfill_spring_training.py [SEASON]   # default: 2026
"""

import datetime
import os
import sys
import time

import psycopg2
import requests

SEASON    = int(sys.argv[1]) if len(sys.argv) > 1 else 2026
TEAM_ID   = 136
TEAM_ABBR = "SEA"
BASE      = "https://statsapi.mlb.com/api/v1"
GAME_TYPE = "S"

session = requests.Session()
session.headers.update({"User-Agent": "MLBSpringBackfill/1.0", "Accept": "application/json"})


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


def get_roster():
    # Use depthChart to get anyone who might appear in spring training
    data = api_get(f"/teams/{TEAM_ID}/roster", rosterType="depthChart", season=SEASON)
    return data.get("roster", [])


def upsert_batter(cur, today, person_id, name, pos):
    data = api_get(f"/people/{person_id}/stats",
                   stats="season", season=SEASON, gameType=GAME_TYPE,
                   group="hitting", sportId=1)
    stats = data.get("stats") or []
    if not stats:
        return False
    splits = stats[0].get("splits", [])
    if not splits:
        return False
    st = splits[0].get("stat", {})

    avg = sf(st.get("avg"))
    slg = sf(st.get("slg"))
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
    """, (
        today, SEASON, name, person_id, TEAM_ABBR, GAME_TYPE, pos,
        int(sf(st.get("gamesPlayed"))), int(sf(st.get("atBats"))),
        int(sf(st.get("hits"))), int(sf(st.get("homeRuns"))),
        int(sf(st.get("rbi"))), int(sf(st.get("runs"))),
        int(sf(st.get("baseOnBalls"))), int(sf(st.get("strikeOuts"))),
        int(sf(st.get("stolenBases"))), int(sf(st.get("doubles"))),
        int(sf(st.get("triples"))),
        avg, sf(st.get("obp")), slg, sf(st.get("ops")),
        sf(st.get("babip")), round(slg - avg, 3),
    ))
    return True


def upsert_pitcher(cur, today, person_id, name, pos):
    data = api_get(f"/people/{person_id}/stats",
                   stats="season", season=SEASON, gameType=GAME_TYPE,
                   group="pitching", sportId=1)
    stats = data.get("stats") or []
    if not stats:
        return False
    splits = stats[0].get("splits", [])
    if not splits:
        return False
    st = splits[0].get("stat", {})

    ip  = sf(st.get("inningsPitched"))
    hr  = sf(st.get("homeRunsAllowed", st.get("homeRuns")))
    bb  = sf(st.get("baseOnBalls"))
    so  = sf(st.get("strikeOuts"))
    fip = round(((13 * hr + 3 * bb - 2 * so) / ip) + 3.10, 2) if ip > 0 else None

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
    """, (
        today, SEASON, name, person_id, TEAM_ABBR, GAME_TYPE, pos,
        int(sf(st.get("gamesPitched", st.get("gamesPlayed", 0)))),
        int(sf(st.get("wins"))), int(sf(st.get("losses"))),
        int(sf(st.get("saves"))), int(sf(st.get("holds"))),
        int(sf(st.get("qualityStarts"))),
        ip, int(so), int(bb), int(hr),
        int(sf(st.get("earnedRuns"))),
        sf(st.get("era")), sf(st.get("whip")),
        sf(st.get("strikeoutsPer9Inn")), sf(st.get("walksPer9Inn")),
        sf(st.get("homeRunsPer9")), fip,
    ))
    return True


def main():
    today = datetime.date.today()
    conn  = get_db()
    cur   = conn.cursor()

    roster = get_roster()
    print(f"Roster: {len(roster)} players for {SEASON} spring training", file=sys.stderr)

    batters = pitchers = skipped = 0

    for entry in roster:
        person   = entry.get("person", {})
        pid      = person.get("id")
        name     = person.get("fullName", "Unknown")
        pos      = entry.get("position", {})
        pos_code = pos.get("code", "")
        is_pitcher = pos.get("type") == "Pitcher"

        try:
            if is_pitcher:
                ok = upsert_pitcher(cur, today, pid, name, pos_code)
                if ok:
                    pitchers += 1
                    print(f"  P  {name}", file=sys.stderr)
                else:
                    skipped += 1
                    print(f"  P  {name} — no spring data", file=sys.stderr)
            else:
                ok = upsert_batter(cur, today, pid, name, pos_code)
                if ok:
                    batters += 1
                    print(f"  B  {name}", file=sys.stderr)
                else:
                    skipped += 1
                    print(f"  B  {name} — no spring data", file=sys.stderr)
        except Exception as e:
            print(f"     ERROR {name}: {e}", file=sys.stderr)

        conn.commit()
        time.sleep(0.2)

    cur.close()
    conn.close()
    print(f"\nDone: {batters} batters, {pitchers} pitchers inserted. {skipped} skipped (no spring data).",
          file=sys.stderr)


if __name__ == "__main__":
    main()
