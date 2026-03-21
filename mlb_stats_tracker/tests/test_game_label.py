"""
Tests for the game dropdown label expression used in game_recap.json.

The Grafana variable query builds a label like:
    "Mar 28  vs ATH  (W 4-2)"  or  "Apr 04  @ SF  (L 9-10)  (DH)"

When any field in a SQL string concatenation is NULL the whole expression
becomes NULL, causing Grafana to fall back to showing the raw gamepk number.
These tests verify the label logic never returns None/empty for any realistic
game row, including rows with partially-NULL data.
"""

from __future__ import annotations


def make_game_label(row: dict) -> str | None:
    """
    Pure-Python mirror of the SQL label expression used in game_recap.json.

    SQL (simplified):
        TO_CHAR(date,'Mon DD')
        || CASE WHEN doubleheader IN ('Y','S') THEN ' (DH)' ELSE '' END
        || CASE WHEN home_team='SEA' THEN '  vs ' || COALESCE(away_team,'???')
                ELSE '  @ ' || COALESCE(home_team,'???') END
        || '  (' || COALESCE(result,'?') || ' '
                 || COALESCE(sea_score::text,'?') || '-'
                 || COALESCE(opp_score::text,'?') || ')'
    """
    date = row.get("date")
    if date is None:
        return None  # date is the PK; should never be NULL

    import datetime
    if isinstance(date, datetime.date):
        date_str = date.strftime("%b %d")
    else:
        # Accept "YYYY-MM-DD" strings as well
        try:
            date_str = datetime.datetime.strptime(str(date), "%Y-%m-%d").strftime("%b %d")
        except ValueError:
            date_str = str(date)

    dh = " (DH)" if row.get("doubleheader") in ("Y", "S") else ""

    home = row.get("home_team")
    away = row.get("away_team")
    if home == "SEA":
        location = "  vs " + (away or "???")
    else:
        location = "  @ " + (home or "???")

    result   = row.get("result")   or "?"
    sea_score = row.get("sea_score")
    opp_score = row.get("opp_score")
    score_str = f"{sea_score if sea_score is not None else '?'}-{opp_score if opp_score is not None else '?'}"

    return f"{date_str}{dh}{location}  ({result} {score_str})"


# ── fixtures ───────────────────────────────────────────────────────────────────

def _game(overrides=None):
    """Return a minimal complete game row, with optional field overrides."""
    base = {
        "date": "2025-03-28",
        "doubleheader": "N",
        "home_team": "SEA",
        "away_team": "ATH",
        "result": "W",
        "sea_score": 4,
        "opp_score": 2,
    }
    if overrides:
        base.update(overrides)
    return base


# ── happy-path tests ───────────────────────────────────────────────────────────

class TestGameLabelHappyPath:

    def test_home_win_format(self):
        label = make_game_label(_game())
        assert label == "Mar 28  vs ATH  (W 4-2)"

    def test_away_loss_format(self):
        label = make_game_label(_game({"home_team": "SF", "away_team": "SEA",
                                       "result": "L", "sea_score": 9, "opp_score": 10}))
        assert label == "Mar 28  @ SF  (L 9-10)"

    def test_doubleheader_Y_adds_dh(self):
        label = make_game_label(_game({"doubleheader": "Y"}))
        assert "(DH)" in label

    def test_doubleheader_S_adds_dh(self):
        label = make_game_label(_game({"doubleheader": "S"}))
        assert "(DH)" in label

    def test_doubleheader_N_no_dh(self):
        label = make_game_label(_game({"doubleheader": "N"}))
        assert "(DH)" not in label

    def test_date_formatting(self):
        label = make_game_label(_game({"date": "2025-09-28"}))
        assert label.startswith("Sep 28")

    def test_returns_string(self):
        assert isinstance(make_game_label(_game()), str)

    def test_label_not_empty(self):
        assert make_game_label(_game()) != ""


# ── NULL-safety tests (the bug we're guarding against) ────────────────────────

class TestGameLabelNullSafety:
    """
    Any NULL in a SQL string concatenation makes the whole expression NULL.
    Grafana then falls back to showing the raw gamepk number.
    Verify the label is NEVER None even when individual fields are missing.
    """

    def test_null_result_does_not_return_none(self):
        label = make_game_label(_game({"result": None}))
        assert label is not None
        assert "?" in label   # placeholder shown instead

    def test_null_sea_score_does_not_return_none(self):
        label = make_game_label(_game({"sea_score": None}))
        assert label is not None
        assert "?" in label

    def test_null_opp_score_does_not_return_none(self):
        label = make_game_label(_game({"opp_score": None}))
        assert label is not None
        assert "?" in label

    def test_null_away_team_home_game_does_not_return_none(self):
        label = make_game_label(_game({"away_team": None}))
        assert label is not None
        assert "???" in label

    def test_null_home_team_away_game_does_not_return_none(self):
        label = make_game_label(_game({"home_team": None, "away_team": "SEA"}))
        assert label is not None
        assert "???" in label

    def test_null_doubleheader_is_treated_as_non_dh(self):
        label = make_game_label(_game({"doubleheader": None}))
        assert label is not None
        assert "(DH)" not in label

    def test_all_nullable_fields_null_still_returns_label(self):
        row = {
            "date": "2025-03-28",
            "doubleheader": None,
            "home_team": "SEA",
            "away_team": None,
            "result": None,
            "sea_score": None,
            "opp_score": None,
        }
        label = make_game_label(row)
        assert label is not None
        assert isinstance(label, str)
        assert len(label) > 0

    def test_away_game_null_home_team_shows_placeholder(self):
        # SEA is the away team; home_team is used in the label
        row = _game({"home_team": None, "away_team": "SEA",
                     "result": "L", "sea_score": 1, "opp_score": 4})
        label = make_game_label(row)
        assert "???" in label
        assert label is not None


# ── full season coverage test ──────────────────────────────────────────────────

class TestGameLabelFullSeason:
    """Generate representative rows for a full season and verify all labels."""

    def _season_rows(self):
        """162 rows covering home/away, wins/losses, doubleheaders, edge scores."""
        import datetime
        rows = []
        start = datetime.date(2025, 3, 28)
        opponents = ["ATH", "DET", "HOU", "TEX", "SF", "CIN", "TOR", "LAA", "MIN"]
        for i in range(162):
            opp = opponents[i % len(opponents)]
            is_home = (i % 3 != 0)
            rows.append({
                "gamepk": 778547 - i,
                "date": start + datetime.timedelta(days=i // 2),
                "doubleheader": "Y" if (i % 15 == 0) else "N",
                "home_team": "SEA" if is_home else opp,
                "away_team": opp if is_home else "SEA",
                "result": "W" if i % 3 else "L",
                "sea_score": i % 10,
                "opp_score": (i + 1) % 8,
                "game_type": "R",
                "status": "Final",
            })
        return rows

    def test_no_label_is_none(self):
        for row in self._season_rows():
            label = make_game_label(row)
            assert label is not None, f"NULL label for gamepk {row['gamepk']}"

    def test_no_label_is_empty(self):
        for row in self._season_rows():
            label = make_game_label(row)
            assert label != "", f"Empty label for gamepk {row['gamepk']}"

    def test_home_games_contain_vs(self):
        for row in self._season_rows():
            if row["home_team"] == "SEA":
                assert "vs" in make_game_label(row)

    def test_away_games_contain_at(self):
        for row in self._season_rows():
            if row["away_team"] == "SEA":
                assert " @ " in make_game_label(row)

    def test_doubleheader_games_contain_dh(self):
        for row in self._season_rows():
            label = make_game_label(row)
            if row["doubleheader"] in ("Y", "S"):
                assert "(DH)" in label
            else:
                assert "(DH)" not in label
