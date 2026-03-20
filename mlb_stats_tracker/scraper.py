"""
MLB Stats Tracker — Seattle Mariners (Team ID: 136)

Uses the official MLB Stats API (free, no auth required).
Scrapes roster + player stats after each game and exposes Prometheus metrics.

Endpoints used:
  GET /teams/136/roster?rosterType=active&season=YYYY
  GET /people/{id}/stats?stats=season&season=YYYY&group=hitting|pitching
  GET /standings?leagueId=103&season=YYYY&standingsTypes=regularSeason
  GET /schedule?teamId=136&date=TODAY&sportId=1
"""

import datetime
import logging
import os
import time
from typing import Optional

import requests
from prometheus_client import Counter, Gauge, Info, start_http_server

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
TEAM_ID       = int(os.getenv("TEAM_ID", "136"))          # 136 = Seattle Mariners
TEAM_ABBR     = os.getenv("TEAM_ABBR", "SEA")
SEASON        = os.getenv("SEASON", str(datetime.date.today().year))
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "1800"))   # 30 min default
METRICS_PORT  = int(os.getenv("METRICS_PORT", "8001"))
MLB_API       = "https://statsapi.mlb.com/api/v1"

PITCHER_POSITIONS = {"P", "SP", "RP", "CP"}

# ── Prometheus Metrics ────────────────────────────────────────────────────────
_P = ["team", "player", "player_id", "position"]   # player labels
_T = ["team", "team_id", "division"]               # team labels

# Batting
bat_avg    = Gauge("mlb_player_batting_avg",         "Batting average",              _P)
bat_obp    = Gauge("mlb_player_obp",                 "On-base percentage",           _P)
bat_slg    = Gauge("mlb_player_slg",                 "Slugging percentage",          _P)
bat_ops    = Gauge("mlb_player_ops",                 "OPS (OBP + SLG)",              _P)
bat_hr     = Gauge("mlb_player_home_runs_total",     "Home runs (season)",           _P)
bat_rbi    = Gauge("mlb_player_rbi_total",           "RBIs (season)",                _P)
bat_hits   = Gauge("mlb_player_hits_total",          "Hits (season)",                _P)
bat_ab     = Gauge("mlb_player_at_bats_total",       "At bats (season)",             _P)
bat_runs   = Gauge("mlb_player_runs_total",          "Runs scored (season)",         _P)
bat_bb     = Gauge("mlb_player_walks_total",         "Walks (season)",               _P)
bat_k      = Gauge("mlb_player_strikeouts_total",    "Strikeouts (season)",          _P)
bat_sb     = Gauge("mlb_player_stolen_bases_total",  "Stolen bases (season)",        _P)
bat_2b     = Gauge("mlb_player_doubles_total",       "Doubles (season)",             _P)
bat_3b     = Gauge("mlb_player_triples_total",       "Triples (season)",             _P)
bat_games  = Gauge("mlb_player_games_played_total",  "Games played (batters)",       _P)
bat_iso    = Gauge("mlb_player_iso",                 "Isolated power (SLG - AVG)",   _P)
bat_babip  = Gauge("mlb_player_babip",               "BABIP",                        _P)

# Pitching
pit_era    = Gauge("mlb_pitcher_era",                "ERA",                          _P)
pit_whip   = Gauge("mlb_pitcher_whip",               "WHIP",                        _P)
pit_wins   = Gauge("mlb_pitcher_wins_total",         "Wins (season)",                _P)
pit_losses = Gauge("mlb_pitcher_losses_total",       "Losses (season)",              _P)
pit_saves  = Gauge("mlb_pitcher_saves_total",        "Saves (season)",               _P)
pit_holds  = Gauge("mlb_pitcher_holds_total",        "Holds (season)",               _P)
pit_so     = Gauge("mlb_pitcher_strikeouts_total",   "Strikeouts (season)",          _P)
pit_bb     = Gauge("mlb_pitcher_walks_total",        "Walks allowed (season)",       _P)
pit_ip     = Gauge("mlb_pitcher_innings_pitched",    "Innings pitched (season)",     _P)
pit_k9     = Gauge("mlb_pitcher_k9",                 "K/9",                          _P)
pit_bb9    = Gauge("mlb_pitcher_bb9",                "BB/9",                         _P)
pit_hr9    = Gauge("mlb_pitcher_hr9",                "HR/9",                         _P)
pit_games  = Gauge("mlb_pitcher_games_total",        "Games pitched (season)",       _P)
pit_qs     = Gauge("mlb_pitcher_quality_starts_total","Quality starts",              _P)
pit_fip    = Gauge("mlb_pitcher_fip",                "FIP (fielding indep. pitching)",_P)

# Team
tm_wins    = Gauge("mlb_team_wins_total",            "Team wins",                    _T)
tm_losses  = Gauge("mlb_team_losses_total",          "Team losses",                  _T)
tm_pct     = Gauge("mlb_team_win_pct",               "Win percentage",               _T)
tm_gb      = Gauge("mlb_team_games_behind",          "Games behind leader (0=1st)", _T)
tm_rs      = Gauge("mlb_team_runs_scored_total",     "Runs scored (season)",         _T)
tm_ra      = Gauge("mlb_team_runs_allowed_total",    "Runs allowed (season)",        _T)
tm_streak  = Gauge("mlb_team_streak",                "Streak: +N=wins, -N=losses",  _T)
tm_home_w  = Gauge("mlb_team_home_wins_total",       "Home wins",                    _T)
tm_away_w  = Gauge("mlb_team_away_wins_total",       "Away wins",                    _T)
tm_l10     = Gauge("mlb_team_last10_wins",           "Wins in last 10 games",        _T)

# Scraper health
scrape_errors = Counter("mlb_scrape_errors_total",   "Scrape errors", ["error_type"])
scrapes_total = Counter("mlb_scrapes_total",          "Total scrape cycles")
last_scrape   = Gauge("mlb_last_scrape_timestamp_seconds", "Last successful scrape timestamp")
players_scraped = Gauge("mlb_players_scraped_total", "Number of players scraped last cycle")


# ── HTTP Session ──────────────────────────────────────────────────────────────
def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": "MLBStatsTracker/1.0 (personal monitoring project)",
        "Accept": "application/json",
    })
    return s


# ── MLB API Helpers ───────────────────────────────────────────────────────────
def api_get(session: requests.Session, path: str, **params) -> dict:
    url = f"{MLB_API}{path}"
    resp = session.get(url, params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()


def get_roster(session: requests.Session) -> list[dict]:
    data = api_get(session, f"/teams/{TEAM_ID}/roster",
                   rosterType="active", season=SEASON)
    return data.get("roster", [])


def get_hitting_stats(session: requests.Session, person_id: int) -> Optional[dict]:
    data = api_get(session, f"/people/{person_id}/stats",
                   stats="season", season=SEASON, group="hitting", sportId=1)
    stats = data.get("stats") or []
    if not stats:
        return None
    splits = stats[0].get("splits", [])
    return splits[0].get("stat") if splits else None


def get_pitching_stats(session: requests.Session, person_id: int) -> Optional[dict]:
    data = api_get(session, f"/people/{person_id}/stats",
                   stats="season", season=SEASON, group="pitching", sportId=1)
    stats = data.get("stats") or []
    if not stats:
        return None
    splits = stats[0].get("splits", [])
    return splits[0].get("stat") if splits else None


def get_standings(session: requests.Session) -> Optional[dict]:
    """Return the Mariners' team record from AL standings."""
    data = api_get(session, "/standings",
                   leagueId=103, season=SEASON, standingsTypes="regularSeason")
    for division in data.get("records", []):
        for rec in division.get("teamRecords", []):
            if rec.get("team", {}).get("id") == TEAM_ID:
                div_name = division.get("division", {}).get("nameShort", "AL West")
                return rec, div_name
    return None, None


def get_todays_game_state(session: requests.Session) -> Optional[str]:
    """Return 'Preview' | 'Live' | 'Final' | None for today's game."""
    today = datetime.date.today().isoformat()
    data = api_get(session, "/schedule", teamId=TEAM_ID, date=today, sportId=1)
    dates = data.get("dates", [])
    if not dates:
        return None
    games = dates[0].get("games", [])
    if not games:
        return None
    return games[0].get("status", {}).get("abstractGameState")


def safe_float(val, default: float = 0.0) -> float:
    """Parse stat values that may be strings like '0.287' or ints."""
    try:
        return float(val) if val not in (None, "", "-.--", "--", ".---") else default
    except (ValueError, TypeError):
        return default


# ── Metric Updaters ───────────────────────────────────────────────────────────
def update_batter(labels: dict, stat: dict) -> None:
    avg = safe_float(stat.get("avg"))
    slg = safe_float(stat.get("slg"))

    bat_avg.labels(**labels).set(avg)
    bat_obp.labels(**labels).set(safe_float(stat.get("obp")))
    bat_slg.labels(**labels).set(slg)
    bat_ops.labels(**labels).set(safe_float(stat.get("ops")))
    bat_hr.labels(**labels).set(safe_float(stat.get("homeRuns")))
    bat_rbi.labels(**labels).set(safe_float(stat.get("rbi")))
    bat_hits.labels(**labels).set(safe_float(stat.get("hits")))
    bat_ab.labels(**labels).set(safe_float(stat.get("atBats")))
    bat_runs.labels(**labels).set(safe_float(stat.get("runs")))
    bat_bb.labels(**labels).set(safe_float(stat.get("baseOnBalls")))
    bat_k.labels(**labels).set(safe_float(stat.get("strikeOuts")))
    bat_sb.labels(**labels).set(safe_float(stat.get("stolenBases")))
    bat_2b.labels(**labels).set(safe_float(stat.get("doubles")))
    bat_3b.labels(**labels).set(safe_float(stat.get("triples")))
    bat_games.labels(**labels).set(safe_float(stat.get("gamesPlayed")))
    bat_iso.labels(**labels).set(round(slg - avg, 3))
    bat_babip.labels(**labels).set(safe_float(stat.get("babip")))


def update_pitcher(labels: dict, stat: dict) -> None:
    pit_era.labels(**labels).set(safe_float(stat.get("era")))
    pit_whip.labels(**labels).set(safe_float(stat.get("whip")))
    pit_wins.labels(**labels).set(safe_float(stat.get("wins")))
    pit_losses.labels(**labels).set(safe_float(stat.get("losses")))
    pit_saves.labels(**labels).set(safe_float(stat.get("saves")))
    pit_holds.labels(**labels).set(safe_float(stat.get("holds")))
    pit_so.labels(**labels).set(safe_float(stat.get("strikeOuts")))
    pit_bb.labels(**labels).set(safe_float(stat.get("baseOnBalls")))
    pit_ip.labels(**labels).set(safe_float(stat.get("inningsPitched")))
    pit_k9.labels(**labels).set(safe_float(stat.get("strikeoutsPer9Inn")))
    pit_bb9.labels(**labels).set(safe_float(stat.get("walksPer9Inn")))
    pit_hr9.labels(**labels).set(safe_float(stat.get("homeRunsPer9")))
    pit_games.labels(**labels).set(safe_float(stat.get("gamesPitched")))
    pit_qs.labels(**labels).set(safe_float(stat.get("qualityStarts")))

    # FIP = ((13*HR + 3*BB - 2*SO) / IP) + FIP_constant (~3.10)
    hr  = safe_float(stat.get("homeRunsAllowed", stat.get("homeRuns")))
    bb  = safe_float(stat.get("baseOnBalls"))
    so  = safe_float(stat.get("strikeOuts"))
    ip  = safe_float(stat.get("inningsPitched"))
    fip = round(((13 * hr + 3 * bb - 2 * so) / ip) + 3.10, 2) if ip > 0 else 0.0
    pit_fip.labels(**labels).set(fip)


def update_team(record: dict, div_name: str) -> None:
    labels = {
        "team": TEAM_ABBR,
        "team_id": str(TEAM_ID),
        "division": div_name,
    }

    tm_wins.labels(**labels).set(record.get("wins", 0))
    tm_losses.labels(**labels).set(record.get("losses", 0))
    tm_pct.labels(**labels).set(safe_float(record.get("winningPercentage")))

    gb_raw = record.get("gamesBack", "0")
    gb = 0.0 if gb_raw in ("-", "", None) else safe_float(gb_raw)
    tm_gb.labels(**labels).set(gb)

    rs = safe_float(record.get("runsScored"))
    ra = safe_float(record.get("runsAllowed"))
    tm_rs.labels(**labels).set(rs)
    tm_ra.labels(**labels).set(ra)

    # Streak: convert "W3" → +3, "L2" → -2
    streak_str = record.get("streak", {}).get("streakCode", "W0")
    try:
        streak_val = int(streak_str[1:]) * (1 if streak_str[0] == "W" else -1)
    except (ValueError, IndexError):
        streak_val = 0
    tm_streak.labels(**labels).set(streak_val)

    # Last 10
    l10 = record.get("records", {}).get("splitRecords", [])
    for split in l10:
        if split.get("type") == "lastTen":
            tm_l10.labels(**labels).set(split.get("wins", 0))
        if split.get("type") == "home":
            tm_home_w.labels(**labels).set(split.get("wins", 0))
        if split.get("type") == "away":
            tm_away_w.labels(**labels).set(split.get("wins", 0))


# ── Main Scrape Cycle ─────────────────────────────────────────────────────────
def scrape(session: requests.Session) -> None:
    scrapes_total.inc()
    log.info("Starting scrape cycle — Season %s", SEASON)

    # ── Standings ─────────────────────────────────────────────────────────
    try:
        record, div_name = get_standings(session)
        if record:
            update_team(record, div_name or "AL West")
            log.info("Team record: %s-%s (GB: %s)",
                     record.get("wins"), record.get("losses"), record.get("gamesBack"))
    except Exception as e:
        scrape_errors.labels(error_type="standings").inc()
        log.warning("Standings fetch failed: %s", e)

    # ── Roster + Player Stats ──────────────────────────────────────────────
    try:
        roster = get_roster(session)
        log.info("Roster size: %d players", len(roster))
    except Exception as e:
        scrape_errors.labels(error_type="roster").inc()
        log.error("Roster fetch failed: %s", e)
        return

    count = 0
    for entry in roster:
        person    = entry.get("person", {})
        pid       = person.get("id")
        name      = person.get("fullName", "Unknown")
        pos_code  = entry.get("position", {}).get("code", "")
        is_pitcher = pos_code in PITCHER_POSITIONS

        labels = {
            "team":      TEAM_ABBR,
            "player":    name,
            "player_id": str(pid),
            "position":  pos_code,
        }

        try:
            if is_pitcher:
                stat = get_pitching_stats(session, pid)
                if stat:
                    update_pitcher(labels, stat)
                    log.debug("  %-25s (P)  ERA=%-5s  WHIP=%s",
                              name, stat.get("era", "-"), stat.get("whip", "-"))
            else:
                stat = get_hitting_stats(session, pid)
                if stat:
                    update_batter(labels, stat)
                    log.debug("  %-25s (%s)  AVG=%-5s  OPS=%s",
                              name, pos_code, stat.get("avg", "-"), stat.get("ops", "-"))
            count += 1
            time.sleep(0.2)   # be polite to the API
        except Exception as e:
            scrape_errors.labels(error_type="player_stats").inc()
            log.warning("  Stats fetch failed for %s: %s", name, e)

    players_scraped.set(count)
    last_scrape.set(time.time())
    log.info("Scrape complete — %d/%d players updated", count, len(roster))


# ── Adaptive Sleep ────────────────────────────────────────────────────────────
def sleep_until_next_scrape(session: requests.Session) -> None:
    """
    Sleep smartly:
    - If a game just went Final → scrape again in 5 min to catch box score updates
    - If game is Live → poll every 10 min
    - Otherwise → wait POLL_INTERVAL
    """
    try:
        state = get_todays_game_state(session)
        if state == "Final":
            log.info("Game is Final — will re-scrape in 5 min for box score updates")
            time.sleep(300)
            return
        elif state == "Live":
            log.info("Game is Live — polling in 10 min")
            time.sleep(600)
            return
    except Exception:
        pass

    log.info("Sleeping %ds until next scrape", POLL_INTERVAL)
    time.sleep(POLL_INTERVAL)


# ── Entry Point ───────────────────────────────────────────────────────────────
def main() -> None:
    log.info("MLB Stats Tracker starting")
    log.info("  Team:     %s (ID: %d)", TEAM_ABBR, TEAM_ID)
    log.info("  Season:   %s", SEASON)
    log.info("  Interval: %ds", POLL_INTERVAL)
    log.info("  Metrics:  http://0.0.0.0:%d/metrics", METRICS_PORT)

    start_http_server(METRICS_PORT)
    session = make_session()

    while True:
        try:
            scrape(session)
        except Exception as e:
            scrape_errors.labels(error_type="unexpected").inc()
            log.exception("Unexpected error in scrape cycle: %s", e)
        sleep_until_next_scrape(session)


if __name__ == "__main__":
    main()
