"""Offline verification of the installed or frozen app and its bundled tools."""

import json
from pathlib import Path
from queue import Queue
import subprocess
import sys
import tempfile
from threading import Event
import tkinter as tk

import yt_dlp
from yt_dlp_ejs.yt.solver import core, lib

from ytdl_gui.downloader import DownloadRequest, Downloader, find_ffmpeg, find_tool
from ytdl_gui.ui import App


def run(report_path: str) -> int:
    report = {"passed": False, "frozen": bool(getattr(sys, "frozen", False))}
    root = None
    try:
        ffmpeg, node = find_ffmpeg(), find_tool("node")
        if not ffmpeg or not node:
            raise RuntimeError("ffmpeg and Node.js are required for the standalone build.")

        def execute(args):
            return subprocess.run(args, check=True, capture_output=True, text=True,
                                  encoding="utf-8", errors="replace", timeout=30,
                                  creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)

        report["ffmpeg"] = execute([ffmpeg, "-version"]).stdout.splitlines()[0]
        report["node"] = execute([node, "--version"]).stdout.strip()
        if execute([node, "-e", "console.log(6 * 7)"]).stdout.strip() != "42":
            raise RuntimeError("JavaScript execution failed.")
        if not core() or not lib():
            raise RuntimeError("YouTube challenge scripts are missing.")
        report["youtube_scripts"] = True
        options = Downloader(Queue(), Event()).base_options(DownloadRequest("https://youtu.be/abc"))
        with yt_dlp.YoutubeDL(options) as ydl:
            for extractor in ("Youtube", "Facebook"):
                ydl.get_info_extractor(extractor)
            if not ydl._js_runtimes["node"].info:
                raise RuntimeError("yt-dlp could not start the bundled JS runtime.")
        report["extractors"] = ["Youtube", "Facebook"]
        with tempfile.TemporaryDirectory(prefix="ytdl-selftest-") as folder:
            video = Path(folder) / "test.mp4"
            audio = Path(folder) / "test.mp3"
            execute([ffmpeg, "-nostdin", "-y", "-f", "lavfi", "-i", "color=s=160x90:r=10",
                     "-f", "lavfi", "-i", "sine=frequency=440", "-t", "1",
                     "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(video)])
            execute([ffmpeg, "-nostdin", "-y", "-i", str(video), "-vn", "-c:a",
                     "libmp3lame", "-b:a", "192k", str(audio)])
            for path in (video, audio):
                execute([ffmpeg, "-nostdin", "-i", str(path), "-map", "0", "-f", "null", "-"])
                if not path.stat().st_size:
                    raise RuntimeError(f"Empty media file: {path.name}")
        report["mp4_and_mp3"] = True
        root = tk.Tk()
        root.withdraw()
        app = App(root)
        root.update_idletasks()
        if not app.ffmpeg or "Audio only (MP3)" not in app.mode_combo["values"]:
            raise RuntimeError("Audio conversion is unavailable in the GUI.")
        report["gui"] = True
        report["passed"] = True
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"
    finally:
        if root is not None:
            root.destroy()
    Path(report_path).write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0 if report["passed"] else 1
