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

GAME_TYPE         = os.getenv("GAME_TYPE", "R")
PITCHER_POSITIONS = {"P", "SP", "RP", "CP"}


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
    for attempt in range(4):
        resp = session.get(f"{MLB_API}{path}", params=params, timeout=15)
        if resp.status_code == 429 or resp.status_code >= 500:
            wait = 2 ** attempt * 5  # 5, 10, 20, 40s
            log.warning("MLB API %s (attempt %d) — retrying in %ds", resp.status_code, attempt + 1, wait)
            time.sleep(wait)
            continue
        resp.raise_for_status()
        return resp.json()
    resp.raise_for_status()
    return resp.json()


def sf(val, default: float = 0.0):
    try:
        return float(val) if val not in (None, "", "-.--", "--", ".---", "Inf", "inf") else default
    except (ValueError, TypeError):
        return default


def si(val, default: int = 0) -> int:
    try:
        return int(val) if val not in (None, "") else default
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
    cur = conn.cursor()

    for league_id in (103, 104):  # AL, NL
        data = api_get(session, "/standings", leagueId=league_id, season=SEASON,
                       standingsTypes="regularSeason", hydrate="team(division)")

        for division in data.get("records", []):
            for rec in division.get("teamRecords", []):
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
                """, (today, SEASON, team_abbr, team_id, GAME_TYPE, div_name, wins, losses, gb))

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
                    if split.get("type") == "lastTen":
                        l10   = split.get("wins", 0)
                    elif split.get("type") == "home":
                        home_w = split.get("wins", 0)
                    elif split.get("type") == "away":
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
                """, (today, SEASON, team_abbr, team_id, GAME_TYPE, div_name, wins, losses, win_pct,
                      gb, rs, ra, streak, l10, home_w, away_w))

                if team_id == TEAM_ID:
                    log.info("SEA: %s-%s  GB=%.1f  Streak=%+d", wins, losses, gb, streak)

    conn.commit()
    cur.close()


# ── Player Stats ──────────────────────────────────────────────────────────────
def get_all_teams(session: requests.Session) -> list[dict]:
    """Return list of {id, abbr} for all 30 MLB teams."""
    teams = []
    for league_id in (103, 104):
        data = api_get(session, "/standings", leagueId=league_id, season=SEASON,
                       standingsTypes="regularSeason", hydrate="team")
        for div in data.get("records", []):
            for rec in div.get("teamRecords", []):
                t = rec.get("team", {})
                teams.append({"id": t.get("id"), "abbr": t.get("abbreviation", "UNK")})
    return teams


def get_roster(session: requests.Session, team_id: int = TEAM_ID) -> list:
    data = api_get(session, f"/teams/{team_id}/roster",
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


def upsert_batter(cur, today, player_id, name, pos, stat, team_abbr=TEAM_ABBR) -> None:
    avg = sf(stat.get("avg"))
    slg = sf(stat.get("slg"))
    cur.execute("""
        INSERT INTO player_batting
            (date, season, player, player_id, team, game_type, position,
             games_played, at_bats, hits, home_runs, rbi, runs,
             walks, strikeouts, stolen_bases, doubles, triples,
             avg, obp, slg, ops, babip, iso)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (date, player_id, season, game_type) DO UPDATE SET
            games_played=EXCLUDED.games_played, at_bats=EXCLUDED.at_bats,
            hits=EXCLUDED.hits, home_runs=EXCLUDED.home_runs,
            rbi=EXCLUDED.rbi, runs=EXCLUDED.runs,
            walks=EXCLUDED.walks, strikeouts=EXCLUDED.strikeouts,
            stolen_bases=EXCLUDED.stolen_bases, doubles=EXCLUDED.doubles,
            triples=EXCLUDED.triples, avg=EXCLUDED.avg, obp=EXCLUDED.obp,
            slg=EXCLUDED.slg, ops=EXCLUDED.ops, babip=EXCLUDED.babip,
            iso=EXCLUDED.iso
    """, (
        today, SEASON, name, player_id, team_abbr, GAME_TYPE, pos,
        int(sf(stat.get("gamesPlayed"))), int(sf(stat.get("atBats"))),
        int(sf(stat.get("hits"))), int(sf(stat.get("homeRuns"))),
        int(sf(stat.get("rbi"))), int(sf(stat.get("runs"))),
        int(sf(stat.get("baseOnBalls"))), int(sf(stat.get("strikeOuts"))),
        int(sf(stat.get("stolenBases"))), int(sf(stat.get("doubles"))),
        int(sf(stat.get("triples"))),
        avg, sf(stat.get("obp")), slg, sf(stat.get("ops")),
        sf(stat.get("babip")), round(slg - avg, 3),
    ))


def upsert_pitcher(cur, today, player_id, name, pos, stat, team_abbr=TEAM_ABBR) -> None:
    ip     = sf(stat.get("inningsPitched"))
    hr     = sf(stat.get("homeRunsAllowed", stat.get("homeRuns")))
    bb     = sf(stat.get("baseOnBalls"))
    so     = sf(stat.get("strikeOuts"))
    fip    = round(((13 * hr + 3 * bb - 2 * so) / ip) + 3.10, 2) if ip > 0 else None
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
            earned_runs=EXCLUDED.earned_runs, era=EXCLUDED.era,
            whip=EXCLUDED.whip, k9=EXCLUDED.k9, bb9=EXCLUDED.bb9,
            hr9=EXCLUDED.hr9, fip=EXCLUDED.fip
    """, (
        today, SEASON, name, player_id, team_abbr, GAME_TYPE, pos,
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
    teams = get_all_teams(session)
    log.info("Scraping player stats for %d teams", len(teams))
    cur = conn.cursor()
    total = 0

    for tm in teams:
        team_id, team_abbr = tm["id"], tm["abbr"]
        try:
            roster = get_roster(session, team_id)
        except Exception as e:
            log.warning("Roster failed for %s: %s", team_abbr, e)
            continue

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
                        upsert_pitcher(cur, today, pid, name, pos_code, stat, team_abbr)
                        count += 1
                else:
                    stat = get_hitting_stats(session, pid)
                    if stat:
                        upsert_batter(cur, today, pid, name, pos_code, stat, team_abbr)
                        count += 1
                time.sleep(0.25)
            except Exception as e:
                log.warning("Stats failed for %s (%s): %s", name, team_abbr, e)

        conn.commit()
        total += count
        log.info("  %s: %d/%d players", team_abbr, count, len(roster))

    cur.close()
    log.info("Players total: %d updated across %d teams", total, len(teams))


# ── Game Recap ────────────────────────────────────────────────────────────────
_team_abbr_map: dict = {}


def get_team_abbr_map(session: requests.Session) -> dict:
    global _team_abbr_map
    if not _team_abbr_map:
        data = api_get(session, "/teams", sportId=1)
        _team_abbr_map = {t["id"]: t.get("abbreviation", "UNK") for t in data.get("teams", [])}
    return _team_abbr_map


def parse_batting_lines(box: dict, abbr_map: dict) -> list:
    rows = []
    for side in ("home", "away"):
        team_data = box["teams"][side]
        abbr      = abbr_map.get(team_data["team"]["id"], "UNK")
        players   = team_data.get("players", {})
        for pid in team_data.get("batters", []):
            p     = players.get(f"ID{pid}", {})
            st    = p.get("stats", {}).get("batting", {})
            order = p.get("battingOrder")
            if not st and order is None:
                continue
            rows.append({
                "player_id": pid,
                "player":    p.get("person", {}).get("fullName", "Unknown"),
                "team":      abbr,
                "batting_order": int(order) if order else None,
                "ab": si(st.get("atBats")),   "r":  si(st.get("runs")),
                "h":  si(st.get("hits")),      "doubles": si(st.get("doubles")),
                "triples": si(st.get("triples")), "hr": si(st.get("homeRuns")),
                "rbi": si(st.get("rbi")),      "bb": si(st.get("baseOnBalls")),
                "so": si(st.get("strikeOuts")), "sb": si(st.get("stolenBases")),
                "lob": si(st.get("leftOnBase")),
            })
    return rows


def parse_pitching_lines(box: dict, abbr_map: dict, decisions: dict) -> list:
    winner_id = decisions.get("winner", {}).get("id")
    loser_id  = decisions.get("loser",  {}).get("id")
    save_id   = decisions.get("save",   {}).get("id")
    rows = []
    for side in ("home", "away"):
        team_data = box["teams"][side]
        abbr      = abbr_map.get(team_data["team"]["id"], "UNK")
        players   = team_data.get("players", {})
        for order, pid in enumerate(team_data.get("pitchers", []), start=1):
            p  = players.get(f"ID{pid}", {})
            st = p.get("stats", {}).get("pitching", {})
            note = ("W" if pid == winner_id else
                    "L" if pid == loser_id  else
                    "S" if pid == save_id   else None)
            rows.append({
                "player_id":  pid,
                "player":     p.get("person", {}).get("fullName", "Unknown"),
                "team":       abbr,
                "pitch_order": order,
                "ip":  st.get("inningsPitched", "0.0"),
                "h":   si(st.get("hits")),         "r":  si(st.get("runs")),
                "er":  si(st.get("earnedRuns")),   "bb": si(st.get("baseOnBalls")),
                "so":  si(st.get("strikeOuts")),   "hr": si(st.get("homeRuns")),
                "pitches": si(st.get("pitchesThrown")) if st.get("pitchesThrown") else None,
                "strikes":  si(st.get("strikes"))  if st.get("strikes")  else None,
                "era":  sf(st.get("era"), None),
                "note": note,
            })
    return rows


def parse_linescore(ls: dict, home_abbr: str, away_abbr: str) -> list:
    rows = []
    for inning_data in ls.get("innings", []):
        num = inning_data.get("num")
        for side, abbr in (("home", home_abbr), ("away", away_abbr)):
            half = inning_data.get(side, {})
            if not half or "runs" not in half:
                continue
            rows.append({
                "inning": num, "team": abbr,
                "runs":   si(half.get("runs")),
                "hits":   si(half.get("hits")),
                "errors": si(half.get("errors")),
            })
    return rows


def upsert_game_recap(cur, gamepk: int, game_entry: dict, box: dict, ls: dict,
                      abbr_map: dict, decisions: dict, game_number: int) -> None:
    teams_sched = game_entry.get("teams", {})
    home_id   = teams_sched.get("home", {}).get("team", {}).get("id")
    away_id   = teams_sched.get("away", {}).get("team", {}).get("id")
    home_abbr = abbr_map.get(home_id, "UNK")
    away_abbr = abbr_map.get(away_id, "UNK")
    sea_is_home = (home_id == TEAM_ID)
    opponent  = abbr_map.get(away_id if sea_is_home else home_id, "UNK")

    ls_totals  = ls.get("teams", {})
    home_score = ls_totals.get("home", {}).get("runs")
    away_score = ls_totals.get("away", {}).get("runs")
    sea_score  = home_score if sea_is_home else away_score
    opp_score  = away_score if sea_is_home else home_score
    result = ("W" if sea_score > opp_score else "L") \
             if (sea_score is not None and opp_score is not None) else None

    game_date    = datetime.date.fromisoformat(game_entry.get("gameDate", "")[:10])
    doubleheader = game_entry.get("doubleHeader", "N")
    status       = game_entry.get("status", {}).get("abstractGameState", "Unknown")

    cur.execute("""
        INSERT INTO games
            (gamepk, date, season, game_number, game_type, doubleheader,
             home_team, away_team, home_score, away_score,
             sea_score, opp_score, opponent, result, venue,
             winning_pitcher, losing_pitcher, save_pitcher, status)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (gamepk) DO UPDATE SET
            home_score=EXCLUDED.home_score, away_score=EXCLUDED.away_score,
            sea_score=EXCLUDED.sea_score, opp_score=EXCLUDED.opp_score,
            result=EXCLUDED.result, winning_pitcher=EXCLUDED.winning_pitcher,
            losing_pitcher=EXCLUDED.losing_pitcher, save_pitcher=EXCLUDED.save_pitcher,
            status=EXCLUDED.status
    """, (
        gamepk, game_date, SEASON, game_number, GAME_TYPE, doubleheader,
        home_abbr, away_abbr, home_score, away_score,
        sea_score, opp_score, opponent, result,
        game_entry.get("venue", {}).get("name"),
        decisions.get("winner", {}).get("fullName"),
        decisions.get("loser",  {}).get("fullName"),
        decisions.get("save",   {}).get("fullName"),
        status,
    ))

    batting_rows  = parse_batting_lines(box, abbr_map)
    pitching_rows = parse_pitching_lines(box, abbr_map, decisions)
    ls_rows       = parse_linescore(ls, home_abbr, away_abbr)

    for r in batting_rows:
        cur.execute("""
            INSERT INTO game_batting_lines
                (gamepk, player_id, player, team, batting_order,
                 ab, r, h, doubles, triples, hr, rbi, bb, so, sb, lob)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (gamepk, player_id) DO UPDATE SET
                ab=EXCLUDED.ab, r=EXCLUDED.r, h=EXCLUDED.h,
                doubles=EXCLUDED.doubles, triples=EXCLUDED.triples,
                hr=EXCLUDED.hr, rbi=EXCLUDED.rbi, bb=EXCLUDED.bb,
                so=EXCLUDED.so, sb=EXCLUDED.sb, lob=EXCLUDED.lob
        """, (gamepk, r["player_id"], r["player"], r["team"], r["batting_order"],
              r["ab"], r["r"], r["h"], r["doubles"], r["triples"],
              r["hr"], r["rbi"], r["bb"], r["so"], r["sb"], r["lob"]))

    for r in pitching_rows:
        cur.execute("""
            INSERT INTO game_pitching_lines
                (gamepk, player_id, player, team, pitch_order,
                 ip, h, r, er, bb, so, hr, pitches, strikes, era, note)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (gamepk, player_id) DO UPDATE SET
                ip=EXCLUDED.ip, h=EXCLUDED.h, r=EXCLUDED.r, er=EXCLUDED.er,
                bb=EXCLUDED.bb, so=EXCLUDED.so, hr=EXCLUDED.hr,
                pitches=EXCLUDED.pitches, strikes=EXCLUDED.strikes,
                era=EXCLUDED.era, note=EXCLUDED.note
        """, (gamepk, r["player_id"], r["player"], r["team"], r["pitch_order"],
              r["ip"], r["h"], r["r"], r["er"], r["bb"], r["so"], r["hr"],
              r["pitches"], r["strikes"], r["era"], r["note"]))

    for r in ls_rows:
        cur.execute("""
            INSERT INTO game_linescore (gamepk, inning, team, runs, hits, errors)
            VALUES (%s,%s,%s,%s,%s,%s)
            ON CONFLICT (gamepk, inning, team) DO UPDATE SET
                runs=EXCLUDED.runs, hits=EXCLUDED.hits, errors=EXCLUDED.errors
        """, (gamepk, r["inning"], r["team"], r["runs"], r["hits"], r["errors"]))


def scrape_game_recap(session: requests.Session, conn) -> None:
    today = datetime.date.today().isoformat()
    data  = api_get(session, "/schedule", teamId=TEAM_ID, date=today,
                    sportId=1, hydrate="decisions")
    dates = data.get("dates", [])
    if not dates:
        return

    abbr_map = get_team_abbr_map(session)
    cur = conn.cursor()

    for game_entry in dates[0].get("games", []):
        if game_entry.get("status", {}).get("abstractGameState") != "Final":
            continue

        gamepk = game_entry.get("gamePk")

        # Skip if we already have a completed result for this game
        cur.execute("SELECT result FROM games WHERE gamepk = %s", (gamepk,))
        row = cur.fetchone()
        if row and row[0] is not None:
            log.debug("Game recap already stored for gamePk=%s", gamepk)
            continue

        # Determine next sequential game number for this season
        cur.execute("SELECT COALESCE(MAX(game_number), 0) + 1 FROM games WHERE season = %s",
                    (SEASON,))
        game_number = cur.fetchone()[0]

        try:
            box_resp = session.get(f"{MLB_API}/game/{gamepk}/boxscore", timeout=20)
            box_resp.raise_for_status()
            box = box_resp.json()
            time.sleep(0.3)

            ls_resp = session.get(f"{MLB_API}/game/{gamepk}/linescore", timeout=20)
            ls_resp.raise_for_status()
            ls = ls_resp.json()

            upsert_game_recap(cur, gamepk, game_entry, box, ls, abbr_map,
                              game_entry.get("decisions", {}), game_number)
            conn.commit()
            log.info("Game recap stored: gamePk=%s G%03d", gamepk, game_number)
        except Exception as e:
            log.warning("Game recap failed gamePk=%s: %s", gamepk, e)
            conn.rollback()

    cur.close()


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


PLAYER_SCRAPE_INTERVAL = int(os.getenv("PLAYER_SCRAPE_INTERVAL", "43200"))  # 12 hours


# ── Main ─────────────────────────────────────────────────────────────────────
def main() -> None:
    log.info("MLB Stats Tracker starting — Team=%s  Season=%s", TEAM_ABBR, SEASON)
    conn = wait_for_db()
    session = make_session()
    last_player_scrape = 0.0

    while True:
        today = datetime.date.today()
        try:
            log.info("── Scrape cycle %s ──", today)
            scrape_standings(session, conn, today)
            now = time.time()
            if now - last_player_scrape >= PLAYER_SCRAPE_INTERVAL:
                scrape_players(session, conn, today)
                last_player_scrape = now
            else:
                remaining = PLAYER_SCRAPE_INTERVAL - (now - last_player_scrape)
                log.info("Player scrape skipped — next in %.0f min", remaining / 60)
            scrape_game_recap(session, conn)
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
