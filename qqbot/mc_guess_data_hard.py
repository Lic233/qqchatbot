"""「弗一把 · Minecraft 物品」困难模式题库：1.20.2 之后、26.3 及以前。

简单模式用的是 ``config/mc_guess_easy.json``（Java 1.20.2 截止），这里**不动它**，
只把 1.20.5 ~ 26.3 的新内容放在 ``config/mc_guess_hard.json`` 里，两边合并使用。
26.1 小鬼当家只多了一件金蒲公英；26.2 混沌立方加了硫黄洞穴、硫方怪；
26.3 奔赴荒野加了杨树、层孔菇、红灌木、麦秆床和坐垫。

JSON 结构与 ``mc_guess_easy.json`` 一样（items 数组），另外多两块：

    {
      "late_versions": ["1.20.5", ..., "1.21.11", "26.1", "26.2", "26.3"],
      "version_names": {"1.21": "棘巧试炼", "26.1": "小鬼当家", ...},
      "items": [ ... ],
      "legacy_aliases": {"猪": ["温带猪", "寒带猪", "热带猪"], ...}
    }

``legacy_aliases`` 用来把新版本里多出来的写法挂到**老条目**上（不在新题库里
另开一条），比如「温带猪」→ 老题库的「猪」、「斑驳的铜块」→「铜块」。

**同一种东西只收一条**（和「挽具」16 色算一条是一个思路）：七种材质的矛合成
「矛」，寒带 / 热带 / 温带的猪牛羊鸡并回老题库的「猪 / 牛 / 鸡」，蓝色 / 棕色
鸡蛋并回「蛋」；铜方块的氧化 / 涂蜡变体全部写成别名 —— 不然题库里会有好几条
几乎一样的答案互相干扰。
"""
from __future__ import annotations

from .config import config_file
from .mc_guess_data import (
    COLORS,
    ITEMS,
    VERSION_NAMES,
    VERSION_ORDER,
    Item,
    check_data,
    load_items,
    normalize_name,
    read_bank,
    version_label as _version_label,
    version_newer as _version_newer,
)

BANK_FILE = "mc_guess_hard.json"

_BANK_PATH = config_file(BANK_FILE)
_PAYLOAD = read_bank(_BANK_PATH)

_LATE = _PAYLOAD.get("late_versions")
if not isinstance(_LATE, list) or not all(isinstance(v, str) for v in _LATE):
    raise RuntimeError(f"题库 {_BANK_PATH} 的 late_versions 必须是字符串数组")

# 1.20.2 之后的正式版档位（到 26.3 为止的所有内容更新）
LATE_VERSIONS = tuple(_LATE)
VERSION_ORDER_HARD = VERSION_ORDER + LATE_VERSIONS

_NAMES_RAW = _PAYLOAD.get("version_names") or {}
if not isinstance(_NAMES_RAW, dict) or not all(
        isinstance(k, str) and isinstance(v, str) and v.strip()
        for k, v in _NAMES_RAW.items()):
    raise RuntimeError(f"题库 {_BANK_PATH} 的 version_names 必须是「版本号: 名字」对象")
_unknown_names = [k for k in _NAMES_RAW if k not in VERSION_ORDER_HARD]
if _unknown_names:
    raise RuntimeError(
        f"题库 {_BANK_PATH} 的 version_names 里有档位表没有的版本："
        f"{'、'.join(_unknown_names)}")
_conflict = [k for k, v in _NAMES_RAW.items()
             if k in VERSION_NAMES and VERSION_NAMES[k] != v]
if _conflict:
    raise RuntimeError(
        f"题库 {_BANK_PATH} 的 version_names 和简单题库打架：{'、'.join(_conflict)}")

# 两套题库的名字合并：简单模式的 1.x + 困难模式的 26.x
VERSION_NAMES_HARD = {**VERSION_NAMES, **_NAMES_RAW}

EXTRA_ITEMS = load_items(_BANK_PATH, COLORS, _PAYLOAD)
HARD_ITEMS = ITEMS + EXTRA_ITEMS

# 老物品在新版本里多出来的写法：不新增条目，只把别名挂到老条目上
LEGACY_ALIASES: dict[str, tuple[str, ...]] = {}
_LEGACY_RAW = _PAYLOAD.get("legacy_aliases") or {}
if not isinstance(_LEGACY_RAW, dict):
    raise RuntimeError(f"题库 {_BANK_PATH} 的 legacy_aliases 必须是对象")
for _owner, _aliases in _LEGACY_RAW.items():
    if not isinstance(_aliases, list) or not all(isinstance(a, str)
                                                 for a in _aliases):
        raise RuntimeError(
            f"题库 {_BANK_PATH} 里「{_owner}」的 legacy_aliases 必须是字符串数组")
    LEGACY_ALIASES[str(_owner)] = tuple(_aliases)


def version_newer(left: str, right: str) -> int:
    """困难模式的两版比对：用扩展后的档位表（老版本顺序不变）。"""
    return _version_newer(left, right, VERSION_ORDER_HARD)


def version_label(version: str) -> str:
    """带更新主题名的版本写法（两套题库的名字合并表）。"""
    return _version_label(version, VERSION_NAMES_HARD)


HARD_BY_NAME: dict[str, Item] = {}
for _entry in HARD_ITEMS:
    for _key in (_entry.name, *_entry.aliases):
        _normalized = normalize_name(_key)
        if _normalized:
            HARD_BY_NAME[_normalized] = _entry

_ITEMS_BY_NAME = {item.name: item for item in ITEMS}
for _owner, _aliases in LEGACY_ALIASES.items():
    _target = _ITEMS_BY_NAME.get(_owner)
    if _target is None:
        raise RuntimeError(
            f"题库 {_BANK_PATH} 的 legacy_aliases 指向不存在的条目：{_owner}")
    for _alias in _aliases:
        HARD_BY_NAME[normalize_name(_alias)] = _target


def find_hard_item(text: str) -> Item | None:
    """困难模式查表：1.20.2 的老题库 + 之后的新内容。"""
    return HARD_BY_NAME.get(normalize_name(text))


def check_hard_data() -> list[str]:
    """困难题库自检：老题库原样校验一遍，新条目按扩展档位再校验一遍。

    ``check_data`` 会把名字 / 别名撞车、版本档位、类型标签一起查掉，
    所以这里直接复用，不另写一套。
    """
    return check_data(HARD_ITEMS, VERSION_ORDER_HARD)


__all__ = [
    "EXTRA_ITEMS", "HARD_BY_NAME", "HARD_ITEMS", "LATE_VERSIONS",
    "LEGACY_ALIASES", "VERSION_ORDER_HARD", "check_hard_data",
    "find_hard_item", "version_newer",
]
