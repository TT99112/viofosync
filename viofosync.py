#!/usr/bin/env python3

# Copyright (c) 2024 Rob Smith
# Based on BlackVueSync by Alessandro Colomba
# (https://github.com/acolomba)
# GPS extraction method by Sergei Franco
#
# Permission is hereby granted, free of charge, to any person
# obtaining a copy of this software and associated documentation
# files (the "Software"), to deal in the Software without
# restriction, including without limitation the rights to use,
# copy, modify, merge, publish, distribute, sublicense, and/or
# sell copies of the Software, and to permit persons to whom the
# Software is furnished to do so, subject to the following
# conditions:
#
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES
# OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
# HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
# WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
# FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR
# OTHER DEALINGS IN THE SOFTWARE.

__version__ = "1.3"

import argparse
import datetime
import glob
import http.client
import logging
import os
import re
import shutil
import socket
import struct
import subprocess
import tempfile
import time
import urllib
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import namedtuple

# Logging
logging.basicConfig(
    format="%(asctime)s: %(levelname)s %(message)s"
)
logger = logging.getLogger()
cron_logger = logging.getLogger("cron")

# Globals
dry_run = False
read_only = False
delete_after_sync = False
max_disk_used_percent = 90
cutoff_date = None
socket_timeout = 10.0

DEFAULT_DOWNLOAD_ATTEMPTS = 1
max_download_attempts = DEFAULT_DOWNLOAD_ATTEMPTS
RETRY_BACKOFF = 5  # seconds, multiplied by attempt number
DEFAULT_MERGE_GAP_SECONDS = 2.0
FALLBACK_SEGMENT_SECONDS = (180.0, 300.0)

# Recording namedtuple matching Viofo's file information
Recording = namedtuple(
    "Recording",
    "filename filepath size timecode datetime attr",
)

LocalRecording = namedtuple(
    "LocalRecording",
    "filepath filename size datetime sequence camera mode tag duration",
)

# Group name globs, keyed by grouping
group_name_globs = {
    "none": None,
    "daily": "[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]",
    "weekly": "[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]",
    "monthly": "[0-9][0-9][0-9][0-9]-[0-9][0-9]",
    "yearly": "[0-9][0-9][0-9][0-9]",
}

# Downloaded recording filename glob pattern
downloaded_filename_glob = (
    "[0-9][0-9][0-9][0-9]_[0-9][0-9][0-9][0-9]"
    "_[0-9][0-9][0-9][0-9][0-9][0-9]"
    "_*[FR].MP4"
)

# Downloaded recording filename regular expression
downloaded_filename_re = re.compile(
    r"^(?P<year>\d{4})_(?P<month>\d{2})(?P<day>\d{2})"
    r"_(?P<hour>\d{2})(?P<minute>\d{2})(?P<second>\d{2})"
    r"_(?P<sequence>\d+)(?P<camera>.+)\.MP4$",
    re.IGNORECASE,
)

# Viofo camera filename pattern
filename_re = re.compile(
    r"(?P<year>\d{4})_(?P<month>\d{2})(?P<day>\d{2})"
    r"_(?P<hour>\d{2})(?P<minute>\d{2})(?P<second>\d{2})"
    r"_(?P<sequence>\d+)(?P<camera>.+)\.MP4",
    re.IGNORECASE,
)


def to_downloaded_recording(filename, grouping):
    """Extracts destination recording info from a filename."""
    m = downloaded_filename_re.match(filename)
    if m is None:
        return None

    recording_datetime = datetime.datetime(
        int(m.group("year")), int(m.group("month")),
        int(m.group("day")), int(m.group("hour")),
        int(m.group("minute")), int(m.group("second")),
    )
    return Recording(filename, None, None, None,
                     recording_datetime, None)


def parse_viofo_datetime(time_str):
    """Parse the datetime string from Viofo's format."""
    return datetime.datetime.strptime(time_str, "%Y/%m/%d %H:%M:%S")


def positive_int(value):
    """argparse type: integer >= 1."""
    try:
        parsed = int(value)
    except ValueError as e:
        raise argparse.ArgumentTypeError(
            f"invalid int value: '{value}'"
        ) from e

    if parsed < 1:
        raise argparse.ArgumentTypeError(
            "value must be greater than or equal to 1"
        )
    return parsed


def non_negative_float(value):
    """argparse type: float >= 0."""
    try:
        parsed = float(value)
    except ValueError as e:
        raise argparse.ArgumentTypeError(
            f"invalid float value: '{value}'"
        ) from e

    if parsed < 0:
        raise argparse.ArgumentTypeError(
            "value must be greater than or equal to 0"
        )
    return parsed


def parse_recording_filename(filename):
    """Parses a Viofo recording filename into recording metadata."""
    m = filename_re.match(os.path.basename(filename))
    if m is None:
        return None

    tag = m.group("camera").upper()
    mode = "parking" if tag.startswith("P") else "normal"
    camera = tag[1:] if mode == "parking" else tag

    recording_datetime = datetime.datetime(
        int(m.group("year")), int(m.group("month")),
        int(m.group("day")), int(m.group("hour")),
        int(m.group("minute")), int(m.group("second")),
    )
    return {
        "datetime": recording_datetime,
        "sequence": int(m.group("sequence")),
        "camera": camera,
        "mode": mode,
        "tag": tag,
    }


def get_dashcam_filenames(base_url):
    """Gets the recording filenames from the Viofo dashcam."""
    try:
        url = f"{base_url}/?custom=1&cmd=3015&par=1"
        request = urllib.request.Request(url)
        response = urllib.request.urlopen(request)

        if response.getcode() != 200:
            raise RuntimeError(
                f"Error response from {base_url}; "
                f"status code: {response.getcode()}"
            )

        xml_data = response.read().decode('utf-8')
        root = ET.fromstring(xml_data)

        recordings = []
        for file_elem in root.findall(".//File"):
            attr = int(file_elem.find("ATTR").text)
            if read_only and attr != 33:
                continue
            name = file_elem.find("NAME").text
            filepath = file_elem.find("FPATH").text
            size = int(file_elem.find("SIZE").text)
            timecode = int(file_elem.find("TIMECODE").text)
            ts = parse_viofo_datetime(
                file_elem.find("TIME").text
            )
            recording = Recording(
                name, filepath, size, timecode, ts, attr
            )
            recordings.append(recording)

        logger.info(f"Found {len(recordings)} recordings on dashcam")
        return recordings
    except urllib.error.URLError as e:
        raise RuntimeError(
            f"Cannot obtain recordings from {base_url}: {e}"
        ) from e
    except socket.timeout as e:
        raise UserWarning(
            f"Timeout communicating with dashcam at "
            f"{base_url}: {e}"
        ) from e
    except http.client.RemoteDisconnected as e:
        raise UserWarning(
            f"Dashcam disconnected without response; "
            f"address: {base_url}: {e}"
        ) from e
    except ET.ParseError as e:
        raise RuntimeError(
            f"Error parsing XML response from dashcam: {e}"
        ) from e


# HTML directory listing regex
html_file_re = re.compile(
    r'<a href="(?P<filepath>[^"]+\.MP4)">'
    r'<b>(?P<filename>[^<]+)</b></a>'
    r'<td align=right>\s*(?P<size>[\d.]+)\s*(?P<unit>[KMGT]?B)',
    re.IGNORECASE,
)

# Directories to scrape on the dashcam
DCIM_DIRS = ["/DCIM/Movie", "/DCIM/Movie/Parking"]
DCIM_DIRS_RO = ["/DCIM/Movie/RO"]


def parse_html_size(size_str, unit):
    """Converts '102.00 MB' style size to bytes."""
    multipliers = {
        "B": 1, "KB": 1 << 10, "MB": 1 << 20,
        "GB": 1 << 30, "TB": 1 << 40,
    }
    return int(float(size_str) * multipliers.get(unit, 1))


def get_dashcam_filenames_html(base_url):
    """Gets recordings by scraping the HTML directory listings.

    Much faster than the XML API on cameras with many files.
    """
    dirs = DCIM_DIRS_RO if read_only else DCIM_DIRS
    recordings = []

    for dir_path in dirs:
        url = f"{base_url}{dir_path}"
        try:
            with urllib.request.urlopen(
                url, timeout=socket_timeout
            ) as resp:
                if resp.getcode() != 200:
                    logger.warning(
                        f"HTTP {resp.getcode()} for {url}, "
                        f"skipping"
                    )
                    continue
                html = resp.read().decode('utf-8')
        except urllib.error.HTTPError as e:
            if e.code == 404:
                logger.debug(
                    f"Directory not found: {dir_path}"
                )
                continue
            raise
        except urllib.error.URLError as e:
            raise RuntimeError(
                f"Cannot reach dashcam at {base_url}: {e}"
            ) from e
        except socket.timeout as e:
            raise UserWarning(
                f"Timeout communicating with dashcam at "
                f"{base_url}: {e}"
            ) from e

        for m in html_file_re.finditer(html):
            filepath = m.group("filepath")
            filename = m.group("filename")
            size = parse_html_size(
                m.group("size"), m.group("unit").upper()
            )

            # Always extract datetime from the filename
            # (the actual recording timestamp)
            fm = filename_re.search(filename)
            if not fm:
                logger.warning(
                    f"Cannot parse date from filename: "
                    f"{filename}, skipping"
                )
                continue

            ts = datetime.datetime(
                int(fm.group("year")),
                int(fm.group("month")),
                int(fm.group("day")),
                int(fm.group("hour")),
                int(fm.group("minute")),
                int(fm.group("second")),
            )

            recordings.append(Recording(
                filename, filepath, size, None, ts, None
            ))

    logger.info(
        f"Found {len(recordings)} recordings on dashcam "
        f"(HTML mode)"
    )
    return recordings


def get_filepath(destination, group_name, filename):
    """Constructs a path from destination, group name and filename."""
    if group_name:
        return os.path.join(destination, group_name, filename)
    return os.path.join(destination, filename)


def get_remote_size(url, timeout):
    """HEAD request to get Content-Length of a remote file."""
    req = urllib.request.Request(url, method="HEAD")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        cl = resp.getheader("Content-Length")
    return int(cl) if cl and cl.isdigit() else None


def human_size(num_bytes):
    """Returns human-readable size string, e.g. '325.1 MB'."""
    if num_bytes == 0:
        return "0 B"
    for factor, suffix in [(1 << 30, "GB"), (1 << 20, "MB"),
                           (1 << 10, "KB"), (1, "B")]:
        if num_bytes >= factor:
            return f"{num_bytes / factor:.1f} {suffix}"
    return f"{num_bytes} B"


def human_speed(num_bytes, elapsed):
    """Returns human-readable speed string, e.g. '27.1 MB/s'."""
    bps = num_bytes / max(elapsed, 1e-9)
    if bps == 0:
        return "0 B/s"
    for factor, suffix in [(1 << 30, "GB/s"), (1 << 20, "MB/s"),
                           (1 << 10, "KB/s"), (1, "B/s")]:
        if bps >= factor:
            return f"{bps / factor:.1f} {suffix}"
    return f"{bps:.1f} B/s"


def download_file(base_url, recording, destination, group_name):
    """Downloads a file from the Viofo dashcam to the destination.

    Returns (downloaded: bool, speed_str: str|None,
    local_available: bool, verified: bool).
    Uses HEAD to check size, retries up to max_download_attempts,
    and verifies integrity after download.
    """
    if group_name:
        group_filepath = os.path.join(destination, group_name)
        ensure_destination(group_filepath)

    dest_filepath = get_filepath(
        destination, group_name, recording.filename
    )

    # Build download URL — strip drive letter (A: for SD, B: for SSD)
    # and normalise path separators
    cleaned = re.sub(r'^[A-Z]:', '', recording.filepath).replace(
        '\\', '/'
    )
    url = f"{base_url}/{cleaned.lstrip('/')}"

    # Check expected size via HEAD, falling back to exact XML metadata.
    try:
        expected_size = get_remote_size(url, socket_timeout)
    except Exception:
        expected_size = None
    if expected_size is None and recording.timecode is not None:
        expected_size = recording.size

    # Skip if already downloaded and size matches
    if os.path.exists(dest_filepath):
        local_size = os.path.getsize(dest_filepath)
        if expected_size is not None:
            if local_size == expected_size:
                logger.debug(
                    f"Skipping {recording.filename} "
                    f"({human_size(local_size)})"
                )
                return False, None, True, True
            # Size mismatch — re-download
            logger.info(
                f"Size mismatch for {recording.filename} "
                f"({human_size(local_size)}/"
                f"{human_size(expected_size)}), "
                f"re-downloading"
            )
        else:
            logger.debug(
                f"Already downloaded: {recording.filename}"
            )
            return False, None, local_size > 0, False

    if dry_run:
        logger.info(
            f"[DRY RUN] Would download: {recording.filename}"
        )
        return True, None, False, False

    # Atomic download with tempfile + retries
    dest_dir = os.path.dirname(dest_filepath)
    tmp_fd, tmp_path = tempfile.mkstemp(
        dir=dest_dir,
        prefix=f".{recording.filename}.",
        suffix=".part",
    )
    os.close(tmp_fd)

    try:
        for attempt in range(1, max_download_attempts + 1):
            try:
                start = time.perf_counter()
                with urllib.request.urlopen(
                    url, timeout=socket_timeout
                ) as resp, open(tmp_path, "wb") as out:
                    shutil.copyfileobj(resp, out)
                elapsed = time.perf_counter() - start
            except Exception as e:
                logger.warning(
                    f"Download attempt {attempt} failed for "
                    f"{recording.filename}: {e}"
                )
                if attempt < max_download_attempts:
                    time.sleep(RETRY_BACKOFF * attempt)
                continue

            actual_size = os.path.getsize(tmp_path)

            # Verify integrity
            if (expected_size is not None
                    and actual_size != expected_size):
                logger.warning(
                    f"Incomplete download of "
                    f"{recording.filename}: "
                    f"{human_size(actual_size)}/"
                    f"{human_size(expected_size)}"
                )
                if attempt < max_download_attempts:
                    time.sleep(RETRY_BACKOFF * attempt)
                continue

            # Success — atomic move into place
            os.replace(tmp_path, dest_filepath)
            size_str = human_size(actual_size)
            speed_str = human_speed(actual_size, elapsed)
            logger.info(
                f"Downloaded {recording.filename}: "
                f"{size_str} in {elapsed:.1f}s ({speed_str})"
            )
            return True, speed_str, True, expected_size is not None

        # All attempts exhausted
        logger.error(
            f"Failed to download {recording.filename} "
            f"after {max_download_attempts} attempts"
        )
        return False, None, False, False
    except socket.timeout as e:
        raise UserWarning(
            f"Timeout communicating with dashcam at "
            f"{base_url}: {e}"
        ) from e
    except http.client.RemoteDisconnected:
        cron_logger.warning(
            f"Remote end closed connection for "
            f"{recording.filename}; ignoring."
        )
        return False, None, False, False
    finally:
        # Clean up temp file if it still exists
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def verify_local_file(local_path, expected_size=None):
    """Returns True if local_path exists and matches expected size."""
    try:
        if not os.path.exists(local_path):
            return False
        local_size = os.path.getsize(local_path)
        if local_size <= 0:
            return False
        return expected_size is None or local_size == expected_size
    except OSError:
        return False


def delete_from_camera(address, filepath, timeout):
    """Requests deletion of filepath on the camera via the XML API.

    Returns True when the camera responds HTTP 200 with Status 0,
    raises on connection/parse errors.
    """
    encoded = urllib.parse.quote(filepath, safe="/")
    url = f"http://{address}/?custom=1&cmd=4003&str={encoded}"
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        if resp.getcode() != 200:
            return False
        xml_data = resp.read().decode("utf-8")
    root = ET.fromstring(xml_data)
    status_elem = root.find(".//Status")
    return status_elem is not None and status_elem.text.strip() == "0"


def get_downloaded_recordings(destination, grouping):
    """Reads destination dir and returns set of (filename, date)."""
    group_name_glob = group_name_globs[grouping]
    filepath_glob = get_filepath(
        destination, group_name_glob, downloaded_filename_glob
    )
    downloaded_filepaths = glob.glob(filepath_glob)

    recordings = set()
    for filepath in downloaded_filepaths:
        filename = os.path.basename(filepath)
        m = downloaded_filename_re.match(filename)
        if m:
            recording_date = datetime.date(
                int(m.group("year")),
                int(m.group("month")),
                int(m.group("day")),
            )
            recordings.add((filename, recording_date))
    return recordings


def get_outdated_recordings(destination, grouping):
    """Returns filenames of recordings prior to the cutoff date."""
    if cutoff_date is None:
        return []

    downloaded = get_downloaded_recordings(destination, grouping)
    return [
        filename
        for filename, rec_date in downloaded
        if rec_date < cutoff_date
    ]


def cleanup_empty_dirs(destination, grouping):
    """Removes empty group directories under destination."""
    group_glob = group_name_globs[grouping]
    if not group_glob:
        return

    pattern = os.path.join(destination, group_glob)
    for dirpath in glob.glob(pattern):
        if os.path.isdir(dirpath) and not os.listdir(dirpath):
            if dry_run:
                logger.info(
                    f"[DRY RUN] Would remove empty dir: "
                    f"{dirpath}"
                )
            else:
                try:
                    os.rmdir(dirpath)
                    logger.info(
                        f"Removed empty directory: {dirpath}"
                    )
                except OSError as e:
                    logger.debug(
                        f"Could not remove {dirpath}: {e}"
                    )


def prepare_destination(destination, grouping):
    """Prepares destination: removes outdated recordings and
    their .gpx sidecars, then cleans up empty directories."""
    if not cutoff_date:
        return

    outdated = get_outdated_recordings(destination, grouping)

    for outdated_recording in outdated:
        if dry_run:
            logger.info(
                f"[DRY RUN] Would remove outdated: "
                f"{outdated_recording}"
            )
            continue

        logger.info(f"Removing outdated: {outdated_recording}")

        # Glob for the recording and any sidecars (.gpx etc)
        base = os.path.splitext(outdated_recording)[0]
        sidecar_glob = f"{base}.*"
        filepath_glob = get_filepath(
            destination, group_name_globs[grouping],
            sidecar_glob,
        )

        for filepath in glob.glob(filepath_glob):
            try:
                os.remove(filepath)
                logger.info(f"Removed: {filepath}")
            except OSError as e:
                logger.error(
                    f"Error removing {filepath}: {e}"
                )

    cleanup_empty_dirs(destination, grouping)


def path_is_within(path, root):
    """Returns True when path is inside root."""
    if not root:
        return False
    try:
        real_path = os.path.realpath(path)
        real_root = os.path.realpath(root)
        return os.path.commonpath([real_path, real_root]) == real_root
    except ValueError:
        return False


def local_file_is_locked(filepath):
    """Best-effort check for files copied from the RO folder."""
    parts = filepath.replace("\\", "/").upper().split("/")
    return "RO" in parts


def to_local_recording(filepath):
    """Builds LocalRecording metadata for a local Viofo file."""
    filename = os.path.basename(filepath)
    metadata = parse_recording_filename(filename)
    if metadata is None:
        return None
    try:
        size = os.path.getsize(filepath)
    except OSError as e:
        logger.warning(f"Cannot stat {filepath}: {e}")
        return None
    return LocalRecording(
        filepath, filename, size, metadata["datetime"],
        metadata["sequence"], metadata["camera"],
        metadata["mode"], metadata["tag"], None,
    )


def iter_local_recordings(source, excluded_roots=None):
    """Yields Viofo recordings found under a local source path."""
    excluded_roots = excluded_roots or []

    if os.path.isfile(source):
        recording = to_local_recording(source)
        if recording and (not read_only
                          or local_file_is_locked(source)):
            yield recording
        return

    if not os.path.isdir(source):
        raise RuntimeError(f"Import source is not a directory: {source}")

    for dirpath, dirnames, filenames in os.walk(source):
        dirnames[:] = [
            dirname for dirname in dirnames
            if not any(
                path_is_within(os.path.join(dirpath, dirname), root)
                for root in excluded_roots
            )
        ]

        for filename in filenames:
            filepath = os.path.join(dirpath, filename)
            if any(path_is_within(filepath, root)
                   for root in excluded_roots):
                continue
            if read_only and not local_file_is_locked(filepath):
                continue
            recording = to_local_recording(filepath)
            if recording:
                yield recording


def copy_or_move_local_recording(recording, destination,
                                 grouping, move_imported):
    """Copies or moves one local recording into the destination tree."""
    group_name = get_group_name(recording.datetime, grouping)
    if group_name:
        ensure_destination(os.path.join(destination, group_name))

    dest_path = get_filepath(
        destination, group_name, recording.filename
    )

    if os.path.realpath(recording.filepath) == os.path.realpath(
        dest_path
    ):
        logger.debug(f"Already organized: {recording.filename}")
        return False, dest_path

    if os.path.exists(dest_path):
        try:
            dest_size = os.path.getsize(dest_path)
        except OSError as e:
            logger.warning(f"Cannot stat {dest_path}: {e}")
            return False, None

        if dest_size == recording.size:
            logger.info(f"Already imported: {recording.filename}")
            if move_imported and not dry_run:
                try:
                    os.remove(recording.filepath)
                    logger.info(
                        f"Removed duplicate source: "
                        f"{recording.filepath}"
                    )
                except OSError as e:
                    logger.warning(
                        f"Could not remove duplicate source "
                        f"{recording.filepath}: {e}"
                    )
            return False, dest_path

        logger.warning(
            f"Destination exists with a different size, skipping: "
            f"{dest_path}"
        )
        return False, None

    if dry_run:
        action = "move" if move_imported else "copy"
        logger.info(
            f"[DRY RUN] Would {action} {recording.filepath} "
            f"to {dest_path}"
        )
        return True, dest_path

    try:
        if move_imported:
            shutil.move(recording.filepath, dest_path)
            action = "Moved"
        else:
            shutil.copy2(recording.filepath, dest_path)
            action = "Copied"
    except OSError as e:
        logger.error(f"Failed to import {recording.filepath}: {e}")
        return False, None

    if not verify_local_file(dest_path, recording.size):
        logger.error(
            f"Imported file failed verification: {dest_path}"
        )
        return False, None

    logger.info(f"{action} {recording.filename} to {dest_path}")
    return True, dest_path


def organize_local_recordings(source, destination, grouping,
                              move_imported, gps_extract):
    """Imports recordings from a mounted drive into the destination."""
    logger.info(f"Starting local import from {source}")
    ensure_destination(destination)
    prepare_destination(destination, grouping)

    recordings = sorted(
        iter_local_recordings(source),
        key=lambda r: r.datetime,
    )
    logger.info(f"Found {len(recordings)} local recordings")

    imported = 0
    for recording in recordings:
        if cutoff_date and recording.datetime.date() < cutoff_date:
            continue
        changed, dest_path = copy_or_move_local_recording(
            recording, destination, grouping, move_imported
        )
        if changed:
            imported += 1
        if changed and gps_extract and dest_path and not dry_run:
            extract_gps_data(dest_path)

    logger.info(f"Local import complete: {imported} files imported")
    return True


def get_video_duration(filepath):
    """Returns video duration in seconds using ffprobe."""
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                filepath,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        raise RuntimeError(
            "ffprobe is required for --merge-chunks"
        )

    if result.returncode != 0:
        logger.warning(
            f"Could not read duration for {filepath}: "
            f"{result.stderr.strip()}"
        )
        return None

    try:
        return float(result.stdout.strip())
    except ValueError:
        logger.warning(f"Could not parse duration for {filepath}")
        return None


def with_durations(recordings):
    """Adds ffprobe durations to LocalRecording entries."""
    hydrated = []
    for recording in recordings:
        duration = get_video_duration(recording.filepath)
        hydrated.append(recording._replace(duration=duration))
    return hydrated


def should_merge_after(previous, current, merge_gap):
    """Returns True when two chunks appear to be one session."""
    if (previous.camera != current.camera
            or previous.mode != current.mode):
        return False

    if previous.mode == "parking":
        return False

    if current.sequence <= previous.sequence:
        return False

    elapsed = (current.datetime - previous.datetime).total_seconds()
    if elapsed <= 0:
        return False

    if previous.duration is not None:
        previous_end = previous.datetime + datetime.timedelta(
            seconds=previous.duration
        )
        gap = (current.datetime - previous_end).total_seconds()
        return -1.0 <= gap <= merge_gap

    return any(
        abs(elapsed - segment_seconds) <= merge_gap
        for segment_seconds in FALLBACK_SEGMENT_SECONDS
    )


def merge_stream_key(recording, grouping):
    """Returns the grouping boundary and stream for merge decisions."""
    return (
        get_group_name(recording.datetime, grouping),
        recording.mode,
        recording.camera,
    )


def sort_stream_key(stream_key):
    """Sort helper that handles ungrouped recordings."""
    return tuple("" if value is None else value for value in stream_key)


def build_merge_groups(recordings, merge_gap, grouping):
    """Groups adjacent recordings by camera and time continuity."""
    groups = []

    for stream in sorted(
        {merge_stream_key(r, grouping) for r in recordings},
        key=sort_stream_key,
    ):
        camera_recordings = sorted(
            [r for r in recordings
             if merge_stream_key(r, grouping) == stream],
            key=lambda r: r.datetime,
        )
        current_group = []

        for recording in camera_recordings:
            if not current_group:
                current_group = [recording]
                continue

            if should_merge_after(
                current_group[-1], recording, merge_gap,
            ):
                current_group.append(recording)
            else:
                if len(current_group) > 1:
                    groups.append(current_group)
                current_group = [recording]

        if len(current_group) > 1:
            groups.append(current_group)

    return groups


def concat_file_line(filepath):
    """Formats one ffmpeg concat demuxer file line."""
    escaped = os.path.abspath(filepath).replace("'", "'\\''")
    return f"file '{escaped}'\n"


def merged_output_filename(group):
    """Builds a filename for a merged recording group."""
    start = group[0].datetime.strftime("%Y_%m%d_%H%M%S")
    end = group[-1].datetime.strftime("%Y%m%d_%H%M%S")
    tag = re.sub(r"[^A-Z0-9_-]", "", group[0].tag) or "CAM"
    return f"{start}_{tag}_to_{end}.MP4"


def remove_recording_and_sidecars(filepath):
    """Removes a source MP4 and sidecars with the same base name."""
    base = os.path.splitext(filepath)[0]
    for sidecar_path in glob.glob(f"{base}.*"):
        try:
            os.remove(sidecar_path)
            logger.info(f"Removed source: {sidecar_path}")
        except OSError as e:
            logger.warning(f"Could not remove {sidecar_path}: {e}")


def merge_recording_group(group, merged_destination,
                          grouping, delete_sources):
    """Merges one chunk group with ffmpeg concat copy."""
    group_name = get_group_name(group[0].datetime, grouping)
    output_dir = (
        os.path.join(merged_destination, group_name)
        if group_name else merged_destination
    )
    ensure_destination(output_dir)

    output_path = os.path.join(
        output_dir, merged_output_filename(group)
    )
    if os.path.exists(output_path):
        logger.info(f"Merged file already exists: {output_path}")
        return False

    if dry_run:
        logger.info(
            f"[DRY RUN] Would merge {len(group)} chunks into "
            f"{output_path}"
        )
        return True

    list_fd, list_path = tempfile.mkstemp(
        dir=output_dir, prefix=".concat-", suffix=".txt"
    )
    tmp_fd, tmp_output = tempfile.mkstemp(
        dir=output_dir,
        prefix=f".{os.path.basename(output_path)}.",
        suffix=".MP4",
    )
    os.close(list_fd)
    os.close(tmp_fd)

    try:
        with open(list_path, "w") as list_file:
            for recording in group:
                list_file.write(concat_file_line(recording.filepath))

        result = subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error",
                "-y", "-f", "concat", "-safe", "0",
                "-i", list_path, "-c", "copy", tmp_output,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            logger.error(
                f"Failed to merge into {output_path}: "
                f"{result.stderr.strip()}"
            )
            return False

        if not verify_local_file(tmp_output):
            logger.error(f"Merged file is empty: {tmp_output}")
            return False

        os.replace(tmp_output, output_path)
        logger.info(
            f"Merged {len(group)} chunks into {output_path}"
        )

        if delete_sources:
            for recording in group:
                remove_recording_and_sidecars(recording.filepath)

        return True
    finally:
        for path in (list_path, tmp_output):
            if os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass


def merge_chunks(source, grouping, merged_destination,
                 merge_gap, delete_sources):
    """Finds and merges sequential local chunks under source."""
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg is required for --merge-chunks")
    if shutil.which("ffprobe") is None:
        raise RuntimeError("ffprobe is required for --merge-chunks")

    merged_destination = (
        merged_destination or os.path.join(source, "merged")
    )
    logger.info(
        f"Scanning {source} for chunks to merge into "
        f"{merged_destination}"
    )

    all_recordings = sorted(
        iter_local_recordings(
            source, excluded_roots=[merged_destination]
        ),
        key=lambda r: (r.mode, r.camera, r.datetime),
    )
    skipped_parking = sum(
        1 for recording in all_recordings
        if recording.mode == "parking"
    )
    if skipped_parking:
        logger.info(
            f"Skipping {skipped_parking} parking recordings "
            f"during merge"
        )
    recordings = [
        recording for recording in all_recordings
        if recording.mode != "parking"
    ]
    recordings = with_durations(recordings)
    groups = build_merge_groups(recordings, merge_gap, grouping)
    logger.info(f"Found {len(groups)} merge groups")

    merged = 0
    for group in groups:
        if merge_recording_group(
            group, merged_destination, grouping, delete_sources
        ):
            merged += 1

    logger.info(f"Chunk merge complete: {merged} groups processed")
    return True


def _handle_camera_deletion(address, recording, dest_path):
    """Post-download deletion: verify local file then delete from camera."""
    is_locked = (
        (recording.filepath and local_file_is_locked(
            recording.filepath
        ))
        or recording.attr == 33
    )
    if is_locked:
        logger.info(
            f"Skipping deletion of locked file: "
            f"{recording.filename}"
        )
        return

    if dry_run:
        logger.info(
            f"[DRY RUN] Would delete from camera: "
            f"{recording.filename}"
        )
        return

    if not verify_local_file(dest_path):
        logger.warning(
            f"Failed to delete from camera: "
            f"{recording.filename} "
            f"(local file missing or empty)"
        )
        return

    try:
        if delete_from_camera(
            address, recording.filepath, socket_timeout
        ):
            logger.info(
                f"Deleted from camera: {recording.filename}"
            )
        else:
            logger.warning(
                f"Failed to delete from camera: "
                f"{recording.filename} "
                f"(camera returned error)"
            )
    except Exception as e:
        logger.warning(
            f"Failed to delete from camera: "
            f"{recording.filename} ({e})"
        )


def sync(address, destination, grouping, download_priority,
         recording_filter, args):
    """Synchronizes dashcam recordings with destination dir."""
    logger.info(f"Starting sync for {address}")
    ensure_destination(destination)
    prepare_destination(destination, grouping)

    base_url = f"http://{address}"
    try:
        if args.html:
            dashcam_recordings = get_dashcam_filenames_html(
                base_url
            )
        else:
            dashcam_recordings = get_dashcam_filenames(base_url)
    except (RuntimeError, UserWarning) as e:
        logger.error(f"Sync aborted: {e}")
        return False

    dashcam_recordings.sort(
        key=lambda r: r.datetime,
        reverse=(download_priority == "rdate"),
    )

    if recording_filter:
        dashcam_recordings = [
            r for r in dashcam_recordings
            if any(f in r.filename for f in recording_filter)
        ]
        logger.info(
            f"Filtered to {len(dashcam_recordings)} recordings"
        )

    total = len(dashcam_recordings)
    for i, recording in enumerate(dashcam_recordings, start=1):
        if cutoff_date and recording.datetime.date() < cutoff_date:
            continue
        group_name = get_group_name(
            recording.datetime, grouping
        )
        logger.info(
            f"[{i}/{total}] Processing {recording.filename}"
        )
        downloaded, _, local_available, verified = download_file(
            base_url, recording, destination, group_name
        )
        dest_path = get_filepath(
            destination, group_name, recording.filename
        )
        if downloaded and local_available:
            if args.gps_extract and not dry_run:
                extract_gps_data(dest_path)
        if delete_after_sync and (verified or dry_run):
            _handle_camera_deletion(
                address, recording, dest_path
            )
        elif delete_after_sync and local_available:
            logger.warning(
                f"Skipping camera deletion for "
                f"{recording.filename}: local file size could "
                f"not be verified"
            )

    logger.info("Sync complete")
    return True


def ensure_destination(destination):
    """Ensures the destination directory exists and is writable."""
    if not os.path.exists(destination):
        os.makedirs(destination)
    elif not os.path.isdir(destination):
        raise RuntimeError(
            f"Not a directory: {destination}"
        )
    elif not os.access(destination, os.W_OK):
        raise RuntimeError(
            f"Not writable: {destination}"
        )


def get_group_name(recording_datetime, grouping):
    """Determines the group name for a recording datetime."""
    if grouping == "daily":
        return recording_datetime.strftime("%Y-%m-%d")
    elif grouping == "weekly":
        delta = datetime.timedelta(
            days=recording_datetime.weekday()
        )
        return (recording_datetime - delta).strftime("%Y-%m-%d")
    elif grouping == "monthly":
        return recording_datetime.strftime("%Y-%m")
    elif grouping == "yearly":
        return recording_datetime.strftime("%Y")
    return None


# --- GPS Extraction Functions ---

def fix_time(hour, minute, second, year, month, day):
    return (
        f"{year + 2000:04d}-{month:02d}-{day:02d}"
        f"T{hour:02d}:{minute:02d}:{second:02d}Z"
    )


def fix_coordinates(hemisphere, coordinate):
    minutes = coordinate % 100.0
    degrees = coordinate - minutes
    coordinate = degrees / 100.0 + (minutes / 60.0)
    if hemisphere in ['S', 'W']:
        return -1 * float(coordinate)
    return float(coordinate)


def fix_speed(speed):
    return speed * 0.514444


def get_atom_info(eight_bytes):
    try:
        atom_size, atom_type = struct.unpack('>I4s', eight_bytes)
        return int(atom_size), atom_type.decode()
    except (struct.error, UnicodeDecodeError):
        return 0, ''


def get_gps_atom_info(eight_bytes):
    atom_pos, atom_size = struct.unpack('>II', eight_bytes)
    return int(atom_pos), int(atom_size)


def get_gps_offset(data):
    """Finds GPS payload position by scanning for A{N,S}{E,W}
    pattern. Supports newer VIOFO cameras (e.g. A329S) where
    GPS data sits at a variable offset within the payload."""
    pointer = len(data) - 20
    while pointer > 0:
        try:
            active, lon_hemi, lat_hemi = struct.unpack_from(
                '<sss', data, pointer
            )
            active = active.decode()
            lon_hemi = lon_hemi.decode()
            lat_hemi = lat_hemi.decode()
        except UnicodeDecodeError:
            pointer -= 1
            continue
        if (active == 'A'
                and lon_hemi in ('N', 'S')
                and lat_hemi in ('E', 'W')):
            return pointer - 24
        pointer -= 1
    return -1


def get_gps_data(data):
    gps = {
        'DT': {
            'Year': None, 'Month': None, 'Day': None,
            'Hour': None, 'Minute': None, 'Second': None,
            'DT': None,
        },
        'Loc': {
            'Lat': {'Raw': None, 'Hemi': None, 'Float': None},
            'Lon': {'Raw': None, 'Hemi': None, 'Float': None},
            'Speed': None, 'Bearing': None,
        },
    }

    offset = get_gps_offset(data)
    if offset < 0:
        return None

    try:
        hour, minute, second = struct.unpack_from(
            '<III', data, offset
        )
        offset += 12
        year, month, day = struct.unpack_from(
            '<III', data, offset
        )
        offset += 12
        _, lat_hemi, lon_hemi = struct.unpack_from(
            '<sss', data, offset
        )
        offset += 4
        lat_raw, lon_raw = struct.unpack_from(
            '<ff', data, offset
        )
        offset += 8
        speed, bearing = struct.unpack_from(
            '<ff', data, offset
        )

        gps['Loc']['Lat']['Hemi'] = lat_hemi.decode()
        gps['Loc']['Lon']['Hemi'] = lon_hemi.decode()
    except (struct.error, UnicodeDecodeError) as e:
        logger.debug(f"Skipping: bad GPS data. Error: {e}")
        return None

    gps['DT']['Hour'] = hour
    gps['DT']['Minute'] = minute
    gps['DT']['Second'] = second
    gps['DT']['Year'] = year
    gps['DT']['Month'] = month
    gps['DT']['Day'] = day
    gps['DT']['DT'] = fix_time(
        hour, minute, second, year, month, day
    )

    gps['Loc']['Lat']['Raw'] = lat_raw
    gps['Loc']['Lon']['Raw'] = lon_raw
    gps['Loc']['Lat']['Float'] = fix_coordinates(
        gps['Loc']['Lat']['Hemi'], lat_raw
    )
    gps['Loc']['Lon']['Float'] = fix_coordinates(
        gps['Loc']['Lon']['Hemi'], lon_raw
    )
    gps['Loc']['Speed'] = fix_speed(speed)
    gps['Loc']['Bearing'] = bearing

    return gps


def get_gps_atom(gps_atom_info, f):
    atom_pos, atom_size = gps_atom_info
    try:
        f.seek(atom_pos)
        data = f.read(atom_size)
    except OverflowError as e:
        logger.error(
            f"Skipping at {atom_pos:x}: "
            f"seek or read error: {e}"
        )
        return None

    if len(data) < 12:
        logger.debug(
            f"Skipping at {atom_pos:x}: "
            f"atom too small ({len(data)} bytes)"
        )
        return None

    expected_type, expected_magic = 'free', 'GPS '
    atom_size1, atom_type, magic = struct.unpack_from(
        '>I4s4s', data
    )
    try:
        atom_type = atom_type.decode()
        magic = magic.decode()
        if (atom_size != atom_size1
                or atom_type != expected_type
                or magic != expected_magic):
            logger.error(
                f"Skipping atom at {atom_pos:x} "
                f"(size:{atom_size1}/{atom_size}, "
                f"type:{atom_type}/{expected_type}, "
                f"magic:{magic}/{expected_magic})"
            )
            return None
    except UnicodeDecodeError as e:
        logger.error(
            f"Skipping at {atom_pos:x}: "
            f"garbage atom type or magic: {e}"
        )
        return None

    return get_gps_data(data[12:])


def parse_moov(in_fh):
    gps_data = []
    offset = 0
    while True:
        atom_size, atom_type = get_atom_info(in_fh.read(8))
        if atom_size == 0:
            break

        if atom_type == 'moov':
            sub_offset = offset + 8
            while sub_offset < (offset + atom_size):
                sub_atom_size, sub_atom_type = get_atom_info(
                    in_fh.read(8)
                )

                if sub_atom_type == 'gps ':
                    gps_offset = 16 + sub_offset
                    in_fh.seek(gps_offset, 0)
                    while gps_offset < (sub_offset
                                        + sub_atom_size):
                        data = get_gps_atom(
                            get_gps_atom_info(in_fh.read(8)),
                            in_fh,
                        )
                        if data:
                            gps_data.append(data)
                        gps_offset += 8
                        in_fh.seek(gps_offset, 0)

                sub_offset += sub_atom_size
                in_fh.seek(sub_offset, 0)

        offset += atom_size
        in_fh.seek(offset, 0)
    return gps_data


def generate_gpx(gps_data, out_file):
    gpx = '<?xml version="1.0" encoding="UTF-8"?>\n'
    gpx += '<gpx version="1.0"\n'
    gpx += '\tcreator="Viofo GPS Extractor"\n'
    gpx += '\txmlns:xsi='
    gpx += '"http://www.w3.org/2001/XMLSchema-instance"\n'
    gpx += '\txmlns="http://www.topografix.com/GPX/1/0"\n'
    gpx += (
        '\txsi:schemaLocation='
        '"http://www.topografix.com/GPX/1/0 '
        'http://www.topografix.com/GPX/1/0/gpx.xsd">\n'
    )
    gpx += f"\t<name>{out_file}</name>\n"
    gpx += f"\t<trk><name>{out_file}</name><trkseg>\n"
    for gps in gps_data:
        if gps:
            lat = gps['Loc']['Lat']['Float']
            lon = gps['Loc']['Lon']['Float']
            gpx += f'\t\t<trkpt lat="{lat}" lon="{lon}">'
            gpx += f"<time>{gps['DT']['DT']}</time>"
            gpx += f"<speed>{gps['Loc']['Speed']}</speed>"
            gpx += (
                f"<course>{gps['Loc']['Bearing']}</course>"
                f"</trkpt>\n"
            )
    gpx += '\t</trkseg></trk>\n'
    gpx += '</gpx>\n'
    return gpx


def extract_gps_data(file_path):
    logger.info(f"Extracting GPS data from {file_path}")

    with open(file_path, "rb") as in_fh:
        gps_data = parse_moov(in_fh)

    logger.info(f"Found {len(gps_data)} GPS data points")

    if gps_data:
        gpx_file = file_path + ".gpx"
        gpx_content = generate_gpx(
            gps_data, os.path.basename(gpx_file)
        )
        with open(gpx_file, "w") as f:
            logger.info(f"Writing GPS data to '{gpx_file}'")
            f.write(gpx_content)
    else:
        logger.warning("No GPS data found in the file")


# --- CLI ---

def parse_args():
    """Parses the command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Synchronizes Viofo dashcam recordings "
        "with a local directory, imports mounted media, "
        "and extracts GPS data.",
    )
    parser.add_argument(
        "address", nargs="?",
        help="Dashcam IP address or hostname",
    )
    parser.add_argument(
        "-d", "--destination", default=os.getcwd(),
        help="Destination directory for downloads",
    )
    parser.add_argument(
        "-g", "--grouping", default="none",
        choices=["none", "daily", "weekly", "monthly", "yearly"],
        help="Group recordings by time period",
    )
    parser.add_argument(
        "-k", "--keep",
        help="Keep recordings for period (e.g. '30d', '4w')",
    )
    parser.add_argument(
        "-p", "--priority", default="date",
        choices=["date", "rdate"],
        help="Download priority: oldest or newest first",
    )
    parser.add_argument(
        "-f", "--filter", nargs="+",
        help="Filter recordings by filename pattern",
    )
    parser.add_argument(
        "-u", "--max-used-disk", default=90,
        metavar="DISK%", type=int, choices=range(5, 99),
        help="Stop if disk usage exceeds this percent",
    )
    parser.add_argument(
        "-t", "--timeout", default=10.0,
        metavar="TIMEOUT", type=float,
        help="Connection timeout in seconds",
    )
    parser.add_argument(
        "--download-attempts",
        default=DEFAULT_DOWNLOAD_ATTEMPTS,
        metavar="ATTEMPTS",
        type=positive_int,
        help="How many times to retry a failed download",
    )
    parser.add_argument(
        "-v", "--verbose", action="count", default=0,
        help="Increase output verbosity",
    )
    parser.add_argument(
        "-q", "--quiet", action="store_true",
        help="Only log errors; overrides verbosity",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would happen without doing it",
    )
    parser.add_argument(
        "--read-only", action="store_true",
        help="Only manage read-only (locked) recordings",
    )
    parser.add_argument(
        "--cron", action="store_true",
        help="Cron mode: reduced logging verbosity",
    )
    parser.add_argument(
        "--gps-extract", action="store_true",
        help="Extract GPS data and create GPX files",
    )
    parser.add_argument(
        "--delete-after-sync", action="store_true",
        help="Delete files from camera after successful download "
        "(skips locked/RO files)",
    )
    parser.add_argument(
        "--import-source",
        help="Import and organize recordings from a local mounted "
        "drive or directory instead of syncing over Wi-Fi",
    )
    parser.add_argument(
        "--move-imported", action="store_true",
        help="Move local import files into the destination instead "
        "of copying them",
    )
    parser.add_argument(
        "--merge-chunks", action="store_true",
        help="Merge sequential chunks by camera using ffmpeg",
    )
    parser.add_argument(
        "--merge-gap", default=DEFAULT_MERGE_GAP_SECONDS,
        metavar="SECONDS", type=non_negative_float,
        help="Maximum gap between chunks to merge",
    )
    parser.add_argument(
        "--merged-destination",
        help="Directory for merged files; defaults to "
        "<destination>/merged",
    )
    parser.add_argument(
        "--delete-merged-sources", action="store_true",
        help="Delete source chunks and sidecars after a successful "
        "merge",
    )
    parser.add_argument(
        "--html", action="store_true",
        help="Use fast HTML directory scraping instead of "
        "slow XML API to list recordings",
    )
    parser.add_argument(
        "--version", action="version",
        version=f"%(prog)s {__version__}",
    )
    return parser.parse_args()


# --- Entry point ---

def run():
    global dry_run, read_only, delete_after_sync
    global max_disk_used_percent, cutoff_date, socket_timeout
    global max_download_attempts

    args = parse_args()

    if args.quiet:
        logger.setLevel(logging.ERROR)
        cron_logger.setLevel(logging.ERROR)
    elif args.cron:
        logger.setLevel(logging.WARNING)
        cron_logger.setLevel(logging.INFO)
    else:
        logger.setLevel(
            logging.DEBUG if args.verbose > 0 else logging.INFO
        )

    logger.info("Starting Viofo Sync")

    dry_run = args.dry_run
    if dry_run:
        logger.info("[DRY RUN] No action will be taken.")

    read_only = args.read_only
    if read_only:
        logger.info("READ ONLY mode: locked files only.")

    delete_after_sync = args.delete_after_sync
    if delete_after_sync:
        logger.info(
            "DELETE AFTER SYNC: camera files will be deleted "
            "after successful download."
        )

    socket_timeout = args.timeout
    socket.setdefaulttimeout(socket_timeout)
    max_download_attempts = args.download_attempts

    if args.keep:
        keep_match = re.fullmatch(
            r"(?P<range>\d+)(?P<unit>[dw]?)", args.keep
        )
        if keep_match is None:
            raise RuntimeError(
                "KEEP must be in the format <number>[dw]"
            )

        keep_range = int(keep_match.group("range"))
        if keep_range < 1:
            raise RuntimeError("KEEP must be greater than one.")

        keep_unit = keep_match.group("unit") or "d"
        if keep_unit == "d":
            delta = datetime.timedelta(days=keep_range)
        elif keep_unit == "w":
            delta = datetime.timedelta(weeks=keep_range)
        else:
            raise RuntimeError(
                f"unknown KEEP unit: {keep_unit}"
            )

        cutoff_date = datetime.datetime.now().date() - delta
        logger.info(f"Recording cutoff date: {cutoff_date}")

    try:
        if args.import_source:
            success = organize_local_recordings(
                args.import_source, args.destination,
                args.grouping, args.move_imported,
                args.gps_extract,
            )
        elif args.address:
            success = sync(
                args.address, args.destination, args.grouping,
                args.priority, args.filter, args,
            )
        elif args.merge_chunks:
            success = True
        else:
            raise RuntimeError(
                "address is required unless --import-source or "
                "--merge-chunks is set"
            )

        if success and args.merge_chunks:
            success = merge_chunks(
                args.destination, args.grouping,
                args.merged_destination, args.merge_gap,
                args.delete_merged_sources,
            )
    except Exception:
        logger.exception("An error occurred")
        return 1

    if success:
        logger.info("Viofo Sync completed successfully")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
