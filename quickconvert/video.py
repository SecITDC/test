"""Video conversion logic built on FFmpeg.

The key idea: a .mov file is just a *container* (a box). Inside the box are
streams: usually one video stream (H.264 or HEVC) and one audio stream (AAC).
MP4 is a different box that can hold the same streams.

So we have two strategies:
  * REMUX  - copy the streams into a new box. Instant, zero quality loss.
  * ENCODE - decode and re-compress the video. Slow, but needed when the
             stream inside isn't something MP4 players/websites accept well.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

# On Windows, stop ffmpeg/ffprobe from flashing a black console window.
NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

# Codecs that every browser / upload site handles inside an MP4.
WEB_SAFE_VIDEO = {"h264"}
WEB_SAFE_AUDIO = {"aac", "mp3"}


class ConversionError(Exception):
    pass


class Cancelled(Exception):
    pass


def find_tool(name: str) -> str:
    """Find ffmpeg/ffprobe: first a copy next to this script (bin/), then PATH."""
    exe = name + (".exe" if sys.platform == "win32" else "")
    bundled = Path(__file__).resolve().parent / "bin" / exe
    if bundled.is_file():
        return str(bundled)
    found = shutil.which(name)
    if found:
        return found
    raise ConversionError(
        f"Could not find {name}.\n\n"
        "Install FFmpeg (e.g. `winget install Gyan.FFmpeg`) and restart Explorer, "
        f"or put {exe} in the quickconvert\\bin folder."
    )


@dataclass
class MediaInfo:
    duration: float          # seconds (0 if unknown)
    video_codec: Optional[str]
    audio_codec: Optional[str]
    pix_fmt: Optional[str]


def probe(path: Path) -> MediaInfo:
    """Ask ffprobe what's inside the file."""
    cmd = [
        find_tool("ffprobe"), "-v", "error",
        "-show_entries", "format=duration:stream=codec_type,codec_name,pix_fmt",
        "-of", "json", str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, creationflags=NO_WINDOW)
    if result.returncode != 0:
        raise ConversionError(f"ffprobe could not read the file:\n{result.stderr.strip()}")

    data = json.loads(result.stdout)
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    try:
        duration = float(data.get("format", {}).get("duration", 0))
    except ValueError:
        duration = 0.0

    return MediaInfo(
        duration=duration,
        video_codec=video and video.get("codec_name"),
        audio_codec=audio and audio.get("codec_name"),
        pix_fmt=video and video.get("pix_fmt"),
    )


def unique_output_path(src: Path, ext: str) -> Path:
    """clip.mov -> clip.mp4, or clip (1).mp4 if that already exists. Never overwrite."""
    candidate = src.with_suffix("." + ext)
    n = 1
    while candidate.exists():
        candidate = src.with_name(f"{src.stem} ({n}).{ext}")
        n += 1
    return candidate


def build_mp4_command(src: Path, tmp_out: Path, info: MediaInfo) -> tuple[list[str], str]:
    """Return (ffmpeg command, human-readable description of the strategy)."""
    if info.video_codec is None:
        raise ConversionError("This file has no video stream.")

    # 8-bit 4:2:0 is what browsers can play. iPhone HDR clips are 10-bit.
    video_copyable = info.video_codec in WEB_SAFE_VIDEO and info.pix_fmt in (None, "yuv420p", "yuvj420p")

    cmd = [
        find_tool("ffmpeg"), "-hide_banner", "-y",
        "-i", str(src),
        # Take only the first video + first audio stream. iPhone MOVs carry extra
        # metadata tracks that MP4 can't hold and would make ffmpeg fail.
        "-map", "0:v:0", "-map", "0:a:0?",
        "-map_metadata", "0",           # keep creation date etc.
    ]

    if video_copyable:
        cmd += ["-c:v", "copy"]
        mode = "Fast copy (no quality loss)"
    else:
        cmd += [
            "-c:v", "libx264",
            "-preset", "fast",           # speed vs. file size trade-off
            "-crf", "20",                # quality: lower = better (18-23 is typical)
            "-pix_fmt", "yuv420p",       # maximum compatibility
        ]
        mode = f"Re-encoding {info.video_codec.upper()} to H.264"

    if info.audio_codec is None or info.audio_codec in WEB_SAFE_AUDIO:
        cmd += ["-c:a", "copy"]
    else:
        cmd += ["-c:a", "aac", "-b:a", "192k"]

    cmd += [
        "-movflags", "+faststart",       # lets websites start playback before full download
        "-f", "mp4",                     # needed because the temp file ends in .part
        "-progress", "pipe:1", "-nostats",  # machine-readable progress on stdout
        str(tmp_out),
    ]
    return cmd, mode


ProgressFn = Callable[[float, str], None]   # (fraction 0..1, status text)


def convert_to_mp4(
    src: Path,
    on_progress: ProgressFn = lambda f, s: None,
    cancel_event: Optional[threading.Event] = None,
) -> Path:
    """Convert `src` to MP4 next to the original. Returns the output path."""
    src = Path(src)
    if not src.is_file():
        raise ConversionError(f"File not found: {src}")

    info = probe(src)
    out = unique_output_path(src, "mp4")
    # Write to a temp name first, so a crash/cancel never leaves a broken .mp4 behind.
    tmp = out.with_name(out.name + ".part")
    cmd, mode = build_mp4_command(src, tmp, info)
    on_progress(0.0, mode)

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace",
        creationflags=NO_WINDOW,
    )

    # Read stderr on a side thread. If nobody drains it, the pipe buffer fills up
    # and ffmpeg freezes. We keep only the last lines for error messages.
    err_tail: deque[str] = deque(maxlen=15)
    t = threading.Thread(target=lambda: err_tail.extend(proc.stderr), daemon=True)
    t.start()

    try:
        # ffmpeg -progress prints "key=value" lines, e.g. out_time_us=1234567
        for line in proc.stdout:
            if cancel_event is not None and cancel_event.is_set():
                proc.kill()
                proc.wait()
                raise Cancelled()
            key, _, value = line.strip().partition("=")
            if key == "out_time_us" and info.duration > 0 and value.isdigit():
                fraction = min(int(value) / 1_000_000 / info.duration, 1.0)
                on_progress(fraction, mode)

        proc.wait()
        t.join(timeout=2)
        if proc.returncode != 0:
            raise ConversionError("FFmpeg failed:\n" + "".join(err_tail).strip())

        os.replace(tmp, out)
        on_progress(1.0, "Done")
        return out
    finally:
        if proc.poll() is None:
            proc.kill()
        if tmp.exists():
            tmp.unlink(missing_ok=True)
