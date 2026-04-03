#!/usr/bin/env python3
"""Flask dashboard for MLB stats tracker — replaces Grafana."""
from __future__ import annotations

import json
import os
from contextlib import contextmanager

import psycopg2
import psycopg2.extras
from flask import Flask, redirect, render_template, request, url_for

app = Flask(__name__)

# ── Config ───────────────────────────────────────────────────────────────────

SEASON = int(os.environ.get("SEASON", 2026))
TEAM_ABBR = os.environ.get("TEAM_ABBR", "SEA")

_DB = dict(
    host=os.environ.get("DB_HOST", "localhost"),
    dbname=os.environ.get("DB_NAME", "mlb_stats"),
    user=os.environ.get("DB_USER", "mlb"),
    password=os.environ.get("DB_PASS", "mlbpass"),
    port=int(os.environ.get("DB_PORT", 5433)),
)

# ── DB helpers ────────────────────────────────────────────────────────────────

@contextmanager
def _conn():
    c = psycopg2.connect(**_DB)
    try:
        yield c
    finally:
        c.close()


def q(sql, params=None):
    with _conn() as c:
        with c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params or ())
            return [dict(r) for r in cur.fetchall()]


def q1(sql, params=None):
    rows = q(sql, params)
    return rows[0] if rows else None


def jsn(data):
    return app.response_class(
        json.dumps(data, default=str), mimetype="application/json"
    )

# ── Helpers ───────────────────────────────────────────────────────────────────

def _game_label(row):
    d = row.get("date")
    if not d:
        return None
    date_str = d.strftime("%b %d")
    dh = row.get("doubleheader", "N")
    dh_str = " (DH)" if dh in ("Y", "S") else ""
    home = row.get("home_team") or ""
    away = row.get("away_team") or ""
    if home == TEAM_ABBR:
        loc = f"  vs {away or '???'}"
    else:
        loc = f"  @ {home or '???'}"
    result = row.get("result") or "?"
    sea_score = str(row.get("sea_score") if row.get("sea_score") is not None else "?")
    opp_score = str(row.get("opp_score") if row.get("opp_score") is not None else "?")
    return f"{date_str}{dh_str}{loc}  ({result} {sea_score}-{opp_score})"


def _pivot_linescore(rows, away_team, home_team):
    data: dict[str, dict[int, dict]] = {}
    max_inn = 0
    for r in rows:
        team, inn = r["team"], r["inning"]
        data.setdefault(team, {})[inn] = r
        max_inn = max(max_inn, inn)
    innings = list(range(1, max_inn + 1))
    result = []
    for team in [away_team, home_team]:
        out = {"team": team, "cells": [], "R": 0, "H": 0, "E": 0}
        for i in innings:
            cell = data.get(team, {}).get(i)
            if cell:
                out["cells"].append(str(cell["runs"]))
                out["R"] += cell["runs"]
                out["H"] += cell["hits"]
                out["E"] += cell["errors"]
            else:
                out["cells"].append("x" if team == home_team else "-")
        result.append(out)
    return {"innings": innings, "rows": result}

# ── Page routes ───────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return redirect(url_for("teams"))

@app.route("/teams")
def teams():
    return render_template("teams.html", default_season=SEASON, default_team=TEAM_ABBR)

@app.route("/players")
def players():
    return render_template("players.html", default_season=SEASON, default_team=TEAM_ABBR)

@app.route("/recap")
def recap():
    return render_template("recap.html", default_season=SEASON, default_team=TEAM_ABBR)

@app.route("/divisions")
def divisions():
    return render_template("divisions.html", default_season=SEASON, default_division="AL West")

@app.route("/challenges")
def challenges():
    return render_template("challenges.html", default_season=SEASON, default_team=TEAM_ABBR)

# ── API: Common ───────────────────────────────────────────────────────────────

@app.route("/api/seasons")
def api_seasons():
    rows = q("SELECT DISTINCT season FROM team_stats ORDER BY season DESC")
    return jsn([r["season"] for r in rows])

@app.route("/api/teams/list")
def api_teams_list():
    rows = q("SELECT DISTINCT team FROM team_stats ORDER BY team")
    return jsn([r["team"] for r in rows])

# ── API: Teams ────────────────────────────────────────────────────────────────

@app.route("/api/teams/summary")
def api_teams_summary():
    season = request.args.get("season", SEASON, int)
    team = request.args.get("team", TEAM_ABBR)
    row = q1("""
        SELECT DISTINCT ON (team)
            wins, losses, win_pct, games_behind, streak, last10_wins,
            runs_scored, runs_allowed, home_wins, away_wins
        FROM team_stats
        WHERE team = %s AND season = %s AND game_type = 'R'
        ORDER BY team, date DESC
    """, (team, season))
    return jsn(row or {})

@app.route("/api/teams/trends")
def api_teams_trends():
    season = request.args.get("season", SEASON, int)
    team = request.args.get("team", TEAM_ABBR)
    rows = q("""
        SELECT date, wins, losses, win_pct, runs_scored, runs_allowed
        FROM team_stats
        WHERE team = %s AND season = %s AND game_type = 'R'
        ORDER BY date
    """, (team, season))
    return jsn(rows)

@app.route("/api/teams/gb_trend")
def api_teams_gb_trend():
    season = request.args.get("season", SEASON, int)
    team = request.args.get("team", TEAM_ABBR)
    rows = q("""
        SELECT date, games_behind
        FROM division_standings
        WHERE team = %s AND season = %s AND game_type = 'R'
        ORDER BY date
    """, (team, season))
    return jsn(rows)

@app.route("/api/teams/batting_leaders")
def api_teams_batting_leaders():
    season = request.args.get("season", SEASON, int)
    team = request.args.get("team", TEAM_ABBR)
    rows = q("""
        SELECT player, position, avg, obp, slg, ops, home_runs, rbi,
               runs, hits, stolen_bases, games_played, at_bats
        FROM (
            SELECT DISTINCT ON (player_id)
                player, position, avg, obp, slg, ops, home_runs, rbi,
                runs, hits, stolen_bases, games_played, at_bats
            FROM player_batting
            WHERE team = %s AND season = %s AND game_type = 'R' AND at_bats > 0
            ORDER BY player_id, date DESC
        ) latest
        ORDER BY ops DESC NULLS LAST
    """, (team, season))
    return jsn(rows)

@app.route("/api/teams/pitching_leaders")
def api_teams_pitching_leaders():
    season = request.args.get("season", SEASON, int)
    team = request.args.get("team", TEAM_ABBR)
    rows = q("""
        SELECT player, position, era, whip, fip, wins, losses, saves,
               strikeouts, innings_pitched, k9, bb9, games, quality_starts
        FROM (
            SELECT DISTINCT ON (player_id)
                player, position, era, whip, fip, wins, losses, saves,
                strikeouts, innings_pitched, k9, bb9, games, quality_starts
            FROM player_pitching
            WHERE team = %s AND season = %s AND game_type = 'R' AND innings_pitched > 0
            ORDER BY player_id, date DESC
        ) latest
        ORDER BY era ASC NULLS LAST
    """, (team, season))
    return jsn(rows)

# ── API: Players ──────────────────────────────────────────────────────────────

@app.route("/api/players/batters")
def api_players_batters():
    season = request.args.get("season", SEASON, int)
    team = request.args.get("team", TEAM_ABBR)
    rows = q("""
        SELECT DISTINCT ON (player_id) player_id, player
        FROM player_batting
        WHERE team = %s AND season = %s AND game_type = 'R' AND at_bats > 0
        ORDER BY player_id, date DESC
    """, (team, season))
    return jsn(rows)

@app.route("/api/players/pitchers")
def api_players_pitchers():
    season = request.args.get("season", SEASON, int)
    team = request.args.get("team", TEAM_ABBR)
    rows = q("""
        SELECT DISTINCT ON (player_id) player_id, player
        FROM player_pitching
        WHERE team = %s AND season = %s AND game_type = 'R' AND innings_pitched > 0
        ORDER BY player_id, date DESC
    """, (team, season))
    return jsn(rows)

@app.route("/api/players/batter_summary")
def api_players_batter_summary():
    season = request.args.get("season", SEASON, int)
    player_id = request.args.get("player_id", type=int)
    row = q1("""
        SELECT DISTINCT ON (player_id)
            player, avg, obp, slg, ops, iso, babip,
            home_runs, rbi, runs, hits, stolen_bases, games_played, at_bats
        FROM player_batting
        WHERE player_id = %s AND season = %s AND game_type = 'R'
        ORDER BY player_id, date DESC
    """, (player_id, season))
    return jsn(row or {})

@app.route("/api/players/batter_trend")
def api_players_batter_trend():
    season = request.args.get("season", SEASON, int)
    player_id = request.args.get("player_id", type=int)
    rows = q("""
        SELECT date, avg, obp, slg, ops, home_runs, rbi, runs
        FROM player_batting
        WHERE player_id = %s AND season = %s AND game_type = 'R'
        ORDER BY date
    """, (player_id, season))
    return jsn(rows)

@app.route("/api/players/pitcher_summary")
def api_players_pitcher_summary():
    season = request.args.get("season", SEASON, int)
    player_id = request.args.get("player_id", type=int)
    row = q1("""
        SELECT DISTINCT ON (player_id)
            player, era, whip, fip, k9, bb9, wins, losses, saves,
            strikeouts, innings_pitched, games, quality_starts
        FROM player_pitching
        WHERE player_id = %s AND season = %s AND game_type = 'R'
        ORDER BY player_id, date DESC
    """, (player_id, season))
    return jsn(row or {})

@app.route("/api/players/pitcher_trend")
def api_players_pitcher_trend():
    season = request.args.get("season", SEASON, int)
    player_id = request.args.get("player_id", type=int)
    rows = q("""
        SELECT date, era, whip, fip, k9, bb9, strikeouts, innings_pitched
        FROM player_pitching
        WHERE player_id = %s AND season = %s AND game_type = 'R'
        ORDER BY date
    """, (player_id, season))
    return jsn(rows)

# ── API: Recap ────────────────────────────────────────────────────────────────

@app.route("/api/recap/games")
def api_recap_games():
    season = request.args.get("season", SEASON, int)
    team = request.args.get("team", "")
    if team and team != "ALL":
        rows = q("""
            SELECT gamepk, date, home_team, away_team, doubleheader,
                   home_score, away_score
            FROM games
            WHERE season = %s AND status = 'Final' AND game_type = 'R'
              AND result IS NOT NULL
              AND (home_team = %s OR away_team = %s)
            ORDER BY date DESC, gamepk DESC
        """, (season, team, team))
    else:
        rows = q("""
            SELECT gamepk, date, home_team, away_team, doubleheader,
                   home_score, away_score
            FROM games
            WHERE season = %s AND status = 'Final' AND game_type = 'R'
              AND result IS NOT NULL
            ORDER BY date DESC, gamepk DESC
        """, (season,))
    out = []
    for r in rows:
        d = r.get("date")
        date_str = d.strftime("%b %d") if d else "?"
        dh = r.get("doubleheader", "N")
        dh_str = " (DH)" if dh in ("Y", "S") else ""
        home, away = r.get("home_team", "?"), r.get("away_team", "?")
        hs = r.get("home_score") if r.get("home_score") is not None else "?"
        as_ = r.get("away_score") if r.get("away_score") is not None else "?"
        label = f"{date_str}{dh_str}  {away} @ {home}  ({as_}-{hs})"
        out.append({"gamepk": r["gamepk"], "label": label})
    return jsn(out)

@app.route("/api/recap/game")
def api_recap_game():
    gamepk = request.args.get("gamepk", type=int)
    game = q1("SELECT * FROM games WHERE gamepk = %s", (gamepk,))
    if not game:
        return jsn({})
    ls_rows = q("""
        SELECT inning, team, runs, hits, errors
        FROM game_linescore WHERE gamepk = %s ORDER BY inning, team
    """, (gamepk,))
    batting_home = q("""
        SELECT player, batting_order, ab, r, h, doubles, triples, hr, rbi, bb, so, sb, lob
        FROM game_batting_lines WHERE gamepk = %s AND team = %s
        ORDER BY batting_order NULLS LAST
    """, (gamepk, game["home_team"]))
    batting_away = q("""
        SELECT player, batting_order, ab, r, h, doubles, triples, hr, rbi, bb, so, sb, lob
        FROM game_batting_lines WHERE gamepk = %s AND team = %s
        ORDER BY batting_order NULLS LAST
    """, (gamepk, game["away_team"]))
    pitching_home = q("""
        SELECT player, pitch_order, ip, h, r, er, bb, so, hr, pitches, strikes, era, note
        FROM game_pitching_lines WHERE gamepk = %s AND team = %s ORDER BY pitch_order
    """, (gamepk, game["home_team"]))
    pitching_away = q("""
        SELECT player, pitch_order, ip, h, r, er, bb, so, hr, pitches, strikes, era, note
        FROM game_pitching_lines WHERE gamepk = %s AND team = %s ORDER BY pitch_order
    """, (gamepk, game["away_team"]))
    ai = q1("SELECT summary_text, generated_at FROM game_summaries WHERE gamepk = %s", (gamepk,))
    return jsn({
        "game": game,
        "linescore": _pivot_linescore(ls_rows, game["away_team"], game["home_team"]),
        "batting": {"home": batting_home, "away": batting_away},
        "pitching": {"home": pitching_home, "away": pitching_away},
        "ai_summary": ai,
    })

# ── API: Divisions ────────────────────────────────────────────────────────────

DIVS = ["AL East", "AL Central", "AL West", "NL East", "NL Central", "NL West"]


def _div_teams(div, season):
    """Return list of team abbreviations in a division (ordered by standings)."""
    rows = q("""
        SELECT DISTINCT ON (team) team, wins, losses, games_behind
        FROM division_standings
        WHERE division = %s AND season = %s AND game_type = 'R'
        ORDER BY team, date DESC
    """, (div, season))
    rows.sort(key=lambda x: (float(x.get("games_behind") or 0), -(x.get("wins") or 0)))
    return [r["team"] for r in rows]


@app.route("/api/divisions/list")
def api_divisions_list():
    return jsn(DIVS)


@app.route("/api/divisions/all")
def api_divisions_all():
    season = request.args.get("season", SEASON, int)
    result = {}
    for div in DIVS:
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
        teams_in_div = [s["team"] for s in standings]
        dates = sorted(set(str(r["date"]) for r in race_rows))
        by_team: dict[str, dict] = {t: {} for t in teams_in_div}
        wpct_by_team: dict[str, dict] = {t: {} for t in teams_in_div}
        for r in race_rows:
            if r["team"] in by_team:
                by_team[r["team"]][str(r["date"])] = float(r.get("games_behind") or 0)
                w, l = r.get("wins") or 0, r.get("losses") or 0
                wpct_by_team[r["team"]][str(r["date"])] = round(w / (w + l), 3) if (w + l) else None
        result[div] = {
            "standings": standings,
            "race": {
                "dates": dates,
                "teams": {t: [by_team[t].get(d) for d in dates] for t in teams_in_div},
            },
            "wpct": {
                "dates": dates,
                "teams": {t: [wpct_by_team[t].get(d) for d in dates] for t in teams_in_div},
            },
        }
    return jsn(result)


@app.route("/api/divisions/batting_leaders")
def api_divisions_batting_leaders():
    season = request.args.get("season", SEASON, int)
    div = request.args.get("division", "AL West")
    teams = _div_teams(div, season)
    if not teams:
        return jsn([])
    rows = q("""
        SELECT player, team, position, avg, obp, slg, ops,
               home_runs, rbi, runs, hits, stolen_bases, games_played, at_bats
        FROM (
            SELECT DISTINCT ON (player_id)
                player, team, position, avg, obp, slg, ops,
                home_runs, rbi, runs, hits, stolen_bases, games_played, at_bats
            FROM player_batting
            WHERE team = ANY(%s) AND season = %s AND game_type = 'R' AND at_bats > 0
            ORDER BY player_id, date DESC
        ) latest
        ORDER BY ops DESC NULLS LAST
        LIMIT 15
    """, (teams, season))
    return jsn(rows)


@app.route("/api/divisions/pitching_leaders")
def api_divisions_pitching_leaders():
    season = request.args.get("season", SEASON, int)
    div = request.args.get("division", "AL West")
    teams = _div_teams(div, season)
    if not teams:
        return jsn([])
    rows = q("""
        SELECT player, team, position, era, whip, fip, wins, losses, saves,
               strikeouts, innings_pitched, k9, bb9, games, quality_starts
        FROM (
            SELECT DISTINCT ON (player_id)
                player, team, position, era, whip, fip, wins, losses, saves,
                strikeouts, innings_pitched, k9, bb9, games, quality_starts
            FROM player_pitching
            WHERE team = ANY(%s) AND season = %s AND game_type = 'R' AND innings_pitched > 0
            ORDER BY player_id, date DESC
        ) latest
        ORDER BY era ASC NULLS LAST
        LIMIT 15
    """, (teams, season))
    return jsn(rows)


@app.route("/api/divisions/run_diff")
def api_divisions_run_diff():
    """Run differential trend per team in a division."""
    season = request.args.get("season", SEASON, int)
    div = request.args.get("division", "AL West")
    teams = _div_teams(div, season)
    if not teams:
        return jsn({"dates": [], "teams": {}})
    rows = q("""
        SELECT date, team, runs_scored, runs_allowed
        FROM team_stats
        WHERE team = ANY(%s) AND season = %s AND game_type = 'R'
        ORDER BY date
    """, (teams, season))
    dates = sorted(set(str(r["date"]) for r in rows))
    rd_by_team: dict[str, dict] = {t: {} for t in teams}
    for r in rows:
        t = r["team"]
        if t in rd_by_team:
            rs = r.get("runs_scored") or 0
            ra = r.get("runs_allowed") or 0
            rd_by_team[t][str(r["date"])] = rs - ra
    return jsn({
        "dates": dates,
        "teams": {t: [rd_by_team[t].get(d) for d in dates] for t in teams},
    })


@app.route("/api/divisions/hr_race")
def api_divisions_hr_race():
    """Top HR hitters over time within a division."""
    season = request.args.get("season", SEASON, int)
    div = request.args.get("division", "AL West")
    teams = _div_teams(div, season)
    if not teams:
        return jsn({"dates": [], "players": {}})
    # Find top 8 HR hitters (latest snapshot)
    top = q("""
        SELECT player_id, player, team FROM (
            SELECT DISTINCT ON (player_id) player_id, player, team, home_runs
            FROM player_batting
            WHERE team = ANY(%s) AND season = %s AND game_type = 'R' AND at_bats > 0
            ORDER BY player_id, date DESC
        ) latest ORDER BY home_runs DESC NULLS LAST LIMIT 8
    """, (teams, season))
    if not top:
        return jsn({"dates": [], "players": {}})
    pids = [r["player_id"] for r in top]
    pnames = {r["player_id"]: f"{r['player']} ({r['team']})" for r in top}
    rows = q("""
        SELECT date, player_id, home_runs
        FROM player_batting
        WHERE player_id = ANY(%s) AND season = %s AND game_type = 'R'
        ORDER BY date
    """, (pids, season))
    dates = sorted(set(str(r["date"]) for r in rows))
    by_player: dict[int, dict] = {pid: {} for pid in pids}
    for r in rows:
        by_player[r["player_id"]][str(r["date"])] = r["home_runs"] or 0
    return jsn({
        "dates": dates,
        "players": {pnames[pid]: [by_player[pid].get(d) for d in dates] for pid in pids},
    })


@app.route("/api/divisions/sb_race")
def api_divisions_sb_race():
    """Top stolen base leaders over time within a division."""
    season = request.args.get("season", SEASON, int)
    div = request.args.get("division", "AL West")
    teams = _div_teams(div, season)
    if not teams:
        return jsn({"dates": [], "players": {}})
    top = q("""
        SELECT player_id, player, team FROM (
            SELECT DISTINCT ON (player_id) player_id, player, team, stolen_bases
            FROM player_batting
            WHERE team = ANY(%s) AND season = %s AND game_type = 'R' AND at_bats > 0
            ORDER BY player_id, date DESC
        ) latest ORDER BY stolen_bases DESC NULLS LAST LIMIT 8
    """, (teams, season))
    if not top:
        return jsn({"dates": [], "players": {}})
    pids = [r["player_id"] for r in top]
    pnames = {r["player_id"]: f"{r['player']} ({r['team']})" for r in top}
    rows = q("""
        SELECT date, player_id, stolen_bases
        FROM player_batting
        WHERE player_id = ANY(%s) AND season = %s AND game_type = 'R'
        ORDER BY date
    """, (pids, season))
    dates = sorted(set(str(r["date"]) for r in rows))
    by_player: dict[int, dict] = {pid: {} for pid in pids}
    for r in rows:
        by_player[r["player_id"]][str(r["date"])] = r["stolen_bases"] or 0
    return jsn({
        "dates": dates,
        "players": {pnames[pid]: [by_player[pid].get(d) for d in dates] for pid in pids},
    })


@app.route("/api/divisions/k_race")
def api_divisions_k_race():
    """Top strikeout pitchers over time within a division."""
    season = request.args.get("season", SEASON, int)
    div = request.args.get("division", "AL West")
    teams = _div_teams(div, season)
    if not teams:
        return jsn({"dates": [], "players": {}})
    top = q("""
        SELECT player_id, player, team FROM (
            SELECT DISTINCT ON (player_id) player_id, player, team, strikeouts
            FROM player_pitching
            WHERE team = ANY(%s) AND season = %s AND game_type = 'R' AND innings_pitched > 0
            ORDER BY player_id, date DESC
        ) latest ORDER BY strikeouts DESC NULLS LAST LIMIT 8
    """, (teams, season))
    if not top:
        return jsn({"dates": [], "players": {}})
    pids = [r["player_id"] for r in top]
    pnames = {r["player_id"]: f"{r['player']} ({r['team']})" for r in top}
    rows = q("""
        SELECT date, player_id, strikeouts
        FROM player_pitching
        WHERE player_id = ANY(%s) AND season = %s AND game_type = 'R'
        ORDER BY date
    """, (pids, season))
    dates = sorted(set(str(r["date"]) for r in rows))
    by_player: dict[int, dict] = {pid: {} for pid in pids}
    for r in rows:
        by_player[r["player_id"]][str(r["date"])] = r["strikeouts"] or 0
    return jsn({
        "dates": dates,
        "players": {pnames[pid]: [by_player[pid].get(d) for d in dates] for pid in pids},
    })

# ── API: Challenges ───────────────────────────────────────────────────────────

@app.route("/api/challenges/summary")
def api_challenges_summary():
    season = request.args.get("season", SEASON, int)
    team = request.args.get("team", "")
    params: list = [season]
    team_sql = ""
    if team:
        team_sql = "AND challenging_team = %s"
        params.append(team)
    row = q1(f"""
        SELECT
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE challenge_result = 'overturned') AS overturned,
            ROUND(
                COUNT(*) FILTER (WHERE challenge_result = 'overturned')::numeric
                / NULLIF(COUNT(*), 0) * 100, 1
            ) AS overturn_rate,
            COUNT(*) FILTER (WHERE call_before = 'Ball')    AS ball_challenges,
            COUNT(*) FILTER (WHERE call_before = 'Strike')  AS strike_challenges,
            COUNT(*) FILTER (WHERE call_before = 'Ball'   AND challenge_result = 'overturned') AS ball_overturned,
            COUNT(*) FILTER (WHERE call_before = 'Strike' AND challenge_result = 'overturned') AS strike_overturned
        FROM game_challenges
        WHERE season = %s {team_sql}
    """, params)
    return jsn(row or {})

@app.route("/api/challenges/by_team")
def api_challenges_by_team():
    season = request.args.get("season", SEASON, int)
    rows = q("""
        SELECT challenging_team AS team,
               COUNT(*) AS total,
               COUNT(*) FILTER (WHERE challenge_result = 'overturned') AS overturned,
               ROUND(
                   COUNT(*) FILTER (WHERE challenge_result = 'overturned')::numeric
                   / NULLIF(COUNT(*), 0) * 100, 1
               ) AS overturn_rate
        FROM game_challenges
        WHERE season = %s
        GROUP BY challenging_team
        ORDER BY total DESC
    """, (season,))
    return jsn(rows)

@app.route("/api/challenges/game_list")
def api_challenges_game_list():
    season = request.args.get("season", SEASON, int)
    team = request.args.get("team", "")
    params: list = [season]
    team_sql = ""
    if team:
        team_sql = "AND gc.challenging_team = %s"
        params.insert(0, team)
    rows = q(f"""
        SELECT g.gamepk, g.date, g.home_team, g.away_team, g.result,
               g.sea_score, g.opp_score, g.doubleheader,
               COUNT(gc.id) AS challenge_count,
               COUNT(gc.id) FILTER (WHERE gc.challenge_result = 'overturned') AS overturned_count
        FROM games g
        JOIN game_challenges gc ON g.gamepk = gc.gamepk {team_sql}
        WHERE g.season = %s AND g.game_type = 'R'
        GROUP BY g.gamepk, g.date, g.home_team, g.away_team, g.result,
                 g.sea_score, g.opp_score, g.doubleheader
        ORDER BY g.date DESC
    """, params)
    return jsn([{**r, "label": _game_label(r)} for r in rows])

@app.route("/api/challenges/game")
def api_challenges_game():
    gamepk = request.args.get("gamepk", type=int)
    rows = q("""
        SELECT inning, inning_half, challenging_team, challenging_type,
               call_before, call_after, challenge_result
        FROM game_challenges
        WHERE gamepk = %s
        ORDER BY inning, inning_half DESC, at_bat_index
    """, (gamepk,))
    return jsn(rows)

@app.route("/api/challenges/trend")
def api_challenges_trend():
    season = request.args.get("season", SEASON, int)
    team = request.args.get("team", "")
    params: list = [season]
    team_sql = ""
    if team:
        team_sql = "AND challenging_team = %s"
        params.append(team)
    rows = q(f"""
        SELECT date,
               COUNT(*) AS total,
               COUNT(*) FILTER (WHERE challenge_result = 'overturned') AS overturned
        FROM game_challenges
        WHERE season = %s {team_sql}
        GROUP BY date ORDER BY date
    """, params)
    return jsn(rows)

# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    debug = os.environ.get("DEBUG", "").lower() == "true"
    app.run(host="0.0.0.0", port=port, debug=debug)
