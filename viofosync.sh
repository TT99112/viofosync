#!/usr/bin/env bash

args=()

if [[ -n $ADDRESS ]]; then
    args+=("$ADDRESS")
fi

args+=(--destination /recordings)

if [[ -n $KEEP ]]; then
    args+=(--keep "$KEEP")
fi

if [[ -n $GROUPING ]]; then
    args+=(--grouping "$GROUPING")
fi

if [[ -n $PRIORITY ]]; then
    args+=(--priority "$PRIORITY")
fi

if [[ -n $MAX_USED_DISK ]]; then
    args+=(--max-used-disk "$MAX_USED_DISK")
fi

if [[ -n $TIMEOUT ]]; then
    args+=(--timeout "$TIMEOUT")
fi

if [[ -n $DOWNLOAD_ATTEMPTS ]]; then
    args+=(--download-attempts "$DOWNLOAD_ATTEMPTS")
fi

if [[ ${VERBOSE:-0} =~ ^[0-9]+$ ]] && [[ ${VERBOSE:-0} -gt 0 ]]; then
    for _ in $(seq 1 "$VERBOSE"); do
        args+=(--verbose)
    done
fi

if [[ -n $QUIET ]]; then
    args+=(--quiet)
fi

if [[ -n $READ_ONLY ]]; then
    args+=(--read-only)
fi

if [[ -n $CRON ]]; then
    args+=(--cron)
fi

if [[ -n $DRY_RUN ]]; then
    args+=(--dry-run)
fi

if [[ -n $GPS_EXTRACT ]]; then
    args+=(--gps-extract)
fi

if [[ -n $HTML ]]; then
    args+=(--html)
fi

if [[ -n $DELETE_AFTER_SYNC ]]; then
    args+=(--delete-after-sync)
fi

if [[ -n $IMPORT_SOURCE ]]; then
    args+=(--import-source "$IMPORT_SOURCE")
fi

if [[ -n $MOVE_IMPORTED ]]; then
    args+=(--move-imported)
fi

if [[ -n $MERGE_CHUNKS ]]; then
    args+=(--merge-chunks)
fi

if [[ -n $MERGE_GAP ]]; then
    args+=(--merge-gap "$MERGE_GAP")
fi

if [[ -n $MERGED_DESTINATION ]]; then
    args+=(--merged-destination "$MERGED_DESTINATION")
fi

if [[ -n $DELETE_MERGED_SOURCES ]]; then
    args+=(--delete-merged-sources)
fi

exec /viofosync.py "${args[@]}"
