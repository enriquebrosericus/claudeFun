FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir requests psycopg2-binary

COPY scraper.py backfill_standings.py backfill_player_stats.py backfill_spring_training.py backfill_game_recaps.py backfill_challenges.py ./

CMD ["python", "scraper.py"]
