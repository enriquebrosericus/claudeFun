-- MLB Stats Tracker — PostgreSQL Schema
-- Tables use (date, team/player_id, season, game_type) as natural primary keys.
-- game_type: 'R' = regular season, 'S' = spring training
-- Scraper UPSERTs today's row each cycle; backfill scripts populate history.

CREATE TABLE IF NOT EXISTS team_stats (
    date         DATE         NOT NULL,
    season       SMALLINT     NOT NULL,
    team         VARCHAR(10)  NOT NULL,
    team_id      INT          NOT NULL,
    game_type    VARCHAR(2)   NOT NULL DEFAULT 'R',
    division     VARCHAR(50),
    wins         INT          NOT NULL DEFAULT 0,
    losses       INT          NOT NULL DEFAULT 0,
    win_pct      NUMERIC(5,3),
    games_behind NUMERIC(4,1) NOT NULL DEFAULT 0,
    runs_scored  INT,
    runs_allowed INT,
    streak       INT,          -- positive = win streak, negative = loss streak
    last10_wins  INT,
    home_wins    INT,
    away_wins    INT,
    PRIMARY KEY (date, team, season, game_type)
);

CREATE TABLE IF NOT EXISTS division_standings (
    date         DATE         NOT NULL,
    season       SMALLINT     NOT NULL,
    team         VARCHAR(10)  NOT NULL,
    team_id      INT          NOT NULL,
    game_type    VARCHAR(2)   NOT NULL DEFAULT 'R',
    division     VARCHAR(50)  NOT NULL,
    wins         INT          NOT NULL DEFAULT 0,
    losses       INT          NOT NULL DEFAULT 0,
    games_behind NUMERIC(4,1) NOT NULL DEFAULT 0,
    PRIMARY KEY (date, team, season, game_type)
);

CREATE TABLE IF NOT EXISTS player_batting (
    date         DATE          NOT NULL,
    season       SMALLINT      NOT NULL,
    player       VARCHAR(100)  NOT NULL,
    player_id    INT           NOT NULL,
    team         VARCHAR(10)   NOT NULL,
    game_type    VARCHAR(2)    NOT NULL DEFAULT 'R',
    position     VARCHAR(10),
    games_played INT,
    at_bats      INT,
    hits         INT,
    home_runs    INT,
    rbi          INT,
    runs         INT,
    walks        INT,
    strikeouts   INT,
    stolen_bases INT,
    doubles      INT,
    triples      INT,
    avg          NUMERIC(5,3),
    obp          NUMERIC(5,3),
    slg          NUMERIC(5,3),
    ops          NUMERIC(5,3),
    babip        NUMERIC(5,3),
    iso          NUMERIC(5,3),
    PRIMARY KEY (date, player_id, season, game_type)
);

CREATE TABLE IF NOT EXISTS player_pitching (
    date              DATE          NOT NULL,
    season            SMALLINT      NOT NULL,
    player            VARCHAR(100)  NOT NULL,
    player_id         INT           NOT NULL,
    team              VARCHAR(10)   NOT NULL,
    game_type         VARCHAR(2)    NOT NULL DEFAULT 'R',
    position          VARCHAR(10),
    games             INT,
    wins              INT,
    losses            INT,
    saves             INT,
    holds             INT,
    quality_starts    INT,
    innings_pitched   NUMERIC(6,1),
    strikeouts        INT,
    walks             INT,
    home_runs_allowed INT,
    earned_runs       INT,
    era               NUMERIC(5,2),
    whip              NUMERIC(5,3),
    k9                NUMERIC(5,2),
    bb9               NUMERIC(5,2),
    hr9               NUMERIC(5,2),
    fip               NUMERIC(5,2),
    PRIMARY KEY (date, player_id, season, game_type)
);

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_team_stats_team_season   ON team_stats (team, season, date);
CREATE INDEX IF NOT EXISTS idx_div_standings_season     ON division_standings (season, date);
CREATE INDEX IF NOT EXISTS idx_batting_player_season    ON player_batting (player_id, season, date);
CREATE INDEX IF NOT EXISTS idx_batting_team_season      ON player_batting (team, season, date);
CREATE INDEX IF NOT EXISTS idx_pitching_player_season   ON player_pitching (player_id, season, date);
CREATE INDEX IF NOT EXISTS idx_pitching_team_season     ON player_pitching (team, season, date);

-- ── Game recap tables ─────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS games (
    gamepk           INT          PRIMARY KEY,
    date             DATE         NOT NULL,
    season           SMALLINT     NOT NULL,
    game_number      INT          NOT NULL,
    game_type        VARCHAR(2)   NOT NULL DEFAULT 'R',
    doubleheader     VARCHAR(2)   NOT NULL DEFAULT 'N',
    home_team        VARCHAR(10)  NOT NULL,
    away_team        VARCHAR(10)  NOT NULL,
    home_score       INT,
    away_score       INT,
    sea_score        INT,
    opp_score        INT,
    opponent         VARCHAR(10),
    result           VARCHAR(1),   -- 'W' or 'L'
    venue            VARCHAR(200),
    winning_pitcher  VARCHAR(100),
    losing_pitcher   VARCHAR(100),
    save_pitcher     VARCHAR(100),
    status           VARCHAR(50)
);

CREATE TABLE IF NOT EXISTS game_batting_lines (
    gamepk       INT          NOT NULL REFERENCES games(gamepk) ON DELETE CASCADE,
    player_id    INT          NOT NULL,
    player       VARCHAR(100) NOT NULL,
    team         VARCHAR(10)  NOT NULL,
    batting_order INT,
    ab           INT          NOT NULL DEFAULT 0,
    r            INT          NOT NULL DEFAULT 0,
    h            INT          NOT NULL DEFAULT 0,
    doubles      INT          NOT NULL DEFAULT 0,
    triples      INT          NOT NULL DEFAULT 0,
    hr           INT          NOT NULL DEFAULT 0,
    rbi          INT          NOT NULL DEFAULT 0,
    bb           INT          NOT NULL DEFAULT 0,
    so           INT          NOT NULL DEFAULT 0,
    sb           INT          NOT NULL DEFAULT 0,
    lob          INT          NOT NULL DEFAULT 0,
    PRIMARY KEY (gamepk, player_id)
);

CREATE TABLE IF NOT EXISTS game_pitching_lines (
    gamepk      INT          NOT NULL REFERENCES games(gamepk) ON DELETE CASCADE,
    player_id   INT          NOT NULL,
    player      VARCHAR(100) NOT NULL,
    team        VARCHAR(10)  NOT NULL,
    pitch_order INT          NOT NULL DEFAULT 1,
    ip          VARCHAR(10),
    h           INT          NOT NULL DEFAULT 0,
    r           INT          NOT NULL DEFAULT 0,
    er          INT          NOT NULL DEFAULT 0,
    bb          INT          NOT NULL DEFAULT 0,
    so          INT          NOT NULL DEFAULT 0,
    hr          INT          NOT NULL DEFAULT 0,
    pitches     INT,
    strikes     INT,
    era         NUMERIC(5,2),
    note        VARCHAR(5),   -- 'W', 'L', 'S'
    PRIMARY KEY (gamepk, player_id)
);

CREATE TABLE IF NOT EXISTS game_linescore (
    gamepk  INT         NOT NULL REFERENCES games(gamepk) ON DELETE CASCADE,
    inning  INT         NOT NULL,
    team    VARCHAR(10) NOT NULL,
    runs    INT         NOT NULL DEFAULT 0,
    hits    INT         NOT NULL DEFAULT 0,
    errors  INT         NOT NULL DEFAULT 0,
    PRIMARY KEY (gamepk, inning, team)
);

CREATE TABLE IF NOT EXISTS game_summaries (
    gamepk       INT          PRIMARY KEY REFERENCES games(gamepk) ON DELETE CASCADE,
    summary_text TEXT         NOT NULL,
    generated_at TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    model        VARCHAR(100)
);

CREATE INDEX IF NOT EXISTS idx_games_season_date ON games (season, date);
CREATE INDEX IF NOT EXISTS idx_games_season_team ON games (season, home_team, away_team);
