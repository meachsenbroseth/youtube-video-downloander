import json
from pathlib import Path
from queue import Queue
import tempfile
from threading import Event
import unittest
from unittest.mock import patch

from yt_dlp.utils import DownloadError

from ytdl_gui import config
from ytdl_gui.downloader import (DownloadRequest, Downloader, available_qualities,
                                 find_ffmpeg, find_tool, friendly_error, validate_url)


class DownloaderTests(unittest.TestCase):
    def test_frozen_launch_uses_bundled_tools_without_path(self):
        with tempfile.TemporaryDirectory() as folder:
            bundle = Path(folder)
            (bundle / "tools").mkdir()
            for name in ("ffmpeg", "node"):
                (bundle / "tools" / f"{name}.exe").touch()
            with patch("ytdl_gui.downloader.shutil.which", return_value=None), \
                    patch("ytdl_gui.downloader.sys.frozen", True, create=True), \
                    patch("ytdl_gui.downloader.sys._MEIPASS", str(bundle), create=True), \
                    patch("ytdl_gui.downloader.sys.platform", "win32"):
                worker = Downloader(Queue(), Event())
                self.assertTrue(worker.ffmpeg)
                options = worker.base_options(DownloadRequest("https://youtu.be/abc"))
                self.assertEqual(options["ffmpeg_location"], str(bundle / "tools/ffmpeg.exe"))
                self.assertEqual(options["js_runtimes"], {
                    "node": {"path": str(bundle / "tools/node.exe")}})
                self.assertIsNone(find_tool("deno"))

    def test_bundled_tool_takes_precedence_over_system_tool(self):
        with tempfile.TemporaryDirectory() as folder:
            bundle = Path(folder)
            (bundle / "tools").mkdir()
            companion = bundle / "tools/ffmpeg.exe"
            companion.touch()
            with patch("ytdl_gui.downloader.shutil.which", return_value="old-ffmpeg.exe"), \
                    patch("ytdl_gui.downloader.sys.frozen", True, create=True), \
                    patch("ytdl_gui.downloader.sys._MEIPASS", str(bundle), create=True), \
                    patch("ytdl_gui.downloader.sys.platform", "win32"):
                self.assertEqual(find_ffmpeg(), str(companion))

    def test_source_launch_finds_local_ffmpeg_without_path(self):
        with tempfile.TemporaryDirectory() as folder:
            project = Path(folder)
            companion = project / ".tools" / "bin" / "ffmpeg.exe"
            companion.parent.mkdir(parents=True)
            companion.touch()
            with patch("ytdl_gui.downloader.shutil.which", return_value=None), \
                    patch("ytdl_gui.downloader.__file__", str(project / "src/ytdl_gui/downloader.py")), \
                    patch("ytdl_gui.downloader.sys.frozen", False, create=True), \
                    patch("ytdl_gui.downloader.sys.platform", "win32"):
                self.assertEqual(find_ffmpeg(), str(companion))
                companion.unlink()
                self.assertIsNone(find_ffmpeg())

    def test_portable_launch_uses_companion_next_to_exe(self):
        with tempfile.TemporaryDirectory() as folder:
            executable = Path(folder) / "YTDL.exe"
            companion = Path(folder) / "ffmpeg.exe"
            companion.touch()
            with patch("ytdl_gui.downloader.shutil.which", return_value=None), \
                    patch("ytdl_gui.downloader.sys.frozen", True, create=True), \
                    patch("ytdl_gui.downloader.sys.executable", str(executable)), \
                    patch("ytdl_gui.downloader.sys.platform", "win32"):
                self.assertEqual(find_ffmpeg(), str(companion))
                worker = Downloader(Queue(), Event())
                options = worker.base_options(DownloadRequest("https://youtu.be/abc"))
                self.assertEqual(options["ffmpeg_location"], str(companion))
                companion.unlink()
                self.assertIsNone(find_ffmpeg())

    def test_format_error_explains_missing_ffmpeg(self):
        message = friendly_error(DownloadError("Requested format is not available"), ffmpeg=False)
        self.assertIn("video and audio tracks", message)
        self.assertIn("winget install ffmpeg", message)

    def test_supported_links_and_lookalike_host(self):
        for url in ("https://youtu.be/abc", "https://www.youtube.com/shorts/abc",
                    "https://www.youtube.com/playlist?list=abc", "https://m.facebook.com/reel/123",
                    "https://fb.watch/abc/", "https://www.facebook.com/watch/?v=123"):
            self.assertEqual(validate_url(url), url)
        for url in ("file:///tmp/movie", "https://youtube.com.attacker.test/abc", "youtube.com/watch?v=abc"):
            with self.assertRaises(ValueError):
                validate_url(url)

    def test_missing_ffmpeg_keeps_only_combined_mp4_qualities(self):
        info = {"formats": [
            {"height": 1080, "vcodec": "h264", "acodec": "none", "ext": "mp4"},
            {"height": 720, "vcodec": "vp9", "acodec": "opus", "ext": "webm"},
            {"height": 360, "vcodec": "h264", "acodec": "aac", "ext": "mp4"},
        ]}
        self.assertEqual(available_qualities(info, False), ["Best", "360p"])
        self.assertEqual(available_qualities(info, True), ["Best", "1080p", "720p", "360p"])
        with tempfile.TemporaryDirectory() as folder:
            queue = Queue()
            worker = Downloader(queue, Event(), ffmpeg=False)
            worker.download(DownloadRequest("https://youtu.be/abc", folder, mode="Audio only (MP3)"))
            terminal = queue.get_nowait()
            self.assertEqual(terminal["type"], "error")
            self.assertIn("ffmpeg", terminal["message"])

    def test_cancel_wrapped_by_yt_dlp_reports_cancelled(self):
        queue, cancel = Queue(), Event()
        worker = Downloader(queue, cancel, ffmpeg=True)
        with tempfile.TemporaryDirectory() as folder, patch("ytdl_gui.downloader.yt_dlp.YoutubeDL") as factory:
            def interrupted(*_args, **_kwargs):
                cancel.set()
                try:
                    worker.progress_hook({"status": "downloading", "downloaded_bytes": 1024})
                except Exception as error:
                    raise DownloadError("hook failed") from error
            factory.return_value.__enter__.return_value.extract_info.side_effect = interrupted
            worker.download(DownloadRequest("https://youtu.be/abc", folder))
        self.assertEqual(queue.get_nowait()["type"], "cancelled")

    def test_download_error_is_friendly_terminal_event(self):
        queue = Queue()
        with patch("ytdl_gui.downloader.yt_dlp.YoutubeDL") as factory:
            factory.return_value.__enter__.return_value.extract_info.side_effect = DownloadError("ERROR: HTTP Error 403")
            Downloader(queue, Event()).fetch_info(DownloadRequest("https://youtu.be/abc"))
        result = queue.get_nowait()
        self.assertEqual(result["type"], "error")
        self.assertIn("refused access", result["message"])

    def test_playlist_preview_does_not_extract_all_entries(self):
        queue = Queue()
        with patch("ytdl_gui.downloader.yt_dlp.YoutubeDL") as factory:
            factory.return_value.__enter__.return_value.extract_info.return_value = {
                "_type": "playlist", "title": "Collection", "entries": [{"title": "First", "formats": []}]}
            Downloader(queue, Event()).fetch_info(DownloadRequest("https://www.youtube.com/playlist?list=abc", playlist=True))
            self.assertEqual(factory.call_args.args[0]["playlistend"], 1)
            self.assertFalse(factory.call_args.args[0]["noplaylist"])
        self.assertEqual(queue.get_nowait()["info"]["playlist_title"], "Collection")
        self.assertEqual(queue.get_nowait()["type"], "done")

    def test_playlist_only_url_is_limited_when_checkbox_is_off(self):
        worker = Downloader(Queue(), Event())
        request = DownloadRequest("https://www.youtube.com/playlist?list=abc")
        options = worker.base_options(request)
        self.assertTrue(options["noplaylist"])
        self.assertEqual(options["playlist_items"], "1")


class ConfigTests(unittest.TestCase):
    def test_corrupt_config_and_folder_roundtrip(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            with patch.dict("os.environ", {"YTDL_GUI_CONFIG": str(path)}):
                path.write_text("invalid JSON", encoding="utf-8")
                self.assertEqual(config.load_output_folder(), str(Path.home() / "Downloads"))
                config.save_output_folder(folder)
                self.assertEqual(config.load_output_folder(), folder)
                self.assertEqual(set(json.loads(path.read_text())), {"output_folder"})


if __name__ == "__main__":
    unittest.main()
