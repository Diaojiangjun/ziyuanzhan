FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DB_PATH=/app/webapp/data/site.db \
    SEED_FILE=/app/docs/data/sources.json \
    ENABLE_MONITOR=1 \
    MONITOR_INTERVAL_MINUTES=120

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY webapp ./webapp
COPY docs/data/sources.json ./docs/data/sources.json

RUN mkdir -p /app/webapp/data
VOLUME ["/app/webapp/data"]

EXPOSE 8000

CMD ["uvicorn", "webapp.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
