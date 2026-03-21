"""
MLB Stats Tracker — Seattle Mariners
Writes daily stats to PostgreSQL. Each scrape cycle upserts today's row.
Historical data is populated separately by the backfill scripts.
"""

import datetime
import logging
import os
import time
from typing import Optional

import psycopg2
import psycopg2.extras
import requests

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
TEAM_ID       = int(os.getenv("TEAM_ID", "136"))
TEAM_ABBR     = os.getenv("TEAM_ABBR", "SEA")
SEASON        = int(os.getenv("SEASON", str(datetime.date.today().year)))
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "1800"))
MLB_API       = "https://statsapi.mlb.com/api/v1"

DB_HOST = os.getenv("DB_HOST", "postgres")
DB_PORT = int(os.getenv("DB_PORT", "5432"))
DB_NAME = os.getenv("DB_NAME", "mlb_stats")
DB_USER = os.getenv("DB_USER", "mlb")
DB_PASS = os.getenv("DB_PASS", "mlbpass")

PITCHER_POSITIONS = {"P", "SP", "RP", "CP"}

AL_WEST_TEAM_ABBR = {108: "LAA", 117: "HOU", 133: "ATH", 136: "SEA", 140: "TEX"}


# ── Database ──────────────────────────────────────────────────────────────────
def get_db():
    return psycopg2.connect(
        host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
        user=DB_USER, password=DB_PASS,
    )


def wait_for_db(max_attempts: int = 10) -> psycopg2.extensions.connection:
    for attempt in range(1, max_attempts + 1):
        try:
            conn = get_db()
            log.info("Connected to PostgreSQL")
            return conn
        except psycopg2.OperationalError as e:
            log.warning("DB not ready (attempt %d/%d): %s", attempt, max_attempts, e)
            time.sleep(5)
    raise RuntimeError("Could not connect to PostgreSQL after retries")


# ── MLB API ───────────────────────────────────────────────────────────────────
def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": "MLBStatsTracker/2.0", "Accept": "application/json"})
    return s


def api_get(session: requests.Session, path: str, **params) -> dict:
    resp = session.get(f"{MLB_API}{path}", params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()


def sf(val, default: float = 0.0) -> float:
    try:
        return float(val) if val not in (None, "", "-.--", "--", ".---") else default
    except (ValueError, TypeError):
        return default


def ip_to_thirds(ip_str) -> int:
    try:
        s = str(ip_str)
        whole, frac = s.split(".")
        return int(whole) * 3 + int(frac)
    except Exception:
        return 0


def thirds_to_ip(thirds: int) -> float:
    return round(thirds // 3 + (thirds % 3) / 10, 1)


# ── Standings ─────────────────────────────────────────────────────────────────
def scrape_standings(session: requests.Session, conn, today: datetime.date) -> None:
    data = api_get(session, "/standings",
                   leagueId=103, season=SEASON, standingsTypes="regularSeason")
    cur = conn.cursor()

    for division in data.get("records", []):
        div_info = division.get("division", {})
        div_name = div_info.get("nameShort", "")
        is_al_west = div_info.get("id") == 200

        for rec in division.get("teamRecords", []):
            team = rec.get("team", {})
            team_id = team.get("id")
            team_abbr = AL_WEST_TEAM_ABBR.get(team_id, team.get("name", "UNK"))
            wins   = rec.get("wins", 0)
            losses = rec.get("losses", 0)
            gb_raw = rec.get("gamesBack", "0")
            gb = 0.0 if gb_raw in ("-", "", None) else sf(gb_raw)

            # Division standings for all AL West teams
            if is_al_west:
                cur.execute("""
                    INSERT INTO division_standings
                        (date, season, team, team_id, division, wins, losses, games_behind)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (date, team, season) DO UPDATE SET
                        wins = EXCLUDED.wins,
                        losses = EXCLUDED.losses,
                        games_behind = EXCLUDED.games_behind
                """, (today, SEASON, team_abbr, team_id, div_name, wins, losses, gb))

            # Full team stats for the Mariners
            if team_id == TEAM_ID:
                win_pct = sf(rec.get("winningPercentage"))
                rs = sf(rec.get("runsScored"))
                ra = sf(rec.get("runsAllowed"))

                streak_str = rec.get("streak", {}).get("streakCode", "W0")
                try:
                    streak = int(streak_str[1:]) * (1 if streak_str[0] == "W" else -1)
                except (ValueError, IndexError):
                    streak = 0

                l10 = home_w = away_w = 0
                for split in rec.get("records", {}).get("splitRecords", []):
                    if split.get("type") == "lastTen":
                        l10 = split.get("wins", 0)
                    elif split.get("type") == "home":
                        home_w = split.get("wins", 0)
                    elif split.get("type") == "away":
                        away_w = split.get("wins", 0)

                cur.execute("""
                    INSERT INTO team_stats
                        (date, season, team, team_id, division, wins, losses, win_pct,
                         games_behind, runs_scored, runs_allowed, streak,
                         last10_wins, home_wins, away_wins)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (date, team, season) DO UPDATE SET
                        wins=EXCLUDED.wins, losses=EXCLUDED.losses,
                        win_pct=EXCLUDED.win_pct, games_behind=EXCLUDED.games_behind,
                        runs_scored=EXCLUDED.runs_scored, runs_allowed=EXCLUDED.runs_allowed,
                        streak=EXCLUDED.streak, last10_wins=EXCLUDED.last10_wins,
                        home_wins=EXCLUDED.home_wins, away_wins=EXCLUDED.away_wins
                """, (today, SEASON, TEAM_ABBR, TEAM_ID, div_name, wins, losses, win_pct,
                      gb, rs, ra, streak, l10, home_w, away_w))
                log.info("Team: %s-%s  GB=%.1f  Streak=%+d", wins, losses, gb, streak)

    conn.commit()
    cur.close()


# ── Player Stats ──────────────────────────────────────────────────────────────
def get_roster(session: requests.Session) -> list:
    data = api_get(session, f"/teams/{TEAM_ID}/roster",
                   rosterType="active", season=SEASON)
    return data.get("roster", [])


def get_hitting_stats(session, person_id) -> Optional[dict]:
    data = api_get(session, f"/people/{person_id}/stats",
                   stats="season", season=SEASON, group="hitting", sportId=1)
    stats = data.get("stats") or []
    if not stats:
        return None
    splits = stats[0].get("splits", [])
    return splits[0].get("stat") if splits else None


def get_pitching_stats(session, person_id) -> Optional[dict]:
    data = api_get(session, f"/people/{person_id}/stats",
                   stats="season", season=SEASON, group="pitching", sportId=1)
    stats = data.get("stats") or []
    if not stats:
        return None
    splits = stats[0].get("splits", [])
    return splits[0].get("stat") if splits else None


def upsert_batter(cur, today, player_id, name, pos, stat) -> None:
    avg = sf(stat.get("avg"))
    slg = sf(stat.get("slg"))
    cur.execute("""
        INSERT INTO player_batting
            (date, season, player, player_id, team, position,
             games_played, at_bats, hits, home_runs, rbi, runs,
             walks, strikeouts, stolen_bases, doubles, triples,
             avg, obp, slg, ops, babip, iso)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (date, player_id, season) DO UPDATE SET
            games_played=EXCLUDED.games_played, at_bats=EXCLUDED.at_bats,
            hits=EXCLUDED.hits, home_runs=EXCLUDED.home_runs,
            rbi=EXCLUDED.rbi, runs=EXCLUDED.runs,
            walks=EXCLUDED.walks, strikeouts=EXCLUDED.strikeouts,
            stolen_bases=EXCLUDED.stolen_bases, doubles=EXCLUDED.doubles,
            triples=EXCLUDED.triples, avg=EXCLUDED.avg, obp=EXCLUDED.obp,
            slg=EXCLUDED.slg, ops=EXCLUDED.ops, babip=EXCLUDED.babip,
            iso=EXCLUDED.iso
    """, (
        today, SEASON, name, player_id, TEAM_ABBR, pos,
        int(sf(stat.get("gamesPlayed"))), int(sf(stat.get("atBats"))),
        int(sf(stat.get("hits"))), int(sf(stat.get("homeRuns"))),
        int(sf(stat.get("rbi"))), int(sf(stat.get("runs"))),
        int(sf(stat.get("baseOnBalls"))), int(sf(stat.get("strikeOuts"))),
        int(sf(stat.get("stolenBases"))), int(sf(stat.get("doubles"))),
        int(sf(stat.get("triples"))),
        avg, sf(stat.get("obp")), slg, sf(stat.get("ops")),
        sf(stat.get("babip")), round(slg - avg, 3),
    ))


def upsert_pitcher(cur, today, player_id, name, pos, stat) -> None:
    ip     = sf(stat.get("inningsPitched"))
    hr     = sf(stat.get("homeRunsAllowed", stat.get("homeRuns")))
    bb     = sf(stat.get("baseOnBalls"))
    so     = sf(stat.get("strikeOuts"))
    fip    = round(((13 * hr + 3 * bb - 2 * so) / ip) + 3.10, 2) if ip > 0 else None
    cur.execute("""
        INSERT INTO player_pitching
            (date, season, player, player_id, team, position,
             games, wins, losses, saves, holds, quality_starts,
             innings_pitched, strikeouts, walks, home_runs_allowed, earned_runs,
             era, whip, k9, bb9, hr9, fip)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (date, player_id, season) DO UPDATE SET
            games=EXCLUDED.games, wins=EXCLUDED.wins, losses=EXCLUDED.losses,
            saves=EXCLUDED.saves, holds=EXCLUDED.holds,
            quality_starts=EXCLUDED.quality_starts,
            innings_pitched=EXCLUDED.innings_pitched, strikeouts=EXCLUDED.strikeouts,
            walks=EXCLUDED.walks, home_runs_allowed=EXCLUDED.home_runs_allowed,
            earned_runs=EXCLUDED.earned_runs, era=EXCLUDED.era,
            whip=EXCLUDED.whip, k9=EXCLUDED.k9, bb9=EXCLUDED.bb9,
            hr9=EXCLUDED.hr9, fip=EXCLUDED.fip
    """, (
        today, SEASON, name, player_id, TEAM_ABBR, pos,
        int(sf(stat.get("gamesPitched"))), int(sf(stat.get("wins"))),
        int(sf(stat.get("losses"))), int(sf(stat.get("saves"))),
        int(sf(stat.get("holds"))), int(sf(stat.get("qualityStarts"))),
        ip, int(so), int(bb),
        int(hr), int(sf(stat.get("earnedRuns"))),
        sf(stat.get("era")), sf(stat.get("whip")),
        sf(stat.get("strikeoutsPer9Inn")), sf(stat.get("walksPer9Inn")),
        sf(stat.get("homeRunsPer9")), fip,
    ))


def scrape_players(session: requests.Session, conn, today: datetime.date) -> None:
    roster = get_roster(session)
    log.info("Roster: %d players", len(roster))
    cur = conn.cursor()
    count = 0

    for entry in roster:
        person    = entry.get("person", {})
        pid       = person.get("id")
        name      = person.get("fullName", "Unknown")
        pos       = entry.get("position", {})
        pos_code  = pos.get("code", "")
        is_pitcher = pos.get("type") == "Pitcher"

        try:
            if is_pitcher:
                stat = get_pitching_stats(session, pid)
                if stat:
                    upsert_pitcher(cur, today, pid, name, pos_code, stat)
                    count += 1
            else:
                stat = get_hitting_stats(session, pid)
                if stat:
                    upsert_batter(cur, today, pid, name, pos_code, stat)
                    count += 1
            time.sleep(0.2)
        except Exception as e:
            log.warning("Stats failed for %s: %s", name, e)

    conn.commit()
    cur.close()
    log.info("Players: %d/%d updated", count, len(roster))


# ── Game State ────────────────────────────────────────────────────────────────
def get_todays_game_state(session: requests.Session) -> Optional[str]:
    today = datetime.date.today().isoformat()
    data = api_get(session, "/schedule", teamId=TEAM_ID, date=today, sportId=1)
    dates = data.get("dates", [])
    if not dates:
        return None
    games = dates[0].get("games", [])
    return games[0].get("status", {}).get("abstractGameState") if games else None


def sleep_until_next_scrape(session: requests.Session) -> None:
    try:
        state = get_todays_game_state(session)
        if state == "Final":
            log.info("Game Final — re-scraping in 5 min")
            time.sleep(300)
            return
        elif state == "Live":
            log.info("Game Live — polling in 10 min")
            time.sleep(600)
            return
    except Exception:
        pass
    log.info("Sleeping %ds", POLL_INTERVAL)
    time.sleep(POLL_INTERVAL)


# ── Main ─────────────────────────────────────────────────────────────────────
def main() -> None:
    log.info("MLB Stats Tracker starting — Team=%s  Season=%s", TEAM_ABBR, SEASON)
    conn = wait_for_db()
    session = make_session()

    while True:
        today = datetime.date.today()
        try:
            log.info("── Scrape cycle %s ──", today)
            scrape_standings(session, conn, today)
            scrape_players(session, conn, today)
            log.info("Cycle complete")
        except Exception as e:
            log.exception("Scrape cycle error: %s", e)
            try:
                conn.rollback()
            except Exception:
                pass
            # Reconnect if DB connection dropped
            try:
                conn = get_db()
            except Exception:
                pass

        sleep_until_next_scrape(session)


if __name__ == "__main__":
    main()
