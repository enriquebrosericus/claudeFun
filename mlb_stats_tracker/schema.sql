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
