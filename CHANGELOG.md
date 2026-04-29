# CHANGELOG

## 1.4 (2026-04-29)

* Add Viofo photo (`.jpg` / `.jpeg`) sync and local import support, including the `/DCIM/Photo` HTML directory.
* Keep GPS extraction and chunk merging video-only.
* Add `DESTINATION` environment support for faster same-volume local imports.
* When both `IMPORT_SOURCE` and `ADDRESS` are set, fall back to Wi-Fi sync when the import source has no Viofo media files.

## 1.3 (2026-04-29)

* Add local import mode via `IMPORT_SOURCE` / `--import-source` for organizing recordings from a mounted SD card, SSD, or copied folder without Wi-Fi sync.
* Add optional `MOVE_IMPORTED` / `--move-imported` to remove local import source files after destination verification.
* Add optional chunk merging via `MERGE_CHUNKS` / `--merge-chunks` using `ffmpeg`, with configurable merge gap, output directory, and source cleanup.
* Merge only normal driving recordings (`F`/`R`), leave parking recordings (`PF`/`PR`) as individual files, respect grouping boundaries, and default chunk merging to a strict 2 second continuity gap.
* Harden delete-after-sync so camera deletion only runs when the local file size was verified.
* Fix `RUN_ONCE` container exit handling after successful one-shot runs.
* Clean up Docker runtime configuration, boolean environment parsing, README, stale helper files, and disk-usage enforcement.

## 1.2 (2026-04-28)

* Add `DELETE_AFTER_SYNC` / `--delete-after-sync`: optionally delete each file from the camera immediately after it has been successfully downloaded and the local copy verified. Read-only/locked files (`/RO/` folder or attr=33) are always skipped. Deletion is safe under `--dry-run`.

## 1.1

* Make download attempts configurable via `DOWNLOAD_ATTEMPTS` / `--download-attempts`

## 1.0 (2024-09-18)

* initial release
