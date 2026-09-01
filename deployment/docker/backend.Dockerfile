FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /workspace

# P0.3R media workers use the distribution FFmpeg build. Keeping FFmpeg in the
# image makes runtime capability deterministic instead of depending on the host.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY apps/backend ./apps/backend
COPY AI-Features/models ./AI-Features/models
COPY database/migrations ./database/migrations

RUN python -m pip install --no-cache-dir "./apps/backend[analytics]"

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
