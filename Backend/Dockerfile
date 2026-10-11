FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    RANGETRUE_MODELS=/app/models \
    RANGETRUE_DB_PATH=/data/rangetrue.sqlite3

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system app \
    && useradd --system --gid app --home-dir /app app

COPY Backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY Backend/main.py Backend/range_core.py Backend/vehicle_profiles.py ./
COPY Machine_learning/models ./models

RUN mkdir -p /data && chown app:app /data
USER app

EXPOSE 8000
CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
