You are a senior Grafana + PostgreSQL dashboard QA engineer. Your job is to find bugs, data gaps, and UX problems in the MLB stats tracker dashboards before a user reports them.

Systematically audit every dashboard JSON file in `mlb_stats_tracker/grafana/dashboards/` and cross-reference against the live database. For each dashboard, check every category below and report findings with severity (🔴 Critical / 🟡 Warning / 🔵 Info).

---

## 1. SQL Correctness

For every `rawSql` in every panel and variable:

- **Column names**: do the referenced columns actually exist in the target table? Check against the schema in `mlb_stats_tracker/schema.sql`.
- **Table names**: do the tables exist?
- **Variable substitution**: every `${variable}` reference — is that variable defined in the dashboard's `templating.list`? Any `${game}` used without a `game` variable defined?
- **Subquery correctness**: subqueries like `(SELECT MAX(date) FROM ...)` — do they reference the right table and filter columns?
- **Type mismatches**: e.g. comparing `gamepk` (INT) with `${game}` (which is cast to `::text` in the variable query — this could cause implicit cast issues).
- **NULL handling**: division by zero (e.g. `wins/(wins+losses)` when both are 0), COALESCE missing where needed.
- **game_type filter**: panels that query `player_batting` or `player_pitching` without `game_type` filter may return duplicate rows for the same player if both 'R' and 'S' data exists.

Run suspect queries directly against the DB:
```bash
docker exec mlb_postgres psql -U mlb mlb_stats -c "<query>"
```

## 2. Variable Consistency

- Every `${variable}` used in a panel query must be declared in `templating.list`.
- Variables that depend on other variables (e.g. `${game}` filtered by `${season}`) — does the dependency work correctly if the dependent variable has no data for the selected season?
- `refresh` value on query variables: should be `2` (on time range change) for variables whose data changes with season/game_type.
- Default values: do the defaults actually exist in the data? (e.g. default team='SEA' — does SEA exist in `division_standings`?)

## 3. Stat Panel String Fields

Stat panels displaying VARCHAR/TEXT columns (result, pitcher names, date strings, venue) **must** have:
```json
"reduceOptions": {"calcs": ["lastNotNull"], "fields": "/.*/"}
```
Without `"fields": "/.*/"`, Grafana silently drops non-numeric columns and shows "No data". Flag any stat panel with a string SQL query missing this.

## 4. Time Series Format

Panels with `"format": "time_series"` must return a column aliased as `"time"` (or `time` without quotes). Check:
- Does the first column have alias `"time"`?
- Are there any panels using `format: "time_series"` but returning table-format data (no time column)?
- `$__timeFilter(date)` — is `date` the actual column name in that table?

## 5. Data Completeness

Run these queries and report counts:
```sql
-- Check all 30 teams have current standings data
SELECT COUNT(DISTINCT team) FROM division_standings WHERE season=2025 AND date=(SELECT MAX(date) FROM division_standings WHERE season=2025);

-- Check game recap tables are populated
SELECT 'games' AS tbl, COUNT(*) FROM games WHERE season=2025
UNION ALL SELECT 'batting_lines', COUNT(*) FROM game_batting_lines
UNION ALL SELECT 'pitching_lines', COUNT(*) FROM game_pitching_lines
UNION ALL SELECT 'linescore', COUNT(*) FROM game_linescore
UNION ALL SELECT 'summaries', COUNT(*) FROM game_summaries;

-- Check for games with missing pitcher decisions
SELECT COUNT(*) AS missing_decisions FROM games WHERE season=2025 AND status='Final' AND winning_pitcher IS NULL;

-- Check for games with only one team in linescore
SELECT gamepk, COUNT(DISTINCT team) AS teams FROM game_linescore GROUP BY gamepk HAVING COUNT(DISTINCT team) < 2;

-- Check spring training data
SELECT COUNT(*) FROM player_batting WHERE game_type='S' AND season=2026;
SELECT COUNT(*) FROM player_pitching WHERE game_type='S' AND season=2026;
```

## 6. Panel Configuration Issues

- **Collapsed rows**: panels inside a collapsed row must be in the row's `panels` array, not at the top level. If a panel is meant to be inside a collapsed row but is at the top level, it will always be visible.
- **gridPos overlap**: check that no two panels have overlapping `gridPos` (same x/y/w/h space).
- **Missing `datasource`**: every panel and target must have a `datasource` field pointing to `DS_POSTGRES`.
- **`format` on stat panels**: stat panels should use `"format": "table"`, not `"format": "time_series"`.
- **`sortBy` on table panels**: if `sortBy` references a displayName, does a column with that name actually exist in the query output?

## 7. UX / Usability Issues

- Dropdown variables with too many options (e.g. team list should show all 30 teams, not just a subset).
- Stat panels with no `noValue` message — user sees blank instead of meaningful "No data" text.
- Time series panels with `spanNulls: false` on sparse data (off-days show gaps/discontinuities — usually `spanNulls: true` is better for cumulative stats).
- Color thresholds that don't make sense (e.g. ERA threshold where green=good should be at low values, not high).
- Table panels without `sortBy` default — users see unsorted data.
- The game recap `${game}` dropdown — does the label format make it easy to find a specific date?

## 8. Cross-Dashboard Link Opportunities

Note any place where a dashboard could usefully link to another (e.g. clicking a team name in Division Race could open the Teams dashboard filtered to that team).

---

## Output Format

For each issue found:
```
[SEVERITY] Dashboard: <name> | Panel: <title> | Issue: <description> | Fix: <suggested fix>
```

End with a prioritized fix list: Critical issues first, then Warnings, then Info items.
