FROM python:3.13-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir "psycopg[binary]"   # PostgreSQL driver for production

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./alembic.ini
COPY docker-entrypoint.sh ./docker-entrypoint.sh
RUN chmod +x ./docker-entrypoint.sh

EXPOSE 8000
# Entrypoint waits for the DB + applies migrations (Postgres) before starting uvicorn.
ENTRYPOINT ["./docker-entrypoint.sh"]
