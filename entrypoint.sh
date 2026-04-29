#!/usr/bin/env bash
set -u

trap 'exit 0' INT TERM
app_dir="${APP_DIR:-/app}"

env_enabled() {
    case "${1:-}" in
        1|true|True|TRUE|yes|Yes|YES|on|On|ON)
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

if env_enabled "${RUN_ONCE:-}"; then
    exec "$app_dir/viofosync.sh" "$@"
fi

while true; do
    "$app_dir/viofosync.sh" "$@" || true
    sleep "${SYNC_INTERVAL:-600}" &
    wait $!
done
