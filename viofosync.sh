#!/usr/bin/env bash
set -u

env_enabled() {
    case "${1:-}" in
        ""|0|false|False|FALSE|no|No|NO)
            return 1
            ;;
        *)
            return 0
            ;;
    esac
}

args=()
app_dir="${APP_DIR:-/app}"
python_bin="${PYTHON_BIN:-python3}"

if [[ -n ${ADDRESS:-} ]]; then
    args+=("$ADDRESS")
fi

args+=(--destination /recordings)

if [[ -n ${KEEP:-} ]]; then
    args+=(--keep "$KEEP")
fi

if [[ -n ${GROUPING:-} ]]; then
    args+=(--grouping "$GROUPING")
fi

if [[ -n ${PRIORITY:-} ]]; then
    args+=(--priority "$PRIORITY")
fi

if [[ -n ${MAX_USED_DISK:-} ]]; then
    args+=(--max-used-disk "$MAX_USED_DISK")
fi

if [[ -n ${TIMEOUT:-} ]]; then
    args+=(--timeout "$TIMEOUT")
fi

if [[ -n ${DOWNLOAD_ATTEMPTS:-} ]]; then
    args+=(--download-attempts "$DOWNLOAD_ATTEMPTS")
fi

if [[ ${VERBOSE:-0} =~ ^[0-9]+$ ]] && [[ ${VERBOSE:-0} -gt 0 ]]; then
    for _ in $(seq 1 "$VERBOSE"); do
        args+=(--verbose)
    done
fi

if env_enabled "${QUIET:-}"; then
    args+=(--quiet)
fi

if env_enabled "${READ_ONLY:-}"; then
    args+=(--read-only)
fi

if env_enabled "${CRON:-}"; then
    args+=(--cron)
fi

if env_enabled "${DRY_RUN:-}"; then
    args+=(--dry-run)
fi

if env_enabled "${GPS_EXTRACT:-}"; then
    args+=(--gps-extract)
fi

if env_enabled "${HTML:-}"; then
    args+=(--html)
fi

if env_enabled "${DELETE_AFTER_SYNC:-}"; then
    args+=(--delete-after-sync)
fi

if [[ -n ${IMPORT_SOURCE:-} ]]; then
    args+=(--import-source "$IMPORT_SOURCE")
fi

if env_enabled "${MOVE_IMPORTED:-}"; then
    args+=(--move-imported)
fi

if env_enabled "${MERGE_CHUNKS:-}"; then
    args+=(--merge-chunks)
fi

if [[ -n ${MERGE_GAP:-} ]]; then
    args+=(--merge-gap "$MERGE_GAP")
fi

if [[ -n ${MERGED_DESTINATION:-} ]]; then
    args+=(--merged-destination "$MERGED_DESTINATION")
fi

if env_enabled "${DELETE_MERGED_SOURCES:-}"; then
    args+=(--delete-merged-sources)
fi

exec "$python_bin" "$app_dir/viofosync.py" "${args[@]}" "$@"
