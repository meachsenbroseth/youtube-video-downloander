"""yt-dlp operations and queue events; deliberately independent of Tkinter."""

from dataclasses import dataclass
from pathlib import Path
from queue import Queue
import re
import shutil
import sys
from threading import Event
import time
from urllib.parse import urlparse
from urllib.request import Request as URLRequest, urlopen

import yt_dlp
from yt_dlp.utils import DownloadError


class DownloadCancelled(Exception):
    """Raised from hooks when the user requests cancellation."""


@dataclass(frozen=True)
class DownloadRequest:
    url: str
    output_folder: str = ""
    mode: str = "Video (MP4)"
    quality: str = "Best"
    playlist: bool = False
    cookiefile: str | None = None


def find_tool(tool: str) -> str | None:
    """Use bundled tools when frozen; also support PATH and local companions."""
    name = f"{tool}.exe" if sys.platform == "win32" else tool
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        bundled = Path(sys._MEIPASS) / "tools" / name
        if bundled.is_file():
            return str(bundled)
    executable = shutil.which(tool)
    if executable:
        return executable
    if getattr(sys, "frozen", False):
        candidates = [Path(sys.executable).resolve().parent / name]
    else:
        project = Path(__file__).resolve().parents[2]
        candidates = [project / name, project / ".tools" / "bin" / name]
    return next((str(path) for path in candidates if path.is_file()), None)


def find_ffmpeg() -> str | None:
    return find_tool("ffmpeg")


def has_ffmpeg() -> bool:
    return find_ffmpeg() is not None


def validate_url(value: str) -> str:
    value = value.strip()
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Paste a complete YouTube or Facebook URL starting with https://.")
    host = parsed.hostname.lower()
    if not any(host == domain or host.endswith("." + domain) for domain in
               ("youtube.com", "youtu.be", "facebook.com", "fb.watch", "fb.com")):
        raise ValueError("Please use a YouTube or Facebook video or playlist link.")
    return value


def available_qualities(info: dict, ffmpeg: bool) -> list[str]:
    formats = info.get("formats") or []
    heights = set()
    for fmt in formats:
        if fmt.get("vcodec") in (None, "none"):
            continue
        if not ffmpeg and (fmt.get("ext") != "mp4" or fmt.get("acodec") in (None, "none")):
            continue
        if isinstance(fmt.get("height"), (int, float)):
            heights.add(fmt["height"])
    return ["Best"] + [f"{height}p" for height in (1080, 720, 480, 360) if height in heights]


def friendly_error(error: Exception, ffmpeg: bool | None = None) -> str:
    detail = re.sub(r"\x1b\[[0-9;]*m", "", str(error)).removeprefix("ERROR: ").strip()
    lower = detail.lower()
    if "requested format" in lower:
        if ffmpeg is False:
            return ("ffmpeg is missing. This link has no combined MP4 at the selected quality. "
                    "Its video and audio tracks need ffmpeg to be merged.\n\n"
                    "On Windows, run: winget install ffmpeg\n"
                    "Then restart the app. You can also place ffmpeg.exe beside YTDL.exe.")
        hint = "No format matches this quality. Fetch info again and select Best."
    elif any(word in lower for word in ("private", "login", "sign in", "cookies", "confirm you")):
        hint = "This video may require a valid Netscape cookies.txt file or permission from its owner."
    elif any(word in lower for word in ("403", "429", "blocked", "bot")):
        hint = "The site refused access. Try again later or supply a valid cookie file."
    elif any(word in lower for word in ("timed out", "resolve", "connection", "network")):
        hint = "Check your internet connection and try again."
    else:
        hint = "Check that the link is accessible and update yt-dlp with uv if needed."
    return f"{hint}\n\n{detail}" if detail else hint


class QueueLogger:
    def __init__(self, events: Queue, cancel: Event):
        self.events, self.cancel = events, cancel

    def debug(self, message: str) -> None:
        if self.cancel.is_set():
            raise DownloadCancelled()
        if not message.startswith("[debug]"):
            self.events.put({"type": "log", "message": message})

    def warning(self, message: str) -> None:
        self.events.put({"type": "log", "message": f"Warning: {message}"})

    def error(self, message: str) -> None:
        self.events.put({"type": "log", "message": message})


class Downloader:
    def __init__(self, events: Queue, cancel: Event, ffmpeg: bool | None = None):
        self.events, self.cancel = events, cancel
        self.ffmpeg = has_ffmpeg() if ffmpeg is None else ffmpeg
        self.ffmpeg_path = find_ffmpeg() if self.ffmpeg else None
        self._last_progress = 0.0

    def check_cancel(self) -> None:
        if self.cancel.is_set():
            raise DownloadCancelled()

    def progress_hook(self, data: dict) -> None:
        self.check_cancel()
        now = time.monotonic()
        if data.get("status") == "downloading" and now - self._last_progress < 0.1:
            return
        self._last_progress = now
        info = data.get("info_dict") or {}
        self.events.put({
            "type": "progress", "status": data.get("status"),
            "downloaded": data.get("downloaded_bytes", 0),
            "total": data.get("total_bytes") or data.get("total_bytes_estimate"),
            "speed": data.get("speed"), "eta": data.get("eta"),
            "title": info.get("title", ""), "index": info.get("playlist_index"),
            "count": info.get("n_entries") or info.get("playlist_count"),
        })

    def postprocessor_hook(self, data: dict) -> None:
        self.check_cancel()
        self.events.put({"type": "phase", "message": "Processing media…",
                         "postprocessor": data.get("postprocessor")})

    def base_options(self, request: DownloadRequest) -> dict:
        validate_url(request.url)
        if request.cookiefile and not Path(request.cookiefile).is_file():
            raise ValueError("The selected cookie file does not exist. Choose a cookies.txt file.")
        runtimes = {name: {"path": path} for name in ("deno", "node")
                    if (path := find_tool(name))}
        options = {
            "noplaylist": not request.playlist,
            # noplaylist alone still downloads every entry of a playlist-only URL.
            "playlist_items": None if request.playlist else "1",
            "cookiefile": request.cookiefile or None,
            "logger": QueueLogger(self.events, self.cancel),
            "progress_hooks": [self.progress_hook],
            "postprocessor_hooks": [self.postprocessor_hook],
            "quiet": True, "no_color": True, "socket_timeout": 15,
            "retries": 2, "fragment_retries": 2, "cachedir": False,
            "js_runtimes": runtimes,
        }
        if self.ffmpeg_path:
            options["ffmpeg_location"] = self.ffmpeg_path
        return options

    def download_options(self, request: DownloadRequest) -> dict:
        options = self.base_options(request)
        if not request.output_folder.strip():
            raise ValueError("Choose an output folder first.")
        folder = Path(request.output_folder).expanduser().resolve()
        folder.mkdir(parents=True, exist_ok=True)
        options.update({
            "paths": {"home": str(folder)},
            "outtmpl": "%(title).150B [%(id)s].%(ext)s",
            "windowsfilenames": True,
        })
        if request.mode == "Audio only (MP3)":
            if not self.ffmpeg:
                raise ValueError("MP3 conversion needs ffmpeg. Install it and restart the app.")
            options.update({"format": "bestaudio/best", "postprocessors": [{
                "key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192",
            }]})
        elif request.mode == "Video (MP4)":
            if request.quality == "Best":
                ceiling = ""
            elif request.quality in {"1080p", "720p", "480p", "360p"}:
                ceiling = f"[height<=?{request.quality[:-1]}]"
            else:
                raise ValueError("Choose a quality from the dropdown.")
            if self.ffmpeg:
                options.update({
                    "format": f"bestvideo{ceiling}+bestaudio/best{ceiling}",
                    "merge_output_format": "mp4",
                    "format_sort": ["vcodec:h264", "acodec:aac"],
                    # Also cover a single-stream fallback that arrives as WebM.
                    "postprocessors": [{"key": "FFmpegVideoRemuxer", "preferedformat": "mp4"}],
                })
            else:
                options["format"] = f"best[ext=mp4][vcodec!=none][acodec!=none]{ceiling}"
        else:
            raise ValueError("Choose Video (MP4) or Audio only (MP3).")
        return options

    def fetch_info(self, request: DownloadRequest) -> None:
        self._run("fetch", request)

    def download(self, request: DownloadRequest) -> None:
        self._run("download", request)

    def _run(self, operation: str, request: DownloadRequest) -> None:
        try:
            self.check_cancel()
            options = (self.download_options(request) if operation == "download"
                       else self.base_options(request))
            if operation == "fetch":
                # A preview must not depend on a downloadable merged format.
                options["ignore_no_formats_error"] = True
            if operation == "fetch" and request.playlist:
                options["playlistend"] = 1  # Preview the first item, never fetch every video here.
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(request.url, download=operation == "download")
            self.check_cancel()
            if info is None:
                raise ValueError("No accessible media was found at this link.")
            if operation == "fetch":
                playlist = info.get("_type") in {"playlist", "multi_video"}
                first = next((entry for entry in info.get("entries", []) if entry), None) if playlist else info
                if not first:
                    raise ValueError("This playlist has no accessible videos.")
                preview = {key: first.get(key) for key in ("title", "uploader", "duration", "thumbnail")}
                preview.update({"qualities": available_qualities(first, self.ffmpeg),
                                "playlist_title": info.get("title") if playlist else None})
                self.events.put({"type": "info", "info": preview})
                self._fetch_thumbnail(first.get("thumbnail"))
            self.check_cancel()
            self.events.put({"type": "done", "operation": operation})
        except DownloadCancelled:
            self.events.put({"type": "cancelled", "operation": operation})
        except DownloadError as error:
            self._report_error(operation, error)
        except Exception as error:
            self._report_error(operation, error)

    def _report_error(self, operation: str, error: Exception) -> None:
        # yt-dlp may wrap a hook exception in DownloadError.
        if self.cancel.is_set():
            self.events.put({"type": "cancelled", "operation": operation})
        else:
            self.events.put({"type": "error", "operation": operation,
                             "message": friendly_error(error, self.ffmpeg)})

    def _fetch_thumbnail(self, url: str | None) -> None:
        if not url:
            return
        try:
            if urlparse(url).scheme not in {"http", "https"}:
                return
            self.check_cancel()
            with urlopen(URLRequest(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=10) as response:
                data = response.read(2 * 1024 * 1024 + 1)
            self.check_cancel()
            if len(data) <= 2 * 1024 * 1024:
                self.events.put({"type": "thumbnail", "data": data})
        except DownloadCancelled:
            raise
        except Exception:
            self.events.put({"type": "log", "message": "Thumbnail unavailable; media info is ready."})
