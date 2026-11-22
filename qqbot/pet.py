"""宠物系统：大肥鱼。

规则来源：``config/宠物系统.txt``。要点复述一遍，改之前先对齐：

* 一切以 **20 分钟** 为最小结算单位。换操作时先结算上一个操作，不足 20 分钟
  的零头丢掉（``action_start`` 会重置到当下）。
* 体力 / 心情在上一个动作里撑不到 20 分钟的整块时，只结算撑得住的那几块，
  剩下的时间自动转成「发呆」——所以挂机三天回来也只是干到累倒然后躺着。
* **发呆每 20 分钟回 1 体力 1 心情**（慢，但保证不会彻底卡死），主要回复还是靠吃饭。
* 心情或体力为 0 时只能「发呆」和「吃饭」。
* 升级需求 20+5×等级（1→2 级 25 点，29→30 级 165 点），满级 30 不再涨经验。
* 每过 5 级，心情上限 +5、体力上限 +10（5/10/15/20/25/30 级各一次）。
* 打工 / 学习产出的银币直接进 ``Cards`` 那本账，和签到、开箱共用钱包。
"""
from __future__ import annotations

from dataclasses import dataclass

from .base import *  # noqa: F401,F403

PET_FILE = "pets_official.json"
PET_NAME = "大肥鱼"
PET_LOG = "[宠物]"

MOOD_BASE = 100                 # 1-4 级的上限；每满 5 级再涨
STAMINA_BASE = 100
MOOD_PER_STEP = 5
STAMINA_PER_STEP = 10
AFFECTION_MAX = 100             # 好感度不随等级涨，固定 100
AFFECTION_PER_WORK = 3          # 工作/学习每块掉 3 点好感（摸鱼不扣）

UNIT_SECONDS = 20 * 60          # 一个结算单位：20 分钟
MAX_LEVEL = 40
LEVEL_EXP_BASE = 20
LEVEL_EXP_STEP = 5
LEVEL_EXP_LATE_BASE = 400       # 30 级以后陡增：400 + 100×(等级-30)
LEVEL_EXP_LATE_STEP = 100

# data/situation 下的状态图（按文件名前缀取，缺图就退回纯文字面板）
SITUATION_DIR = "situation"
SITUATION = {
    "发呆": "01_bed_dazing.jpg",
    "玩耍": "02_bed_phone.jpg",
    "工作": "03_desk_working.jpg",
    "学习": "05_desk_studying.jpg",
    "吃饭": "01_bed_dazing.jpg",
    "睡觉": "04_sleep.png",
}
# 吃饭 / 玩耍时附的动图（data/images 下）
EAT_GIF = "eat.gif"
PLAY_GIF = "play.gif"

# 任一属性低于 WARN_THRESHOLD 就顶一句（第一人称，按缺哪项挑）。
# 同一人 30 分钟内只提醒一次。
WARN_COOLDOWN = 30 * 60
WARN_THRESHOLD = 10          # 严格小于：9 会提醒，10 不提醒
WARN_POOLS = {
    # 调子照「我腿软了……真的站不起来了，先给我口饭吧。」：第一人称、气弱、
    # 不怨人、末了小声提个请求。但句式要散开，别 31 句长一个样。
    # 体力见底：软、饿、惦记大白饭
    "stamina": (
        "我腿软了……真的站不起来了，先给我口饭吧。",
        "我想去盛碗大白饭……走到一半又坐回来了。",
        "碗还是空的，那碗大白饭我等了一下午。",
        "手抖得端不住碗了，喂我口大白饭，行吗。",
        "从早上到现在，我一口大白饭都没吃上。",
        "我现在站不住了。先给我口大白饭，好不好。",
        "我蹲在饭桌边上，等了半天也没人开饭。",
        "肚子叫得好响……能不能给我盛碗大白饭。",
    ),
    # 心情低：闷、空，说不出原因
    "mood": (
        "我不想说话……也不是不高兴，就是提不起劲。",
        "盯着屏幕发了一下午呆，什么也没看进去。",
        "今天谁叫我，我大概都懒得应一声了。",
        "别问我怎么了，我自己一时也说不上来。",
        "游戏打开又关掉了，视频翻两下也看不进去。",
        "我今天笑不出来。硬挤一下会更难看。",
        "能不能让我一个人在边上安静坐一会儿。",
        "心里堵得慌……坐着也不是，躺着也不是。",
    ),
    # 好感低：等不到人，不敢出声
    "affection": (
        "我等了好久……你叫我一声，好不好。",
        "今天跟我说过话的，好像只有我自己。",
        "你从我旁边走过去的时候，我都没敢出声。",
        "屋子里太安静了，我把尾巴收起来了。",
        "我就在你旁边站着，你一直没抬过头。",
        "是不是把我忘了……我一直没敢走开。",
        "别人都被叫到了，我数着，没轮到我。",
        "陪我说句话就行，我不吵你，也不闹的。",
    ),
    # 两项以上：整个人都塌了
    "all": (
        "又饿又难受，我缩在角落里一下午没动。",
        "我真的快撑不住了……给我口大白饭吧。",
        "饿得翻来覆去睡不着，也没人过来看我一眼。",
        "我手脚都是软的，眼睛都快睁不开了。",
        "先别急着问我了，喂我吃点东西，行吗。",
        "我整个人都塌下来了，你能过来一下吗。",
        "饭也没吃，人也没来，我蹲着不知道干嘛。",
    ),
}

# 玩耍的种类：**只是名字**，不影响数值，每次开始玩耍时随机挑一个，
# 显示在「玩耍中·xxx」里。想加就往下加。
PLAY_KINDS = ("CS", "MC", "看6657", "刷B站")


def limits(level: int) -> tuple[int, int]:
    """(心情上限, 体力上限)。每过 5 级各涨一次，30 级封顶。"""
    steps = max(0, min(int(level or 1), MAX_LEVEL)) // 5
    return MOOD_BASE + MOOD_PER_STEP * steps, STAMINA_BASE + STAMINA_PER_STEP * steps


@dataclass(frozen=True)
class Action:
    """一个持续动作。数值都是「每 20 分钟」。"""

    key: str
    group: str          # 一级分类：发呆 / 工作 / 学习
    stamina: int        # 负数=消耗，正数=回复
    mood: int
    affection: int = 0  # 只有玩耍是正的；工作/学习统一按 AFFECTION_PER_WORK 扣
    coins: int = 0
    exp: int = 0
    need_level: int = 1
    image: str = ""
    affection_free: bool = False  # True = 这项活儿不扣好感（摸鱼）


@dataclass(frozen=True)
class Food:
    key: str
    coins: int          # 花多少银币
    stamina: int
    mood: int
    affection: int = 0  # 少数食物还能哄人


ACTIONS: dict[str, Action] = {
    # 发呆：什么都不干，慢慢回一点点体力与心情（不至于彻底卡死）
    "发呆": Action("发呆", "发呆", 1, 1, image=SITUATION["发呆"]),
    # 睡觉：不花任何东西，躺着回体力/心情/好感，比发呆回得多
    "睡觉": Action("睡觉", "睡觉", 5, 3, affection=3, image=SITUATION["睡觉"]),
    # 玩耍：回好感、回心情、给经验，但要花一点体力（每 20 分钟 3 点）
    "玩耍": Action("玩耍", "玩耍", -3, 5, affection=10, exp=3,
                 image=SITUATION["玩耍"]),
    # 工作
    "写代码": Action("写代码", "工作", -10, -10, coins=48, exp=2, need_level=1,
                  image=SITUATION["工作"]),
    "直播": Action("直播", "工作", -5, -15, coins=55, exp=3, need_level=5,
                 image=SITUATION["工作"]),
    "摸鱼": Action("摸鱼", "工作", -5, 0, coins=12, exp=3, need_level=15,
                 affection_free=True, image=SITUATION["工作"]),
    "cos大肥鱼": Action("cos大肥鱼", "工作", -20, -10, coins=90, exp=5, need_level=20,
                    image=SITUATION["工作"]),
    "AI模型研发": Action("AI模型研发", "工作", -25, -20, coins=130, exp=15, need_level=28,
                    image=SITUATION["工作"]),
    # 学习
    "数据结构": Action("数据结构", "学习", -5, -15, exp=10, need_level=1,
                   image=SITUATION["学习"]),
    "奶龙学概论": Action("奶龙学概论", "学习", -5, -5, exp=6, need_level=5,
                    image=SITUATION["学习"]),
    "高等数学": Action("高等数学", "学习", -20, -20, exp=20, need_level=10,
                   image=SITUATION["学习"]),
    "肥鱼产后护理": Action("肥鱼产后护理", "学习", -8, -8, exp=10, need_level=15,
                     image=SITUATION["学习"]),
    "红石电子技术": Action("红石电子技术", "学习", -10, -15, exp=18, need_level=22,
                     image=SITUATION["学习"]),
}

FOODS: dict[str, Food] = {
    "大白饭": Food("大白饭", 50, 20, 20),
    "好多大肥鱼": Food("好多大肥鱼", 80, 60, 20),
    "香喷喷炒面": Food("香喷喷炒面", 50, 10, 30),
    "joja可乐": Food("joja可乐", 50, 0, 40),
    "压缩饼干": Food("压缩饼干", 50, 40, 0),
    "黄桃罐头": Food("黄桃罐头", 100, 20, 30, affection=5),
}

GROUPS = {
    "工作": ["写代码", "直播", "摸鱼", "cos大肥鱼", "AI模型研发"],
    "学习": ["数据结构", "奶龙学概论", "高等数学", "肥鱼产后护理", "红石电子技术"],
    "吃饭": list(FOODS),
}

COMMAND_PANEL = "宠物面板"
BUTTONS_PER_ROW = 3            # 面板按钮一行放几个（三个一行更好点）
# 「宠物 工作」这种二级菜单用的前缀；也是在群聊里唯一能被识别的宠物命令形状
COMMAND_PREFIX = "宠物"

# 状态文案
GROUP_LABEL = {"发呆": "发呆中", "睡觉": "睡觉中", "玩耍": "休闲中",
               "工作": "打工中", "学习": "学习中", "吃饭": "吃东西"}


def exp_need(level: int) -> int:
    """升到下一级要多少经验。

    29 级及以前线性：20 + 5×等级（1→2 级 25 点，29→30 级 165 点）；
    **到了 30 级**改用陡增曲线：400 + 100×(等级-30)（30→31 级 400 点，39→40 级 1300 点）。
    文档写的是"达到 30 级后"，所以 30 级本身就走新公式。
    """
    level = int(level)
    if level < 30:
        return LEVEL_EXP_BASE + LEVEL_EXP_STEP * level
    return LEVEL_EXP_LATE_BASE + LEVEL_EXP_LATE_STEP * (level - 30)


def duration_text(seconds: float) -> str:
    seconds = max(0, int(seconds))
    if seconds < 60:
        return "不到 1 分钟"
    hours, rest = divmod(seconds, 3600)
    minutes = rest // 60
    if hours and minutes:
        return f"{hours} 小时 {minutes} 分"
    if hours:
        return f"{hours} 小时"
    return f"{minutes} 分钟"


def affection_delta(action: Action) -> int:
    """这一块会怎么改好感度：工作/学习固定 -3（摸鱼除外），玩耍 +10，发呆不动。"""
    if action.affection_free:
        return action.affection
    if action.group in ("工作", "学习"):
        return -AFFECTION_PER_WORK
    return action.affection


def low_warning(record: dict) -> str:
    """三项里有没有低于阈值的；有就返回一句第一人称的话，没有返回空串。"""
    low = [name for name, key in (
        ("stamina", "stamina"), ("mood", "mood"), ("affection", "affection"),
    ) if float(record.get(key) or 0) < WARN_THRESHOLD]
    if not low:
        return ""
    return random.choice(WARN_POOLS["all" if len(low) >= 2 else low[0]])


def _clamp(value: float, top: int) -> int:
    return int(max(0, min(top, value)))


class Pets:
    """所有宠物记录 + 规则实现；同步方法，状态落盘到 data/pets_official.json。"""

    def __init__(self, data_dir: Path, cards, filename: str = PET_FILE) -> None:
        self.data_dir = data_dir
        # cards 可以是实例，也可以是「取实例的函数」。自检里 handler.cards 会被
        # 整个换掉（换卡池之后重建一个），直接存实例就会把钱记到旧对象上。
        self._cards = cards if callable(cards) else (lambda: cards)
        self.path = data_dir / filename
        self._users: dict[str, dict] = self._load()

    @property
    def cards(self):
        return self._cards()

    # ---- 存取 ----
    def _load(self) -> dict[str, dict]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            return {}
        if not isinstance(payload, dict):
            return {}
        return {str(k): v for k, v in payload.items() if isinstance(v, dict)}

    def _save(self) -> None:
        temporary = self.path.with_name("pets.tmp")
        try:
            temporary.write_text(
                json.dumps(self._users, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            temporary.replace(self.path)
        except OSError as error:
            log(f"{PET_LOG} 记录保存失败：{error}")

    def get(self, user_id: str, now: float | None = None) -> dict:
        """取记录（没有就建一只）。**不结算**，只把上次的零头时间记着。"""
        user_id = str(user_id)
        now = time.time() if now is None else now
        record = self._users.get(user_id)
        if record is None:
            record = self._new_record(now)
            self._users[user_id] = record
            self._save()
            log(f"{PET_LOG} {user_id[:8]}… 领养了一只{PET_NAME}")
        for key, default in (("mood", MOOD_BASE), ("stamina", STAMINA_BASE),
                             ("affection", AFFECTION_MAX), ("play_kind", ""),
                             ("warn_at", 0),
                             ("exp", 0),
                             ("level", 1), ("action", "发呆"), ("coins_earned", 0),
                             ("action_start", int(now))):
            record.setdefault(key, default)
        # 动作表改过（比如某个科目下线了）就把记录里的旧动作归位，别卡在不存在
        # 的动作上：结算和面板都会退化成发呆，但显示会自相矛盾。
        if record.get("action") not in ACTIONS:
            record["action"] = "发呆"
            record["action_start"] = int(now)
        return record

    def exists(self, user_id: str) -> bool:
        """这个人养过宠物没有。用来决定要不要往 AI 提示词里塞状态。"""
        return str(user_id) in self._users

    def _new_record(self, now: float) -> dict:
        return {
            "name": PET_NAME,
            "level": 1,
            "exp": 0,
            "mood": MOOD_BASE,
            "stamina": STAMINA_BASE,
            "affection": AFFECTION_MAX,
            "action": "发呆",
            "action_start": int(now),
            "coins_earned": 0,
            "born": int(now),
        }

    # ---- 结算 ----
    def _apply_settlement(self, record: dict, now: float) -> dict:
        """在**传进来的这份记录**上结算：只改状态，不碰钱包、不落盘。

        真实结算和"预览"共用这一段——预览时传的是拷贝，所以面板能显示
        "结算之后会是什么样"，而不会真的把钱打进去。
        """
        units = coins = exp = 0
        idle_units = 0
        stopped = False
        switched_to_idle = False
        for _ in range(64):     # 防呆上限：最多两三轮就该结束
            start = int(record.get("action_start") or now)
            blocks = int((now - start) // UNIT_SECONDS)
            if blocks <= 0:
                break
            action = ACTIONS.get(record.get("action") or "发呆") or ACTIONS["发呆"]
            usable = blocks
            if action.stamina < 0:
                usable = min(usable, int(float(record["stamina"]) // (-action.stamina)))
            if action.mood < 0:
                usable = min(usable, int(float(record["mood"]) // (-action.mood)))
            aff = affection_delta(action)
            if aff < 0:
                usable = min(usable,
                            int(float(record.get("affection") or 0) // (-aff)))
            usable = max(0, usable)
            if usable == 0:
                # 一点都干不动了：剩下的时间全当发呆
                record["action"] = "发呆"
                switched_to_idle = True
                stopped = stopped or action.key != "发呆"
                continue
            mood_max, stamina_max = limits(int(record.get("level") or 1))
            record["stamina"] = _clamp(float(record["stamina"]) + action.stamina * usable,
                                       stamina_max)
            record["mood"] = _clamp(float(record["mood"]) + action.mood * usable, mood_max)
            record["affection"] = _clamp(float(record.get("affection") or 0) + aff * usable,
                                         AFFECTION_MAX)
            if int(record.get("level") or 1) < MAX_LEVEL:
                exp += action.exp * usable
            coins += action.coins * usable
            if action.group == "发呆":
                idle_units += usable
            else:
                units += usable
            record["action_start"] = start + usable * UNIT_SECONDS
            if usable < blocks:
                record["action"] = "发呆"
                switched_to_idle = True
                stopped = stopped or action.key != "发呆"
                continue
            break
        levels = 0
        if exp:
            record["exp"] = int(record.get("exp") or 0) + exp
            levels = self._apply_level(record)
        # 干到 0 就躺下，别让状态卡在"打工中"
        if record["action"] in ("工作", "学习") and (
            record["stamina"] <= 0 or record["mood"] <= 0
            or float(record.get("affection") or 0) <= 0
        ):
            record["action"] = "发呆"
            record["action_start"] = int(now)
            switched_to_idle = True
            stopped = True
        return {
            "units": units, "idle_units": idle_units, "coins": coins, "exp": exp,
            "levels": levels, "stopped": stopped, "to_idle": switched_to_idle,
        }

    def settle(self, user_id: str, now: float | None = None) -> dict:
        """把上次操作到现在的时间按 20 分钟整块结算掉，并真的把银币打进钱包。"""
        now = time.time() if now is None else now
        record = self.get(user_id, now)
        info = self._apply_settlement(record, now)
        if info["coins"]:
            record["coins_earned"] = int(record.get("coins_earned") or 0) + info["coins"]
            self.cards.grant_shards(user_id, info["coins"])
        self._save()
        if info["units"] or info["levels"] or info["idle_units"]:
            log(f"{PET_LOG} 结算：干活 {info['units']} 块、发呆 {info['idle_units']} 块，"
                f"+{info['coins']} 银币 +{info['exp']} 经验"
                f"{f'，升 {info['levels']} 级' if info['levels'] else ''}")
        return {**info, "record": record, "action": record["action"]}

    def _preview(self, record: dict, now: float) -> tuple[dict, dict]:
        """拷贝一份记录按"现在就结算"推演，真数据一点不动。

        记录里全是 int/str/None，json 来回一趟就是干净的深拷贝。
        """
        shadow = json.loads(json.dumps(record))
        info = self._apply_settlement(shadow, now)
        return shadow, info

    def _apply_level(self, record: dict) -> int:
        ups = 0
        while int(record.get("level") or 1) < MAX_LEVEL:
            level = int(record["level"])
            need = exp_need(level)
            if int(record.get("exp") or 0) < need:
                break
            record["exp"] = int(record["exp"]) - need
            record["level"] = level + 1
            ups += 1
        if int(record.get("level") or 1) >= MAX_LEVEL:
            record["exp"] = 0
        return ups

    # ---- 操作 ----
    def switch(self, user_id: str, action_key: str,
               now: float | None = None) -> dict:
        """换动作：先结算上一个，再开始新的（零头丢掉）。"""
        now = time.time() if now is None else now
        settled = self.settle(user_id, now)
        record = settled["record"]
        action = ACTIONS.get(action_key)
        if action is None:
            return {"ok": False, "reason": "unknown", "settle": settled, "record": record}
        level = int(record.get("level") or 1)
        if level < action.need_level:
            return {"ok": False, "reason": "locked", "need_level": action.need_level,
                    "settle": settled, "record": record, "action": action}
        if action.stamina < 0 and record["stamina"] <= 0:
            return {"ok": False, "reason": "exhausted", "settle": settled,
                    "record": record, "action": action}
        if action.group in ("工作", "学习") and (
            record["mood"] <= 0
            or (float(record.get("affection") or 0) <= 0
                and not action.affection_free)
        ):
            return {"ok": False, "reason": "exhausted", "settle": settled,
                    "record": record, "action": action}
        changed = record.get("action") != action.key
        if changed:
            # 只有「换了动作」才算新的操作、才丢掉不足 20 分钟的零头；
            # 点同一个按钮不该把正在跑的时长清零。
            record["action"] = action.key
            record["action_start"] = int(now)
            if action.group == "玩耍":
                # 每次开始玩都换一个花样，只影响显示、不影响数值
                record["play_kind"] = random.choice(PLAY_KINDS)
        self._save()
        return {"ok": True, "changed": changed, "settle": settled,
                "record": record, "action": action}

    def eat(self, user_id: str, food_key: str, now: float | None = None) -> dict:
        """吃东西：先结算上一段，再扣银币回体力心情。

        吃饭本身也算一次"新操作"，所以和换动作一样：结算 → 丢掉不足 20 分钟
        的零头 → 吃完继续做原来的事。
        """
        now = time.time() if now is None else now
        settled = self.settle(user_id, now)
        record = settled["record"]
        food = FOODS.get(food_key)
        if food is None:
            return {"ok": False, "reason": "unknown", "settle": settled, "record": record}
        mood_max, stamina_max = limits(int(record.get("level") or 1))
        stamina_after, mood_after = self._projected(record, now)
        stats_full = (stamina_after >= stamina_max and mood_after >= mood_max)
        affection_full = (food.affection <= 0
                          or float(record.get("affection") or 0) >= AFFECTION_MAX)
        if stats_full and affection_full:
            return {"ok": False, "reason": "full", "settle": settled,
                    "record": record, "food": food}
        left = self.cards.spend_shards(user_id, food.coins)
        if left is None:
            return {"ok": False, "reason": "poor", "settle": settled, "record": record,
                    "food": food, "shards": self.cards.shards_of(user_id)}
        record["stamina"] = _clamp(float(record["stamina"]) + food.stamina, stamina_max)
        record["mood"] = _clamp(float(record["mood"]) + food.mood, mood_max)
        if food.affection:
            record["affection"] = _clamp(
                float(record.get("affection") or 0) + food.affection, AFFECTION_MAX)
        record["action_start"] = int(now)   # 这一次的零头就不算了
        self._save()
        return {"ok": True, "settle": settled, "record": record, "food": food,
                "shards": left}

    def _projected(self, record: dict, now: float) -> tuple[float, float]:
        """按还没结算的块数推算体力/心情会变成多少（只读，不改记录）。"""
        action = ACTIONS.get(record.get("action") or "发呆") or ACTIONS["发呆"]
        blocks = max(0, int((now - int(record.get("action_start") or now)) // UNIT_SECONDS))
        if action.stamina < 0:
            blocks = min(blocks, int(float(record["stamina"]) // (-action.stamina)))
        if action.mood < 0:
            blocks = min(blocks, int(float(record["mood"]) // (-action.mood)))
        mood_max, stamina_max = limits(int(record.get("level") or 1))
        return (
            float(_clamp(float(record["stamina"]) + action.stamina * blocks, stamina_max)),
            float(_clamp(float(record["mood"]) + action.mood * blocks, mood_max)),
        )

    def warn_text(self, user_id: str, now: float | None = None) -> str:
        """这个人要不要顶一句：没养宠物、三项都不低于阈值、或者还在冷却 → 空串。"""
        if not self.exists(user_id):
            return ""
        now = time.time() if now is None else now
        snapshot = self.snapshot(user_id, now)   # 用结算后的数值判断
        text = low_warning(snapshot["record"])
        if not text:
            return ""
        record = self.get(user_id, now)
        if now - float(record.get("warn_at") or 0) < WARN_COOLDOWN:
            return ""
        record["warn_at"] = int(now)             # 记在**真实**记录上，不是预览副本
        self._save()
        return text

    # ---- 只读 ----
    def snapshot(self, user_id: str, now: float | None = None) -> dict:
        """给面板用：展示**结算之后**的样子，但不落账、不改记录。

        面板上的数字＝你现在切一下动作会得到的数字，显示和实际就不会打架。
        """
        now = time.time() if now is None else now
        record = self.get(user_id, now)
        elapsed = max(0, now - int(record.get("action_start") or now))
        blocks = int(elapsed // UNIT_SECONDS)
        shown, info = (self._preview(record, now) if blocks > 0 else (record, {}))
        action = ACTIONS.get(shown.get("action") or "发呆") or ACTIONS["发呆"]
        level = int(shown.get("level") or 1)
        mood_max, stamina_max = limits(level)
        return {
            "record": shown,
            "action": action,
            "elapsed": elapsed,
            "blocks": blocks,
            "mood_max": mood_max,
            "stamina_max": stamina_max,
            "affection_max": AFFECTION_MAX,
            "coins": self.cards.shards_of(user_id),
            "pending_coins": int(info.get("coins") or 0),
            "pending_exp": int(info.get("exp") or 0),
        }

    def shards_of(self, user_id: str) -> int:
        return self.cards.shards_of(str(user_id))


# --------------------------------------------------------------------------
# 文案
# --------------------------------------------------------------------------


def status_line(snapshot: dict) -> str:
    record = snapshot["record"]
    action = snapshot["action"]
    elapsed = snapshot["elapsed"]
    # 卡片上宽度紧张，"1 小时 20 分" 这种带空格的写法会被折成两行，
    # 这里统一压掉空格，中文阅读也不别扭。
    span = "刚开始" if elapsed < 60 else f"已持续{duration_text(elapsed).replace(' ', '')}"
    tired = record["stamina"] <= 0 or record["mood"] <= 0
    upset = float(record.get("affection") or 0) <= 0
    if action.group == "发呆":
        if tired and upset:
            return "又累又不想理你，只好躺着"
        if upset:
            return "不太想理你，正在发呆"
        if tired:
            return "累趴了，只能躺着"
        return f"发呆中 · {span}"
    if action.group == "睡觉":
        return f"睡觉中 · {span}"
    if action.group == "玩耍":
        # 跟「打工中：写代码」保持同一套排版：冒号 + 换行
        kind = str(record.get("play_kind") or "").strip() or "随便玩玩"
        return f"玩耍中：{kind}\n{span}"
    tail = ""
    if snapshot["pending_coins"]:
        tail = f" · 待结算 {snapshot['pending_coins']}"
    return f"{GROUP_LABEL.get(action.group, '忙')}：{action.key}\n{span}{tail}"


# 一句话：按状态挑，第一人称、大肥鱼口吻
_CHATTER = {
    "hungry_stamina": (
        "我腿软了……真的站不起来了，先给我口饭吧。",
        "体力见底了啦，再干下去就要趴在键盘上了。",
    ),
    "hungry_mood": (
        "心情差到不想说话……能不能让我躺一会儿。",
        "再逼我干活我要生气了哦。",
    ),
    "tired": (
        "有点撑不住了，想歇会儿。",
        "唔……脑袋开始发木了。",
    ),
    "working": (
        "代码写得很顺，别打扰我。",
        "这一版一定能跑起来，我保证。",
        "键盘声听着真舒服，我还能再战。",
    ),
    "studying": (
        "这个知识点我记住了，你别考我。",
        "看书看得眼睛发酸，但还行。",
        "等我学完这些，就能干更值钱的活了。",
    ),
    "idle": (
        "躺着真舒服，你要不要也躺一会儿。",
        "我什么都没干，但我一点都不心虚。",
        "发呆是我的天赋，别打扰。",
    ),
    "sleeping": (
        "呼……呼……",
        "别吵，我再睡五分钟。",
        "梦里有一条很大的鱼。",
        "被子有点薄，但还行。",
    ),
    "playing": (
        "再玩一会儿，就一会儿。",
        "这个好玩，你也来看看。",
        "别催别催，我正玩到关键的地方。",
    ),
    "sulky": (
        "不太想说话……你先忙你的吧。",
        "哼，我才不是在生气。",
        "有点累了，不想理人。",
    ),
    "maxed": (
        "我已经满级了，现在就负责可爱。",
    ),
}


def chatter(record: dict, action: Action) -> str:
    """第一人称的一句话。用规则挑，不走 AI（离线可用、也省钱）。"""
    if int(record.get("level") or 1) >= MAX_LEVEL:
        return random.choice(_CHATTER["maxed"])
    if action.group == "睡觉":
        return random.choice(_CHATTER["sleeping"])
    if record["stamina"] <= 20:
        return random.choice(_CHATTER["hungry_stamina"])
    if record["mood"] <= 20:
        return random.choice(_CHATTER["hungry_mood"])
    if record["stamina"] <= 40 or record["mood"] <= 40:
        return random.choice(_CHATTER["tired"])
    if action.group == "工作":
        return random.choice(_CHATTER["working"])
    if float(record.get("affection") or 0) <= 20:
        return random.choice(_CHATTER["sulky"])
    if action.group == "学习":
        return random.choice(_CHATTER["studying"])
    if action.group == "玩耍":
        return random.choice(_CHATTER["playing"])
    return random.choice(_CHATTER["idle"])


def panel_markdown(snapshot: dict) -> str:
    """主面板的 markdown 正文（图片已经在上面那条发过了）。"""
    record = snapshot["record"]
    return (
        f"**{record['name']}**  Lv.{int(record['level'])}  ·  "
        f"体力 {record['stamina']}/{snapshot['stamina_max']}  ·  "
        f"心情 {record['mood']}/{snapshot['mood_max']}  ·  "
        f"好感 {record['affection']}/{snapshot['affection_max']}\n"
        f"银币 **{snapshot['coins']}**\n"
        f"{status_line(snapshot)}"
    )


def group_markdown(title: str, keys: list[str], record: dict) -> str:
    """二级菜单正文：列出这一组里有什么、哪些还没解锁。"""
    level = int(record.get("level") or 1)
    if title == "吃饭":
        lines = []
        for key in keys:
            food = FOODS[key]
            gain = []
            if food.stamina:
                gain.append(f"体力+{food.stamina}")
            if food.mood:
                gain.append(f"心情+{food.mood}")
            if food.affection:
                gain.append(f"好感+{food.affection}")
            lines.append(f"**{food.key}**\n{food.coins} 银币 → {' '.join(gain)}")
    else:
        lines = []
        for key in keys:
            action = ACTIONS[key]
            lock = "" if level >= action.need_level else f"（Lv.{action.need_level}）"
            cost = []
            if action.stamina:
                cost.append(f"体力{action.stamina:+d}")
            if action.mood:
                cost.append(f"心情{action.mood:+d}")
            gain = []
            if action.coins:
                gain.append(f"{action.coins} 银币")
            if action.exp:
                gain.append(f"{action.exp} 经验")
            lines.append(f"**{key}**{lock}\n{' '.join(cost)} → {' '.join(gain) or '没产出'}")
    return f"### {title}\n" + "\n".join(lines)


def settle_summary(settle: dict | None, record: dict) -> str:
    """把一次结算压成一句话。换动作和吃饭都要发同一份提示。"""
    settle = settle or {}
    units = int(settle.get("units") or 0)
    if units:
        bits = [f"结算了 {units} 个 20 分钟"]
        if settle.get("coins"):
            bits.append(f"+{settle['coins']} 银币")
        if settle.get("exp"):
            bits.append(f"+{settle['exp']} 经验")
        if settle.get("levels"):
            bits.append(f"升到 Lv.{int(record.get('level') or 1)}")
        return "，".join(bits) + "。"
    if settle.get("stopped"):
        return "上一个活儿干到脱力，先躺平了。"
    return ""


def switch_text(result: dict, snapshot: dict | None = None) -> str:
    record = result["record"]
    action = result.get("action")
    name = action.key if action else "发呆"
    if not result.get("ok"):
        reason = result.get("reason")
        if reason == "locked":
            return f"{name}要 Lv.{result.get('need_level')} 才能碰，我还没长那么大。"
        if reason == "exhausted":
            return "我已经没力气也没心情了，只能发呆、睡觉或者吃点东西。"
        return "这个操作现在做不了。"
    summary = settle_summary(result.get("settle"), record)
    head = f"{summary}\n" if summary else ""
    return f"{head}现在{GROUP_LABEL.get(action.group, '忙着')}：**{name}**。"


def eat_text(result: dict, snapshot: dict | None = None) -> str:
    """吃东西的结果。``snapshot`` 传进来的话，数字按"结算之后"报。"""
    if not result.get("ok"):
        reason = result.get("reason")
        if reason == "poor":
            return f"银币不够，这顿吃不起（你有 {result.get('shards')}）。"
        if reason == "full":
            return "我现在饱得很，吃不下了。"
        return "吃不了。"
    food = result["food"]
    record = (snapshot or {}).get("record") or result["record"]
    return (f"吃完了{food.key}，体力回到 {record['stamina']}、心情回到 {record['mood']}。\n"
            f"银币余额 {result.get('shards')}。")
