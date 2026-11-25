"""宠物冒险的内容表：位面 / 怪物 / 道具 / 遗物 / 招式 / 事件。

只有数据与纯函数，不碰存档、不碰面板 —— 引擎在 ``pet_sword.py``。
数值口径见 ``config/宠物冒险系统.txt``；改完这里记得跑 ``--selftest``。

几个约定（引擎按这些认）：
* 怪物招式是 ``(名字, 伤害倍率, 附带效果)``，效果取值：
  ``""`` 普通 / ``"bleed"`` 让我方流血 / ``"drain"`` 吸血 / ``"crush"`` 破防 /
  ``"heal"`` 自愈 / ``"heavy"`` 就是重击（伤害倍率已经调高）。
* 事件选项的 ``good`` / ``bad`` 是一串 ``(效果, 参数)``，效果见 ``EFFECT_*``。
  ``chance = 0`` 表示必定走 good。
* 道具的 ``effect`` 由引擎解释，见 ``pet_sword.use_item``。
"""
from __future__ import annotations

from .base import *  # noqa: F401,F403

# --------------------------------------------------------------------------
# 进度结构
# --------------------------------------------------------------------------

MAX_PLANES = 8
FLOORS_PER_PLANE = 5

# 战斗类型：表里的基础数值已经体现了“普通 / 精英 / 首领”的强弱，
# 所以这里只放大银币和鲸鳞，血量攻击交给下面的统一缩放。
KIND_NORMAL = "战斗"
KIND_ELITE = "精英"
KIND_BOSS = "首领"
KINDS = (KIND_NORMAL, KIND_ELITE, KIND_BOSS)
KIND_COINS = {KIND_NORMAL: 1.0, KIND_ELITE: 2.2, KIND_BOSS: 4.5}
KIND_SCALES = {KIND_NORMAL: 0, KIND_ELITE: 2, KIND_BOSS: 4}

# 事件 / 休整 / 商店 / 宝藏 这几种节点的按钮标签（面板正文里还会写一句说明）
NODE_LABELS = {
    "战斗": "战斗", KIND_ELITE: "精英", KIND_BOSS: "首领",
    "事件": "事件", "休整": "休整", "商店": "商店", "宝藏": "宝藏",
}

# --------------------------------------------------------------------------
# 怪物
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Monster:
    name: str
    hp: int
    attack: int
    moves: tuple[tuple[str, float, str], ...]
    flavor: str = ""


@dataclass(frozen=True)
class Plane:
    index: int
    name: str
    pool: tuple[Monster, ...]
    elite: Monster
    boss: Monster


def _monster(name: str, hp: int, attack: int,
             moves: tuple[tuple[str, float, str], ...],
             flavor: str = "") -> Monster:
    return Monster(name, hp, attack, moves, flavor)


PLANES: tuple[Plane, ...] = (
    Plane(1, "浅潮滩",
          (_monster("河蟹", 46, 11,
                    (("钳击", 1.0, ""), ("横爬冲撞", 1.2, "crush")),
                    "钳子举得老高，横着就过来了。"),
           _monster("咸水虾", 40, 12,
                    (("弹射", 1.1, ""), ("甩尾", 0.9, "bleed")),
                    "身后一串水泡，弹得比谁都快。"),
           _monster("滩涂寄居蟹", 52, 10,
                    (("缩壳", 0.6, "heal"), ("螺壳突刺", 1.1, "")),
                    "壳上挂着半截渔网，挪一步晃三晃。")),
          _monster("铁壳王蟹", 90, 14,
                   (("巨钳夹击", 1.3, "crush"), ("铁甲冲撞", 1.1, ""),
                    ("吐沙", 0.7, "bleed")),
                   "壳厚得像块铁，钳子上全是旧伤。"),
          _monster("潮汐鲸王", 150, 16,
                   (("潮涌拍击", 1.4, ""), ("鲸尾横扫", 1.2, "crush"),
                    ("吞潮", 0.8, "drain")),
                   "它一翻身，整片浅滩的水都矮了一截。")),

    Plane(2, "珊瑚坟场",
          (_monster("珊瑚傀儡", 58, 12,
                    (("钙化拳", 1.2, ""), ("枝刺穿刺", 1.0, "bleed")),
                    "整块珊瑚拼起来的，关节处咔咔响。"),
           _monster("棘刺海胆", 50, 14,
                    (("万针齐发", 1.3, ""), ("蜷缩", 0.5, "heal")),
                    "慢，但扎一下能记很久。"),
           _monster("白骨水母", 46, 15,
                    (("触须缠绕", 1.0, "crush"), ("苍白电击", 1.4, "")),
                    "半透明的伞盖里游着一串骨节。")),
          _monster("千目珊瑚", 118, 17,
                   (("万目注视", 1.2, "bleed"), ("珊瑚炮", 1.5, ""),
                    ("共生修复", 0.4, "heal")),
                   "每一只眼睛都在看你，谁看谁都不舒服。"),
          _monster("珊瑚母巢", 210, 19,
                   (("母巢脉冲", 1.5, ""), ("骨刺风暴", 1.2, "bleed"),
                    ("吞噬养分", 0.9, "drain")),
                   "整座坟场都是它长出来的。")),

    Plane(3, "锈铁深渊",
          (_monster("锈齿鲨", 66, 15,
                    (("咬合", 1.3, "bleed"), ("铁鳞冲撞", 1.1, "")),
                    "牙齿是锈的，咬一口还带铁屑味。"),
           _monster("废铁潜行者", 60, 16,
                    (("暗刺", 1.4, ""), ("油污喷雾", 0.9, "crush")),
                    "贴着管壁滑过来，一点声音都没有。"),
           _monster("漏油章鱼", 72, 14,
                    (("八腕缠绞", 1.2, "crush"), ("墨汁", 0.7, "bleed")),
                    "触腕上挂满油滴，走一路黑一路。")),
          _monster("断锚巨像", 150, 20,
                   (("锚链横扫", 1.4, "crush"), ("铁拳落锤", 1.5, ""),
                    ("锈化", 0.8, "bleed")),
                   "半截船锚长在它手臂上。"),
          _monster("深渊熔炉", 260, 22,
                   (("熔渣喷涌", 1.6, ""), ("炉心过载", 1.3, "bleed"),
                    ("吃铁回炉", 0.9, "drain")),
                   "炉膛里烧的不是火，是沉下来的铁。")),

    Plane(4, "沉船墓域",
          (_monster("沉船幽灵", 74, 17,
                    (("幽咽低语", 1.0, "bleed"), ("甲板冲撞", 1.3, "")),
                    "它还在等一趟永远不来的航。"),
           _monster("锚索水鬼", 68, 18,
                    (("索链绞喉", 1.5, "crush"), ("拖入水底", 1.1, "")),
                    "湿透的绳子从桅杆上垂下来。"),
           _monster("货舱寄生体", 82, 16,
                    (("触手破舱", 1.3, ""), ("孢子", 0.8, "bleed")),
                    "货舱的木板随着它呼吸一起起伏。")),
          _monster("船长亡魂", 180, 23,
                   (("号令炮击", 1.5, ""), ("锈剑斩", 1.4, "bleed"),
                    ("亡者之舵", 0.9, "heal")),
                   "帽檐压得很低，看不清脸。"),
          _monster("沉船龙骨鲸", 320, 25,
                   (("龙骨撞击", 1.6, "crush"), ("沉船漩涡", 1.3, "bleed"),
                    ("吞舟", 1.1, "drain")),
                   "一整艘船在它肋骨之间。")),

    Plane(5, "幽光冰渊",
          (_monster("冰棱鳕", 84, 19,
                    (("冰刺突袭", 1.4, ""), ("霜息", 1.0, "crush")),
                    "鳞片下透着一层冷蓝的光。"),
           _monster("霜壳龟", 96, 17,
                    (("霜甲顶撞", 1.2, ""), ("冷雾", 0.7, "bleed")),
                    "壳上结的冰比壳本身还厚。"),
           _monster("幽光水母", 78, 21,
                    (("幽光电击", 1.6, ""), ("缠须", 0.9, "bleed")),
                    "在黑暗里亮着，像一盏会动的灯。")),
          _monster("永冻巨鲟", 215, 26,
                   (("冻河冲撞", 1.5, "crush"), ("冰鳍斩", 1.6, ""),
                    ("寒潮回涌", 0.8, "drain")),
                   "它游过的地方，水会一直结到明年。"),
          _monster("冰渊之心", 360, 28,
                   (("绝对零度", 1.7, ""), ("碎冰风暴", 1.3, "bleed"),
                    ("静默冻结", 1.0, "crush")),
                   "一颗心跳得比冰崩还慢。")),

    Plane(6, "熔鳞火海",
          (_monster("岩浆鳗", 96, 22,
                    (("灼咬", 1.4, "bleed"), ("岩浆甩尾", 1.3, "")),
                    "在水里烧得正旺，一点不怕。"),
           _monster("赤鳞蟹", 108, 20,
                    (("熔钳", 1.5, "crush"), ("热涌", 1.0, "")),
                    "壳是暗红的，钳子像两块烧透的炭。"),
           _monster("熔渣鱼群", 88, 23,
                    (("群噬", 1.55, ""), ("火星四溅", 0.9, "bleed")),
                    "一小群，烫得整片水都在冒泡。")),
          _monster("熔炉看守", 245, 29,
                   (("熔流灌注", 1.6, ""), ("铁砧落砸", 1.5, "crush"),
                    ("炉渣愈合", 0.8, "heal")),
                   "手里拎着一整条熔岩河道。"),
          _monster("焚海之鲸", 400, 32,
                   (("焚天鲸鸣", 1.6, ""), ("沸海漩涡", 1.35, "bleed"),
                    ("吞火", 1.1, "drain")),
                   "它一张嘴，海面就烧起来了。")),

    Plane(7, "裂隙星海",
          (_monster("星尘鳐", 110, 25,
                    (("星屑扫射", 1.5, ""), ("虚空滑翔", 1.1, "crush")),
                    "游过去留下一道淡淡的银河。"),
           _monster("虚空触手", 120, 24,
                    (("维度撕扯", 1.6, "bleed"), ("触须缠身", 1.2, "crush")),
                    "从裂缝里伸出来，看不出另一头通向哪。"),
           _monster("折光鱼", 100, 27,
                    (("折射光矛", 1.7, ""), ("幻影分身", 0.8, "heal")),
                    "你看它的时候，它已经不在那儿了。")),
          _monster("裂隙吞噬者", 285, 32,
                   (("裂隙吞噬", 1.7, ""), ("空间坍缩", 1.4, "crush"),
                    ("掠夺光", 0.9, "drain")),
                   "整片星海在它嘴里慢慢变暗。"),
          _monster("星海织梦者", 460, 36,
                   (("织梦之矛", 1.65, ""), ("现实回响", 1.4, "bleed"),
                    ("梦境覆写", 1.1, "crush")),
                   "它把打过的仗，又织了一遍。")),

    Plane(8, "终末鲸落",
          (_monster("腐骨鲸嗣", 130, 29,
                    (("齿骨撕咬", 1.6, "bleed"), ("尾骨砸", 1.4, "")),
                    "骨架还没长全，牙却已经够长了。"),
           _monster("深潜织梦虫", 145, 28,
                    (("丝网缠绕", 1.3, "crush"), ("梦蛾", 1.5, "")),
                    "它织的网，网住的都是睡着的东西。"),
           _monster("末路鳞卫", 160, 30,
                    (("断鳞斩", 1.7, ""), ("最后防线", 1.1, "heal")),
                    "一排排鳞片，像是要给谁守到最后一刻。")),
          _monster("鲸落守墓人", 340, 36,
                   (("墓碑落砸", 1.7, "crush"), ("深海送葬", 1.5, "bleed"),
                    ("安魂", 0.9, "heal")),
                   "它守的墓，是这片海自己。"),
          _monster("终末鲸落·大肥鱼之影", 560, 40,
                   (("镜像鲸斩", 1.7, ""), ("末路鲸肘", 1.5, "bleed"),
                    ("鲸落终章", 1.3, "crush")),
                   "它和你用的是同一套招式，只是更狠。")),
)

PLANE_BY_INDEX = {plane.index: plane for plane in PLANES}


def plane_of(index: int) -> Plane:
    return PLANE_BY_INDEX.get(int(index), PLANES[-1])


# --------------------------------------------------------------------------
# 数值换算（纯函数，自检好测）
# --------------------------------------------------------------------------


def tier_of(plane: int, floor: int) -> int:
    """第几个小关：0 ~ 39（8 位面 × 5 层）。"""
    return (int(plane) - 1) * FLOORS_PER_PLANE + (int(floor) - 1)


def stats_for(monster: Monster, plane: int, floor: int, kind: str,
              rng=random) -> dict:
    """把怪物按「第几关」放大，返回这一场的实际数值。

    表里的基础数值本身已经体现了“普通 → 精英 → 首领”的差距（40 只怪是
    一条连续的强度曲线），所以这里**不再乘类型倍率**，只按关卡整体抬一档：
    第 1 关 ×1.00，第 40 关 ×2.17（血量）/ ×1.86（攻击）。
    """
    tier = tier_of(plane, floor)
    hp_mult = 1.0 + 0.03 * tier
    atk_mult = 1.0 + 0.02 * tier
    hp = max(1, int(round(monster.hp * hp_mult * rng.uniform(0.95, 1.05))))
    attack = max(1, int(round(monster.attack * atk_mult
                              * rng.uniform(0.95, 1.05))))
    return {"name": monster.name, "hp": hp, "hp_max": hp, "attack": attack,
            "moves": monster.moves, "flavor": monster.flavor, "kind": kind}


def loot_coins(plane: int, floor: int, kind: str, rng=random) -> int:
    """打赢这一场给多少银币（进本局钱包，收工时一起结算）。"""
    base = 14 + 5 * int(plane) + 3 * int(floor)
    mult = KIND_COINS.get(kind, 1.0)
    return max(1, int(round(base * mult * rng.uniform(0.85, 1.15))))


def monster_for(plane: int, kind: str, rng=random) -> Monster:
    """从这一位面的池子里抽一只；精英 / 首领各有一个固定的狠角色。"""
    entry = plane_of(plane)
    if kind == KIND_BOSS:
        return entry.boss
    if kind == KIND_ELITE:
        return entry.elite
    return rng.choice(entry.pool)


def move_intent(stats: dict, rng=random) -> dict:
    """给怪物抽这一次出手的招式，摆在面板上当"意图"。"""
    moves = stats.get("moves") or (("攻击", 1.0, ""),)
    name, multiplier, effect = rng.choice(moves)
    return {"name": str(name), "multiplier": float(multiplier),
            "effect": str(effect)}


# --------------------------------------------------------------------------
# 道具
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Item:
    key: str
    name: str
    effect: str
    value: int
    desc: str
    where: str = "any"      # any = 随时能用 / battle = 只在战斗里
    once: bool = True       # 都是消耗品，用一次就没了（面板上要标出来）
    # 附带效果：[(效果, 参数), ...]，用来做“有正有负”的道具
    extra: tuple[tuple[str, int], ...] = ()


ITEMS: dict[str, Item] = {
    item.name: item
    for item in (
        Item("疗伤牛奶", "疗伤牛奶", "heal", 30, "回复 30 HP"),
        Item("磨刀石", "磨刀石", "sharp", 25, "锋利度 +25"),
        Item("鲸息胶囊", "鲸息胶囊", "atk_buff", 35,
             "本场战斗攻击 +35%（3 回合）"),
        Item("深海护符", "深海护符", "block", 12, "获得 12 点格挡"),
        Item("赌徒硬币", "赌徒硬币", "gamble", 0,
             "50% 回复 35 HP，50% 自己 -12 HP"),
        Item("深渊墨汁", "深渊墨汁", "enemy_debuff", 35,
             "本场敌人攻击 -35%（3 回合）"),
        Item("回响贝壳", "回响贝壳", "cooldown", 0,
             "所有招式冷却立刻清零"),
        Item("鲸骨酒", "鲸骨酒", "atk_buff", 20,
             "回复 15 HP，攻击 +20%（3 回合）"),
        Item("血之契约", "血之契约", "perm_atk", 12,
             "本局攻击 +12%，最大生命 -10"),
        Item("贪食之牙", "贪食之牙", "stack_atk", 2,
             "本局攻击 +2（可叠 5 层），每层最大生命 -3"),
        Item("幸运鳞片", "幸运鳞片", "loot", 50,
             "下一场战斗银币 +50%"),
        Item("空间鱼鳔", "空间鱼鳔", "escape", 0, "立刻脱离战斗"),
        Item("愈合苔藓", "愈合苔藓", "heal", 20, "回复 20 HP"),
        Item("星屑瓶", "星屑瓶", "star", 4,
             "3 回合内每回合对敌人造成 4 点伤害"),
        # ---- v2.14.0 新增：纯正面 / 有正有负 ----
        Item("鲸脂膏", "鲸脂膏", "heal", 10,
             "回复 10 HP，本局最大生命 +12",
             extra=(("max_hp", 12),)),
        Item("鲨牙粉", "鲨牙粉", "atk_flat", 6,
             "本局攻击 +6（纯正面）"),
        Item("双刃鳞", "双刃鳞", "atk", 12,
             "本局攻击 +12%，最大生命 -8",
             extra=(("max_hp", -8),)),
        Item("苦胆酒", "苦胆酒", "atk_buff", 30,
             "本场攻击 +30%，但自己 -6 HP",
             where="battle", extra=(("self_damage", 6),)),
        Item("蜕壳素", "蜕壳素", "heal", 20,
             "回复 20 HP，本局坚韧 +4（防守格挡更高）",
             extra=(("tough", 4),)),
    )
}

# 战斗内才能用的
BATTLE_ITEMS = ("鲸息胶囊", "深海护符", "深渊墨汁", "回响贝壳", "空间鱼鳔",
                "星屑瓶", "鲸骨酒", "赌徒硬币", "苦胆酒")


def item_line(item: Item) -> str:
    """面板上的一行：名字 + 效果 + 是否一次性。"""
    tag = "（一次性）" if item.once else ""
    where = "（限战斗）" if item.where == "battle" else ""
    return f"{item.name} — {item.desc}{tag}{where}"


def battle_items() -> tuple[Item, ...]:
    return tuple(ITEMS[name] for name in BATTLE_ITEMS)


def random_item(rng=random, exclude: tuple[str, ...] = ()) -> Item | None:
    pool = [item for name, item in ITEMS.items() if name not in exclude]
    return rng.choice(pool) if pool else None


# --------------------------------------------------------------------------
# 遗物
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Relic:
    key: str
    name: str
    desc: str          # 面板上要原样显示：正面和负面都写清楚


RELICS: dict[str, Relic] = {
    relic.name: relic
    for relic in (
        Relic("鲸骨护腕", "鲸骨护腕", "攻击 +15%，最大生命 -10%"),
        Relic("血锈之刃", "血锈之刃", "每场战斗第一击伤害翻倍，但开战 -3 HP"),
        Relic("深海耳环", "深海耳环", "招式冷却 -1（最少 1 回合），受到伤害 +2"),
        Relic("赌徒之瞳", "赌徒之瞳", "每次攻击 20% 双倍伤害、10% 反噬 5 点"),
        Relic("磨刀匠指环", "磨刀匠指环", "磨刀费用 -30%"),
        Relic("拾荒者腰带", "拾荒者腰带", "战斗银币 +25%"),
        Relic("回响鳞片", "回响鳞片", "每场战斗开始获得 6 点格挡"),
        Relic("贪婪之心", "贪婪之心", "银币 +40%，最大生命 -8%"),
        Relic("潮汐罗盘", "潮汐罗盘", "休整时额外回复 10 HP"),
        Relic("破晓鳞光", "破晓鳞光", "血量低于 30% 时攻击 +30%"),
        Relic("深渊契约", "深渊契约", "攻击 +25%，但每回合开始 -1 HP"),
        Relic("叠浪纹章", "叠浪纹章", "每通过一个位面，攻击 +4%（本局，最多 8 层）"),
        Relic("静默海螺", "静默海螺", "敌人攻击 -10%"),
        Relic("命运硬币", "命运硬币",
              "每场战斗开始 50% 获得 8 格挡 / 50% 攻击 +15%（本场）"),
        Relic("苦行者念珠", "苦行者念珠", "最大生命 +20%，攻击 -10%"),
        # ---- v2.14.0 新增：纯正面 / 有正有负 ----
        Relic("鲸脂护符", "鲸脂护符", "最大生命 +12%（纯正面）"),
        Relic("鲨齿项链", "鲨齿项链", "攻击 +10%（纯正面）"),
        Relic("蜕鳞臂甲", "蜕鳞臂甲", "坚韧 +8（纯正面，防守格挡更高）"),
        Relic("双生珊瑚", "双生珊瑚", "攻击 +18%，最大生命 -8%"),
        Relic("潮汐肺", "潮汐肺", "最大生命 +10%，剑的锋利度消耗 +25%"),
    )
}


def random_relic(rng=random, exclude: tuple[str, ...] = ()) -> Relic | None:
    pool = [relic for name, relic in RELICS.items() if name not in exclude]
    return rng.choice(pool) if pool else None


# --------------------------------------------------------------------------
# 招式（大肥鱼的攻击手段）
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Move:
    key: str
    name: str
    power: float
    hits: int
    cooldown: int
    effect: str        # "" / bleed / heal / block / debuff / execute / self_damage
    value: int
    desc: str


MOVES: dict[str, Move] = {
    move.name: move
    for move in (
        Move("次元鲸斩", "次元鲸斩", 2.4, 1, 3, "", 0,
             "2.4 倍伤害，冷却 3 回合"),
        Move("曼巴鲸肘", "曼巴鲸肘", 0.6, 3, 2, "", 0,
             "3 段 0.6 倍伤害，冷却 2 回合"),
        Move("白鲨突刺", "白鲨突刺", 1.6, 1, 3, "bleed", 3,
             "1.6 倍伤害并让敌人流血 3 回合，冷却 3 回合"),
        Move("鲸落震击", "鲸落震击", 1.8, 1, 3, "block", 6,
             "1.8 倍伤害并获得 6 格挡，冷却 3 回合"),
        Move("回声吐息", "回声吐息", 0.0, 0, 3, "heal", 14,
             "回复 14 HP，冷却 3 回合"),
        Move("潮汐连斩", "潮汐连斩", 1.1, 2, 2, "", 0,
             "2 段 1.1 倍伤害，冷却 2 回合"),
        Move("深渊凝视", "深渊凝视", 0.0, 0, 4, "debuff", 25,
             "敌人攻击 -25%（2 回合），冷却 4 回合"),
        Move("逆流冲撞", "逆流冲撞", 1.3, 1, 3, "execute", 40,
             "1.3 倍伤害，敌人血量低于 40% 时翻倍，冷却 3 回合"),
        Move("鲸歌安魂", "鲸歌安魂", 0.0, 0, 4, "heal", 8,
             "回复 8 HP 并清除流血，冷却 4 回合"),
        Move("湮灭一掷", "湮灭一掷", 3.2, 1, 5, "self_damage", 8,
             "3.2 倍伤害，但自己 -8 HP，冷却 5 回合"),
    )
}


def random_move(rng=random, exclude: tuple[str, ...] = ()) -> Move | None:
    pool = [move for name, move in MOVES.items() if name not in exclude]
    return rng.choice(pool) if pool else None


# --------------------------------------------------------------------------
# 事件
# --------------------------------------------------------------------------

# 事件效果（引擎认这些）：
EFFECT_ITEM = "item"          # 参数：道具名 / "random"
EFFECT_RELIC = "relic"
EFFECT_MOVE = "move"
EFFECT_COINS = "coins"
EFFECT_HEAL = "heal"
EFFECT_DAMAGE = "damage"
EFFECT_MAX_HP = "max_hp"
EFFECT_ATK = "atk"            # 参数：百分比（本局永久）
EFFECT_SHARP = "sharp"        # 参数：点数 / "full"
EFFECT_SHARP_MAX = "sharp_max"  # 参数：点数（改锋利度上限）
EFFECT_SCALES = "scales"
EFFECT_ATK_FLAT = "atk_flat"  # 参数：点数（本局攻击 +N）
EFFECT_TOUGH = "tough"        # 参数：点数（本局坚韧 +N，防守格挡更高）


@dataclass(frozen=True)
class Option:
    label: str                      # 按钮文字（≤10 字）
    detail: str                     # 面板正文里的说明
    good: tuple[tuple[str, object], ...] = ()
    bad: tuple[tuple[str, object], ...] = ()
    chance: float = 0.0             # 0 = 必定成功
    good_text: str = ""
    bad_text: str = ""


@dataclass(frozen=True)
class Event:
    key: str
    name: str
    text: str
    options: tuple[Option, ...]


EVENTS: dict[str, Event] = {
    event.key: event
    for event in (
        Event("crate", "漂流箱", "一只锈透的箱子卡在礁石缝里，锁扣早就烂了。",
              (Option("撬开", "随机获得一件道具",
                      good=(("item", "random"),),
                      good_text="箱盖一开，里面躺着点还能用的东西。"),
               Option("拖走", "获得 60 银币",
                      good=(("coins", 60),),
                      good_text="拆了当废铁卖，换了几枚银币。"))),
        Event("wreck", "沉船残骸",
              "半截船身斜插在泥沙里，舱门被水压顶得吱呀响。",
              (Option("潜进去", "50% 获得遗物，50% 被水压伤 10 HP",
                      good=(("relic", "random"),), bad=(("damage", 10),),
                      chance=0.5, good_text="货舱深处有个还亮着的东西。",
                      bad_text="门板弹回来砸在背上。"),
               Option("绕开", "回复 8 HP",
                      good=(("heal", 8),),
                      good_text="绕路也是赶路，顺便歇了口气。"))),
        Event("stele", "远古石碑",
              "石碑上刻着看不懂的招式图，边角还在渗水。",
              (Option("触摸", "50% 学会一个招式，50% 被反噬 12 HP",
                      good=(("move", "random"),), bad=(("damage", 12),),
                      chance=0.5, good_text="图样顺着鳍爬上来，招式记住了。",
                      bad_text="一股寒气反冲回来，指节发麻。"),
               Option("拓印", "获得 40 银币",
                      good=(("coins", 40),),
                      good_text="把图样拓下来卖给收藏家。"))),
        Event("altar", "深海祭坛",
              "祭坛中央浮着一团缓慢旋转的黑水，像是等着什么。",
              (Option("献祭", "最大生命 -10，本局攻击 +12%",
                      good=(("max_hp", -10), ("atk", 12)),
                      good_text="黑水吞掉一块肉，又还回来一股狠劲。"),
               Option("拒绝", "获得 40 银币",
                      good=(("coins", 40),),
                      good_text="祭坛上的供品，反正也没人收。"))),
        Event("plankton", "浮游生物群",
              "一片发光的浮游生物在水里打转，像下了一场很慢的雪。",
              (Option("捕捞", "回复 18 HP",
                      good=(("heal", 18),),
                      good_text="嚼起来有点咸，但很顶饱。"),
               Option("观察", "获得 50 银币",
                      good=(("coins", 50),),
                      good_text="把观测记录卖给了研究所。"))),
        Event("furnace", "破损熔炉",
              "海底居然还有一台没熄的熔炉，炉门缝里透着橙光。",
              (Option("烧一烧", "锋利度 +25",
                      good=(("sharp", 25),),
                      good_text="刃口重新泛出一点冷光。"),
               Option("拆零件", "获得 45 银币",
                      good=(("coins", 45),),
                      good_text="炉膛的合金还算值钱。"))),
        Event("gambler", "赌徒的邀请",
              "一条戴礼帽的鲶鱼晃着骰子：赌不赌，一句话。",
              (Option("赌一把", "50% 得 180 银币，50% 掉 18 HP",
                      good=(("coins", 180),), bad=(("damage", 18),),
                      chance=0.5, good_text="它把一袋银币推了过来。",
                      bad_text="骰子停下的瞬间，你被自己的倒霉气笑了。"),
               Option("不赌", "回复 10 HP",
                      good=(("heal", 10),),
                      good_text="看戏看得挺饱。"))),
        Event("bonepile", "鲸骨堆",
              "一整座鲸骨搭成的小山，缝隙里有东西在反光。",
              (Option("翻找", "50% 道具 / 50% 遗物",
                      good=(("item", "random"),), bad=(("relic", "random"),),
                      chance=0.5, good_text="摸出一个还能用的道具。",
                      bad_text="底下压着某位前辈的遗物。"),
               Option("挖骨", "获得 55 银币",
                      good=(("coins", 55),),
                      good_text="鲸骨能炼油，也能卖钱。"))),
        Event("rift", "深渊裂隙",
              "一道细长的裂缝悬在水里，另一头的光是紫的。",
              (Option("探头", "50% 遗物，50% 掉 15 HP 换 60 银币",
                      good=(("relic", "random"),),
                      bad=(("damage", 15), ("coins", 60)),
                      chance=0.5, good_text="裂缝吐出一件不属于这里的东西。",
                      bad_text="光刺得眼睛疼，但缝隙里掉出几枚银币。"),
               Option("离开", "获得 20 银币",
                      good=(("coins", 20),),
                      good_text="走之前捡了块裂缝边的碎晶。"))),
        Event("calf", "迷路的幼鲸",
              "一只比你还小的幼鲸绕着你转圈，尾巴打得很急。",
              (Option("护送", "50% 获得遗物，50% 获得道具",
                      good=(("relic", "random"),), bad=(("item", "random"),),
                      chance=0.5, good_text="它妈妈衔来一件旧物当谢礼。",
                      bad_text="它蹭了蹭你的鳍，留下一件东西就游走了。"),
               Option("收留", "回复 25 HP",
                      good=(("heal", 25),),
                      good_text="它蹭着你睡着了，你也跟着眯了一会儿。"))),
        Event("hold", "锈蚀的货舱",
              "货舱门半开着，里面堆着泡烂的木箱。",
              (Option("撬开", "60% 道具，40% 掉 10 HP",
                      good=(("item", "random"),), bad=(("damage", 10),),
                      chance=0.6, good_text="箱底压着一件没泡坏的东西。",
                      bad_text="木板塌下来砸了一下。"),
               Option("拆铜", "获得 70 银币",
                      good=(("coins", 70),),
                      good_text="铜钉锈得厉害，但收废品的照收。"))),
        Event("stardust", "星屑雨",
              "细碎的星光落进水里，落点会轻轻地炸开。",
              (Option("接住", "50% 道具，50% 锋利度 -10",
                      good=(("item", "random"),), bad=(("sharp", -10),),
                      chance=0.5, good_text="掌心里凝出一小件东西。",
                      bad_text="星屑顺着刃口划过去，蹭掉一层。"),
               Option("躲进壳里", "回复 12 HP",
                      good=(("heal", 12),),
                      good_text="等雨停，顺便打了个盹。"))),
        # ---- v2.14.0 新增：会改数值的事件（大肥鱼的冒险） ----
        Event("hot_spring", "热泉疗养",
              "海底裂开一道热泉，水温刚好，硫磺味冲得鼻子发酸。"
              "大肥鱼把肚皮摊在石头上，觉得骨头都软了。",
              (Option("泡一会儿", "最大生命 +12，回复 15 HP",
                      good=(("max_hp", 12), ("heal", 15)),
                      good_text="泡到皮肤发红，伤口结了一层薄壳，感觉更耐打了。"),
               Option("喝一口", "回复 20 HP",
                      good=(("heal", 20),),
                      good_text="又咸又烫，但胃里暖得很。"))),
        Event("carve", "鲸骨铭刻",
              "前辈的鲸骨上刻满了名字，刀痕很深。大肥鱼摸着自己的刀，也想留一笔。",
              (Option("刻上名字", "攻击 +12%，最大生命 -8",
                      good=(("atk", 12), ("max_hp", -8)),
                      good_text="刀痕刻进骨头的同时，也有一小块肉被剜走了。"),
               Option("磨掉旧痕", "锋利度 +15",
                      good=(("sharp", 15),),
                      good_text="把别人刻歪的痕迹磨平，顺便把自己的刃口也磨亮了。"))),
        Event("shark_pack", "鲨群围猎",
              "一群鲨鱼绕着你打转，带头的那条少了半片鳍。"
              "大肥鱼把剑横在身前，尾巴绷得笔直。",
              (Option("抢食", "攻击 +10%，自己 -12 HP",
                      good=(("atk", 10), ("damage", 12)),
                      good_text="从鲨口里抢下一块肉，胳膊上多了几道口子。"),
               Option("让开", "获得 40 银币",
                      good=(("coins", 40),),
                      good_text="它们散了，留下一地没人要的鳞片。"))),
        Event("fat", "脂肪储备",
              "一整季的浮游生物在胃里发胀，暖烘烘的。"
              "大肥鱼打了个嗝，觉得自己圆了一圈。",
              (Option("吃个够", "最大生命 +20，攻击 -6%",
                      good=(("max_hp", 20), ("atk", -6)),
                      good_text="圆是真圆了，动作也真慢了半拍。"),
               Option("留一点", "回复 15 HP",
                      good=(("heal", 15),),
                      good_text="留了半肚子，游起来还利索。"))),
        Event("pressure", "深海压强",
              "水压把鳍压得贴住身体，骨头在响。大肥鱼咬着牙往下沉。",
              (Option("硬扛", "坚韧 +10，最大生命 -6",
                      good=(("tough", 10), ("max_hp", -6)),
                      good_text="骨头被压得更密实，壳也硬了，只是内伤留了一点。"),
               Option("上浮", "回复 10 HP",
                      good=(("heal", 10),),
                      good_text="浮上来大口喘气，耳朵还在嗡嗡响。"))),
        Event("molt", "蜕鳞",
              "旧鳞一片片翘起来，底下是新的银光。大肥鱼有点舍不得。",
              (Option("蜕掉", "坚韧 +8",
                      good=(("tough", 8),),
                      good_text="新鳞还软，但更厚实了。"),
               Option("收集旧鳞", "获得 55 银币",
                      good=(("coins", 55),),
                      good_text="旧鳞卖给了收废品的，换了几枚银币。"))),
        Event("elder", "老鲸的馈赠",
              "一头很老很老的鲸鱼浮过来，用额头顶了顶你的刀。"
              "它什么也没说，只是慢慢游走了。",
              (Option("接受祝福", "攻击 +5（本局）",
                      good=(("atk_flat", 5),),
                      good_text="刀身轻轻震了一下，像是应了一声。"),
               Option("陪它游一段", "回复 25 HP，最大生命 +6",
                      good=(("heal", 25), ("max_hp", 6)),
                      good_text="跟得很慢，但心里很稳。"))),
        Event("dumbbell", "沉船哑铃",
              "沉船的健身舱里，铁块还泡在水里。大肥鱼试着提了提，居然没提动。",
              (Option("举两下", "攻击 +8（本局），锋利度上限 -8",
                      good=(("atk_flat", 8), ("sharp_max", -8)),
                      good_text="举是举起来了，刀刃在杠铃上磕出一个小口。"),
               Option("当废铁卖", "获得 65 银币",
                      good=(("coins", 65),),
                      good_text="铁块比想象中沉，卖价也比想象中高。"))),
        Event("echo", "深渊回声",
              "裂缝里传出你自己的叫声，只是更低沉。"
              "大肥鱼听着听着，觉得那声音在教它什么。",
              (Option("回应它", "攻击 +20%，最大生命 -20",
                      good=(("atk", 20), ("max_hp", -20)),
                      good_text="回声灌进身体，力气大了，可也空了一块。"),
               Option("堵住耳朵", "回复 12 HP",
                      good=(("heal", 12),),
                      good_text="安静下来，心跳也慢了。"))),
        Event("whetstone_rite", "磨刀祭",
              "礁石上摆着一排磨刀石，像是谁留下的仪式。大肥鱼站在中间，有点想笑。",
              (Option("磨一磨", "锋利度上限 +10",
                      good=(("sharp_max", 10),),
                      good_text="刃口薄了一层，也更锋利了。"),
               Option("拿走石头", "获得道具「磨刀石」",
                      good=(("item", "磨刀石"),),
                      good_text="揣进兜里，下次还能用。"))),
        Event("coral_feast", "饱食珊瑚",
              "珊瑚丛里飘着甜味，吃一口能顶三天。大肥鱼犹豫了一下，还是张了嘴。",
              (Option("吃", "最大生命 +10，回复 10 HP",
                      good=(("max_hp", 10), ("heal", 10)),
                      good_text="甜得发腻，但肚子里踏踏实实。"),
               Option("打包", "获得 30 银币",
                      good=(("coins", 30),),
                      good_text="装了一兜，卖给了路过的鱼贩。"))),
        Event("last_stand", "破釜沉舟",
              "身后的退路被落石堵死了。大肥鱼回头看了一眼，把剑握紧。",
              (Option("拼命", "攻击 +25%，当前最大生命 -25%",
                      good=(("atk", 25), ("max_hp", "-25%")),
                      good_text="没有退路了，反而打得比平时更狠。"),
               Option("挖开", "自己 -10 HP，获得 70 银币",
                      good=(("damage", 10), ("coins", 70)),
                      good_text="挖了很久，手掌磨破了，碎石里还翻出几枚银币。"))),
    )
}


def random_event(rng=random) -> Event:
    return rng.choice(list(EVENTS.values()))


# --------------------------------------------------------------------------
# 通关存档 & 哦鲸鲸大挑战
# --------------------------------------------------------------------------

SAVE_SLOTS = 3                 # 存档栏位
CHALLENGE_SCALES = 12          # 挑战胜利的鲸鳞


@dataclass(frozen=True)
class ChallengeBoss:
    """大挑战首领：数值期望比正常首领高一档，各自带一套机制。"""

    key: str
    name: str
    hp: int
    attack: int
    desc: str
    # 一阶段血量见底就锁血、进入二阶段
    phase2_name: str = ""
    phase2_hp: int = 0
    phase2_attack: int = 0
    # 二阶段：每次进入防御姿态时会反弹玩家这一击
    reflect: bool = False
    # 攻击时有概率麻痹玩家，让下一次防守失效
    paralyze: float = 0.0
    # 玩家的攻击有概率被弹开（无效）
    dodge: float = 0.0
    # 每回合自己回复最大生命的比例
    heal_rate: float = 0.0


CHALLENGE_BOSSES: tuple[ChallengeBoss, ...] = (
    ChallengeBoss(
        "softshell", "海德软脚虾", 320, 60,
        "血量和小怪差不多，但打空会锁血；二阶段北国沙鹰虾会反弹攻击。",
        phase2_name="北国沙鹰虾", phase2_hp=1800, phase2_attack=72,
        reflect=True,
    ),
    ChallengeBoss(
        "gpu", "显卡吞噬者老黄", 2600, 70,
        "它的攻击有概率让你麻痹 —— 麻痹时下一次防守会失效。",
        paralyze=0.45,
    ),
    ChallengeBoss(
        "trump", "川建国", 3000, 66,
        "你的攻击有 20% 会被弹开，而且它每回合都会自己回一点血。",
        dodge=0.20, heal_rate=0.03,
    ),
)

CHALLENGE_BY_KEY = {boss.key: boss for boss in CHALLENGE_BOSSES}


def challenge_boss(rng=random) -> ChallengeBoss:
    return rng.choice(CHALLENGE_BOSSES)


# --------------------------------------------------------------------------
# 结算奖励：鲸鳞（银币只留在局内花）
# --------------------------------------------------------------------------

COINS_TO_SCALES = 150          # 每 150 局内银币折 1 鲸鳞（带出来的银币换成鲸鳞）
REWARD_DEATH_RATE = 0.5        # 阵亡只带回一半鲸鳞


# --------------------------------------------------------------------------
# 鲸鳞兑换（场外）
# --------------------------------------------------------------------------

# (道具名, 价格)：买下来进仓库，下一趟冒险开局自动带入（最多 2 件）
EXCHANGE_ITEMS: tuple[tuple[str, int], ...] = (
    ("疗伤牛奶", 12),
    ("磨刀石", 10),
    ("深海护符", 15),
    ("幸运鳞片", 18),
    ("回响贝壳", 14),
)

# 启程资金：永久升级，每级 +80 局内银币（每趟冒险开局就带着）
EXCHANGE_SILVER_KEY = "silver"
EXCHANGE_SILVER_NAME = "启程资金"
EXCHANGE_SILVER_COSTS: tuple[int, ...] = (25, 40, 60)
EXCHANGE_SILVER_BONUS = 80


def exchange_silver_bonus(level: int) -> int:
    return EXCHANGE_SILVER_BONUS * max(0, int(level))


# --------------------------------------------------------------------------
# 局外养成
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Upgrade:
    key: str
    name: str
    desc: str
    costs: tuple[int, ...]     # 每级的鲸鳞花费


META_UPGRADES: dict[str, Upgrade] = {
    upgrade.key: upgrade
    for upgrade in (
        Upgrade("hp", "硬鳞", "最大生命 +8/级", (2, 4, 6)),
        Upgrade("atk", "利齿", "基础攻击 +2/级", (2, 4, 6)),
        Upgrade("blade", "护刃", "剑的锋利度消耗 -8%/级", (2, 4, 6)),
        Upgrade("start", "起手", "开局多带 1 件道具", (3, 6)),
        Upgrade("shop", "慧眼", "商店价格 -15%/级", (3, 6)),
        Upgrade("block", "鲸息", "每场战斗开始 +4 格挡/级", (3, 6)),
    )
}

# 位面清完、首领打完、全身而退时给的鲸鳞
SCALES_PER_FLOOR = 1
SCALES_PER_BOSS = 3
SCALES_PER_CLEAR = 10


def upgrade_bonus(levels: dict, key: str) -> int:
    return max(0, int(levels.get(key) or 0))


def upgrade_cost(upgrade: Upgrade, level: int) -> int:
    """升到下一级要多少鲸鳞；已经满级返回 0。"""
    level = int(level)
    if level >= len(upgrade.costs):
        return 0
    return int(upgrade.costs[level])
