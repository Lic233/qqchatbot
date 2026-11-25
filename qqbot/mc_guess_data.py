"""「弗一把 · Minecraft 物品」简单模式题库（Java 1.20.2 截止）。

**题目全部在 ``config/mc_guess_easy.json``，这个文件只管读和校验** ——
改题、加题、改别名都不用碰 Python，存完重启（或跑自检）就生效。

JSON 结构：

    {
      "version_order": ["远古", "1.0", ...],     # 加入版本档位，顺序即新旧
      "types":  [...], "tags": [...],           # 类型 / 标签词表（写错会被自检抓出来）
      "worlds": [...], "colors": [...],         # 生成世界 / 16 种染料色
      "type_families": {"工具": "装备", ...},   # 哪些类型算「沾边」
      "items": [
        {"name": "泥土", "version": "远古", "type": "方块",
         "tags": ["地形", "建筑"], "world": "主世界",
         "note": "徒手就能挖，到处都是，还能种地。",
         "aliases": ["dirt"], "colored": false, "weight": 1}
      ]
    }

几条硬规则（``check_data`` 会逐条查）：

* ``name`` 1~12 字、全库不重复；``version`` 必须在 ``version_order`` 里；
* ``type`` / ``world`` / 每个 ``tags`` 都必须落在词表里，``tags`` 1~4 个且不重复；
* ``aliases`` 是别名与英文 id，归一化后不能和别的条目撞车；
* ``colored: true`` 表示这条有 16 种颜色（羊毛 / 陶瓦……），16 色别名由
  ``colors`` 自动补齐，不用一条条写 —— 猜「羊毛」和猜「红色羊毛」都算它；
* ``weight`` 是抽题权重，默认 1，必须是正数：写 3 就是权重 1 的三倍概率
  （概率 = 本题权重 ÷ 全库权重和），全库都写 1 就是均匀抽。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from .config import config_file

BANK_FILE = "mc_guess_easy.json"

# 一条题目允许出现的字段：多写一个（比如把 tags 拼成 tag）会当场报错，
# 免得改完静悄悄地不生效。
ITEM_KEYS = {"name", "version", "type", "tags", "world", "note",
             "aliases", "colored", "weight"}


@dataclass(frozen=True)
class Item:
    name: str
    version: str
    type: str
    tags: tuple[str, ...]
    world: str
    note: str = ""
    aliases: tuple[str, ...] = field(default_factory=tuple)
    # 这个物品有 16 种颜色（羊毛 / 陶瓦……），别名里已经带上「红色羊毛」这类写法
    colored: bool = False
    # 抽题权重：越大越容易被抽到（权重 3 就是权重 1 的三倍概率），当前全库都是 1
    weight: float = 1.0

    @property
    def chars(self) -> int:
        return len(self.name)


def normalize_name(text: str) -> str:
    """把玩家输入收拾成查表用的键：去空白、去标点、英文小写。"""
    if not text:
        return ""
    kept = [ch for ch in str(text).strip().lower()
            if not ch.isspace() and ch not in "，。、！？,.!?~～·-—_"]
    return "".join(kept)


# --------------------------------------------------------------------------
# 读 JSON
# --------------------------------------------------------------------------


def read_bank(path) -> dict:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as error:
        raise RuntimeError(f"找不到题库 {path}：{error}") from error
    try:
        payload = json.loads(text)
    except ValueError as error:
        raise RuntimeError(f"题库 {path} 不是合法 JSON：{error}") from error
    if not isinstance(payload, dict):
        raise RuntimeError(f"题库 {path} 的最外层必须是对象")
    return payload


def _text_list(payload: dict, key: str, path) -> tuple[str, ...]:
    value = payload.get(key)
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise RuntimeError(f"题库 {path} 的 {key} 必须是字符串数组")
    return tuple(value)


def _build_item(record, index: int, path, colors: tuple[str, ...]) -> Item:
    where = f"{path} 第 {index + 1} 条题目"
    if not isinstance(record, dict):
        raise RuntimeError(f"{where} 必须是对象")
    extra = set(record) - ITEM_KEYS
    if extra:
        raise RuntimeError(f"{where} 有认不出的字段：{'、'.join(sorted(extra))}")
    name = record.get("name")
    if not isinstance(name, str) or not name.strip():
        raise RuntimeError(f"{where} 缺少 name")
    for key in ("version", "type", "world"):
        if not isinstance(record.get(key), str) or not record[key].strip():
            raise RuntimeError(f"{where}（{name}）缺少 {key}")
    tags = record.get("tags")
    if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
        raise RuntimeError(f"{where}（{name}）的 tags 必须是字符串数组")
    aliases = record.get("aliases", [])
    if not isinstance(aliases, list) or not all(isinstance(a, str)
                                                for a in aliases):
        raise RuntimeError(f"{where}（{name}）的 aliases 必须是字符串数组")
    note = record.get("note", "")
    if not isinstance(note, str):
        raise RuntimeError(f"{where}（{name}）的 note 必须是字符串")
    colored = bool(record.get("colored", False))
    if colored:
        aliases = aliases + [f"{color}{name}" for color in colors]
    weight = record.get("weight", 1)
    if isinstance(weight, bool) or not isinstance(weight, (int, float)) \
            or weight <= 0:
        raise RuntimeError(f"{where}（{name}）的 weight 必须是大于 0 的数字")
    return Item(name=name, version=record["version"], type=record["type"],
                tags=tuple(tags), world=record["world"], note=note,
                aliases=tuple(aliases), colored=colored, weight=float(weight))


def load_items(path, colors: tuple[str, ...],
               payload: dict | None = None) -> tuple[Item, ...]:
    """把一个题库 JSON 里的 items 读成 Item 元组（困难模式也复用它）。"""
    payload = read_bank(path) if payload is None else payload
    records = payload.get("items")
    if not isinstance(records, list):
        raise RuntimeError(f"题库 {path} 的 items 必须是数组")
    return tuple(_build_item(record, index, path, colors)
                 for index, record in enumerate(records))


_BANK_PATH = config_file(BANK_FILE)
_PAYLOAD = read_bank(_BANK_PATH)

VERSION_ORDER = _text_list(_PAYLOAD, "version_order", _BANK_PATH)
TYPES = _text_list(_PAYLOAD, "types", _BANK_PATH)
TAGS = _text_list(_PAYLOAD, "tags", _BANK_PATH)
WORLDS = _text_list(_PAYLOAD, "worlds", _BANK_PATH)
COLORS = _text_list(_PAYLOAD, "colors", _BANK_PATH)
TYPE_FAMILIES = dict(_PAYLOAD.get("type_families") or {})

ITEMS = load_items(_BANK_PATH, COLORS, _PAYLOAD)

# 名字 / 别名 → Item（键统一过 normalize_name）
BY_NAME: dict[str, Item] = {}
for _entry in ITEMS:
    for _key in (_entry.name, *_entry.aliases):
        _normalized = normalize_name(_key)
        if _normalized:
            BY_NAME[_normalized] = _entry


def find_item(text: str) -> Item | None:
    """按名字或别名找物品；找不到返回 None。"""
    return BY_NAME.get(normalize_name(text))


def version_newer(left: str, right: str, order=None) -> int:
    """比较两个版本档：左新返回 1，一样返回 0，左旧返回 -1。

    ``order`` 不传就用本表的档位（简单模式）；困难模式会传一张更长的表进来，
    只往后追加，老版本之间的相对顺序不变。
    """
    table = {value: index for index, value in enumerate(order or VERSION_ORDER)}
    a, b = table.get(left, -1), table.get(right, -1)
    return (a > b) - (a < b)


def check_data(items=None, order=None) -> list[str]:
    """题库自检：返回所有不合规的说明（空列表 = 全过）。

    ``items`` / ``order`` 不传就查本表的题库，困难模式传自己那套进来。
    """
    items = ITEMS if items is None else items
    order = VERSION_ORDER if order is None else order
    problems: list[str] = []
    seen: set[str] = set()
    alias_owner: dict[str, str] = {}
    for item in items:
        where = f"「{item.name}」"
        if item.version not in order:
            problems.append(f"{where} 加入版本不在档位表里：{item.version}")
        if item.type not in TYPES:
            problems.append(f"{where} 类型不认识：{item.type}")
        if item.world not in WORLDS:
            problems.append(f"{where} 生成世界不认识：{item.world}")
        if not 1 <= len(item.tags) <= 4:
            problems.append(f"{where} 标签要 1~4 个，现在是 {len(item.tags)} 个")
        if len(set(item.tags)) != len(item.tags):
            problems.append(f"{where} 标签重复")
        for tag in item.tags:
            if tag not in TAGS:
                problems.append(f"{where} 标签不认识：{tag}")
        if not 1 <= len(item.name) <= 12:
            problems.append(f"{where} 名字长度不合适（1~12 字）")
        if item.name in seen:
            problems.append(f"{where} 名字重复")
        seen.add(item.name)
        if not item.note:
            problems.append(f"{where} 没写介绍")
        if item.colored:
            missing = [c for c in COLORS if f"{c}{item.name}" not in item.aliases]
            if missing:
                problems.append(f"{where} 少了几种颜色的别名：{missing[:3]}")
        if isinstance(item.weight, bool) or not isinstance(item.weight, (int, float)) \
                or item.weight <= 0:
            problems.append(f"{where} 权值必须是大于 0 的数字：{item.weight!r}")
        for alias in (item.name, *item.aliases):
            key = normalize_name(alias)
            if not key:
                problems.append(f"{where} 有个空别名")
                continue
            owner = alias_owner.get(key)
            if owner and owner != item.name:
                problems.append(f"{where} 的别名「{alias}」和「{owner}」撞了")
            alias_owner[key] = item.name
    return problems
