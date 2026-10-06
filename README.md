# YTDL — Video & Audio Downloader

A desktop app for downloading YouTube and Facebook videos as **MP4 video** or
**MP3 audio**. Preview media, choose a quality, and track downloads in a simple
Windows interface.

The standalone **Windows x64** executable includes Python, ffmpeg, Node.js, and
the YouTube JavaScript challenge scripts. Move one file and double-click to run.

## Contents

- [Features](#features)
- [Run the Windows app](#run-the-windows-app)
- [Download a video or audio](#download-a-video-or-audio)
- [Playlists](#playlists)
- [Cookies](#cookies)
- [Settings and downloaded files](#settings-and-downloaded-files)
- [Run from source](#run-from-source)
- [Build a standalone executable](#build-a-standalone-executable)
- [Troubleshooting](#troubleshooting)
- [Development](#development)

## Features

| Feature | Details |
| --- | --- |
| YouTube | Videos, Shorts, and playlists |
| Facebook | Public videos, Reels, Watch links, and `fb.watch` links |
| Video | MP4 with video and audio merged using ffmpeg |
| Audio | MP3 conversion at 192 kbps |
| Quality | Best, plus available 1080p, 720p, 480p, and 360p choices |
| Preview | Title, uploader, duration, and thumbnail |
| Progress | Download percentage, speed, ETA, and activity log |
| Playlists | Optional full-playlist downloads |
| Cancellation | Cancel an operation and retain partial files for retrying |
| Settings | Remembers your output folder |
| Portable executable | No separate Python, ffmpeg, or Node.js installation needed |

Available formats depend on the video and the site's access restrictions.

## Run the Windows app

1. Get the supplied **`YTDL.exe`**. When a GitHub release is available, download
   the executable from its **Assets** section.
2. Move it to a folder of your choice.
3. Double-click **`YTDL.exe`**.

An internet connection is needed to fetch media information and download files.
The executable extracts its bundled tools into a temporary folder at startup.

If you have the source code and no executable, follow the
[build instructions](#build-a-standalone-executable).

## Download a video or audio

1. Paste a complete YouTube or Facebook link using **Paste** or **Ctrl+V**.
2. Click **Fetch Info** to preview the media and load available qualities.
3. Select **Video (MP4)** or **Audio only (MP3)**.
4. For video, choose **Best** or an available resolution.
5. Choose your **Save to** folder with **Browse…**.
6. Click **Download** and follow the progress and activity log.

The default destination is your **Downloads** folder. **Best** can also be used
without fetching information first. A selected resolution is a maximum height;
the app can use a lower resolution when necessary.

Click **Cancel** to stop the current operation. An active network request or
ffmpeg operation may finish before cancellation takes effect. Closing the app
during a download requests cancellation and waits for the worker to stop.

## Playlists

**Download full playlist** is off by default. With it off, a playlist-only link
downloads the first item. With it on, **Fetch Info** previews the first accessible
item and **Download** processes the full playlist.

The selected quality applies as a maximum height to each item. Progress tracks
the current item and stream; completion is reported after media processing ends.

## Cookies

For media that requires an authenticated session, use **Choose…** beside
**Cookies (optional)** to select a Netscape-format `cookies.txt` file.

Cookies can help with content your account can access. They do not grant access
to content your account cannot view. Treat cookie files like passwords and keep
them out of commits, issue reports, and screenshots. The app does not save cookie
paths or URLs in its settings.

## Settings and downloaded files

| Item | Location or behavior |
| --- | --- |
| Default output folder | Your user's `Downloads` folder |
| Windows settings | `%APPDATA%\ytdl-gui\config.json` |
| macOS/Linux settings | `~/.config/ytdl-gui/config.json`, respecting `XDG_CONFIG_HOME` |
| Settings override | Set `YTDL_GUI_CONFIG` to a different settings-file path |
| Output filename | Video title followed by `[video ID]` and the extension |
| Partial downloads | `.part` files are retained so a repeated download can resume |

Invalid settings fall back to the default output folder. Output filenames use
Windows-safe sanitization.

## Run from source

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then open a
terminal in the project directory:

```powershell
uv sync --locked
uv run python -m ytdl_gui
```

The project pins Python 3.12 in `.python-version`; uv manages the environment and
dependencies. Source launches need **ffmpeg** for MP3 conversion and merging,
and **Deno or Node.js 22+** for YouTube JavaScript challenges. See
[yt-dlp's runtime setup guide](https://github.com/yt-dlp/yt-dlp/wiki/EJS).

On Windows, source launches can find tools on `PATH`, in the project directory,
or in `.tools/bin/`. On macOS/Linux, Tkinter availability depends on the Python
installation. The standalone executable and build script target Windows.

See [the developer guide](docs/DEVELOPMENT.md#source-setup) for tool setup.

## Build a standalone executable

On Windows, place `ffmpeg.exe` in `.tools/bin/` and install Node.js 22+ on `PATH`.
Then run:

```powershell
uv sync --locked
uv run python build_windows.py
```

The output is **`dist/YTDL.exe`**. It bundles the app, Python, ffmpeg, Node.js,
and `yt-dlp-ejs` challenge scripts. Only that file is needed on the target
computer. Bundled tools take priority over installed tools.

You can supply explicit build inputs:

```powershell
uv run python build_windows.py --ffmpeg C:\tools\ffmpeg.exe --node C:\tools\node.exe
```

See [build and verification details](docs/DEVELOPMENT.md#standalone-windows-build).

## Troubleshooting

| Problem | What to try |
| --- | --- |
| MP3 mode is missing | In a source launch, install ffmpeg or put `ffmpeg.exe` in `.tools/bin/`, then restart. The standalone build includes it. |
| A quality is unavailable | Fetch information again and choose **Best**. Available qualities depend on the video. |
| Login or cookie error | Confirm that your account can view the media and select a valid Netscape cookie file. |
| HTTP 403, 429, or site refusal | Try again later and check whether a valid authenticated session is required. |
| Timeout or connection error | Check the internet connection and retry. |
| A download stops working after a site change | Use an updated executable, or update source dependencies and rebuild. |
| Cancellation is taking time | Wait for the current network request or ffmpeg operation to finish. |

To update the downloader in a source checkout:

```powershell
uv lock --upgrade-package yt-dlp --upgrade-package yt-dlp-ejs
uv sync
```

Rebuild `YTDL.exe` to include updated dependencies in the standalone app.

## Development

See [DEVELOPMENT.md](docs/DEVELOPMENT.md) for the project structure, tests,
standalone verification, and GitHub release instructions.

When reporting a problem, include your platform, whether you used the executable
or source, the selected mode and quality, and the relevant activity-log error.

Powered by [yt-dlp](https://github.com/yt-dlp/yt-dlp),
[ffmpeg](https://ffmpeg.org/), [Pillow](https://python-pillow.org/),
and [PyInstaller](https://pyinstaller.org/).
