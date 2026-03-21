#!/usr/bin/env python3
"""
Backfill AL West division standings for a full season.

Fetches daily standings from the MLB Stats API and outputs OpenMetrics format
suitable for ingestion into Prometheus via promtool:

  python3 backfill_standings.py > /tmp/standings_2025.om
  docker cp /tmp/standings_2025.om mlb_prometheus:/tmp/
  docker exec mlb_prometheus promtool tsdb create-blocks-from openmetrics \
      /tmp/standings_2025.om /prometheus
  docker restart mlb_prometheus

Usage:
  python3 backfill_standings.py [SEASON]   # default: 2025
"""

import datetime
import sys
import time

import requests

SEASON = sys.argv[1] if len(sys.argv) > 1 else "2025"
BASE   = "https://statsapi.mlb.com/api/v1"
AL_WEST_DIVISION_ID = 200

# The standings API only returns team id/name/link — no abbreviation.
# Map team IDs to abbreviations manually.
TEAM_ABBR = {
    108: "LAA",   # Los Angeles Angels
    117: "HOU",   # Houston Astros
    133: "ATH",   # Athletics (Oakland/Sacramento)
    136: "SEA",   # Seattle Mariners
    140: "TEX",   # Texas Rangers
}

# 2025 regular season window (fetch will skip pre-season dates with no data)
SEASON_START = datetime.date(int(SEASON), 3, 20)
SEASON_END   = datetime.date(int(SEASON), 9, 30)

session = requests.Session()
session.headers.update({
    "User-Agent": "MLBStatsBackfill/1.0 (personal project)",
    "Accept": "application/json",
})


def fetch_standings(date_str: str) -> list[dict]:
    """Return list of team records for AL West on a given date."""
    try:
        resp = session.get(
            f"{BASE}/standings",
            params={
                "leagueId": 103,
                "season": SEASON,
                "standingsTypes": "regularSeason",
                "date": date_str,
                "sportId": 1,
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"# ERROR {date_str}: {e}", file=sys.stderr)
        return []

    for division in data.get("records", []):
        if division.get("division", {}).get("id") == AL_WEST_DIVISION_ID:
            return division.get("teamRecords", [])
    return []


def main() -> None:
    # OpenMetrics header
    lines = [
        "# HELP mlb_division_games_behind Games behind division leader (0 = first place)",
        "# TYPE mlb_division_games_behind gauge",
        "# HELP mlb_division_wins Team wins",
        "# TYPE mlb_division_wins gauge",
        "# HELP mlb_division_losses Team losses",
        "# TYPE mlb_division_losses gauge",
    ]

    current = SEASON_START
    days_with_data = 0

    while current <= SEASON_END:
        date_str = current.strftime("%Y-%m-%d")
        # Use noon UTC on that date as the sample timestamp
        ts = int(datetime.datetime(
            current.year, current.month, current.day, 20, 0, 0
        ).timestamp())

        records = fetch_standings(date_str)

        if records:
            days_with_data += 1
            for rec in records:
                team      = rec.get("team", {})
                team_id   = str(team.get("id", ""))
                team_abbr = TEAM_ABBR.get(team.get("id"), team.get("name", "UNK"))
                wins      = rec.get("wins", 0)
                losses    = rec.get("losses", 0)
                gb_raw    = rec.get("gamesBack", "0")
                try:
                    gb = 0.0 if gb_raw in ("-", "", None) else float(gb_raw)
                except ValueError:
                    gb = 0.0

                lbl = (
                    f'{{team="{team_abbr}",team_id="{team_id}",'
                    f'division="AL West",season="{SEASON}"}}'
                )
                lines.append(f"mlb_division_games_behind{lbl} {gb} {ts}")
                lines.append(f"mlb_division_wins{lbl} {wins} {ts}")
                lines.append(f"mlb_division_losses{lbl} {losses} {ts}")

            print(f"{date_str}: {len(records)} teams", file=sys.stderr)
        else:
            print(f"{date_str}: no data (pre-season / off-day)", file=sys.stderr)

        current += datetime.timedelta(days=1)
        time.sleep(0.15)   # ~150ms between requests — polite to the API

    lines.append("# EOF")
    print("\n".join(lines))
    print(
        f"\nDone: {days_with_data} days with data written to stdout.",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
