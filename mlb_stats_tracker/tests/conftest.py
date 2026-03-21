"""
Shared pytest fixtures — realistic MLB API response data for unit tests.
All data is based on game 778547 (2025-03-28: SEA 4, ATH 2, Opening Day).
"""
import pytest


TEAM_ABBR_MAP = {136: "SEA", 133: "ATH", 117: "HOU", 140: "TEX"}

SEA_ID = 136
ATH_ID = 133


@pytest.fixture
def abbr_map():
    return dict(TEAM_ABBR_MAP)


@pytest.fixture
def boxscore():
    """Minimal but realistic MLB API boxscore for SEA(home) vs ATH(away), SEA wins 4-2."""
    return {
        "teams": {
            "home": {
                "team": {"id": SEA_ID},
                "batters": [677594, 663728, 665742],
                "pitchers": [669302, 663423, 662253],
                "players": {
                    # Julio Rodriguez — 2-for-4, HR, 2 RBI
                    "ID677594": {
                        "person": {"id": 677594, "fullName": "Julio Rodriguez"},
                        "battingOrder": "100",
                        "stats": {
                            "batting": {
                                "atBats": 4, "runs": 2, "hits": 2,
                                "doubles": 0, "triples": 0, "homeRuns": 1,
                                "rbi": 2, "baseOnBalls": 0, "strikeOuts": 1,
                                "stolenBases": 0, "leftOnBase": 1,
                            }
                        },
                    },
                    # Cal Raleigh — 1-for-3, BB
                    "ID663728": {
                        "person": {"id": 663728, "fullName": "Cal Raleigh"},
                        "battingOrder": "200",
                        "stats": {
                            "batting": {
                                "atBats": 3, "runs": 1, "hits": 1,
                                "doubles": 1, "triples": 0, "homeRuns": 0,
                                "rbi": 1, "baseOnBalls": 1, "strikeOuts": 0,
                                "stolenBases": 0, "leftOnBase": 2,
                            }
                        },
                    },
                    # Mitch Garver — 0-for-3 (pinch runner with no batting stats)
                    "ID665742": {
                        "person": {"id": 665742, "fullName": "Mitch Garver"},
                        "battingOrder": None,
                        "stats": {"batting": {}},
                    },
                    # Logan Gilbert — starter (7 IP, 1 ER)
                    "ID669302": {
                        "person": {"id": 669302, "fullName": "Logan Gilbert"},
                        "stats": {
                            "pitching": {
                                "inningsPitched": "7.0", "hits": 2, "runs": 1,
                                "earnedRuns": 1, "baseOnBalls": 0, "strikeOuts": 8,
                                "homeRuns": 1, "pitchesThrown": 83, "strikes": 60,
                                "era": "1.29",
                            }
                        },
                    },
                    # Trent Thornton — 1 IP (winning pitcher)
                    "ID663423": {
                        "person": {"id": 663423, "fullName": "Trent Thornton"},
                        "stats": {
                            "pitching": {
                                "inningsPitched": "1.0", "hits": 0, "runs": 0,
                                "earnedRuns": 0, "baseOnBalls": 0, "strikeOuts": 1,
                                "homeRuns": 0, "pitchesThrown": 12, "strikes": 9,
                                "era": "0.00",
                            }
                        },
                    },
                    # Andrés Muñoz — 1 IP, save
                    "ID662253": {
                        "person": {"id": 662253, "fullName": "Andrés Muñoz"},
                        "stats": {
                            "pitching": {
                                "inningsPitched": "1.0", "hits": 0, "runs": 0,
                                "earnedRuns": 0, "baseOnBalls": 0, "strikeOuts": 2,
                                "homeRuns": 0, "pitchesThrown": 14, "strikes": 11,
                                "era": "0.00",
                            }
                        },
                    },
                },
            },
            "away": {
                "team": {"id": ATH_ID},
                "batters": [600917, 641355],
                "pitchers": [622663],
                "players": {
                    # José Leclerc — losing pitcher (ATH batter slot for test)
                    "ID600917": {
                        "person": {"id": 600917, "fullName": "José Leclerc"},
                        "battingOrder": "100",
                        "stats": {
                            "batting": {
                                "atBats": 4, "runs": 1, "hits": 1,
                                "doubles": 0, "triples": 0, "homeRuns": 1,
                                "rbi": 1, "baseOnBalls": 0, "strikeOuts": 2,
                                "stolenBases": 0, "leftOnBase": 3,
                            }
                        },
                    },
                    "ID641355": {
                        "person": {"id": 641355, "fullName": "Brent Rooker"},
                        "battingOrder": "200",
                        "stats": {
                            "batting": {
                                "atBats": 3, "runs": 0, "hits": 0,
                                "doubles": 0, "triples": 0, "homeRuns": 0,
                                "rbi": 0, "baseOnBalls": 1, "strikeOuts": 1,
                                "stolenBases": 1, "leftOnBase": 1,
                            }
                        },
                    },
                    # Luis Severino — losing pitcher
                    "ID622663": {
                        "person": {"id": 622663, "fullName": "Luis Severino"},
                        "stats": {
                            "pitching": {
                                "inningsPitched": "6.0", "hits": 3, "runs": 3,
                                "earnedRuns": 3, "baseOnBalls": 4, "strikeOuts": 6,
                                "homeRuns": 1, "pitchesThrown": 99, "strikes": 57,
                                "era": "4.50",
                            }
                        },
                    },
                },
            },
        }
    }


@pytest.fixture
def decisions():
    return {
        "winner": {"id": 663423, "fullName": "Trent Thornton"},
        "loser":  {"id": 622663, "fullName": "Luis Severino"},
        "save":   {"id": 662253, "fullName": "Andrés Muñoz"},
    }


@pytest.fixture
def linescore():
    """SEA (home) wins 4-2. Bottom of 9th not played (SEA led going in)."""
    return {
        "teams": {
            "home": {"runs": 4, "hits": 7, "errors": 0},
            "away": {"runs": 2, "hits": 4, "errors": 1},
        },
        "innings": [
            {"num": 1, "home": {"runs": 0, "hits": 0, "errors": 0},
                       "away": {"runs": 0, "hits": 0, "errors": 0}},
            {"num": 2, "home": {"runs": 0, "hits": 1, "errors": 0},
                       "away": {"runs": 0, "hits": 0, "errors": 0}},
            {"num": 3, "home": {"runs": 0, "hits": 0, "errors": 0},
                       "away": {"runs": 0, "hits": 1, "errors": 1}},
            {"num": 4, "home": {"runs": 0, "hits": 1, "errors": 0},
                       "away": {"runs": 0, "hits": 0, "errors": 0}},
            {"num": 5, "home": {"runs": 0, "hits": 0, "errors": 0},
                       "away": {"runs": 1, "hits": 1, "errors": 0}},
            {"num": 6, "home": {"runs": 0, "hits": 1, "errors": 0},
                       "away": {"runs": 0, "hits": 0, "errors": 0}},
            {"num": 7, "home": {"runs": 1, "hits": 0, "errors": 0},
                       "away": {"runs": 0, "hits": 0, "errors": 0}},
            {"num": 8, "home": {"runs": 3, "hits": 2, "errors": 0},
                       "away": {"runs": 1, "hits": 1, "errors": 0}},
            # Bottom of 9th not played — only away half exists
            {"num": 9, "away": {"runs": 0, "hits": 1, "errors": 0}},
        ],
    }


@pytest.fixture
def batting_rows():
    """Pre-parsed batting rows as returned by parse_batting_lines."""
    return [
        {"player_id": 677594, "player": "Julio Rodriguez", "team": "SEA",
         "batting_order": 100, "ab": 4, "r": 2, "h": 2, "doubles": 0,
         "triples": 0, "hr": 1, "rbi": 2, "bb": 0, "so": 1, "sb": 0, "lob": 1},
        {"player_id": 663728, "player": "Cal Raleigh", "team": "SEA",
         "batting_order": 200, "ab": 3, "r": 1, "h": 1, "doubles": 1,
         "triples": 0, "hr": 0, "rbi": 1, "bb": 1, "so": 0, "sb": 0, "lob": 2},
        {"player_id": 600917, "player": "José Leclerc", "team": "ATH",
         "batting_order": 100, "ab": 4, "r": 1, "h": 1, "doubles": 0,
         "triples": 0, "hr": 1, "rbi": 1, "bb": 0, "so": 2, "sb": 0, "lob": 3},
    ]


@pytest.fixture
def pitching_rows():
    """Pre-parsed pitching rows as returned by parse_pitching_lines."""
    return [
        {"player_id": 669302, "player": "Logan Gilbert", "team": "SEA",
         "pitch_order": 1, "ip": "7.0", "h": 2, "r": 1, "er": 1,
         "bb": 0, "so": 8, "hr": 1, "pitches": 83, "strikes": 60,
         "era": 1.29, "note": None},
        {"player_id": 663423, "player": "Trent Thornton", "team": "SEA",
         "pitch_order": 2, "ip": "1.0", "h": 0, "r": 0, "er": 0,
         "bb": 0, "so": 1, "hr": 0, "pitches": 12, "strikes": 9,
         "era": 0.0, "note": "W"},
        {"player_id": 662253, "player": "Andrés Muñoz", "team": "SEA",
         "pitch_order": 3, "ip": "1.0", "h": 0, "r": 0, "er": 0,
         "bb": 0, "so": 2, "hr": 0, "pitches": 14, "strikes": 11,
         "era": 0.0, "note": "S"},
        {"player_id": 622663, "player": "Luis Severino", "team": "ATH",
         "pitch_order": 1, "ip": "6.0", "h": 3, "r": 3, "er": 3,
         "bb": 4, "so": 6, "hr": 1, "pitches": 99, "strikes": 57,
         "era": 4.50, "note": "L"},
    ]


@pytest.fixture
def linescore_rows():
    """Pre-parsed linescore rows as returned by parse_linescore."""
    return [
        {"inning": 1, "team": "SEA", "runs": 0, "hits": 0, "errors": 0},
        {"inning": 1, "team": "ATH", "runs": 0, "hits": 0, "errors": 0},
        {"inning": 2, "team": "SEA", "runs": 0, "hits": 1, "errors": 0},
        {"inning": 2, "team": "ATH", "runs": 0, "hits": 0, "errors": 0},
        {"inning": 3, "team": "SEA", "runs": 0, "hits": 0, "errors": 0},
        {"inning": 3, "team": "ATH", "runs": 0, "hits": 1, "errors": 1},
        {"inning": 5, "team": "ATH", "runs": 1, "hits": 1, "errors": 0},
        {"inning": 7, "team": "SEA", "runs": 1, "hits": 0, "errors": 0},
        {"inning": 8, "team": "SEA", "runs": 3, "hits": 2, "errors": 0},
        {"inning": 8, "team": "ATH", "runs": 1, "hits": 1, "errors": 0},
        {"inning": 9, "team": "ATH", "runs": 0, "hits": 1, "errors": 0},
    ]
