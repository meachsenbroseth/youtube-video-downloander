"""Small, atomic settings file. Cookie paths and URLs are never persisted."""

import json
import os
from pathlib import Path


def config_path() -> Path:
    override = os.environ.get("YTDL_GUI_CONFIG")
    if override:
        return Path(override).expanduser()
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "ytdl-gui" / "config.json"


def load_output_folder() -> str:
    try:
        data = json.loads(config_path().read_text(encoding="utf-8"))
        value = data.get("output_folder") if isinstance(data, dict) else None
        if isinstance(value, str) and value.strip():
            return str(Path(value).expanduser())
    except (OSError, ValueError):
        pass
    return str(Path.home() / "Downloads")


def save_output_folder(folder: str) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps({"output_folder": str(Path(folder).expanduser())}, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)
