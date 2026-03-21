"""
Tests for parse_batting_lines, parse_pitching_lines, and parse_linescore.
These are pure functions that transform raw MLB API JSON into lists of dicts
with no DB or network calls.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from scraper import parse_batting_lines, parse_pitching_lines, parse_linescore


# ── parse_batting_lines ────────────────────────────────────────────────────────

class TestParseBattingLines:

    def test_returns_both_teams(self, boxscore, abbr_map):
        rows = parse_batting_lines(boxscore, abbr_map)
        teams = {r["team"] for r in rows}
        assert teams == {"SEA", "ATH"}

    def test_sea_batter_count(self, boxscore, abbr_map):
        rows = parse_batting_lines(boxscore, abbr_map)
        sea = [r for r in rows if r["team"] == "SEA"]
        # Mitch Garver has no stats AND no batting order — should be excluded
        assert len(sea) == 2

    def test_ath_batter_count(self, boxscore, abbr_map):
        rows = parse_batting_lines(boxscore, abbr_map)
        ath = [r for r in rows if r["team"] == "ATH"]
        assert len(ath) == 2

    def test_julio_rodriguez_stats(self, boxscore, abbr_map):
        rows = parse_batting_lines(boxscore, abbr_map)
        julio = next(r for r in rows if r["player_id"] == 677594)
        assert julio["player"] == "Julio Rodriguez"
        assert julio["team"] == "SEA"
        assert julio["batting_order"] == 100
        assert julio["ab"] == 4
        assert julio["h"] == 2
        assert julio["hr"] == 1
        assert julio["rbi"] == 2
        assert julio["r"] == 2
        assert julio["so"] == 1
        assert julio["bb"] == 0
        assert julio["doubles"] == 0
        assert julio["sb"] == 0
        assert julio["lob"] == 1

    def test_batting_order_parsed_as_int(self, boxscore, abbr_map):
        rows = parse_batting_lines(boxscore, abbr_map)
        for r in rows:
            if r["batting_order"] is not None:
                assert isinstance(r["batting_order"], int)

    def test_player_with_no_stats_no_order_excluded(self, boxscore, abbr_map):
        # Mitch Garver: battingOrder=None, stats.batting={} → should be excluded
        rows = parse_batting_lines(boxscore, abbr_map)
        player_ids = [r["player_id"] for r in rows]
        assert 665742 not in player_ids

    def test_unknown_team_id_uses_unk(self, boxscore, abbr_map):
        # Remove ATH from abbr_map to trigger "UNK"
        abbr_map.pop(133)
        rows = parse_batting_lines(boxscore, abbr_map)
        ath_rows = [r for r in rows if r["team"] == "UNK"]
        assert len(ath_rows) == 2

    def test_empty_boxscore_returns_empty(self, abbr_map):
        empty = {"teams": {"home": {"team": {"id": 136}, "batters": [], "players": {}},
                           "away": {"team": {"id": 133}, "batters": [], "players": {}}}}
        assert parse_batting_lines(empty, abbr_map) == []

    def test_all_required_fields_present(self, boxscore, abbr_map):
        required = {"player_id", "player", "team", "batting_order",
                    "ab", "r", "h", "doubles", "triples", "hr",
                    "rbi", "bb", "so", "sb", "lob"}
        for row in parse_batting_lines(boxscore, abbr_map):
            assert required.issubset(row.keys()), f"Missing keys in row for {row['player']}"

    def test_missing_stat_defaults_to_zero(self, abbr_map):
        """Stats not present in API response should default to 0, not raise."""
        sparse_box = {
            "teams": {
                "home": {
                    "team": {"id": 136},
                    "batters": [999],
                    "players": {
                        "ID999": {
                            "person": {"id": 999, "fullName": "Ghost Player"},
                            "battingOrder": "300",
                            "stats": {"batting": {"atBats": 2}},  # most fields missing
                        }
                    },
                },
                "away": {"team": {"id": 133}, "batters": [], "players": {}},
            }
        }
        rows = parse_batting_lines(sparse_box, abbr_map)
        assert len(rows) == 1
        assert rows[0]["hr"] == 0
        assert rows[0]["rbi"] == 0
        assert rows[0]["ab"] == 2


# ── parse_pitching_lines ───────────────────────────────────────────────────────

class TestParsePitchingLines:

    def test_returns_both_teams(self, boxscore, abbr_map, decisions):
        rows = parse_pitching_lines(boxscore, abbr_map, decisions)
        teams = {r["team"] for r in rows}
        assert teams == {"SEA", "ATH"}

    def test_sea_pitcher_count(self, boxscore, abbr_map, decisions):
        rows = parse_pitching_lines(boxscore, abbr_map, decisions)
        assert len([r for r in rows if r["team"] == "SEA"]) == 3

    def test_winning_pitcher_note(self, boxscore, abbr_map, decisions):
        rows = parse_pitching_lines(boxscore, abbr_map, decisions)
        thornton = next(r for r in rows if r["player_id"] == 663423)
        assert thornton["note"] == "W"

    def test_losing_pitcher_note(self, boxscore, abbr_map, decisions):
        rows = parse_pitching_lines(boxscore, abbr_map, decisions)
        severino = next(r for r in rows if r["player_id"] == 622663)
        assert severino["note"] == "L"

    def test_save_pitcher_note(self, boxscore, abbr_map, decisions):
        rows = parse_pitching_lines(boxscore, abbr_map, decisions)
        munoz = next(r for r in rows if r["player_id"] == 662253)
        assert munoz["note"] == "S"

    def test_non_decision_pitcher_note_is_none(self, boxscore, abbr_map, decisions):
        rows = parse_pitching_lines(boxscore, abbr_map, decisions)
        gilbert = next(r for r in rows if r["player_id"] == 669302)
        assert gilbert["note"] is None

    def test_pitch_order_sequential_per_team(self, boxscore, abbr_map, decisions):
        rows = parse_pitching_lines(boxscore, abbr_map, decisions)
        sea = sorted([r for r in rows if r["team"] == "SEA"], key=lambda r: r["pitch_order"])
        assert [r["pitch_order"] for r in sea] == [1, 2, 3]

    def test_ip_field_is_string(self, boxscore, abbr_map, decisions):
        rows = parse_pitching_lines(boxscore, abbr_map, decisions)
        for r in rows:
            assert isinstance(r["ip"], str), f"IP should be string for {r['player']}"

    def test_era_is_float_or_none(self, boxscore, abbr_map, decisions):
        rows = parse_pitching_lines(boxscore, abbr_map, decisions)
        for r in rows:
            assert r["era"] is None or isinstance(r["era"], float)

    def test_empty_decisions_all_notes_none(self, boxscore, abbr_map):
        rows = parse_pitching_lines(boxscore, abbr_map, {})
        assert all(r["note"] is None for r in rows)

    def test_all_required_fields_present(self, boxscore, abbr_map, decisions):
        required = {"player_id", "player", "team", "pitch_order",
                    "ip", "h", "r", "er", "bb", "so", "hr",
                    "pitches", "strikes", "era", "note"}
        for row in parse_pitching_lines(boxscore, abbr_map, decisions):
            assert required.issubset(row.keys())

    def test_pitches_none_when_not_provided(self, abbr_map):
        box = {
            "teams": {
                "home": {
                    "team": {"id": 136},
                    "pitchers": [1],
                    "players": {
                        "ID1": {
                            "person": {"id": 1, "fullName": "Mystery Arm"},
                            "stats": {"pitching": {"inningsPitched": "1.0"}},
                        }
                    },
                },
                "away": {"team": {"id": 133}, "pitchers": [], "players": {}},
            }
        }
        rows = parse_pitching_lines(box, abbr_map, {})
        assert rows[0]["pitches"] is None
        assert rows[0]["strikes"] is None


# ── parse_linescore ────────────────────────────────────────────────────────────

class TestParseLinescore:

    def test_both_teams_represented(self, linescore):
        rows = parse_linescore(linescore, "SEA", "ATH")
        teams = {r["team"] for r in rows}
        assert teams == {"SEA", "ATH"}

    def test_nine_full_innings_away_only_last(self, linescore):
        rows = parse_linescore(linescore, "SEA", "ATH")
        # Inning 9: only ATH half exists (SEA didn't bat — walked off)
        inning9 = [r for r in rows if r["inning"] == 9]
        assert len(inning9) == 1
        assert inning9[0]["team"] == "ATH"

    def test_run_totals_correct(self, linescore):
        rows = parse_linescore(linescore, "SEA", "ATH")
        sea_runs = sum(r["runs"] for r in rows if r["team"] == "SEA")
        ath_runs = sum(r["runs"] for r in rows if r["team"] == "ATH")
        assert sea_runs == 4
        assert ath_runs == 2

    def test_error_totals_correct(self, linescore):
        rows = parse_linescore(linescore, "SEA", "ATH")
        ath_errors = sum(r["errors"] for r in rows if r["team"] == "ATH")
        assert ath_errors == 1

    def test_inning_numbers_present(self, linescore):
        rows = parse_linescore(linescore, "SEA", "ATH")
        innings = {r["inning"] for r in rows}
        assert 1 in innings and 8 in innings and 9 in innings

    def test_all_required_fields(self, linescore):
        rows = parse_linescore(linescore, "SEA", "ATH")
        for row in rows:
            assert set(row.keys()) == {"inning", "team", "runs", "hits", "errors"}

    def test_inning_missing_runs_key_skipped(self):
        """A half-inning dict without 'runs' should be skipped (not played)."""
        ls = {
            "innings": [
                {"num": 9, "away": {"runs": 0, "hits": 0, "errors": 0},
                           "home": {}},  # home half not played
            ]
        }
        rows = parse_linescore(ls, "SEA", "ATH")
        assert len(rows) == 1
        assert rows[0]["team"] == "ATH"

    def test_empty_innings_returns_empty(self):
        rows = parse_linescore({"innings": []}, "SEA", "ATH")
        assert rows == []

    def test_extra_innings(self):
        ls = {
            "innings": [
                {"num": i,
                 "home": {"runs": 0, "hits": 0, "errors": 0},
                 "away": {"runs": 0, "hits": 0, "errors": 0}}
                for i in range(1, 11)
            ]
        }
        ls["innings"][9]["home"]["runs"] = 1  # SEA scores in 10th
        rows = parse_linescore(ls, "SEA", "ATH")
        inning10 = [r for r in rows if r["inning"] == 10]
        assert len(inning10) == 2
        sea_10 = next(r for r in inning10 if r["team"] == "SEA")
        assert sea_10["runs"] == 1
