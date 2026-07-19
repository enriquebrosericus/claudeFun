#!/usr/bin/env python3
"""
Minimal backend for the *alternate* MLB frontend.

Reuses the query shapes from ../../web/app.py but only the handful of endpoints
the starter Teams page needs. Serves the static UI from ./static on the same
origin (no CORS). Extend by copying more endpoints out of web/app.py.

Run via dev/docker-compose.yml (recommended) or locally:
    DB_HOST=localhost DB_PORT=5544 python server.py
"""
from __future__ import annotations

import json
import os
from contextlib import contextmanager

import psycopg2
import psycopg2.extras
from flask import Flask, request, send_from_directory

app = Flask(__name__, static_folder="static", static_url_path="")

SEASON = int(os.environ.get("SEASON", 2026))
TEAM_ABBR = os.environ.get("TEAM_ABBR", "SEA")

_DB = dict(
    host=os.environ.get("DB_HOST", "localhost"),
    dbname=os.environ.get("DB_NAME", "mlb_stats"),
    user=os.environ.get("DB_USER", "mlb"),
    password=os.environ.get("DB_PASS", "mlbpass"),
    port=int(os.environ.get("DB_PORT", 5544)),
)


@contextmanager
def _conn():
    c = psycopg2.connect(**_DB)
    try:
        yield c
    finally:
        c.close()


def q(sql, params=None):
    with _conn() as c, c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params or ())
        return [dict(r) for r in cur.fetchall()]


def q1(sql, params=None):
    rows = q(sql, params)
    return rows[0] if rows else None


def jsn(data):
    return app.response_class(json.dumps(data, default=str), mimetype="application/json")


# ── Static UI ───────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return send_from_directory("static", "index.html")


# ── API ─────────────────────────────────────────────────────────────────────
@app.route("/api/seasons")
def api_seasons():
    return jsn([r["season"] for r in q("SELECT DISTINCT season FROM team_stats ORDER BY season DESC")])


@app.route("/api/teams/list")
def api_teams_list():
    return jsn([r["team"] for r in q("SELECT DISTINCT team FROM team_stats ORDER BY team")])


@app.route("/api/teams/summary")
def api_teams_summary():
    season = request.args.get("season", SEASON, int)
    team = request.args.get("team", TEAM_ABBR)
    return jsn(q1("""
        SELECT DISTINCT ON (team)
            wins, losses, win_pct, games_behind, streak, last10_wins,
            runs_scored, runs_allowed, home_wins, away_wins
        FROM team_stats
        WHERE team = %s AND season = %s AND game_type = 'R'
        ORDER BY team, date DESC
    """, (team, season)) or {})


@app.route("/api/teams/trends")
def api_teams_trends():
    """Everything the Teams charts need, in one call.

    Returns per-date series plus a day-over-day run-differential delta so the
    run-diff bar chart matches the shape of the original dashboard.
    """
    season = request.args.get("season", SEASON, int)
    team = request.args.get("team", TEAM_ABBR)
    rows = q("""
        SELECT date, wins, losses, win_pct, runs_scored, runs_allowed
        FROM team_stats
        WHERE team = %s AND season = %s AND game_type = 'R'
        ORDER BY date
    """, (team, season))
    gb = q("""
        SELECT date, games_behind
        FROM division_standings
        WHERE team = %s AND season = %s AND game_type = 'R'
        ORDER BY date
    """, (team, season))
    gb_by_date = {str(r["date"]): float(r["games_behind"] or 0) for r in gb}

    out = []
    prev_diff = None
    for r in rows:
        d = str(r["date"])
        rs = int(r["runs_scored"] or 0)
        ra = int(r["runs_allowed"] or 0)
        cum_diff = rs - ra
        day_diff = 0 if prev_diff is None else cum_diff - prev_diff
        prev_diff = cum_diff
        out.append({
            "date": d,
            "wins": r["wins"] or 0,
            "losses": r["losses"] or 0,
            "win_pct": float(r["win_pct"]) if r["win_pct"] is not None else None,
            "run_diff_cum": cum_diff,
            "run_diff_day": day_diff,
            "games_behind": gb_by_date.get(d),
        })
    return jsn(out)


# ── Players ───────────────────────────────────────────────────────────────────
@app.route("/api/teams/batting_leaders")
def api_teams_batting_leaders():
    season = request.args.get("season", SEASON, int)
    team = request.args.get("team", TEAM_ABBR)
    return jsn(q("""
        SELECT player_id, player, position, avg, obp, slg, ops, home_runs, rbi,
               runs, hits, stolen_bases, games_played, at_bats
        FROM (
            SELECT DISTINCT ON (player_id)
                player_id, player, position, avg, obp, slg, ops, home_runs, rbi,
                runs, hits, stolen_bases, games_played, at_bats
            FROM player_batting
            WHERE team = %s AND season = %s AND game_type = 'R' AND at_bats > 0
            ORDER BY player_id, date DESC
        ) latest
        ORDER BY ops DESC NULLS LAST
    """, (team, season)))


@app.route("/api/teams/pitching_leaders")
def api_teams_pitching_leaders():
    season = request.args.get("season", SEASON, int)
    team = request.args.get("team", TEAM_ABBR)
    return jsn(q("""
        SELECT player_id, player, position, era, whip, fip, wins, losses, saves,
               strikeouts, innings_pitched, k9, bb9, games, quality_starts
        FROM (
            SELECT DISTINCT ON (player_id)
                player_id, player, position, era, whip, fip, wins, losses, saves,
                strikeouts, innings_pitched, k9, bb9, games, quality_starts
            FROM player_pitching
            WHERE team = %s AND season = %s AND game_type = 'R' AND innings_pitched > 0
            ORDER BY player_id, date DESC
        ) latest
        ORDER BY era ASC NULLS LAST
    """, (team, season)))


@app.route("/api/players/batter_trend")
def api_players_batter_trend():
    season = request.args.get("season", SEASON, int)
    pid = request.args.get("player_id", type=int)
    return jsn(q("""
        SELECT date, avg, obp, slg, ops, home_runs, rbi, runs
        FROM player_batting
        WHERE player_id = %s AND season = %s AND game_type = 'R'
        ORDER BY date
    """, (pid, season)))


@app.route("/api/players/pitcher_trend")
def api_players_pitcher_trend():
    season = request.args.get("season", SEASON, int)
    pid = request.args.get("player_id", type=int)
    return jsn(q("""
        SELECT date, era, whip, fip, k9, bb9, strikeouts, innings_pitched
        FROM player_pitching
        WHERE player_id = %s AND season = %s AND game_type = 'R'
        ORDER BY date
    """, (pid, season)))


# ── Division race ─────────────────────────────────────────────────────────────
DIVS = ["AL East", "AL Central", "AL West", "NL East", "NL Central", "NL West"]


@app.route("/api/divisions/list")
def api_divisions_list():
    return jsn(DIVS)


@app.route("/api/divisions/all")
def api_divisions_all():
    """Standings + games-behind race + win% race for one division."""
    season = request.args.get("season", SEASON, int)
    div = request.args.get("division", "AL West")
    standings = q("""
        SELECT DISTINCT ON (team)
            team, wins, losses, games_behind,
            ROUND(wins::numeric / NULLIF(wins + losses, 0), 3) AS win_pct
        FROM division_standings
        WHERE division = %s AND season = %s AND game_type = 'R'
        ORDER BY team, date DESC
    """, (div, season))
    standings.sort(key=lambda x: (float(x.get("games_behind") or 0), -(x.get("wins") or 0)))
    race_rows = q("""
        SELECT date, team, games_behind, wins, losses
        FROM division_standings
        WHERE division = %s AND season = %s AND game_type = 'R'
        ORDER BY date
    """, (div, season))
    teams = [s["team"] for s in standings]
    dates = sorted(set(str(r["date"]) for r in race_rows))
    gb = {t: {} for t in teams}
    wp = {t: {} for t in teams}
    for r in race_rows:
        if r["team"] in gb:
            gb[r["team"]][str(r["date"])] = float(r.get("games_behind") or 0)
            w, l = r.get("wins") or 0, r.get("losses") or 0
            wp[r["team"]][str(r["date"])] = round(w / (w + l), 3) if (w + l) else None
    return jsn({
        "standings": standings,
        "dates": dates,
        "gb": {t: [gb[t].get(d) for d in dates] for t in teams},
        "wpct": {t: [wp[t].get(d) for d in dates] for t in teams},
    })


# ── Game recap ────────────────────────────────────────────────────────────────
def _pivot_linescore(rows, away_team, home_team):
    data: dict = {}
    max_inn = 0
    for r in rows:
        data.setdefault(r["team"], {})[r["inning"]] = r
        max_inn = max(max_inn, r["inning"])
    innings = list(range(1, max_inn + 1))
    out = []
    for team in [away_team, home_team]:
        row = {"team": team, "cells": [], "R": 0, "H": 0, "E": 0}
        for i in innings:
            cell = data.get(team, {}).get(i)
            if cell:
                row["cells"].append(str(cell["runs"]))
                row["R"] += cell["runs"]; row["H"] += cell["hits"]; row["E"] += cell["errors"]
            else:
                row["cells"].append("x" if team == home_team else "-")
        out.append(row)
    return {"innings": innings, "rows": out}


@app.route("/api/recap/games")
def api_recap_games():
    season = request.args.get("season", SEASON, int)
    team = request.args.get("team", "")
    where = "AND (home_team = %(t)s OR away_team = %(t)s)" if team and team != "ALL" else ""
    rows = q(f"""
        SELECT gamepk, date, home_team, away_team, doubleheader, home_score, away_score
        FROM games
        WHERE season = %(s)s AND status = 'Final' AND game_type = 'R' {where}
        ORDER BY date DESC, gamepk DESC
    """, {"s": season, "t": team})
    out = []
    for r in rows:
        d = r["date"].strftime("%b %d") if r.get("date") else "?"
        dh = " (DH)" if r.get("doubleheader") in ("Y", "S") else ""
        out.append({"gamepk": r["gamepk"],
                    "label": f"{d}{dh}  {r['away_team']} @ {r['home_team']}  ({r['away_score']}-{r['home_score']})"})
    return jsn(out)


@app.route("/api/recap/game")
def api_recap_game():
    gamepk = request.args.get("gamepk", type=int)
    game = q1("SELECT * FROM games WHERE gamepk = %s", (gamepk,))
    if not game:
        return jsn({})
    ls = q("SELECT inning, team, runs, hits, errors FROM game_linescore WHERE gamepk = %s ORDER BY inning, team", (gamepk,))
    bat = lambda tm: q("""
        SELECT player, batting_order, ab, r, h, doubles, triples, hr, rbi, bb, so, sb, lob
        FROM game_batting_lines WHERE gamepk = %s AND team = %s ORDER BY batting_order NULLS LAST
    """, (gamepk, tm))
    pit = lambda tm: q("""
        SELECT player, pitch_order, ip, h, r, er, bb, so, hr, era, note
        FROM game_pitching_lines WHERE gamepk = %s AND team = %s ORDER BY pitch_order
    """, (gamepk, tm))
    return jsn({
        "game": game,
        "linescore": _pivot_linescore(ls, game["away_team"], game["home_team"]),
        "batting": {"home": bat(game["home_team"]), "away": bat(game["away_team"])},
        "pitching": {"home": pit(game["home_team"]), "away": pit(game["away_team"])},
    })


# ── Challenges (ABS) ──────────────────────────────────────────────────────────
@app.route("/api/challenges/summary")
def api_challenges_summary():
    season = request.args.get("season", SEASON, int)
    team = request.args.get("team", "")
    where = "AND challenging_team = %(t)s" if team else ""
    return jsn(q1(f"""
        SELECT COUNT(*) AS total,
               COUNT(*) FILTER (WHERE challenge_result = 'overturned') AS overturned,
               ROUND(COUNT(*) FILTER (WHERE challenge_result = 'overturned')::numeric
                     / NULLIF(COUNT(*), 0) * 100, 1) AS overturn_rate,
               COUNT(*) FILTER (WHERE call_before = 'Ball')   AS ball_challenges,
               COUNT(*) FILTER (WHERE call_before = 'Strike') AS strike_challenges
        FROM game_challenges WHERE season = %(s)s {where}
    """, {"s": season, "t": team}) or {})


@app.route("/api/challenges/by_team")
def api_challenges_by_team():
    season = request.args.get("season", SEASON, int)
    return jsn(q("""
        SELECT challenging_team AS team, COUNT(*) AS total,
               COUNT(*) FILTER (WHERE challenge_result = 'overturned') AS overturned,
               ROUND(COUNT(*) FILTER (WHERE challenge_result = 'overturned')::numeric
                     / NULLIF(COUNT(*), 0) * 100, 1) AS overturn_rate
        FROM game_challenges WHERE season = %s AND challenging_team IS NOT NULL
        GROUP BY challenging_team ORDER BY total DESC
    """, (season,)))


@app.route("/api/challenges/trend")
def api_challenges_trend():
    season = request.args.get("season", SEASON, int)
    team = request.args.get("team", "")
    where = "AND challenging_team = %(t)s" if team else ""
    return jsn(q(f"""
        SELECT date, COUNT(*) AS total,
               COUNT(*) FILTER (WHERE challenge_result = 'overturned') AS overturned
        FROM game_challenges WHERE season = %(s)s {where}
        GROUP BY date ORDER BY date
    """, {"s": season, "t": team}))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8090)),
            debug=os.environ.get("DEBUG", "true").lower() == "true")
