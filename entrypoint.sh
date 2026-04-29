#!/usr/bin/env bash
set -e

/setuid.sh \
&& su -m dashcam /viofosync.sh

if [[ -z $RUN_ONCE ]]; then
    crond -f
fi
