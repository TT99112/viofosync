# CHANGELOG

## 1.2 (2026-04-28)

* Add `DELETE_AFTER_SYNC` / `--delete-after-sync`: optionally delete each file from the camera immediately after it has been successfully downloaded and the local copy verified. Read-only/locked files (`/RO/` folder or attr=33) are always skipped. Deletion is safe under `--dry-run`.

## 1.1

* Make download attempts configurable via `DOWNLOAD_ATTEMPTS` / `--download-attempts`

## 1.0 (2024-09-18)

* initial release
