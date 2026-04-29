# Viofo Sync

Viofo Sync is a tool for synchronizing recordings from a Viofo dashcam (tested with A229 Pro) over Wi-Fi to a local directory.

It is designed to be run as a Docker container on a NAS or similar device.

This project is based on the great BlackVue Sync by Alessandro Colomba (https://github.com/acolomba) and uses GPX extraction from https://sergei.nz/extracting-gps-data-from-viofo-a119-and-other-novatek-powered-cameras/

## GPS Extraction

If you have a use for GPX files, they can be extracted from the video using the `GPS_EXTRACT` option detailed below.

## Hardware and Firmware Requirements

The dashcam must remain powered on and connected to Wi-Fi. It is recommended to use a hardwire kit, such as the Viofo HK4, and ideally, a dedicated dashcam battery to prevent draining the car battery.

The dashcam should be connected to the LAN using Wi-Fi station mode.

As of September 2024, the official A229 Pro firmware does not retain the previous Wi-Fi state after a reboot. However, Viofo support has provided special firmware upon request that retains this state. This feature may be officially released in the near future and is recommended to make downloads fully automated.

## Using the Docker Container

To use Viofo Sync as a Docker container, follow these steps:

1. **Install Docker:**

    Download from https://www.docker.com/ if you don't have it already.

2. **Run the Docker Container:**
   ```bash
   docker run -it --rm \
       -e ADDRESS=<DASHCAM_IP> \
       -e PUID=$(id -u) \
       -e PGID=$(id -g) \
       -e TZ="Europe/London" \
       -e KEEP=2w \
       -e GROUPING=daily \
       -v /path/to/local/directory:/recordings \
       --name viofosync \
       robxyz/viofosync
   ```

   Replace `<DASHCAM_IP>` with the IP address of your dashcam and `/path/to/local/directory` with the path to your local directory where recordings will be stored.

## Configuration Options

The following environment variables can be set to configure the behavior of the Viofo Sync Docker container:

| Variable | Description | Default |
|---|---|---|
| `ADDRESS` | IP address or hostname of the dashcam | *(required)* |
| `PUID` | User ID for file permissions | |
| `PGID` | Group ID for file permissions | |
| `TZ` | Timezone (e.g. `Europe/London`) | |
| `KEEP` | Retention period — recordings older than this are deleted. Accepts `<number>[d\|w]` for days or weeks (e.g. `30d`, `4w`) | |
| `GROUPING` | Group recordings into subdirectories: `daily`, `weekly`, `monthly`, `yearly`, or `none` | `none` |
| `PRIORITY` | Download order: `date` (oldest first) or `rdate` (newest first) | `date` |
| `MAX_USED_DISK` | Stop downloading if disk usage exceeds this percentage (5-98) | `90` |
| `TIMEOUT` | Connection timeout in seconds | `30` |
| `DOWNLOAD_ATTEMPTS` | Number of attempts for each download (must be >= 1) | `1` |
| `VERBOSE` | Logging verbosity level (0 = normal, 1+ = debug) | `0` |
| `QUIET` | Set to any value to only log errors | |
| `CRON` | Set to any value for reduced cron-mode logging | `1` |
| `GPS_EXTRACT` | Set to any value to extract GPS data and create `.gpx` files alongside recordings | |
| `READ_ONLY` | Set to any value to only sync read-only (locked) recordings | |
| `HTML` | Set to any value to use alternative HTML scraping instead of the XML API. Recommended for cameras that are slow or timeout responding to the XML file listing request | |
| `DELETE_AFTER_SYNC` | Set to any value to delete each file from the camera immediately after it has been successfully downloaded and verified locally. Read-only/locked files (RO folder) are never deleted. See [Warnings](#warnings) below. | |
| `IMPORT_SOURCE` | Import and organize recordings from a locally mounted drive or directory instead of syncing over Wi-Fi. Mount the drive into the container first, for example `/import` | |
| `MOVE_IMPORTED` | Set to any value to move imported local files instead of copying them. This removes the source file after the destination copy is verified | |
| `MERGE_CHUNKS` | Set to any value to merge sequential clips by camera using `ffmpeg` | |
| `MERGE_GAP` | Maximum gap in seconds between chunks to treat them as one continuous session | `2` |
| `MERGED_DESTINATION` | Output directory for merged recordings | `/recordings/merged` |
| `DELETE_MERGED_SOURCES` | Set to any value to delete original chunks and sidecars after a successful merge. See [Warnings](#warnings) below. | |
| `DRY_RUN` | Set to any value to show what would happen without downloading or deleting anything | |
| `RUN_ONCE` | Set to any value to sync once and exit instead of running on a cron schedule | |

## XML vs HTML Mode

By default, Viofo Sync uses the camera's XML API (`/?custom=1&cmd=3015&par=1`) to get the file listing. For some reason on my camera this started running very slowly so setting `HTML=1` switches to scraping the camera's HTTP directory listings (`/DCIM/Movie`, `/DCIM/Movie/Parking`, `/DCIM/Movie/RO`), which seem to load faster.

## Local Drive Import

If you do not want to sync over Wi-Fi, mount the dashcam SD card, SSD, or copied folder and import it locally:

```bash
docker run -it --rm \
    -e IMPORT_SOURCE=/import \
    -e RUN_ONCE=1 \
    -e GROUPING=daily \
    -v /path/to/nas/recordings:/recordings \
    -v /path/to/dashcam/drive:/import:rw \
    --name viofosync \
    robxyz/viofosync
```

No `ADDRESS` is required when `IMPORT_SOURCE` is set. By default files are copied into `/recordings` using the same grouping rules as Wi-Fi sync. Set `MOVE_IMPORTED=1` if you want the import source cleaned up after each file is verified at the destination.

The same mode can be run directly without Docker:

```bash
./viofosync.py --import-source /path/to/dashcam/drive \
    --destination /path/to/nas/recordings \
    --grouping daily
```

## Chunk Merging

Set `MERGE_CHUNKS=1` to join sequential normal driving clips after a sync or local import. Front and rear camera files are merged separately, parking files are not merged, and output files are written to `/recordings/merged` by default. The Docker image includes `ffmpeg`; direct CLI usage requires `ffmpeg` and `ffprobe` on `PATH`.

```bash
./viofosync.py --destination /path/to/nas/recordings \
    --merge-chunks \
    --merge-gap 2
```

The filename suffix controls the merge stream: `F` only merges with `F`, `R` only merges with `R`, and parking files such as `PF` and `PR` are left as individual files. Merge groups also respect `GROUPING`, so with `GROUPING=daily` a drive crossing midnight becomes separate merged outputs for each day. `MERGE_GAP` controls how much time can be missing between the end of one clip and the start of the next before a new merged file is started. With the default `2`, real gaps are left split while normal 3-minute or 5-minute dashcam chunks still join.

## Warnings

### DELETE_AFTER_SYNC

`DELETE_AFTER_SYNC` permanently removes files from the dashcam's SD card. Before enabling it:

- **Verify your destination is reliable.** If the download destination runs out of space or becomes unavailable mid-sync, files that were already deleted from the camera cannot be recovered.
- **Read-only/locked files are never deleted.** Files stored under `/DCIM/Movie/RO/` or marked as locked on the camera are skipped regardless of this setting.
- **Deletion is inline, not batched.** Each file is deleted from the camera immediately after it is successfully downloaded and the local copy is verified. If the script is interrupted partway through a sync, only the files that were already downloaded will be removed from the camera.
- **`--dry-run` is safe.** When `DRY_RUN` is set alongside `DELETE_AFTER_SYNC`, the script logs what it would delete without actually sending any delete requests to the camera.

### DELETE_MERGED_SOURCES

`DELETE_MERGED_SOURCES` removes original chunk files and matching sidecars after `ffmpeg` has produced a verified merged output. Run with `DRY_RUN=1` first if you want to confirm the groups before deleting originals.

## License

This project is licensed under the MIT License. See the [COPYING](COPYING) file for details.
