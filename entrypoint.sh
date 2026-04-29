#!/usr/bin/env bash
set -u

trap 'exit 0' INT TERM
app_dir="${APP_DIR:-/app}"

if [[ -n ${RUN_ONCE:-} ]]; then
    exec "$app_dir/viofosync.sh" "$@"
fi

while true; do
    "$app_dir/viofosync.sh" "$@" || true
    sleep "${SYNC_INTERVAL:-600}" &
    wait $!
done
