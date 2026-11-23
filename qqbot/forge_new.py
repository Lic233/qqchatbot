"""新锻造系统：选材 → 锻造 → 淬火 → 测试，四阶段走按钮面板。

规则照 ``config/新锻造系统.txt``（旧版的 ``forge.py`` 原样保留，入口在 handler 里
用一个开关关掉了，见 ``handler.LEGACY_FORGE_ENABLED``）：

* **选材**：发「锻造」开局面板，四种材料各标一个价（草钢 140 / 陨铁 280 /
  弹簧钢 620 / 强化合金 1288 银币）。买材料时扣银币、随机出一种刀型，属性、塑性和
  刀型都跟着材料走。银币不够直接拒绝，**没有免费开局这回事**。
* **锻造**：``用力砸`` 没有次数上限；第 n 锤三项属性各自在 ±min(9+n, 15) 内随机，
  这个范围还会被**塑性**整体平移（期望 -10 ~ +10，每锤塑性 -3）；属性没有上限，
  但**任一项掉到 0 这一炉就报废**（材料钱不退、没有收益）。``回火`` 砸够 5 锤可用，
  按正态重摇塑性（均值固定 55，不随次数衰减）。
* **淬火**：水淬 / 油淬 二选一，只决定图案模板的概率分布，不动属性；部分基础模板
  还会按单独判定「变异」成全蓝淬火 / 蓝宝石 / 红宝石 / 绿宝石。
* **测试**：单项成绩 ~ N(属性, 属性/10)，只保底 0、没有上限，三项合计是总分。
  同时按三项属性的离散程度判定**磨损**（崭新出厂 ×1.15 ~ 战痕累累 ×0.85）。
  总价值 = 四舍五入(B × P × T × 材料系数 K × 磨损倍率 W)，其中
  ``T = 4.35 * (e^(S'/120) - 1) / (e^2.5 - 1)``（S > 300 的部分按 35% 折算），
  直接加进银币余额。
* **面板只认最新那条**：每发一次面板 ``seq`` +1，按钮 data 里带着锻造 id 和这个
  seq；点旧面板会被判过期，所以一次操作只会生效一次，也不会和别人的局串味。
* 收工记一条锻造排行榜（锻造人 / 时间 / 刀型 / 图案 / 分数 / 总价值），见
  ``forge_rank.py``。

局内进度只放内存（重启就散），排行榜才落盘。
"""
from __future__ import annotations

import math

from .base import *  # noqa: F401,F403

# --------------------------------------------------------------------------
# 规则常量
# --------------------------------------------------------------------------

STAGE_PICK = "选材"
STAGE_FORGE = "锻造"
STAGE_QUENCH = "淬火"
STAGE_NAMES = (STAGE_PICK, STAGE_FORGE, STAGE_QUENCH)

# 面板按钮的 data 一律是「锻造 <锻造id> <面板序号> <动作> [参数]」。
# 只认这种格式，所以「用力砸」「结束锻造」这些旧文字命令现在一条都不响应。
PANEL_PREFIX = "锻造"
ACTION_MATERIAL = "料"
ACTION_HAMMER = "砸"
ACTION_FINISH = "收"
ACTION_WATER = "水"
ACTION_OIL = "油"
ACTION_RECOVER = "回"

# 用力砸：
# * **没有次数上限**，砸到属性见底（任一属性归零）这一炉就废；
# * 波动范围随回合变大：第 1 锤 ±10，之后每锤上下各多 1，到第 6 锤起固定 ±15；
# * 属性**没有上限**（想砸多高砸多高，但 100 就是满分线，再高也不再涨分）。
# 塑性：0~100，只影响用力砸的期望，不参与测试评分。
# 期望曲线是 **反 S 型（1.5 次方）**：中间 40~60 较平，越往两端越陡。
#   E(p) = 10 × sign(x) × |x|^1.5  (x = (p - 50) / 50) → 0 是 -10、50 是 0、100 是 +10
# 每砸一锤塑性 -3；回火可以重摇塑性，但每次回火的上限递减（见 RECOVERY_CAPS）。
PLASTICITY_MAX = 100
PLASTICITY_PIVOT = 50            # 过零点：塑性 50 期望为 0
PLASTICITY_DECAY = 3             # 每锤掉多少
HAMMER_EXPECT_TOP = 10           # 期望的绝对值上限（每项属性）
PLASTICITY_CURVE_POWER = 1.0     # 1=直线（50 附近最有感），越大中间越平
RECOVERY_INTERVAL = 5            # 两次回火之间至少砸几次
RECOVERY_MEAN = 55               # 回火后塑性的中心值（固定值，不再随次数衰减）
RECOVERY_SIGMA = 15.0            # 回火的正态标准差

HAMMER_START = 10                # 第 1 锤的波动半径
HAMMER_GROWTH = 1                # 每过一锤半径 +1
HAMMER_MAX_RADIUS = 15           # 半径最多这么大（第 6 锤起）
ATTR_FLOOR = 0                   # 任一属性掉到 0 就地强制失败，所以属性不会变负
ATTR_NAMES = ("强度", "硬度", "韧性")
TEST_ROUNDS = 100                # 单项基准分（属性 100 → 平均 100 分）
TEST_MAX_SCORE = TEST_ROUNDS * 3  # 基准满分 300（现在可以突破）

# ---- 测试：正态分布出分 ----
# 属性 a 的得分 ~ N(a, a/10)：均值就是属性本身，标准差是属性的 1/10。
# 也就是说属性 60 平均考 60 分（上下浮动约 ±6），属性 150 平均 150 分（约 ±15）——
# 属性越高，平均分和“运气浮动”一起变大，没有上限。
SCORE_SIGMA_RATIO = 0.1

# 性能系数：T = PERFORMANCE_TOP × (e^(S'/120) - 1) ÷ (e^(300/120) - 1)
# PERFORMANCE_TOP 就是 300 分时的值（也是所有成品价值的全局倍率）。
# S' 是"折算分"：300 分以内直接用 S；超过 300 的部分按 OVERFLOW_RATE 打折，
# 这样高端局不会因为指数曲线炸出天文数字（分数仍然可以往上考，只是价值涨得慢）。
PERFORMANCE_TOP = 4.35
PERFORMANCE_DIVISOR = 120.0
PERFORMANCE_NORM = math.exp(300 / PERFORMANCE_DIVISOR) - 1.0
PERFORMANCE_OVERFLOW_RATE = 0.35   # 超过 300 分的部分只按 35% 计入性能系数

# 磨损度：测试时按三项属性的"离散程度"判定，越均匀越新。
# 差异度取「最大占比 - 最小占比」，再用正态分布 CDF 映射到 0 ~ 0.80 的磨损值。
WEAR_MAX = 0.80
# 差异度按**占比**算：每项属性占总和的多少，取「最大占比 - 最小占比」。
# 占比极差的理论范围是 0 ~ 2/3（三项平均时是 0），下面两个常数按这个尺度定。
WEAR_CENTER = 0.26               # 占比极差落在这个值上时，磨损正好到中位数
WEAR_WIDTH = 0.14                # 映射的"宽度"，越小越极端
# (名称, 磨损值上限, 价值倍率)
WEAR_GRADES: tuple[tuple[str, float, float], ...] = (
    ("崭新出厂", 0.07, 1.15),
    ("略有磨损", 0.15, 1.05),
    ("久经沙场", 0.38, 1.00),
    ("破损不堪", 0.45, 0.95),
    ("战痕累累", 0.80, 0.85),
)

# 锻造 id：短、好念、不会和别的东西撞（去掉了 0/o/1/l/i 这种容易看混的字符）。
FORGE_ID_ALPHABET = "23456789abcdefghjkmnpqrstuvwxyz"
FORGE_ID_LENGTH = 6
# 一局超过这么久还没收工，就当人跑了：再发「锻造」直接开新局。
SESSION_TTL = 2 * 60 * 60


@dataclass(frozen=True)
class Knife:
    name: str
    base: int          # 刀型基础价值 B


@dataclass(frozen=True)
class Pattern:
    name: str
    multiplier: float  # 图案模板倍率 P


@dataclass(frozen=True)
class Material:
    name: str
    price: int
    strength: int
    hardness: int
    toughness: int
    # 出刀概率，顺序与 KNIVES 一致
    knives: tuple[float, ...]
    # 材料收益系数：现在是 1.00（价格按期望反推），留着当校准旋钮
    payout: float = 1.0
    # 开局塑性区间（闭区间，买料时在里面随机）：贵的料不代表塑性就好
    plasticity: tuple[int, int] = (40, 65)

    @property
    def attrs(self) -> tuple[int, int, int]:
        return (self.strength, self.hardness, self.toughness)


# 刀型：价值依次上升（越贵的材料出好刀的概率越高，见各材料的 knives）
# 2026-11-20 加了两把：骷髅匕首（折叠刀与刺刀之间）、锯齿爪刀（刺刀与蝴蝶刀之间）；
# 同时蝴蝶刀 550 → 650、爪子刀 800 → 900。
KNIVES: tuple[Knife, ...] = (
    Knife("廓尔喀刀", 120),
    Knife("折叠刀", 230),
    Knife("骷髅匕首", 310),
    Knife("刺刀", 390),
    Knife("锯齿爪刀", 490),
    Knife("蝴蝶刀", 680),
    Knife("爪子刀", 920),
    Knife("M9刺刀", 1200),
)
KNIFE_BASE = {knife.name: knife.base for knife in KNIVES}

# 图案模板（基础）：价值依次上升。概率表只认这 12 个。
# 2026-11-20 补了六个：表面生锈 / 澄澈之水 / 无涂装 / 传说 / 渐变大理石 / 伽马多普勒。
PATTERNS: tuple[Pattern, ...] = (
    Pattern("狩猎网格", 0.8),
    Pattern("表面生锈", 0.82),
    Pattern("澄澈之水", 0.88),
    Pattern("屠夫", 1.0),
    Pattern("无涂装", 1.13),
    Pattern("大马士革钢", 1.34),
    Pattern("传说", 1.55),
    Pattern("表面淬火", 1.85),
    Pattern("渐变大理石", 2.35),
    Pattern("多普勒", 2.95),
    Pattern("伽马多普勒", 4.0),
    Pattern("渐变之色", 6.0),
)
# 特殊模板：基础模板"变异"出来的，不占概率表，由下面 SPECIAL_ROLLS 的单独一次判定决定
SPECIAL_PATTERNS: tuple[Pattern, ...] = (
    Pattern("蓝宝石", 10.0),
    Pattern("红宝石", 10.0),
    Pattern("绿宝石", 10.0),
    Pattern("全蓝淬火", 15.0),
)
PATTERN_MULTIPLIER = {
    pattern.name: pattern.multiplier
    for pattern in PATTERNS + SPECIAL_PATTERNS
}

# 特殊判定：先按概率表抽出基础模板，再按这里的概率试着"变异"。
# 多普勒家族的总体出现率沿用旧表（水淬 蓝 2.5% + 红 2.5% + 多普勒 8% = 13%；
# 油淬 1% + 1% + 10% = 12%），所以子判定的比例 = 宝石率 ÷ 家族率。
SPECIAL_ROLLS: dict[str, dict[str, tuple[tuple[str, float], ...]]] = {
    "水淬": {
        "表面淬火": (("全蓝淬火", 0.10),),
        "多普勒": (("蓝宝石", 0.25), ("红宝石", 0.25)),
        "伽马多普勒": (("绿宝石", 0.35),),
    },
    "油淬": {
        "表面淬火": (("全蓝淬火", 0.05),),
        "多普勒": (("蓝宝石", 0.10), ("红宝石", 0.10)),
        "伽马多普勒": (("绿宝石", 0.10),),
    },
}

# 淬火方式 → 图案概率（与 PATTERNS 同序）。水淬波动大、油淬集中在中档。
QUENCH_NAMES = ("水淬", "油淬")
# 与 PATTERNS 同序；多普勒 / 伽马多普勒 这两档是**家族合计**（含宝石、绿宝石）
# 两张表都是驼峰形（峰值在中段），油淬的峰更高更窄、水淬更宽更平；总期望与原表基本持平
QUENCH_PROBABILITIES = {
    "水淬": (0.06, 0.07, 0.09, 0.11, 0.12, 0.12, 0.12, 0.10, 0.08, 0.06, 0.04, 0.03),
    "油淬": (0.01, 0.02, 0.05, 0.09, 0.13, 0.16, 0.17, 0.15, 0.11, 0.07, 0.03, 0.01),
}
QUENCH_ACTION = {ACTION_WATER: "水淬", ACTION_OIL: "油淬"}

# 每张概率表的长度必须和 KNIVES 对齐，改刀型时记得一起改（错了 roll_knife 会下标越界）
MATERIALS: dict[str, Material] = {
    material.name: material
    for material in (
        # 概率统一两位小数；四舍五入后不足 1 的差额补在最大的一项上
        Material("草钢", 140, 20, 15, 15,
                 (0.44, 0.17, 0.13, 0.10, 0.09, 0.04, 0.02, 0.01),
                 payout=1.00, plasticity=(62, 78)),
        Material("陨铁", 280, 25, 30, 20,
                 (0.10, 0.13, 0.16, 0.20, 0.17, 0.14, 0.07, 0.03),
                 payout=1.00, plasticity=(52, 68)),
        Material("弹簧钢", 620, 35, 30, 45,
                 (0.05, 0.09, 0.13, 0.17, 0.18, 0.19, 0.12, 0.07),
                 payout=1.00, plasticity=(52, 72)),
        Material("强化合金", 1288, 60, 55, 40,
                 (0.01, 0.02, 0.04, 0.06, 0.11, 0.20, 0.30, 0.26),
                 payout=1.00, plasticity=(45, 60)),
    )
}

for _material in MATERIALS.values():
    assert len(_material.knives) == len(KNIVES), (
        f"{_material.name} 的刀型概率表有 {len(_material.knives)} 项，"
        f"但刀型有 {len(KNIVES)} 种"
    )

NO_SESSION_REPLY = "现在没有正在进行的锻造。发「锻造」开一局吧。"
STALE_REPLY = "这条面板已经用过了，看最新那条吧。"

# 面板底下那句闲话：删掉规则说明之后空了一大截，随机抽一句撑撑场面。
# 刚买完料 / 砸过几锤 / 砸满十锤，三种场合分开写，免得说错话。
FORGE_FLAVOR_OPEN = (
    "料已经架上砧板了，趁热来一锤？",
    "炉火正旺，刀坯还软着，这会儿捶最省力。",
    "看这料的纹路，说不准是把好刀。",
    "手别抖，第一锤最关键。",
)
FORGE_FLAVOR = (
    "火星子溅了一地，虎口有点发麻。",
    "这一锤下去，接缝顺眼多了。",
    "声音比刚才脆了，有点样子。",
    "铁腥味有点重，不过手感还行。",
    "纹路慢慢出来了，别停。",
    "好刀都是捶出来的，急不得。",
    "看着像把刀了 —— 虽然还不太像。",
    "再捶两下，说不定就出彩了。",
    "砧板震了一下，耳朵嗡嗡的。",
    "手腕压住，一锤定音。",
)
# 属性快见底时换这套：这一锤再往下砸就要废了，得提醒一句。
FORGE_FLAVOR_DANGER = (
    "手感不对了……再砸下去怕是要见底。",
    "有一项已经快撑不住，收手还来得及。",
    "裂纹顺着刀背爬，再重一点就要断。",
    "别贪那一锤，废了就什么都没有了。",
)
DANGER_THRESHOLD = 40            # 任一属性低于这个数，面板就换成危险台词


# --------------------------------------------------------------------------
# 概率与数值
# --------------------------------------------------------------------------


def _weighted(pairs: tuple[tuple[str, float], ...] | list[tuple[str, float]],
              rng) -> str:
    """按权重抽一个名字；概率表加起来不等于 1 时，剩下的概率给最后一个。"""
    roll = rng.random()
    total = 0.0
    for name, weight in pairs:
        total += weight
        if roll < total:
            return name
    return pairs[-1][0]


def roll_knife(material: Material, rng=random) -> str:
    """按材料自己的概率表出一把刀（越贵的材料越容易出好刀）。"""
    return _weighted([(knife.name, material.knives[index])
                      for index, knife in enumerate(KNIVES)], rng)


def roll_pattern(quench: str, rng=random) -> str:
    """按淬火方式抽图案：先抽基础模板，再按 SPECIAL_ROLLS 试一次"变异"。

    变异是**单独一次判定**（比如表面淬火有 5% 变成全蓝淬火），
    判定失败就保留基础模板。
    """
    weights = QUENCH_PROBABILITIES[quench]
    base = _weighted([(pattern.name, weights[index])
                      for index, pattern in enumerate(PATTERNS)], rng)
    specials = SPECIAL_ROLLS.get(quench, {}).get(base, ())
    if specials:
        # 一次判定按累计概率取：这样每个特殊模板的触发率就是它写的那个数
        roll = rng.random()
        acc = 0.0
        for special, chance in specials:
            acc += chance
            if roll < acc:
                return special
    return base


def mean_score(attr: float) -> float:
    """这项属性的平均得分：**就是属性本身**（属性 60 → 平均 60 分）。"""
    return max(float(attr), 0.0)


def score_sigma(attr: float) -> float:
    """出分的标准差：属性的 1/10（属性 60 → 上下浮动约 ±6）。"""
    return mean_score(attr) * SCORE_SIGMA_RATIO


def score_for(attr: float, rng=random) -> int:
    """单项属性的测试成绩 ~ N(属性, 属性/10)，四舍五入。

    没有上限（属性 150 平均 150 分，还能往上飘），下限 0 分。
    """
    mean = mean_score(attr)
    if mean <= 0:
        return 0
    return int(max(round(rng.gauss(mean, score_sigma(attr))), 0))


def run_test(attrs: list[int] | tuple[int, ...], rng=random) -> list[int]:
    """三项属性各出一个 0~100 的成绩（正态分布），返回三项。"""
    return [score_for(attr, rng) for attr in attrs]


def hammer_expect(plasticity: int) -> int:
    """塑性给出的「每项属性的期望变化」。

    ``E = 10 × x``（x = (p-50)/50，线性）：塑性每多一点，期望就跟着涨一点，
    50 附近最有手感（55 → +1、60 → +2、65 → +3），0 / 100 时到 ∓10。
    """
    span = (int(plasticity) - PLASTICITY_PIVOT) / (PLASTICITY_MAX - PLASTICITY_PIVOT)
    value = math.copysign(HAMMER_EXPECT_TOP * abs(span) ** PLASTICITY_CURVE_POWER, span)
    return int(round(max(min(value, HAMMER_EXPECT_TOP), -HAMMER_EXPECT_TOP)))


def hammer_range(radius: int, plasticity: int) -> tuple[int, int]:
    """这一锤每项属性的实际变化范围 = 半径 +/- 塑性期望。

    例：塑性 60、半径 10 → 期望 +1 → 范围 -9 ~ +11（宽度不变，整体平移）。
    """
    bonus = hammer_expect(plasticity)
    return (-radius + bonus, radius + bonus)


def recovery_ready(session: Session) -> bool:
    """现在能不能回火：距上次回火砸够了 RECOVERY_INTERVAL 锤（次数不限，均值会越回越低）。"""
    return session.hammers - session.last_recovery_hammer >= RECOVERY_INTERVAL


def recovery_mean(recoveries: int) -> int:
    """这次回火的正态均值：**固定 55**，回多少次都一样。

    参数只为了和面板/旧调用保持兼容，不再参与计算。
    """
    return RECOVERY_MEAN


def hammer_radius(hammers_done: int) -> int:
    """下一锤的波动半径：第 1 锤 ±10，每过一锤 +1，第 6 锤起固定 ±15。"""
    return min(HAMMER_START + HAMMER_GROWTH * hammers_done, HAMMER_MAX_RADIUS)


def effective_score(score: int) -> float:
    """算性能系数时用的"折算分"：300 以内原样，超出部分按 OVERFLOW_RATE 打折。"""
    score = max(int(score), 0)
    base = 300
    if score <= base:
        return float(score)
    return base + (score - base) * PERFORMANCE_OVERFLOW_RATE


def performance(score: int) -> float:
    """测试性能系数 T：300 分时等于 PERFORMANCE_TOP，超过了也会涨，但涨得慢很多。"""
    return (PERFORMANCE_TOP
            * (math.exp(effective_score(score) / PERFORMANCE_DIVISOR) - 1.0)
            / PERFORMANCE_NORM)


def wear_value(attrs: list[int] | tuple[int, ...]) -> float:
    """按三项属性的**占比**算磨损值（0 ~ 0.80）。

    每项先化成占比 = 属性 ÷ 三项之和，再取「最大占比 - 最小占比」作为差异度：
    三项越平均，占比越接近 1/3，差异度越接近 0，刀越新；不按绝对差值算，
    所以整体把属性砸高不会让磨损变差，只有「砸得不匀」才会。
    差异度经正态分布 CDF 映射到磨损值：差异度 = WEAR_CENTER 时正好落在 0.40（中位）。
    """
    values = [int(a) for a in attrs]
    total = sum(values)
    if total <= 0:
        return WEAR_MAX
    shares = [value / total for value in values]
    spread = max(shares) - min(shares)
    z = (spread - WEAR_CENTER) / WEAR_WIDTH
    cdf = 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))
    return round(min(max(WEAR_MAX * cdf, 0.0), WEAR_MAX), 3)


def wear_grade(wear: float) -> tuple[str, float]:
    """磨损值 → (磨损名称, 价值倍率)。"""
    for name, limit, multiplier in WEAR_GRADES:
        if wear <= limit:
            return name, multiplier
    name, _, multiplier = WEAR_GRADES[-1]
    return name, multiplier


def value_of(material: Material, knife: str, pattern: str, score: int,
             wear_multiplier: float = 1.0) -> int:
    """总价值 = 四舍五入(刀型基础价值 × 图案倍率 × 性能系数 × 材料系数 × 磨损倍率)。

    材料系数（``Material.payout``）是 2026-11-19 加的一层：测试改成正态出分后，
    四种材料按原价算出来的期望并不相等，用这个系数把它们拉回同一个收益水平。

    这里不用内置 ``round``：它是「四舍六入五成双」，和文档说的四舍五入不一样。
    """
    base = KNIFE_BASE.get(knife, 0)
    multiplier = PATTERN_MULTIPLIER.get(pattern, 0.0)
    value = (base * multiplier * performance(score)
             * material.payout * wear_multiplier)
    return int(math.floor(value + 0.5))


# --------------------------------------------------------------------------
# 一局的状态
# --------------------------------------------------------------------------


@dataclass
class Session:
    forge_id: str
    group: str
    user: str
    name: str
    stage: str = STAGE_PICK
    material: Material | None = None
    knife: str = ""
    attrs: list[int] = field(default_factory=list)
    hammers: int = 0
    quench: str = ""
    pattern: str = ""
    # 当前有效面板的序号：每发一次面板 +1，旧面板的按钮点过来就对不上了。
    seq: int = 0
    # 磨损度：测试时才算，0~0.80，越新越值钱
    wear: float = 0.0
    wear_grade: str = ""
    # 塑性：0~100，决定用力砸的期望（50 为中性）
    plasticity: int = 100
    recoveries: int = 0          # 已经回火几次（上限递减看 RECOVERY_CAPS）
    last_recovery_hammer: int = 0  # 上次回火时的砸锤数，用来算冷却
    # 上一锤三项属性各自实际变了几分（撞到 0/100 时按实际变化记），面板上要写出来。
    last_delta: tuple[int, int, int] | None = None
    started_at: float = 0.0


# --------------------------------------------------------------------------
# 面板与文案
# --------------------------------------------------------------------------


def _shards_text(amount: int) -> str:
    return f"{int(amount):,}"


def pick_panel(session: Session, shards: int) -> dict:
    """选材面板：四种材料 + 价格 + 初始属性。"""
    lines = [
        "## 锻造 · 选材",
        f"挑一块料，买定离手，**刀型随机**。你手里有 {_shards_text(shards)} 银币。",
    ]
    for material in MATERIALS.values():
        lines.append(
            f"**{material.name}** — {material.price} 银币\n"
            f"强度 {material.strength} · 硬度 {material.hardness} · "
            f"韧性 {material.toughness} · 塑性 {material.plasticity[0]}~{material.plasticity[1]}"
        )
    lines.append("越贵的料越容易出好刀，初始属性也越高。")
    # 按钮只写材料名（价格在正文里列着，按钮塞数字会太长、被客户端截成「强化…」）。
    # 四块料排**两行两列**：一行四个的话每个按钮太窄，长了就被截。
    buttons = [(material.name, panel_data(session, ACTION_MATERIAL, material.name))
               for material in MATERIALS.values()]
    rows = [buttons[index:index + 2] for index in range(0, len(buttons), 2)]
    return {"text": "\n".join(lines), "rows": rows}


def _attrs_line(session: Session, show_delta: bool = True) -> str:
    """三项属性；``show_delta`` 时带上这一锤的增减（+2 / -3 / +0）。"""
    parts: list[str] = []
    for index, name in enumerate(ATTR_NAMES):
        value = session.attrs[index]
        if show_delta and session.last_delta is not None:
            parts.append(f"{name} {value}（{session.last_delta[index]:+d}）")
        else:
            parts.append(f"{name} {value}")
    return " · ".join(parts)


def _recovery_line(session: Session) -> str:
    """面板上那行回火状态。"""
    mean = recovery_mean(session.recoveries)
    gap = session.hammers - session.last_recovery_hammer
    if gap < RECOVERY_INTERVAL:
        return f"回火：再砸 {RECOVERY_INTERVAL - gap} 锤可用（均值 {mean}）"
    return f"回火：可以用了（均值 {mean}）"


def forge_panel(session: Session, rng=random) -> dict:
    """锻造面板：看属性（含这一锤的增减）、下一锤的波动范围、继续砸 / 结束锻造。"""
    radius = hammer_radius(session.hammers)
    expect = hammer_expect(session.plasticity)
    low, high = hammer_range(radius, session.plasticity)
    if session.hammers == 0:
        flavor = rng.choice(FORGE_FLAVOR_OPEN)
    elif min(session.attrs) <= DANGER_THRESHOLD:
        flavor = rng.choice(FORGE_FLAVOR_DANGER)
    else:
        flavor = rng.choice(FORGE_FLAVOR)
    lines = [
        "## 锻造 · 锻造",
        f"{session.material.name} · **{session.knife}**\n"
        f"{_attrs_line(session)}\n"
        f"塑性 {session.plasticity} · 每锤期望 {expect:+d}\n"
        f"已用力砸 {session.hammers} 次 · 下一锤 {low:+d} ~ {high:+d}",
        _recovery_line(session),
    ]
    rows = [
        [("用力砸", panel_data(session, ACTION_HAMMER))],
        [("结束锻造", panel_data(session, ACTION_FINISH))],
    ]
    if recovery_ready(session):
        rows.append([("回火", panel_data(session, ACTION_RECOVER))])
    return {"text": "\n".join(lines) + "\n\n" + flavor, "rows": rows}


def quench_panel(session: Session) -> dict:
    """淬火面板：水淬 / 油淬 二选一。"""
    lines = [
        "## 锻造 · 淬火",
        f"{session.material.name} · **{session.knife}**\n"
        f"{_attrs_line(session, show_delta=False)}\n"
        f"用力砸了 {session.hammers} 次",
        "**水淬** —— 赌上限。冷水一浇，图案大起大落："
        "最次的货最容易出在这儿，蓝宝石、红宝石也只有这儿敢想。\n"
        "**油淬** —— 求稳。油里慢慢降温，图案多半落在中档，"
        "惊喜不多，但也基本不会翻车。",
    ]
    rows = [[
        ("水淬", panel_data(session, ACTION_WATER)),
        ("油淬", panel_data(session, ACTION_OIL)),
    ]]
    return {"text": "\n".join(lines), "rows": rows}


def busy_text(session: Session) -> str:
    """已有未完成的一局时，拒绝再开新局。"""
    stage = session.stage
    if session.material is None:
        detail = "还在选材"
    else:
        detail = f"{session.material.name} · {session.knife}，{stage}阶段"
    return (
        f"你手上还有一把没做完（{detail}），先把这一局走完再来开新的。"
        "面板找不到了就翻一下上面的消息。"
    )


def _zeroed_names(attrs: list[int] | tuple[int, ...]) -> list[str]:
    """哪几项属性见底了（<= 0）。"""
    return [ATTR_NAMES[index] for index, value in enumerate(attrs)
            if int(value) <= ATTR_FLOOR]


def failure_text(session: Session) -> str:
    """属性见底的结局：这一炉报废，材料钱不退、没有收益。"""
    dead = "、".join(_zeroed_names(session.attrs)) or "属性"
    attrs = " · ".join(
        f"{ATTR_NAMES[index]} {max(int(value), 0)}"
        for index, value in enumerate(session.attrs)
    )
    return (
        f"锻造失败 —— {dead}被砸到了 0，这一炉直接报废。\n"
        f"{session.material.name} · {session.knife}，砸了 {session.hammers} 锤\n"
        f"{attrs}\n"
        "材料钱不退，这一炉没有任何收益。发「锻造」重新开炉吧。"
    )


def result_text(session: Session, scores: list[int], score: int, value: int,
                left: int, rank: int | None, wear_multiplier: float = 1.0) -> str:
    """测试结果：磨损 + 每项得分 + 总分 + 最终价值（已经打进余额）。"""
    lines = [
        f"锻造完成 —— {session.material.name} · {session.knife} · "
        f"{session.pattern}（{session.wear_grade}）",
    ]
    for index, name in enumerate(ATTR_NAMES):
        lines.append(f"{name} {session.attrs[index]} → {scores[index]} 分")
    lines.append(f"测试得分 {score}（基准满分 {TEST_MAX_SCORE}）")
    lines.append(
        f"磨损 {session.wear:.3f}（{session.wear_grade}）· 价值倍率 ×{wear_multiplier:g}"
    )
    lines.append(f"总价值 {value} 银币，已存进余额（现在 {left}）。")
    if rank:
        lines.append(f"这一把进了锻造排行榜第 {rank} 名。")
    return "\n".join(lines)


def leaderboard_text(records: list[dict]) -> str:
    """「锻造排行榜」的文字兜底版（图片渲染不出来时用）。"""
    from .forge_rank import ordinal

    lines = ["锻造排行榜（按总价值排）"]
    if not records:
        lines.append("还没有人收工，砸完一局来占个位置吧。")
        return "\n".join(lines)
    for index, record in enumerate(records, start=1):
        bits = [f"{int(record.get('value') or 0)} 银币"]
        bits.append(str(record.get("name") or "群友"))
        knife = str(record.get("knife") or record.get("sword") or "").strip()
        if knife:
            bits.append(knife)
        pattern = str(record.get("pattern") or "").strip()
        if pattern:
            bits.append(pattern)
        if record.get("score") is not None:
            bits.append(f"{int(record['score'])} 分")
        time_text = str(record.get("time") or "").strip()
        if time_text:
            bits.append(time_text)
        lines.append(f"{ordinal(index)} " + " · ".join(bits))
    return "\n".join(lines)


# --------------------------------------------------------------------------
# 面板按钮的 data：锻造 <id> <seq> <动作> [参数]
# --------------------------------------------------------------------------


def panel_data(session: Session, action: str, argument: str = "") -> str:
    """拼一个按钮的 data（和发面板时的 seq 绑定，点旧面板就会对不上）。"""
    parts = [PANEL_PREFIX, session.forge_id, str(session.seq), action]
    if argument:
        parts.append(argument)
    return " ".join(parts)


def parse_panel_data(text: str) -> tuple[str, int, str, str] | None:
    """解析按钮 data；不是面板数据就返回 None。"""
    parts = (text or "").strip().split()
    if len(parts) < 4 or parts[0] != PANEL_PREFIX:
        return None
    try:
        seq = int(parts[2])
    except (TypeError, ValueError):
        return None
    return parts[1], seq, parts[3], (parts[4] if len(parts) > 4 else "")


# --------------------------------------------------------------------------
# 主逻辑
# --------------------------------------------------------------------------


class NewForge:
    """新锻造系统的状态机：一局一个人，进度只在内存里。"""

    def __init__(self, cards, rank, on_forged=None) -> None:
        self.cards = cards
        self.rank = rank
        # 收工回调：把这一把交给别的玩法（宠物冒险的剑库）。
        # 签名 on_forged(session, score, value) -> dict|None；抛异常只记日志，
        # 不影响结算 —— 剑库挂了也不能让锻造的钱发不出去。
        self.on_forged = on_forged
        self.rng = random
        self._sessions: dict[tuple[str, str], Session] = {}

    # ---- 查询 ----

    @staticmethod
    def _key(group: str, user: str) -> tuple[str, str]:
        return (str(group or ""), str(user or ""))

    def active(self, group: str, user: str) -> Session | None:
        return self._sessions.get(self._key(group, user))

    def clear(self) -> None:
        """丢掉所有局（自检用）。"""
        self._sessions.clear()

    # ---- 内部 ----

    def _new_id(self) -> str:
        """生成一个没有在用的锻造 id。

        随机源坏掉（自检里会塞死值）或者撞上活着的局时不能死循环，
        试几次不成退回时间戳。
        """
        for _ in range(50):
            value = "".join(
                self.rng.choice(FORGE_ID_ALPHABET) for _ in range(FORGE_ID_LENGTH)
            )
            if all(session.forge_id != value for session in self._sessions.values()):
                return value
        return f"{int(time.time() * 1000) % 10 ** 8:08x}"

    def _panel(self, session: Session) -> dict:
        """按当前阶段出面板；每出一次 seq +1，之前的面板随即作废。"""
        session.seq += 1
        if session.stage == STAGE_PICK:
            return pick_panel(session, self.cards.shards_of(session.user))
        if session.stage == STAGE_FORGE:
            return forge_panel(session, self.rng)
        return quench_panel(session)

    def _reply(self, text: str) -> dict:
        return {"ok": False, "panel": None, "reply": text}

    # ---- 对外 ----

    def start(self, group: str, user: str, name: str = "") -> dict:
        """发「锻造」：开一局，回到选材面板。"""
        key = self._key(group, user)
        session = self._sessions.get(key)
        if session is not None:
            if time.time() - session.started_at < SESSION_TTL:
                return self._reply(busy_text(session))
            # 上一局放太久了，当人跑了，直接开新的
            self._sessions.pop(key, None)
        session = Session(
            forge_id=self._new_id(),
            group=key[0],
            user=key[1],
            name=str(name or "").strip() or "群友",
            started_at=time.time(),
        )
        self._sessions[key] = session
        return {"ok": True, "panel": self._panel(session), "reply": ""}

    def act(self, group: str, user: str, forge_id: str, seq: int,
            action: str, argument: str = "") -> dict:
        """处理一次面板点击：锻造 id 和面板序号都对上才执行。"""
        session = self.active(group, user)
        if session is None:
            return self._reply(NO_SESSION_REPLY)
        if session.forge_id != forge_id or session.seq != seq:
            return self._reply(STALE_REPLY)
        handler = {
            (STAGE_PICK, ACTION_MATERIAL): self._buy,
            (STAGE_FORGE, ACTION_HAMMER): self._hammer,
            (STAGE_FORGE, ACTION_RECOVER): self._recover,
            (STAGE_FORGE, ACTION_FINISH): self._to_quench,
            (STAGE_QUENCH, ACTION_WATER): self._quench,
            (STAGE_QUENCH, ACTION_OIL): self._quench,
        }.get((session.stage, action))
        if handler is None:
            return self._reply(STALE_REPLY)
        return handler(session, action, argument)

    def _buy(self, session: Session, action: str, argument: str) -> dict:
        material = MATERIALS.get(argument)
        if material is None or session.stage != STAGE_PICK:
            return self._reply(STALE_REPLY)
        shards = self.cards.shards_of(session.user)
        if shards < material.price:
            # 什么都没发生：面板不重发，seq 也不动，还能接着选便宜点的料
            return self._reply(
                f"银币不够：{material.name} 要 {material.price}，你只有 {shards}。"
                "换一块便宜点的料吧。"
            )
        self.cards.spend_shards(session.user, material.price)
        session.material = material
        session.knife = roll_knife(material, self.rng)
        session.attrs = list(material.attrs)
        session.plasticity = self.rng.randint(*material.plasticity)
        session.stage = STAGE_FORGE
        session.hammers = 0
        return {"ok": True, "panel": self._panel(session), "reply": ""}

    def _hammer(self, session: Session, action: str, argument: str) -> dict:
        radius = hammer_radius(session.hammers)
        low, high = hammer_range(radius, session.plasticity)
        attrs: list[int] = []
        deltas: list[int] = []
        for attr in session.attrs:
            before = int(attr)
            after = before + self.rng.randint(low, high)
            attrs.append(after)
            # 撞到 0 就直接报废，所以这里按**实际**变化记（面板上写 +5 却没动会很怪）
            deltas.append(after - before)
        session.attrs = attrs
        session.last_delta = (deltas[0], deltas[1], deltas[2])
        session.hammers += 1
        # 每砸一锤塑性掉 3，掉到 0 就固定 -15 期望
        session.plasticity = max(session.plasticity - PLASTICITY_DECAY, 0)
        if min(attrs) <= ATTR_FLOOR:
            return self._ruin(session)
        return {"ok": True, "panel": self._panel(session), "reply": ""}

    def _ruin(self, session: Session) -> dict:
        """任一属性见底：这一炉当场报废，材料钱不退、也没有任何收益。"""
        text = failure_text(session)
        log(
            f"[锻造] {session.name} {session.material.name}/{session.knife} 砸了 "
            f"{session.hammers} 锤，{'、'.join(_zeroed_names(session.attrs))}归零，报废"
        )
        self._sessions.pop(self._key(session.group, session.user), None)
        return {"ok": False, "panel": None, "reply": text}

    def _recover(self, session: Session, action: str, argument: str) -> dict:
        """回火：重摇塑性。要砸够 5 锤才能用，且每次上限递减。"""
        gap = session.hammers - session.last_recovery_hammer
        if gap < RECOVERY_INTERVAL:
            return self._reply(
                f"回火还差 {RECOVERY_INTERVAL - gap} 锤 —— "
                f"至少砸够 {RECOVERY_INTERVAL} 次才能回火。"
            )
        mean = recovery_mean(session.recoveries)
        roll = self.rng.gauss(mean, RECOVERY_SIGMA)
        # 只保证落在 0~100 这个属性范围内，不再按递减上限截断
        session.plasticity = int(min(max(round(roll), 0), PLASTICITY_MAX))
        session.recoveries += 1
        session.last_recovery_hammer = session.hammers
        # 回火不动属性，面板不该还挂着上一锤的 +/-
        session.last_delta = None
        log(
            f"[锻造] {session.name} 第 {session.recoveries} 次回火，"
            f"均值 {mean} → 塑性 {session.plasticity}"
        )
        return {"ok": True, "panel": self._panel(session), "reply": ""}

    def _to_quench(self, session: Session, action: str, argument: str) -> dict:
        session.stage = STAGE_QUENCH
        return {"ok": True, "panel": self._panel(session), "reply": ""}

    def _quench(self, session: Session, action: str, argument: str) -> dict:
        # 水淬 / 油淬的区分在动作码上（「水」「油」），不在参数里
        quench = QUENCH_ACTION.get(action)
        if quench is None or session.stage != STAGE_QUENCH:
            return self._reply(STALE_REPLY)
        session.quench = quench
        session.pattern = roll_pattern(quench, self.rng)
        scores = run_test(session.attrs, self.rng)
        score = sum(scores)
        # 磨损度：测得三项属性越均匀越新，磨损越轻、价值倍率越高
        session.wear = wear_value(session.attrs)
        session.wear_grade, wear_multiplier = wear_grade(session.wear)
        value = value_of(session.material, session.knife, session.pattern, score,
                         wear_multiplier)
        left = int(self.cards.grant_shards(session.user, value))
        rank = self.rank.record(
            value, session.user, session.name,
            knife=session.knife, pattern=session.pattern, score=score,
        )
        # 这把剑另外登记一份到剑库（宠物冒险用）；银币照旧全额进余额
        kept = None
        if self.on_forged is not None:
            try:
                kept = self.on_forged(session, score, value)
            except Exception as error:  # noqa: BLE001 - 剑库失败不能拖垮结算
                log(f"[锻造] 剑库登记失败：{error!r}")
        text = result_text(session, scores, score, value, left, rank,
                           wear_multiplier)
        if kept:
            text += ("\n这把剑已经放进剑库了 —— 发「宠物 冒险」就能交给宠物使唤"
                     "（银币照旧全额到账，剑是额外留下的）。")
        log(
            f"[锻造] {session.name} {session.material.name}/{session.knife}"
            f"/{session.pattern}/{quench} 砸{session.hammers}次 分数{score} "
            f"磨损{session.wear}({session.wear_grade}) 价值{value}"
        )
        self._sessions.pop(self._key(session.group, session.user), None)
        return {"ok": True, "panel": None, "reply": text}
