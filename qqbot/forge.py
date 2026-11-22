"""锻造系统：砸剑、涨价值、掉完成度、附魔书、按收益换银币。

规则照 ``data/锻造系统.txt``：

* 开局：``锻造 石剑`` / ``锻造 铁剑`` / ``锻造 钻石剑``，入场费与初始价值
  分别是 50/250/500，完成度一律从 100 起。银币不够时明确拒绝，**只有石剑**
  付不起也照样开局（不扣银币）。
* 每回合 ``用力砸``：价值增加（石剑 ×1.2~1.4，铁剑 ×1.3~1.5，钻石剑 ×1.4~1.6）、
  不变、或**锻造失败**。三档概率逐回合查表，第 5 回合后沿用第 5 行。
  写成 ``用力砸5`` 就是一次连砸 5 回合，结果按回合合并成一条消息（最多 10 下），
  中途**锻造失败就停下**，后面的回合不再自动砸。
* 失败**不再降低价值**，改成掉随机 30~50 完成度（``COMPLETION_LOSS``）；
  完成度掉到 0 或以下时剑彻底崩了，局当场结束、拿 0 银币。
* 锻造成功（「增加」）时完成度回复 3 点（``COMPLETION_RECOVER``），上限仍是 100。
* 触发「增加」时另判一次幸运暴击（3%/8%/12%，倍率 ×1.8~2.3）。
* 砸满 3 回合后 ``结束锻造``（别名 ``收工``）按
  ``完成度/100 × 5000 × ln(1 + 价值/5000)`` 发银币（见 ``reward_for``）：
  完成度是等比折扣，价值走对数曲线；价值越小越接近原值，接近 5000 之后压得越狠。
* 附魔书（开箱 20% 开出，可累积）：一局最多用 7 个次数，效果见 ``BOOK_EFFECTS``；
  「升格」把剑换成下界合金剑并吃 2 个次数。
* 重构：``附魔 重构`` 给下一锤 2 次重掷机会，且这一锤只要「增加」就必定暴击；
  ``重构`` 命令重掷；认下就作废剩余次数。
* 每次成功收工记一条锻造排行榜（见 forge_rank.py）。

局内进度只放内存（重启就散），排行榜才落盘。
"""
from __future__ import annotations

import math
import random
import re
from dataclasses import dataclass

from .base import log
from .cards import ENCHANT_BOOKS, Cards
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
    # 银币不够入场费时要不要照样开局（免费、不扣银币）。只有石剑是 True。
    free_if_poor: bool = False
    # 能不能直接用「锻造 <剑名>」开局。下界合金剑只能靠「升格」换，所以是 False。
    buyable: bool = True


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
}

_INCREASE_FACTOR: dict[str, tuple[float, float]] = {
    "stone": (1.2, 1.4),
    "iron": (1.3, 1.5),
    "diamond": (1.4, 1.6),
    "netherite": (1.6, 1.8),
}
_CRIT_CHANCE: dict[str, float] = {
    "stone": 0.03,
    "iron": 0.08,
    "diamond": 0.12,
    "netherite": 0.20,
}
CRIT_FACTOR: tuple[float, float] = (1.8, 2.3)

# ---- 附魔书（s2） ----
ENCHANT_MENDING = "经验修补"
ENCHANT_REFORGE = "重构"
ENCHANT_SHARP = "锋利"
ENCHANT_HEAL = "治愈"
ENCHANT_FORTUNE = "时运"
ENCHANT_LAST_DANCE = "最后一舞"
# s1 遗留：本赛季开不出来（见 ``ENCHANT_BOOKS``），机制留着，换季可能回来。
ENCHANT_UPGRADE = "升格"
ENCHANT_GUARD = "保护"
ENCHANT_PLUNDER = "掠夺"
BOOK_NAMES: tuple[str, ...] = tuple(ENCHANT_BOOKS)
MAX_BOOKS_PER_FORGE = 7
BOOK_EFFECTS: dict[str, str] = {
    ENCHANT_MENDING: "每次「增加」或「不变」都回复 5 完成度",
    ENCHANT_REFORGE: "下一锤若「增加」必定暴击，且这一锤最多还能重掷两次（重掷发「重构」）",
    ENCHANT_SHARP: "本局每次「增加」都按最大倍率（石剑 1.4 / 铁剑 1.5 / 钻石剑 1.6）",
    ENCHANT_HEAL: "本局每次暴击额外回复 15 完成度，最多生效 2 次",
    ENCHANT_FORTUNE: "本局暴击率翻五倍，触发两次暴击后失效",
    ENCHANT_LAST_DANCE: "立刻 +30 完成度，三回合后 -30；三回合内收工收益减半",
    ENCHANT_UPGRADE: "消耗 2 个附魔书次数，把剑换成下界合金剑",
    ENCHANT_GUARD: "三回合后获得一次保护：下一次失败不减少完成度（一局一次）",
    ENCHANT_PLUNDER: "本局「不变」也会涨价值，倍率 1.2~1.4",
}
FORTUNE_MULTIPLIER = 5.0
FORTUNE_CRITS = 2
PLUNDER_FACTOR: tuple[float, float] = (1.2, 1.4)
MENDING_RECOVER = 5.0
# 「治愈」：暴击时额外回的完成度与生效次数上限。
HEAL_RECOVER = 15.0
HEAL_CHARGES = 2
# 「最后一舞」：立刻涨多少、几回合后扣多少、提前收工的收益倍率。
LAST_DANCE_GAIN = 30.0
LAST_DANCE_LOSS = 30.0
LAST_DANCE_TURNS = 3
LAST_DANCE_PENALTY = 0.5
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
}
BUYABLE_SWORDS: tuple[Sword, ...] = tuple(
    sword for sword in SWORDS.values() if sword.buyable
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
    价值超过 K 后收益被对数压住，每翻 e 倍价值只多 K 银币。
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
    # 治愈：这一锤暴击吃了一次额外回复；heal_left 是吃完剩下的次数。
    healed: bool = False
    heal_left: int = 0
    # 最后一舞：这一锤正好到三回合，被扣了完成度。
    dance_drop: bool = False
    deferred: bool = False
    reforge_left: int = 0

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
        """完成度是不是归零了。"""
        return self.completion <= 0


@dataclass
class ForgeSession:
    """群里某个人的一局锻造。"""

    sword: str
    value: float
    completion: float = INITIAL_COMPLETION
    turns: int = 0
    last_factor: float | None = None
    guard: bool = False
    guard_book: bool = False
    guard_granted: bool = False
    mending: bool = False
    plunder: bool = False
    sharp: bool = False
    heal_left: int = 0
    # 最后一舞：贴上的回合数，以及那 -30 是不是已经扣过了。
    last_dance: bool = False
    last_dance_turn: int = 0
    last_dance_done: bool = False
    fortune: bool = False
    fortune_crits_left: int = 0
    books_used: int = 0
    reforge_left: int = 0
    pending: StrikeResult | None = None


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
        self.sessions[key] = ForgeSession(
            sword=sword.key, value=float(sword.initial),
        )
        log(
            f"[锻造] {user} 开局 {sword.name}，"
            + ("银币不够、免费开局" if paid == 0 else f"扣 {paid} 银币")
            + f"，剩余 {remaining}"
        )
        return {
            "ok": True,
            "sword": sword,
            "shards": remaining,
            "value": sword.initial,
            "completion": self.sessions[key].completion,
            "paid": paid,
            "free": paid == 0,
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

    def completion_loss(self) -> int:
        """这一锤失败要掉多少完成度（30~50）。"""
        return self.rng.randint(*COMPLETION_LOSS)

    def crit_chance(self, session: ForgeSession) -> float:
        chance = SWORDS[session.sword].crit_chance
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
            # ① 「保护」附魔：挡下这一次完成度损失，价值当然也不动。
            if session.guard:
                return StrikeResult(
                    outcome=outcome, value=before, turns=turn,
                    value_before=before, guarded=True,
                    completion=before_completion,
                    completion_before=before_completion,
                )
            # ② 没顶住：掉随机完成度（30~50）；掉到 0 或以下剑就崩了。
            after_completion = max(0.0, before_completion - self.completion_loss())
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
                mending=session.mending,
                completion=after_completion,
                completion_before=before_completion,
                completion_gained=after_completion - before_completion,
            )
        # 增加：先判暴击（重构必中、时运翻五倍），中了用暴击倍率；
        # 没中就用剑的普通倍率（下界合金剑是 1.6~1.8）。
        crit = reforge_crit or self.crit_hit(session)
        lo, hi = CRIT_FACTOR if crit else sword.factor
        # 「锋利」：本局的普通增加固定吃剑的最大倍率（暴击还是走 1.8~2.3）。
        if session.sharp and not crit:
            lo = hi = sword.factor[1]
        # 上下限一样时（剑本身的固定倍率）不掷骰子，结果就是那个固定倍率。
        factor = lo if lo == hi else round(self.random_uniform(lo, hi), 4)
        after_completion = self._completion_after_mending(
            before_completion, session, success=True
        )
        # 「治愈」：暴击时额外回 15 完成度，一局最多两次。
        healed = crit and session.heal_left > 0
        if healed:
            after_completion = min(
                INITIAL_COMPLETION, after_completion + HEAL_RECOVER
            )
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
            mending=session.mending,
            healed=healed,
            heal_left=max(0, session.heal_left - 1) if healed else session.heal_left,
            completion=after_completion,
            completion_before=before_completion,
            completion_gained=after_completion - before_completion,
        )

    @staticmethod
    def _completion_after_mending(before: float, session: ForgeSession,
                                  success: bool) -> float:
        """这一锤之后的完成度。

        没贴「经验修补」：成功 +3、不变 +0。
        贴了「经验修补」：**「增加」或「不变」都只回 5 点**（成功时那 5 点取代
        基础的 3 点，不是 3+5）。上限是 100。
        """
        if session.mending:
            gained = MENDING_RECOVER
        else:
            gained = COMPLETION_RECOVER if success else 0.0
        return min(INITIAL_COMPLETION, before + gained)

    def _apply(self, session: ForgeSession, result: StrikeResult) -> None:
        """把这一锤落到局里，并结算这一锤真正用掉的附魔。"""
        session.value = result.value
        session.completion = result.completion
        session.turns = result.turns
        session.last_factor = result.factor
        if result.guarded:
            session.guard = False
        # 时运：每暴击一次扣一次，扣完就失效。
        if result.crit and session.fortune:
            session.fortune_crits_left -= 1
            if session.fortune_crits_left <= 0:
                session.fortune = False
                session.fortune_crits_left = 0
        # 治愈：吃一次额外回复就少一次。
        if result.healed:
            session.heal_left = result.heal_left
        # 最后一舞：贴书上满三回合就扣 30 完成度（一局只扣一次）。
        if (
            session.last_dance
            and not session.last_dance_done
            and session.turns >= session.last_dance_turn + LAST_DANCE_TURNS
        ):
            before_dance = session.completion
            session.completion = max(0.0, before_dance - LAST_DANCE_LOSS)
            result.completion = session.completion
            result.completion_lost += before_dance - session.completion
            result.dance_drop = True
            session.last_dance_done = True
            log(
                f"[锻造] 最后一舞到期：完成度 -{completion_text(LAST_DANCE_LOSS)}"
                f" → {completion_text(session.completion)}%"
            )
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

    # ---- 结算 ----
    def _settle(self, key: tuple[str, str], session: ForgeSession,
                username: str = "") -> dict:
        """算最终价值与收益、发银币、记排行榜；返回结算摘要。"""
        user = key[1]
        value = float(session.value)
        completion = max(0.0, session.completion)
        reward = reward_for(value, completion)
        # 最后一舞：三回合那 30 点还没扣就收工 → 收益减半。
        halved = session.last_dance and not session.last_dance_done
        if halved:
            reward = int(round(reward * LAST_DANCE_PENALTY))
        total = self.cards.grant_shards(user, reward)
        sword_name = SWORDS[session.sword].name
        if halved:
            # 减半后的收益是硬数字，别再让排行榜按公式重算回去。
            rank = self.rank.record(reward, user, username, sword=sword_name)
        else:
            rank = self.rank.record(
                reward, user, username,
                forge_value=value, completion=completion,
                sword=sword_name,
            )
        return {
            "value": value,
            "completion": completion,
            "reward": reward,
            "halved": halved,
            "shards": total,
            "rank": rank,
        }

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
        if settled is not None and settled.ruined:
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
            ENCHANT_SHARP: session.sharp,
            ENCHANT_HEAL: session.heal_left > 0,
            ENCHANT_LAST_DANCE: session.last_dance,
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
        elif name == ENCHANT_SHARP:
            session.sharp = True
        elif name == ENCHANT_HEAL:
            session.heal_left = HEAL_CHARGES
        elif name == ENCHANT_LAST_DANCE:
            # 立刻涨 30 完成度，三回合后那 30 点会扣回去（见 ``_apply``）。
            session.last_dance = True
            session.last_dance_turn = session.turns
            session.last_dance_done = False
            session.completion = min(
                INITIAL_COMPLETION, session.completion + LAST_DANCE_GAIN
            )
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
            "completion": session.completion,
            "heal_left": session.heal_left,
            "dance_turns": LAST_DANCE_TURNS,
            "books_left": MAX_BOOKS_PER_FORGE - session.books_used,
            "max": MAX_BOOKS_PER_FORGE,
        }

    def end_forge(self, group: str, user: str, username: str = "") -> dict | None:
        """收工：砸满 3 回合后按 ``reward_for(价值, 完成度)`` 发银币，并记排行榜。"""
        key = (group, user)
        session = self.sessions.get(key)
        if session is None:
            return None
        settled = self._commit_pending(key, session, username)
        if settled is not None and settled.ruined:
            return {"ok": False, "reason": "broken"}
        if session.turns < FORGE_MIN_TURNS:
            return {
                "ok": False,
                "reason": "early",
                "turns": session.turns,
                "need": FORGE_MIN_TURNS,
            }
        # 先摘局再发银币：中途出错也不会“领两次”或“局还挂着”。
        del self.sessions[key]
        sword = SWORDS[session.sword]
        done = self._settle(key, session, username)
        log(
            f"[锻造] {user} 收工 {sword.name}，价值 {session.value:.2f}、"
            f"完成度 {completion_text(done['completion'])}% → {done['reward']} 银币，"
            f"共 {done['shards']}"
            + (f"，排行榜第 {done['rank']} 名" if done['rank'] else "")
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
            "halved": done["halved"],
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
        + " / ".join(f"{s.name}（{s.cost} 银币）" for s in BUYABLE_SWORDS)
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
                f"你连 {sword.cost} 银币都没有……行吧，这次算我请你，"
                f"不扣银币，还剩 {result['shards']}。"
            )
        else:
            cost = f"还剩 {result['shards']} 银币。"
        lo, hi = sword.factor
        head = (
            f"喏，{sword.name}架好了，初始价值 {sword.initial}。"
            f"{cost}"
            f"砸一次价值涨到 {lo}~{hi} 倍。"
        )
        return head
    if result["reason"] == "busy":
        return (
            "你这把剑还没收工呢，急什么？"
            + progress_line(result["session"])
            + "接着喊「用力砸」就行。"
        )
    return (
        f"锻造{sword.name}要 {sword.cost} 银币，你手里只有 {result['shards']}。"
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
        "银币一个都拿不回来。想再来一局就发「锻造 石剑」。"
    )


def strike_text(result: StrikeResult) -> str:
    lines = [pick_crit_flavor() if result.crit else pick_flavor()]
    completion = completion_text(result.completion)
    if result.failed:
        if result.guarded:
            lines.append(
                f"Anubis逆转了死亡的流沙————「保护」生效。这一锤完成度不变，还是 {completion}%，"
                f"价值 {round(result.value)}。（第 {result.turns} 回合）"
            )
        elif result.destroyed:
            lines.append(
                f"哐——！剑身彻底崩了……完成度归零，第 {result.turns} 回合，"
                "这局废了，银币不退。"
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
        lines.append("（附魔书·经验修补生效）")
    if result.healed:
        left = int(result.heal_left)
        lines.append(
            f"（附魔书·治愈生效：完成度 +{completion_text(HEAL_RECOVER)}，"
            + (f"还能生效 {left} 次）" if left > 0 else "本局已用尽）")
        )
    if result.plunder:
        lines.append("（附魔书·掠夺生效）")
    if result.dance_drop:
        lines.append(
            f"（最后一舞：{LAST_DANCE_TURNS} 回合到，完成度 -"
            f"{completion_text(LAST_DANCE_LOSS)}）"
        )
        if result.ruined:
            lines.append("完成度归零，剑彻底崩了……这局废了，银币不退。")
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
        if result.healed:
            extra += f"（治愈 +{completion_text(HEAL_RECOVER)}）"
        if result.dance_drop:
            if result.failed:
                # completion_lost 已经把这一锤和最后一舞一起算进去了，别写两遍。
                extra = (
                    "（锻造失败 + 最后一舞到期，完成度 -"
                    f"{completion_text(result.completion_lost)}）"
                )
            else:
                extra += f"（最后一舞 -{completion_text(LAST_DANCE_LOSS)}）"
        lines.append(
            f"已进行 {turn} 次锻造，现在价值 {round(result.value)}，"
            f"该回合增加 {gained}，完成度 {completion}%{extra}。（第 {turn} 回合）"
        )
    if results and results[-1].ruined:
        lines.append("哐——！剑身彻底崩了……这局废了，银币不退。")
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
                + "开箱现在不出附魔书了，这本暂时弄不到。"
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
    elif book == ENCHANT_LAST_DANCE:
        turns = int(result.get("dance_turns") or LAST_DANCE_TURNS)
        tail = (
            f"「最后一舞」贴上了：完成度立刻 +{completion_text(LAST_DANCE_GAIN)}"
            f"（现在 {completion_text(float(result.get('completion') or 0))}%），"
            f"{turns} 回合后会扣回 {completion_text(LAST_DANCE_LOSS)}；"
            "那之前收工的话收益减半。"
        )
    elif book == ENCHANT_HEAL:
        tail = (
            f"「治愈」贴上了：之后每次暴击额外回 {completion_text(HEAL_RECOVER)} 完成度，"
            f"最多 {HEAL_CHARGES} 次。"
        )
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
        if reason == "early":
            left = result["need"] - result["turns"]
            return f"才砸 {result['turns']} 次就想收工？再砸 {left} 次再说。"
        return ""
    rank_line = (
        f"\n这局收益上了锻造排行榜第 {result['rank']} 名！"
        if result.get("rank") else ""
    )
    dance_line = (
        f"\n（最后一舞：没撑到 {LAST_DANCE_TURNS} 回合就收工，收益减半）"
        if result.get("halved") else ""
    )
    return (
        f"收工！{result['sword'].name}价值 {round(result['value'])}、完成度 "
        f"{completion_text(result['completion'])}% → {result['reward']} 银币，"
        f"现在共有 {result['shards']}。"
        f"{username}，下次想砸再喊我。"
        + dance_line
        + rank_line
    )


def rank_text(records: list[dict]) -> str:
    """排行榜渲染失败时的文字版：固定十行，名次/收益/人/时间/类型（跟图一致）。"""
    lines = ["锻造排行榜（锻造收益最高的十次）"]
    for index in range(TOP_N):
        rank = ordinal(index + 1)
        if index < len(records):
            item = records[index]
            name = item.get("name") or "无名氏"
            sword = str(item.get("sword") or "").strip() or "—"
            lines.append(
                f"{rank}  {int(item.get('value') or 0):,}  "
                f"{name}  {item.get('time') or '—'}  {sword}"
            )
        else:
            lines.append(f"{rank}  —  虚位以待  —")
    return "\n".join(lines)
