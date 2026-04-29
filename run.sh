#!/usr/bin/env bash

docker run -it --rm \
    -e ADDRESS=dashcam.local \
    -v "$(pwd)/tmp:/recordings" \
    -e DRY_RUN=1 \
    -e RUN_ONCE=1 \
    -e VERBOSE=1 \
    --name viofosync \
    tt99112/viofosync:latest
