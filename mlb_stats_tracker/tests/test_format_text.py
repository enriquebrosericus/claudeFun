"""
Tests for format_linescore_text, format_batting_text, and format_pitching_text.
These functions transform parsed row dicts into human-readable strings for the
AI summary prompt. No DB or network calls.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# backfill_game_recaps.py reads sys.argv[1] at module level for SEASON;
# temporarily clear argv so it falls back to the default (2025).
_saved_argv = sys.argv[:]
sys.argv = sys.argv[:1]
from backfill_game_recaps import (
    format_linescore_text,
    format_batting_text,
    format_pitching_text,
)
sys.argv = _saved_argv


# ── format_linescore_text ──────────────────────────────────────────────────────

class TestFormatLinescoreText:

    def test_contains_both_team_abbrs(self, linescore_rows):
        text = format_linescore_text(linescore_rows, "ATH", "SEA")
        assert "ATH" in text
        assert "SEA" in text

    def test_header_has_inning_numbers(self, linescore_rows):
        text = format_linescore_text(linescore_rows, "ATH", "SEA")
        header = text.splitlines()[0]
        assert "1" in header
        assert "9" in header

    def test_run_totals_shown(self, linescore_rows):
        text = format_linescore_text(linescore_rows, "ATH", "SEA")
        # SEA total = 4, ATH total = 2
        lines = text.splitlines()
        sea_line = next(l for l in lines if "SEA" in l)
        ath_line = next(l for l in lines if "ATH" in l)
        assert sea_line.endswith("4")
        assert ath_line.endswith("2")

    def test_missing_half_inning_shown_as_X(self, linescore_rows):
        # Bottom of 9th not played — SEA has no inning-9 row
        text = format_linescore_text(linescore_rows, "ATH", "SEA")
        sea_line = next(l for l in text.splitlines() if "SEA" in l)
        assert "X" in sea_line

    def test_returns_string(self, linescore_rows):
        assert isinstance(format_linescore_text(linescore_rows, "ATH", "SEA"), str)

    def test_nine_columns_minimum(self, linescore_rows):
        text = format_linescore_text(linescore_rows, "ATH", "SEA")
        header = text.splitlines()[0]
        # Header should reference at least innings 1-9
        for i in range(1, 10):
            assert str(i) in header

    def test_extra_inning_extends_header(self):
        rows = [
            {"inning": i, "team": "SEA", "runs": 0, "hits": 0, "errors": 0}
            for i in range(1, 11)
        ] + [
            {"inning": i, "team": "ATH", "runs": 0, "hits": 0, "errors": 0}
            for i in range(1, 11)
        ]
        rows[-1]["runs"] = 1  # ATH scores in 10th
        text = format_linescore_text(rows, "ATH", "SEA")
        assert "10" in text.splitlines()[0]

    def test_empty_rows_returns_string(self):
        text = format_linescore_text([], "ATH", "SEA")
        # Should not raise; returns a header + two X-filled lines
        assert isinstance(text, str)


# ── format_batting_text ────────────────────────────────────────────────────────

class TestFormatBattingText:

    def test_sea_players_present(self, batting_rows):
        text = format_batting_text(batting_rows, "SEA")
        assert "Julio Rodriguez" in text
        assert "Cal Raleigh" in text

    def test_ath_players_excluded(self, batting_rows):
        text = format_batting_text(batting_rows, "SEA")
        assert "José Leclerc" not in text

    def test_hits_and_at_bats_format(self, batting_rows):
        text = format_batting_text(batting_rows, "SEA")
        assert "2-for-4" in text   # Julio: 2 H, 4 AB
        assert "1-for-3" in text   # Cal: 1 H, 3 AB

    def test_hr_shown_when_nonzero(self, batting_rows):
        text = format_batting_text(batting_rows, "SEA")
        assert "1 HR" in text

    def test_rbi_shown_when_nonzero(self, batting_rows):
        text = format_batting_text(batting_rows, "SEA")
        assert "2 RBI" in text    # Julio has 2 RBI

    def test_bb_shown_when_nonzero(self, batting_rows):
        text = format_batting_text(batting_rows, "SEA")
        assert "1 BB" in text     # Cal has 1 BB

    def test_zero_stats_not_shown(self, batting_rows):
        # Julio has 0 BB — should NOT show "0 BB"
        text = format_batting_text(batting_rows, "SEA")
        assert "0 BB" not in text
        assert "0 HR" not in text

    def test_sorted_by_batting_order(self, batting_rows):
        text = format_batting_text(batting_rows, "SEA")
        julio_pos = text.index("Julio Rodriguez")
        cal_pos = text.index("Cal Raleigh")
        assert julio_pos < cal_pos   # batting_order 100 before 200

    def test_no_sea_players_returns_no_data(self):
        rows = [{"player": "John Doe", "team": "ATH", "batting_order": 100,
                 "ab": 3, "h": 1, "hr": 0, "rbi": 0, "bb": 0, "sb": 0}]
        text = format_batting_text(rows, "SEA")
        assert text == "  (no data)"

    def test_empty_rows_returns_no_data(self):
        assert format_batting_text([], "SEA") == "  (no data)"

    def test_sb_shown_when_nonzero(self):
        rows = [{"player": "Fast Guy", "team": "SEA", "batting_order": 100,
                 "ab": 4, "h": 2, "hr": 0, "rbi": 0, "bb": 0, "sb": 2}]
        text = format_batting_text(rows, "SEA")
        assert "2 SB" in text

    def test_returns_string(self, batting_rows):
        assert isinstance(format_batting_text(batting_rows, "SEA"), str)


# ── format_pitching_text ───────────────────────────────────────────────────────

class TestFormatPitchingText:

    def test_sea_pitchers_present(self, pitching_rows):
        text = format_pitching_text(pitching_rows, "SEA")
        assert "Logan Gilbert" in text
        assert "Trent Thornton" in text
        assert "Andrés Muñoz" in text

    def test_ath_pitchers_excluded(self, pitching_rows):
        text = format_pitching_text(pitching_rows, "SEA")
        assert "Luis Severino" not in text

    def test_ip_in_output(self, pitching_rows):
        text = format_pitching_text(pitching_rows, "SEA")
        assert "7.0 IP" in text   # Gilbert
        assert "1.0 IP" in text   # Thornton / Muñoz

    def test_strikeouts_shown_as_K(self, pitching_rows):
        text = format_pitching_text(pitching_rows, "SEA")
        assert "8 K" in text     # Gilbert

    def test_win_decision_shown(self, pitching_rows):
        text = format_pitching_text(pitching_rows, "SEA")
        assert "(W)" in text

    def test_save_decision_shown(self, pitching_rows):
        text = format_pitching_text(pitching_rows, "SEA")
        assert "(S)" in text

    def test_no_decision_not_shown(self, pitching_rows):
        # Gilbert has note=None → no parenthetical
        text = format_pitching_text(pitching_rows, "SEA")
        lines = [l for l in text.splitlines() if "Logan Gilbert" in l]
        assert len(lines) == 1
        assert "(" not in lines[0]

    def test_pitch_count_shown(self, pitching_rows):
        text = format_pitching_text(pitching_rows, "SEA")
        assert "83P" in text    # Gilbert threw 83 pitches

    def test_pitch_count_omitted_when_none(self):
        rows = [{"player": "Mystery Arm", "team": "SEA", "pitch_order": 1,
                 "ip": "1.0", "h": 0, "r": 0, "er": 0, "bb": 0, "so": 1,
                 "hr": 0, "pitches": None, "note": None}]
        text = format_pitching_text(rows, "SEA")
        # A pitch count would appear as e.g. ", 83P" — check no digit precedes P
        import re
        assert not re.search(r"\d+P", text)

    def test_sorted_by_pitch_order(self, pitching_rows):
        text = format_pitching_text(pitching_rows, "SEA")
        gilbert_pos  = text.index("Logan Gilbert")
        thornton_pos = text.index("Trent Thornton")
        munoz_pos    = text.index("Andrés Muñoz")
        assert gilbert_pos < thornton_pos < munoz_pos

    def test_no_sea_pitchers_returns_no_data(self):
        rows = [{"player": "Other Guy", "team": "ATH", "pitch_order": 1,
                 "ip": "6.0", "h": 5, "r": 2, "er": 2, "bb": 1, "so": 4,
                 "hr": 0, "pitches": 90, "note": "L"}]
        text = format_pitching_text(rows, "SEA")
        assert text == "  (no data)"

    def test_empty_rows_returns_no_data(self):
        assert format_pitching_text([], "SEA") == "  (no data)"

    def test_returns_string(self, pitching_rows):
        assert isinstance(format_pitching_text(pitching_rows, "SEA"), str)
