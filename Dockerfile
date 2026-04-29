FROM alpine:3.20.3
LABEL maintainer="Rob Smith https://github.com/RobXYZ"

RUN apk add --no-cache bash ffmpeg python3 shadow tzdata \
    && useradd -UMr dashcam

COPY COPYING /
COPY setuid.sh /setuid.sh
COPY entrypoint.sh /entrypoint.sh
COPY crontab /var/spool/cron/crontabs/dashcam

ENV ADDRESS="" \
    PUID="" \
    PGID="" \
    KEEP="" \
    GROUPING="" \
    PRIORITY="" \
    MAX_USED_DISK="" \
    TIMEOUT="" \
    DOWNLOAD_ATTEMPTS="" \
    VERBOSE=0 \
    QUIET="" \
    CRON=1 \
    DRY_RUN="" \
    RUN_ONCE="" \
    READ_ONLY="" \
    GPS_EXTRACT="" \
    HTML="" \
    DELETE_AFTER_SYNC="" \
    IMPORT_SOURCE="" \
    MOVE_IMPORTED="" \
    MERGE_CHUNKS="" \
    MERGE_GAP="" \
    MERGED_DESTINATION="" \
    DELETE_MERGED_SOURCES=""

COPY --chown=dashcam viofosync.sh /viofosync.sh
COPY --chown=dashcam viofosync.py /viofosync.py

RUN sed -i 's/\r$//' /entrypoint.sh /setuid.sh /viofosync.sh /viofosync.py \
    && chmod +x /viofosync.sh

ENTRYPOINT [ "/entrypoint.sh"]
