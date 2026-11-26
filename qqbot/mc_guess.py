"""弗一把 · Minecraft 物品版：全群一起猜一件物品，二十轮之内猜中全员上榜。

玩法（跟 CSGO 的「弗一把」同一套路，只是把选手换成 Minecraft 物品）：

* 群里有人发「弗一把」，先弹一块面板，按钮是**简单模式 / 困难模式**；
  点了才抽题。两个模式规则完全一样，只有题库不同：
  - **简单**：``mc_guess_data.ITEMS``（Java 1.20.2 截止），原样没动；
  - **困难**：``mc_guess_data_hard``，26.3 及以前的全部物品与生物
    （1.20.5 犰狳 → 1.21 试炼密室 → 1.21.11 鹦鹉螺 / 矛 → 26.1 金蒲公英 →
    26.2 硫方怪 / 硫黄 / 朱砂 → 26.3 杨树 / 层孔菇 / 坐垫都在）。
* 之后谁都可以猜：直接发物品名 / 生物名，或者「猜 名字」。**全群共享二十轮**，
  每猜一次算一轮，猜错也会给六维反馈：
  名称重合 / 加入版本 / 类型 / 标签 / 字数 / 生成世界。
* 反馈用颜色：🟩 完全对上，🟨 沾边（类型同属装备、标签有重合），⬜ 不对，
  ⬆️⬇️ 表示答案的版本更新 / 更旧。
* **带颜色的物品只认后缀**：题库里羊毛 / 陶瓦 / 混凝土这些是一条家族条目，
  别名自动补齐 16 色，所以猜「羊毛」和猜「红色羊毛」都算猜中。
* 二十轮内猜中：猜中的人记一次胜场、进本群榜（纯粹比谁猜得准）；
  二十轮全用完还没中，就是大肥鱼难过那句话。
* **榜单每 7 天清一次，固定在周四 0 点清零**（本周四到下周三是同一个榜），
  榜里只算这一周的猜中次数；清空只动榜单，进行中的局不受影响。
* 一局十分钟没人动就散场（下次发「弗一把」直接开新局，不会卡着）。

会话只在内存里（和 ``cs.py`` 一样，重启就没了），不落任何文件。
"""
from __future__ import annotations

import datetime as _dt
import time

from .base import *  # noqa: F401,F403
from .mc_guess_data import (
    ITEMS,
    TYPE_FAMILIES,
    VERSION_ORDER,
    Item,
    check_data,
    find_item,
    normalize_name,
    version_newer,
)
from .mc_guess_data_hard import (
    HARD_ITEMS,
    VERSION_ORDER_HARD,
    check_hard_data,
    find_hard_item,
    version_label,
)

# --------------------------------------------------------------------------
# 常量
# --------------------------------------------------------------------------

FILE_LOG = "[弗一把]"

MAX_ROUNDS = 20                 # 一局总共能猜几次（全群共享）
SESSION_TTL = 10 * 60.0         # 十分钟没人动就散场

# 两种难度：简单 = 原来的 1.20.2 题库；困难 = 26.3 及以前的全部物品与生物。
MODE_EASY, MODE_HARD = "简单", "困难"
MODE_LABELS = {MODE_EASY: "简单模式", MODE_HARD: "困难模式"}
MODE_BANKS = {
    MODE_EASY: {
        "items": ITEMS,
        "order": VERSION_ORDER,
        "find": find_item,
        "check": check_data,
        "scope": "1.20.2 之前的物品和生物",
    },
    MODE_HARD: {
        "items": HARD_ITEMS,
        "order": VERSION_ORDER_HARD,
        "find": find_hard_item,
        "check": check_hard_data,
        "scope": "26.3 及以前的全部物品和生物（1.21.x 和 26.x 的新内容都在里面）",
    },
}

# 榜单：按「猜中次数」排，落盘 data/mc_guess_rank.json（按群分开算）
RANK_FILE = "mc_guess_rank.json"
RANK_TOP = 3                    # 开局 / 状态里带的前三名（完整榜用「弗一把 榜单」）

# 榜单周期：**每 7 天清一次，固定在周四 0 点**。周四到下一个周三是同一期，
# 到下周四 0 点整自动清零（清空只动榜单，对局不受影响）。
RESET_WEEKDAY = 3               # datetime.weekday()：周一 0 …… 周四 3
RESET_LABEL = "每周四 0 点清零"

# 冷场提醒：一个人猜对之后隔多久没人接话，就催一句（不占轮数、不改任何局内状态）
NUDGE_IDLE = 180.0              # 三分钟没人动就催
NUDGE_MAX = 2                   # 一局最多催两次
NUDGE_CHECK_INTERVAL = 20.0     # 后台多久看一眼（handler 的定时任务用）
NUDGE_TALK = (
    "快点啊，我等的花都谢了💔（还剩 {left} 次机会）",
    "真的没人猜吗……大肥鱼已经打哈欠了💤（还剩 {left} 次）",
)

START_COMMANDS = ("弗一把", "mc弗一把", "我的世界弗一把", "弗一把开始", "再弗一把")
STATUS_COMMANDS = ("弗一把状态", "弗一把 状态", "弗一把进度", "弗一把 进度")
RANK_COMMANDS = ("弗一把榜单", "弗一把 榜单", "弗一把排行", "弗一把 排行",
                 "弗一把排行榜", "弗一把 排行榜")
END_COMMANDS = ("弗一把结束", "弗一把 结束", "认输", "弗一把认输",
                "弗一把 认输", "不玩了", "放弃")
# 面板按钮的 data：点一下就是把这句话发进来，和打字走同一条路
MODE_DATA = {
    MODE_EASY: "弗一把 简单模式",
    MODE_HARD: "弗一把 困难模式",
}
# 长前缀放前面：「猜一下钻石」要先剥掉「猜一下」，不然会剩个「一下钻石」
GUESS_PREFIXES = ("猜一下", "猜个", "我猜", "猜")

DIM_NAMES = ("名称", "加入版本", "类型", "标签", "字数", "生成世界")

# 归一化后的命令集合，省得每条消息都重新拼一遍
START_KEYS = frozenset(normalize_name(item) for item in START_COMMANDS)
STATUS_KEYS = frozenset(normalize_name(item) for item in STATUS_COMMANDS)
RANK_KEYS = frozenset(normalize_name(item) for item in RANK_COMMANDS)
END_KEYS = frozenset(normalize_name(item) for item in END_COMMANDS)

# 「弗一把 简单模式」/「弗一把困难」这些写法都认（面板按钮发的就是这句）
MODE_KEYS: dict[str, str] = {}
for _mode in (MODE_EASY, MODE_HARD):
    for _text in (f"弗一把{_mode}", f"弗一把{_mode}模式",
                  f"弗一把 {_mode}", f"弗一把 {_mode}模式"):
        MODE_KEYS[normalize_name(_text)] = _mode

# 颜色
GREEN, YELLOW, RED = "🟩", "🟨", "⬜"
UP, DOWN = "⬆️", "⬇️"


@dataclass
class Guess:
    """一轮猜测：谁猜的、猜了什么、反馈长什么样。"""

    user: str
    name: str
    item: Item
    cells: list[str]
    win: bool = False

    def render(self) -> str:
        lines = [f"  {label} {cell}" for label, cell in
                 zip(DIM_NAMES, self.cells)]
        return "\n".join(lines)


@dataclass
class Game:
    """一个群的当前这一局。"""

    group: str
    target: Item
    started_at: float
    last_at: float
    mode: str = MODE_EASY
    guesses: list[Guess] = field(default_factory=list)
    # user_id -> 昵称；参与过任意一次有效猜测的人都记着，结算时列出来
    players: dict[str, str] = field(default_factory=dict)
    # 猜过的物品名（归一化后）→ 防止同一件东西反复烧轮数
    tried: set[str] = field(default_factory=set)
    # 冷场提醒：已经催过几次、上次催是什么时候（纯文案，不影响轮数和奖励）
    nudges: int = 0
    last_nudge: float = 0.0

    @property
    def rounds(self) -> int:
        return len(self.guesses)

    @property
    def left(self) -> int:
        return max(0, MAX_ROUNDS - self.rounds)

    def history(self, limit: int = 8) -> str:
        names = [guess.item.name for guess in self.guesses]
        if len(names) > limit:
            names = names[-limit:]
            return "… / " + " / ".join(names)
        return " / ".join(names)


# --------------------------------------------------------------------------
# 引擎
# --------------------------------------------------------------------------


def weighted_pick(items, rng):
    """按每道题的 ``weight`` 抽一条：权重越大越容易被抽到。

    **一律走加权抽**（``rng.choices``），权值全一样时自然就是均匀分布，
    不再分「全等走 choice / 不等走 choices」两条路径。
    权重必须是正数（加载时已经校验过）。
    """
    if not items:
        raise ValueError("题库是空的，没法抽题")
    weights = [float(getattr(item, "weight", 1.0)) for item in items]
    return rng.choices(items, weights=weights, k=1)[0]


def week_key(ts: float) -> str:
    """``ts`` 这一期的名字：最近一个周四的日期（``YYYY-MM-DD``，本地时间）。

    周期是「周四 0 点 → 下周四 0 点前」，所以周四当天就算新一期；
    零点一过这个字符串就跳到今天，跟榜里记的对不上，榜单随之清零。
    """
    moment = _dt.datetime.fromtimestamp(ts)
    back = (moment.weekday() - RESET_WEEKDAY) % 7
    return (moment.date() - _dt.timedelta(days=back)).isoformat()


class MCGuess:
    """「弗一把」的会话管理 + 规则实现。

    对局只在内存里；**榜单**按群落盘到 ``data/mc_guess_rank.json``
    （猜中一次记一次，重启也在；**每 7 天清一次，固定周四 0 点清零**）。
    冷场提醒只发一句文案，不碰任何局内状态。
    """

    def __init__(self, pets, data_dir=None, rng=None, now=None) -> None:
        # pets 现在不参与结算（本玩法不再发宠物经验），参数留着不改调用方
        self.pets = pets
        self.rng = rng or random.Random()
        self.now = now or time.time
        self._games: dict[str, Game] = {}
        self.path = (Path(data_dir) / RANK_FILE) if data_dir else None
        # 榜里的 period 是这一期的名字（起始那个周四的日期），对不上就清零
        self._period = ""
        self._rank = self._load_rank()

    # ---- 榜单 ----

    def _load_rank(self) -> dict[str, dict[str, dict]]:
        """读榜：新格式 ``{"period": "2026-11-26", "groups": {...}}``。

        老文件（直接是 ``{群: {人: 记录}}``）照样能读，但里面没有周期信息，
        第一次检查周期时会当成「上一期」直接清零。
        """
        if self.path is None:
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            return {}
        if not isinstance(payload, dict):
            return {}
        if isinstance(payload.get("groups"), dict):
            self._period = str(payload.get("period") or "")
            payload = payload["groups"]
        return {str(group): {str(user): entry for user, entry in board.items()
                             if isinstance(entry, dict)}
                for group, board in payload.items() if isinstance(board, dict)}

    def _save_rank(self) -> None:
        if self.path is None:
            return
        temporary = self.path.with_name("mc_guess_rank.tmp")
        payload = {"period": self._period, "groups": self._rank}
        try:
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            temporary.replace(self.path)
        except OSError as error:
            log(f"{FILE_LOG} 榜单保存失败：{error}")

    def reset_week(self, force: bool = False) -> bool:
        """到周四 0 点就把榜清空；返回这次到底清没清。

        只在「看榜 / 记一次猜中」时顺手检查，机器人半夜关着也不会漏：
        下次一读榜发现周期对不上，照样清。``force=True`` 立刻清（自检 / 手动用）。
        """
        if not force and not self.needs_reset():
            return False
        cleared = bool(self._rank)
        self._rank = {}
        self._period = week_key(self.now())
        self._save_rank()
        if cleared:
            log(f"{FILE_LOG} 榜单清零（{RESET_LABEL}）")
        return cleared

    def needs_reset(self) -> bool:
        """现在这一期跟榜里记的那期是不是同一个周四。"""
        return week_key(self.now()) != self._period

    @staticmethod
    def _board_sorted(board: dict[str, dict]) -> list[tuple[str, dict]]:
        return sorted(
            board.items(),
            key=lambda pair: (-int(pair[1].get("wins") or 0),
                              -int(pair[1].get("last") or 0),
                              str(pair[1].get("name") or "")),
        )

    def leaderboard(self, group: str, limit: int = 10) -> list[dict]:
        """这个群的榜单：猜中次数从多到少（看之前先确认是不是还在同一周）。"""
        self.reset_week()
        board = self._rank.get(str(group), {})
        rows = []
        for index, (user, entry) in enumerate(self._board_sorted(board)):
            if index >= limit:
                break
            rows.append({
                "rank": index + 1,
                "user": user,
                "name": str(entry.get("name") or "群友"),
                "wins": int(entry.get("wins") or 0),
            })
        return rows

    def record_win(self, group: str, user: str, name: str) -> tuple[int, int]:
        """记一次猜中，返回（这个人本周猜中次数, 本群排名）。"""
        self.reset_week()       # 跨过周四就先清零，新一期从这一把开始算
        board = self._rank.setdefault(str(group), {})
        entry = board.setdefault(str(user), {"name": name, "wins": 0, "last": 0})
        entry["name"] = (name or str(entry.get("name") or "群友")).strip()
        entry["wins"] = int(entry.get("wins") or 0) + 1
        entry["last"] = int(self.now())
        self._save_rank()
        ranked = [user_key for user_key, _ in self._board_sorted(board)]
        rank = ranked.index(str(user)) + 1 if str(user) in ranked else len(ranked)
        return int(entry["wins"]), rank

    def _board_line(self, group: str) -> str:
        rows = self.leaderboard(group, RANK_TOP)
        if not rows:
            return "🏆 本群榜还空着，第一个猜中的就是榜首喵。"
        return "🏆 本群榜：" + "　".join(
            f"{row['rank']}.{row['name']} {row['wins']} 次" for row in rows
        )

    def board_text(self, group: str) -> str:
        rows = self.leaderboard(group, 10)
        if not rows:
            return (f"🏆 本群弗一把榜还空着喵（{RESET_LABEL}）。\n"
                    "发「弗一把」开一局，猜中一次就能上榜。")
        lines = [f"🏆 本群弗一把榜（按猜中次数 · {RESET_LABEL}）"]
        lines += [f"{row['rank']}. {row['name']} — {row['wins']} 次" for row in rows]
        lines.append(f"共 {len(self._rank.get(str(group), {}))} 人上榜。")
        return "\n".join(lines)

    # ---- 会话 ----

    def active(self, group: str) -> Game | None:
        """取这个群正在玩的那局；超时就顺手丢掉。"""
        game = self._games.get(str(group))
        if game is None:
            return None
        if self.now() - game.last_at > SESSION_TTL:
            self._games.pop(str(group), None)
            log(f"{FILE_LOG} 超时散场（{MODE_LABELS.get(game.mode, MODE_EASY)}，"
                f"{game.rounds}/{MAX_ROUNDS} 轮，答案 {game.target.name}）")
            return None
        return game

    def clear(self) -> None:
        self._games.clear()

    def _pick(self, mode: str = MODE_EASY) -> Item:
        items = MODE_BANKS.get(mode, MODE_BANKS[MODE_EASY])["items"]
        return weighted_pick(items, self.rng)

    # ---- 对外入口 ----

    def handle(self, text: str, group: str, user: str, name: str = "") -> dict | None:
        """认一条消息：开局 / 选难度 / 结束 / 状态 / 猜词。

        返回 ``{"panel": ...}`` 表示要发带按钮的面板（发「弗一把」时选难度），
        ``{"reply": "..."}`` 表示这条消息归我处理；返回 ``None`` 表示
        不关我事（交给规则、AI 或复读），普通闲聊不会被抢。
        """
        text = (text or "").strip()
        if not text:
            return None
        group = str(group or "")
        user = str(user or "")
        name = (name or "").strip() or "群友"
        key = normalize_name(text)

        game = self.active(group)

        if key in START_KEYS:
            if game is not None:
                return {"reply": (
                    f"这把还没打完喵～ 现在第 {game.rounds + 1}/{MAX_ROUNDS} 轮，"
                    f"要重开先发「弗一把 结束」。\n{self._hint_line(game)}"
                )}
            return {"panel": self._mode_panel(group)}

        if key in MODE_KEYS:
            mode = MODE_KEYS[key]
            if game is not None:
                return {"reply": (
                    f"这个群已经开着「{MODE_LABELS.get(game.mode, mode)}」了喵，"
                    f"第 {game.rounds + 1}/{MAX_ROUNDS} 轮；"
                    "要换难度先发「弗一把 结束」。"
                )}
            return {"reply": self._start(group, name, mode)}

        if key in STATUS_KEYS:
            if game is None:
                return {"reply": "现在这个群没在玩「弗一把」喵，发一句「弗一把」就开局。"}
            return {"reply": self._status_text(game)}

        if key in RANK_KEYS:
            return {"reply": self.board_text(group)}

        if key in END_KEYS:
            if game is None:
                return None          # 没在玩的时候「认输」就是普通闲聊
            self._games.pop(group, None)
            return {"reply": self._give_up_text(game)}

        if game is None:
            item, _raw, prefixed = self._parse(text, key, MODE_HARD)
            if prefixed and item is not None:
                # 「猜 钻石剑」但还没开局：给一句提示；「猜猜我是谁」这种闲聊别接
                return {"reply": "先发一句「弗一把」选个难度开局喵，不然猜了也不算数。"}
            return None

        return self._guess(game, text, key, user, name)

    # ---- 开局 / 提示 ----

    def _mode_panel(self, group: str) -> dict:
        """「弗一把」的第一屏：只给两个按钮，简单 / 困难，点了才开局。"""
        lines = [
            "# 🎮 弗一把 · Minecraft 物品 & 生物",
            self._board_line(group),
            "",
            f"**{MODE_LABELS[MODE_EASY]}**：{MODE_BANKS[MODE_EASY]['scope']}，老题原样",
            f"**{MODE_LABELS[MODE_HARD]}**：{MODE_BANKS[MODE_HARD]['scope']}",
            "",
            f"{MAX_ROUNDS} 轮全群共享 · 每猜一次给六维反馈 · 猜中记进本群榜"
            f"（{RESET_LABEL}）",
            "挑一个模式开局喵：",
        ]
        rows = [[(MODE_LABELS[MODE_EASY], MODE_DATA[MODE_EASY]),
                 (MODE_LABELS[MODE_HARD], MODE_DATA[MODE_HARD])]]
        return {"text": "\n".join(lines), "rows": rows}

    def _start(self, group: str, name: str, mode: str = MODE_EASY) -> str:
        bank = MODE_BANKS.get(mode, MODE_BANKS[MODE_EASY])
        target = self._pick(mode)
        now = self.now()
        game = Game(group=group, target=target, started_at=now, last_at=now,
                    mode=mode)
        self._games[group] = game
        log(f"{FILE_LOG} {name} 开局（{MODE_LABELS.get(mode, mode)}），"
            f"答案：{target.name}"
            f"（{target.version} / {target.type} / {'、'.join(target.tags)}"
            f" / {target.world}）")
        return (
            f"🎮 弗一把 · Minecraft 物品 & 生物篇 · "
            f"{MODE_LABELS.get(mode, MODE_EASY)}\n"
            f"我从「{bank['scope']}」里偷偷抽了一个，{MAX_ROUNDS} 轮内猜到，"
            f"全群一起猜，猜中记榜喵！\n"
            "🟩 完全对上 · 🟨 沾边 · ⬜ 不对 · ⬆️⬇️ 答案比它新 / 旧\n"
            f"{self._board_line(group)}\n"
            "想放弃就发「弗一把 结束」。"
        )

    @staticmethod
    def _hint_line(game: Game) -> str:
        if not game.guesses:
            return "还没人猜，随便发一个名字试试。"
        return f"已经猜过：{game.history()}"

    def _status_text(self, game: Game) -> str:
        return (
            f"🎮 弗一把 · {MODE_LABELS.get(game.mode, MODE_EASY)} · "
            f"第 {game.rounds}/{MAX_ROUNDS} 轮"
            f"（还剩 {game.left} 次机会）\n"
            f"{self._hint_line(game)}\n"
            f"参与过的：{'、'.join(list(game.players.values())[:8]) or '还没有'}\n"
            f"{self._board_line(game.group)}"
        )

    # ---- 冷场提醒 ----

    def has_games(self) -> bool:
        return bool(self._games)

    def groups(self) -> list[str]:
        return list(self._games)

    def nudge(self, group: str) -> str | None:
        """很久没人猜就催一句。**只改提醒计数**，不碰轮数 / 参与者 / 奖励。"""
        game = self._games.get(str(group))
        if game is None:
            return None
        now = self.now()
        if now - game.last_at < NUDGE_IDLE:
            return None
        if game.nudges >= NUDGE_MAX:
            return None
        if game.last_nudge and now - game.last_nudge < NUDGE_IDLE:
            return None
        game.nudges += 1
        game.last_nudge = now
        talk = NUDGE_TALK[(game.nudges - 1) % len(NUDGE_TALK)]
        return talk.format(left=game.left)

    # ---- 猜词 ----

    def _parse(self, text: str, key: str,
               mode: str = MODE_EASY) -> tuple[Item | None, str, bool]:
        """从消息里剥出要猜的物品名：认「猜 X」前缀，也认光秃秃的物品名。

        返回（物品, 剩下的原文, 是不是带了「猜」前缀）。困难模式的题库更大，
        所以查表要用这局对应的那张。
        """
        raw, prefixed = text, False
        for prefix in GUESS_PREFIXES:
            head = normalize_name(prefix)
            if key.startswith(head) and len(key) > len(head):
                raw, prefixed = text[len(prefix):].strip(), True
                break
        find = MODE_BANKS.get(mode, MODE_BANKS[MODE_EASY])["find"]
        return find(raw), raw, prefixed

    def _guess(self, game: Game, text: str, key: str, user: str,
               name: str) -> dict | None:
        item, raw, prefixed = self._parse(text, key, game.mode)

        if item is None:
            if not prefixed:
                return None      # 不是物品名，也不带「猜」，当普通聊天放过
            return {"reply": f"题库里没有「{raw or text}」喵，换一个试试～"}

        if item.name in game.tried:
            return {"reply": f"「{item.name}」这一局已经猜过了喵，这一轮不算，换一个。"}

        game.tried.add(item.name)
        game.players.setdefault(user, name)
        game.last_at = self.now()

        win = item.name == game.target.name
        order = MODE_BANKS.get(game.mode, MODE_BANKS[MODE_EASY])["order"]
        guess = Guess(user=user, name=name, item=item,
                      cells=self._cells(item, game.target, order), win=win)
        game.guesses.append(guess)

        if win:
            self._games.pop(game.group, None)
            return {"reply": self._win_text(game, guess)}

        if game.left <= 0:
            self._games.pop(game.group, None)
            return {"reply": self._lose_text(game, guess)}

        log(f"{FILE_LOG} {name} 猜 {item.name}（第 {game.rounds}/{MAX_ROUNDS} 轮）")
        return {"reply": self._round_text(game, guess)}

    # ---- 六维比对 ----

    @staticmethod
    def _cells(guess: Item, target: Item, order=None) -> list[str]:
        return [
            MCGuess._name_cell(guess, target),
            MCGuess._version_cell(guess, target, order),
            MCGuess._type_cell(guess, target),
            MCGuess._tag_cell(guess, target),
            MCGuess._chars_cell(guess, target),
            MCGuess._world_cell(guess, target),
        ]

    @staticmethod
    def _name_cell(guess: Item, target: Item) -> str:
        if guess.name == target.name:
            return f"{GREEN} {guess.name}"
        shared = [ch for ch in dict.fromkeys(guess.name) if ch in target.name]
        if not shared:
            return f"{RED} 没有重合的字"
        return f"{YELLOW} 重合 {len(shared)} 字「{''.join(shared)}」"

    @staticmethod
    def _version_cell(guess: Item, target: Item, order=None) -> str:
        newer = version_newer(guess.version, target.version, order)
        label = version_label(guess.version)
        if newer == 0:
            return f"{GREEN} {label}"
        if newer < 0:
            return f"{UP} 答案比「{label}」新"
        return f"{DOWN} 答案比「{label}」旧"

    @staticmethod
    def _type_cell(guess: Item, target: Item) -> str:
        if guess.type == target.type:
            return f"{GREEN} {guess.type}"
        family = TYPE_FAMILIES.get(guess.type)
        if family and family == TYPE_FAMILIES.get(target.type):
            return f"{YELLOW} 同属{family}，但不是{guess.type}"
        return f"{RED} 不是{guess.type}"

    @staticmethod
    def _tag_cell(guess: Item, target: Item) -> str:
        mine, answer = set(guess.tags), set(target.tags)
        if mine == answer:
            return f"{GREEN} {'、'.join(guess.tags)}"
        shared = [tag for tag in guess.tags if tag in answer]
        if shared:
            return f"{YELLOW} 重合 {len(shared)} 个：{'、'.join(shared)}"
        return f"{RED} 一个标签都没对上"

    @staticmethod
    def _chars_cell(guess: Item, target: Item) -> str:
        diff = target.chars - guess.chars
        if diff == 0:
            return f"{GREEN} {guess.chars} 字"
        if diff > 0:
            return f"{UP} 答案多 {diff} 字（{guess.chars}→{target.chars}）"
        return f"{DOWN} 答案少 {-diff} 字（{guess.chars}→{target.chars}）"

    @staticmethod
    def _world_cell(guess: Item, target: Item) -> str:
        if guess.world == target.world:
            return f"{GREEN} {guess.world}"
        return f"{RED} 猜的是{guess.world}"

    # ---- 文案 ----

    def _hint(self, game: Game) -> str:
        """四次小提示，按「已经猜了几轮」触发：

        * 第 12 轮：随机说一个「它能合成的东西」；
        * 第 14 轮：随机说一个「合成它要用的材料」；
        * 第 16 轮：名字的第一个字；第 18 轮：名字的最后一个字。

        没有合成关系的题（矿石、生物……）直接说「没有再合成别的东西」/
        「不是合成出来的」，也算有效信息。名字只有一个字时第 16 / 18 轮
        不点名，换成「看看已猜里哪个最像它」。
        """
        rounds = game.rounds
        target = game.target
        if rounds == 12:
            if target.crafts_into:
                pick = self.rng.choice(target.crafts_into)
                return f"🔍 小提示：它可以合成「{pick}」。"
            return "🔍 小提示：它没有再合成别的东西。"
        if rounds == 14:
            if target.crafted_from:
                pick = self.rng.choice(target.crafted_from)
                return f"🔍 小提示：它的合成材料里有「{pick}」。"
            return "🔍 小提示：它不是合成出来的。"
        if rounds not in (16, 18):
            return ""
        if len(target.name) <= 1:
            return "🔍 小提示：答案就一个字，看看已猜里哪个最像它。"
        if rounds == 16:
            return f"🔍 小提示：名字的第一个字是「{target.name[0]}」。"
        return f"🔍 小提示：名字的最后一个字是「{target.name[-1]}」。"

    def _round_text(self, game: Game, guess: Guess) -> str:
        text = (
            f"第 {game.rounds}/{MAX_ROUNDS} 轮 · {guess.item.name}（{guess.name}）\n"
            f"{guess.render()}\n"
            f"已猜：{game.history()}　还剩 {game.left} 次"
        )
        hint = self._hint(game)
        if hint:
            text += "\n" + hint
        return text

    def _win_flavor(self, game: Game) -> str:
        """猜中时的趣味吐槽（纯文案，不影响任何结算）。"""
        if game.rounds == 1:
            return "—— 1 轮秒杀，这不是外挂？"
        if game.rounds <= 3:
            return "，这速度有点东西喵。"
        if game.left <= 0:
            return f"，第 {MAX_ROUNDS} 轮绝杀！"
        return ""

    def _win_text(self, game: Game, guess: Guess) -> str:
        wins, rank = self.record_win(game.group, guess.user, guess.name)
        players = list(game.players.values())
        shown = "、".join(players[:8])
        if len(players) > 8:
            shown += f" 等 {len(players)} 人"
        lines = [
            f"🎉 猜中啦！答案是「{game.target.name}」",
            f"{game.target.name}：{game.target.note}",
        ]
        if game.target.colored:
            lines.append("（带颜色的题只认后缀：猜「羊毛」或「红色羊毛」都算对喵）")
        lines += [
            f"第 {game.rounds}/{MAX_ROUNDS} 轮拿下（{guess.name} 猜中的）"
            f"{self._win_flavor(game)}",
            f"🐟 本局参与者：{shown}",
            f"🏆 {guess.name} 本周第 {wins} 次猜中，本群第 {rank} 名",
        ]
        log(f"{FILE_LOG} 猜中，{game.rounds} 轮，{len(players)} 人参与；"
            f"{guess.name} 本周累计 {wins} 次")
        return "\n".join(lines)

    def _lose_text(self, game: Game, guess: Guess) -> str:
        log(f"{FILE_LOG} {MAX_ROUNDS} 轮用完了，答案 {game.target.name}")
        return (
            "这么简单都没猜到，大肥鱼很难过(；′⌒`)\n"
            f"答案是「{game.target.name}」：{game.target.note}\n"
            f"最后一轮猜的是「{guess.item.name}」。下次发「弗一把」再来喵～"
        )

    def _give_up_text(self, game: Game) -> str:
        log(f"{FILE_LOG} 主动结束（{game.rounds}/{MAX_ROUNDS} 轮）")
        return (
            f"这把先不玩了喵。答案是「{game.target.name}」"
            f"：{game.target.note}\n"
            "下次发「弗一把」再来～"
        )


# 题库本身的自检在 selftest 里也用得到
__all__ = [
    "Game", "Guess", "MAX_ROUNDS", "MCGuess", "MODE_EASY", "MODE_HARD",
    "MODE_LABELS", "RESET_LABEL", "RESET_WEEKDAY", "SESSION_TTL",
    "check_data", "ITEMS", "week_key",
]
