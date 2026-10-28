"""锻造排行榜：只保留锻造价值最高的**十次**历史记录。

记录什么、什么时候记：

* 每次**成功收工**（「结束锻造」/「收工」，见 ``forge.end_forge``）记一条 ——
  记的是这一局最后换成碎片的那个价值（四舍五入后的整数，跟收工文案、
  奶龙碎片对得上）。
* 砸碎（价值归零、拿 0 碎片）**不算**记录：排行榜要的是"锻造价值"，
  归零的那一局没有价值可言，塞进去只会占掉一个空位。
* 一条记录三个字段：**锻造价值、锻造人、锻造时间**（精确到分，
  ``YYYY-MM-DD HH:MM``）。另外内部存一个 ``user_id``，方便以后排查/去重，
  排行榜图上只显示名字。
* 只留前十：新记录比第十名**严格更高**才挤得进去；同分时**先到先得**
  （原本就在榜上的排在前面），这样榜单不会被同分的后来者反复顶掉。

**范围**：整个机器人一份榜（不分群）—— 记录里本来就只有"价值 / 人 / 时间"，
QQ 号和奶龙碎片也都是跨群共用的，跨群比较才合理。如果以后要改成每群一份，
把 ``group_id`` 塞进记录、在 ``record``/``leaderboard`` 里过滤即可。

**持久化**：落在 ``data\\forge_rank.json``（见 ``config.FORGE_RANK_FILE``），
写临时文件再原子替换；重启不丢。文件格式是一个数组：

    [{"value": 1234, "user_id": 123456, "name": "奶龙",
      "time": "2026-10-19 12:18"}, …]

按价值从高到低排好，最多十条；手工改坏了（不是数组 / 字段不全）就丢掉坏条目，
读不出来时退回空榜，不影响锻造本身。
"""
from __future__ import annotations

import datetime
import json
import tempfile
import threading
from pathlib import Path

from nonebot import logger

from .config import FORGE_RANK_FILE

# 榜单只留前十名。
TOP_N = 10
# 触发命令。跟「锻造」开局一样是**精确匹配**（前后空白容忍），
# 不跟"排行榜"这类泛词混在一起，免得把闲聊抢答了。
COMMAND = "锻造排行榜"
# 锻造时间精确到分（需求原话），存也存这个格式：字符串按字典序排就是时间顺序。
TIME_FORMAT = "%Y-%m-%d %H:%M"
# 第 1~3 名的后缀是 1st/2nd/3rd，其余 th（11~13 也走 th）。
_ORDINAL_SUFFIX = {1: "st", 2: "nd", 3: "rd"}

_records: list[dict] = []
_records_lock = threading.Lock()
_loaded = False


def is_rank_command(text: str) -> bool:
    """是不是「锻造排行榜」这条命令（只有这五个字，多一个字都不算）。"""
    return (text or "").strip() == COMMAND


def ordinal(number: int) -> str:
    """1 → ``1st``、2 → ``2nd``、3 → ``3rd``、4 → ``4th``、11 → ``11th``。"""
    if 10 <= number % 100 <= 20:
        suffix = "th"
    else:
        suffix = _ORDINAL_SUFFIX.get(number % 10, "th")
    return f"{number}{suffix}"


def _sort_key(record: dict) -> tuple[float, str]:
    """价值高的在前；同分按时间早的在前（时间字符串可直接比较）。"""
    return (-float(record.get("value") or 0), str(record.get("time") or ""))


def _normalize(raw: object) -> dict | None:
    """把文件里的一条记录收拾成内部格式；不像样的返回 ``None``（丢掉）。"""
    if not isinstance(raw, dict):
        return None
    try:
        value = int(round(float(raw.get("value"))))
        user_id = int(raw.get("user_id") or 0)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    name = str(raw.get("name") or "").strip()
    time_text = str(raw.get("time") or "").strip()
    return {
        "value": value,
        "user_id": user_id,
        "name": name or (f"QQ {user_id}" if user_id else "无名氏"),
        "time": time_text,
    }


def _ensure_loaded_locked() -> None:
    """第一次访问时把榜单从磁盘读进来（调用方需持锁）。"""
    global _loaded
    if _loaded:
        return
    _loaded = True
    try:
        raw = json.loads(FORGE_RANK_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return
    except (OSError, json.JSONDecodeError) as error:
        logger.warning(f"[锻造排行榜] 记录读取失败，将从空榜开始：{error}")
        return
    # 允许数组，也允许 {"records": [...]} 这种包一层的写法（手工改文件时常见）。
    if isinstance(raw, dict):
        raw = raw.get("records", [])
    if not isinstance(raw, list):
        logger.warning("[锻造排行榜] 记录文件格式不对（不是数组），将从空榜开始")
        return
    cleaned = [record for record in map(_normalize, raw) if record is not None]
    cleaned.sort(key=_sort_key)
    _records[:] = cleaned[:TOP_N]
    logger.info(f"[锻造排行榜] 已载入 {len(_records)} 条记录")


def _save_locked() -> None:
    """把榜单写回磁盘（临时文件 + 原子替换；调用方需持锁）。"""
    temporary_path: Path | None = None
    try:
        FORGE_RANK_FILE.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=FORGE_RANK_FILE.parent,
            prefix="forge_rank_", suffix=".tmp", delete=False,
        ) as file:
            temporary_path = Path(file.name)
            json.dump(_records, file, ensure_ascii=False, indent=2)
            file.write("\n")
        temporary_path.replace(FORGE_RANK_FILE)
    except OSError as error:
        logger.warning(f"[锻造排行榜] 记录保存失败：{error}")
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink(missing_ok=True)


def record(
    value: float | int,
    user_id: int | str,
    name: str = "",
    when: datetime.datetime | None = None,
) -> int | None:
    """记一次收工的价值；进了前十就返回**名次**（1 起），没进返回 ``None``。

    参数：
        value    这一局最后的价值（按四舍五入取整，跟发给玩家的碎片一致）
        user_id  锻造人的 QQ（内部留存，图上不显示）
        name     锻造人的群名片/昵称（空的话退回 ``QQ <号>``）
        when     收工时间；不给就用当前时间（测试可以钉死）
    """
    try:
        value = int(round(float(value)))
        user_id = int(user_id)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        # 0 价值（砸碎）没有上榜的意义，直接不记。
        return None
    display_name = str(name or "").strip() or f"QQ {user_id}"
    timestamp = (when or datetime.datetime.now()).strftime(TIME_FORMAT)
    entry = {
        "value": value,
        "user_id": user_id,
        "name": display_name,
        "time": timestamp,
    }
    with _records_lock:
        _ensure_loaded_locked()
        # 榜单满了、又没比第十名高（同分也算没超过）：不记。
        # 同分先到先得 —— 已经在榜上的那一条不该被后来者挤掉。
        if len(_records) >= TOP_N and value <= int(_records[-1]["value"]):
            return None
        _records.append(entry)
        # list.sort 是稳定排序：同价值、同分钟时，先记的那条仍排在前面。
        _records.sort(key=_sort_key)
        del _records[TOP_N:]
        _save_locked()
        for index, item in enumerate(_records):
            if item is entry:
                logger.info(
                    f"[锻造排行榜] user={user_id} 价值 {value} 进榜："
                    f"第 {index + 1} 名（时间 {timestamp}）"
                )
                return index + 1
        return None


def leaderboard() -> list[dict]:
    """当前榜单（价值从高到低，最多十条）的**副本**。

    拷贝是故意的：调用方拿去渲染/拼文案时，不会被另一条收工的并发写入改到一半。
    """
    with _records_lock:
        _ensure_loaded_locked()
        return [dict(item) for item in _records]


def clear() -> None:
    """清空榜单并删掉记录文件（**自测专用**；正常玩法里没有清榜操作）。"""
    global _loaded
    with _records_lock:
        _records.clear()
        _loaded = True
        try:
            FORGE_RANK_FILE.unlink(missing_ok=True)
        except OSError as error:
            logger.warning(f"[锻造排行榜] 清空记录文件失败：{error}")
