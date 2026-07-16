# syntax=docker/dockerfile:1
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

COPY . .

# Cloud Run injects $PORT (default 8080) -- shell form so it expands.
CMD exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}
