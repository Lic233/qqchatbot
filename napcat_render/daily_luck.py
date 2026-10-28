"""每日运势：`data\\daily_luck\\daily_luck.json` 里的图，一天一张。

数据完全是**你自己维护**的，跟 `persona.txt` 一个套路：代码只读，不写。

    data\\daily_luck\\daily_luck.json     {"大吉": "大吉.png", "小吉": "小吉.png", …}
    data\\daily_luck\\*.png|jpg|gif       对应的运势图

抽签规则：**按 (群, 人, 日期) 定死** —— 同一个人同一天抽到的永远是同一张，
不会靠反复签到重抽（拿运势当抽奖就没意思了）。用的是 `random.Random(种子)`，
种子由群号、QQ、日期拼出来，所以重启之后结果也不会变。
"""
from __future__ import annotations

import datetime
import json
import random
from pathlib import Path

from nonebot import logger

from .config import DAILY_LUCK_DIR, DAILY_LUCK_FILE

# 运势等级 → 图文件名。读 `daily_luck.json`；文件不在/读不动时保持空表，
# 签到图那边就会把运势那一栏整个跳过（而不是画一个空框）。
luck_records: dict[str, str] = {}

# 各档运势配的一句话。**不在 json 里的等级不会因为没有这句话而出问题** ——
# 找不到就用「今天的运势是 X。」兜底，图照发。
LUCK_FLAVOR = {
    "大吉": "想什么都成，别浪费了。",
    "中吉": "稳稳当当的一天。",
    "小吉": "小的也算吉，别嫌少。",
    "吉": "平平常常，也还行吧。",
    "末吉": "末等的吉也是吉，拿着。",
    "凶": "……唔，今天就别乱来了。",
    "大凶": "别出门了，真的。",
}

# 签到图底部那两行"宜 / 忌"。同样是按等级给的，没登记的等级走 DEFAULT_ADVICE。
DEFAULT_ADVICE = ("抽卡", "开箱")
LUCK_ADVICE = {
    "大吉": ("抽卡、开箱、表白", "跟小鲸鱼顶嘴"),
    "中吉": ("抽卡、攒碎片", "熬夜"),
    "小吉": ("抽卡", "乱花碎片"),
    "吉": ("签到、聊天", "想太多"),
    "末吉": ("先攒着", "冲动开箱"),
    "凶": ("安静待着", "抽卡"),
    "大凶": ("缩在被窝里", "出门、抽卡、说话"),
}


def luck_advice(name: str) -> tuple[str, str]:
    """返回这一档的 ``(宜, 忌)``。"""
    return LUCK_ADVICE.get(name, DEFAULT_ADVICE)



def load_luck_records() -> None:
    global luck_records
    if not DAILY_LUCK_FILE.exists():
        logger.info(f"[运势] 没找到 {DAILY_LUCK_FILE}，签到图里不显示运势栏")
        luck_records = {}
        return
    try:
        records = json.loads(DAILY_LUCK_FILE.read_text(encoding="utf-8"))
        if not isinstance(records, dict):
            raise ValueError("记录必须是对象")
        luck_records = {
            str(name): str(filename) for name, filename in records.items()
            if isinstance(name, str) and isinstance(filename, str) and filename
        }
        logger.info(f"[运势] 共 {len(luck_records)} 档：{'、'.join(luck_records)}")
    except (OSError, json.JSONDecodeError, ValueError) as error:
        logger.warning(f"[运势] 记录读取失败，将不显示运势栏：{error}")
        luck_records = {}


def luck_image_path(name: str) -> Path | None:
    """按等级取图片路径；没登记、或文件不在都返回 ``None``。"""
    filename = luck_records.get(name)
    if not filename:
        return None
    path = DAILY_LUCK_DIR / filename
    return path if path.is_file() else None


def luck_options() -> list[str]:
    """能用的运势等级：登记过、且文件真的在的那些。"""
    return [name for name in luck_records if luck_image_path(name) is not None]


def luck_seed(group_id: int, user_id: int, today: datetime.date) -> str:
    """今天这一次抽签的种子：同群同人同一天 → 同一档运势。"""
    return f"luck:{group_id}:{user_id}:{today.isoformat()}"


def daily_luck(
    group_id: int, user_id: int, today: datetime.date | None = None
) -> str | None:
    """抽今天的运势，返回等级名；没配好运势图时返回 ``None``。

    同一天重复调用（比如当天第二次签到、或者重启之后）拿到的是同一个结果 ——
    种子只跟群、人和日期有关。想改成"每次签到都重抽"的话，把 ``random.Random``
    那句换成 ``random.choice(options)`` 就行。
    """
    today = today or datetime.date.today()
    options = luck_options()
    if not options:
        return None
    return random.Random(luck_seed(group_id, user_id, today)).choice(options)


def luck_flavor(name: str) -> str:
    """给某一档运势配的那句话；没登记就用一句中性的兜底。"""
    return LUCK_FLAVOR.get(name, f"今天的运势是 {name}。")


load_luck_records()
