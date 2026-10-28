"""给原版渲染器用的配置替身：只提供它 import 的那几个路径。"""
from __future__ import annotations

import os
from pathlib import Path

DATA_DIR = Path(os.getenv("QQCHATBOT_DATA_DIR", "").strip() or (Path(__file__).resolve().parent.parent / "data"))
CHECKIN_CARD_DIR = DATA_DIR / "checkin"
DAILY_LUCK_DIR = DATA_DIR / "daily_luck"
DAILY_LUCK_FILE = DAILY_LUCK_DIR / "daily_luck.json"
FORGE_RANK_FILE = DATA_DIR / "forge_rank.json"
