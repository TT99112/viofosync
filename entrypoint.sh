#!/usr/bin/env bash
set -u

trap 'exit 0' INT TERM

if [[ -n ${RUN_ONCE:-} ]]; then
    exec /app/viofosync.sh "$@"
fi

while true; do
    /app/viofosync.sh "$@" || true
    sleep "${SYNC_INTERVAL:-600}" &
    wait $!
done
