"""题库自检：改完 config/mc_guess_*.json 跑一下这个。

    python tools/mc_guess_check.py

只读：把两套题库读进来、跑一遍 check_data，打印条数和所有问题；
有问题时退出码 1（方便挂到提交前检查里）。改完 JSON 想知道有没有写错，
不用启动机器人，也不用等整套 --selftest。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from qqbot.config import config_file  # noqa: E402
from qqbot.mc_guess_data import (  # noqa: E402
    BANK_FILE,
    ITEMS,
    check_data,
)
from qqbot.mc_guess_data_hard import (  # noqa: E402
    BANK_FILE as HARD_BANK_FILE,
    EXTRA_ITEMS,
    HARD_ITEMS,
    check_hard_data,
)


def main() -> int:
    problems: list[str] = []
    for label, filename, items, check in (
        ("简单", BANK_FILE, ITEMS, check_data),
        ("困难", HARD_BANK_FILE, HARD_ITEMS, check_hard_data),
    ):
        path = config_file(filename)
        state = "存在" if path.exists() else "缺失"
        total_weight = sum(getattr(item, "weight", 1) for item in items)
        print(f"[{label}] {path}（{state}）· {len(items)} 条"
              f" · 权重合计 {total_weight:g}")
        problems += [f"[{label}] {line}" for line in check()]

    print(f"困难模式新增条目：{len(EXTRA_ITEMS)} 条")
    if not problems:
        print("题库没问题。")
        return 0
    print(f"发现 {len(problems)} 个问题：")
    for line in problems:
        print("  -", line)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
