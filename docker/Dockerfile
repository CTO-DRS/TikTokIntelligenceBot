FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# system deps: postgres client libs + Arabic fonts for PDF reports + healthcheck curl
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 curl fonts-noto-core fonts-noto-naskh-arabic \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN useradd -m -u 10001 botuser \
    && mkdir -p /app/data \
    && chown -R botuser:botuser /app
USER botuser

CMD ["python", "bot/main.py"]
