#!/usr/bin/env python3
"""
Backfill Mariners game-by-game box scores and AI summaries into PostgreSQL.

For each completed regular-season game, fetches the box score and linescore
from the MLB Stats API and stores batting/pitching lines, inning-by-inning
scoring, and game metadata. Optionally generates AI-written game recaps using
the Anthropic API (claude-haiku-4-5-20251001) if ANTHROPIC_API_KEY is set.

Usage:
  python3 backfill_game_recaps.py [SEASON]          # default: 2025
  ANTHROPIC_API_KEY=sk-... python3 backfill_game_recaps.py

Run from inside scraper container or locally (DB_HOST=localhost, DB_PORT=5433).
Re-running is safe — all upserts use ON CONFLICT DO UPDATE.
AI summaries are skipped for games that already have one (to avoid re-billing).
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

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
SKIP_SUMMARIES    = os.getenv("SKIP_SUMMARIES", "0") == "1"
CLAUDE_MODEL      = "claude-haiku-4-5-20251001"

session = requests.Session()
session.headers.update({"User-Agent": "MLBGameBackfill/1.0", "Accept": "application/json"})


# ── DB / API helpers ──────────────────────────────────────────────────────────

def get_db():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "5433")),
        dbname=os.getenv("DB_NAME", "mlb_stats"),
        user=os.getenv("DB_USER", "mlb"),
        password=os.getenv("DB_PASS"),
    )


def api_get(path, **params):
    resp = session.get(f"{BASE}{path}", params=params, timeout=20)
    resp.raise_for_status()
    return resp.json()


def si(val, default=0):
    try:
        return int(val) if val not in (None, "") else default
    except (ValueError, TypeError):
        return default


def sf(val, default=None):
    try:
        return float(val) if val not in (None, "", "-.--", "--", ".---", "Inf", "inf") else default
    except (ValueError, TypeError):
        return default


# ── Team abbreviation map ─────────────────────────────────────────────────────

def build_team_abbr_map() -> dict:
    data = api_get("/teams", sportId=1)
    return {t["id"]: t.get("abbreviation", "UNK") for t in data.get("teams", [])}


# ── Schedule ──────────────────────────────────────────────────────────────────

def fetch_schedule(season: int) -> list:
    data = api_get("/schedule", season=season, sportId=1,
                   gameType="R", hydrate="decisions")
    games = []
    for date_entry in data.get("dates", []):
        for g in date_entry.get("games", []):
            games.append(g)
    games.sort(key=lambda g: (g.get("gameDate", ""), g.get("gamePk", 0)))
    return games


# ── Box score / linescore parsers ─────────────────────────────────────────────

def parse_batting_lines(box: dict, team_abbr_map: dict) -> list:
    rows = []
    for side in ("home", "away"):
        team_data = box["teams"][side]
        team_id   = team_data["team"]["id"]
        abbr      = team_abbr_map.get(team_id, "UNK")
        players   = team_data.get("players", {})

        for pid in team_data.get("batters", []):
            key   = f"ID{pid}"
            p     = players.get(key, {})
            st    = p.get("stats", {}).get("batting", {})
            order = p.get("battingOrder")  # "100", "200", "101" etc.

            # Skip players with no batting stats and no batting order (pinch runners, etc.)
            if not st and order is None:
                continue

            rows.append({
                "player_id":    pid,
                "player":       p.get("person", {}).get("fullName", "Unknown"),
                "team":         abbr,
                "batting_order": int(order) if order else None,
                "ab":      si(st.get("atBats")),
                "r":       si(st.get("runs")),
                "h":       si(st.get("hits")),
                "doubles": si(st.get("doubles")),
                "triples": si(st.get("triples")),
                "hr":      si(st.get("homeRuns")),
                "rbi":     si(st.get("rbi")),
                "bb":      si(st.get("baseOnBalls")),
                "so":      si(st.get("strikeOuts")),
                "sb":      si(st.get("stolenBases")),
                "lob":     si(st.get("leftOnBase")),
            })
    return rows


def parse_pitching_lines(box: dict, team_abbr_map: dict) -> list:
    decisions = box.get("decisions", {})
    winner_id = decisions.get("winner", {}).get("id")
    loser_id  = decisions.get("loser", {}).get("id")
    save_id   = decisions.get("save", {}).get("id")

    rows = []
    for side in ("home", "away"):
        team_data   = box["teams"][side]
        team_id     = team_data["team"]["id"]
        abbr        = team_abbr_map.get(team_id, "UNK")
        players     = team_data.get("players", {})
        pitcher_ids = team_data.get("pitchers", [])

        for order, pid in enumerate(pitcher_ids, start=1):
            key = f"ID{pid}"
            p   = players.get(key, {})
            st  = p.get("stats", {}).get("pitching", {})

            note = None
            if pid == winner_id:
                note = "W"
            elif pid == loser_id:
                note = "L"
            elif pid == save_id:
                note = "S"

            rows.append({
                "player_id":  pid,
                "player":     p.get("person", {}).get("fullName", "Unknown"),
                "team":       abbr,
                "pitch_order": order,
                "ip":      st.get("inningsPitched", "0.0"),
                "h":       si(st.get("hits")),
                "r":       si(st.get("runs")),
                "er":      si(st.get("earnedRuns")),
                "bb":      si(st.get("baseOnBalls")),
                "so":      si(st.get("strikeOuts")),
                "hr":      si(st.get("homeRuns")),
                "pitches": si(st.get("pitchesThrown")) if st.get("pitchesThrown") else None,
                "strikes": si(st.get("strikes")) if st.get("strikes") else None,
                "era":     sf(st.get("era")),
                "note":    note,
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
                "inning": num,
                "team":   abbr,
                "runs":   si(half.get("runs")),
                "hits":   si(half.get("hits")),
                "errors": si(half.get("errors")),
            })
    return rows


# ── DB upserts ────────────────────────────────────────────────────────────────

def upsert_game(cur, gamepk, game_entry, box, ls, team_abbr_map, game_number):
    teams_sched = game_entry.get("teams", {})
    home_id     = teams_sched.get("home", {}).get("team", {}).get("id")
    away_id     = teams_sched.get("away", {}).get("team", {}).get("id")
    home_abbr   = team_abbr_map.get(home_id, "UNK")
    away_abbr   = team_abbr_map.get(away_id, "UNK")

    is_sea_game = (home_id == TEAM_ID or away_id == TEAM_ID)
    sea_is_home = (home_id == TEAM_ID)

    ls_totals   = ls.get("teams", {})
    home_score  = ls_totals.get("home", {}).get("runs")
    away_score  = ls_totals.get("away", {}).get("runs")

    if is_sea_game:
        opp_id    = away_id if sea_is_home else home_id
        opponent  = team_abbr_map.get(opp_id, "UNK")
        sea_score = home_score if sea_is_home else away_score
        opp_score = away_score if sea_is_home else home_score
        result    = ("W" if sea_score > opp_score else "L") if (sea_score is not None and opp_score is not None) else None
    else:
        opponent  = None
        sea_score = None
        opp_score = None
        result    = None

    decisions       = box.get("decisions", {})
    winning_pitcher = decisions.get("winner", {}).get("fullName")
    losing_pitcher  = decisions.get("loser",  {}).get("fullName")
    save_pitcher    = decisions.get("save",   {}).get("fullName")

    venue        = game_entry.get("venue", {}).get("name")
    game_date    = datetime.date.fromisoformat(game_entry.get("gameDate", "2025-01-01")[:10])
    doubleheader = game_entry.get("doubleHeader", "N")
    game_type    = game_entry.get("gameType", "R")
    status       = game_entry.get("status", {}).get("abstractGameState", "Unknown")

    cur.execute("""
        INSERT INTO games
            (gamepk, date, season, game_number, game_type, doubleheader,
             home_team, away_team, home_score, away_score,
             sea_score, opp_score, opponent, result, venue,
             winning_pitcher, losing_pitcher, save_pitcher, status)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (gamepk) DO UPDATE SET
            game_number=EXCLUDED.game_number, home_score=EXCLUDED.home_score,
            away_score=EXCLUDED.away_score, sea_score=EXCLUDED.sea_score,
            opp_score=EXCLUDED.opp_score, result=EXCLUDED.result,
            winning_pitcher=EXCLUDED.winning_pitcher,
            losing_pitcher=EXCLUDED.losing_pitcher,
            save_pitcher=EXCLUDED.save_pitcher, status=EXCLUDED.status
    """, (
        gamepk, game_date, SEASON, game_number, game_type, doubleheader,
        home_abbr, away_abbr, home_score, away_score,
        sea_score, opp_score, opponent, result, venue,
        winning_pitcher, losing_pitcher, save_pitcher, status,
    ))


def upsert_batting_lines(cur, gamepk, rows):
    for r in rows:
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
        """, (
            gamepk, r["player_id"], r["player"], r["team"], r["batting_order"],
            r["ab"], r["r"], r["h"], r["doubles"], r["triples"],
            r["hr"], r["rbi"], r["bb"], r["so"], r["sb"], r["lob"],
        ))


def upsert_pitching_lines(cur, gamepk, rows):
    for r in rows:
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
        """, (
            gamepk, r["player_id"], r["player"], r["team"], r["pitch_order"],
            r["ip"], r["h"], r["r"], r["er"], r["bb"], r["so"], r["hr"],
            r["pitches"], r["strikes"], r["era"], r["note"],
        ))


def upsert_linescore(cur, gamepk, rows):
    for r in rows:
        cur.execute("""
            INSERT INTO game_linescore (gamepk, inning, team, runs, hits, errors)
            VALUES (%s,%s,%s,%s,%s,%s)
            ON CONFLICT (gamepk, inning, team) DO UPDATE SET
                runs=EXCLUDED.runs, hits=EXCLUDED.hits, errors=EXCLUDED.errors
        """, (gamepk, r["inning"], r["team"], r["runs"], r["hits"], r["errors"]))


# ── AI summary generation ─────────────────────────────────────────────────────

def format_linescore_text(ls_rows, away_abbr, home_abbr):
    by_team = {}
    for row in ls_rows:
        by_team.setdefault(row["team"], {})[row["inning"]] = row["runs"]

    max_inning = max((r["inning"] for r in ls_rows), default=9)
    innings = list(range(1, max(max_inning, 9) + 1))

    lines = []
    for abbr in (away_abbr, home_abbr):
        innings_data = by_team.get(abbr, {})
        cells = []
        for i in innings:
            v = innings_data.get(i)
            cells.append("X" if v is None else str(v))
        total = sum(innings_data.values())
        lines.append(f"  {abbr:>4}: {' '.join(c.rjust(2) for c in cells)}  — {total}")
    header = "         " + " ".join(str(i).rjust(2) for i in innings)
    return "\n".join([header] + lines)


def format_batting_text(batting_rows, sea_abbr):
    sea = [r for r in batting_rows if r["team"] == sea_abbr]
    sea.sort(key=lambda r: (r["batting_order"] or 9999))
    lines = []
    for r in sea:
        extra = []
        if r["hr"]:   extra.append(f"{r['hr']} HR")
        if r["rbi"]:  extra.append(f"{r['rbi']} RBI")
        if r["bb"]:   extra.append(f"{r['bb']} BB")
        if r["sb"]:   extra.append(f"{r['sb']} SB")
        note = (", " + ", ".join(extra)) if extra else ""
        lines.append(f"  {r['player']}: {r['h']}-for-{r['ab']}{note}")
    return "\n".join(lines) if lines else "  (no data)"


def format_pitching_text(pitching_rows, sea_abbr):
    sea = [r for r in pitching_rows if r["team"] == sea_abbr]
    sea.sort(key=lambda r: r["pitch_order"])
    lines = []
    for r in sea:
        dec   = f" ({r['note']})" if r["note"] else ""
        ptch  = f", {r['pitches']}P" if r["pitches"] else ""
        lines.append(f"  {r['player']}: {r['ip']} IP, {r['h']} H, {r['r']} R, "
                     f"{r['er']} ER, {r['bb']} BB, {r['so']} K{ptch}{dec}")
    return "\n".join(lines) if lines else "  (no data)"


def generate_summary(gamepk, game_meta, batting_rows, pitching_rows, ls_rows) -> str:
    away_abbr = game_meta["away_team"]
    home_abbr = game_meta["home_team"]
    sea_abbr  = TEAM_ABBR

    linescore_text = format_linescore_text(ls_rows, away_abbr, home_abbr)
    batting_text   = format_batting_text(batting_rows, sea_abbr)
    pitching_text  = format_pitching_text(pitching_rows, sea_abbr)

    result_word = "defeated" if game_meta["result"] == "W" else "fell to"
    at_or_vs    = "vs" if game_meta["home_team"] == sea_abbr else "@"

    prompt = f"""You are a Seattle Mariners beat reporter. Write a concise 3-paragraph game recap (around 200-250 words) for the following game. Be specific with stats. Write in past tense. Do not use em dashes.

GAME: {game_meta['date']} — Mariners {at_or_vs} {game_meta['opponent']} at {game_meta['venue']}
RESULT: Mariners {result_word} {game_meta['opponent']} {game_meta['sea_score']}-{game_meta['opp_score']}
DECISIONS: W-{game_meta['winning_pitcher'] or 'N/A'}  L-{game_meta['losing_pitcher'] or 'N/A'}  SV-{game_meta['save_pitcher'] or 'None'}

LINE SCORE:
{linescore_text}

MARINERS BATTING:
{batting_text}

MARINERS PITCHING:
{pitching_text}

Write: (1) Lead paragraph with result and key narrative, (2) Pitching performance, (3) Offensive highlights."""

    resp = session.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key":         ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type":      "application/json",
        },
        json={
            "model":      CLAUDE_MODEL,
            "max_tokens": 600,
            "messages":   [{"role": "user", "content": prompt}],
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["content"][0]["text"]


def upsert_summary(cur, gamepk, text):
    cur.execute("""
        INSERT INTO game_summaries (gamepk, summary_text, generated_at, model)
        VALUES (%s, %s, NOW(), %s)
        ON CONFLICT (gamepk) DO UPDATE SET
            summary_text=EXCLUDED.summary_text, generated_at=NOW()
    """, (gamepk, text, CLAUDE_MODEL))


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    conn = get_db()
    cur  = conn.cursor()

    print(f"Building team abbreviation map...", file=sys.stderr)
    team_abbr_map = build_team_abbr_map()
    time.sleep(0.3)

    print(f"Fetching {SEASON} schedule (all teams)...", file=sys.stderr)
    all_games = fetch_schedule(SEASON)
    print(f"  {len(all_games)} total games found", file=sys.stderr)

    game_number = 0
    processed   = 0
    skipped     = 0
    errors      = 0

    for game_entry in all_games:
        gamepk = game_entry.get("gamePk")
        status = game_entry.get("status", {}).get("abstractGameState", "")

        if status != "Final":
            skipped += 1
            continue

        game_number += 1
        teams = game_entry.get("teams", {})
        home_id   = teams.get("home", {}).get("team", {}).get("id")
        away_id   = teams.get("away", {}).get("team", {}).get("id")
        home_abbr = team_abbr_map.get(home_id, "UNK")
        away_abbr = team_abbr_map.get(away_id, "UNK")
        is_sea_game = (home_id == TEAM_ID or away_id == TEAM_ID)
        opp_abbr  = away_abbr if home_id == TEAM_ID else home_abbr

        print(f"  G{game_number:03d} gamePk={gamepk} "
              f"({away_abbr} @ {home_abbr})", file=sys.stderr)

        try:
            box = session.get(f"{BASE}/game/{gamepk}/boxscore", timeout=20)
            box.raise_for_status()
            box = box.json()
            time.sleep(0.2)

            ls = session.get(f"{BASE}/game/{gamepk}/linescore", timeout=20)
            ls.raise_for_status()
            ls = ls.json()
            time.sleep(0.2)

            batting_rows  = parse_batting_lines(box, team_abbr_map)
            pitching_rows = parse_pitching_lines(box, team_abbr_map)
            ls_rows       = parse_linescore(ls, home_abbr, away_abbr)

            upsert_game(cur, gamepk, game_entry, box, ls, team_abbr_map, game_number)
            upsert_batting_lines(cur, gamepk, batting_rows)
            upsert_pitching_lines(cur, gamepk, pitching_rows)
            upsert_linescore(cur, gamepk, ls_rows)
            conn.commit()
            processed += 1

            # AI summary — only for SEA games, if key present and no existing summary
            if is_sea_game and ANTHROPIC_API_KEY and not SKIP_SUMMARIES:
                cur.execute("SELECT 1 FROM game_summaries WHERE gamepk = %s", (gamepk,))
                if not cur.fetchone():
                    try:
                        game_meta = {
                            "date":            game_entry.get("gameDate", "")[:10],
                            "home_team":       home_abbr,
                            "away_team":       away_abbr,
                            "opponent":        opp_abbr,
                            "venue":           game_entry.get("venue", {}).get("name", ""),
                            "result":          None,
                            "sea_score":       None,
                            "opp_score":       None,
                            "winning_pitcher": box.get("decisions", {}).get("winner", {}).get("fullName"),
                            "losing_pitcher":  box.get("decisions", {}).get("loser",  {}).get("fullName"),
                            "save_pitcher":    box.get("decisions", {}).get("save",   {}).get("fullName"),
                        }
                        ls_totals = ls.get("teams", {})
                        sea_is_home = (home_id == TEAM_ID)
                        home_score = ls_totals.get("home", {}).get("runs")
                        away_score = ls_totals.get("away", {}).get("runs")
                        game_meta["sea_score"] = home_score if sea_is_home else away_score
                        game_meta["opp_score"] = away_score if sea_is_home else home_score
                        game_meta["result"] = (
                            "W" if game_meta["sea_score"] > game_meta["opp_score"] else "L"
                        ) if game_meta["sea_score"] is not None else "?"

                        text = generate_summary(gamepk, game_meta, batting_rows, pitching_rows, ls_rows)
                        upsert_summary(cur, gamepk, text)
                        conn.commit()
                        print(f"         AI summary generated", file=sys.stderr)
                        time.sleep(1.2)
                    except Exception as e:
                        print(f"         summary FAILED: {e}", file=sys.stderr)
                        conn.rollback()

        except Exception as e:
            print(f"  ERROR gamePk={gamepk}: {e}", file=sys.stderr)
            conn.rollback()
            errors += 1

    cur.close()
    conn.close()
    print(f"\nDone: {processed} games, {skipped} skipped (not Final), "
          f"{errors} errors.", file=sys.stderr)

    if not ANTHROPIC_API_KEY and not SKIP_SUMMARIES:
        print("\nTip: set ANTHROPIC_API_KEY to generate AI game summaries.", file=sys.stderr)


if __name__ == "__main__":
    main()
