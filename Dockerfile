FROM python:3.12-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends bash ffmpeg \
    && rm -rf /var/lib/apt/lists/*

ENV ADDRESS="" \
    DESTINATION="/recordings" \
    TZ="Europe/London" \
    GROUPING="daily" \
    PRIORITY="date" \
    KEEP="" \
    SYNC_INTERVAL="600" \
    MAX_USED_DISK="90" \
    TIMEOUT="10" \
    DOWNLOAD_ATTEMPTS="1" \
    VERBOSE="0" \
    QUIET="0" \
    HTML="0" \
    READ_ONLY="0" \
    GPS_EXTRACT="0" \
    DELETE_AFTER_SYNC="0" \
    DRY_RUN="0" \
    RUN_ONCE="0" \
    IMPORT_SOURCE="" \
    MOVE_IMPORTED="0" \
    MERGE_CHUNKS="0" \
    MERGE_GAP="2" \
    MERGED_DESTINATION="" \
    DELETE_MERGED_SOURCES="0"

COPY . /app

RUN chmod +x /app/entrypoint.sh /app/viofosync.sh /app/viofosync.py

ENTRYPOINT ["/app/entrypoint.sh"]
