# Viofo Sync

Viofo Sync copies recordings from a Viofo dashcam to a NAS or local folder.

It supports three workflows:

- Wi-Fi sync from the dashcam HTTP interface
- Local import from a mounted SD card, SSD, or copied dashcam folder
- Optional normal-driving clip merging with `ffmpeg`

Parking recordings such as `PF` and `PR` are imported but not merged.

## Quick Start

```yaml
services:
  viofosync:
    image: tt99112/viofosync:latest
    container_name: viofosync
    restart: unless-stopped
    volumes:
      - /dashcam-recordings:/recordings:rw
    environment:
      ADDRESS: 192.168.1.230
      TZ: Europe/London
      GROUPING: daily
      KEEP: 2w
```

Start it:

```bash
docker compose up -d
```

By default the container runs every 10 minutes. Set `RUN_ONCE=1` to run once and exit.

If you do not want root-owned files on the NAS, run the container as your NAS user:

```yaml
user: "1000:1000"
```

## Wi-Fi Sync

Set `ADDRESS` to the dashcam IP or hostname:

```yaml
environment:
  ADDRESS: 192.168.1.230
  GROUPING: daily
```

The dashcam must be powered on and reachable from the NAS. For automated use, station mode Wi-Fi is recommended.

Use `HTML=1` if the XML file listing is slow or unreliable:

```yaml
environment:
  HTML: 1
```

## Local Import

Use this when you remove the SD card or SSD and mount it on the NAS or another machine connected to the NAS.

```yaml
services:
  viofosync:
    image: tt99112/viofosync:latest
    volumes:
      - /dashcam-recordings:/recordings:rw
      - /path/to/dashcam-drive:/import:rw
    environment:
      IMPORT_SOURCE: /import
      GROUPING: daily
      RUN_ONCE: 1
```

Files are copied into `/recordings` by default. Set `MOVE_IMPORTED=1` if you want files removed from the import source after the destination copy is verified.

Direct CLI usage:

```bash
./viofosync.py --import-source /path/to/dashcam-drive \
  --destination /path/to/recordings \
  --grouping daily
```

## Optional Deletion From Dashcam

Deletion is off by default.

Enable it only when you trust the destination:

```yaml
environment:
  DELETE_AFTER_SYNC: 1
```

The script deletes a dashcam file only after the local copy has been verified. Locked/read-only recordings are skipped.

## Optional Clip Merging

Merging is off by default.

Enable it with:

```yaml
environment:
  MERGE_CHUNKS: 1
  MERGE_GAP: 2
```

Merge behavior:

- `F` clips merge only with `F`
- `R` clips merge only with `R`
- `PF` and `PR` parking clips are not merged
- merge groups respect `GROUPING`

For example, with `GROUPING=daily`, a drive that crosses midnight becomes separate merged files for each day.

Merged files are written to `/recordings/merged` unless `MERGED_DESTINATION` is set.

Keep `DELETE_MERGED_SOURCES` disabled until you have checked the merged output:

```yaml
environment:
  DELETE_MERGED_SOURCES: ''
```

## Configuration

| Variable | Default | Description |
|---|---:|---|
| `ADDRESS` | | Dashcam IP or hostname for Wi-Fi sync |
| `IMPORT_SOURCE` | | Local folder to import instead of Wi-Fi sync |
| `GROUPING` | `none` | `none`, `daily`, `weekly`, `monthly`, or `yearly` |
| `KEEP` | | Delete destination recordings older than this, e.g. `30d` or `4w` |
| `PRIORITY` | `date` | `date` for oldest first, `rdate` for newest first |
| `SYNC_INTERVAL` | `600` | Seconds between runs when `RUN_ONCE` is not set |
| `RUN_ONCE` | | Set to `1` to run once and exit |
| `HTML` | | Set to `1` to list files from the dashcam HTML directory pages |
| `READ_ONLY` | | Set to `1` to sync only locked/read-only recordings |
| `GPS_EXTRACT` | | Set to `1` to write `.gpx` files beside recordings |
| `DELETE_AFTER_SYNC` | | Set to `1` to delete verified files from the dashcam |
| `MOVE_IMPORTED` | | Set to `1` to move local import files instead of copying |
| `MERGE_CHUNKS` | | Set to `1` to merge normal driving chunks |
| `MERGE_GAP` | `2` | Allowed seconds between consecutive normal chunks |
| `MERGED_DESTINATION` | `/recordings/merged` | Optional merged-file output folder |
| `DELETE_MERGED_SOURCES` | | Set to `1` to delete source chunks after a merge |
| `MAX_USED_DISK` | `90` | Stop downloading when destination disk usage reaches this percent |
| `TIMEOUT` | `10` | Dashcam connection timeout in seconds |
| `DOWNLOAD_ATTEMPTS` | `1` | Retry attempts per file |
| `VERBOSE` | `0` | Set above `0` for debug logging |
| `QUIET` | | Set to `1` to log only errors |
| `DRY_RUN` | | Set to `1` to show actions without changing files |

Boolean options accept `1`, `true`, or any non-empty value. Use an empty value, `0`, or `false` to disable them.

## Docker Hub Publishing

This repo includes a GitHub Actions workflow that publishes:

```text
tt99112/viofosync:latest
```

on pushes to `main`.

Add these repository secrets in GitHub before publishing:

```text
DOCKER_USERNAME
DOCKER_PASSWORD
```

## Notes

- Viofo filenames provide the recording start time.
- Normal chunk merging uses filename start time plus `ffprobe` duration.
- Parking timelapse duration is not real elapsed time, so parking files stay separate.
- This project is based on BlackVue Sync by Alessandro Colomba and includes Viofo GPS extraction work based on Sergei Franco's research.

## Development

Run the basic local checks:

```bash
python3 -m py_compile viofosync.py
bash -n entrypoint.sh
bash -n viofosync.sh
```

Build the image locally:

```bash
docker build -t viofosync:local .
```

## License

MIT. See [COPYING](COPYING).
