FROM python:3.12-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends bash ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY . /app

RUN chmod +x /app/entrypoint.sh /app/viofosync.sh /app/viofosync.py

ENTRYPOINT ["/app/entrypoint.sh"]
