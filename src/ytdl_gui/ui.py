"""Tkinter interface. Only the main thread owns widgets and Tk variables."""

import io
import os
from queue import Empty, Queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

from ytdl_gui.config import load_output_folder, save_output_folder
from ytdl_gui.downloader import DownloadRequest, Downloader, has_ffmpeg, validate_url


def duration_text(seconds: float | None) -> str:
    if seconds is None:
        return "Unknown / live"
    seconds = max(0, int(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, seconds = divmod(rest, 60)
    return f"{hours}:{minutes:02}:{seconds:02}" if hours else f"{minutes}:{seconds:02}"


def speed_text(speed: float | None) -> str:
    if speed is None:
        return "Speed: —"
    for unit in ("B/s", "KiB/s", "MiB/s", "GiB/s"):
        if speed < 1024 or unit == "GiB/s":
            return f"Speed: {speed:.1f} {unit}"
        speed /= 1024
    return "Speed: —"


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.ffmpeg = has_ffmpeg()
        self.events: Queue = Queue()
        self.cancel_event = threading.Event()
        self.worker: threading.Thread | None = None
        self.busy = False
        self.closing = False
        self.operation = ""
        self.photo: ImageTk.PhotoImage | None = None
        self.controls: list[tuple[ttk.Widget, str]] = []
        self.url = tk.StringVar()
        self.folder = tk.StringVar(value=load_output_folder())
        self.cookies = tk.StringVar()
        self.mode = tk.StringVar(value="Video (MP4)")
        self.quality = tk.StringVar(value="Best")
        self.playlist = tk.BooleanVar(value=False)
        self.title = tk.StringVar(value="Paste a link to get started")
        self.uploader = tk.StringVar(value="Uploader: —")
        self.duration = tk.StringVar(value="Duration: —")
        self.percent = tk.StringVar(value="0%")
        self.speed = tk.StringVar(value="Speed: —")
        self.eta = tk.StringVar(value="ETA: —")
        self.current = tk.StringVar(value="Ready")
        self.status = tk.StringVar(value="Ready • ffmpeg available" if self.ffmpeg
                                   else "Ready • combined MP4 only (ffmpeg missing)")
        self._build()
        for variable in (self.url, self.cookies, self.playlist):
            variable.trace_add("write", self._source_changed)
        self.mode.trace_add("write", self._mode_changed)
        root.protocol("WM_DELETE_WINDOW", self._close)
        self._poll_id = root.after(100, self._poll)
        self._warn_id = None
        root.bind("<Destroy>", self._destroyed, add="+")
        if not self.ffmpeg:
            self._warn_id = root.after(200, self._warn_ffmpeg)

    def _destroyed(self, event) -> None:
        if event.widget is not self.root:
            return
        for callback in (self._poll_id, self._warn_id):
            if callback:
                self.root.after_cancel(callback)

    def _control(self, widget: ttk.Widget, idle: str = "normal") -> ttk.Widget:
        self.controls.append((widget, idle))
        return widget

    def _build(self) -> None:
        root = self.root
        root.title("YTDL • Video & Audio Downloader")
        root.geometry("800x700")
        root.minsize(640, 520)
        style = ttk.Style(root)
        style.theme_use("vista" if os.name == "nt" and "vista" in style.theme_names() else "clam")
        style.configure("Title.TLabel", font=("Segoe UI", 10, "bold"))
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)
        body = ttk.Frame(root, padding=10)
        body.grid(row=0, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.rowconfigure(6, weight=1)
        source = ttk.LabelFrame(body, text="YouTube or Facebook link", padding=6)
        source.grid(row=1, column=0, sticky="ew", pady=(0, 6))
        source.columnconfigure(0, weight=1)
        self.url_entry = self._control(ttk.Entry(source, textvariable=self.url))
        self.url_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self._control(ttk.Button(source, text="Paste", command=self._paste)).grid(row=0, column=1, padx=(0, 8))
        self.fetch_button = self._control(ttk.Button(source, text="Fetch Info", command=self._fetch))
        self.fetch_button.grid(row=0, column=2)
        self._control(ttk.Checkbutton(source, text="Download full playlist", variable=self.playlist)).grid(
            row=1, column=0, columnspan=3, sticky="w", pady=(4, 0))

        preview = ttk.LabelFrame(body, text="Media info", padding=6)
        preview.grid(row=2, column=0, sticky="ew", pady=(0, 6))
        preview.columnconfigure(1, weight=1)
        self.thumbnail = ttk.Label(preview, text="No preview", width=18, anchor="center")
        self.thumbnail.grid(row=0, column=0, rowspan=2, padx=(0, 12))
        self.title_label = ttk.Label(preview, textvariable=self.title, style="Title.TLabel", wraplength=480)
        self.title_label.grid(row=0, column=1, sticky="w")
        self.title_label.bind("<Configure>", lambda event: self.title_label.configure(
            wraplength=max(200, preview.winfo_width() - 215)))
        details = ttk.Frame(preview)
        details.grid(row=1, column=1, sticky="w", pady=(5, 0))
        ttk.Label(details, textvariable=self.uploader, wraplength=220).pack(side="left", padx=(0, 12))
        ttk.Label(details, textvariable=self.duration).pack(side="left")

        options = ttk.LabelFrame(body, text="Download options", padding=6)
        options.grid(row=3, column=0, sticky="ew", pady=(0, 6))
        options.columnconfigure(1, weight=1)
        ttk.Label(options, text="Mode").grid(row=0, column=0, sticky="w", padx=(0, 10))
        mode_values = ("Video (MP4)", "Audio only (MP3)") if self.ffmpeg else ("Video (MP4)",)
        self.mode_combo = self._control(ttk.Combobox(options, textvariable=self.mode,
                                                   values=mode_values, state="readonly"), "readonly")
        self.mode_combo.grid(row=0, column=1, sticky="ew", padx=(0, 12))
        ttk.Label(options, text="Quality").grid(row=0, column=2, padx=(0, 8))
        self.quality_combo = self._control(ttk.Combobox(options, textvariable=self.quality,
                                                      values=("Best",), width=10, state="readonly"), "readonly")
        self.quality_combo.grid(row=0, column=3, sticky="ew")
        ttk.Label(options, text="Save to").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self._control(ttk.Entry(options, textvariable=self.folder)).grid(
            row=1, column=1, columnspan=2, sticky="ew", padx=(0, 8), pady=(6, 0))
        self._control(ttk.Button(options, text="Browse…", command=self._pick_folder)).grid(
            row=1, column=3, sticky="ew", pady=(6, 0))
        ttk.Label(options, text="Cookies (optional)").grid(row=2, column=0, sticky="w", pady=(6, 0), padx=(0, 10))
        self._control(ttk.Entry(options, textvariable=self.cookies)).grid(
            row=2, column=1, columnspan=2, sticky="ew", padx=(0, 8), pady=(6, 0))
        cookie_buttons = ttk.Frame(options)
        cookie_buttons.grid(row=2, column=3, pady=(6, 0))
        self._control(ttk.Button(cookie_buttons, text="Choose…", command=self._pick_cookies)).pack(side="left")
        self._control(ttk.Button(cookie_buttons, text="×", width=3,
                                 command=lambda: self.cookies.set(""))).pack(side="left", padx=(4, 0))
        actions = ttk.Frame(body)
        actions.grid(row=4, column=0, sticky="ew", pady=(0, 6))
        self.download_button = self._control(ttk.Button(actions, text="Download", command=self._download))
        self.download_button.pack(side="left")
        self.cancel_button = ttk.Button(actions, text="Cancel", command=self._cancel, state="disabled")
        self.cancel_button.pack(side="left", padx=(8, 0))
        ttk.Label(actions, textvariable=self.current, wraplength=530).pack(side="left", padx=(12, 0))

        progress = ttk.Frame(body)
        progress.grid(row=5, column=0, sticky="ew", pady=(0, 6))
        progress.columnconfigure(0, weight=1)
        self.progress = ttk.Progressbar(progress, maximum=100, mode="determinate")
        self.progress.grid(row=0, column=0, columnspan=3, sticky="ew")
        ttk.Label(progress, textvariable=self.percent).grid(row=1, column=0, sticky="w", pady=(5, 0))
        ttk.Label(progress, textvariable=self.speed).grid(row=1, column=1, padx=20, pady=(5, 0))
        ttk.Label(progress, textvariable=self.eta).grid(row=1, column=2, sticky="e", pady=(5, 0))

        logs = ttk.LabelFrame(body, text="Activity log", padding=8)
        logs.grid(row=6, column=0, sticky="nsew")
        logs.columnconfigure(0, weight=1)
        logs.rowconfigure(0, weight=1)
        self.log = tk.Text(logs, height=6, wrap="word", state="disabled", font=("Consolas", 9),
                           relief="flat", padx=6, pady=6)
        self.log.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(logs, command=self.log.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.log.configure(yscrollcommand=scrollbar.set)
        ttk.Label(root, textvariable=self.status, anchor="w", relief="sunken", padding=(12, 6)).grid(
            row=1, column=0, sticky="ew")
        self.url_entry.focus_set()

    def _warn_ffmpeg(self) -> None:
        instructions = ("winget install ffmpeg" if os.name == "nt"
                        else "macOS: brew install ffmpeg\nDebian/Ubuntu: sudo apt install ffmpeg")
        messagebox.showwarning("ffmpeg is missing", "Install ffmpeg and make sure it is on PATH:\n\n"
                               + instructions + "\n\nRestart this app after installing. MP3 conversion and "
                               "separate video/audio merging are disabled. Combined MP4 formats still work. "
                               "You can also place ffmpeg.exe beside YTDL.exe on Windows.",
                               parent=self.root)

    def _source_changed(self, *_args) -> None:
        if self.busy:
            return
        self.quality_combo.configure(values=("Best",))
        self.quality.set("Best")
        self.title.set("Fetch info to preview this link")
        self.uploader.set("Uploader: —")
        self.duration.set("Duration: —")
        self.thumbnail.configure(image="", text="No preview")
        self.photo = None

    def _mode_changed(self, *_args) -> None:
        self.quality_combo.configure(state="disabled" if self.busy or self.mode.get() == "Audio only (MP3)"
                                     else "readonly")

    def _paste(self) -> None:
        try:
            self.url.set(self.root.clipboard_get().strip())
            self.url_entry.focus_set()
            self.url_entry.icursor("end")
        except tk.TclError:
            self._log("The clipboard does not contain text.")

    def _pick_folder(self) -> None:
        folder = filedialog.askdirectory(parent=self.root, initialdir=self.folder.get(), title="Save downloads to")
        if folder:
            self.folder.set(folder)
            self._save_folder()

    def _pick_cookies(self) -> None:
        path = filedialog.askopenfilename(parent=self.root, title="Choose Netscape cookies.txt",
                                          filetypes=[("Cookie files", "*.txt"), ("All files", "*.*")])
        if path:
            self.cookies.set(path)

    def _save_folder(self) -> None:
        try:
            save_output_folder(self.folder.get())
        except OSError as error:
            self._log(f"Could not remember the output folder: {error}")

    def _request(self) -> DownloadRequest:
        return DownloadRequest(url=validate_url(self.url.get()), output_folder=self.folder.get().strip(),
                               mode=self.mode.get(), quality=self.quality.get(), playlist=self.playlist.get(),
                               cookiefile=self.cookies.get().strip() or None)

    def _fetch(self) -> None:
        self._start("fetch")

    def _download(self) -> None:
        self._start("download")

    def _start(self, operation: str) -> None:
        if self.busy:
            return
        try:
            request = self._request()
            if operation == "download" and not request.output_folder:
                raise ValueError("Choose an output folder first.")
        except ValueError as error:
            self._log(str(error))
            messagebox.showerror("Check download settings", str(error), parent=self.root)
            return
        if operation == "download":
            self._save_folder()
        self.operation = operation
        self.cancel_event.clear()
        self._set_busy(True)
        self.progress.stop()
        self.progress.configure(mode="indeterminate", value=0)
        self.progress.start(12)
        self.percent.set("—")
        self.speed.set("Speed: —")
        self.eta.set("ETA: —")
        self.current.set("Fetching info…" if operation == "fetch" else "Preparing download…")
        self.status.set(self.current.get())
        self._log(self.current.get())
        downloader = Downloader(self.events, self.cancel_event, self.ffmpeg)
        target = downloader.fetch_info if operation == "fetch" else downloader.download
        self.worker = threading.Thread(target=target, args=(request,), daemon=True, name=f"ytdl-{operation}")
        self.worker.start()

    def _set_busy(self, value: bool) -> None:
        self.busy = value
        for widget, idle in self.controls:
            widget.configure(state="disabled" if value else idle)
        self.cancel_button.configure(state="normal" if value else "disabled")
        self._mode_changed()

    def _cancel(self) -> None:
        self.cancel_event.set()
        self.cancel_button.configure(state="disabled")
        self.current.set("Cancelling…")
        self.status.set("Cancelling at the next network or processing boundary…")
        self._log("Cancellation requested. An active ffmpeg operation may need to finish first.")

    def _log(self, message: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", str(message) + "\n")
        if int(self.log.index("end-1c").split(".")[0]) > 1200:
            self.log.delete("1.0", "201.0")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _poll(self) -> None:
        for _ in range(200):
            try:
                event = self.events.get_nowait()
            except Empty:
                break
            self._handle_event(event)
        # Terminal events precede worker return by a few instructions. Do not allow
        # a new job (or close) until that worker has really released its files.
        if hasattr(self, "_terminal") and self.worker and not self.worker.is_alive():
            event = self._terminal
            del self._terminal
            self._finish(event)
        if self.closing and not self.busy:
            self.root.destroy()
            return
        self._poll_id = self.root.after(100, self._poll)

    def _handle_event(self, event: dict) -> None:
        kind = event["type"]
        if kind == "log":
            self._log(event["message"])
        elif kind == "info":
            info = event["info"]
            self.title.set(info.get("title") or "Untitled")
            self.uploader.set("Uploader: " + (info.get("uploader") or "Unknown"))
            self.duration.set("Duration: " + duration_text(info.get("duration")))
            self.quality_combo.configure(values=info["qualities"])
            if self.quality.get() not in info["qualities"]:
                self.quality.set("Best")
            self._log("Found: " + self.title.get())
            if info.get("playlist_title"):
                self._log(f"Playlist: {info['playlist_title']} (previewing its first accessible item). "
                          "Quality is a ceiling applied independently to each downloaded item.")
        elif kind == "thumbnail":
            try:
                with Image.open(io.BytesIO(event["data"])) as image:
                    image.thumbnail((112, 63))
                    self.photo = ImageTk.PhotoImage(image.copy(), master=self.root)
                self.thumbnail.configure(image=self.photo, text="", width="")
            except Exception:
                self._log("Could not display the thumbnail.")
        elif kind == "progress":
            if self.cancel_event.is_set():
                return
            total = event.get("total")
            if event["status"] == "finished":
                self.progress.stop()
                self.progress.configure(mode="indeterminate")
                self.progress.start(12)
                self.percent.set("Processing…")
                self.current.set("Transfer finished; processing media…")
                self.speed.set("Speed: —")
                self.eta.set("ETA: —")
            elif total:
                value = min(100, event["downloaded"] / total * 100)
                self.progress.stop()
                self.progress.configure(mode="determinate", value=value)
                self.percent.set(f"{value:.1f}%")
                self.speed.set(speed_text(event.get("speed")))
                self.eta.set("ETA: " + (duration_text(event["eta"]) if event.get("eta") is not None else "—"))
                position = f"Item {event['index']} of {event.get('count') or '?'} • " if event.get("index") else ""
                self.current.set((position + (event.get("title") or "Downloading…"))[:85])
            else:
                if self.progress["mode"] != "indeterminate":
                    self.progress.configure(mode="indeterminate")
                    self.progress.start(12)
                self.percent.set(f"{event['downloaded'] / 1024 / 1024:.1f} MiB")
                self.speed.set(speed_text(event.get("speed")))
                self.eta.set("ETA: —")
        elif kind == "phase":
            if not self.cancel_event.is_set():
                self.current.set(event["message"])
                self.status.set(event["message"])
        elif kind in {"done", "cancelled", "error"}:
            self._terminal = event

    def _finish(self, event: dict) -> None:
        self.progress.stop()
        self.progress.configure(mode="determinate")
        self._set_busy(False)
        self.speed.set("Speed: —")
        self.eta.set("ETA: —")
        if event["type"] == "done":
            downloaded = event["operation"] == "download"
            self.progress.configure(value=100 if downloaded else 0)
            self.percent.set("100%" if downloaded else "Ready")
            result = "Download complete" if downloaded else "Info ready"
            self._log(result + (f" • {self.folder.get()}" if downloaded else ""))
        elif event["type"] == "cancelled":
            result = "Cancelled"
            self.percent.set("Cancelled")
            self._log("Cancelled. Partial files can be resumed by downloading the same link again.")
        else:
            result = "Failed • see activity log"
            self.percent.set("Failed")
            self._log(event["message"])
            if not self.closing:
                messagebox.showerror("Download error", event["message"], parent=self.root)
        self.current.set(result)
        self.status.set(result)

    def _close(self) -> None:
        if self.closing:
            return
        if self.busy:
            if not messagebox.askyesno("Cancel and close?", "An operation is running. Cancel it and close "
                                      "after it stops?", parent=self.root):
                return
            self.closing = True
            self._cancel()
        else:
            self._save_folder()
            self.root.destroy()


def main() -> None:
    root = tk.Tk()
    App(root)
    root.mainloop()
