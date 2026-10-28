"""给原版渲染器用的老婆池替身：只数 data/wife 里有多少张图。"""
from __future__ import annotations

from pathlib import Path

from .config import DATA_DIR

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}


def wife_paths() -> list[Path]:
    directory: Path = DATA_DIR / "wife"
    if not directory.is_dir():
        return []
    return [
        path for path in directory.iterdir()
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    ]
