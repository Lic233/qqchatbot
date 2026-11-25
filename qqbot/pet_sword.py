"""宠物冒险：把锻造出来的剑交给宠物，闯一座 40 层的位面塔。

规则照 ``config/宠物冒险系统.txt``，内容表在 ``pet_sword_data.py``。要点：

* **剑从锻造来**：``forge_new.NewForge`` 收工回调 ``record_forge`` 把这一把
  （刀型 / 图案 / 三围 / 磨损 / 价值）登记进剑库。银币照旧全额进余额，
  剑是**额外**留下的装备，剑库落盘 ``data/pet_swords_official.json``。
* **肉鸽结构**：8 个位面 × 5 层 = 40 层。每层刷 2~3 条分支，每条分支都是
  明码标价的（面板上直接写“这条路会碰到什么怪 / 什么事件”）；有的分支只给
  打怪和精英，有的才有休整和事件 —— 走哪条自己挑。
* **战斗**：宠物（大肥鱼）用剑的锋锐出招，招式（次元鲸斩 / 曼巴鲸肘……）
  靠事件与商店获得；怪物也有自己的招式，面板会提前写出它的「意图」。
* **道具 / 遗物**：道具栏只有 **2 格**，满了必须**丢弃或替换**；遗物是常驻
  被动（可能带负面），面板上逐条写清效果。两者都有说明、是否一次性。
* **锋利度**：剑不再是“每砍一刀掉一点”，而是**每打完一场掉一截**
  （普通 4 / 精英 6 / 首领 10，养成和遗物能减），掉到 0 就卷刃、伤害腰斩；
  休整节点可以免费磨刀 —— 一局下来大约磨 1~3 次刀。
* **局外养成**：鲸鳞落盘，能在「宠物 养成」里永久升级（生命 / 攻击 /
  护刃 / 起手 / 慧眼 / 鲸息），下一局生效。
* **面板**：和锻造同一套 ``panel.py`` 机制 —— 每个面板带 id + 序号，
  一条面板只能点一次，点旧的回「这条面板已经用过了」；按钮只签给唤出面板的人。

存档（每人一份，落在 ``data/pet_swords_official.json``）：:

    sword        剑库 + 装备
    runs/coins/best   战迹
    meta         {"points": 鲸鳞, "upgrades": {"hp": 0, ...}}
    run          正在打的那一趟（有就说明没打完，重启也还在）
"""
from __future__ import annotations

import math

from .base import *  # noqa: F401,F403
from .forge_new import PATTERN_MULTIPLIER, wear_grade
from .pet_sword_data import (
    CHALLENGE_BOSSES,
    CHALLENGE_BY_KEY,
    CHALLENGE_SCALES,
    COINS_TO_SCALES,
    EFFECT_ATK,
    EFFECT_ATK_FLAT,
    EFFECT_COINS,
    EFFECT_DAMAGE,
    EFFECT_HEAL,
    EFFECT_ITEM,
    EFFECT_MAX_HP,
    EFFECT_MOVE,
    EFFECT_RELIC,
    EFFECT_SHARP,
    EFFECT_SHARP_MAX,
    EFFECT_TOUGH,
    EVENTS,
    EXCHANGE_ITEMS,
    EXCHANGE_SILVER_BONUS,
    EXCHANGE_SILVER_COSTS,
    EXCHANGE_SILVER_KEY,
    EXCHANGE_SILVER_NAME,
    FLOORS_PER_PLANE,
    ITEMS,
    KIND_BOSS,
    KIND_ELITE,
    KIND_NORMAL,
    MAX_PLANES,
    META_UPGRADES,
    MOVES,
    PLANES,
    RELICS,
    REWARD_DEATH_RATE,
    SAVE_SLOTS,
    SCALES_PER_BOSS,
    SCALES_PER_CLEAR,
    SCALES_PER_FLOOR,
    Item,
    Move,
    Option,
    challenge_boss,
    exchange_silver_bonus,
    item_line,
    loot_coins,
    monster_for,
    move_intent,
    plane_of,
    random_item,
    random_move,
    random_relic,
    stats_for,
    upgrade_cost,
)

# --------------------------------------------------------------------------
# 常量
# --------------------------------------------------------------------------

SWORD_FILE = "pet_swords_official.json"
SWORD_LOG = "[宠物冒险]"

# 面板按钮的 data：冒险 <面板id> <面板序号> <动作> [参数]
PANEL_PREFIX = "冒险"
COMMANDS = (
    "宠物 冒险", "宠物冒险", "冒险面板",
    "宠物 剑库", "宠物剑库", "剑库",
    "宠物 养成", "宠物养成", "养成",
    "宠物 挑战", "宠物挑战", "哦鲸鲸大挑战", "大挑战",
    "宠物 兑换", "宠物兑换", "鲸鳞兑换", "兑换",
)
LIBRARY_COMMANDS = ("宠物 剑库", "宠物剑库", "剑库")
META_COMMANDS = ("宠物 养成", "宠物养成", "养成")
CHALLENGE_COMMANDS = ("宠物 挑战", "宠物挑战", "哦鲸鲸大挑战", "大挑战")
EXCHANGE_COMMANDS = ("宠物 兑换", "宠物兑换", "鲸鳞兑换", "兑换")

ACT_MAP = "板"          # 回本局面板
ACT_LIBRARY = "库"      # 剑库
ACT_BAG = "囊"          # 行囊（道具 / 遗物 / 招式说明）
ACT_META = "养"         # 局外养成
ACT_UPGRADE = "升"      # 买一级养成（参数：升级 key）
ACT_ROUTE = "路"        # 选一条分支（参数：序号）
ACT_START = "始"        # 开新的一趟
ACT_QUIT = "收"         # 收工（结算本局）
ACT_MOVE = "招"         # 用招式（参数：招式名）
ACT_PLAIN = "普"        # 普通攻击
ACT_GUARD = "守"        # 防守
ACT_ITEM = "用"         # 用道具（参数：行囊序号）
ACT_FLEE = "跑"         # 撤退
ACT_EVENT = "选"        # 事件选项（参数：序号）
ACT_REST = "休"         # 休整选项（参数：0 睡觉 / 1 磨刀）
ACT_BUY = "买"          # 商店购买（参数：序号）
ACT_TAKE = "取"         # 战利品三选一（参数：序号）
ACT_DROP = "丢"         # 替换时丢掉新东西
ACT_SWAP = "换"         # 替换（参数：旧槽位序号）
ACT_BACK = "退"         # 返回上一层面板
ACT_EQUIP = "佩"        # 剑库换剑（参数：剑 id）
ACT_CHALLENGE = "战"    # 打开「哦鲸鲸大挑战」
ACT_CHALLENGE_SLOT = "挑"   # 用某个存档开挑战（参数：栏位）
ACT_SAVE = "存"         # 通关后存进某个栏位（参数：栏位）
ACT_SAVE_REPLACE = "替"  # 覆盖已有存档
ACT_SAVE_CANCEL = "否"   # 取消覆盖
ACT_NO_SAVE = "罢"      # 不存档
ACT_EXCHANGE = "兑"     # 打开鲸鳞兑换
ACT_BUY_EXCHANGE = "购"  # 买兑换道具（参数：序号）
ACT_BUY_SILVER = "财"    # 升级「启程资金」

ID_ALPHABET = "23456789abcdefghjkmnpqrstuvwxyz"
ID_LENGTH = 6
MAX_SWORDS = 24
SHOW_SWORDS = 10
SHOW_PER_ROW = 4
CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩"

ITEM_SLOTS = 2          # 道具栏只有两个格子，多的必须丢或换
MOVE_SLOTS = 4          # 招式栏四个

SESSION_TTL = 2 * 60 * 60

NO_PANEL_REPLY = "这张面板翻篇了，发「宠物 冒险」重新唤一张吧。"
STALE_REPLY = "这条面板已经用过了，看最新那条吧。"
NO_SWORD_REPLY = "剑库还是空的。先发「锻造」做一把剑 —— 收工后它会自己进剑库。"

# 战斗里每次行动最多展示几个招式按钮（面板最多 5 行，留一行给道具/撤退）
SHOW_MOVES = MOVE_SLOTS

# 节点分支的几种“排布”。权重越大越常出现。
# 注意：这决定了“不是每层都一定有休整/事件”—— 打怪层就只有怪和精英。
LAYOUTS = (
    ("mixed", 0.42, ("战斗", "事件", "休整", "商店", "宝藏")),
    ("fight", 0.26, ("战斗", "精英")),
    ("elite", 0.10, ("精英", "战斗")),
    ("rest", 0.14, ("休整", "事件")),
    ("shop", 0.08, ("商店", "宝藏")),
)

# 战斗手感
DAMAGE_SPREAD = 0.2
ENEMY_DEFENSE_RATE = 0.45
GUARD_BASE = 8
BLEED_DAMAGE = 3

# 剑的锋利度：每场战斗掉多少（普通 / 精英 / 首领）
SHARP_COST = {"战斗": 4, "精英": 6, "首领": 10}
SHARP_COST_FLEE = 2
SHARP_COST_DEATH = 3
BLUNT_ATTACK_RATE = 0.6      # 卷刃（锋利度 0）时攻击只剩六成

# 磨刀：每点 3 银币，最少 30
SHARPEN_PER_POINT = 3
SHARPEN_MIN_COST = 30
SHARPEN_RELIC_DISCOUNT = 30      # 磨刀匠指环 -30%

# 银币 / 鲸鳞
COINS_DEATH_RATE = 0.5

# 休整：回最大生命的 35%（至少 35 点），潮汐罗盘再 +10
REST_HEAL_RATIO = 35
REST_HEAL_FLOOR = 35
REST_HEAL_RELIC = 10

# 副本里银币只在收工时统一进钱包（避免每场刷屏）

# 闲话
BATTLE_OPEN_FLAVOR = (
    "它先动的，我后发制人。",
    "水忽然安静下来，我知道要开打了。",
    "我把剑换了个握法，尾巴尖绷紧。",
)
VICTORY_FLAVOR = (
    "它沉下去了，我甩了甩剑上的水。",
    "喘了两口，还行，没伤到骨头。",
    "这一架打得值，回去得好好磨磨刀。",
)


# --------------------------------------------------------------------------
# 纯函数：数值换算（自检好测，面板和战斗共用一套口径）
# --------------------------------------------------------------------------


def pattern_bonus(pattern: str) -> float:
    """图案倍率 → 锋锐加成（0.8 ~ 1.57），开方是为了不让一件图案顶十件。"""
    multiplier = float(PATTERN_MULTIPLIER.get(pattern, 1.0))
    return 0.8 + 0.2 * math.sqrt(max(multiplier, 0.01))


def attack_of(sword: dict) -> int:
    """锋锐：0.6×强度 + 0.4×硬度，再乘图案加成。"""
    strength = int(sword["attrs"][0])
    hardness = int(sword["attrs"][1])
    value = (0.6 * strength + 0.4 * hardness) * pattern_bonus(str(sword["pattern"]))
    return max(1, int(round(value)))


def toughness_of(sword: dict) -> int:
    """坚韧：韧性 × 磨损倍率（崭新 ×1.15，战痕 ×0.85）。"""
    _, multiplier = wear_grade(float(sword.get("wear") or 0.0))
    return max(1, int(round(int(sword["attrs"][2]) * multiplier)))


def sharp_cap(multiplier: float) -> int:
    """锋利度上限：崭新出厂 100，战痕累累 50。"""
    span = float(multiplier) - 0.85
    return int(round(min(max(50 + 50 * span / 0.30, 50), 100)))


def hero_hp_base(toughness: int, pet_level: int, meta_hp: int = 0) -> int:
    """血量底子：26 + 坚韧的一半 + 每级 2 点 + 养成「硬鳞」8 点/级。"""
    return 26 + int(toughness) // 2 + 2 * int(pet_level) + 8 * int(meta_hp)


def guard_block(toughness: int, meta_block: int = 0) -> int:
    """防守的格挡值：8 + 坚韧的一半 + 养成「鲸息」4 点/级。"""
    return GUARD_BASE + int(toughness) // 2 + 4 * int(meta_block)


def enemy_defense(attack: int) -> int:
    return int(round(int(attack) * ENEMY_DEFENSE_RATE))


def sharp_cost(kind: str, blade_level: int = 0) -> int:
    """打完一场掉多少锋利度；养成「护刃」每级 -8%。"""
    base = SHARP_COST.get(kind, SHARP_COST["战斗"])
    return max(1, int(round(base * (1 - 0.08 * max(0, int(blade_level))))))


def sharpen_cost(missing: int, relics=(), keep_sharp: bool = False) -> int:
    """磨刀价格：每点 3 银币，最少 30；有「磨刀匠指环」打七折。"""
    value = max(SHARPEN_MIN_COST, int(missing) * SHARPEN_PER_POINT)
    if "磨刀匠指环" in set(relics):
        value = int(round(value * (1 - SHARPEN_RELIC_DISCOUNT / 100)))
    return value


def sword_name(sword: dict) -> str:
    knife = str(sword.get("knife") or "剑")
    pattern = str(sword.get("pattern") or "").strip()
    return f"{knife} · {pattern}" if pattern else knife


def plane_title(plane: int, floor: int) -> str:
    """「位面3 · 锈铁深渊 · 第2层」。"""
    entry = plane_of(plane)
    return f"位面{int(plane)} · {entry.name} · 第{int(floor)}层"


def circled(index: int) -> str:
    return CIRCLED[index] if 0 <= index < len(CIRCLED) else f"{index + 1}."


# --------------------------------------------------------------------------
# 面板按钮的 data
# --------------------------------------------------------------------------


def sword_panel_data(panel_id: str, seq: int, action: str,
                     argument: str = "") -> str:
    parts = [PANEL_PREFIX, panel_id, str(seq), action]
    if argument:
        parts.append(argument)
    return " ".join(parts)


def parse_sword_data(text: str) -> tuple[str, int, str, str] | None:
    parts = (text or "").strip().split()
    if len(parts) < 4 or parts[0] != PANEL_PREFIX:
        return None
    try:
        seq = int(parts[2])
    except (TypeError, ValueError):
        return None
    return parts[1], seq, parts[3], (parts[4] if len(parts) > 4 else "")


# --------------------------------------------------------------------------
# 会话
# --------------------------------------------------------------------------


@dataclass
class Panel:
    """一个人的面板会话：面板 id + 序号。"""

    panel_id: str
    group: str
    user: str
    name: str = ""
    seq: int = 0
    started_at: float = 0.0
    # 刚结束的一局结算（只在内存里；刷新面板用，重启就没了）
    end: dict | None = None
    # 通关后待存的快照 / 正在确认覆盖的栏位
    save_snapshot: dict | None = None
    save_confirm: int | None = None


# --------------------------------------------------------------------------
# 剑库 + 冒险
# --------------------------------------------------------------------------


class SwordAdventure:
    """剑库、肉鸽进程、局外养成。剑库与进度落盘 ``data/pet_swords_official.json``。"""

    def __init__(self, data_dir: Path, cards, pets,
                 filename: str = SWORD_FILE) -> None:
        self.data_dir = Path(data_dir)
        self._cards = cards if callable(cards) else (lambda: cards)
        self._pets = pets if callable(pets) else (lambda: pets)
        self.path = self.data_dir / filename
        self._users = self._load()
        self._panels: dict[tuple[str, str], Panel] = {}
        self.rng = random

    @property
    def cards(self):
        return self._cards()

    @property
    def pets(self):
        return self._pets()

    # ==================================================================
    # 存档
    # ==================================================================

    def _load(self) -> dict[str, dict]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            return {}
        if not isinstance(payload, dict):
            return {}
        return {str(key): value for key, value in payload.items()
                if isinstance(value, dict)}

    def _save(self) -> None:
        temporary = self.path.with_name("pet_swords.tmp")
        try:
            temporary.write_text(
                json.dumps(self._users, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            temporary.replace(self.path)
        except OSError as error:
            log(f"{SWORD_LOG} 存档保存失败：{error}")

    def user(self, user_id: str) -> dict:
        record = self._users.setdefault(
            str(user_id),
            {"swords": {}, "equipped": "", "runs": 0, "coins": 0, "best": 0,
             "meta": {"points": 0, "upgrades": {}}, "run": None,
             "saves": [None] * SAVE_SLOTS, "pending_save": None,
             "vault": {"items": {}, "silver": 0}},
        )
        for key, default in (("swords", {}), ("equipped", ""), ("runs", 0),
                             ("coins", 0), ("best", 0), ("run", None),
                             ("pending_save", None)):
            record.setdefault(key, default)
        vault = record.setdefault("vault", {})
        if not isinstance(vault, dict):
            vault = record["vault"] = {}
        vault.setdefault("items", {})
        vault.setdefault("silver", 0)
        saves = record.setdefault("saves", [])
        while len(saves) < SAVE_SLOTS:
            saves.append(None)
        if len(saves) > SAVE_SLOTS:
            del saves[SAVE_SLOTS:]
        meta = record.setdefault("meta", {})
        if not isinstance(meta, dict):
            meta = record["meta"] = {}
        meta.setdefault("points", 0)
        upgrades = meta.setdefault("upgrades", {})
        if not isinstance(upgrades, dict):
            upgrades = meta["upgrades"] = {}
        for upgrade in META_UPGRADES.values():
            upgrades.setdefault(upgrade.key, 0)
        return record

    def exists(self, user_id: str) -> bool:
        return str(user_id) in self._users

    # ---- 剑库 ----
    def swords_of(self, user_id: str) -> list[dict]:
        swords = list(self.user(user_id)["swords"].values())
        return sorted(
            swords,
            key=lambda sword: (attack_of(sword), int(sword.get("value") or 0)),
            reverse=True,
        )

    def equipped_sword(self, user_id: str) -> dict | None:
        record = self.user(user_id)
        swords = record["swords"]
        sword = swords.get(str(record.get("equipped") or ""))
        if sword is None and swords:
            sword = max(swords.values(), key=attack_of)
            record["equipped"] = str(sword["id"])
            self._save()
        return dict(sword) if sword else None

    def _set_sword_sharp(self, user: str, sword_id: str, sharp: int) -> int:
        record = self.user(user)
        sword = record["swords"].get(str(sword_id))
        if sword is None:
            return max(0, int(sharp))
        cap = int(sword.get("sharp_max") or 100)
        value = max(0, min(int(sharp), cap))
        sword["sharp"] = value
        self._save()
        return value

    def _new_id(self, existing) -> str:
        taken = set(existing)
        for _ in range(50):
            value = "".join(self.rng.choice(ID_ALPHABET) for _ in range(ID_LENGTH))
            if value not in taken:
                return value
        return f"{int(time.time() * 1000) % 10 ** 8:08x}"

    def record_forge(self, session, score: int, value: int) -> dict | None:
        """``NewForge`` 收工回调：把这一把登记进剑库。"""
        user = str(getattr(session, "user", "") or "")
        knife = str(getattr(session, "knife", "") or "")
        pattern = str(getattr(session, "pattern", "") or "")
        attrs = list(getattr(session, "attrs", []) or [])
        if not user or not knife or not pattern or len(attrs) != 3:
            return None
        wear = float(getattr(session, "wear", 0.0) or 0.0)
        grade, multiplier = wear_grade(wear)
        cap = sharp_cap(multiplier)
        record = self.user(user)
        material = getattr(session, "material", None)
        sword = {
            "id": self._new_id(list(record["swords"])),
            "knife": knife,
            "pattern": pattern,
            "material": str(getattr(material, "name", "") or ""),
            "attrs": [int(attr) for attr in attrs],
            "score": int(score),
            "value": int(value),
            "wear": round(wear, 3),
            "grade": grade,
            "sharp": cap,
            "sharp_max": cap,
            "forged_at": int(time.time()),
        }
        record["swords"][sword["id"]] = sword
        overflow = len(record["swords"]) - MAX_SWORDS
        if overflow > 0:
            spare = [item for item in record["swords"].values()
                     if item["id"] != record.get("equipped")]
            spare.sort(key=lambda item: int(item.get("value") or 0))
            for item in spare[:overflow]:
                record["swords"].pop(item["id"], None)
                payout = max(1, int(item.get("value") or 0) // 2)
                self.cards.grant_shards(user, payout)
                log(f"{SWORD_LOG} {user[:8]}… 剑库满了，{item['knife']}折成 {payout} 银币")
        if not record.get("equipped") or record["equipped"] not in record["swords"]:
            record["equipped"] = sword["id"]
        self._save()
        log(f"{SWORD_LOG} {user[:8]}… 入库：{knife}·{pattern}"
            f"（锋锐 {attack_of(sword)}，锋利度 {cap}）")
        return sword

    # ==================================================================
    # 面板会话
    # ==================================================================

    @staticmethod
    def _key(group: str, user: str) -> tuple[str, str]:
        return (str(group or ""), str(user or ""))

    def panel_state(self, group: str, user: str, name: str = "") -> Panel:
        key = self._key(group, user)
        state = self._panels.get(key)
        if state is None or time.time() - state.started_at > SESSION_TTL:
            state = Panel(
                panel_id=self._new_id([p.panel_id for p in self._panels.values()]),
                group=key[0], user=key[1],
                name=str(name or "").strip() or "群友",
                started_at=time.time(),
            )
            self._panels[key] = state
        elif name:
            state.name = str(name).strip() or state.name
        return state

    def active(self, group: str, user: str) -> Panel | None:
        return self._panels.get(self._key(group, user))

    def clear(self) -> None:
        self._panels.clear()

    # ==================================================================
    # 对外：认命令 / 处理按钮
    # ==================================================================

    @staticmethod
    def recognizes(text: str) -> bool:
        text = (text or "").strip()
        return text in COMMANDS or parse_sword_data(text) is not None

    def handle(self, text: str, group: str, user: str, name: str = "") -> dict:
        text = (text or "").strip()
        parsed = parse_sword_data(text)
        if parsed is not None:
            panel_id, seq, action, argument = parsed
            return self._act(group, user, panel_id, seq, action, argument)
        state = self.panel_state(group, user, name)
        if text in LIBRARY_COMMANDS:
            return self._library(state)
        if text in META_COMMANDS:
            return self._meta(state)
        if text in CHALLENGE_COMMANDS:
            return self._challenge(state)
        if text in EXCHANGE_COMMANDS:
            return self._exchange(state)
        return self._home(state)

    # ==================================================================
    # 动作分发
    # ==================================================================

    def _act(self, group: str, user: str, panel_id: str, seq: int,
             action: str, argument: str, name: str = "") -> dict:
        state = self._panels.get(self._key(group, user))
        if state is None:
            return self._say(NO_PANEL_REPLY)
        if state.panel_id != panel_id or state.seq != seq:
            return self._say(STALE_REPLY)
        if action == ACT_LIBRARY:
            return self._library(state)
        if action == ACT_META:
            return self._meta(state)
        if action == ACT_BAG:
            return self._bag(state)
        if action == ACT_BACK:
            return self._home(state)
        if action == ACT_EQUIP:
            return self._equip(state, argument)
        if action == ACT_CHALLENGE:
            return self._challenge(state)
        if action == ACT_CHALLENGE_SLOT:
            return self._start_challenge(state, argument)
        if action == ACT_SAVE:
            return self._save_choose(state, argument)
        if action == ACT_SAVE_REPLACE:
            return self._save_replace(state)
        if action == ACT_SAVE_CANCEL:
            return self._save_cancel(state)
        if action == ACT_NO_SAVE:
            return self._no_save(state)
        if action == ACT_EXCHANGE:
            return self._exchange(state)
        if action == ACT_BUY_EXCHANGE:
            return self._buy_exchange(state, argument)
        if action == ACT_BUY_SILVER:
            return self._buy_silver(state)
        run = self._run(state.user)
        if action == ACT_START:
            return self._start_run(state)
        if run is None:
            if action == ACT_UPGRADE:
                return self._buy_upgrade(state, None, argument)
            return self._say("现在没有正在进行的冒险，发「宠物 冒险」开一趟吧。")
        handler = {
            ACT_MAP: self._home,
            ACT_ROUTE: self._route,
            ACT_PLAIN: lambda s, r, a: self._move(s, r, "挥剑"),
            ACT_MOVE: self._move,
            ACT_GUARD: self._guard,
            ACT_ITEM: self._use_item,
            ACT_FLEE: self._flee,
            ACT_EVENT: self._event_option,
            ACT_REST: self._rest_option,
            ACT_BUY: self._buy,
            ACT_TAKE: self._take_reward,
            ACT_DROP: self._replace_drop,
            ACT_SWAP: self._replace_swap,
            ACT_QUIT: self._quit,
            ACT_UPGRADE: self._buy_upgrade,
        }.get(action)
        if handler is None:
            return self._say(STALE_REPLY)
        return handler(state, run, argument)

    # ---- 面板刷新 ----
    def _reply(self, text: str) -> dict:
        return {"ok": False, "panel": None, "reply": text}

    def _say(self, text: str) -> dict:
        return self._reply(text)

    def _panel(self, state: Panel, run: dict | None = None) -> dict:
        """按当前模式渲染面板，序号 +1。"""
        state.seq += 1
        run = self._run(state.user) if run is None else run
        if run is None:
            record = self.user(state.user)
            if not state.save_snapshot and record.get("pending_save"):
                state.save_snapshot = record["pending_save"]
            if state.save_snapshot:
                if state.save_confirm is not None:
                    return self._save_confirm_panel(state)
                return self._save_panel(state)
            if state.end:
                return self._end_panel(state, state.end)
            return self._home_panel(state)
        mode = run.get("mode") or "map"
        if mode == "battle":
            return self._battle_panel(state, run)
        if mode == "event":
            return self._event_panel(state, run)
        if mode == "rest":
            return self._rest_panel(state, run)
        if mode == "shop":
            return self._shop_panel(state, run)
        if mode == "reward":
            return self._reward_panel(state, run)
        if mode == "replace":
            return self._replace_panel(state, run)
        if mode == "end":
            return self._end_panel(state, run)
        return self._map_panel(state, run)

    def _data(self, state: Panel, action: str, argument: str = "") -> str:
        return sword_panel_data(state.panel_id, state.seq, action, argument)

    # ==================================================================
    # 局外养成 / 剑库
    # ==================================================================

    def _meta(self, state: Panel) -> dict:
        state.seq += 1
        return {"ok": True, "panel": self._meta_panel(state), "reply": ""}

    def _meta_panel(self, state: Panel) -> dict:
        record = self.user(state.user)
        meta = record["meta"]
        levels = meta["upgrades"]
        lines = [
            "## 宠物冒险 · 局外养成",
            f"鲸鳞 **{int(meta['points'])}**（每通一层 +{SCALES_PER_FLOOR}，"
            f"首领 +{SCALES_PER_BOSS}，通关 +{SCALES_PER_CLEAR}）",
            "升级永久生效，下一趟冒险开始算。",
        ]
        pairs = []
        for upgrade in META_UPGRADES.values():
            level = int(levels.get(upgrade.key) or 0)
            cost = upgrade_cost(upgrade, level)
            if cost:
                state_text = f"Lv.{level}/{len(upgrade.costs)} · 升一级 {cost} 鲸鳞"
                pairs.append((upgrade.name, self._data(state, ACT_UPGRADE, upgrade.key)))
            else:
                state_text = f"Lv.{level}/{len(upgrade.costs)} · 已满级"
            lines.append(f"**{upgrade.name}**：{upgrade.desc} —— {state_text}")
        rows = [pairs[index:index + 2] for index in range(0, len(pairs), 2)]
        rows.append([("返回", self._data(state, ACT_BACK))])
        return {"text": "\n".join(lines), "rows": rows}

    def _buy_upgrade(self, state: Panel, run: dict | None,
                     argument: str) -> dict:
        record = self.user(state.user)
        meta = record["meta"]
        upgrade = META_UPGRADES.get(argument)
        if upgrade is None:
            return self._say(STALE_REPLY)
        levels = meta["upgrades"]
        level = int(levels.get(upgrade.key) or 0)
        cost = upgrade_cost(upgrade, level)
        if not cost:
            return self._say(f"「{upgrade.name}」已经满级了。")
        points = int(meta.get("points") or 0)
        if points < cost:
            return self._say(
                f"「{upgrade.name}」升一级要 {cost} 鲸鳞，你只有 {points}。"
                "再通几层吧。"
            )
        meta["points"] = points - cost
        levels[upgrade.key] = level + 1
        self._save()
        state.seq += 1
        panel = self._meta_panel(state)
        panel["text"] = (f"「{upgrade.name}」升到 Lv.{level + 1}，"
                         f"花了 {cost} 鲸鳞。\n\n" + panel["text"])
        return {"ok": True, "panel": panel, "reply": ""}

    def _library(self, state: Panel, lead: str = "") -> dict:
        state.seq += 1
        return {"ok": True, "panel": self._library_panel(state, lead), "reply": ""}

    def _library_panel(self, state: Panel, lead: str = "") -> dict:
        record = self.user(state.user)
        swords = self.swords_of(state.user)
        equipped = str(record.get("equipped") or "")
        lines = ["## 宠物冒险 · 剑库"]
        if lead:
            lines.append(lead)
        if not swords:
            lines.append(NO_SWORD_REPLY)
        else:
            for index, sword in enumerate(swords[:SHOW_SWORDS]):
                mark = "（手里这把）" if sword["id"] == equipped else ""
                lines.append(
                    f"{circled(index)}{sword['knife']} · {sword['pattern']} — "
                    f"锋锐 {attack_of(sword)} · 锋利度 "
                    f"{int(sword.get('sharp') or 0)}/{int(sword.get('sharp_max') or 0)}"
                    f"{mark}"
                )
            if len(swords) > SHOW_SWORDS:
                lines.append(f"还有 {len(swords) - SHOW_SWORDS} 把没列出来"
                             f"（剑库最多留 {MAX_SWORDS} 把）。")
        pairs = []
        for index, sword in enumerate(swords[:SHOW_SWORDS]):
            label = f"{circled(index)}{sword['knife']}"
            pairs.append((label, self._data(state, ACT_EQUIP, str(sword["id"]))))
        rows = [pairs[index:index + SHOW_PER_ROW]
                for index in range(0, len(pairs), SHOW_PER_ROW)]
        rows = rows[:4]
        rows.append([("返回", self._data(state, ACT_BACK)),
                     ("养成", self._data(state, ACT_META))])
        return {"text": "\n".join(lines), "rows": rows}

    def _equip(self, state: Panel, sword_id: str) -> dict:
        """剑库换剑。本局已经开打的话，这一趟仍然用开局那把（不中途换武器）。"""
        record = self.user(state.user)
        if sword_id not in record["swords"]:
            return self._say("剑库里没这一把，可能已经折成银币了。")
        record["equipped"] = sword_id
        self._save()
        sword = record["swords"][sword_id]
        lead = f"换上了 **{sword_name(sword)}**（锋锐 {attack_of(sword)}）。"
        if record.get("run"):
            lead += "（本局已经开打，这一趟还是用开局那把剑）"
        return self._library(state, lead)

    # ==================================================================
    # 主面板 / 本局地图
    # ==================================================================

    def _home(self, state: Panel) -> dict:
        """回主面板：有局就回局内，没局就回首页；顺手清掉结算画面。

        但如果还有「通关待存档」没处理，结算信息要留着 —— 不然「不保存」之后
        就看不到这一趟的结算了。
        """
        record = self.user(state.user)
        if not state.save_snapshot and not record.get("pending_save"):
            state.end = None
        state.save_confirm = None
        state.seq += 1
        return {"ok": True, "panel": self._panel(state), "reply": ""}

    def _home_panel(self, state: Panel) -> dict:
        record = self.user(state.user)
        meta = record["meta"]
        sword = self.equipped_sword(state.user)
        snapshot = self.pets.snapshot(state.user)
        pet = snapshot["record"]
        lines = ["## 宠物冒险 · 出征准备"]
        if sword is None:
            lines.append(NO_SWORD_REPLY)
        else:
            lines.append(f"**{sword_name(sword)}**（{sword.get('grade') or '未知'}）")
            lines.append(
                f"锋锐 {attack_of(sword)} · 坚韧 {toughness_of(sword)} · "
                f"锋利度 {int(sword.get('sharp') or 0)}/{int(sword.get('sharp_max') or 0)}"
            )
        lines.append(
            f"宠物 Lv.{int(pet['level'])} · 体力 {int(pet['stamina'])}"
            f"/{snapshot['stamina_max']} · 心情 {int(pet['mood'])}"
            f"/{snapshot['mood_max']}"
        )
        lines.append(
            f"战迹：出征 {int(record.get('runs') or 0)} 次"
        )
        vault = record.get("vault") or {}
        silver_level = int(vault.get("silver") or 0)
        stash = vault.get("items") or {}
        if silver_level or stash:
            lines.append(
                f"启程资金 Lv.{silver_level}"
                f"（开局 +{exchange_silver_bonus(silver_level)} 局内银币）"
                + (f" · 仓库 {sum(int(n) for n in stash.values())} 件" if stash else "")
            )
        lines.append(f"鲸鳞 **{int(meta.get('points') or 0)}** · 位面塔共 "
                     f"{MAX_PLANES} 个位面 × {FLOORS_PER_PLANE} 层")
        saves = record.get("saves") or []
        used = sum(1 for item in saves if isinstance(item, dict))
        lines.append(f"存档 {used}/{SAVE_SLOTS} · 「哦鲸鲸大挑战」用通关存档挑战三位首领")
        if not sword:
            lines.append("先去「锻造」做一把剑，再回来开塔。")
        else:
            lines.append("一趟从位面1的第1层开始，走到底要穿过 8 个位面。")
        rows = [
            [("出发", self._data(state, ACT_START)),
             ("剑库", self._data(state, ACT_LIBRARY)),
             ("养成", self._data(state, ACT_META))],
            [("大挑战", self._data(state, ACT_CHALLENGE)),
             ("兑换", self._data(state, ACT_EXCHANGE))],
            [("宠物面板", "宠物面板")],
        ]
        return {"text": "\n".join(lines), "rows": rows}

    def _map_panel(self, state: Panel, run: dict) -> dict:
        lines = [
            f"## {plane_title(run['plane'], run['floor'])}",
            self._status_line(run),
        ]
        if run.get("note"):
            lines.append(f"> {run['note']}")
        lines.append(self._bag_line(run))
        lines.append("**选一条路**（每条路会碰到什么写在下面）：")
        pairs = []
        for index, node in enumerate(run.get("options") or []):
            lines.append(f"{circled(index)}{node['detail']}")
            pairs.append((f"{circled(index)}{node['label']}",
                          self._data(state, ACT_ROUTE, str(index))))
        rows = [pairs] if pairs else []
        rows.append([("行囊", self._data(state, ACT_BAG)),
                     ("养成", self._data(state, ACT_META))])
        rows.append([("收工", self._data(state, ACT_QUIT))])
        return {"text": "\n".join(lines), "rows": rows}

    def _status_line(self, run: dict) -> str:
        return (
            f"HP **{int(run['hp'])}/{int(run['hp_max'])}** · "
            f"锋锐 {int(self._attack_power(run))} · "
            f"锋利度 {int(run['sharp'])}/{int(run.get('sharp_max') or 0)}"
            f"{'（卷刃）' if int(run['sharp']) <= 0 else ''} · "
            f"鲸鳞 {int(run.get('scales') or 0)} · 本局银币 {int(run.get('coins') or 0)}"
        )

    def _bag_line(self, run: dict, full: bool = False) -> str:
        """道具 / 遗物 / 招式的一行摘要（``full`` 时带完整说明）。"""
        items = [ITEMS[name] for name in run.get("items") or [] if name in ITEMS]
        relics = [RELICS[name] for name in run.get("relics") or [] if name in RELICS]
        moves = [MOVES[name] for name in run.get("moves") or [] if name in MOVES]
        parts = []
        if items:
            if full:
                for index, item in enumerate(items):
                    parts.append(f"{circled(index)}{item_line(item)}")
            else:
                parts.append("道具（{}/{}）：{}".format(
                    len(items), ITEM_SLOTS,
                    " · ".join(item.name for item in items)))
        else:
            parts.append(f"道具（0/{ITEM_SLOTS}）：空")
        if relics:
            if full:
                for relic in relics:
                    parts.append(f"遗物：**{relic.name}** —— {relic.desc}")
            else:
                parts.append("遗物：" + " · ".join(relic.name for relic in relics))
        else:
            parts.append("遗物：无")
        if moves:
            parts.append("招式：" + " · ".join(self._move_tag(run, move) for move in moves))
        else:
            parts.append("招式：还没有学会（事件和商店能学）")
        return "\n".join(parts)

    def _move_tag(self, run: dict, move: Move) -> str:
        cooldown = int(run.get("cooldowns", {}).get(move.name) or 0)
        return f"{move.name}（{'就绪' if cooldown <= 0 else f'冷却{cooldown}'}）"

    # ==================================================================
    # 开局 / 分支 / 层推进
    # ==================================================================

    def _start_run(self, state: Panel) -> dict:
        record = self.user(state.user)
        if record.get("run"):
            return {"ok": True, "panel": self._panel(state),
                    "reply": "上一趟还没走完，接着打。"}
        sword = self.equipped_sword(state.user)
        if sword is None:
            return self._say(NO_SWORD_REPLY)
        if int(sword.get("sharp") or 0) <= 0:
            return self._say(
                f"{sword['knife']}已经卷刃了（锋利度 0）。"
                "先去剑库磨刀，或者换一把。"
            )
        snapshot = self.pets.snapshot(state.user)
        pet = snapshot["record"]
        meta = record["meta"]
        upgrades = meta.get("upgrades") or {}
        level = int(pet.get("level") or 1)
        tough = toughness_of(sword)
        hp_base = hero_hp_base(tough, level, int(upgrades.get("hp") or 0))
        run = {
            "id": self._new_id([p.panel_id for p in self._panels.values()]),
            "sword_id": sword["id"],
            "sword_name": sword_name(sword),
            "plane": 1, "floor": 1, "floors_done": 0,
            "tough": tough,
            "base_attack": max(1, attack_of(sword)
                               + 2 * int(upgrades.get("atk") or 0)),
            "hp_base": hp_base, "hp": hp_base, "hp_max": hp_base,
            "sharp": int(sword["sharp"]), "sharp_max": int(sword["sharp_max"]),
            "moves": [], "cooldowns": {},
            "items": [], "relics": [],
            "coins": 0, "scales": 0,
            "atk_bonus": 0.0, "flat_atk": 0, "hp_flat": 0,
            "buffs": {}, "battle": None, "node": None,
            "options": [], "pending": None, "note": "", "mode": "map",
            "started_at": int(time.time()),
        }
        # 养成「起手」：开局多带道具
        for _ in range(int(upgrades.get("start") or 0)):
            item = random_item(self.rng)
            if item is not None and len(run["items"]) < ITEM_SLOTS:
                run["items"].append(item.name)
        self._refresh_max_hp(run)
        run["hp"] = run["hp_max"]
        run["owner"] = state.user
        # 鲸鳞兑换的「启程资金」：每趟开局就带一笔局内银币（商店、磨刀用）
        vault = record.get("vault") or {}
        run["coins"] = exchange_silver_bonus(int(vault.get("silver") or 0))
        # 仓库里的兑换道具：开局自动塞进道具栏（最多 2 格），用一件少一件
        stash = vault.get("items") or {}
        while len(run["items"]) < ITEM_SLOTS:
            name = next((key for key, count in stash.items()
                         if key in ITEMS and int(count or 0) > 0), None)
            if name is None:
                break
            run["items"].append(name)
            stash[name] = int(stash.get(name) or 0) - 1
            if stash[name] <= 0:
                stash.pop(name, None)
        if run["coins"]:
            run["note"] = f"启程资金：开局带着 {run['coins']} 局内银币"
        record["run"] = run
        state.panel_id = self._new_id([p.panel_id for p in self._panels.values()])
        state.end = None
        run["options"] = self._build_options(run)
        self._save()
        log(f"{SWORD_LOG} {state.name} 开局：{run['sword_name']}"
            f"（HP {run['hp_max']}，锋锐 {run['base_attack']}）")
        return {"ok": True, "panel": self._panel(state, run), "reply": ""}

    def _after_floor(self, state: Panel, run: dict) -> dict:
        """一层走完：记鲸鳞、进下一层，走完第 5 层就进下一个位面。"""
        run["floors_done"] = int(run.get("floors_done") or 0) + 1
        run["scales"] = int(run.get("scales") or 0) + SCALES_PER_FLOOR
        if int(run["floor"]) >= FLOORS_PER_PLANE:
            run["plane"] = int(run["plane"]) + 1
            run["floor"] = 1
        else:
            run["floor"] = int(run["floor"]) + 1
        run["options"] = []
        run["node"] = None
        run["battle"] = None
        run["pending"] = None
        run["mode"] = "map"
        if int(run["plane"]) > MAX_PLANES:
            snapshot = run.get("pre_boss") or self._snapshot(run)
            self._end_run(state, run, "clear")
            state.save_snapshot = snapshot
            record = self.user(state.user)
            record["pending_save"] = snapshot
            self._save()
            return {"ok": True, "panel": self._panel(state), "reply": ""}
        run["options"] = self._build_options(run)
        self._save()
        return {"ok": True, "panel": self._panel(state, run), "reply": ""}

    def _build_options(self, run: dict) -> list[dict]:
        """刷这一层的 2~3 条分支。分支类型有随机性：有的层只有打怪和精英。"""
        plane, floor = int(run["plane"]), int(run["floor"])
        if floor == FLOORS_PER_PLANE:
            return [self._battle_node(run, KIND_BOSS)]
        name, _, pool = self._pick_layout()
        count = self.rng.choice((2, 3))
        kinds: list[str] = []
        if name == "fight":
            kinds = ["战斗", "精英"]
            if count >= 3:
                kinds.append("战斗")
        elif name == "elite":
            kinds = ["精英", "战斗"]
        elif name == "rest":
            kinds = ["休整", "事件"]
        elif name == "shop":
            kinds = ["商店", "宝藏"]
        else:
            candidates = [kind for kind in pool]
            while len(kinds) < count and candidates:
                kind = self.rng.choice(candidates)
                kinds.append(kind)
                if kind in ("战斗", "精英"):
                    candidates = [c for c in candidates if c not in ("战斗", "精英")]
            if not kinds:
                kinds = ["战斗", "事件"]
        nodes = []
        for kind in kinds:
            if kind in ("战斗", "精英"):
                nodes.append(self._battle_node(run, kind))
            elif kind == "事件":
                nodes.append(self._event_node())
            elif kind == "休整":
                nodes.append({"kind": "休整", "label": "休整",
                              "detail": "休整：睡一觉回血，或免费磨刀"})
            elif kind == "商店":
                nodes.append(self._shop_node(run))
            else:
                nodes.append({"kind": "宝藏", "label": "宝藏",
                              "detail": "宝藏：随机开出一件道具或遗物"})
        return nodes

    def _pick_layout(self):
        roll = self.rng.random()
        total = 0.0
        for name, weight, pool in LAYOUTS:
            total += weight
            if roll < total:
                return name, weight, pool
        return LAYOUTS[0]

    def _battle_node(self, run: dict, kind: str) -> dict:
        plane, floor = int(run["plane"]), int(run["floor"])
        monster = monster_for(plane, kind, self.rng)
        stats = stats_for(monster, plane, floor, kind, self.rng)
        coins = loot_coins(plane, floor, kind, self.rng)
        if kind == KIND_BOSS:
            detail = (f"首领：{stats['name']}（HP {stats['hp']} · "
                      f"攻击 {stats['attack']}）→ 遗物 + 银币 + 鲸鳞")
        elif kind == KIND_ELITE:
            detail = (f"精英：{stats['name']}（HP {stats['hp']} · "
                      f"攻击 {stats['attack']}）→ 约 {coins} 银币 + 遗物")
        else:
            detail = (f"战斗：{stats['name']}（HP {stats['hp']} · "
                      f"攻击 {stats['attack']}）→ 约 {coins} 银币")
        return {"kind": kind, "label": kind, "detail": detail,
                "monster": stats, "coins": coins}

    def _event_node(self) -> dict:
        event = self.rng.choice(list(EVENTS.values()))
        first = event.options[0]
        return {
            "kind": "事件", "label": "事件",
            "detail": f"事件：{event.name} —— {first.detail}",
            "event": event.key,
        }

    def _shop_node(self, run: dict) -> dict:
        """商店：两件货 + 磨刀 / 治疗，价格随位面涨。"""
        plane = int(run["plane"])
        offers = []
        item = random_item(self.rng, tuple(run.get("items") or ()))
        relic = random_relic(self.rng, tuple(run.get("relics") or ()))
        move = random_move(self.rng, tuple(run.get("moves") or ()))
        meta = self.user(run.get("owner") or "").get("meta") or {}
        discount = 1 - 0.15 * int((meta.get("upgrades") or {}).get("shop") or 0)
        if item is not None:
            price = int(round((70 + 12 * plane) * discount))
            offers.append({"kind": "item", "name": item.name,
                           "detail": f"道具：{item_line(item)}", "price": price})
        if relic is not None and len(offers) < 3:
            price = int(round((210 + 26 * plane) * discount))
            offers.append({"kind": "relic", "name": relic.name,
                           "detail": f"遗物：**{relic.name}** —— {relic.desc}",
                           "price": price})
        if move is not None and len(offers) < 3:
            price = int(round((150 + 18 * plane) * discount))
            offers.append({"kind": "move", "name": move.name,
                           "detail": f"招式：**{move.name}** —— {move.desc}",
                           "price": price})
        offers.append({"kind": "sharpen", "name": "磨刀",
                       "detail": "磨刀：把剑磨回上限",
                       "price": None})
        return {"kind": "商店", "label": "商店",
                "detail": "商店：花本局银币买道具 / 遗物 / 招式，或磨刀",
                "offers": offers}

    # ==================================================================
    # 选路
    # ==================================================================

    def _route(self, state: Panel, run: dict, argument: str) -> dict:
        try:
            index = int(argument)
        except (TypeError, ValueError):
            return self._say(STALE_REPLY)
        options = run.get("options") or []
        if not 0 <= index < len(options):
            return self._say("这条路已经走过了，看看最新那条面板。")
        node = options[index]
        kind = node.get("kind")
        if kind in (KIND_NORMAL, KIND_ELITE, KIND_BOSS):
            return self._begin_battle(state, run, node)
        run["node"] = node
        run["note"] = ""
        if kind == "事件":
            run["mode"] = "event"
        elif kind == "休整":
            run["mode"] = "rest"
        elif kind == "商店":
            run["mode"] = "shop"
        else:                       # 宝藏
            run["mode"] = "reward"
            run["rewards"] = self._treasure_rewards(run)
            run["reward_kind"] = "宝藏"
        self._save()
        return {"ok": True, "panel": self._panel(state, run), "reply": ""}

    # ==================================================================
    # 战斗
    # ==================================================================

    def _begin_battle(self, state: Panel, run: dict, node: dict) -> dict:
        stats = node["monster"]
        battle = {
            "name": stats["name"], "kind": node["kind"],
            "hp": int(stats["hp"]), "hp_max": int(stats["hp_max"]),
            "attack": int(stats["attack"]),
            "moves": list(stats.get("moves") or []),
            "turn": 1, "block": 0, "bleed": 0, "player_bleed": 0,
            "first": True, "atk_buff": 0, "atk_buff_turns": 0,
            "enemy_debuff": 0, "enemy_debuff_turns": 0, "star": 0,
            "star_turns": 0, "loot": int(node.get("coins") or 0),
            "flavor": str(stats.get("flavor") or ""),
        }
        battle["intent"] = move_intent({"moves": battle["moves"]}, self.rng)
        run["battle"] = battle
        run["node"] = node
        if node.get("kind") == KIND_BOSS and int(run["plane"]) >= MAX_PLANES:
            # 通关存档要的是「打最后那个首领之前」的状态，这里先留一份
            run["pre_boss"] = self._snapshot(run)
        run["mode"] = "battle"
        run["note"] = ""
        # 开战被动：遗物 / 养成 / 道具
        notes = self._battle_start(run)
        run["note"] = "；".join(notes)
        self._save()
        return {"ok": True, "panel": self._panel(state, run), "reply": ""}

    def _battle_start(self, run: dict) -> list[str]:
        battle = run["battle"]
        relics = set(run.get("relics") or ())
        meta = self.user(run.get("owner") or "").get("meta") or {}
        upgrades = meta.get("upgrades") or {}
        notes = []
        block = 0
        if "回响鳞片" in relics:
            block += 6
        block += 4 * int(upgrades.get("block") or 0)
        if "命运硬币" in relics:
            if self.rng.random() < 0.5:
                block += 8
                notes.append("命运硬币：开战获得 8 格挡")
            else:
                battle["atk_buff"] = 15
                battle["atk_buff_turns"] = 99
                notes.append("命运硬币：开战攻击 +15%")
        if "血锈之刃" in relics:
            run["hp"] = max(1, int(run["hp"]) - 3)
            notes.append("血锈之刃：开战 -3 HP")
        battle["block"] = block
        if block:
            notes.append(f"开战获得 {block} 格挡")
        return notes

    def _battle_panel(self, state: Panel, run: dict) -> dict:
        battle = run["battle"]
        intent = battle.get("intent") or {}
        flavor = battle.get("flavor") or ""
        lines = [
            f"## 战斗 · {battle['name']}（{plane_title(run['plane'], run['floor'])}）",
            f"**{battle['name']}** HP {battle['hp']}/{battle['hp_max']} · "
            f"攻击 {battle['attack']}",
            (f"意图：**{intent.get('name', '攻击')}**（防御，这一回合不出手）"
             if intent.get("effect") == "reflect" else
             f"意图：**{intent.get('name', '攻击')}**"
             f"（约 {self._intent_damage(run)} 伤害"
             f"{'，附带流血' if intent.get('effect') == 'bleed' else ''}"
             f"{'，破防' if intent.get('effect') == 'crush' else ''}"
             f"{'，会让你麻痹' if intent.get('effect') == 'paralyze' else ''}）"),
            f"我 HP **{run['hp']}/{run['hp_max']}** · 格挡 {battle['block']} · "
            f"锋锐 {self._attack_power(run)} · 锋利度 {run['sharp']}"
            f"{'（卷刃）' if int(run['sharp']) <= 0 else ''}",
        ]
        if battle.get("player_bleed"):
            lines.append(f"我流血中（{battle['player_bleed']} 回合）")
        if battle.get("bleed"):
            lines.append(f"敌人流血中（{battle['bleed']} 回合）")
        if battle.get("atk_buff_turns"):
            lines.append(f"攻击 +{battle['atk_buff']}%（{battle['atk_buff_turns']} 回合）")
        if battle.get("enemy_debuff_turns"):
            lines.append(f"敌人攻击 -{battle['enemy_debuff']}%"
                         f"（{battle['enemy_debuff_turns']} 回合）")
        if battle.get("star_turns"):
            lines.append(f"星屑灼烧（{battle['star_turns']} 回合，每回合 {battle['star']}）")
        if int(battle.get("turn") or 1) > 6:
            lines.append(f"⚠ 已经拖到第 {int(battle['turn'])} 回合，"
                         "它每回合都在变强")
        if battle.get("boss_enraged"):
            lines.append("⚠ 首领残血暴怒（攻击 +20%）")
        if battle.get("challenge"):
            phase = int(battle.get("challenge_phase") or 1)
            if phase >= 2:
                lines.append("阶段：**二阶段 · 北国沙鹰虾**（防御时会反弹攻击）")
            if battle.get("paralyzed"):
                lines.append("⚠ 被麻痹：下一次防守会失效")
            boss = CHALLENGE_BY_KEY.get(battle.get("boss_key") or "")
            if boss is not None and boss.dodge:
                lines.append(f"它的壳很滑：你的攻击有 {int(boss.dodge * 100)}% "
                             "会被弹开")
            if boss is not None and boss.heal_rate:
                lines.append(f"它每回合会回复 {int(boss.heal_rate * 100)}% 生命")
        cooling = [move for move in (run.get("moves") or [])
                   if int(run.get("cooldowns", {}).get(move) or 0) > 0]
        if cooling:
            lines.append("冷却中：" + " · ".join(
                f"{name} {int(run['cooldowns'][name])}" for name in cooling))
        if run.get("note"):
            lines.append(f"> {run['note']}")
            run["note"] = ""
        elif flavor:
            lines.append(f"> {flavor}")

        rows = [[("挥剑", self._data(state, ACT_PLAIN)),
                 ("防守", self._data(state, ACT_GUARD))]]
        moves = [MOVES[name] for name in run.get("moves") or [] if name in MOVES]
        moves = moves[:SHOW_MOVES]
        pairs = []
        for move in moves:
            cooldown = int(run.get("cooldowns", {}).get(move.name) or 0)
            label = f"{move.name}" if cooldown <= 0 else f"{move.name}"
            pairs.append((label, self._data(state, ACT_MOVE, move.name)))
        for index in range(0, len(pairs), 2):
            rows.append(pairs[index:index + 2])
        rows.append([("道具", self._data(state, ACT_BAG)),
                     ("撤退", self._data(state, ACT_FLEE))])
        return {"text": "\n".join(lines), "rows": rows}

    def _enemy_attack_now(self, run: dict, battle: dict) -> float:
        """敌人此刻的攻击力：吃减益，也会因为拖太久 / 残血而愈发狠。"""
        attack = float(battle["attack"])
        if int(battle.get("enemy_debuff_turns") or 0) > 0:
            attack *= 1 - float(battle["enemy_debuff"]) / 100
        turn = int(battle.get("turn") or 1)
        if turn > 6 and not battle.get("challenge"):
            attack *= 1 + 0.12 * (turn - 6)
        if battle.get("boss_enraged"):
            attack *= 1.2
        return attack

    def _intent_damage(self, run: dict) -> int:
        battle = run["battle"]
        intent = battle.get("intent") or {}
        attack = self._enemy_attack_now(run, battle)
        return max(0, int(round(attack * float(intent.get("multiplier", 1.0))))
                   - int(battle.get("block") or 0))

    def _tough_power(self, run: dict) -> int:
        """本局实际坚韧：剑的坚韧 + 遗物/道具的加成（防守格挡更高）。"""
        value = int(run["tough"])
        if "蜕鳞臂甲" in set(run.get("relics") or ()):
            value += 8
        value += int(run.get("tough_flat") or 0)
        return max(1, value)

    def _attack_power(self, run: dict) -> int:
        """本回合实际攻击力：剑的锋锐 × 各种加成，卷刃时腰斩。"""
        value = int(run["base_attack"]) + int(run.get("flat_atk") or 0)
        percent = float(run.get("atk_bonus") or 0)
        relics = set(run.get("relics") or ())
        if "鲸骨护腕" in relics:
            percent += 15
        if "深渊契约" in relics:
            percent += 25
        if "苦行者念珠" in relics:
            percent -= 10
        if "叠浪纹章" in relics:
            percent += 4 * max(0, int(run["plane"]) - 1)
        if "破晓鳞光" in relics and int(run["hp"]) <= int(run["hp_max"]) * 0.3:
            percent += 30
        if "鲨齿项链" in relics:
            percent += 10
        if "双生珊瑚" in relics:
            percent += 18
        battle = run.get("battle") or {}
        percent += float(battle.get("atk_buff") or 0)
        value = int(round(value * (1 + percent / 100)))
        if int(run.get("sharp") or 0) <= 0:
            value = int(round(value * BLUNT_ATTACK_RATE))
        return max(1, value)

    def _move(self, state: Panel, run: dict, argument: str) -> dict:
        if run.get("mode") != "battle" or not run.get("battle"):
            return self._say("现在不在战斗里。")
        name = argument or "挥剑"
        if name == "挥剑":
            move = Move("挥剑", "挥剑", 1.0, 1, 0, "", 0, "基础攻击")
        else:
            move = MOVES.get(name)
            if move is None:
                return self._say("没有这个招式。")
            if name not in (run.get("moves") or []):
                return self._say("这一招你还没学会。")
            cooldown = int(run.get("cooldowns", {}).get(name) or 0)
            if cooldown > 0:
                return self._say(f"「{name}」还在冷却（{cooldown} 回合）。")
        return self._player_action(state, run, "move", move)

    def _guard(self, state: Panel, run: dict, argument: str = "") -> dict:
        if run.get("mode") != "battle" or not run.get("battle"):
            return self._say("现在不在战斗里。")
        return self._player_action(state, run, "guard")

    def _player_action(self, state: Panel, run: dict, kind: str,
                       move: Move | None = None) -> dict:
        battle = run["battle"]
        notes: list[str] = []
        meta = self.user(state.user)["meta"]
        upgrades = meta.get("upgrades") or {}
        battle["block"] = 0            # 上回合的格挡清掉
        paralyzed = bool(battle.pop("paralyzed", False))
        # 1) 自身流血
        if int(battle.get("player_bleed") or 0) > 0:
            run["hp"] = int(run["hp"]) - BLEED_DAMAGE
            battle["player_bleed"] = int(battle["player_bleed"]) - 1
            notes.append(f"流血 -{BLEED_DAMAGE}")
        if int(run["hp"]) <= 0:
            return self._death(state, run, notes)
        # 2) 出招
        if kind == "guard":
            if paralyzed:
                block = 0
                notes.append("被麻痹了，防守没举起来")
            else:
                block = guard_block(self._tough_power(run),
                                    int(upgrades.get("block") or 0))
                battle["block"] = block
                notes.append(f"防守：获得 {block} 格挡")
        else:
            assert move is not None
            if move.effect == "heal":
                healed = self._heal(run, move.value, notes)
                if healed:
                    notes.append(f"回复 {healed} HP")
                if move.name == "鲸歌安魂":
                    battle["player_bleed"] = 0
                    notes.append("流血清掉了")
            else:
                if float(move.power) > 0 and int(move.hits) > 0:
                    notes.extend(self._strike(run, battle, move))
            if move.effect == "block":
                battle["block"] = int(battle["block"] or 0) + int(move.value)
                notes.append(f"获得 {move.value} 格挡")
            if move.effect == "debuff":
                battle["enemy_debuff"] = int(move.value)
                battle["enemy_debuff_turns"] = 2
                notes.append(f"敌人攻击 -{move.value}%")
            if move.effect == "bleed":
                battle["bleed"] = max(int(battle.get("bleed") or 0), int(move.value))
                notes.append(f"敌人流血 {move.value} 回合")
            if move.effect == "self_damage":
                run["hp"] = max(0, int(run["hp"]) - int(move.value))
                notes.append(f"自己 -{move.value} HP")
            if move.cooldown:
                run.setdefault("cooldowns", {})[move.name] = move.cooldown
        # 3) 星屑 / 敌人流血
        if int(battle.get("star_turns") or 0) > 0:
            battle["hp"] = max(0, int(battle["hp"]) - int(battle["star"]))
            battle["star_turns"] = int(battle["star_turns"]) - 1
            notes.append(f"星屑造成 {battle['star']} 点")
        if int(battle.get("bleed") or 0) > 0:
            battle["hp"] = max(0, int(battle["hp"]) - BLEED_DAMAGE)
            battle["bleed"] = int(battle["bleed"]) - 1
            notes.append(f"敌人流血 -{BLEED_DAMAGE}")
        # 首领一阶段见底：锁血进二阶段（秒杀也一样），转阶段这回合它不出手
        transitioned = self._challenge_phase(battle, notes)
        # 4) 敌人死了？
        if int(battle["hp"]) <= 0:
            return self._win_battle(state, run, notes)
        if int(run["hp"]) <= 0:
            return self._death(state, run, notes)
        # 5) 敌人回合（转阶段那一回合它缩壳，不出手）
        if not transitioned:
            notes.extend(self._enemy_turn(run, battle))
        else:
            notes.append("它顾着缩壳变身，这回合没出手")
        if int(run["hp"]) <= 0:
            return self._death(state, run, notes)
        # 6) 回合收尾：冷却、buff、意图
        for name in list(run.get("cooldowns", {})):
            run["cooldowns"][name] = max(0, int(run["cooldowns"][name]) - 1)
        if int(battle.get("atk_buff_turns") or 0) > 0:
            battle["atk_buff_turns"] = int(battle["atk_buff_turns"]) - 1
            if battle["atk_buff_turns"] <= 0:
                battle["atk_buff"] = 0
        if int(battle.get("enemy_debuff_turns") or 0) > 0:
            battle["enemy_debuff_turns"] = int(battle["enemy_debuff_turns"]) - 1
        battle["turn"] = int(battle["turn"]) + 1
        battle["first"] = False
        battle["intent"] = self._next_intent(run, battle)
        run["note"] = "；".join(notes[-3:])
        self._save()
        return {"ok": True, "panel": self._panel(state, run), "reply": ""}

    def _strike(self, run: dict, battle: dict, move: Move) -> list[str]:
        notes = []
        relics = set(run.get("relics") or ())
        attack = self._attack_power(run)
        defense = enemy_defense(int(battle["attack"]))
        boss = (CHALLENGE_BY_KEY.get(battle.get("boss_key") or "")
                if battle.get("challenge") else None)
        reflecting = bool(
            boss is not None and boss.reflect
            and int(battle.get("challenge_phase") or 1) >= 2
            and (battle.get("intent") or {}).get("effect") == "reflect"
        )
        total = 0
        hits = max(1, int(move.hits))
        for _ in range(hits):
            if boss is not None and boss.dodge and self.rng.random() < boss.dodge:
                notes.append("被它弹开了，这一击没造成伤害")
                continue
            raw = int(round(attack * float(move.power)
                            * self.rng.uniform(1 - DAMAGE_SPREAD,
                                               1 + DAMAGE_SPREAD)))
            damage = max(1, raw - defense)
            if relics and "血锈之刃" in relics and battle.get("first"):
                damage *= 2
                notes.append("血锈之刃：首击翻倍")
            if "赌徒之瞳" in relics:
                roll = self.rng.random()
                if roll < 0.2:
                    damage *= 2
                    notes.append("赌徒之瞳：双倍！")
                elif roll < 0.3:
                    run["hp"] = max(0, int(run["hp"]) - 5)
                    notes.append("赌徒之瞳：反噬 5 点")
            if move.effect == "execute" and battle["hp"] <= battle["hp_max"] * 0.4:
                damage *= 2
                notes.append("逆流冲撞：处决翻倍")
            if reflecting:
                reflected = max(1, int(round(raw * 0.5)))
                run["hp"] = max(0, int(run["hp"]) - reflected)
                damage = max(1, damage // 5)
                notes.append(f"它举壳反弹！我受到 {reflected} 点反伤")
            total += damage
        battle["hp"] = max(0, int(battle["hp"]) - total)
        notes.append(f"{move.name} 造成 {total} 点")
        return notes

    def _enemy_turn(self, run: dict, battle: dict) -> list[str]:
        intent = battle.get("intent") or {}
        notes = []
        boss = (CHALLENGE_BY_KEY.get(battle.get("boss_key") or "")
                if battle.get("challenge") else None)
        if (intent.get("effect") or "") == "reflect":
            notes.append("它举着硬壳防守，这一回合没有出手")
            return notes
        attack = self._enemy_attack_now(run, battle)
        if int(battle.get("turn") or 1) == 7:
            notes.append("它打出手感了，之后每一击都更重")
        relics = set(run.get("relics") or ())
        if "静默海螺" in relics:
            attack *= 0.9
        effect = intent.get("effect") or ""
        if effect == "crush":
            battle["block"] = int(battle["block"]) // 2
        damage = max(0, int(round(attack * float(intent.get("multiplier", 1.0))
                                  * self.rng.uniform(1 - DAMAGE_SPREAD,
                                                     1 + DAMAGE_SPREAD))))
        block = int(battle.get("block") or 0)
        absorbed = min(block, damage)
        damage -= absorbed
        battle["block"] = block - absorbed
        if damage > 0:
            if "深海耳环" in relics:
                damage += 2
            run["hp"] = int(run["hp"]) - damage
            notes.append(f"{intent.get('name', '攻击')} → 我 -{damage}")
        else:
            notes.append(f"{intent.get('name', '攻击')} 被挡下")
        if (battle.get("kind") == KIND_BOSS and not battle.get("boss_enraged")
                and int(battle["hp"]) <= int(battle["hp_max"]) * 0.5):
            battle["boss_enraged"] = True
            notes.append("首领暴怒了，攻击 +20%")
        if effect == "bleed":
            battle["player_bleed"] = max(int(battle.get("player_bleed") or 0), 2)
            notes.append("我流血了（2 回合）")
        elif effect == "drain":
            healed = max(1, int(damage * 0.5))
            battle["hp"] = min(int(battle["hp_max"]), int(battle["hp"]) + healed)
            notes.append(f"它吸回 {healed} HP")
        elif effect == "heal":
            healed = max(1, int(battle["hp_max"] * 0.08))
            battle["hp"] = min(int(battle["hp_max"]), int(battle["hp"]) + healed)
            notes.append(f"它恢复 {healed} HP")
        if boss is not None and boss.paralyze:
            if self.rng.random() < boss.paralyze:
                battle["paralyzed"] = 1
                notes.append("被它的显卡热浪麻痹了，下一次防守会失效")
        if boss is not None and boss.heal_rate:
            healed = max(1, int(round(int(battle["hp_max"]) * boss.heal_rate)))
            battle["hp"] = min(int(battle["hp_max"]), int(battle["hp"]) + healed)
            notes.append(f"它顺手回了 {healed} 点血")
        if "深渊契约" in relics:
            run["hp"] = int(run["hp"]) - 1
            notes.append("深渊契约：-1 HP")
        return notes

    # ---- 战斗结算 ----
    def _win_battle(self, state: Panel, run: dict, notes: list[str]) -> dict:
        if run.get("challenge"):
            return self._end_challenge(state, run, True)
        battle = run["battle"]
        # 记一笔战斗，结算面板上要报「打了多少场」
        run.setdefault("battles", []).append({
            "kind": str(battle.get("kind") or KIND_NORMAL),
            "turns": int(battle.get("turn") or 1),
            "plane": int(run.get("plane") or 1),
            "floor": int(run.get("floor") or 1),
        })
        kind = battle.get("kind") or KIND_NORMAL
        loot = int(battle.get("loot") or 0)
        relics = set(run.get("relics") or ())
        if "拾荒者腰带" in relics:
            loot = int(round(loot * 1.25))
        if "贪婪之心" in relics:
            loot = int(round(loot * 1.4))
        if int(run.get("loot_buff") or 0):
            loot = int(round(loot * (1 + int(run["loot_buff"]) / 100)))
            run["loot_buff"] = 0
        run["coins"] = int(run.get("coins") or 0) + loot
        if kind == KIND_BOSS:
            run["scales"] = int(run.get("scales") or 0) + SCALES_PER_BOSS
            # 首领战之后长一截血：40 层走下来，光靠开局那点血撑不住
            run["hp_base"] = int(run.get("hp_base") or 0) + 8
            self._refresh_max_hp(run)
            run["hp"] = min(int(run["hp_max"]),
                            int(run["hp"]) + int(round(run["hp_max"] * 0.2)))
            notes.append("打完首领：最大生命 +8，顺便回了点血")
        cost = self._battle_sharp_cost(run, kind,
                                       int(self._grade(state.user) or 0))
        run["sharp"] = max(0, int(run["sharp"]) - cost)
        self._set_sword_sharp(state.user, run["sword_id"], run["sharp"])
        run["battle"] = None
        run["node"] = None
        run["mode"] = "reward"
        run["rewards"] = self._battle_rewards(run, kind)
        run["reward_kind"] = kind
        run["note"] = (self.rng.choice(VICTORY_FLAVOR)
                       + f" 带回 {loot} 银币，剑 -{cost} 锋利度。")
        self._save()
        return {"ok": True, "panel": self._panel(state, run), "reply": ""}

    def _battle_sharp_cost(self, run: dict, kind: str,
                           blade_level: int = 0) -> int:
        """打完一场掉的锋利度；遗物「潮汐肺」会再多 25%。"""
        cost = sharp_cost(kind, blade_level)
        if "潮汐肺" in set(run.get("relics") or ()):
            cost = max(1, int(round(cost * 1.25)))
        return cost

    def _grade(self, user: str) -> int:
        meta = self.user(user).get("meta") or {}
        return int((meta.get("upgrades") or {}).get("blade") or 0)

    def _pick_some(self, pool: list, count: int) -> list:
        """从池子里不重复地抽 ``count`` 个（rng 只依赖 random/randint）。"""
        pool = list(pool)
        picked = []
        while pool and len(picked) < count:
            index = self.rng.randint(0, len(pool) - 1) if len(pool) > 1 else 0
            picked.append(pool.pop(index))
        return picked

    def _battle_rewards(self, run: dict, kind: str) -> list[dict]:
        pool = []
        item = random_item(self.rng)
        relic = random_relic(self.rng, tuple(run.get("relics") or ()))
        move = random_move(self.rng, tuple(run.get("moves") or ()))
        if kind == KIND_BOSS and relic is not None:
            pool.append({"kind": "relic", "name": relic.name,
                         "detail": f"遗物：**{relic.name}** —— {relic.desc}"})
        if item is not None:
            pool.append({"kind": "item", "name": item.name,
                         "detail": f"道具：{item_line(item)}"})
        if move is not None:
            pool.append({"kind": "move", "name": move.name,
                         "detail": f"招式：**{move.name}** —— {move.desc}"})
        pool.append({"kind": "heal", "ratio": 25,
                     "detail": "治疗：回复 25% 最大生命"})
        pool.append({"kind": "coins", "value": 40 + 10 * int(kind == KIND_ELITE)
                     + 30 * int(kind == KIND_BOSS),
                     "detail": "银币：直接拿一笔"})
        if kind == KIND_BOSS and relic is not None:
            return pool[:3]
        boss_bonus = [entry for entry in pool if entry["kind"] == "relic"]
        others = [entry for entry in pool if entry["kind"] != "relic"]
        return (boss_bonus + self._pick_some(others, 3))[:3]

    def _treasure_rewards(self, run: dict) -> list[dict]:
        pool = []
        item = random_item(self.rng)
        relic = random_relic(self.rng, tuple(run.get("relics") or ()))
        if item is not None:
            pool.append({"kind": "item", "name": item.name,
                         "detail": f"道具：{item_line(item)}"})
        if relic is not None:
            pool.append({"kind": "relic", "name": relic.name,
                         "detail": f"遗物：**{relic.name}** —— {relic.desc}"})
        pool.append({"kind": "coins", "value": 50, "detail": "银币：直接拿一笔"})
        return self._pick_some(pool, 2) + [{"kind": "heal", "ratio": 20,
                                            "detail": "治疗：回复 20% 最大生命"}]

    def _death(self, state: Panel, run: dict, notes: list[str]) -> dict:
        if run.get("challenge"):
            return self._end_challenge(state, run, False)
        run["hp"] = 0
        run["sharp"] = max(0, int(run["sharp"]) - SHARP_COST_DEATH)
        self._set_sword_sharp(state.user, run["sword_id"], run["sharp"])
        run["note"] = "；".join(notes[-2:])
        self._end_run(state, run, "dead")
        return {"ok": True, "panel": self._panel(state), "reply": ""}

    def _flee(self, state: Panel, run: dict, argument: str = "") -> dict:
        if run.get("mode") != "battle" or not run.get("battle"):
            return self._say("现在不在战斗里。")
        if run.get("challenge"):
            return self._end_challenge(state, run, False, fled=True)
        run["sharp"] = max(0, int(run["sharp"]) - SHARP_COST_FLEE)
        self._set_sword_sharp(state.user, run["sword_id"], run["sharp"])
        run["battle"] = None
        run["node"] = None
        run["mode"] = "map"
        run["note"] = f"撤回来了，剑 -{SHARP_COST_FLEE} 锋利度。这条路还在。"
        self._save()
        return {"ok": True, "panel": self._panel(state, run), "reply": ""}

    # ==================================================================
    # 战利品 / 事件 / 休整 / 商店
    # ==================================================================

    def _reward_panel(self, state: Panel, run: dict) -> dict:
        rewards = run.get("rewards") or []
        kind = run.get("reward_kind") or ""
        lines = [
            f"## 战利品 · {kind or '宝藏'}",
            f"本局银币 {int(run.get('coins') or 0)} · 剑 锋利度 {int(run['sharp'])}"
            f"/{int(run.get('sharp_max') or 0)}",
        ]
        if run.get("note"):
            lines.append(f"> {run['note']}")
        lines.append("挑一件带走：")
        pairs = []
        labels = {"item": "选道具", "relic": "选遗物", "move": "选招式",
                  "heal": "治疗", "coins": "拿银币"}
        for index, reward in enumerate(rewards):
            lines.append(f"{circled(index)}{reward['detail']}")
            label = labels.get(reward["kind"], "选")
            pairs.append((f"{circled(index)}{label}",
                          self._data(state, ACT_TAKE, str(index))))
        rows = [pairs]
        rows.append([("都不要", self._data(state, ACT_TAKE, "-1"))])
        return {"text": "\n".join(lines), "rows": rows}

    def _take_reward(self, state: Panel, run: dict, argument: str) -> dict:
        if run.get("mode") != "reward":
            return self._say("现在没有要挑的战利品。")
        try:
            index = int(argument)
        except (TypeError, ValueError):
            return self._say(STALE_REPLY)
        rewards = run.get("rewards") or []
        if index == -1:
            run["rewards"] = []
            return self._after_floor(state, run)
        if not 0 <= index < len(rewards):
            return self._say(STALE_REPLY)
        return self._apply_reward(state, run, rewards[index])

    def _apply_reward(self, state: Panel, run: dict, reward: dict) -> dict:
        kind = reward.get("kind")
        name = reward.get("name")
        if kind == "item":
            item = ITEMS.get(name)
            if item is not None:
                if not self._gain_item(run, item.name):
                    return self._ask_replace(state, run, "item", item.name)
        elif kind == "relic":
            relic = RELICS.get(name)
            if relic is not None:
                self._gain_relic(run, relic.name)
        elif kind == "move":
            move = MOVES.get(name)
            if move is not None:
                if not self._gain_move(run, move.name):
                    return self._ask_replace(state, run, "move", move.name)
        elif kind == "heal":
            ratio = int(reward.get("ratio") or 0)
            amount = (int(round(int(run["hp_max"]) * ratio / 100)) if ratio
                      else int(reward.get("value") or 0))
            self._heal(run, amount, [])
        elif kind == "coins":
            run["coins"] = int(run.get("coins") or 0) + int(reward.get("value") or 0)
        run["rewards"] = []
        return self._after_floor(state, run)

    def _event_panel(self, state: Panel, run: dict) -> dict:
        event = EVENTS.get((run.get("node") or {}).get("event") or "")
        if event is None:
            run["mode"] = "map"
            return {"ok": True, "panel": self._map_panel(state, run), "reply": ""}
        lines = [f"## 事件 · {event.name}", event.text, "**选项：**"]
        pairs = []
        for index, option in enumerate(event.options):
            lines.append(f"{circled(index)}{option.detail}")
            pairs.append((f"{circled(index)}{option.label}",
                          self._data(state, ACT_EVENT, str(index))))
        rows = [pairs]
        rows.append([("绕开", self._data(state, ACT_EVENT, "-1"))])
        return {"text": "\n".join(lines), "rows": rows}

    def _event_option(self, state: Panel, run: dict, argument: str) -> dict:
        if run.get("mode") != "event":
            return self._say("现在没有事件要做选择。")
        event = EVENTS.get((run.get("node") or {}).get("event") or "")
        if event is None:
            return self._say(STALE_REPLY)
        try:
            index = int(argument)
        except (TypeError, ValueError):
            return self._say(STALE_REPLY)
        if index == -1:
            run["node"] = None
            return self._after_floor(state, run)
        if not 0 <= index < len(event.options):
            return self._say(STALE_REPLY)
        option = event.options[index]
        return self._resolve_option(state, run, option)

    def _resolve_option(self, state: Panel, run: dict,
                        option: Option) -> dict:
        good = True
        if option.chance and self.rng.random() >= option.chance:
            good = False
        effects = option.good if good else option.bad
        text = option.good_text if good else option.bad_text
        notes = []
        for effect, value in effects:
            notes.extend(self._apply_effect(state, run, effect, value))
        run["note"] = (text + ("；" + "；".join(notes) if notes else ""))
        if run.get("mode") == "replace":
            return {"ok": True, "panel": self._panel(state, run), "reply": ""}
        run["node"] = None
        return self._after_floor(state, run)

    def _apply_effect(self, state: Panel, run: dict, effect: str,
                      value) -> list[str]:
        notes = []
        if effect == EFFECT_ITEM:
            item = ITEMS.get(str(value)) if value != "random" else random_item(self.rng)
            if item is not None:
                if self._gain_item(run, item.name):
                    notes.append(f"获得道具 {item.name}")
                else:
                    run["pending"] = {"kind": "item", "name": item.name,
                                      "after": "map"}
                    run["mode"] = "replace"
                    notes.append(f"道具栏满了：{item.name} 要用还是丢")
        elif effect == EFFECT_RELIC:
            relic = RELICS.get(str(value)) if value != "random" else random_relic(
                self.rng, tuple(run.get("relics") or ()))
            if relic is not None and self._gain_relic(run, relic.name):
                notes.append(f"获得遗物 {relic.name}")
        elif effect == EFFECT_MOVE:
            move = MOVES.get(str(value)) if value != "random" else random_move(
                self.rng, tuple(run.get("moves") or ()))
            if move is not None:
                if self._gain_move(run, move.name):
                    notes.append(f"学会招式 {move.name}")
                else:
                    run["pending"] = {"kind": "move", "name": move.name,
                                      "after": "map"}
                    run["mode"] = "replace"
                    notes.append(f"招式栏满了：{move.name} 要还是换")
        elif effect == EFFECT_COINS:
            run["coins"] = int(run.get("coins") or 0) + int(value)
            notes.append(f"+{int(value)} 银币")
        elif effect == EFFECT_HEAL:
            healed = self._heal(run, int(value), notes)
            if healed:
                notes.append(f"+{healed} HP")
        elif effect == EFFECT_DAMAGE:
            got = min(int(run["hp"]) - 1, int(value))
            got = max(0, got)
            run["hp"] = int(run["hp"]) - got
            notes.append(f"-{got} HP")
        elif effect == EFFECT_MAX_HP:
            if isinstance(value, str) and value.strip().endswith("%"):
                try:
                    ratio = float(value.strip().rstrip("%")) / 100
                except ValueError:
                    ratio = 0.0
                run["hp_base"] = max(10, int(round(
                    int(run.get("hp_base") or 10) * (1 + ratio))))
                self._refresh_max_hp(run)
                notes.append(f"最大生命 {value}")
            else:
                run["hp_flat"] = int(run.get("hp_flat") or 0) + int(value)
                self._refresh_max_hp(run)
                notes.append(f"最大生命 {int(value):+d}")
        elif effect == EFFECT_ATK_FLAT:
            run["flat_atk"] = int(run.get("flat_atk") or 0) + int(value)
            notes.append(f"攻击 +{int(value)}")
        elif effect == EFFECT_TOUGH:
            run["tough_flat"] = int(run.get("tough_flat") or 0) + int(value)
            notes.append(f"坚韧 +{int(value)}")
        elif effect == EFFECT_SHARP_MAX:
            run["sharp_max"] = max(10, int(run.get("sharp_max") or 100)
                                   + int(value))
            run["sharp"] = min(int(run["sharp"]), int(run["sharp_max"]))
            self._set_sword_sharp(state.user, run["sword_id"], run["sharp"])
            notes.append(f"锋利度上限 {int(value):+d}")
        elif effect == EFFECT_ATK:
            run["atk_bonus"] = float(run.get("atk_bonus") or 0) + float(value)
            notes.append(f"攻击 {int(value):+d}%")
        elif effect == EFFECT_SHARP:
            if value == "full":
                run["sharp"] = int(run.get("sharp_max") or run["sharp"])
            else:
                run["sharp"] = max(0, min(int(run.get("sharp_max") or 999),
                                          int(run["sharp"]) + int(value)))
            self._set_sword_sharp(state.user, run["sword_id"], run["sharp"])
            notes.append(f"锋利度 {int(run['sharp'])}")
        elif effect == EFFECT_SCALES:
            run["scales"] = int(run.get("scales") or 0) + int(value)
            notes.append(f"+{int(value)} 鲸鳞")
        return notes

    def _rest_heal(self, run: dict) -> int:
        """休整回多少血：最大生命的 35%，最少 35；潮汐罗盘 +10。"""
        relics = set(run.get("relics") or ())
        heal = max(REST_HEAL_FLOOR,
                   int(round(int(run["hp_max"]) * REST_HEAL_RATIO / 100)))
        return heal + (REST_HEAL_RELIC if "潮汐罗盘" in relics else 0)

    def _rest_panel(self, state: Panel, run: dict) -> dict:
        cap = int(run.get("sharp_max") or 0)
        missing = cap - int(run["sharp"])
        heal = self._rest_heal(run)
        lines = [
            "## 休整",
            "潮水退下去，露出一块干净的石台。",
            self._status_line(run),
            f"{circled(0)} 睡一觉 — 回复 {heal} HP",
            (f"{circled(1)} 磨刀 — 免费把剑磨回上限"
             f"（锋利度 {int(run['sharp'])} → {cap}）"
             if missing > 0 else
             f"{circled(1)} 磨刀 — 刃口还很好，不用磨"),
        ]
        rows = [[("睡一觉", self._data(state, ACT_REST, "0")),
                 ("磨刀", self._data(state, ACT_REST, "1"))]]
        return {"text": "\n".join(lines), "rows": rows}

    def _rest_option(self, state: Panel, run: dict, argument: str) -> dict:
        if run.get("mode") != "rest":
            return self._say("现在不在休整。")
        if argument == "1":
            cap = int(run.get("sharp_max") or 0)
            before = int(run["sharp"])
            if before >= cap:
                return self._say("刃口还很好，不用磨。")
            run["sharp"] = cap
            self._set_sword_sharp(state.user, run["sword_id"], cap)
            run["note"] = f"磨好了：锋利度 {before} → {cap}（免费）。"
        else:
            heal = self._rest_heal(run)
            healed = self._heal(run, heal, [])
            run["note"] = (f"睡了一觉，回复 {healed} HP。"
                           if healed else "睡了一觉，血是满的，就当养精神。")
        run["node"] = None
        return self._after_floor(state, run)

    def _shop_panel(self, state: Panel, run: dict) -> dict:
        node = run.get("node") or {}
        offers = node.get("offers") or []
        lines = ["## 商店", "一条穿围裙的章鱼摆开了柜台。",
                 f"本局银币 **{int(run.get('coins') or 0)}**"]
        pairs = []
        for index, offer in enumerate(offers):
            if offer.get("price") is None:
                price = "按缺口算"
            elif not offer.get("price"):
                price = "免费"
            else:
                price = f"{offer['price']} 银币"
            lines.append(f"{circled(index)}{offer['detail']}（{price}）")
            pairs.append((f"{circled(index)}买",
                          self._data(state, ACT_BUY, str(index))))
        rows = [pairs] if pairs else []
        rows.append([("离开", self._data(state, ACT_BUY, "-1"))])
        return {"text": "\n".join(lines), "rows": rows}

    def _buy(self, state: Panel, run: dict, argument: str) -> dict:
        if run.get("mode") != "shop":
            return self._say("现在不在商店。")
        node = run.get("node") or {}
        offers = node.get("offers") or []
        try:
            index = int(argument)
        except (TypeError, ValueError):
            return self._say(STALE_REPLY)
        if index == -1:
            run["node"] = None
            return self._after_floor(state, run)
        if not 0 <= index < len(offers):
            return self._say(STALE_REPLY)
        offer = offers[index]
        price = int(offer.get("price") or 0)
        coins = int(run.get("coins") or 0)
        kind = offer.get("kind")
        if kind != "sharpen" and coins < price:
            return self._say(f"买不起：要 {price} 银币，本局只有 {coins}。")
        if kind == "sharpen":
            cap = int(run.get("sharp_max") or 0)
            missing = cap - int(run["sharp"])
            cost = sharpen_cost(missing, run.get("relics") or ())
            if missing <= 0:
                return self._say("刃口还很好，不用磨。")
            if coins < cost:
                return self._say(f"磨刀要 {cost} 银币，本局只有 {coins}。")
            run["coins"] = coins - cost
            run["sharp"] = cap
            self._set_sword_sharp(state.user, run["sword_id"], cap)
        else:
            item = ITEMS.get(offer.get("name") or "")
            relic = RELICS.get(offer.get("name") or "")
            move = MOVES.get(offer.get("name") or "")
            if kind == "item" and item is not None:
                if not self._gain_item(run, item.name):
                    run["pending"] = {"kind": "item", "name": item.name,
                                      "after": "shop", "price": price,
                                      "offer": index}
                    run["mode"] = "replace"
                    return {"ok": True, "panel": self._panel(state, run),
                            "reply": ""}
            elif kind == "relic" and relic is not None:
                self._gain_relic(run, relic.name)
            elif kind == "move" and move is not None:
                if not self._gain_move(run, move.name):
                    run["pending"] = {"kind": "move", "name": move.name,
                                      "after": "shop", "price": price,
                                      "offer": index}
                    run["mode"] = "replace"
                    return {"ok": True, "panel": self._panel(state, run),
                            "reply": ""}
            run["coins"] = coins - price
        offers.pop(index)
        run["note"] = f"买下了 {offer.get('name') or '磨刀'}。"
        self._save()
        state.seq += 1
        panel = self._shop_panel(state, run)
        panel["text"] = f"> {run['note']}\n" + panel["text"]
        return {"ok": True, "panel": panel, "reply": ""}

    # ==================================================================
    # 道具 / 遗物 / 招式
    # ==================================================================

    def _gain_item(self, run: dict, name: str) -> bool:
        if name not in ITEMS:
            return False
        if len(run.get("items") or []) < ITEM_SLOTS:
            run.setdefault("items", []).append(name)
            return True
        return False

    def _gain_relic(self, run: dict, name: str) -> bool:
        if name not in RELICS or name in (run.get("relics") or []):
            return False
        run.setdefault("relics", []).append(name)
        self._refresh_max_hp(run)
        return True

    def _gain_move(self, run: dict, name: str) -> bool:
        if name not in MOVES or name in (run.get("moves") or []):
            return False
        if len(run.get("moves") or []) < MOVE_SLOTS:
            run.setdefault("moves", []).append(name)
            return True
        return False

    def _ask_replace(self, state: Panel, run: dict, kind: str,
                     name: str, after: str = "map") -> dict:
        run["pending"] = {"kind": kind, "name": name, "after": after}
        run["mode"] = "replace"
        self._save()
        return {"ok": True, "panel": self._panel(state, run), "reply": ""}

    def _replace_panel(self, state: Panel, run: dict) -> dict:
        pending = run.get("pending") or {}
        name = pending.get("name") or "新东西"
        kind = pending.get("kind")
        lines = [f"## 装不下了 · {name}"]
        if kind == "item":
            lines.append(f"道具栏只有 **{ITEM_SLOTS}** 格，满了。"
                         "要么丢掉新的，要么替换掉一个。")
            lines.append("**现在的道具：**")
            for index, key in enumerate(run.get("items") or []):
                item = ITEMS.get(key)
                if item is not None:
                    lines.append(f"{circled(index)}{item_line(item)}")
            new_item = ITEMS.get(name)
            if new_item is not None:
                lines.append(f"**新道具：** {item_line(new_item)}")
            rows = [[("丢弃新的", self._data(state, ACT_DROP))]]
            for index, key in enumerate(run.get("items") or []):
                rows.append([(f"替换{circled(index)}",
                              self._data(state, ACT_SWAP, str(index)))])
        else:
            lines.append(f"招式栏只有 **{MOVE_SLOTS}** 格，满了。"
                         "要么放弃新招式，要么替换掉一个。")
            lines.append("**现在的招式：**")
            for index, key in enumerate(run.get("moves") or []):
                move = MOVES.get(key)
                if move is not None:
                    lines.append(f"{circled(index)}{move.name} — {move.desc}")
            new_move = MOVES.get(name)
            if new_move is not None:
                lines.append(f"**新招式：** {new_move.name} — {new_move.desc}")
            rows = [[("放弃新的", self._data(state, ACT_DROP))]]
            pairs = []
            for index, key in enumerate(run.get("moves") or []):
                pairs.append((f"换掉{circled(index)}",
                              self._data(state, ACT_SWAP, str(index))))
            for index in range(0, len(pairs), 2):
                rows.append(pairs[index:index + 2])
        return {"text": "\n".join(lines), "rows": rows}

    def _replace_drop(self, state: Panel, run: dict, argument: str) -> dict:
        pending = run.get("pending") or {}
        run["pending"] = None
        run["note"] = f"把 {pending.get('name') or '新东西'} 丢下了。"
        if pending.get("after") == "shop":
            run["mode"] = "shop"
            self._save()
            state.seq += 1
            return {"ok": True, "panel": self._shop_panel(state, run), "reply": ""}
        run["node"] = None
        return self._after_floor(state, run)

    def _replace_swap(self, state: Panel, run: dict, argument: str) -> dict:
        pending = run.get("pending") or {}
        kind = pending.get("kind")
        try:
            index = int(argument)
        except (TypeError, ValueError):
            return self._say(STALE_REPLY)
        if kind == "item":
            items = run.get("items") or []
            if not 0 <= index < len(items):
                return self._say(STALE_REPLY)
            old = items[index]
            items[index] = pending["name"]
            note = f"用 {pending['name']} 换下了 {old}。"
        else:
            moves = run.get("moves") or []
            if not 0 <= index < len(moves):
                return self._say(STALE_REPLY)
            old = moves[index]
            moves[index] = pending["name"]
            note = f"用 {pending['name']} 换掉了 {old}。"
        if pending.get("after") == "shop":
            # 商店里替换是要付钱的；付完把卖掉的货撤下柜台
            price = int(pending.get("price") or 0)
            if int(run.get("coins") or 0) < price:
                run["pending"] = None
                run["mode"] = "shop"
                return self._say(f"买不起：要 {price} 银币，刚才那件没换。")
            run["coins"] = int(run["coins"]) - price
            offers = (run.get("node") or {}).get("offers") or []
            offer_index = int(pending.get("offer") or -1)
            if 0 <= offer_index < len(offers):
                offers.pop(offer_index)
            run["pending"] = None
            run["mode"] = "shop"
            run["note"] = note
            self._save()
            state.seq += 1
            return {"ok": True, "panel": self._shop_panel(state, run), "reply": ""}
        run["pending"] = None
        run["node"] = None
        run["note"] = note
        return self._after_floor(state, run)

    def _bag(self, state: Panel) -> dict:
        state.seq += 1
        run = self._run(state.user)
        if run is None:
            record = self.user(state.user)
            lines = ["## 行囊", "现在没有进行中的冒险。",
                     f"鲸鳞 {int(record['meta'].get('points') or 0)}"]
            rows = [[("返回", self._data(state, ACT_BACK))]]
            return {"ok": True, "panel": {"text": "\n".join(lines), "rows": rows},
                    "reply": ""}
        lines = ["## 行囊", self._status_line(run), "",
                 "**道具**（只有两个格子，用掉就没了）"]
        items = [ITEMS[name] for name in run.get("items") or [] if name in ITEMS]
        if items:
            for index, item in enumerate(items):
                lines.append(f"{circled(index)}{item_line(item)}")
        else:
            lines.append("（空）")
        relics = [RELICS[name] for name in run.get("relics") or [] if name in RELICS]
        lines.append("**遗物**（常驻被动，正负效果都写在后面）")
        if relics:
            for relic in relics:
                lines.append(f"· **{relic.name}** —— {relic.desc}")
        else:
            lines.append("（还没有）")
        lines.append("**招式**（冷却好了才能用）")
        moves = [MOVES[name] for name in run.get("moves") or [] if name in MOVES]
        if moves:
            for move in moves:
                lines.append(f"· **{move.name}** —— {move.desc}")
        else:
            lines.append("· 只有「挥剑」这一招，事件里能学更多。")
        rows = []
        if items:
            pairs = [(f"用{circled(index)}", self._data(state, ACT_ITEM, str(index)))
                     for index in range(len(items))]
            rows = [pairs[index:index + 2] for index in range(0, len(pairs), 2)]
        rows.append([("返回", self._data(state, ACT_BACK))])
        return {"ok": True, "panel": {"text": "\n".join(lines), "rows": rows},
                "reply": ""}

    def _use_item(self, state: Panel, run: dict, argument: str) -> dict:
        try:
            index = int(argument)
        except (TypeError, ValueError):
            return self._say(STALE_REPLY)
        items = run.get("items") or []
        if not 0 <= index < len(items):
            return self._say(STALE_REPLY)
        name = items[index]
        item = ITEMS.get(name)
        if item is None:
            return self._say(STALE_REPLY)
        battle = run.get("battle") if run.get("mode") == "battle" else None
        if item.where == "battle" and battle is None:
            return self._say(f"「{item.name}」只能在战斗里用。")
        notes = self._apply_item(run, battle, item)
        items.pop(index)
        run["note"] = "；".join(notes) if notes else f"用了 {item.name}"
        self._save()
        return {"ok": True, "panel": self._panel(state, run), "reply": ""}

    def _apply_item(self, run: dict, battle: dict | None,
                    item: Item) -> list[str]:
        """用一件道具：主效果 + extra 里的附带效果（有正有负的道具靠它）。"""
        notes = [f"用了 {item.name}"]
        parts = [(item.effect, int(item.value))]
        for extra_effect, extra_value in item.extra:
            parts.append((extra_effect, int(extra_value)))
        for effect, value in parts:
            notes.extend(self._apply_item_part(run, battle, item, effect, value))
        return notes

    def _apply_item_part(self, run: dict, battle: dict | None,
                         item: Item, effect: str, value: int) -> list[str]:
        notes: list[str] = []
        if effect == "heal":
            healed = self._heal(run, value, [])
            notes.append(f"+{healed} HP")
        elif effect == "sharp":
            run["sharp"] = max(0, min(int(run.get("sharp_max") or 999),
                                      int(run["sharp"]) + value))
            notes.append(f"锋利度 {int(run['sharp'])}")
        elif effect == "atk_buff" and battle is not None:
            battle["atk_buff"] = int(battle.get("atk_buff") or 0) + value
            battle["atk_buff_turns"] = max(int(battle.get("atk_buff_turns") or 0), 3)
            if item.name == "鲸骨酒":
                self._heal(run, 15, [])
            notes.append(f"攻击 +{value}%")
        elif effect == "block" and battle is not None:
            battle["block"] = int(battle.get("block") or 0) + value
            notes.append(f"格挡 {value}")
        elif effect == "gamble":
            if self.rng.random() < 0.5:
                healed = self._heal(run, 35, [])
                notes.append(f"赌赢了：+{healed} HP")
            else:
                run["hp"] = max(0, int(run["hp"]) - 12)
                notes.append("赌输了：-12 HP")
        elif effect == "enemy_debuff" and battle is not None:
            battle["enemy_debuff"] = max(int(battle.get("enemy_debuff") or 0), 35)
            battle["enemy_debuff_turns"] = 3
            notes.append("敌人攻击 -35%")
        elif effect == "cooldown":
            run["cooldowns"] = {name: 0 for name in run.get("cooldowns", {})}
            notes.append("招式冷却清空")
        elif effect == "perm_atk":
            run["atk_bonus"] = float(run.get("atk_bonus") or 0) + value
            run["hp_flat"] = int(run.get("hp_flat") or 0) - 10
            self._refresh_max_hp(run)
            notes.append(f"攻击 +{value}%，最大生命 -10")
        elif effect == "stack_atk":
            stack = min(5, int(run.get("teeth_stacks") or 0) + 1)
            run["teeth_stacks"] = stack
            run["flat_atk"] = int(run.get("flat_atk") or 0) + value
            run["hp_flat"] = int(run.get("hp_flat") or 0) - 3
            self._refresh_max_hp(run)
            notes.append(f"攻击 +{value}（第 {stack} 层），最大生命 -3")
        elif effect == "loot":
            run["loot_buff"] = 50
            notes.append("下一场战斗银币 +50%")
        elif effect == "escape":
            if battle is not None:
                run["sharp"] = max(0, int(run["sharp"]) - SHARP_COST_FLEE)
                run["battle"] = None
                run["node"] = None
                run["mode"] = "map"
                notes.append("脱离了战斗（剑 -2 锋利度）")
        elif effect == "star" and battle is not None:
            battle["star"] = value
            battle["star_turns"] = 3
            notes.append(f"每回合 {value} 点，持续 3 回合")
        elif effect == "atk_flat":
            run["flat_atk"] = int(run.get("flat_atk") or 0) + value
            notes.append(f"攻击 +{value}")
        elif effect == "atk":
            run["atk_bonus"] = float(run.get("atk_bonus") or 0) + value
            notes.append(f"攻击 {value:+d}%")
        elif effect == "tough":
            run["tough_flat"] = int(run.get("tough_flat") or 0) + value
            notes.append(f"坚韧 +{value}")
        elif effect == "max_hp":
            run["hp_flat"] = int(run.get("hp_flat") or 0) + value
            self._refresh_max_hp(run)
            notes.append(f"最大生命 {value:+d}")
        elif effect == "self_damage":
            run["hp"] = max(0, int(run["hp"]) - value)
            notes.append(f"自己 -{value} HP")
        return notes

    def _heal(self, run: dict, amount: int, notes: list) -> int:
        amount = max(0, int(amount))
        before = int(run["hp"])
        run["hp"] = min(int(run["hp_max"]), before + amount)
        return int(run["hp"]) - before

    def _refresh_max_hp(self, run: dict) -> None:
        percent = 0.0
        relics = set(run.get("relics") or ())
        if "鲸骨护腕" in relics:
            percent -= 10
        if "贪婪之心" in relics:
            percent -= 8
        if "苦行者念珠" in relics:
            percent += 20
        if "鲸脂护符" in relics:
            percent += 12
        if "潮汐肺" in relics:
            percent += 10
        if "双生珊瑚" in relics:
            percent -= 8
        base = int(run.get("hp_base") or 1) + int(run.get("hp_flat") or 0)
        run["hp_max"] = max(10, int(round(base * (1 + percent / 100))))
        run["hp"] = min(int(run.get("hp") or run["hp_max"]), run["hp_max"])

    # ==================================================================
    # 收工 / 阵亡 / 通关
    # ==================================================================

    def _quit(self, state: Panel, run: dict, argument: str = "") -> dict:
        if run.get("challenge"):
            return self._end_challenge(state, run, False, fled=True)
        self._end_run(state, run, "quit")
        return {"ok": True, "panel": self._panel(state), "reply": ""}

    def _run_reward(self, run: dict, outcome: str) -> int:
        """这一趟带回来的鲸鳞。

        每通过一层 +1、每个首领 +3、通关 +10，再按局内银币折算；阵亡只带回一半。
        """
        scales = int(run.get("scales") or 0)
        if outcome == "clear":
            scales += SCALES_PER_CLEAR
        scales += int(int(run.get("coins") or 0) // COINS_TO_SCALES)
        if outcome == "dead":
            scales = int(scales * REWARD_DEATH_RATE)
        return scales

    def _end_run(self, state: Panel, run: dict, outcome: str) -> None:
        record = self.user(state.user)
        scales = self._run_reward(run, outcome)
        meta = record["meta"]
        meta["points"] = int(meta.get("points") or 0) + scales
        record["runs"] = int(record.get("runs") or 0) + 1
        # 通关时 plane 已经加到了 9（“下一层”不存在），结算面板上要显示成第 8 位面第 5 层
        plane = min(int(run.get("plane") or 1), MAX_PLANES)
        floor = (FLOORS_PER_PLANE if outcome == "clear"
                 else min(int(run.get("floor") or 1), FLOORS_PER_PLANE))
        summary = {
            "outcome": outcome,
            "scales": scales,
            "plane": plane,
            "floor": floor,
            "floors": int(run.get("floors_done") or 0),
            "battles": len(run.get("battles") or []),
            "sword": str(run.get("sword_name") or "剑"),
            "sharp": int(run.get("sharp") or 0),
            "points": int(meta.get("points") or 0),
        }
        record["run"] = None
        record["last_run"] = summary
        state.end = summary
        self._save()
        log(f"{SWORD_LOG} {state.name} {outcome}：位面{run.get('plane')}"
            f"第{run.get('floor')}层，+{scales} 鲸鳞")

    def _end_panel(self, state: Panel, summary: dict) -> dict:
        outcome = summary.get("outcome") or "quit"
        if outcome in ("challenge_win", "challenge_lose"):
            return self._challenge_end_panel(state, summary)
        title = {"clear": "通关！", "dead": "阵亡", "quit": "收工"}.get(outcome, "收工")
        lines = [
            f"## 宠物冒险 · {title}",
            f"走到 **位面{summary.get('plane')} · 第{summary.get('floor')}层**"
            f"（共通过 {summary.get('floors')} 层，打了 {summary.get('battles')} 场）",
            f"鲸鳞 **+{summary.get('scales')}**（现有 {summary.get('points')}）",
        ]
        if outcome == "dead":
            lines.append("这趟只捎回一半鲸鳞 —— 命比钱要紧。")
        elif outcome == "clear":
            lines.append("八个位面全清了，深海记住了你的名字。")
        else:
            lines.append("见好就收，回去磨磨刀还能再来。")
        lines.append("局内银币留在局里（商店、磨刀用），带回来的是鲸鳞；"
                     "每 150 局内银币还能再折 1 鲸鳞。")
        if summary.get("note"):
            lines.append(f"> {summary['note']}")
        if int(summary.get("sharp") or 0) <= 0:
            lines.append("⚠ 剑已经卷刃了，记得先去剑库磨刀。")
        rows = [[("回主面板", self._data(state, ACT_BACK)),
                 ("养成", self._data(state, ACT_META)),
                 ("兑换", self._data(state, ACT_EXCHANGE))]]
        return {"text": "\n".join(lines), "rows": rows}

    # ==================================================================
    # 鲸鳞兑换（场外）
    # ==================================================================

    def _exchange(self, state: Panel) -> dict:
        state.seq += 1
        return {"ok": True, "panel": self._exchange_panel(state), "reply": ""}

    def _exchange_panel(self, state: Panel, lead: str = "") -> dict:
        record = self.user(state.user)
        points = int((record.get("meta") or {}).get("points") or 0)
        vault = record.get("vault") or {}
        level = int(vault.get("silver") or 0)
        max_level = len(EXCHANGE_SILVER_COSTS)
        bonus = exchange_silver_bonus(level)
        lines = [
            "## 鲸鳞兑换",
            f"鲸鳞 **{points}**（位面塔、大挑战都能赚）",
        ]
        if lead:
            lines.append(lead)
        if level < max_level:
            cost = int(EXCHANGE_SILVER_COSTS[level])
            lines.append(
                f"**{EXCHANGE_SILVER_NAME}** Lv.{level}/{max_level} —— "
                f"每趟冒险开局多 **{bonus}** 局内银币"
                f"（升一级 {cost} 鲸鳞）"
            )
        else:
            lines.append(
                f"**{EXCHANGE_SILVER_NAME}** Lv.{level}/{max_level} —— "
                f"每趟冒险开局多 **{bonus}** 局内银币（已满级）"
            )
        stash = vault.get("items") or {}
        if stash:
            lines.append("**仓库**：" + " · ".join(
                f"{name}×{int(count)}" for name, count in stash.items()
                if int(count or 0) > 0
            ) + "（下一趟开局自动带入，最多 2 件）")
        else:
            lines.append("**仓库**：空（买下来会在下一趟开局自动带入）")
        lines.append("**兑换道具：**")
        pairs = []
        for index, (name, price) in enumerate(EXCHANGE_ITEMS):
            item = ITEMS.get(name)
            lines.append(
                f"{circled(index)}{item_line(item) if item else name} —— {price} 鲸鳞"
            )
            pairs.append((f"{circled(index)}买",
                          self._data(state, ACT_BUY_EXCHANGE, str(index))))
        rows = [pairs]
        rows.append([(EXCHANGE_SILVER_NAME, self._data(state, ACT_BUY_SILVER)),
                     ("返回", self._data(state, ACT_BACK))])
        return {"text": "\n".join(lines), "rows": rows}

    def _buy_exchange(self, state: Panel, argument: str) -> dict:
        try:
            index = int(argument)
        except (TypeError, ValueError):
            return self._say(STALE_REPLY)
        if not 0 <= index < len(EXCHANGE_ITEMS):
            return self._say(STALE_REPLY)
        name, price = EXCHANGE_ITEMS[index]
        record = self.user(state.user)
        meta = record["meta"]
        points = int(meta.get("points") or 0)
        if points < price:
            return self._say(f"鲸鳞不够：{name} 要 {price}，你只有 {points}。"
                             "去打位面塔或者大挑战赚一点吧。")
        meta["points"] = points - price
        vault = record["vault"]
        items = vault.setdefault("items", {})
        items[name] = int(items.get(name) or 0) + 1
        self._save()
        state.seq += 1
        return {"ok": True,
                "panel": self._exchange_panel(
                    state, lead=f"买下了 **{name}**，已放进仓库（开下一趟会带上）。"),
                "reply": ""}

    def _buy_silver(self, state: Panel) -> dict:
        record = self.user(state.user)
        meta = record["meta"]
        vault = record["vault"]
        level = int(vault.get("silver") or 0)
        max_level = len(EXCHANGE_SILVER_COSTS)
        if level >= max_level:
            return self._say(f"「{EXCHANGE_SILVER_NAME}」已经满级了。")
        cost = int(EXCHANGE_SILVER_COSTS[level])
        points = int(meta.get("points") or 0)
        if points < cost:
            return self._say(f"升级要 {cost} 鲸鳞，你只有 {points}。")
        meta["points"] = points - cost
        vault["silver"] = level + 1
        self._save()
        state.seq += 1
        panel = self._exchange_panel(
            state,
            lead=(f"「{EXCHANGE_SILVER_NAME}」升到 Lv.{level + 1}："
                  f"每趟开局多 {exchange_silver_bonus(level + 1)} 局内银币。"),
        )
        return {"ok": True, "panel": panel, "reply": ""}

    # ==================================================================
    # 通关存档 / 哦鲸鲸大挑战
    # ==================================================================

    # 存档只留这些字段；挑战时直接拿它重建一趟
    SNAPSHOT_KEYS = (
        "plane", "floor", "hp", "hp_max", "hp_base", "tough",
        "base_attack", "sharp", "sharp_max", "sword_id", "sword_name",
        "moves", "cooldowns", "items", "relics",
        "atk_bonus", "flat_atk", "hp_flat", "coins", "scales",
    )

    def _snapshot(self, run: dict) -> dict:
        """拍一份“拿去挑战”的快照（只留数值，不带战斗/分支那些临时状态）。"""
        raw = {key: run.get(key) for key in self.SNAPSHOT_KEYS}
        return json.loads(json.dumps(raw, ensure_ascii=False))

    # ---- 通关后询问存档 ----
    def _save_panel(self, state: Panel) -> dict:
        snapshot = state.save_snapshot or {}
        saves = self.user(state.user)["saves"]
        lines = [
            "## 通关 · 存档",
            "这一趟的终点状态（**打最后那个首领之前**的样子）可以存下来，"
            "之后拿去「哦鲸鲸大挑战」。",
            f"**{snapshot.get('sword_name') or '剑'}** · "
            f"锋锐 {int(snapshot.get('base_attack') or 0)} · "
            f"HP {int(snapshot.get('hp') or 0)}/{int(snapshot.get('hp_max') or 0)} · "
            f"锋利度 {int(snapshot.get('sharp') or 0)}",
        ]
        relics = [RELICS[name].name for name in snapshot.get("relics") or []
                  if name in RELICS]
        if relics:
            lines.append("遗物：" + " · ".join(relics))
        lines.append("**存档栏位：**")
        pairs = []
        for index in range(SAVE_SLOTS):
            entry = saves[index] if index < len(saves) else None
            if isinstance(entry, dict):
                lines.append(
                    f"{circled(index)}已占用：{entry.get('sword') or '剑'} · "
                    f"锋锐 {int(entry.get('attack') or 0)} · "
                    f"HP {int(entry.get('hp') or 0)}/{int(entry.get('hp_max') or 0)}"
                    f"（挑战 {int(entry.get('wins') or 0)} 胜 "
                    f"{int(entry.get('losses') or 0)} 负）"
                )
            else:
                lines.append(f"{circled(index)}空槽")
            pairs.append((f"{circled(index)}存入",
                          self._data(state, ACT_SAVE, str(index))))
        rows = [pairs]
        rows.append([("不保存", self._data(state, ACT_NO_SAVE))])
        return {"text": "\n".join(lines), "rows": rows}

    def _save_confirm_panel(self, state: Panel) -> dict:
        slot = int(state.save_confirm or 0)
        saves = self.user(state.user)["saves"]
        entry = saves[slot] if 0 <= slot < len(saves) else None
        lines = [
            f"## 覆盖 {circled(slot)} 号存档？",
            ("这个栏位已经有一个档了："
             f"**{entry.get('sword') or '剑'}** · 锋锐 {int(entry.get('attack') or 0)}"
             f" · HP {int(entry.get('hp') or 0)}/{int(entry.get('hp_max') or 0)}"
             if isinstance(entry, dict) else "这个栏位现在是空的。"),
            "覆盖之后旧档就没了（挑战胜场也会重新算）。",
        ]
        rows = [[("覆盖", self._data(state, ACT_SAVE_REPLACE)),
                 ("取消", self._data(state, ACT_SAVE_CANCEL))]]
        return {"text": "\n".join(lines), "rows": rows}

    def _save_choose(self, state: Panel, argument: str) -> dict:
        if not state.save_snapshot:
            return self._say("现在没有要存的通关记录。")
        try:
            slot = int(argument)
        except (TypeError, ValueError):
            return self._say(STALE_REPLY)
        if not 0 <= slot < SAVE_SLOTS:
            return self._say(STALE_REPLY)
        saves = self.user(state.user)["saves"]
        if isinstance(saves[slot], dict):
            state.save_confirm = slot
            return {"ok": True, "panel": self._panel(state), "reply": ""}
        self._store_save(state, slot)
        return {"ok": True, "panel": self._panel(state), "reply": ""}

    def _save_replace(self, state: Panel) -> dict:
        if state.save_confirm is None or not state.save_snapshot:
            return self._say(STALE_REPLY)
        self._store_save(state, int(state.save_confirm))
        return {"ok": True, "panel": self._panel(state), "reply": ""}

    def _save_cancel(self, state: Panel) -> dict:
        state.save_confirm = None
        return {"ok": True, "panel": self._panel(state), "reply": ""}

    def _no_save(self, state: Panel) -> dict:
        record = self.user(state.user)
        record["pending_save"] = None
        if state.end:
            state.end["note"] = "（这一趟没有存档）"
        state.save_snapshot = None
        state.save_confirm = None
        return {"ok": True, "panel": self._panel(state), "reply": ""}

    def _store_save(self, state: Panel, slot: int) -> None:
        record = self.user(state.user)
        snapshot = dict(state.save_snapshot or {})
        record["saves"][slot] = {
            "state": snapshot,
            "saved_at": int(time.time()),
            "sword": snapshot.get("sword_name") or "剑",
            "attack": int(snapshot.get("base_attack") or 0),
            "hp": int(snapshot.get("hp") or 0),
            "hp_max": int(snapshot.get("hp_max") or 0),
            "wins": 0,
            "losses": 0,
        }
        record["pending_save"] = None
        if state.end:
            state.end["note"] = f"已存入 {circled(slot)} 号存档"
        state.save_snapshot = None
        state.save_confirm = None
        self._save()
        log(f"{SWORD_LOG} {state.name} 通关存档写入 {slot + 1} 号栏位")

    # ---- 哦鲸鲸大挑战 ----
    def _challenge(self, state: Panel) -> dict:
        state.seq += 1
        return {"ok": True, "panel": self._challenge_panel(state), "reply": ""}

    def _challenge_panel(self, state: Panel) -> dict:
        record = self.user(state.user)
        saves = record["saves"]
        lines = [
            "## 哦鲸鲸大挑战",
            "用通关存档去挑战三位首领，**每次随机出现一位**。",
            "· **海德软脚虾** —— 残血会锁血进二阶段，二阶段的北国沙鹰虾"
            "会在防御时反弹你的攻击",
            "· **显卡吞噬者老黄** —— 攻击有概率让你麻痹，麻痹时防守失效",
            "· **川建国** —— 你的攻击有 20% 被弹开，它每回合还会自己回血",
            "**存档：**",
        ]
        pairs = []
        for index in range(SAVE_SLOTS):
            entry = saves[index] if index < len(saves) else None
            if isinstance(entry, dict):
                lines.append(
                    f"{circled(index)}{entry.get('sword') or '剑'} · "
                    f"锋锐 {int(entry.get('attack') or 0)} · "
                    f"HP {int(entry.get('hp') or 0)}/{int(entry.get('hp_max') or 0)}"
                    f"（{int(entry.get('wins') or 0)} 胜 "
                    f"{int(entry.get('losses') or 0)} 负）"
                )
            else:
                lines.append(f"{circled(index)}空槽 —— 先通关一次再存档")
            pairs.append((f"{circled(index)}挑战",
                          self._data(state, ACT_CHALLENGE_SLOT, str(index))))
        rows = [pairs]
        rows.append([("返回", self._data(state, ACT_BACK))])
        return {"text": "\n".join(lines), "rows": rows}

    def _start_challenge(self, state: Panel, argument: str) -> dict:
        record = self.user(state.user)
        try:
            slot = int(argument)
        except (TypeError, ValueError):
            return self._say(STALE_REPLY)
        saves = record["saves"]
        if not 0 <= slot < SAVE_SLOTS or not isinstance(saves[slot], dict):
            return self._say("这个栏位还没有存档。先通关一次位面塔，"
                             "通关时选择「存入」。")
        if record.get("run"):
            if (record["run"] or {}).get("challenge"):
                return self._say("挑战还没打完，先把这一场走完（或者收工）。")
            return self._say("位面塔那一趟还没走完，先打完（或者收工）再来挑战。")
        snapshot = saves[slot]["state"]
        boss = challenge_boss(self.rng)
        run = json.loads(json.dumps(
            {key: snapshot.get(key) for key in self.SNAPSHOT_KEYS},
            ensure_ascii=False))
        run["id"] = self._new_id([p.panel_id for p in self._panels.values()])
        run["owner"] = state.user
        run["mode"] = "battle"
        run["options"] = []
        run["node"] = None
        run["pending"] = None
        run["note"] = ""
        run["challenge"] = {"slot": slot, "boss": boss.key, "phase": 1}
        battle = {
            "name": boss.name, "kind": KIND_BOSS,
            "hp": int(boss.hp), "hp_max": int(boss.hp),
            "attack": int(boss.attack),
            "moves": (), "turn": 1, "block": 0, "bleed": 0,
            "player_bleed": 0, "first": True,
            "atk_buff": 0, "atk_buff_turns": 0,
            "enemy_debuff": 0, "enemy_debuff_turns": 0,
            "star": 0, "star_turns": 0, "loot": 0,
            "flavor": boss.desc, "challenge": True,
            "boss_key": boss.key, "challenge_phase": 1,
            "paralyzed": 0,
        }
        run["battle"] = battle
        battle["intent"] = self._next_intent(run, battle)
        record["run"] = run
        state.panel_id = self._new_id([p.panel_id for p in self._panels.values()])
        run["note"] = f"挑战开始：{boss.name} 挡在面前"
        self._save()
        log(f"{SWORD_LOG} {state.name} 用 {slot + 1} 号存档挑战 {boss.name}")
        return {"ok": True, "panel": self._panel(state, run), "reply": ""}

    def _next_intent(self, run: dict, battle: dict) -> dict:
        """下一回合敌人要干什么：普通怪按招式表抽，挑战首领按各自的套路。"""
        if battle.get("challenge"):
            boss = CHALLENGE_BY_KEY.get(battle.get("boss_key") or "")
            if boss is None:
                return {"name": "攻击", "multiplier": 1.0, "effect": ""}
            if (boss.reflect and int(battle.get("challenge_phase") or 1) >= 2
                    and int(battle.get("turn") or 1) % 2 == 0):
                return {"name": "沙鹰硬壳", "multiplier": 0.0, "effect": "reflect"}
            if boss.paralyze:
                return {"name": "显卡过热拍击", "multiplier": 1.2,
                        "effect": "paralyze"}
            if boss.dodge:
                return {"name": "关税重锤", "multiplier": 1.2, "effect": ""}
            return {"name": "软壳乱戳", "multiplier": 1.1, "effect": ""}
        moves = battle.get("moves") or (("攻击", 1.0, ""),)
        return move_intent({"moves": moves}, self.rng)

    def _challenge_phase(self, battle: dict, notes: list) -> bool:
        """海德软脚虾：一阶段血量被打空就锁血，切到北国沙鹰虾。返回是否转了阶段。"""
        if not battle.get("challenge"):
            return False
        boss = CHALLENGE_BY_KEY.get(battle.get("boss_key") or "")
        if boss is None or not boss.phase2_name:
            return False
        if int(battle.get("challenge_phase") or 1) != 1:
            return False
        if int(battle.get("hp") or 0) > 0:
            return False
        battle["hp"] = int(boss.phase2_hp)
        battle["hp_max"] = int(boss.phase2_hp)
        battle["attack"] = int(boss.phase2_attack)
        battle["name"] = boss.phase2_name
        battle["challenge_phase"] = 2
        battle["intent"] = self._next_intent({}, battle)
        notes.append("**锁血！** 海德软脚虾缩进壳里 —— 二阶段：北国沙鹰虾")
        return True

    def _end_challenge(self, state: Panel, run: dict, win: bool,
                       fled: bool = False) -> dict:
        record = self.user(state.user)
        info = run.get("challenge") or {}
        slot = int(info.get("slot") or 0)
        boss = CHALLENGE_BY_KEY.get(info.get("boss") or "")
        saved = (record["saves"][slot]
                 if 0 <= slot < len(record["saves"]) else None)
        if isinstance(saved, dict):
            key = "wins" if win else "losses"
            saved[key] = int(saved.get(key) or 0) + 1
        turns = int((run.get("battle") or {}).get("turn") or 1)
        scales = CHALLENGE_SCALES if win else 0
        meta = record["meta"]
        meta["points"] = int(meta.get("points") or 0) + scales
        record["challenge_runs"] = int(record.get("challenge_runs") or 0) + 1
        record["challenge_wins"] = (int(record.get("challenge_wins") or 0)
                                    + (1 if win else 0))
        record["run"] = None
        summary = {
            "outcome": "challenge_win" if win else "challenge_lose",
            "scales": scales,
            "turns": turns,
            "slot": slot, "boss": boss.name if boss else "首领",
            "points": int(meta.get("points") or 0),
            "fled": bool(fled),
        }
        record["last_challenge"] = summary
        state.end = summary
        self._save()
        log(f"{SWORD_LOG} {state.name} 挑战{boss.name if boss else '首领'}"
            f"{'成功' if win else '失败'}（{slot + 1} 号存档）")
        return {"ok": True, "panel": self._panel(state), "reply": ""}

    def _challenge_end_panel(self, state: Panel, summary: dict) -> dict:
        win = summary.get("outcome") == "challenge_win"
        title = "挑战成功！" if win else ("挑战中止" if summary.get("fled")
                                          else "挑战失败")
        lines = [
            f"## 哦鲸鲸大挑战 · {title}",
            f"对手：**{summary.get('boss') or '首领'}**"
            f"（{circled(int(summary.get('slot') or 0))} 号存档）",
        ]
        if win:
            lines.append(f"鲸鳞 **+{summary.get('scales')}**（现有 "
                         f"{summary.get('points')}）")
            lines.append(f"用了 {summary.get('turns')} 回合解决。")
            lines.append("这份存档还留着，可以接着挑战。")
        else:
            lines.append("这一趟没打赢，存档还在，磨磨刀再来。")
        rows = [[("再挑战", self._data(state, ACT_CHALLENGE)),
                 ("回主面板", self._data(state, ACT_BACK))]]
        return {"text": "\n".join(lines), "rows": rows}

    # ==================================================================
    # 存档小工具
    # ==================================================================

    def _run(self, user: str) -> dict | None:
        run = self.user(user).get("run")
        if not isinstance(run, dict) or not run.get("id"):
            return None
        run["owner"] = str(user)
        return run
