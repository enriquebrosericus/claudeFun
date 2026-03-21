#!/usr/bin/env python3
"""
Backfill 2025 Mariners player stats (game-by-game progression).

Fetches each player's game log from the MLB Stats API, accumulates counting
stats game-by-game, and outputs OpenMetrics format for promtool ingestion.

Usage:
  python3 backfill_player_stats.py [SEASON] > /tmp/player_stats_2025.om
  docker cp /tmp/player_stats_2025.om mlb_prometheus:/tmp/
  docker exec mlb_prometheus promtool tsdb create-blocks-from openmetrics \
      /tmp/player_stats_2025.om /prometheus
  docker restart mlb_prometheus
"""

import datetime
import sys
import time

import requests

SEASON    = sys.argv[1] if len(sys.argv) > 1 else "2025"
TEAM_ID   = 136          # Seattle Mariners
TEAM_ABBR = "SEA"
BASE      = "https://statsapi.mlb.com/api/v1"

session = requests.Session()
session.headers.update({
    "User-Agent": "MLBPlayerBackfill/1.0 (personal project)",
    "Accept": "application/json",
})

# ── Helpers ───────────────────────────────────────────────────────────────────

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
    """Convert "6.2" (6⅔ innings) to total outs (20)."""
    try:
        s = str(ip_str)
        whole, frac = s.split(".")
        return int(whole) * 3 + int(frac)
    except Exception:
        return 0


def thirds_to_ip(thirds: int) -> float:
    """Convert total outs back to inningsPitched float (20 → 6.2)."""
    return round(thirds // 3 + (thirds % 3) / 10, 1)


def game_timestamp(date_str: str) -> int:
    """Return Unix timestamp for 11:30 PM on game date."""
    dt = datetime.datetime.strptime(date_str, "%Y-%m-%d").replace(hour=23, minute=30)
    return int(dt.timestamp())


# ── Roster ────────────────────────────────────────────────────────────────────

def get_roster():
    data = api_get(f"/teams/{TEAM_ID}/roster", rosterType="active", season=SEASON)
    return data.get("roster", [])


# ── OpenMetrics output ────────────────────────────────────────────────────────

METRIC_DEFS = {}   # name → (help, type)

def define(name, help_text, metric_type="gauge"):
    METRIC_DEFS[name] = (help_text, metric_type)

define("mlb_player_batting_avg",         "Season-to-date batting average")
define("mlb_player_obp",                 "Season-to-date on-base percentage")
define("mlb_player_slg",                 "Season-to-date slugging percentage")
define("mlb_player_ops",                 "Season-to-date OPS")
define("mlb_player_babip",               "Season-to-date BABIP")
define("mlb_player_iso",                 "Season-to-date ISO (SLG - AVG)")
define("mlb_player_home_runs_total",     "Cumulative home runs")
define("mlb_player_rbi_total",           "Cumulative RBIs")
define("mlb_player_hits_total",          "Cumulative hits")
define("mlb_player_at_bats_total",       "Cumulative at bats")
define("mlb_player_runs_total",          "Cumulative runs scored")
define("mlb_player_walks_total",         "Cumulative walks")
define("mlb_player_strikeouts_total",    "Cumulative strikeouts (batter)")
define("mlb_player_stolen_bases_total",  "Cumulative stolen bases")
define("mlb_player_doubles_total",       "Cumulative doubles")
define("mlb_player_triples_total",       "Cumulative triples")
define("mlb_player_games_played_total",  "Cumulative games played (batter)")
define("mlb_pitcher_era",                "Season-to-date ERA")
define("mlb_pitcher_whip",               "Season-to-date WHIP")
define("mlb_pitcher_k9",                 "Season-to-date K/9")
define("mlb_pitcher_bb9",                "Season-to-date BB/9")
define("mlb_pitcher_hr9",                "Season-to-date HR/9")
define("mlb_pitcher_fip",                "Season-to-date FIP")
define("mlb_pitcher_strikeouts_total",   "Cumulative strikeouts")
define("mlb_pitcher_walks_total",        "Cumulative walks allowed")
define("mlb_pitcher_innings_pitched",    "Cumulative innings pitched")
define("mlb_pitcher_wins_total",         "Cumulative wins")
define("mlb_pitcher_losses_total",       "Cumulative losses")
define("mlb_pitcher_saves_total",        "Cumulative saves")
define("mlb_pitcher_holds_total",        "Cumulative holds")
define("mlb_pitcher_games_total",        "Cumulative games pitched")
define("mlb_pitcher_quality_starts_total", "Cumulative quality starts")
define("mlb_pitcher_home_runs_allowed",  "Cumulative HR allowed")
define("mlb_pitcher_earned_runs_total",  "Cumulative earned runs")


def headers() -> list[str]:
    lines = []
    for name, (help_text, mtype) in METRIC_DEFS.items():
        lines.append(f"# HELP {name} {help_text}")
        lines.append(f"# TYPE {name} {mtype}")
    return lines


def sample(name: str, labels: dict, value: float, ts: int) -> str:
    lbl = ",".join(f'{k}="{v}"' for k, v in labels.items())
    return f"{name}{{{lbl}}} {value} {ts}"


# ── Batter game log ───────────────────────────────────────────────────────────

def backfill_batter(person_id: int, name: str, pos: str) -> list[str]:
    try:
        data = api_get(f"/people/{person_id}/stats",
                       stats="gameLog", season=SEASON, group="hitting", sportId=1)
    except Exception as e:
        print(f"  SKIP {name}: {e}", file=sys.stderr)
        return []

    splits = (data.get("stats") or [{}])[0].get("splits", [])
    if not splits:
        print(f"  {name}: no hitting game log", file=sys.stderr)
        return []

    labels = {
        "team": TEAM_ABBR, "player": name,
        "player_id": str(person_id), "position": pos, "season": SEASON,
    }

    lines = []
    cum_hr = cum_rbi = cum_h = cum_ab = cum_r = cum_bb = 0
    cum_k = cum_sb = cum_2b = cum_3b = cum_g = 0

    for game in splits:
        st  = game.get("stat", {})
        ts  = game_timestamp(game.get("date", "2025-01-01"))

        # Accumulate counting stats
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

        # Rate stats (already season-to-date in game log)
        avg  = sf(st.get("avg"))
        slg  = sf(st.get("slg"))
        obp  = sf(st.get("obp"))
        ops  = sf(st.get("ops"))
        babip = sf(st.get("babip"))

        lines += [
            sample("mlb_player_batting_avg",        labels, avg,     ts),
            sample("mlb_player_obp",                labels, obp,     ts),
            sample("mlb_player_slg",                labels, slg,     ts),
            sample("mlb_player_ops",                labels, ops,     ts),
            sample("mlb_player_babip",              labels, babip,   ts),
            sample("mlb_player_iso",                labels, round(slg - avg, 3), ts),
            sample("mlb_player_home_runs_total",    labels, cum_hr,  ts),
            sample("mlb_player_rbi_total",          labels, cum_rbi, ts),
            sample("mlb_player_hits_total",         labels, cum_h,   ts),
            sample("mlb_player_at_bats_total",      labels, cum_ab,  ts),
            sample("mlb_player_runs_total",         labels, cum_r,   ts),
            sample("mlb_player_walks_total",        labels, cum_bb,  ts),
            sample("mlb_player_strikeouts_total",   labels, cum_k,   ts),
            sample("mlb_player_stolen_bases_total", labels, cum_sb,  ts),
            sample("mlb_player_doubles_total",      labels, cum_2b,  ts),
            sample("mlb_player_triples_total",      labels, cum_3b,  ts),
            sample("mlb_player_games_played_total", labels, cum_g,   ts),
        ]

    print(f"  {name:30} {cum_g:3}G  HR={cum_hr:2}  RBI={cum_rbi:3}  AVG={avg:.3f}", file=sys.stderr)
    return lines


# ── Pitcher game log ──────────────────────────────────────────────────────────

def backfill_pitcher(person_id: int, name: str, pos: str) -> list[str]:
    try:
        data = api_get(f"/people/{person_id}/stats",
                       stats="gameLog", season=SEASON, group="pitching", sportId=1)
    except Exception as e:
        print(f"  SKIP {name}: {e}", file=sys.stderr)
        return []

    splits = (data.get("stats") or [{}])[0].get("splits", [])
    if not splits:
        print(f"  {name}: no pitching game log", file=sys.stderr)
        return []

    labels = {
        "team": TEAM_ABBR, "player": name,
        "player_id": str(person_id), "position": pos, "season": SEASON,
    }

    lines = []
    cum_so = cum_bb = cum_thirds = cum_w = cum_l = 0
    cum_sv = cum_hld = cum_g = cum_qs = cum_hr = cum_er = 0

    for game in splits:
        st = game.get("stat", {})
        ts = game_timestamp(game.get("date", "2025-01-01"))

        # Accumulate counting stats
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

        # Quality starts: 6+ IP and ≤ 3 ER
        ip_game = ip_to_thirds(st.get("inningsPitched", "0.0"))
        er_game = int(st.get("earnedRuns", 0))
        if ip_game >= 18 and er_game <= 3:   # 18 thirds = 6 full innings
            cum_qs += 1

        cum_ip = thirds_to_ip(cum_thirds)

        # Rate stats (season-to-date in game log)
        era  = sf(st.get("era"))
        whip = sf(st.get("whip"))
        k9   = sf(st.get("strikeoutsPer9Inn"))
        bb9  = sf(st.get("walksPer9Inn"))
        hr9  = sf(st.get("homeRunsPer9"))

        # FIP from accumulated totals
        fip = round(((13 * cum_hr + 3 * cum_bb - 2 * cum_so) / cum_ip) + 3.10, 2) \
              if cum_ip > 0 else 0.0

        lines += [
            sample("mlb_pitcher_era",                  labels, era,    ts),
            sample("mlb_pitcher_whip",                 labels, whip,   ts),
            sample("mlb_pitcher_k9",                   labels, k9,     ts),
            sample("mlb_pitcher_bb9",                  labels, bb9,    ts),
            sample("mlb_pitcher_hr9",                  labels, hr9,    ts),
            sample("mlb_pitcher_fip",                  labels, fip,    ts),
            sample("mlb_pitcher_strikeouts_total",     labels, cum_so, ts),
            sample("mlb_pitcher_walks_total",          labels, cum_bb, ts),
            sample("mlb_pitcher_innings_pitched",      labels, cum_ip, ts),
            sample("mlb_pitcher_wins_total",           labels, cum_w,  ts),
            sample("mlb_pitcher_losses_total",         labels, cum_l,  ts),
            sample("mlb_pitcher_saves_total",          labels, cum_sv, ts),
            sample("mlb_pitcher_holds_total",          labels, cum_hld, ts),
            sample("mlb_pitcher_games_total",          labels, cum_g,  ts),
            sample("mlb_pitcher_quality_starts_total", labels, cum_qs, ts),
            sample("mlb_pitcher_home_runs_allowed",    labels, cum_hr, ts),
            sample("mlb_pitcher_earned_runs_total",    labels, cum_er, ts),
        ]

    print(f"  {name:30} {cum_g:3}G  ERA={era:.2f}  SO={cum_so:3}  IP={cum_ip:.1f}", file=sys.stderr)
    return lines


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    roster = get_roster()
    print(f"Roster size: {len(roster)} players for {SEASON}", file=sys.stderr)

    all_lines = headers()
    batters = pitchers = 0

    for entry in roster:
        person  = entry.get("person", {})
        pid     = person.get("id")
        name    = person.get("fullName", "Unknown")
        pos     = entry.get("position", {})
        pos_code = pos.get("code", "")
        is_pitcher = pos.get("type") == "Pitcher"

        if is_pitcher:
            pitchers += 1
            print(f"\nPitcher: {name} ({pid})", file=sys.stderr)
            all_lines += backfill_pitcher(pid, name, pos_code)
        else:
            batters += 1
            print(f"\nBatter:  {name} ({pid})", file=sys.stderr)
            all_lines += backfill_batter(pid, name, pos_code)

        time.sleep(0.2)   # polite to the API

    all_lines.append("# EOF")
    print("\n".join(all_lines))

    print(f"\nDone: {batters} batters, {pitchers} pitchers", file=sys.stderr)


if __name__ == "__main__":
    main()
