import io
import threading
import time
import tkinter as tk
import unittest
from unittest.mock import patch

from PIL import Image

from ytdl_gui.ui import App


class UITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.host = tk.Tk()
        cls.host.withdraw()

    @classmethod
    def tearDownClass(cls):
        cls.host.update_idletasks()
        cls.host.destroy()

    def setUp(self):
        self.root = tk.Toplevel(self.host)
        self.root.withdraw()
        self.patches = [patch("ytdl_gui.ui.has_ffmpeg", return_value=True),
                        patch("ytdl_gui.ui.save_output_folder"),
                        patch("ytdl_gui.ui.messagebox.showerror")]
        self.mocks = [item.start() for item in self.patches]
        self.app = App(self.root)
        self.app.url.set("https://youtu.be/abc")

    def tearDown(self):
        self.root.update_idletasks()
        self.root.destroy()
        for item in reversed(self.patches):
            item.stop()

    def pump_until_idle(self):
        deadline = time.monotonic() + 3
        while self.app.busy and time.monotonic() < deadline:
            self.root.update()
            time.sleep(0.01)
        self.assertFalse(self.app.busy)

    def test_worker_result_is_polled_and_inputs_recover_after_error(self):
        main_thread = threading.get_ident()
        observed = []
        def fetch(worker, request):
            observed.append(threading.get_ident())
            worker.events.put({"type": "error", "operation": "fetch", "message": "Test error"})
        with patch("ytdl_gui.ui.Downloader.fetch_info", fetch):
            self.app._fetch()
            self.assertEqual(str(self.app.url_entry["state"]), "disabled")
            self.pump_until_idle()
        self.assertNotEqual(observed[0], main_thread)
        self.assertEqual(str(self.app.url_entry["state"]), "normal")
        self.mocks[-1].assert_called_once()

    def test_cancel_button_reaches_worker_without_touching_widgets(self):
        def download(worker, request):
            worker.cancel.wait(2)
            worker.events.put({"type": "cancelled", "operation": "download"})
        with patch("ytdl_gui.ui.Downloader.download", download):
            self.app._download()
            self.app._cancel()
            self.pump_until_idle()
        self.assertEqual(self.app.status.get(), "Cancelled")
        self.assertEqual(str(self.app.download_button["state"]), "normal")
        self.assertEqual(str(self.app.cancel_button["state"]), "disabled")

    def test_no_ffmpeg_warns_and_disables_mp3(self):
        other = tk.Toplevel(self.root)
        try:
            with patch("ytdl_gui.ui.has_ffmpeg", return_value=False), \
                    patch("ytdl_gui.ui.messagebox.showwarning") as warning:
                app = App(other)
                self.assertEqual(tuple(app.mode_combo["values"]), ("Video (MP4)",))
                app._warn_ffmpeg()
                warning.assert_called_once()
                self.assertIn("winget install ffmpeg", warning.call_args.args[1])
        finally:
            other.destroy()

    def test_minimum_window_keeps_log_and_controls_visible(self):
        self.root.geometry("640x520")
        self.root.deiconify()
        data = io.BytesIO()
        Image.new("RGB", (320, 180), "blue").save(data, format="PNG")
        self.app._handle_event({"type": "thumbnail", "data": data.getvalue()})
        self.root.update()
        self.assertTrue(self.app.log.winfo_ismapped())
        self.assertGreaterEqual(self.app.log.winfo_height(), 25)
        self.assertLess(self.app.download_button.winfo_rooty() - self.root.winfo_rooty(), 520)


if __name__ == "__main__":
    unittest.main()
