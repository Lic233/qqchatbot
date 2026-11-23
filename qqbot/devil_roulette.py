"""恶魔轮盘赌 · 群友版（复刻 Buckshot Roulette）：单人打大肥鱼 / 双人对赌。

互动全部走 ``panel.py`` 的按钮面板：发「恶魔轮盘赌」开主菜单，之后点按钮就行。

玩法
----
一把 12 号霰弹枪，弹匣里混着实弹（红色）和空包（白色），**顺序随机、双方都只知道
总数**。轮流开枪，可以朝自己也可以朝对方：

* 实弹打中：目标掉 1 点电（手锯 ×2）；
* **朝自己开空包：枪还归你**，可以接着开，这是核心的心理博弈；
* 朝对方开（不管实弹空包）或者朝自己开实弹：交枪。

双方各 **5 点电**，谁先掉到 0 谁输 —— **一局打到有人电量为 0 才结算**。
弹匣打空只是补一轮新弹（每轮每人补发 2 件道具），**血量不会回满**，
所以前面挨的枪会一直跟着你。

两种模式
--------
* **道具模式**：每轮每人发 2 件道具，九件套照原版：放大镜 / 香烟 / 啤酒 / 手锯 /
  手铐 / 逆变器 / 电话 / 药丸 / 肾上腺素。
* **纯赌模式**：一件道具都没有，纯看弹匣和胆子。

入场门槛费（银币，和抽卡 / 锻造同一个钱包）
------------------------------------------
* 道具模式：入场 100，赢了返还 140（×1.4），输了**全部赔掉**；
* 纯赌模式：入场 100，赢了返还 120（×1.2），输了**返还一半**（50）；
* 双人局两边各自交、各自按上面的规则结算，谁的输赢算谁的。
* 余额不够就开不了局（会直接告诉你差多少）；超时散桌原路全退。

三种对局
--------
* **单人**：对手是大肥鱼。它偶尔会冒一句奶凶的狠话震慑你，被你电趴下会**很不甘心**。
* **双人**：``恶魔轮盘赌 @对方`` 定向挑战（只有被点名的能点接受），
  或者主菜单「公开挑战」摆一桌谁都能接；接受时自己选道具 / 纯赌。

榜单
----
主菜单**最上面就是本群榜**（胜场 → 负场 → 最长连胜）。每局结束记胜负，
落盘 ``data/devil_roulette_rank.json``，按群分开，重启还在。
对局面板里不重复贴榜单，省得刷屏。

群里的一个已知取舍
------------------
QQ 群机器人没有「私聊」，放大镜 / 电话看到的情报会写在公开面板上 —— 也就是说
**PvP 里情报是全群可见的**。所以双人局的情报要当「公开牌」打：先看到的人先动手，
后面的人只是知道得晚一点。规则文档里也写明了这一点。

会话只在内存里（和 CS、弗一把一样），重启就散场；榜单才是落盘的。
"""
from __future__ import annotations

from .base import *  # noqa: F401,F403
from .devil_roulette_data import (
    DEFEAT_LINES,
    FISH_ID,
    FISH_NAME,
    HIT_LINES,
    HURT_LINES,
    ITEMS,
    ITEM_ORDER,
    MAX_HP,
    MAX_ITEMS,
    MODE_NAMES,
    PLAYER_LOSE_LINES,
    PLAYER_WIN_LINES,
    TAUNTS,
    WIN_LINES,
)

# --------------------------------------------------------------------------
# 常量
# --------------------------------------------------------------------------

DEVIL_LOG = "[恶魔轮盘赌]"
PANEL_PREFIX = "轮盘"

RANK_FILE = "devil_roulette_rank.json"
RANK_TOP = 3                    # 主菜单 / 结算面板上带的前三名

SESSION_TTL = 30 * 60.0         # 半小时没人动就散桌
INVITE_TTL = 180.0              # 挑战 3 分钟没人接就作废
AI_MAX_STEPS = 12               # 大肥鱼一次最多连着做几个动作（防死循环）
TAUNT_CHANCE = 0.42             # 大肥鱼每动一下冒狠话的概率

DEAL_PER_ROUND = 2              # 道具模式每轮每人发几件
# 每轮的弹匣：(实弹, 空包)。和原版一样，越往后越凶。
RACK_PLAN = ((2, 1), (3, 2), (4, 3), (4, 4))
MAX_ROUNDS_PLAN = len(RACK_PLAN)

# 入场门槛费：和抽卡 / 锻造同一个「银币」钱包。
# 赢了按倍率返还入场费，输了按 refund_on_loss 退（0 = 全赔）。
ENTRY_FEE = 100
MODE_RULES = {
    "道具": {"multiplier": 1.4, "refund_on_loss": 0.0},
    "纯赌": {"multiplier": 1.2, "refund_on_loss": 0.5},
}

ID_ALPHABET = "23456789abcdefghjkmnpqrstuvwxyz"
ID_LENGTH = 6

# ---- 文字命令（比较时把空白全去掉、转小写）----
MENU_COMMANDS = ("恶魔轮盘赌", "恶魔轮盘", "轮盘赌", "恶魔轮盘赌菜单", "轮盘赌菜单")
RANK_COMMANDS = (
    "恶魔轮盘赌榜单", "恶魔轮盘赌排行", "恶魔轮盘赌排行榜",
    "轮盘赌榜单", "轮盘赌排行", "轮盘赌排行榜",
)
RULE_COMMANDS = (
    "恶魔轮盘赌规则", "恶魔轮盘赌玩法", "恶魔轮盘赌道具说明",
    "轮盘赌规则", "轮盘赌玩法", "轮盘赌道具说明", "道具说明",
)
STATUS_COMMANDS = ("恶魔轮盘赌状态", "轮盘赌状态", "恶魔轮盘赌进度")
END_COMMANDS = (
    "恶魔轮盘赌结束", "恶魔轮盘赌认输", "轮盘赌结束", "轮盘赌认输",
    "认输", "跑路",
)

# ---- 面板按钮的动作码（data = 轮盘 <id> <seq> <动作> [参数]）----
ACT_SOLO = "单"      # 单人开局（参数：道具 / 纯赌）
ACT_OPEN = "公"      # 公开挑战
ACT_DIRECT = "定"    # 定向挑战的说明
ACT_MENU = "菜"      # 回主菜单
ACT_RANK = "榜"      # 完整榜单
ACT_RULE = "规"      # 玩法 / 道具说明
ACT_ACCEPT = "接"    # 接受挑战（参数：道具 / 纯赌）
ACT_REFUSE = "拒"    # 拒绝挑战
ACT_SELF = "自"      # 朝自己开枪
ACT_SHOOT = "打"     # 朝对方开枪
ACT_USE = "用"       # 用道具（参数：道具名）
ACT_QUIT = "降"      # 认输
ACT_REMATCH = "再"   # 再来一局

MENU_KEYS = frozenset("".join(item.split()).casefold() for item in MENU_COMMANDS)
RANK_KEYS = frozenset("".join(item.split()).casefold() for item in RANK_COMMANDS)
RULE_KEYS = frozenset("".join(item.split()).casefold() for item in RULE_COMMANDS)
STATUS_KEYS = frozenset("".join(item.split()).casefold() for item in STATUS_COMMANDS)
END_KEYS = frozenset("".join(item.split()).casefold() for item in END_COMMANDS)

NO_GAME_REPLY = "现在没在打恶魔轮盘赌喵，发「恶魔轮盘赌」开一桌。"
STALE_REPLY = "这条面板已经用过了喵，看最新发的那条。"
NO_SESSION_REPLY = "这张面板翻篇了，发「恶魔轮盘赌」重新开一张吧。"
NOT_YOUR_TABLE = "这一桌没你的位置喵，自己开一桌去。"
NOT_YOUR_TURN = "现在不是你的回合喵，把枪放下。"


# --------------------------------------------------------------------------
# 面板按钮的 data
# --------------------------------------------------------------------------


def panel_data(panel_id: str, seq: int, action: str, argument: str = "") -> str:
    parts = [PANEL_PREFIX, panel_id, str(seq), action]
    if argument:
        parts.append(argument)
    return " ".join(parts)


def parse_panel_data(text: str) -> tuple[str, int, str, str] | None:
    parts = (text or "").strip().split()
    if len(parts) < 4 or parts[0] != PANEL_PREFIX:
        return None
    try:
        seq = int(parts[2])
    except (TypeError, ValueError):
        return None
    return parts[1], seq, parts[3], (parts[4] if len(parts) > 4 else "")


# --------------------------------------------------------------------------
# 数据模型
# --------------------------------------------------------------------------


@dataclass
class Player:
    """桌上的一方：玩家或大肥鱼。"""

    user: str
    name: str
    hp: int = MAX_HP
    items: list[str] = field(default_factory=list)
    cuffed: bool = False        # 被手铐锁着，下一回合跳过
    saw: bool = False           # 手锯生效中，下一发伤害 ×2
    ai: bool = False
    paid: int = 0               # 这一局实际交了多少入场费（结算按它退）


@dataclass
class Game:
    """一局（一个群同时只有一桌）。"""

    gid: str
    group: str
    mode: str                       # "道具" / "纯赌"
    players: list[Player]           # 0 先手（单人时是人类）
    solo: bool = False
    turn: int = 0
    round: int = 0
    shells: list[bool] = field(default_factory=list)   # True=实弹
    idx: int = 0
    revealed: dict[int, bool] = field(default_factory=dict)  # 已经公开的弹位
    seq: int = 0
    log: list[str] = field(default_factory=list)
    human_note: str = ""        # 玩家上一手（面板只显示这一条 + 大肥鱼那一手）
    ai_note: str = ""           # 大肥鱼上一手
    sys_note: str = ""          # 换弹 / 被锁这类小播报
    taunt: str = ""
    over: bool = False
    winner: str = ""
    started_at: float = 0.0
    last_at: float = 0.0
    finished_at: float = 0.0
    # 结算时填的面板文案（只在内存里）
    end_flavor: str = ""
    end_fish: str = ""
    end_records: list = field(default_factory=list)
    refunds: list = field(default_factory=list)   # [(名字, 入场, 返还)]

    @property
    def current(self) -> Player:
        return self.players[self.turn]

    @property
    def other(self) -> Player:
        """当前回合的对家（认输的那个人不一定是当前回合，别拿这个算输赢）。"""
        return self.players[1 - self.turn]

    def player_of(self, user: str) -> Player | None:
        for player in self.players:
            if player.user == str(user):
                return player
        return None


@dataclass
class Menu:
    """一张主菜单面板（每个人的菜单序号各自独立）。"""

    panel_id: str
    group: str
    user: str
    seq: int = 0


@dataclass
class Invite:
    """一张挑战帖：``target`` 为空就是公开挑战。"""

    iid: str
    group: str
    challenger: str
    challenger_name: str
    target: str = ""
    target_name: str = ""
    seq: int = 0
    created_at: float = 0.0


# --------------------------------------------------------------------------
# 引擎
# --------------------------------------------------------------------------


class DevilRoulette:
    """恶魔轮盘赌的会话管理 + 规则实现。

    对局只在内存里；**榜单**落盘到 ``data/devil_roulette_rank.json``。
    """

    def __init__(self, data_dir=None, cards=None, rng=None, now=None) -> None:
        # cards 收银机：可以传实例，也可以传 ``lambda: handler.cards`` ——
        # handler 里的钱包偶尔会被整体替换（自检、热改配置），惰性取才不会拿旧账本。
        self._cards = cards            # None = 不收钱（纯引擎用法）
        self.rng = rng or random.Random()
        self.now = now or time.time
        self._games: dict[str, Game] = {}
        self._finished: dict[str, Game] = {}
        self._menus: dict[tuple[str, str], Menu] = {}
        self._invites: dict[str, Invite] = {}
        self.path = (Path(data_dir) / RANK_FILE) if data_dir else None
        self._rank = self._load_rank()

    @property
    def cards(self):
        return self._cards() if callable(self._cards) else self._cards

    # ==================================================================
    # 榜单
    # ==================================================================

    def _load_rank(self) -> dict[str, dict[str, dict]]:
        if self.path is None:
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            return {}
        if not isinstance(payload, dict):
            return {}
        return {
            str(group): {str(user): entry for user, entry in board.items()
                         if isinstance(entry, dict)}
            for group, board in payload.items() if isinstance(board, dict)
        }

    def _save_rank(self) -> None:
        if self.path is None:
            return
        temporary = self.path.with_name("devil_roulette_rank.tmp")
        try:
            temporary.write_text(
                json.dumps(self._rank, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            temporary.replace(self.path)
        except OSError as error:
            log(f"{DEVIL_LOG} 榜单保存失败：{error}")

    @staticmethod
    def _entry(entry: dict) -> dict:
        return {
            "wins": int(entry.get("wins") or 0),
            "losses": int(entry.get("losses") or 0),
            "streak": int(entry.get("streak") or 0),
            "best": int(entry.get("best") or 0),
        }

    @staticmethod
    def _sorted_board(board: dict[str, dict]) -> list[tuple[str, dict]]:
        """胜场多的在前；胜场一样就比谁输得少，再比最长连胜。"""
        def key(pair: tuple[str, dict]) -> tuple:
            entry = pair[1]
            return (
                -int(entry.get("wins") or 0),
                int(entry.get("losses") or 0),
                -int(entry.get("best") or 0),
                -int(entry.get("last") or 0),
                str(entry.get("name") or ""),
            )

        return sorted(board.items(), key=key)

    def leaderboard(self, group: str, limit: int = 10) -> list[dict]:
        board = self._rank.get(str(group), {})
        rows = []
        for index, (user, entry) in enumerate(self._sorted_board(board)):
            if index >= limit:
                break
            stats = self._entry(entry)
            rows.append({
                "rank": index + 1,
                "user": user,
                "name": str(entry.get("name") or "群友"),
                **stats,
            })
        return rows

    def record(self, group: str, user: str, name: str, win: bool) -> dict:
        """记一局胜负，返回这个人的累计战绩和本群排名。"""
        board = self._rank.setdefault(str(group), {})
        entry = board.setdefault(
            str(user),
            {"name": name, "wins": 0, "losses": 0, "streak": 0,
             "best": 0, "last": 0},
        )
        entry["name"] = (name or str(entry.get("name") or "群友")).strip() or "群友"
        if win:
            entry["wins"] = int(entry.get("wins") or 0) + 1
            entry["streak"] = int(entry.get("streak") or 0) + 1
            entry["best"] = max(int(entry.get("best") or 0), int(entry["streak"]))
        else:
            entry["losses"] = int(entry.get("losses") or 0) + 1
            entry["streak"] = 0
        entry["last"] = int(self.now())
        self._save_rank()
        return self.stats_of(group, user)

    def stats_of(self, group: str, user: str) -> dict:
        """读这个人在本群的最新战绩与排名（结算时所有人记完再统一取）。"""
        board = self._rank.get(str(group), {})
        entry = board.get(str(user)) or {}
        ranked = [key for key, _ in self._sorted_board(board)]
        rank = ranked.index(str(user)) + 1 if str(user) in ranked else len(ranked)
        return {**self._entry(entry), "rank": rank, "total": len(board)}

    def board_text(self, group: str, limit: int = 10) -> str:
        rows = self.leaderboard(group, limit)
        header = "🏆 本群恶魔轮盘赌榜（按胜场排）"
        if not rows:
            return (header + "\n还空着喵，赢一局就能上榜。\n"
                    "发「恶魔轮盘赌」开一桌吧。")
        lines = [header]
        for row in rows:
            line = f"{row['rank']}. {row['name']} — {row['wins']} 胜 {row['losses']} 负"
            if row["best"] >= 2:
                line += f"（最长 {row['best']} 连胜）"
            lines.append(line)
        lines.append(f"共 {len(self._rank.get(str(group), {}))} 人上榜。")
        return "\n".join(lines)

    def _board_line(self, group: str, limit: int = RANK_TOP) -> str:
        rows = self.leaderboard(group, limit)
        if not rows:
            return "🏆 本群榜还空着，赢一局就是榜首喵。"
        return "🏆 本群榜：" + "　".join(
            f"{row['rank']}.{row['name']} {row['wins']}胜" for row in rows
        )

    # ==================================================================
    # 会话管理
    # ==================================================================

    @staticmethod
    def _key(text: str) -> str:
        return "".join((text or "").split()).casefold()

    def _new_id(self) -> str:
        used = {menu.panel_id for menu in self._menus.values()}
        used |= set(self._invites)
        used |= {game.gid for game in self._games.values()}
        for _ in range(50):
            value = "".join(self.rng.choice(ID_ALPHABET) for _ in range(ID_LENGTH))
            if value not in used:
                return value
        return f"{int(self.now() * 1000) % 10 ** 8:08x}"

    def active(self, group: str) -> Game | None:
        """这个群正在打的那一桌（超时就顺手散掉，入场费原路退回）。"""
        game = self._games.get(str(group))
        if game is None:
            return None
        if self.now() - game.last_at > SESSION_TTL:
            self._games.pop(str(group), None)
            self._refund_timeout(game)
            log(f"{DEVIL_LOG} 超时散桌（{game.mode}，第 {game.round} 轮）")
            return None
        return game

    # ---- 入场费 ----

    def balance_of(self, user: str) -> int | None:
        """这个人的银币余额；没接钱包时返回 None（界面就不显示钱）。"""
        if self.cards is None:
            return None
        return int(self.cards.shards_of(str(user)))

    def _charge(self, players: list[Player], mode: str) -> str | None:
        """收入场费：有人不够就一分不收，返回一句提示。"""
        if self.cards is None:
            return None
        short = [
            player for player in players
            if not player.ai and self.cards.shards_of(player.user) < ENTRY_FEE
        ]
        if short:
            player = short[0]
            have = self.cards.shards_of(player.user)
            return (f"{player.name} 银币不够：入场要 {ENTRY_FEE}，"
                    f"现在只有 {have}。签到 / 锻造都能攒喵。")
        for player in players:
            if player.ai:
                continue
            self.cards.spend_shards(player.user, ENTRY_FEE)
            player.paid = ENTRY_FEE
        return None

    def _payout(self, game: Game, winner: Player) -> list:
        """按模式结算：赢家拿倍率，输家按模式退。返回 [(名字, 入场, 返还)]。"""
        rule = MODE_RULES.get(game.mode, MODE_RULES["道具"])
        rows = []
        for player in game.players:
            if player.ai or player.paid <= 0:
                continue
            rate = rule["multiplier"] if player is winner \
                else rule["refund_on_loss"]
            refund = int(round(player.paid * rate))
            if refund and self.cards is not None:
                self.cards.grant_shards(player.user, refund)
            rows.append((player.name, player.paid, refund))
            player.paid = 0
        return rows

    def _refund_timeout(self, game: Game) -> None:
        """超时散桌不是输，入场费原路全退。"""
        for player in game.players:
            if player.ai or player.paid <= 0:
                continue
            if self.cards is not None:
                self.cards.grant_shards(player.user, player.paid)
                log(f"{DEVIL_LOG} 超时，退给 {player.name} {player.paid} 银币")
            player.paid = 0

    def game_of(self, group: str, user: str) -> Game | None:
        game = self.active(group)
        if game is not None and game.player_of(user) is not None:
            return game
        return None

    def clear(self) -> None:
        """自检用：把所有局清掉（榜单不动，已交的入场费不退）。"""
        self._games.clear()
        self._finished.clear()
        self._menus.clear()
        self._invites.clear()

    def _prune(self) -> None:
        """顺手清掉过期的挑战帖 / 结算面板（对局在 active() 里清）。"""
        now = self.now()
        for iid, invite in list(self._invites.items()):
            if now - invite.created_at > INVITE_TTL:
                self._invites.pop(iid, None)
        for gid, game in list(self._finished.items()):
            if now - game.finished_at > SESSION_TTL:
                self._finished.pop(gid, None)

    def _menu_state(self, group: str, user: str) -> Menu:
        key = (str(group), str(user))
        state = self._menus.get(key)
        if state is None:
            state = Menu(panel_id=self._new_id(), group=key[0], user=key[1])
            self._menus[key] = state
        return state

    # ==================================================================
    # 对外入口
    # ==================================================================

    def handle(self, text: str, group: str, user: str, name: str = "",
               opponents=()) -> dict | None:
        """认一条消息：开菜单 / 开局 / 点按钮。

        返回 ``{"panel": ...}`` 表示要发面板，``{"reply": "..."}`` 表示只回一句话，
        ``None`` 表示不归我管（交给别的命令或闲聊）。

        ``opponents`` 是这条消息里 @ 到的人 ``[(openid, 昵称), ...]``，
        handler 从 ``event.mention_ids`` 里解析好传进来。
        """
        raw = (text or "").strip()
        if not raw:
            return None
        group = str(group or "")
        user = str(user or "")
        name = (name or "").strip() or "群友"

        parsed = parse_panel_data(raw)
        if parsed is not None:
            pid, seq, action, argument = parsed
            return self._act(group, user, pid, seq, action, argument, name)

        # 清理过期东西放在面板点击之后：点一张过期的挑战帖应该回「过期了」，
        # 而不是回「面板翻篇了」（帖子的 seq 还能对上，由 _invite_action 自己判）。
        self._prune()
        key = self._key(raw)

        if key in RANK_KEYS:
            return self._rank_panel(group, user, name)
        if key in RULE_KEYS:
            return self._rules_reply()
        if key in END_KEYS:
            game = self.game_of(group, user)
            if game is None:
                return None          # 没在打的时候「认输」就是普通闲聊
            return self._give_up(game, game.player_of(user))
        if key in STATUS_KEYS:
            game = self.game_of(group, user)
            if game is None:
                return {"reply": NO_GAME_REPLY}
            return {"panel": self._game_panel(game)}
        if key in MENU_KEYS:
            target = self._pick_opponent(user, opponents)
            if target is not None:
                return self._invite_from_text(group, user, name, target)
            game = self.game_of(group, user)
            if game is not None:
                return {"panel": self._game_panel(game)}
            return {"panel": self._menu_panel(group, user, name)}
        return None

    @staticmethod
    def _pick_opponent(user: str, opponents) -> tuple[str, str] | None:
        """从 @ 列表里挑一个真正的对手（跳过自己、跳过空气）。"""
        for item in opponents or ():
            try:
                openid, nickname = item
            except (TypeError, ValueError):
                continue
            openid = str(openid or "").strip()
            if not openid or openid == user:
                continue
            return openid, (str(nickname or "").strip() or "群友")
        return None

    # ==================================================================
    # 动作分发
    # ==================================================================

    def _act(self, group: str, user: str, pid: str, seq: int, action: str,
             argument: str, name: str) -> dict:
        menu = self._menus.get((group, user))
        if menu is not None and menu.panel_id == pid:
            if menu.seq != seq:
                return self._stale()
            return self._menu_action(group, user, name, action, argument)

        invite = self._invites.get(pid)
        if invite is not None:
            if invite.seq != seq:
                return self._stale()
            return self._invite_action(group, user, name, invite, action, argument)

        finished = self._finished.get(pid)
        if finished is not None:
            if finished.seq != seq:
                return self._stale()
            return self._game_action(group, user, name, finished, action, argument)

        game = self.active(group)
        if game is not None and game.gid == pid:
            if game.seq != seq:
                return self._stale()
            return self._game_action(group, user, name, game, action, argument)

        return self._reply(NO_SESSION_REPLY)

    # ---- 主菜单 ----

    def _menu_panel(self, group: str, user: str, name: str = "") -> dict:
        state = self._menu_state(group, user)
        state.seq += 1
        gid, seq = state.panel_id, state.seq
        game = self.active(group)
        lines = [
            "# 🔫 恶魔轮盘赌",
            self._board_line(group),
            "",
            f"**{MAX_HP} 点电** · 实弹 −1 · **打自己空包不交枪**",
            (f"💰 入场 {ENTRY_FEE} 银币：道具赢 {self._refund('道具', True)} / 输全赔 · "
             f"纯赌赢 {self._refund('纯赌', True)} / 输退 {self._refund('纯赌', False)}"),
        ]
        balance = self.balance_of(user)
        if balance is not None:
            lines.append(f"你的银币：{balance}")
        if game is not None:
            lines.append("⚠️ 这个群有一桌在打了，等他们打完喵。")
        rows = [
            [("单人·道具", panel_data(gid, seq, ACT_SOLO, "道具")),
             ("单人·纯赌", panel_data(gid, seq, ACT_SOLO, "纯赌"))],
            [("公开挑战", panel_data(gid, seq, ACT_OPEN)),
             ("定向挑战", panel_data(gid, seq, ACT_DIRECT))],
            [("完整榜单", panel_data(gid, seq, ACT_RANK)),
             ("玩法规则", panel_data(gid, seq, ACT_RULE))],
        ]
        return {"text": "\n".join(lines), "rows": rows,
                "user_ids": [user] if user else []}

    @staticmethod
    def _refund(mode: str, win: bool) -> int:
        """入场费在这个模式下的返还额（菜单和文案共用一套口径）。"""
        rule = MODE_RULES.get(mode, MODE_RULES["道具"])
        rate = rule["multiplier"] if win else rule["refund_on_loss"]
        return int(round(ENTRY_FEE * rate))

    def _menu_action(self, group: str, user: str, name: str, action: str,
                     argument: str) -> dict:
        if action == ACT_MENU:
            return {"panel": self._menu_panel(group, user, name)}
        if action == ACT_RANK:
            return self._rank_panel(group, user, name)
        if action == ACT_RULE:
            return self._rules_reply()
        if action == ACT_DIRECT:
            return self._reply(
                "想跟谁打，就发一句「恶魔轮盘赌 @对方」喵 —— "
                "对方的手机会弹出一张挑战帖，点接受就开局。"
            )
        if action == ACT_SOLO:
            return self._start_solo(group, user, name, argument)
        if action == ACT_OPEN:
            return self._open_invite(group, user, name)
        return self._stale()

    # ---- 单人与双人开局 ----

    def _start_solo(self, group: str, user: str, name: str, argument: str) -> dict:
        if self.active(group) is not None:
            return self._reply("这个群已经有一桌在打了喵，等他们打完再来。")
        mode = argument if argument in MODE_NAMES else "道具"
        players = [
            Player(user=user, name=name),
            Player(user=FISH_ID, name=FISH_NAME, ai=True),
        ]
        error = self._charge(players, mode)
        if error:
            return self._reply(error)
        game = self._new_game(group, players, mode, solo=True)
        log(f"{DEVIL_LOG} {name} 单人开局（{mode}），入场 {ENTRY_FEE}")
        return {"panel": self._game_panel(game)}

    def _invite_from_text(self, group: str, user: str, name: str,
                          target: tuple[str, str]) -> dict:
        target_id, target_name = target
        if target_id == FISH_ID:
            return self._reply("大肥鱼不用 @ 它，主菜单点「单人」就能跟它打喵。")
        if self.game_of(group, user) is not None:
            return self._reply("你手上还有一局没打完，先打完再挑战别人喵。")
        if self.active(group) is not None:
            return self._reply("这个群已经有一桌在打了喵，等他们打完。")
        if self.game_of(group, target_id) is not None:
            return self._reply(f"{target_name} 也正打着呢，等 TA 打完再说。")
        invite = Invite(
            iid=self._new_id(),
            group=group,
            challenger=user,
            challenger_name=name,
            target=target_id,
            target_name=target_name,
            created_at=self.now(),
        )
        self._invites[invite.iid] = invite
        log(f"{DEVIL_LOG} {name} 向 {target_name} 发起挑战")
        return {"panel": self._invite_panel(invite)}

    def _open_invite(self, group: str, user: str, name: str) -> dict:
        if self.game_of(group, user) is not None:
            return self._reply("你手上还有一局没打完喵。")
        if self.active(group) is not None:
            return self._reply("这个群已经有一桌在打了喵，等他们打完。")
        invite = Invite(
            iid=self._new_id(),
            group=group,
            challenger=user,
            challenger_name=name,
            created_at=self.now(),
        )
        self._invites[invite.iid] = invite
        log(f"{DEVIL_LOG} {name} 摆了一桌公开挑战")
        return {"panel": self._invite_panel(invite)}

    def _invite_panel(self, invite: Invite) -> dict:
        invite.seq += 1
        iid, seq = invite.iid, invite.seq
        if invite.target:
            title = f"# ⚔️ {invite.challenger_name} 向 {invite.target_name} 发起挑战"
            who = f"只有 {invite.target_name} 能点下面的按钮喵"
            rows = [
                [("接受·道具", panel_data(iid, seq, ACT_ACCEPT, "道具")),
                 ("接受·纯赌", panel_data(iid, seq, ACT_ACCEPT, "纯赌"))],
                [("拒绝", panel_data(iid, seq, ACT_REFUSE))],
            ]
            allowed = [invite.target]
        else:
            title = f"# ⚔️ {invite.challenger_name} 摆了一桌，谁来对赌？"
            who = f"除了 {invite.challenger_name}，谁先点谁就是对手喵"
            rows = [
                [("接受·道具", panel_data(iid, seq, ACT_ACCEPT, "道具")),
                 ("接受·纯赌", panel_data(iid, seq, ACT_ACCEPT, "纯赌"))],
            ]
            allowed = []
        lines = [
            title,
            f"{MAX_HP} 点电 · 入场 {ENTRY_FEE} 银币（两边各交各的）",
            f"道具：赢返 {self._refund('道具', True)} / 输全赔 · "
            f"纯赌：赢返 {self._refund('纯赌', True)} / 输退 {self._refund('纯赌', False)}",
            f"{who} · {int(INVITE_TTL)} 秒有效",
        ]
        return {"text": "\n".join(lines), "rows": rows, "user_ids": allowed}

    def _invite_action(self, group: str, user: str, name: str, invite: Invite,
                       action: str, argument: str) -> dict:
        if self.now() - invite.created_at > INVITE_TTL:
            self._invites.pop(invite.iid, None)
            return self._reply("这张挑战帖过期了喵，重新发起一次吧。")
        if action == ACT_REFUSE:
            if user == invite.challenger:
                return self._reply("自己拒绝自己？")
            if invite.target and user != invite.target:
                return self._reply("这张挑战帖不是给你的喵。")
            self._invites.pop(invite.iid, None)
            return self._reply(f"{name} 拒绝了挑战喵。")
        if action != ACT_ACCEPT:
            return self._stale()
        if user == invite.challenger:
            return self._reply("自己接自己的挑战？那不就是单人模式嘛。")
        if invite.target and user != invite.target:
            return self._reply(f"这张挑战帖是给 {invite.target_name} 的喵。")
        if self.active(group) is not None:
            return self._reply("这个群已经有一桌在打了喵，等他们打完。")
        if self.game_of(group, invite.challenger) is not None:
            self._invites.pop(invite.iid, None)
            return self._reply(f"{invite.challenger_name} 已经开局了，这张挑战帖作废。")
        mode = argument if argument in MODE_NAMES else "道具"
        self._invites.pop(invite.iid, None)
        players = [
            Player(user=invite.challenger, name=invite.challenger_name),
            Player(user=user, name=name),
        ]
        error = self._charge(players, mode)
        if error:
            return self._reply(error)
        game = self._new_game(group, players, mode, solo=False)
        log(f"{DEVIL_LOG} {invite.challenger_name} vs {name} 开局"
            f"（{mode}），入场 {ENTRY_FEE}×2")
        return {"panel": self._game_panel(game)}

    def _new_game(self, group: str, players: list[Player], mode: str,
                  solo: bool) -> Game:
        now = self.now()
        game = Game(
            gid=self._new_id(),
            group=group,
            mode=mode,
            players=players,
            solo=solo,
            started_at=now,
            last_at=now,
        )
        self._load_rack(game)
        self._deal(game)
        self._games[group] = game
        return game

    # ==================================================================
    # 弹匣 / 发牌
    # ==================================================================

    @staticmethod
    def _count_live(game: Game) -> int:
        return sum(1 for shell in game.shells[game.idx:] if shell)

    def _load_rack(self, game: Game) -> None:
        """装一轮新弹匣（轮数 +1）。"""
        game.round += 1
        live, blank = RACK_PLAN[min(game.round, MAX_ROUNDS_PLAN) - 1]
        shells = [True] * live + [False] * blank
        self.rng.shuffle(shells)
        game.shells = shells
        game.idx = 0
        game.revealed = {}

    def _deal(self, game: Game) -> None:
        if game.mode != "道具":
            return
        for player in game.players:
            for _ in range(DEAL_PER_ROUND):
                if len(player.items) < MAX_ITEMS:
                    player.items.append(self.rng.choice(ITEM_ORDER))

    def _refill(self, game: Game) -> None:
        """弹匣打完 → 补一轮新弹 + 每人补发 2 件道具。

        **不回血、不清手牌**：前面挨的枪一直记着，一局必须打到有人电量为 0。
        """
        if game.idx < len(game.shells):
            return
        self._load_rack(game)
        self._deal(game)
        game.sys_note = f"🔁 换弹 第 {game.round} 轮（{len(game.shells)} 发）"

    # ==================================================================
    # 对局动作
    # ==================================================================

    def _game_action(self, group: str, user: str, name: str, game: Game,
                     action: str, argument: str) -> dict:
        player = game.player_of(user)
        if player is None:
            return self._reply(NOT_YOUR_TABLE)
        if game.over:
            if action == ACT_REMATCH:
                return self._rematch(group, user, name, game)
            if action == ACT_MENU:
                return {"panel": self._menu_panel(group, user, name)}
            if action == ACT_RANK:
                return self._rank_panel(group, user, name)
            if action == ACT_RULE:
                return self._rules_reply()
            return self._stale()
        if action == ACT_RANK:
            return self._rank_panel(group, user, name)
        if action == ACT_RULE:
            return self._rules_reply()
        if game.current.user != user:
            return self._reply(f"现在是 {game.current.name} 的回合喵，别抢枪。")

        game.last_at = self.now()
        game.taunt = ""
        game.ai_note = ""
        game.sys_note = ""

        if action == ACT_SELF:
            self._shoot(game, game.current, game.current)
        elif action == ACT_SHOOT:
            self._shoot(game, game.current, game.other)
        elif action == ACT_USE:
            if game.mode != "道具":
                return self._reply("纯赌模式没有道具喵，全看弹匣。")
            item = (argument or "").strip()
            if item not in ITEMS:
                return self._stale()
            error = self._use_item(game, game.current, item)
            if error:
                return self._reply(error)
        elif action == ACT_QUIT:
            return self._give_up(game, player)
        else:
            return self._stale()

        if game.over:
            return self._end_panel(game)
        self._run_ai(game)
        if game.over:
            return self._end_panel(game)
        return {"panel": self._game_panel(game)}

    def _shoot(self, game: Game, shooter: Player, target: Player) -> None:
        shell = game.shells[game.idx]
        game.idx += 1
        game.revealed[game.idx - 1] = shell
        damage = 2 if shooter.saw else 1
        sawn = shooter.saw
        shooter.saw = False
        self_pick = target is shooter

        if shell:
            if self_pick:
                self._say(game, f"💥 {shooter.name} 打自己：实弹 −{damage}",
                          "ai" if shooter.ai else "human")
            else:
                extra = "（锯）" if sawn else ""
                self._say(game, f"💥 {shooter.name} → {target.name}：实弹 −{damage}{extra}",
                          "ai" if shooter.ai else "human")
            target.hp -= damage
            # 大肥鱼被打中 / 打中人都会立刻回一句，比随机狠话更贴场
            if target.ai:
                game.taunt = self.rng.choice(HURT_LINES)
            elif shooter.ai:
                game.taunt = self.rng.choice(HIT_LINES)
        else:
            if self_pick:
                self._say(game, f"🌬 {shooter.name} 打自己：空包，继续",
                          "ai" if shooter.ai else "human")
            else:
                self._say(game, f"🌬 {shooter.name} → {target.name}：空包",
                          "ai" if shooter.ai else "human")

        if target.hp <= 0:
            # 谁的血量归零谁就输 —— 包括「朝自己开枪把自己电死」的情况。
            # 以前这里把 shooter 当赢家，自己把自己打空血反而判赢，是错的。
            self._finish(game, self._foe_of(game, target), forfeit=False)
            return

        if shell or not self_pick:
            self._pass_turn(game)
        self._refill(game)

        if game.solo and game.players[1].ai and not game.over:
            self._maybe_taunt(game)

    def _pass_turn(self, game: Game) -> None:
        other_index = 1 - game.turn
        if game.players[other_index].cuffed:
            game.players[other_index].cuffed = False
            game.sys_note = f"⛓️ {game.players[other_index].name} 被锁，跳过"
            return
        game.turn = other_index

    def _use_item(self, game: Game, player: Player, item: str) -> str | None:
        """用一件道具；成功返回 None，失败返回一句给玩家看的话。"""
        if item not in player.items:
            return f"你手里没有「{item}」喵。"
        if item == "手铐" and game.other.cuffed:
            return "对方已经被锁住了，别浪费手铐喵。"
        if item == "肾上腺素" and not game.other.items:
            return "对方手里没道具，这一针抢不到东西喵。"
        player.items.remove(item)
        source = "ai" if player.ai else "human"

        if item == "放大镜":
            value = game.shells[game.idx]
            game.revealed[game.idx] = value
            self._say(game, f"🔍 这一发是【{'实弹' if value else '空包'}】", source)
        elif item == "香烟":
            before = player.hp
            player.hp = min(MAX_HP, player.hp + 1)
            self._say(game, f"🚬 {player.name} +{player.hp - before} → {player.hp}/{MAX_HP}",
                      source)
        elif item == "啤酒":
            value = game.shells[game.idx]
            game.idx += 1
            game.revealed[game.idx - 1] = value
            self._say(game, f"🍺 退出一发【{'实弹' if value else '空包'}】", source)
        elif item == "手锯":
            player.saw = True
            self._say(game, f"🪚 {player.name} 下一枪 ×2", source)
        elif item == "手铐":
            game.other.cuffed = True
            self._say(game, f"⛓️ {player.name} 锁住对方", source)
        elif item == "逆变器":
            game.shells[game.idx] = not game.shells[game.idx]
            if game.idx in game.revealed:
                game.revealed[game.idx] = game.shells[game.idx]
            self._say(game, "🔄 当前这发反转", source)
        elif item == "电话":
            left = len(game.shells) - game.idx
            offset = self.rng.randrange(left)
            position = game.idx + offset
            value = game.shells[position]
            game.revealed[position] = value
            self._say(game, f"☎️ 第 {offset + 1} 发是【{'实弹' if value else '空包'}】",
                      source)
        elif item == "药丸":
            if self.rng.random() < 0.5:
                before = player.hp
                player.hp = min(MAX_HP, player.hp + 2)
                self._say(game, f"💊 好运 +{player.hp - before} → {player.hp}/{MAX_HP}",
                          source)
            else:
                player.hp -= 1
                self._say(game, f"💊 坏的 −1 → {max(player.hp, 0)}/{MAX_HP}", source)
        elif item == "肾上腺素":
            stolen = self.rng.choice(game.other.items)
            game.other.items.remove(stolen)
            if len(player.items) < MAX_ITEMS:
                player.items.append(stolen)
                self._say(game, f"💉 {player.name} 抢到「{stolen}」", source)
            else:
                self._say(game, f"💉 抢到「{stolen}」，手牌满，丢了", source)

        if player.hp <= 0:
            self._finish(game, self._foe_of(game, player), forfeit=False,
                         by_pill=True)
            return None
        # 啤酒可能把最后一发退出去：顺手换一轮（补电、重新发牌）
        self._refill(game)
        return None

    @staticmethod
    def _foe_of(game: Game, player: Player) -> Player:
        return game.players[1] if game.players[0] is player else game.players[0]

    # ==================================================================
    # 大肥鱼
    # ==================================================================

    def _run_ai(self, game: Game) -> None:
        steps = 0
        while not game.over and game.current.ai:
            steps += 1
            if steps > AI_MAX_STEPS:
                game.sys_note = "🐟 想太久，交枪"
                self._pass_turn(game)
                return
            self._ai_act(game)

    def _maybe_taunt(self, game: Game) -> None:
        if self.rng.random() < TAUNT_CHANCE:
            game.taunt = self.rng.choice(TAUNTS)

    def _ai_act(self, game: Game) -> None:
        ai = game.current
        foe = game.other
        known = game.revealed.get(game.idx)
        left = len(game.shells) - game.idx

        # 1) 先照顾自己：残血抽烟 / 赌药丸
        if ai.hp < MAX_HP and "香烟" in ai.items:
            self._use_item(game, ai, "香烟")
            return
        if ai.hp <= 2 and "药丸" in ai.items and self.rng.random() < 0.25:
            self._use_item(game, ai, "药丸")
            return
        # 2) 情报：不知道当前这发就开镜
        if known is None and "放大镜" in ai.items:
            self._use_item(game, ai, "放大镜")
            return
        if known is None and "电话" in ai.items and left > 1 and self.rng.random() < 0.4:
            self._use_item(game, ai, "电话")
            return
        # 3) 抢道具 / 上铐
        if "肾上腺素" in ai.items and foe.items and len(ai.items) < MAX_ITEMS:
            if self.rng.random() < 0.55:
                self._use_item(game, ai, "肾上腺素")
                return
        if "手铐" in ai.items and not foe.cuffed and self.rng.random() < 0.7:
            self._use_item(game, ai, "手铐")
            return

        known = game.revealed.get(game.idx)
        left = len(game.shells) - game.idx
        if known is None:
            live = self._count_live(game)
            ratio = live / left if left else 0.5
            shoot_foe = self.rng.random() < ratio
        else:
            shoot_foe = bool(known)

        # 4) 知道是空包、又想打对方：反转它
        if not shoot_foe and known is False and "逆变器" in ai.items:
            if self.rng.random() < 0.6:
                self._use_item(game, ai, "逆变器")
                return
        # 5) 要打对方就上锯子
        if shoot_foe and not ai.saw and "手锯" in ai.items:
            if self.rng.random() < 0.75:
                self._use_item(game, ai, "手锯")
                return
        # 6) 知道是空包、弹匣还长：喝瓶啤酒把它退掉
        if known is False and left > 1 and "啤酒" in ai.items:
            if self.rng.random() < 0.3:
                self._use_item(game, ai, "啤酒")
                return

        if shoot_foe:
            self._shoot(game, ai, foe)
        else:
            self._shoot(game, ai, ai)
        self._maybe_taunt(game)

    # ==================================================================
    # 结算
    # ==================================================================

    def _give_up(self, game: Game, player: Player | None) -> dict:
        if player is None:
            return self._reply(NOT_YOUR_TABLE)
        log(f"{DEVIL_LOG} {player.name} 认输")
        self._finish(game, self._foe_of(game, player), forfeit=True)
        return self._end_panel(game)

    def _finish(self, game: Game, winner: Player, forfeit: bool = False,
                by_pill: bool = False) -> None:
        """收尾：记榜单、攒结束面板的文案。"""
        game.over = True
        game.winner = winner.name
        game.finished_at = self.now()
        loser = self._foe_of(game, winner)

        recorded = [player for player in game.players if not player.ai]
        # 先把所有人的胜负都记上，再统一取排名 —— 否则先记的人会拿到「当时」的排名，
        # 双人局里输家也会显示成本群第 1。
        for player in recorded:
            self.record(game.group, player.user, player.name, player is winner)
        game.end_records = [
            (player.name, self.stats_of(game.group, player.user))
            for player in recorded
        ]
        game.refunds = self._payout(game, winner)

        if game.solo:
            human = game.players[0]
            if human is winner:
                game.end_flavor = self.rng.choice(PLAYER_WIN_LINES)
                game.end_fish = self.rng.choice(DEFEAT_LINES)
            else:
                if forfeit:
                    game.end_flavor = "你认输了喵，大肥鱼得意地把枪扛回了鱼缸。"
                elif by_pill:
                    game.end_flavor = "你被自己吞的药丸药翻了……大肥鱼都看愣了。"
                else:
                    game.end_flavor = self.rng.choice(PLAYER_LOSE_LINES)
                game.end_fish = self.rng.choice(WIN_LINES)
        else:
            if forfeit:
                game.end_flavor = f"{loser.name} 认输了，{winner.name} 不战而胜喵。"
            elif by_pill:
                game.end_flavor = f"{loser.name} 被自己吞的药丸药翻了，{winner.name} 赢下这局。"
            else:
                game.end_flavor = f"{winner.name} 把 {loser.name} 电趴下了，赢下这局！"
            game.end_fish = ""

        self._games.pop(game.group, None)
        self._finished[game.gid] = game
        log(f"{DEVIL_LOG} 结束：{winner.name} 胜（{game.mode}，共 {game.round} 轮）")

    def _end_panel(self, game: Game) -> dict:
        game.seq += 1
        gid, seq = game.gid, game.seq
        lines = [
            f"# 🏁 恶魔轮盘赌 · {MODE_NAMES.get(game.mode, game.mode)}",
            f"🎉 {game.end_flavor}",
        ]
        for name, stats in game.end_records:
            lines.append(f"🏆 {name} {stats['wins']}胜{stats['losses']}负"
                         f" · 本群第 {stats['rank']}")
        for name, paid, refund in game.refunds:
            net = refund - paid
            sign = f"+{net}" if net >= 0 else str(net)
            lines.append(f"💰 {name} 入场 {paid} → 返 {refund}（{sign}）")
        if game.end_fish:
            lines.append("***")
            lines.append(f"> 🐟 {game.end_fish}")
        rows = [
            [("再来一局", panel_data(gid, seq, ACT_REMATCH))],
            [("主菜单", panel_data(gid, seq, ACT_MENU)),
             ("完整榜单", panel_data(gid, seq, ACT_RANK))],
        ]
        allowed = [player.user for player in game.players if not player.ai]
        return {"ok": True, "reply": "", "panel": {
            "text": "\n".join(lines), "rows": rows, "user_ids": allowed,
        }}

    def _rematch(self, group: str, user: str, name: str, old: Game) -> dict:
        if self.active(group) is not None:
            return self._reply("这个群已经有一桌在打了喵，等他们打完。")
        if old.player_of(user) is None:
            return self._reply(NOT_YOUR_TABLE)
        players = [
            Player(user=player.user, name=player.name, ai=player.ai)
            for player in old.players
        ]
        error = self._charge(players, old.mode)
        if error:
            return self._reply(error)
        game = self._new_game(group, players, old.mode, solo=old.solo)
        log(f"{DEVIL_LOG} 再来一局（{game.mode}）")
        return {"panel": self._game_panel(game)}

    # ==================================================================
    # 渲染
    # ==================================================================

    @staticmethod
    def _hp_bar(hp: int) -> str:
        return "❤" * max(0, min(MAX_HP, hp)) + "🖤" * max(0, MAX_HP - max(0, hp))

    def _score_line(self, game: Game) -> str:
        if game.solo:
            human, fish = game.players[0], game.players[1]
            return f"你 {self._hp_bar(human.hp)}　🐟 {self._hp_bar(fish.hp)}"
        return "　".join(
            f"{player.name} {self._hp_bar(player.hp)}" for player in game.players
        )

    def _rack_line(self, game: Game) -> str:
        left = len(game.shells) - game.idx
        live = self._count_live(game)
        return f"弹匣 {left} · 实 {live} 空 {left - live} · 第 {game.round} 轮"

    def _turn_line(self, game: Game) -> str:
        player = game.current
        if player.ai:
            return "🐟 装弹中…"
        if game.solo:
            return "🎯 你的回合"
        return f"🎯 {player.name} 的回合"

    def _items_line(self, game: Game) -> str:
        if game.mode != "道具":
            return ""
        items = self._items_text(game.current.items)
        return "手牌 " + (items or "空")

    @staticmethod
    def _items_text(items: list[str]) -> str:
        parts = []
        for name in ITEM_ORDER:
            count = items.count(name)
            if count:
                parts.append(f"{ITEMS[name].emoji}{count}")
        return " ".join(parts)

    def _game_text(self, game: Game) -> str:
        lines = [
            f"# 🔫 恶魔轮盘赌 · {MODE_NAMES.get(game.mode, game.mode)}",
            self._score_line(game),
            self._rack_line(game),
        ]
        turn = self._turn_line(game)
        items = self._items_line(game)
        lines.append(f"{turn} · {items}" if items else turn)
        # 只留「你的上一手 + 大肥鱼上一手 + 一句小播报」，多余的过程不往面板上糊
        notes = [note for note in (game.human_note, game.ai_note, game.sys_note) if note]
        if notes:
            lines.append("")
            lines.extend(notes)
        # 大肥鱼的话单独隔开、走引用块（客户端会缩成小字灰底）
        if game.taunt:
            lines.append("***")
            lines.append(f"> 🐟 {game.taunt}")
        return "\n".join(lines)

    def _game_rows(self, game: Game) -> list:
        gid, seq = game.gid, game.seq
        rows = [[
            ("朝自己开枪", panel_data(gid, seq, ACT_SELF)),
            ("朝对方开枪", panel_data(gid, seq, ACT_SHOOT)),
        ]]
        if game.mode == "道具":
            items = []
            for name in ITEM_ORDER:
                count = game.current.items.count(name)
                if not count:
                    continue
                label = name if count == 1 else f"{name}×{count}"
                items.append((label, panel_data(gid, seq, ACT_USE, name)))
            for index in range(0, len(items), 5):
                rows.append(items[index:index + 5])
        rows.append([
            ("道具说明", panel_data(gid, seq, ACT_RULE)),
            ("认输", panel_data(gid, seq, ACT_QUIT)),
        ])
        return rows

    def _game_panel(self, game: Game) -> dict:
        game.seq += 1
        return {
            "text": self._game_text(game),
            "rows": self._game_rows(game),
            "user_ids": [game.current.user] if not game.current.ai else [],
        }

    def _rank_panel(self, group: str, user: str, name: str = "") -> dict:
        state = self._menu_state(group, user)
        state.seq += 1
        rows = [[
            ("返回主菜单", panel_data(state.panel_id, state.seq, ACT_MENU)),
        ]]
        return {"ok": True, "reply": "", "panel": {
            "text": self.board_text(group),
            "rows": rows,
            "user_ids": [user] if user else [],
        }}

    @staticmethod
    def _rules_reply() -> dict:
        lines = [
            "# 🔫 恶魔轮盘赌 · 玩法",
            f"双方各 **{MAX_HP} 点电**，谁先掉到 0 谁输（一局打到见底才结算）。",
            "· 打自己空包：不扣电，**枪还归你**",
            "· 打自己实弹：自己 −1，交枪",
            "· 打对方：实弹对方 −1，空包没事；两种都交枪",
            "· 弹匣打空只是补一轮新弹（每轮每人补 2 件道具），**血量不回满**",
            "",
            f"💰 入场 {ENTRY_FEE} 银币：道具赢返 {DevilRoulette._refund('道具', True)}、"
            f"输全赔；纯赌赢返 {DevilRoulette._refund('纯赌', True)}、"
            f"输退 {DevilRoulette._refund('纯赌', False)}。超时散桌原路全退。",
            "",
            "🃏 道具（每轮发 2 件，上限 8）：",
        ]
        for name in ITEM_ORDER:
            item = ITEMS[name]
            lines.append(f"{item.emoji} {item.name}：{item.desc}")
        lines.append("")
        lines.append("🎲 纯赌：没有道具，全看弹匣和胆子。")
        lines.append("💡 没有私聊，放大镜 / 电话的情报全群可见，双人局当公开牌打。")
        return {"reply": "\n".join(lines)}

    # ==================================================================
    # 小工具
    # ==================================================================

    @staticmethod
    def _say(game: Game, text: str, source: str = "") -> None:
        """记一条播报；``source`` 决定它出现在面板的哪一行。

        ``human`` = 玩家上一手，``ai`` = 大肥鱼上一手，空 = 不上面板（只留在 log）。
        """
        game.log.append(text)
        del game.log[:-6]
        if source == "human":
            game.human_note = text
        elif source == "ai":
            game.ai_note = text

    def _reply(self, text: str) -> dict:
        return {"ok": False, "panel": None, "reply": text}

    def _stale(self) -> dict:
        return self._reply(STALE_REPLY)


__all__ = [
    "ACT_ACCEPT", "ACT_DIRECT", "ACT_MENU", "ACT_OPEN", "ACT_QUIT",
    "ACT_REFUSE", "ACT_REMATCH", "ACT_RANK", "ACT_RULE", "ACT_SELF",
    "ACT_SHOOT", "ACT_SOLO", "ACT_USE", "DEAL_PER_ROUND", "DevilRoulette",
    "END_COMMANDS", "ENTRY_FEE", "Game", "INVITE_TTL", "Invite", "MAX_HP",
    "MAX_ITEMS", "Menu", "MODE_RULES", "PANEL_PREFIX", "Player", "RACK_PLAN",
    "RANK_COMMANDS", "RANK_FILE", "RULE_COMMANDS", "SESSION_TTL", "panel_data",
    "parse_panel_data",
]
