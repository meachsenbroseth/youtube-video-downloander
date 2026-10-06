"""Opt-in live GUI check: uv run python tests/live_check.py.

Requires ffmpeg on PATH or locally and access to YouTube (ffprobe is optional). Keeps test downloads
and a machine-readable report in test-output/. Uses the real Tk mainloop.
"""

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
import tkinter as tk
from unittest.mock import patch

from ytdl_gui.downloader import Downloader, find_ffmpeg
from ytdl_gui.ui import App


def main():
    ffmpeg_path = find_ffmpeg()
    if not ffmpeg_path:
        raise SystemExit("Put ffmpeg on PATH or in .tools/bin/ before the live check.")
    output = Path("test-output").resolve()
    output.mkdir(exist_ok=True)
    os.environ["YTDL_GUI_CONFIG"] = str(output / "config.json")
    root = tk.Tk()
    app = App(root)
    app.url.set("https://www.youtube.com/watch?v=jNQXAC9IVRw")
    app.folder.set(str(output / "video"))
    report = {"url": app.url.get(), "checks": [], "errors": []}
    stage = "fetch"
    started = time.monotonic()
    original_options = Downloader.download_options
    cancelling = False
    progress_seen = False
    beats = 0

    def options(worker, request):
        result = original_options(worker, request)
        if "cancel" in request.output_folder:
            result["ratelimit"] = 32 * 1024
            def observe(data):
                nonlocal progress_seen
                if data.get("status") == "downloading" and data.get("downloaded_bytes", 0) > 0:
                    progress_seen = True
            result["progress_hooks"].append(observe)
        return result

    def show_error(_title, message, **_kwargs):
        report["errors"].append(message)

    def probe(path):
        if shutil.which("ffprobe"):
            result = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format",
                                     "-of", "json", str(path)], check=True, capture_output=True,
                                    text=True, encoding="utf-8", errors="replace")
            data = json.loads(result.stdout)
            metadata = {"format": data["format"]["format_name"],
                        "duration": float(data["format"]["duration"]),
                        "streams": [stream["codec_type"] for stream in data["streams"]],
                        "codecs": [stream["codec_name"] for stream in data["streams"]]}
        else:
            # Decode every stream as well as inspecting the actual media container.
            result = subprocess.run([ffmpeg_path, "-nostdin", "-i", str(path), "-map", "0",
                                     "-f", "null", "-"], check=True, capture_output=True,
                                    text=True, encoding="utf-8", errors="replace")
            source = result.stderr.split("Output #", 1)[0]
            hours, minutes, seconds = re.search(r"Duration: (\d+):(\d+):([\d.]+)", source).groups()
            streams = re.findall(r"Stream #.*?: (Video|Audio): ([\w]+)", source)
            metadata = {"format": re.search(r"Input #0, (.*?), from", source).group(1),
                        "duration": int(hours) * 3600 + int(minutes) * 60 + float(seconds),
                        "streams": [kind.lower() for kind, _ in streams],
                        "codecs": [codec for _, codec in streams], "fully_decoded": True}
        return {"path": str(path), "bytes": path.stat().st_size, **metadata}

    def finish():
        report["mainloop_ticks"] = beats
        report["log"] = app.log.get("1.0", "end")
        (output / "live-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps({key: value for key, value in report.items() if key != "log"}, indent=2), flush=True)
        root.destroy()

    def tick():
        nonlocal stage, cancelling, beats
        beats += 1
        try:
            if time.monotonic() - started > 240:
                raise AssertionError("Live check timed out")
            if stage == "cancel" and progress_seen and app.busy and not cancelling:
                app._cancel()
                cancelling = True
            if app.busy:
                assert str(app.url_entry["state"]) == "disabled"
            else:
                assert str(app.download_button["state"]) == "normal"
                assert not report["errors"], report["errors"]
                if stage == "fetch":
                    assert app.status.get() == "Info ready", app.status.get()
                    assert app.title.get() == "Me at the zoo", app.title.get()
                    report["checks"].append({"fetch": app.title.get(), "duration": app.duration.get(),
                                             "qualities": list(app.quality_combo["values"])})
                    stage = "video"
                    app.quality.set("360p" if "360p" in app.quality_combo["values"] else "Best")
                    app._download()
                elif stage == "video":
                    assert app.status.get() == "Download complete", app.status.get()
                    path = next((output / "video").glob("*.mp4"))
                    metadata = probe(path)
                    assert "video" in metadata["streams"] and "audio" in metadata["streams"]
                    assert 17 < metadata["duration"] < 22
                    report["checks"].append({"mp4": metadata})
                    stage = "audio"
                    app.mode.set("Audio only (MP3)")
                    app.folder.set(str(output / "audio"))
                    app._download()
                elif stage == "audio":
                    assert app.status.get() == "Download complete", app.status.get()
                    metadata = probe(next((output / "audio").glob("*.mp3")))
                    assert metadata["codecs"] == ["mp3"] and 17 < metadata["duration"] < 22
                    report["checks"].append({"mp3": metadata})
                    stage = "cancel"
                    app.mode.set("Video (MP4)")
                    app.folder.set(str(output / "cancel"))
                    app._download()
                else:
                    assert progress_seen and cancelling and app.status.get() == "Cancelled"
                    assert not list((output / "cancel").glob("*.mp4"))
                    report["checks"].append({"cancel": "Stopped after positive download progress; controls recovered"})
                    finish()
                    return
        except Exception as error:
            report["errors"].append(str(error))
            app.cancel_event.set()
            finish()
            return
        root.after(50, tick)

    with patch.object(Downloader, "download_options", options), \
            patch("ytdl_gui.ui.messagebox.showerror", show_error):
        app._fetch()
        root.after(50, tick)
        root.mainloop()
    if report["errors"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
