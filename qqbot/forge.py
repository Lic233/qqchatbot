"""锻造系统：砸剑、涨价值、掉完成度、附魔书、按收益换奶龙碎片。

规则照 ``data/锻造系统.txt``：

* 开局：``锻造 石剑`` / ``锻造 铁剑`` / ``锻造 钻石剑``，入场费与初始价值
  分别是 50/250/500，完成度一律从 100 起。碎片不够时明确拒绝，**只有石剑**
  付不起也照样开局（不扣碎片）。
* 每回合 ``用力砸``：价值增加（石剑 ×1.2~1.4，铁剑 ×1.3~1.5，钻石剑 ×1.4~1.6）、
  不变、或**锻造失败**。三档概率逐回合查表，第 5 回合后沿用第 5 行。
  写成 ``用力砸5`` 就是一次连砸 5 回合，结果按回合合并成一条消息（最多 10 下），
  中途**锻造失败就停下**，后面的回合不再自动砸。
* 失败**不再降低价值**，改成掉随机 30~50 完成度（``COMPLETION_LOSS``）；
  完成度掉到 0 或以下时剑彻底崩了，局当场结束、拿 0 碎片。
* 锻造成功（「增加」）时完成度回复 3 点（``COMPLETION_RECOVER``），上限仍是 100。
* 触发「增加」时另判一次幸运暴击（3%/8%/12%，倍率 ×2.0~2.5）。
* 砸满 3 回合后 ``结束锻造``（别名 ``收工``）按
  ``完成度/100 × 5000 × ln(1 + 价值/5000)`` 发碎片（见 ``reward_for``）：
  完成度是等比折扣，价值走对数曲线；价值越小越接近原值，接近 5000 之后压得越狠。
* 附魔书（开箱 20% 开出，可累积）：一局最多用 7 个次数，效果见 ``BOOK_EFFECTS``；
  「升格」把剑换成下界合金剑并吃 2 个次数。
* 重构：``附魔 重构`` 给下一锤 2 次重掷机会，且这一锤只要「增加」就必定暴击；
  ``重构`` 命令重掷；认下就作废剩余次数。
* 每次成功收工记一条锻造排行榜（见 forge_rank.py）。
* **无头骑士剑**（限时，见 ``headless_available``）：入场费 1000、初始价值 1000、
  完成度从 50 起；概率恒定 25/45/30，倍率 1.3~1.5、暴击 15%；
  不能用附魔书，失败只掉 20~40 完成度，自带「经验修补」（增加/不变都 +5 完成度），
  收益封顶 ``HEADLESS_REWARD_CAP``；开局随机抽一个诅咒（见 ``CURSE_EFFECTS``）。

局内进度只放内存（重启就散），排行榜才落盘。
"""
from __future__ import annotations

import math
import random
import re
from dataclasses import dataclass
from datetime import date

from .base import log
from .cards import CARD_BOX_BOOK_PROBABILITY, ENCHANT_BOOKS, Cards
from .forge_rank import ForgeRank, TOP_N, ordinal

# 砸几次才准「结束锻造」。
FORGE_MIN_TURNS = 3
# 一条「用力砸N」最多连砸多少下：结果合并成一条消息，数字太大会把回复撑爆。
MAX_STRIKE_BATCH = 10

# 完成度：开局 100，锻造失败掉一段，掉到 0 或以下剑就彻底废了。
INITIAL_COMPLETION = 100.0
COMPLETION_LOSS: tuple[int, int] = (30, 50)
# 锻造成功（「增加」）时回复的完成度，上限仍是 100。
COMPLETION_RECOVER = 3.0
# 收工收益曲线的拐点：价值远小于它就基本按原值发，远大于它就开始对数压缩。
REWARD_SCALE = 5000.0

OUTCOME_FAIL = "fail"
OUTCOME_INCREASE = "increase"
OUTCOME_UNCHANGED = "unchanged"

# ---- 无头骑士剑（限时活动） ----
# 总开关：False 就是直接下架。
HEADLESS_ENABLED = True
# 起止日期，形如 "2026-10-27"；留空表示这一头不限制。
HEADLESS_START = ""
HEADLESS_END = ""
# 无头骑士剑的收工收益上限，超过只发这么多。
HEADLESS_REWARD_CAP = 50000

COMMAND_FORGING = "锻造"
COMMAND_STRIKE = "用力砸"
COMMAND_FINISH = "结束锻造"
COMMAND_ENCHANT = "附魔"
COMMAND_REFORGE = "重构"
COMMAND_FINISH_ALIASES = (COMMAND_FINISH, "收工")
COMMANDS = (
    COMMAND_FORGING, COMMAND_STRIKE, *COMMAND_FINISH_ALIASES,
    COMMAND_ENCHANT, COMMAND_REFORGE,
)


def headless_available(today: date | None = None) -> bool:
    """无头骑士剑现在能不能锻造：总开关 + 起止日期（两端都含当天）。

    日期写成 ``YYYY-MM-DD``；留空就是这一头不限制。日期写错（比如手抖打歪了）
    当没写，不会因为配置笔误把剑锁死。
    """
    if not HEADLESS_ENABLED:
        return False
    today = today or date.today()
    for raw, is_start in ((HEADLESS_START, True), (HEADLESS_END, False)):
        raw = (raw or "").strip()
        if not raw:
            continue
        try:
            day = date.fromisoformat(raw)
        except ValueError:
            continue
        if is_start and today < day:
            return False
        if not is_start and today > day:
            return False
    return True


def is_finish_command(text: str) -> bool:
    """是不是「结束锻造」/「收工」。只在真有局时才算命令，由 Handler 判断。"""
    return (text or "").strip() in COMMAND_FINISH_ALIASES


def is_reforge_command(text: str) -> bool:
    """是不是「重构」（精确两个字）。没局时当普通聊天放过。"""
    return (text or "").strip() == COMMAND_REFORGE


_FULLWIDTH_DIGITS = str.maketrans("０１２３４５６７８９", "0123456789")
_STRIKE_COUNT_RE = re.compile(rf"^{COMMAND_STRIKE}\s*(\d*)$")


def parse_strike(text: str) -> int | None:
    """把「用力砸」/「用力砸5」/「用力砸 5」解析成连砸次数。

    不写数字就是 1 下（``用力砸 1`` 和 ``用力砸`` 等价）；全角数字也认。
    不是这个形状（比如「用力砸abc」）返回 None，交给上层当普通消息。
    """
    normalized = (text or "").replace("\u3000", " ").strip()
    normalized = normalized.translate(_FULLWIDTH_DIGITS)
    match = _STRIKE_COUNT_RE.match(normalized)
    if match is None:
        return None
    raw = match.group(1)
    if not raw:
        return 1
    return int(raw)


# ---- 台词（小鲸鱼腔，不用“本小姐”） ----
FLAVORS: tuple[str, ...] = (
    "哼，才不是特意帮你砸的。抡起锤子就是一下——",
    "看好了，这一锤可不便宜——",
    "啧，烧得这么红，是想烫到我吗——",
    "别催别催，这就给你来一下狠的——",
    "哼，砸坏了可别哭鼻子——",
    "我可是很忙的，就砸一下哦——",
    "啊——烫！……咳，什么都没发生，继续砸——",
    "手滑了一下。怎么了，你有意见？——",
)
CRIT_FLAVORS: tuple[str, ...] = (
    "诶……？剑身怎么自己亮起来了——",
    "咦？这一锤的手感不太对——",
    "哈？我可什么都没做哦——",
    "啧，运气这种东西，羡慕不来的——",
)
BOOK_FLAVORS: tuple[str, ...] = (
    "哼，贴书这种细活也来找我——",
    "啧，就这点家当，也舍得往剑上糊？——",
    "拿来吧。附魔可是技术活，别眨眼——",
    "唔，这本……行吧，给你贴上——",
)


def pick_flavor() -> str:
    return random.choice(FLAVORS)


def pick_crit_flavor() -> str:
    return random.choice(CRIT_FLAVORS)


def pick_book_flavor() -> str:
    return random.choice(BOOK_FLAVORS)


@dataclass(frozen=True)
class Sword:
    """一把剑的静态属性。"""

    key: str
    name: str
    cost: int
    initial: int
    factor: tuple[float, float]
    crit_chance: float = 0.0
    # 碎片不够入场费时要不要照样开局（免费、不扣碎片）。只有石剑是 True。
    free_if_poor: bool = False
    # 能不能直接用「锻造 <剑名>」开局。下界合金剑只能靠「升格」换，所以是 False。
    buyable: bool = True
    # 开局完成度；无头骑士剑从 50 起。
    initial_completion: float = INITIAL_COMPLETION
    # 失败掉的完成度区间；None 表示用全局 COMPLETION_LOSS（30~50）。
    loss: tuple[int, int] | None = None
    # 剑身自带「经验修补」：增加/不变都回完成度（无头骑士剑自带，不耗书）。
    innate_mending: bool = False
    # 这把剑不接受附魔书（无头骑士剑是 True）。
    no_books: bool = False
    # 收工收益上限；None 表示不封顶。
    reward_cap: float | None = None
    # 开局随机抽一个诅咒（无头骑士剑是 True）。
    cursed: bool = False


# (失败, 增加, 不变)，按回合 1..5；第 6 回合起沿用第 5 行。
_TABLES: dict[str, dict[int, tuple[float, float, float]]] = {
    "stone": {
        1: (0.10, 0.6000, 0.3000),
        2: (0.13, 0.6100, 0.2600),
        3: (0.16, 0.5200, 0.3200),
        4: (0.19, 0.5800, 0.2300),
        5: (0.22, 0.7500, 0.0300),
    },
    "iron": {
        1: (0.10, 0.4500, 0.4500),
        2: (0.13, 0.5600, 0.3100),
        3: (0.16, 0.4700, 0.3700),
        4: (0.19, 0.7100, 0.1000),
        5: (0.22, 0.5700, 0.2100),
    },
    "diamond": {
        1: (0.20, 0.5200, 0.2800),
        2: (0.22, 0.4800, 0.3000),
        3: (0.24, 0.4600, 0.3000),
        4: (0.26, 0.5400, 0.2000),
        5: (0.28, 0.5100, 0.2100),
    },
    # 下界合金剑：只能靠「升格」换，概率恒定。
    "netherite": {
        1: (0.20, 0.5000, 0.3000),
        2: (0.20, 0.5000, 0.3000),
        3: (0.20, 0.5000, 0.3000),
        4: (0.20, 0.5000, 0.3000),
        5: (0.20, 0.5000, 0.3000),
    },
    # 无头骑士剑：限时开放，概率恒定 25/45/30。
    "headless": {
        1: (0.25, 0.4500, 0.3000),
        2: (0.25, 0.4500, 0.3000),
        3: (0.25, 0.4500, 0.3000),
        4: (0.25, 0.4500, 0.3000),
        5: (0.25, 0.4500, 0.3000),
    },
}

_INCREASE_FACTOR: dict[str, tuple[float, float]] = {
    "stone": (1.2, 1.4),
    "iron": (1.3, 1.5),
    "diamond": (1.4, 1.6),
    "netherite": (1.6, 1.8),
    "headless": (1.3, 1.5),
}
_CRIT_CHANCE: dict[str, float] = {
    "stone": 0.03,
    "iron": 0.08,
    "diamond": 0.12,
    "netherite": 0.20,
    "headless": 0.15,
}
CRIT_FACTOR: tuple[float, float] = (2.0, 2.5)

# ---- 诅咒（无头骑士剑开局随机抽一个，一整局都跟着） ----
CURSE_BRITTLE = "易碎"
CURSE_BACKLASH = "反噬"
CURSE_IMMORTAL = "永生"
CURSE_UNBALANCED = "失衡"
CURSE_POISON = "鸩毒"
CURSE_GLUTTONY = "贪饕"
CURSE_MUTATION = "畸变"
CURSES: tuple[str, ...] = (
    CURSE_BRITTLE, CURSE_BACKLASH, CURSE_IMMORTAL, CURSE_UNBALANCED,
    CURSE_POISON, CURSE_GLUTTONY, CURSE_MUTATION,
)
CURSE_EFFECTS: dict[str, str] = {
    CURSE_BRITTLE: "本场完成度上限 70，收工时最终收益 ×1.6",
    CURSE_BACKLASH: "本场暴击率翻四倍（15%→60%），但暴击时完成度 -5",
    CURSE_IMMORTAL: "本场增加/不变时完成度 +15，完成度到 100% 时强制收工",
    CURSE_UNBALANCED: "本场失败不降完成度，但失败三次后强制失败",
    CURSE_POISON: "本场完成度从 100 起；成败都不影响完成度，但每回合固定 -4",
    CURSE_GLUTTONY: "本场增加价值固定 ×1.1，暴击则固定 ×10",
    CURSE_MUTATION: "本场失败时价值 ×2，但掉的完成度变成 30~50",
}
# 鸩毒：每回合固定掉的完成度（开局完成度直接拉满 100）。
POISON_TURN_LOSS = 4.0
# 贪饕：增加价值的固定倍率与暴击的固定倍率。
GLUTTONY_FACTOR = 1.1
GLUTTONY_CRIT_FACTOR = 10.0
# 畸变：失败时的价值倍率与完成度损失区间。
MUTATION_VALUE_FACTOR = 2.0
MUTATION_LOSS = (30, 50)
# 易碎：完成度上限与最终收益倍率（乘在收益上，不乘价值）。
BRITTLE_COMPLETION_CAP = 70.0
BRITTLE_REWARD_FACTOR = 1.6
# 反噬：暴击率翻四倍，暴击时掉的完成度。
BACKLASH_CRIT_MULTIPLIER = 4.0
BACKLASH_LOSS = 5.0
# 永生：「增加/不变」时回的完成度（取代剑身自带的 5 点）；倍率仍是剑本身的 1.3~1.5。
IMMORTAL_MENDING_RECOVER = 15.0
# 失衡：累计几次失败就强制失败。
UNBALANCED_MAX_FAILS = 3

# ---- 附魔书（s1） ----
ENCHANT_MENDING = "经验修补"
ENCHANT_REFORGE = "重构"
ENCHANT_FORTUNE = "时运"
ENCHANT_UPGRADE = "升格"
ENCHANT_GUARD = "保护"
ENCHANT_PLUNDER = "掠夺"
BOOK_NAMES: tuple[str, ...] = tuple(ENCHANT_BOOKS)
MAX_BOOKS_PER_FORGE = 7
BOOK_EFFECTS: dict[str, str] = {
    ENCHANT_MENDING: "每次「增加」或「不变」都回复 5 完成度",
    ENCHANT_REFORGE: "下一锤若「增加」必定暴击，且这一锤最多还能重掷两次（重掷发「重构」）",
    ENCHANT_FORTUNE: "本局暴击率翻五倍，触发两次暴击后失效",
    ENCHANT_UPGRADE: "消耗 2 个附魔书次数，把剑换成下界合金剑",
    ENCHANT_GUARD: "三回合后获得一次保护：下一次失败不减少完成度（一局一次）",
    ENCHANT_PLUNDER: "本局「不变」也会涨价值，倍率 1.2~1.4",
}
FORTUNE_MULTIPLIER = 5.0
FORTUNE_CRITS = 2
PLUNDER_FACTOR: tuple[float, float] = (1.2, 1.4)
MENDING_RECOVER = 5.0
# 「保护」要砸满几回合才给保护次数（和「结束锻造」的最低回合数一致）。
GUARD_AFTER_TURNS = FORGE_MIN_TURNS
REFORGE_MAX_TIMES = 2

SWORDS: dict[str, Sword] = {
    "stone": Sword("stone", "石剑", 50, 50, _INCREASE_FACTOR["stone"],
                   _CRIT_CHANCE["stone"], free_if_poor=True),
    "iron": Sword("iron", "铁剑", 250, 250, _INCREASE_FACTOR["iron"],
                  _CRIT_CHANCE["iron"]),
    "diamond": Sword("diamond", "钻石剑", 500, 500, _INCREASE_FACTOR["diamond"],
                     _CRIT_CHANCE["diamond"]),
    "netherite": Sword("netherite", "下界合金剑", 300, 300,
                       _INCREASE_FACTOR["netherite"],
                       _CRIT_CHANCE["netherite"], buyable=False),
    "headless": Sword(
        "headless", "无头骑士剑", 1000, 1000,
        _INCREASE_FACTOR["headless"], _CRIT_CHANCE["headless"],
        initial_completion=50.0, loss=(20, 40), innate_mending=True,
        no_books=True, reward_cap=HEADLESS_REWARD_CAP, cursed=True,
    ),
}
BUYABLE_SWORDS: tuple[Sword, ...] = tuple(
    sword for sword in SWORDS.values() if sword.buyable
)


def buyable_now() -> tuple[Sword, ...]:
    """现在真的能开局买的剑：无头骑士剑要看限时开关。"""
    return tuple(
        sword for sword in BUYABLE_SWORDS
        if sword.key != "headless" or headless_available()
    )
SWORD_BY_NAME: dict[str, Sword] = {sword.name: sword for sword in BUYABLE_SWORDS}
SWORD_NAMES = tuple(sword.name for sword in BUYABLE_SWORDS)
TABLE_LAST_TURN = 5


def parse_sword(text: str) -> Sword | None:
    """把「锻造 石剑」解析成一把剑；形状不对/剑名不认识返回 None。"""
    parts = (text or "").replace("\u3000", " ").split()
    if len(parts) != 2 or parts[0] != COMMAND_FORGING:
        return None
    return SWORD_BY_NAME.get(parts[1])


def is_forging_command(text: str) -> bool:
    """是不是一个“像锻造开局”的命令：``锻造`` 后面跟了东西。"""
    parts = (text or "").replace("\u3000", " ").split()
    return len(parts) >= 2 and parts[0] == COMMAND_FORGING


def parse_book(text: str) -> str | None:
    """把「附魔 保护」解析成书名；形状不对/书名不认识返回 None。"""
    parts = (text or "").replace("\u3000", " ").split()
    if len(parts) != 2 or parts[0] != COMMAND_ENCHANT:
        return None
    return parts[1] if parts[1] in BOOK_NAMES else None


def is_enchant_command(text: str) -> bool:
    """``附魔`` 后面跟了东西（书名不认识也算；光说「附魔」不算）。"""
    parts = (text or "").replace("\u3000", " ").split()
    return len(parts) >= 2 and parts[0] == COMMAND_ENCHANT


def outcome_table(sword: str, turn: int) -> tuple[float, float, float]:
    """第 turn 回合的 ``(失败, 增加, 不变)``；第 5 回合之后一直用第 5 行。"""
    return _TABLES[sword][min(turn, TABLE_LAST_TURN)]


def completion_text(value: float) -> str:
    """完成度文案：整数就写整数，方便玩家一眼看懂。"""
    rounded = round(value, 1)
    if abs(rounded - round(rounded)) < 1e-9:
        return str(int(round(rounded)))
    return f"{rounded:.1f}"


def reward_for(value: float, completion: float) -> int:
    """收工收益：``完成度/100 × K × ln(1 + 价值/K)``（K=``REWARD_SCALE``）。

    完成度是**乘在 log 外面**的等比折扣，所以 50% 完成度就是拿一半。
    价值远小于 K 时 ``ln(1+x) ≈ x``，基本还是「价值 × 完成度 / 100」；
    价值超过 K 后收益被对数压住，每翻 e 倍价值只多 K 碎片。
    """
    value = max(0.0, float(value))
    completion = min(max(0.0, float(completion)), INITIAL_COMPLETION)
    return max(
        0,
        round(completion / 100 * REWARD_SCALE * math.log1p(value / REWARD_SCALE)),
    )


@dataclass
class StrikeResult:
    """一次「用力砸」的结果，交给文案层拼回复。"""

    outcome: str
    value: float
    turns: int
    completion: float = INITIAL_COMPLETION
    completion_before: float = INITIAL_COMPLETION
    completion_lost: float = 0.0
    completion_gained: float = 0.0
    factor: float | None = None
    value_before: float = 0.0
    gained: float = 0.0
    crit: bool = False
    guarded: bool = False
    reforge_crit: bool = False
    fortune_crit: bool = False
    plunder: bool = False
    mending: bool = False
    # 剑身自带的经验修补（无头骑士剑），文案要区分「不是附魔书给的」。
    innate_mending: bool = False
    deferred: bool = False
    reforge_left: int = 0
    # 诅咒相关
    unbalanced: bool = False
    fails: int = 0
    backlash: bool = False
    # 鸩毒：这一回合被固定啃掉完成度；畸变：失败反而涨了价值。
    poisoned: bool = False
    mutated: bool = False
    forced_end: bool = False
    forced_fail: bool = False
    reward: int = 0
    shards: int = 0

    @property
    def failed(self) -> bool:
        """这一锤是不是锻造失败（价值不变，只掉完成度）。"""
        return self.outcome == OUTCOME_FAIL

    @property
    def destroyed(self) -> bool:
        """剑是不是真的没了：失败判定命中、完成度又掉到 0 或以下。"""
        return self.failed and self.completion <= 0

    @property
    def ruined(self) -> bool:
        """完成度是不是归零了（含「反噬」把完成度啃光的情况）。"""
        return self.completion <= 0


@dataclass
class ForgeSession:
    """群里某个人的一局锻造。"""

    sword: str
    value: float
    completion: float = INITIAL_COMPLETION
    # 完成度上限：无头骑士剑抽到「易碎」时是 70。
    completion_cap: float = INITIAL_COMPLETION
    turns: int = 0
    last_factor: float | None = None
    guard: bool = False
    guard_book: bool = False
    guard_granted: bool = False
    mending: bool = False
    plunder: bool = False
    fortune: bool = False
    fortune_crits_left: int = 0
    books_used: int = 0
    reforge_left: int = 0
    pending: StrikeResult | None = None
    # ---- 无头骑士剑专属 ----
    # 本场诅咒（None = 普通剑，没有诅咒）。
    curse: str | None = None
    # 剑身自带经验修补（增加/不变都回完成度）。
    innate_mending: bool = False
    # 不接受附魔书。
    no_books: bool = False
    # 收工收益上限。
    reward_cap: float | None = None
    # 「失衡」累计的失败次数。
    fails: int = 0


class Forge:
    """所有进行中的局 + 规则实现。

    局内进度只放内存（``self.sessions``），重启就散；排行榜由 ``self.rank`` 落盘。
    方法都是同步的：Handler 在同一事件循环里按顺序调用，不需要锁。
    """

    def __init__(self, cards: Cards, rank: ForgeRank, rng=None) -> None:
        self.cards = cards
        self.rank = rank
        self.rng = rng or random
        self.sessions: dict[tuple[str, str], ForgeSession] = {}

    # ---- 查询 ----
    def active(self, group: str, user: str) -> ForgeSession | None:
        return self.sessions.get((group, user))

    # ---- 开局 ----
    def start(self, group: str, user: str, sword: Sword) -> dict:
        key = (group, user)
        existing = self.sessions.get(key)
        if existing is not None:
            return {"ok": False, "reason": "busy", "session": existing}
        if sword.key == "headless" and not headless_available():
            return {"ok": False, "reason": "expired", "sword": sword}
        if sword.free_if_poor:
            paid, remaining = self.cards.spend_shards_or_free(user, sword.cost)
        else:
            remaining = self.cards.spend_shards(user, sword.cost)
            if remaining is None:
                return {
                    "ok": False,
                    "reason": "poor",
                    "shards": self.cards.shards_of(user),
                    "sword": sword,
                }
            paid = sword.cost
        curse = self.rng.choice(list(CURSES)) if sword.cursed else None
        completion_cap = (
            BRITTLE_COMPLETION_CAP if curse == CURSE_BRITTLE else INITIAL_COMPLETION
        )
        # 诅咒·鸩毒：完成度直接拉满 100 起（之后每回合固定 -3）。
        initial_completion = (
            INITIAL_COMPLETION if curse == CURSE_POISON
            else float(sword.initial_completion)
        )
        self.sessions[key] = ForgeSession(
            sword=sword.key, value=float(sword.initial),
            completion=min(initial_completion, completion_cap),
            completion_cap=completion_cap,
            innate_mending=sword.innate_mending,
            no_books=sword.no_books,
            reward_cap=sword.reward_cap,
            curse=curse,
        )
        log(
            f"[锻造] {user} 开局 {sword.name}，"
            + ("碎片不够、免费开局" if paid == 0 else f"扣 {paid} 碎片")
            + f"，剩余 {remaining}"
            + (f"，本场诅咒【{curse}】" if curse else "")
        )
        return {
            "ok": True,
            "sword": sword,
            "shards": remaining,
            "value": sword.initial,
            "completion": self.sessions[key].completion,
            "paid": paid,
            "free": paid == 0,
            "curse": curse,
        }

    # ---- 砸 ----
    def pick_outcome(self, sword: str, turn: int, roll: float | None = None) -> str:
        if roll is None:
            roll = self.rng.random()
        fail, increase, _unchanged = outcome_table(sword, turn)
        if roll < fail:
            return OUTCOME_FAIL
        if roll < fail + increase:
            return OUTCOME_INCREASE
        return OUTCOME_UNCHANGED

    def random_uniform(self, low: float, high: float) -> float:
        return self.rng.uniform(low, high)

    def completion_loss(self, sword: str | None = None) -> int:
        """这一锤失败要掉多少完成度：默认 30~50，无头骑士剑是 20~40。"""
        bounds = COMPLETION_LOSS
        if sword:
            bounds = SWORDS[sword].loss or COMPLETION_LOSS
        return self.rng.randint(*bounds)

    def crit_chance(self, session: ForgeSession) -> float:
        chance = SWORDS[session.sword].crit_chance
        if session.curse == CURSE_BACKLASH:
            chance *= BACKLASH_CRIT_MULTIPLIER
        if session.fortune:
            chance *= FORTUNE_MULTIPLIER
        return min(1.0, chance)

    def is_crit(self, sword: str, roll: float | None = None,
                chance: float | None = None) -> bool:
        if roll is None:
            roll = self.rng.random()
        if chance is None:
            chance = SWORDS[sword].crit_chance
        return roll < chance

    def crit_hit(self, session: ForgeSession, roll: float | None = None) -> bool:
        return self.is_crit(session.sword, roll, self.crit_chance(session))

    def _roll_strike(self, session: ForgeSession, turn: int,
                     reforge_crit: bool = False) -> StrikeResult:
        """算一锤，不改 session（重掷就是拿同一份局面重算）。

        ``reforge_crit``：这一锤是「重构」罩着的那一锤，只要判到「增加」就必定暴击
        （重掷出来的结果同样算），相当于这回合套了一层「抢夺」。
        """
        sword = SWORDS[session.sword]
        before = session.value
        before_completion = session.completion
        outcome = self.pick_outcome(session.sword, turn)
        if outcome == OUTCOME_FAIL:
            # 失败不再扣价值，只扣完成度。
            # ① 诅咒·鸩毒：失败不掉完成度（每回合那 3 点在 _apply 里扣）。
            if session.curse == CURSE_POISON:
                return StrikeResult(
                    outcome=outcome, value=before, turns=turn,
                    value_before=before,
                    completion=before_completion,
                    completion_before=before_completion,
                )
            # ② 诅咒·失衡：这次失败一点完成度都不掉（但累计三次就强制失败）。
            if session.curse == CURSE_UNBALANCED:
                return StrikeResult(
                    outcome=outcome, value=before, turns=turn,
                    value_before=before, unbalanced=True,
                    completion=before_completion,
                    completion_before=before_completion,
                )
            # ③ 「保护」附魔：挡下这一次完成度损失，价值当然也不动。
            if session.guard:
                return StrikeResult(
                    outcome=outcome, value=before, turns=turn,
                    value_before=before, guarded=True,
                    completion=before_completion,
                    completion_before=before_completion,
                )
            # ④ 诅咒·畸变：失败反而涨价值 ×1.4，但完成度掉得更狠（30~50）。
            if session.curse == CURSE_MUTATION:
                after_completion = max(
                    0.0, before_completion - self.rng.randint(*MUTATION_LOSS)
                )
                return StrikeResult(
                    outcome=outcome, value=before * MUTATION_VALUE_FACTOR,
                    turns=turn, value_before=before,
                    factor=MUTATION_VALUE_FACTOR, mutated=True,
                    gained=before * MUTATION_VALUE_FACTOR - before,
                    completion=after_completion,
                    completion_before=before_completion,
                    completion_lost=before_completion - after_completion,
                )
            # ⑤ 没顶住：掉随机完成度（无头骑士剑 20~40）；掉到 0 或以下剑就崩了。
            after_completion = max(
                0.0, before_completion - self.completion_loss(session.sword)
            )
            return StrikeResult(
                outcome=outcome, value=before, turns=turn,
                value_before=before,
                completion=after_completion,
                completion_before=before_completion,
                completion_lost=before_completion - after_completion,
            )
        if outcome == OUTCOME_UNCHANGED:
            # 「掠夺」：不变也涨价值（不享受暴击，只吃这 1.2~1.4 倍）。
            factor = None
            value = before
            plunder = False
            if session.plunder:
                factor = round(self.random_uniform(*PLUNDER_FACTOR), 4)
                value = before * factor
                plunder = True
            after_completion = self._completion_after_mending(
                before_completion, session, success=False
            )
            return StrikeResult(
                outcome=outcome, value=value, turns=turn, value_before=before,
                factor=factor, gained=value - before, plunder=plunder,
                mending=session.mending or session.innate_mending,
                innate_mending=session.innate_mending,
                completion=after_completion,
                completion_before=before_completion,
                completion_gained=after_completion - before_completion,
            )
        # 增加：先判暴击（重构必中、时运翻五倍），中了用暴击倍率；
        # 没中就用剑的普通倍率（下界合金剑是 1.6~1.8）。
        crit = reforge_crit or self.crit_hit(session)
        lo, hi = CRIT_FACTOR if crit else sword.factor
        # 诅咒·贪饕：增加固定 ×1.1，暴击固定 ×10（都不掷骰子）。
        if session.curse == CURSE_GLUTTONY:
            lo = hi = GLUTTONY_CRIT_FACTOR if crit else GLUTTONY_FACTOR
        # 上下限一样时（剑本身的固定倍率）不掷骰子，结果就是那个固定倍率。
        factor = lo if lo == hi else round(self.random_uniform(lo, hi), 4)
        after_completion = self._completion_after_mending(
            before_completion, session, success=True
        )
        # 诅咒·反噬：暴击时完成度反过来 -5（这次不再 +5）。
        backlash = crit and session.curse == CURSE_BACKLASH
        if backlash:
            after_completion = max(0.0, before_completion - BACKLASH_LOSS)
        return StrikeResult(
            outcome=outcome,
            value=before * factor,
            turns=turn,
            factor=factor,
            value_before=before,
            gained=before * factor - before,
            crit=crit,
            reforge_crit=crit and reforge_crit,
            fortune_crit=crit and session.fortune,
            mending=session.mending or session.innate_mending,
            innate_mending=session.innate_mending,
            backlash=backlash,
            completion=after_completion,
            completion_before=before_completion,
            completion_gained=after_completion - before_completion,
        )

    @staticmethod
    def _completion_after_mending(before: float, session: ForgeSession,
                                  success: bool) -> float:
        """这一锤之后的完成度。

        没贴「经验修补」：成功 +3、不变 +0。
        贴了「经验修补」（或无头骑士剑这种剑身自带的）：**「增加」或「不变」都只回
        5 点**（成功时那 5 点取代基础的 3 点，不是 3+5）。
        抽到诅咒·永生时：增加/不变都回 **15 点**（取代上面那 5 点）。
        抽到诅咒·鸩毒时：一点都不回（每回合那 3 点在 ``_apply`` 里另扣）。
        上限是这局自己的 ``completion_cap``（抽到「易碎」时只有 70）。
        """
        if session.curse == CURSE_POISON:
            return before
        if session.curse == CURSE_IMMORTAL:
            # 诅咒·永生：增加/不变都回 10 点（取代剑身自带的 5 点）。
            gained = IMMORTAL_MENDING_RECOVER
        elif session.mending or session.innate_mending:
            gained = MENDING_RECOVER
        else:
            gained = COMPLETION_RECOVER if success else 0.0
        return min(session.completion_cap, before + gained)

    def _apply(self, session: ForgeSession, result: StrikeResult) -> None:
        """把这一锤落到局里，并结算这一锤真正用掉的附魔。"""
        session.value = result.value
        session.completion = result.completion
        session.turns = result.turns
        session.last_factor = result.factor
        # 诅咒·鸩毒：不管成败，每回合固定啃掉 3 点完成度。
        if session.curse == CURSE_POISON:
            poisoned = max(0.0, session.completion - POISON_TURN_LOSS)
            result.completion_lost = session.completion - poisoned
            result.completion_gained = -result.completion_lost
            session.completion = poisoned
            result.completion = poisoned
            result.poisoned = True
        # 诅咒·失衡：失败不掉完成度，但次数照记。
        if result.unbalanced:
            session.fails += 1
            result.fails = session.fails
        if result.guarded:
            session.guard = False
        # 时运：每暴击一次扣一次，扣完就失效。
        if result.crit and session.fortune:
            session.fortune_crits_left -= 1
            if session.fortune_crits_left <= 0:
                session.fortune = False
                session.fortune_crits_left = 0
        self._maybe_grant_guard(session)

    def _maybe_grant_guard(self, session: ForgeSession) -> None:
        """「保护」：砸满 3 回合后到手一次保护（一局只给一次）。"""
        if (
            session.guard_book
            and not session.guard_granted
            and session.turns >= GUARD_AFTER_TURNS
        ):
            session.guard = True
            session.guard_granted = True
            log(f"[锻造] 「保护」到账：下一次失败不减少完成度")

    # ---- 结算（收工 / 诅咒强制收工共用） ----
    def _settle(self, key: tuple[str, str], session: ForgeSession,
                username: str = "") -> dict:
        """算最终价值与收益、发碎片、记排行榜；返回结算摘要。

        诅咒·易碎的 ×1.6 乘在**最终收益**上（不是价值）：
        ``收益 = 1.8 × 完成度/100 × K × ln(1 + 价值/K)``，
        所以 ``value`` 记的还是剑本身的价值，排行榜也按这个原始价值记。
        收益封顶同样在这里落地。
        """
        user = key[1]
        value = float(session.value)
        brittle = session.curse == CURSE_BRITTLE
        completion = max(0.0, session.completion)
        reward = reward_for(value, completion)
        if brittle:
            reward = round(reward * BRITTLE_REWARD_FACTOR)
        capped = False
        if session.reward_cap is not None and reward > session.reward_cap:
            reward = int(session.reward_cap)
            capped = True
        total = self.cards.grant_shards(user, reward)
        sword_name = SWORDS[session.sword].name
        if capped:
            # 封顶后的收益是硬数字，别再让排行榜按公式重算回去。
            rank = self.rank.record(reward, user, username, sword=sword_name)
        else:
            rank = self.rank.record(
                reward, user, username,
                forge_value=value, completion=completion,
                reward_factor=BRITTLE_REWARD_FACTOR if brittle else None,
                sword=sword_name,
            )
        return {
            "value": value,
            "completion": completion,
            "reward": reward,
            "capped": capped,
            "brittle": brittle,
            "shards": total,
            "rank": rank,
        }

    def _settle_curse(self, key: tuple[str, str], session: ForgeSession,
                      result: StrikeResult, username: str = "") -> None:
        """诅咒的强制结算：永生满完成度自动收工、失衡三次失败强制毁剑。"""
        if session.curse == CURSE_UNBALANCED and session.fails >= UNBALANCED_MAX_FAILS:
            result.forced_fail = True
            del self.sessions[key]
            log(
                f"[锻造] {key[1]} 诅咒【失衡】失败满 "
                f"{UNBALANCED_MAX_FAILS} 次，锻造强制失败。"
            )
            return
        if (
            session.curse == CURSE_IMMORTAL
            and session.completion >= session.completion_cap
        ):
            del self.sessions[key]
            settled = self._settle(key, session, username)
            result.forced_end = True
            result.reward = settled["reward"]
            result.shards = settled["shards"]
            log(
                f"[锻造] {key[1]} 诅咒【永生】生效，完成度满 "
                f"{completion_text(session.completion)}%，强制收工 → "
                f"{settled['reward']} 碎片"
            )

    def _commit_pending(self, key: tuple[str, str],
                        session: ForgeSession,
                        username: str = "") -> StrikeResult | None:
        """把挂着等重构的那一锤落定；认下就作废剩余重掷次数。"""
        result = session.pending
        if result is None:
            return None
        session.pending = None
        result.deferred = False
        result.reforge_left = 0
        session.reforge_left = 0
        self._apply(session, result)
        if result.ruined:
            del self.sessions[key]
            log(f"[锻造] {key[1]} 第 {result.turns} 回合完成度归零（挂起的一锤被认下）")
        else:
            self._settle_curse(key, session, result, username)
        return result

    def settle_pending(self, group: str, user: str) -> StrikeResult | None:
        """把挂着的那一锤落定；没有挂起返回 None。"""
        key = (group, user)
        session = self.sessions.get(key)
        if session is None:
            return None
        return self._commit_pending(key, session)

    def strike(self, group: str, user: str,
               username: str = "") -> StrikeResult | None:
        """砸一下；没有进行中的局返回 None。"""
        key = (group, user)
        session = self.sessions.get(key)
        if session is None:
            return None
        settled = self._commit_pending(key, session, username)
        if settled is not None and (
            settled.ruined or settled.forced_end or settled.forced_fail
        ):
            return settled
        result = self._roll_strike(
            session, session.turns + 1, reforge_crit=session.reforge_left > 0
        )
        if session.reforge_left > 0:
            session.pending = result
            result.deferred = True
            result.reforge_left = session.reforge_left
            return result
        self._apply(session, result)
        if result.failed:
            if result.guarded:
                log(f"[锻造] {user} 「保护」附魔生效，完成度保持 {result.completion:.0f}")
            elif result.unbalanced:
                log(
                    f"[锻造] {user} 诅咒【失衡】吃下第 {result.fails} 次失败，"
                    f"完成度保持 {result.completion:.0f}"
                )
            elif not result.ruined:
                log(
                    f"[锻造] {user} 锻造失败：完成度 "
                    f"{result.completion_before:.0f} → {result.completion:.0f}"
                )
        if result.ruined:
            del self.sessions[key]
            log(
                f"[锻造] {user} 第 {result.turns} 回合完成度归零，剑彻底崩了"
                f"（{SWORDS[session.sword].name}）"
            )
        else:
            self._settle_curse(key, session, result, username)
        return result

    def strike_many(self, group: str, user: str, count: int,
                    username: str = "") -> list[StrikeResult]:
        """连砸 ``count`` 下（「用力砸5」），一锤接一锤算，**碰到锻造失败就停**。

        每锤的中间状态（完成度、价值、时运/保护次数、重构挂起）都照常结算，
        相当于把这么多次「用力砸」连起来发，只是回复合并成一条。失败那锤照样
        返回（完成度该掉就掉、剑该崩就崩），后面的回合不再自动砸。
        """
        results: list[StrikeResult] = []
        for _ in range(max(0, int(count))):
            result = self.strike(group, user, username)
            if result is None:
                break
            results.append(result)
            if result.failed or result.ruined:
                break
        return results

    def _reroll_pending(self, key: tuple[str, str],
                        session: ForgeSession, username: str = "") -> dict:
        session.reforge_left -= 1
        # 重掷也还是「重构」罩着的那一锤：判到增加照样必暴击。
        result = self._roll_strike(session, session.turns + 1, reforge_crit=True)
        if session.reforge_left > 0:
            session.pending = result
            result.deferred = True
            result.reforge_left = session.reforge_left
            return {"ok": True, "result": result, "left": session.reforge_left}
        session.pending = None
        self._apply(session, result)
        if result.ruined:
            del self.sessions[key]
            log(f"[锻造] {key[1]} 第 {result.turns} 回合完成度归零（重构用尽）")
        else:
            self._settle_curse(key, session, result, username)
        return {"ok": True, "result": result, "left": 0}

    def reforge(self, group: str, user: str, username: str = "") -> dict:
        """花一次重掷机会，重掷挂着的那一锤（「重构」命令）。"""
        key = (group, user)
        session = self.sessions.get(key)
        if session is None:
            return {"ok": False, "reason": "no_forge", "left": 0}
        if session.reforge_left <= 0:
            return {"ok": False, "reason": "no_charge", "left": 0}
        if session.pending is None:
            return {"ok": False, "reason": "nothing", "left": session.reforge_left}
        return self._reroll_pending(key, session, username)

    def use_book(self, group: str, user: str, name: str) -> dict:
        """锻造中用一本附魔书（「附魔 <书名>」）。"""
        key = (group, user)
        session = self.sessions.get(key)
        if session is None:
            return {"ok": False, "reason": "no_forge"}
        # 无头骑士剑不接受附魔书：书不扣，次数也不占。
        if session.no_books:
            return {
                "ok": False, "reason": "no_enchant", "name": name,
                "sword": SWORDS[session.sword].name,
            }
        if name not in BOOK_NAMES:
            return {"ok": False, "reason": "unknown", "name": name}
        # 别的书要先让挂着的那一锤落定，效果才落得下去。
        settled = self._commit_pending(key, session)
        if settled is not None and settled.destroyed:
            return {"ok": False, "reason": "broken"}
        if session.books_used >= MAX_BOOKS_PER_FORGE:
            return {
                "ok": False, "reason": "limit",
                "books_left": 0, "max": MAX_BOOKS_PER_FORGE, "need": 1,
            }
        if name == ENCHANT_REFORGE:
            # 「附魔 重构」只贴书给额度：额度没用掉时不再吃书。
            if session.reforge_left > 0:
                return {"ok": False, "reason": "armed", "left": session.reforge_left}
            if not self.cards.consume_book(user, name):
                return {"ok": False, "reason": "no_book", "name": name}
            session.books_used += 1
            session.reforge_left = REFORGE_MAX_TIMES
            log(
                f"[锻造] {user} 用「重构」，下一锤若「增加」必暴击、"
                f"可重掷 {session.reforge_left} 次"
                f"（本局 {session.books_used}/{MAX_BOOKS_PER_FORGE} 本）"
            )
            return {
                "ok": True, "action": "arm", "book": name,
                "effect": BOOK_EFFECTS[name], "left": session.reforge_left,
                "books_left": MAX_BOOKS_PER_FORGE - session.books_used,
                "max": MAX_BOOKS_PER_FORGE,
            }
        if name == ENCHANT_UPGRADE:
            # 「升格」吃 2 个附魔书次数，把剑换成下界合金剑。
            if session.sword == "netherite":
                return {"ok": False, "reason": "already", "name": name}
            if session.books_used + 2 > MAX_BOOKS_PER_FORGE:
                return {
                    "ok": False, "reason": "limit",
                    "books_left": MAX_BOOKS_PER_FORGE - session.books_used,
                    "max": MAX_BOOKS_PER_FORGE, "need": 2,
                }
            if not self.cards.consume_book(user, name):
                return {"ok": False, "reason": "no_book", "name": name}
            session.books_used += 2
            session.sword = "netherite"
            self._maybe_grant_guard(session)
            log(
                f"[锻造] {user} 用「升格」，剑换成下界合金剑"
                f"（本局 {session.books_used}/{MAX_BOOKS_PER_FORGE} 本）"
            )
            return {
                "ok": True, "action": "upgrade", "book": name,
                "effect": BOOK_EFFECTS[name],
                "sword": SWORDS["netherite"].name,
                "books_left": MAX_BOOKS_PER_FORGE - session.books_used,
                "max": MAX_BOOKS_PER_FORGE,
            }
        already = {
            ENCHANT_MENDING: session.mending,
            ENCHANT_FORTUNE: session.fortune,
            ENCHANT_GUARD: session.guard_book or session.guard_granted,
            ENCHANT_PLUNDER: session.plunder,
        }[name]
        if already:
            return {"ok": False, "reason": "already", "name": name}
        if not self.cards.consume_book(user, name):
            return {"ok": False, "reason": "no_book", "name": name}
        session.books_used += 1
        if name == ENCHANT_MENDING:
            session.mending = True
        elif name == ENCHANT_FORTUNE:
            session.fortune = True
            session.fortune_crits_left = FORTUNE_CRITS
        elif name == ENCHANT_GUARD:
            session.guard_book = True
            self._maybe_grant_guard(session)
        elif name == ENCHANT_PLUNDER:
            session.plunder = True
        log(
            f"[锻造] {user} 用「{name}」：{BOOK_EFFECTS[name]}"
            f"（本局 {session.books_used}/{MAX_BOOKS_PER_FORGE} 本）"
        )
        return {
            "ok": True, "action": "arm", "book": name,
            "effect": BOOK_EFFECTS[name],
            "guard_ready": session.guard,
            "books_left": MAX_BOOKS_PER_FORGE - session.books_used,
            "max": MAX_BOOKS_PER_FORGE,
        }

    def end_forge(self, group: str, user: str, username: str = "") -> dict | None:
        """收工：砸满 3 回合后按 ``reward_for(价值, 完成度)`` 发碎片，并记排行榜。"""
        key = (group, user)
        session = self.sessions.get(key)
        if session is None:
            return None
        settled = self._commit_pending(key, session, username)
        if settled is not None and settled.ruined:
            return {"ok": False, "reason": "broken"}
        if settled is not None and settled.forced_end:
            return {
                "ok": False, "reason": "forced_end", "reward": settled.reward,
            }
        if settled is not None and settled.forced_fail:
            return {"ok": False, "reason": "forced_fail"}
        if session.turns < FORGE_MIN_TURNS:
            return {
                "ok": False,
                "reason": "early",
                "turns": session.turns,
                "need": FORGE_MIN_TURNS,
            }
        # 先摘局再发碎片：中途出错也不会“领两次”或“局还挂着”。
        del self.sessions[key]
        sword = SWORDS[session.sword]
        done = self._settle(key, session, username)
        log(
            f"[锻造] {user} 收工 {sword.name}，价值 {session.value:.2f}、"
            f"完成度 {completion_text(done['completion'])}% → {done['reward']} 碎片，"
            f"共 {done['shards']}"
            + ("（收益封顶）" if done["capped"] else "")
            + (f"，排行榜第 {done['rank']} 名" if done["rank"] else "")
        )
        return {
            "ok": True,
            "sword": sword,
            "value": done["value"],
            "completion": done["completion"],
            "reward": done["reward"],
            "turns": session.turns,
            "shards": done["shards"],
            "rank": done["rank"],
            "brittle": done["brittle"],
            "capped": done["capped"],
            "curse": session.curse,
        }

    def clear(self) -> None:
        """清空所有进行中的局（自检用；排行榜不在这里清）。"""
        self.sessions.clear()


# --------------------------------------------------------------------------
# 文案
# --------------------------------------------------------------------------


def sword_list_text() -> str:
    return (
        "要锻造哪把？"
        + " / ".join(f"{s.name}（{s.cost} 奶龙碎片）" for s in buyable_now())
        + "。照「锻造 石剑」这样发就行。"
    )


def progress_line(session: ForgeSession) -> str:
    sword = SWORDS[session.sword]
    return (
        f"（{sword.name}，第 {session.turns} 回合，价值 {round(session.value)}，"
        f"完成度 {completion_text(session.completion)}%）"
    )


def start_text(result: dict, sword: Sword) -> str:
    if result.get("ok"):
        if result.get("free"):
            cost = (
                f"你连 {sword.cost} 碎片都没有……行吧，这次算我请你，"
                f"不扣碎片，还剩 {result['shards']}。"
            )
        else:
            cost = f"还剩 {result['shards']} 奶龙碎片。"
        lo, hi = sword.factor
        head = (
            f"喏，{sword.name}架好了，初始价值 {sword.initial}。"
            f"{cost}"
            f"砸一次价值涨到 {lo}~{hi} 倍。"
        )
        # 鸩毒把完成度拉满 100，所以看开局结果而不是剑的默认值。
        started_completion = result.get("completion", sword.initial_completion)
        if started_completion < INITIAL_COMPLETION:
            head += f"初始完成度 {completion_text(started_completion)}%，小心点。"
        curse = result.get("curse")
        if curse:
            head += f"\n本场诅咒【{curse}】：{CURSE_EFFECTS[curse]}。"
        return head
    if result["reason"] == "expired":
        return "无头骑士剑是限时活动，现在不开放 —— 先去锻造石剑/铁剑/钻石剑吧。"
    if result["reason"] == "busy":
        return (
            "你这把剑还没收工呢，急什么？"
            + progress_line(result["session"])
            + "接着喊「用力砸」就行。"
        )
    return (
        f"锻造{sword.name}要 {sword.cost} 奶龙碎片，你手里只有 {result['shards']}。"
        "先去签到抽卡攒点吧。"
    )


def books_text(owned: dict[str, int] | None = None) -> str:
    owned = owned or {}
    lines = ["附魔书有这几种："]
    for name in BOOK_NAMES:
        lines.append(f"{name}（{owned.get(name, 0)} 本）：{BOOK_EFFECTS[name]}")
    lines.append(
        f"一次锻造最多用 {MAX_BOOKS_PER_FORGE} 个附魔书次数。"
    )
    return "\n".join(lines)


def broken_text() -> str:
    return (
        "唔，不改了？那就这样吧——完成度已经归零，"
        "碎片一个都拿不回来。想再来一局就发「锻造 石剑」。"
    )


def strike_text(result: StrikeResult) -> str:
    lines = [pick_crit_flavor() if result.crit else pick_flavor()]
    completion = completion_text(result.completion)
    if result.ruined and not result.failed:
        lines.append(
            "完成度被诅咒啃光了……剑彻底崩了，这局废了，碎片不退。"
            f"（第 {result.turns} 回合）"
        )
    elif result.failed:
        if result.forced_fail:
            lines.append(
                f"哐——！这是第三次失败了……诅咒【失衡】生效，"
                f"剑当场报废，碎片不退。（第 {result.turns} 回合）"
            )
        elif result.unbalanced:
            lines.append(
                f"哐——！剑身裂了……诅咒【失衡】生效，完成度 {completion}%，"
                f"（已失败 {result.fails}/{UNBALANCED_MAX_FAILS} 次"
                f"）。（第 {result.turns} 回合）"
            )
        elif result.guarded:
            lines.append(
                f"Anubis逆转了死亡的流沙————「保护」生效。这一锤完成度不变，还是 {completion}%，"
                f"价值 {round(result.value)}。（第 {result.turns} 回合）"
            )
        elif result.destroyed:
            lines.append(
                f"哐——！剑身彻底崩了……完成度归零，第 {result.turns} 回合，"
                "这局废了，碎片不退。"
            )
        elif result.deferred:
            lines.append(
                f"哐——！剑身裂了……认下这一锤要掉 "
                f"{completion_text(result.completion_lost)} 完成度，只剩 {completion}%，"
                f"不满意就发「重构」。（第 {result.turns} 回合）"
            )
        else:
            lines.append(
                f"哐——！剑身裂了……这一锤掉了 "
                f"{completion_text(result.completion_lost)} 完成度，现在剩 {completion}%，"
                f"当前价值 {round(result.value)}。（第 {result.turns} 回合）"
            )
    else:
        factor = result.factor if result.factor is not None else 1.0
        gained = round(result.value) - round(result.value_before)
        head = "暴击！" if result.crit else ""
        completion_part = (
            f"完成度 {completion_text(result.completion_before)}%→{completion}%"
            if result.completion_gained != 0
            else f"完成度 {completion}%"
        )
        if result.plunder:
            lines.append(
                f"这一锤不变……「掠夺」生效，×{factor}，"
                f"现在价值 {round(result.value)}，本回合增加 {gained}，"
                f"{completion_part}。（第 {result.turns} 回合）"
            )
        else:
            lines.append(
                f"{head}这一锤 ×{factor}，现在价值 {round(result.value)}，"
                f"本回合增加 {gained}，{completion_part}。（第 {result.turns} 回合）"
            )
    if result.reforge_crit:
        lines.append("（附魔书·重构生效：这一锤必定暴击）")
    if result.fortune_crit:
        lines.append("（附魔书·时运生效）")
    if result.mending and result.completion_gained > 0:
        lines.append(
            "（无头骑士剑·经验修补生效）" if result.innate_mending
            else "（附魔书·经验修补生效）"
        )
    if result.plunder:
        lines.append("（附魔书·掠夺生效）")
    if result.backlash:
        lines.append(
            f"（诅咒·反噬生效：完成度 -{completion_text(BACKLASH_LOSS)}）"
        )
    if result.mutated:
        lines.append(
            f"（诅咒·畸变生效：失败也涨价值 ×{MUTATION_VALUE_FACTOR}）"
        )
    if result.poisoned:
        lines.append(
            f"（诅咒·鸩毒生效：完成度 -{completion_text(POISON_TURN_LOSS)}）"
        )
    if result.forced_end:
        lines.append(
            f"（诅咒·永生生效：完成度满了，强制收工 → {result.reward} 奶龙碎片）"
        )
    if result.deferred:
        lines.append(
            "（附魔书·重构就绪：这回合必暴击，"
            f"发「重构」可重掷，还剩 {result.reforge_left} 次）"
        )
    return "\n".join(lines)


def strike_batch_text(results: list[StrikeResult]) -> str:
    """「用力砸N」的合并回复：一锤一行，剑崩了就收尾。

    行格式固定成「已进行 x 次锻造，现在价值 …，该回合增加 …，完成度 …%。
    （第 x 回合）」，暴击/失败/保护/掠夺等状态补在句尾。
    """
    lines: list[str] = []
    for result in results:
        turn = result.turns
        completion = completion_text(result.completion)
        if result.failed:
            gained = 0
            if result.guarded:
                extra = "（保护生效，完成度没掉）"
            elif result.forced_fail:
                extra = "（诅咒·失衡：第三次失败，剑碎了）"
            elif result.unbalanced:
                extra = (
                    "（诅咒·失衡：完成度不降，已失败 "
                    f"{result.fails}/{UNBALANCED_MAX_FAILS} 次）"
                )
            elif result.ruined:
                extra = "（锻造失败，剑碎了）"
            else:
                extra = (
                    "（锻造失败，完成度 -"
                    f"{completion_text(result.completion_lost)}）"
                )
        else:
            gained = round(result.value) - round(result.value_before)
            extra = ""
            if result.crit:
                extra = "（暴击）"
            if result.plunder:
                extra = "（掠夺生效）"
        lines.append(
            f"已进行 {turn} 次锻造，现在价值 {round(result.value)}，"
            f"该回合增加 {gained}，完成度 {completion}%{extra}。（第 {turn} 回合）"
        )
    if results and results[-1].forced_end:
        lines.append(
            "（诅咒·永生生效：完成度满了，强制收工 → "
            f"{results[-1].reward} 奶龙碎片）"
        )
    elif results and results[-1].ruined:
        lines.append("哐——！剑身彻底崩了……这局废了，碎片不退。")
    elif results and results[-1].deferred:
        lines.append(
            "（附魔书·重构就绪：想重掷就发「重构」，"
            f"还剩 {results[-1].reforge_left} 次）"
        )
    return "\n".join(lines)


def book_text(result: dict, book: str, owned: dict[str, int] | None = None) -> str:
    """「附魔 <书名>」的完整回复（成功/各种失败都在这里）。"""
    if not result.get("ok"):
        reason = result.get("reason")
        if reason == "broken":
            return broken_text()
        if reason == "no_enchant":
            return (
                f"{result.get('sword') or '这把剑'}不接受附魔书 —— "
                "书我原样还你，也没占这一局的次数。"
            )
        if reason == "limit":
            need = int(result.get("need") or 1)
            left = int(result.get("books_left") or 0)
            if need > 1:
                return (
                    f"「{book}」要吃 {need} 个附魔书次数，这一局只剩 {left} 次了，"
                    "这本先收着吧。"
                )
            return (
                f"这一局已经用满 {MAX_BOOKS_PER_FORGE} 本附魔书了，"
                f"剩余附魔书次数：0/{MAX_BOOKS_PER_FORGE}。"
                "剩下的回合就靠已经贴上的效果吧，这本先收着。"
            )
        if reason == "no_book":
            owned_line = (
                "你现在有：" + "、".join(f"{n} ×{c}" for n, c in (owned or {}).items()) + "。"
                if owned else "你手里一本附魔书都没有。"
            )
            return (
                f"你手里没有「{book}」这本附魔书，别拿空气糊弄我。"
                + owned_line
                + f"开箱有 {CARD_BOX_BOOK_PROBABILITY:.0%} 概率开出来，去开箱子吧。"
            )
        if reason == "already":
            if book == ENCHANT_UPGRADE:
                return "这把剑已经是下界合金剑了，再升格也没用 —— 书我可不退。"
            if book == ENCHANT_GUARD:
                return "「保护」这一局已经贴过了（一局只能一次），书我可不退。"
            return f"「{book}」已经在生效了，再贴一本也是白搭 —— 书我可不退。"
        if reason == "armed":
            return (
                f"重构早就给你架好了（还能重掷 {result.get('left', 0)} 次），"
                "先砸一锤再说，别急着烧书。"
            )
        if reason == "no_forge":
            return "附魔得在锻造里用 —— 先发「锻造 石剑」开一局，再发「附魔 <书名>」。"
        return books_text(owned)
    flavor = pick_book_flavor()
    if book == ENCHANT_REFORGE:
        tail = (
            "下一锤若「增加」必定暴击；砸完不满意就发「重构」重掷，最多 "
            f"{result.get('left', 0)} 次；认下（发别的命令）就作废剩下的。"
        )
    elif book == ENCHANT_UPGRADE:
        tail = (
            f"剑换成{result.get('sword') or '下界合金剑'}了："
            f"「增加」倍率 1.6~1.8、暴击 20%、失败率恒定 20%。"
        )
    elif book == ENCHANT_GUARD and not result.get("guard_ready"):
        tail = "「保护」贴上了：砸满 3 回合后自动到账，下一次失败不减少完成度。（一局一次）"
    else:
        tail = f"「{book}」贴上了：{result['effect']}。"
    quota = f"本次锻造剩余附魔书次数：{result['books_left']}/{result['max']}"
    return f"{flavor}\n{tail}\n{quota}"


def reforge_text(result: dict) -> str:
    if result.get("ok"):
        return strike_text(result["result"])
    reason = result.get("reason")
    if reason == "no_charge":
        return (
            "这一锤的重构次数用完了—— 想再重掷就先贴一本"
            "「附魔 重构」。"
        )
    if reason == "nothing":
        return (
            f"还没砸呢，重构什么？这一锤还有 {result.get('left', 0)} 次重掷机会，"
            "先发「用力砸」，砸完不满意再发「重构」。"
        )
    return ""


def end_text(result: dict | None, username: str = "") -> str:
    if result is None:
        return ""
    if not result.get("ok"):
        reason = result.get("reason")
        if reason == "broken":
            return broken_text()
        if reason == "forced_fail":
            return (
                "诅咒【失衡】生效：锻造失败。"
            )
        if reason == "forced_end":
            return (
                "诅咒【永生】已经替你收工了：完成度一满就自动结算，"
                f"{result.get('reward', 0)} 奶龙碎片已经到账。"
            )
        if reason == "early":
            left = result["need"] - result["turns"]
            return f"才砸 {result['turns']} 次就想收工？再砸 {left} 次再说。"
        return ""
    rank_line = (
        f"\n这局收益上了锻造排行榜第 {result['rank']} 名！"
        if result.get("rank") else ""
    )
    curse_line = ""
    if result.get("brittle"):
        curse_line = "\n（诅咒·易碎生效：最终收益 ×1.6）"
    if result.get("capped"):
        curse_line += f"\n（收益触到上限，只发 {result['reward']} 碎片）"
    return (
        f"收工！{result['sword'].name}价值 {round(result['value'])}、完成度 "
        f"{completion_text(result['completion'])}% → {result['reward']} 奶龙碎片，"
        f"现在共有 {result['shards']}。"
        f"{username}，下次想砸再喊我。"
        + curse_line
        + rank_line
    )


def rank_text(records: list[dict]) -> str:
    """排行榜渲染失败时的文字版：固定十行，名次/收益/剑/人/时间。"""
    lines = ["锻造排行榜（锻造收益最高的十次）"]
    for index in range(TOP_N):
        rank = ordinal(index + 1)
        if index < len(records):
            item = records[index]
            name = item.get("name") or "无名氏"
            sword = str(item.get("sword") or "").strip() or "—"
            lines.append(
                f"{rank}  {int(item.get('value') or 0):,}  "
                f"{sword}  {name}  {item.get('time') or '—'}"
            )
        else:
            lines.append(f"{rank}  —  虚位以待  —")
    return "\n".join(lines)
