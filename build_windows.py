"""Build the single-file Windows app, including its media and JS tools."""

import argparse
from pathlib import Path
import shutil
import subprocess
import sys

import PyInstaller.__main__


def main():
    if sys.platform != "win32":
        raise SystemExit("Run this build on Windows.")
    project = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ffmpeg", default=str(project / ".tools/bin/ffmpeg.exe"))
    parser.add_argument("--node", default=shutil.which("node"))
    args = parser.parse_args()
    tools = {}
    for name in ("ffmpeg", "node"):
        value = getattr(args, name)
        if not value or not Path(value).is_file():
            parser.error(f"Provide --{name} with the path to {name}.exe.")
        tools[name] = Path(value).resolve()
    node_version = subprocess.check_output([str(tools["node"]), "--version"], text=True).strip()
    if int(node_version.lstrip("v").split(".")[0]) < 22:
        parser.error("Node.js 22 or newer is required.")
    subprocess.run([str(tools["ffmpeg"]), "-version"], check=True, capture_output=True)
    PyInstaller.__main__.run([
        "--noconfirm", "--onefile", "--windowed", "--noupx", "--name", "YTDL",
        "--distpath", str(project / "dist"),
        "--workpath", str(project / "build"),
        "--specpath", str(project / "build"),
        "--paths", str(project / "src"),
        "--collect-all", "yt_dlp_ejs",
        "--copy-metadata", "yt-dlp",
        "--copy-metadata", "yt-dlp-ejs",
        "--add-binary", f"{tools['ffmpeg']}:tools",
        "--add-binary", f"{tools['node']}:tools",
        str(project / "src/ytdl_gui/__main__.py"),
    ])
    print(f"Built {project / 'dist/YTDL.exe'} (includes ffmpeg and {node_version}).")


if __name__ == "__main__":
    main()
