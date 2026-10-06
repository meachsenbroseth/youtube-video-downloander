# Developer guide

[Back to the README](../README.md)

## Source setup

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) and open a
terminal in the project root. The repository pins Python 3.12 and includes
`uv.lock` for dependency versions.

```powershell
uv sync --locked
uv run python -m ytdl_gui
```

For media merging and audio conversion, get ffmpeg from the
[FFmpeg download page](https://ffmpeg.org/download.html). On Windows, put
`ffmpeg.exe` in `.tools/bin/` or add its directory to `PATH`.

For YouTube challenges, install Deno or Node.js 22+ and make it discoverable on
`PATH`. The app enables whichever of those runtimes it finds. The `yt-dlp[default]`
dependency includes the `yt-dlp-ejs` companion scripts. Refer to
[yt-dlp's JavaScript setup guide](https://github.com/yt-dlp/yt-dlp/wiki/EJS)
for runtime requirements.

If Tkinter is unavailable on Linux, install the Tk package provided by your
distribution, such as `python3-tk` on Debian/Ubuntu.

Without ffmpeg, source launches disable MP3 mode and offer only MP4 formats
that already contain both video and audio. Some links have no such format.

## Project structure

```text
ytdl-gui/
├── README.md
├── build_windows.py          # Single-file Windows packaging
├── pyproject.toml            # Project metadata and dependencies
├── uv.lock                   # Locked dependency versions
├── docs/
│   └── DEVELOPMENT.md
├── src/ytdl_gui/
│   ├── __main__.py           # App entry point and self-test dispatch
│   ├── ui.py                 # Tkinter interface
│   ├── downloader.py         # yt-dlp options, workers, and queue events
│   ├── config.py             # Output-folder settings
│   └── selftest.py           # Offline installation verification
└── tests/
    ├── test_downloader.py    # Formats, validation, tools, errors, settings
    ├── test_ui.py            # GUI state, workers, cancellation, layout
    └── live_check.py         # Opt-in live YouTube and media check
```

Network operations run in worker threads. Workers send events through
`queue.Queue`; the interface polls the queue with `root.after(100, ...)`. Only
the main thread reads or changes widgets and Tk variables.

Cancellation uses `threading.Event` and is checked at extraction boundaries and
in download/postprocessing hooks. It does not immediately interrupt every
network request or ffmpeg process.

## Standalone Windows build

Build on Windows with x64 Python and x64 tool executables for the Windows x64
artifact. Install the project environment, put ffmpeg at `.tools/bin/ffmpeg.exe`,
and make Node.js 22+ available on `PATH`:

```powershell
uv sync --locked
uv run python build_windows.py
```

To use tools from other locations:

```powershell
uv run python build_windows.py --ffmpeg C:\tools\ffmpeg.exe --node C:\tools\node.exe
```

The script checks the tool paths and Node.js version, then uses PyInstaller's
single-file, windowed mode. It writes:

| Output | Purpose |
| --- | --- |
| `dist/YTDL.exe` | Standalone application for distribution |
| `build/YTDL.spec` | Generated PyInstaller specification |
| `build/YTDL/` | Build intermediates and analysis reports |

The executable includes Python, Tkinter, Pillow, yt-dlp, ffmpeg, Node.js, and
the `yt-dlp-ejs` scripts and package metadata. The bundle extracts to a temporary
directory at launch; see [PyInstaller's runtime documentation](https://pyinstaller.org/en/stable/runtime-information.html).

Tool lookup checks bundled tools first for a frozen executable, then `PATH`,
then companions beside the executable. Source launches check `PATH`, the project
directory, and `.tools/bin/`.

Use `build_windows.py` to produce the complete standalone app. The generated
files and local tool binaries are excluded from Git.

## Verification

### Regression tests

Run from the project root:

```powershell
uv run python -m unittest discover -s tests -v
```

Tk tests require a graphical desktop. The suite covers tool discovery,
format selection, playlist options, URL validation, settings, errors, worker
threading, cancellation, and interface layout.

### Offline executable check

Run the built application with a JSON report path:

```powershell
$appCheck = Start-Process .\dist\YTDL.exe -ArgumentList '--self-test', 'standalone-report.json' -Wait -PassThru
Get-Content standalone-report.json
if ($appCheck.ExitCode -ne 0) { throw 'Standalone verification failed.' }
```

A successful report has `"passed": true` and `"frozen": true`. The check
initializes the GUI, loads the YouTube and Facebook extractors, reads the bundled
challenge scripts, runs Node.js, and creates and fully decodes short MP4 and MP3
test files. Temporary media is removed when the check ends.

This check uses generated media and makes no live video download. To verify
portability, copy only `YTDL.exe` into another folder and repeat the check on a
Windows computer without separately installed Python, ffmpeg, or Node.js.

### Live download check

With internet access, ffmpeg, and a JavaScript runtime available:

```powershell
uv run python tests/live_check.py
```

This opens the app, fetches the public **Me at the zoo** video, downloads MP4
and MP3, inspects the resulting media, and cancels a throttled download after
positive progress. It writes downloads and `live-report.json` into
`test-output/`. ffprobe is optional; ffmpeg is used to inspect and decode the
media when ffprobe is unavailable. Site restrictions can affect this live check.

## Dependency updates

Update the extractor and its challenge scripts together:

```powershell
uv lock --upgrade-package yt-dlp --upgrade-package yt-dlp-ejs
uv sync
```

Run the regression checks and rebuild the executable after updating. An already
built executable keeps its bundled dependency versions until it is replaced.

## GitHub releases

After the repository is on GitHub:

1. Build `dist/YTDL.exe` and run the regression and executable checks.
2. Open the repository's **Releases** page and create a release with the chosen
   version tag and release notes.
3. Attach **`dist/YTDL.exe`** as a release asset.
4. Describe the supported platform, changes, and how to run the executable.
5. Publish the release when it is ready.

The executable belongs in release assets; `dist/` is excluded from source
commits. Instructions for the GitHub release interface are in
[GitHub's release guide](https://docs.github.com/en/repositories/releasing-projects-on-github/managing-releases-in-a-repository).

## Contributing

Describe the user-visible problem and expected behavior before making a change.
Keep yt-dlp logic in `downloader.py` and widget access in `ui.py`. Run checks
appropriate to the change and include their results with a pull request.

Do not commit cookie files, private URLs, personal settings, or downloaded media.
