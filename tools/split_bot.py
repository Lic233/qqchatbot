"""一次性脚本：把 official_bot.py 拆成 qqbot/ 包 + 瘦入口。

按行号切块，块与块之间保留原来的定义顺序；新模块用 `import *` 依赖前面的层，
保证拆分后行为与单文件一致。原文件先备份到 backup/official_bot_before_split.py。

只在拆分时跑一次；之后不要再运行（行号会变）。
"""
from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "official_bot.py"
PKG = ROOT / "qqbot"
BACKUP = ROOT / "backup"

text = SRC.read_text(encoding="utf-8-sig")
lines = text.splitlines(keepends=True)


def take(start: int, end: int) -> str:
    """取 1-based 闭区间的行，去掉首尾空行。"""
    return "".join(lines[start - 1:end]).strip("\n")


def expect_line(number: int, needle: str) -> None:
    line = lines[number - 1]
    if needle not in line:
        raise SystemExit(
            f"第 {number} 行不是预期的 {needle!r}，先检查文件有没有改动：{line!r}"
        )


# 边界自检：文件被改过就先停下，不能按错位的行号乱切。
for number, needle in [
    (82, "# ---"),
    (233, "def load_rules"),
    (769, "# ---"),
    (770, "联网搜索"),
    (1046, "# ---"),
    (1047, "# API"),
    (1282, "# ---"),
    (1283, "抽卡"),
    (1682, "# ---"),
    (1683, "功能列表"),
    (2116, "# ---"),
    (2117, "业务处理"),
    (2851, "# ---"),
    (2852, "极简 WebSocket"),
    (3110, "# ---"),
    (3111, "自检"),
    (3861, "# ---"),
    (3862, "入口"),
]:
    expect_line(number, needle)

BACKUP.mkdir(exist_ok=True)
shutil.copy2(SRC, BACKUP / "official_bot_before_split.py")
print("  备份 backup/official_bot_before_split.py")

PKG.mkdir(exist_ok=True)


def write(name: str, content: str) -> None:
    path = PKG / name
    path.write_text(content.rstrip() + "\n", encoding="utf-8")
    print(f"  写入 qqbot/{name}（{len(content.splitlines())} 行）")


write("__init__.py", '"""QQ 官方机器人内部模块。"""')

# ---- config：纯常量，不依赖任何内部模块 ----
write("config.py", f'''"""配置：路径、环境变量、人设/记忆/搜索/规则参数。

这里只放常量和环境变量读取，不放逻辑；改完记得重启（环境变量在 import 时读一次）。
"""
from __future__ import annotations

import os
from pathlib import Path


{take(82, 230)}
''')

# ---- base：底层工具 + 事件解析 + 人设/记忆 ----
write("base.py", f'''"""基础层：日志、路径、事件解析、文本/HTTP/图片工具、人设与短期记忆。

只依赖 config；其他模块都从这里拿基础能力。
"""
from __future__ import annotations

from .config import *  # noqa: F401,F403

{take(29, 58)}
from pathlib import Path


{take(60, 79)}


{take(233, 767)}
''')

# ---- ai：联网搜索 + DeepSeek ----
write("ai.py", f'''"""联网搜索（DeepSeek Search）与 DeepSeek 对话（含工具调用循环）。

依赖 base/config；不碰 QQ 平台协议。
"""
from __future__ import annotations

from .base import *  # noqa: F401,F403


{take(769, 1043)}
''')

# ---- api：QQ 平台 HTTP 接口 + 发送器 ----
write("api.py", f'''"""QQ 开放平台 HTTP API、分片上传、被动回复发送器。

依赖 base/config；不包含业务逻辑。
"""
from __future__ import annotations

from .base import *  # noqa: F401,F403


{take(1046, 1279)}
''')

# ---- cards：抽卡 ----
write("cards.py", f'''"""抽卡 / 开箱 / 库存与卡池。

依赖 base/config；Handler 调这里的方法，卡池数据在 data/card/。
"""
from __future__ import annotations

from .base import *  # noqa: F401,F403


{take(1282, 1679)}
''')

# ---- features：文档、画像、名单、打卡、运势、老婆 ----
write("features.py", f'''"""功能列表、群友画像、名单、打卡、每日运势、老婆图。

依赖 base/config；都是被 Handler 调用的独立小功能。
"""
from __future__ import annotations

from .base import *  # noqa: F401,F403


{take(1682, 2113)}
''')

# ---- handler：群消息业务 ----
write("handler.py", f'''"""群消息业务处理：命令、关键词、歌词、AI 对话、复读。

只依赖下面几层；网关和入口不在这里。
"""
from __future__ import annotations

from .base import *  # noqa: F401,F403
from .cards import *  # noqa: F401,F403
from .config import *  # noqa: F401,F403
from .features import *  # noqa: F401,F403


{take(2116, 2848)}
''')

# ---- net：WebSocket / Gateway ----
write("net.py", f'''"""极简 WebSocket 客户端（标准库）与网关事件循环。

只依赖 base；Gateway 拿到 Handler 的实例调用 handle()。
"""
from __future__ import annotations

from .base import *  # noqa: F401,F403


{take(2851, 3107)}
''')

# ---- selftest：离线自检 ----
write("selftest.py", f'''"""离线自检：不联网，覆盖规则、命令、AI、搜索、复读、上传。

单独成文件，平时运行 bot 不用导入它（入口只在 --selftest 时延迟导入）。
"""
from __future__ import annotations

from .ai import *  # noqa: F401,F403
from .api import *  # noqa: F401,F403
from .base import *  # noqa: F401,F403
from .cards import *  # noqa: F401,F403
from .config import *  # noqa: F401,F403
from .features import *  # noqa: F401,F403
from .handler import *  # noqa: F401,F403


{take(3110, 3858)}
''')

# ---- 瘦入口 ----
entry = f'''{take(1, 26)}

from __future__ import annotations

import argparse
import asyncio
import os
import sys

import lyrics_line

from qqbot.ai import DeepSeek, web_search
from qqbot.api import GroupSender, QQBotAPI
from qqbot.base import KEEP_AWAKE, Paths, keep_awake, log, read_text_config
from qqbot.config import (
    DATA_DIR,
    DEEPSEEK_MODEL,
    PERSONA_FILE,
    SEARCH_ENABLED,
)
from qqbot.handler import Handler
from qqbot.net import Gateway


{take(3861, 3977)}
'''
# 自检按需导入，正常启动不加载 selftest 及其依赖。
entry = entry.replace(
    "    if args.selftest:\n        return await selftest()",
    "    if args.selftest:\n        from qqbot.selftest import selftest\n\n        return await selftest()",
)
SRC.write_text(entry.rstrip() + "\n", encoding="utf-8")
print(f"  写入 official_bot.py（{len(entry.splitlines())} 行）")

print("拆分完成。接下来跑：python official_bot.py --selftest")
