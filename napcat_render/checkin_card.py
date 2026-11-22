"""把一次签到渲染成一张图：今日老婆 + 抽卡结果 + 银币。

布局照着 ``data\\example.jpeg``（群里那张"游戏签到"汇总图）的路子来：背景铺一层
模糊的照片，上面排**几张独立的白色圆角卡片** —— 左卡放图（今日老婆），右卡放信息
（签到资料、抽卡结果、资产），每张卡里再按"标题 + 分隔线 + 内容"排。

为什么用 Pillow 而不是 HTML 截图：本应用的 venv 里本来就有 Pillow（`PIL 12.3.0`），
而 HTML 那套要另起一个浏览器进程 —— 群消息里等它两三秒太亏，渲染失败的概率也大。
排版是固定的卡片网格，Pillow 足够，而且**渲染失败能整齐退回纯文案**
（见 `__init__._render_check_in`），不会让签到本身失败。
"""
from __future__ import annotations

import datetime
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps
from nonebot import logger

from .config import CHECKIN_CARD_DIR
from .daily_luck import luck_advice, luck_flavor
from .forge_rank import TOP_N as FORGE_RANK_TOP_N, ordinal as rank_ordinal

# ------------------------------------------------------------------ 版式尺寸
# 尺寸**由内容算出来**，不是写死的一串坐标：改字号/行高时布局自己跟着走，
# 不会出现"图高写死、内容一多就被切掉"这种事。
#
# 整张图有一个统一缩放 SCALE：显式的尺寸都过一遍 `_s()`，字号在 `_font()` 里统一放大。
# 想整张图更大/更小（群里手机上看着太小之类），只改 IMAGE_WIDTH 和 SCALE 两个数就行，
# 版式比例、留白、字号会一起跟着走。
IMAGE_WIDTH = 2100
SCALE = 1.2


def _s(value: float) -> int:
    """把基准版式里的尺寸换算成实际像素（四舍五入到整数）。"""
    return int(round(value * SCALE))


MARGIN = _s(40)              # 画布四周留白
PAD = _s(24)                 # 卡片内边距
GAP = _s(24)                 # 卡片之间、两栏之间的间距
HEADER_HEIGHT = _s(150)      # 左卡里"头像 + 名字 + 签到信息"那一段
CARD_HEADER_HEIGHT = _s(96)  # 每张小卡里"标题 + 分隔线"那一段（_card_header 画的）
# 老婆图的画框：**形状跟着图片自己的宽高比走**（见 ``_wife_image_box``）——
# 宽图画框就是扁的、竖图画框就是高的，图既不裁也不缩在中间留一圈白边。
# 只留上下限兜底：竖图最高这么高（再高整张图会被撑爆），超宽图最低这么高
# （16:9 以上的横图按宽度撑满会瘦成一条线，抬一点才好看）。
WIFE_IMAGE_MAX_HEIGHT = 1200
WIFE_IMAGE_MIN_HEIGHT = 420
# 画框的宽度下限（占卡片内宽的比例）：再瘦的图也别缩成一根细线。
WIFE_IMAGE_MIN_WIDTH_RATIO = 0.6
# 老婆名下面那句说明（"这是某某今天的份，收好。"）。不要它就把 WIFE_NOTE 置成 False，
# 卡片会跟着矮一行。
WIFE_NOTE = True
# 右栏单独一张"提示卡"的文案（`{command}` 会换成命令名）。不想显示就把 WIFE_HINT 置成空串。
WIFE_HINT = "输入“{command}”查看所有支持的功能喵"
WIFE_NAME_HEIGHT = _s(70)    # 图片下面那行老婆名字（没名字时这一行整段不占位）
WIFE_NOTE_LINE = _s(40)      # 再下面那句说明每行占的高度
WIFE_NOTE_LINES = 1          # 说明只留一行（写短点，多一行会顶到卡片底边）
FOOTER_HEIGHT = _s(44)       # 卡片底下那条装饰性的小字
# 两栏：左 = 用户信息 + 老婆图；右 = 抽卡结果 + 银币 + 今日运势。
# 左栏给到 1000px 是因为**横图只能靠画框宽度变大**（它按宽度撑满，画框多宽图就多大）；
# 右栏 760px 刚好够放抽卡卡名和"宜/忌"那句，再窄就要开始省略号了。
LEFT_COLUMN_WIDTH = 1000
RIGHT_COLUMN_WIDTH = IMAGE_WIDTH - MARGIN * 2 - GAP - LEFT_COLUMN_WIDTH
# 运势卡：图最少留这么高，下面的等级名 + 一句配文固定占这些，再加宜/忌两行。
# 这一栏要给得比另外两张卡宽松 —— 运势图是竖图，得靠高度才撑得起来。
LUCK_IMAGE_MIN_HEIGHT = 480
LUCK_CARD_TEXT_HEIGHT = _s(96)
LUCK_ADVICE_HEIGHT = _s(88)
# 银币卡：标题 + 内容（大数字 + "本次 +N" + 说明）。这就是它的最小高度。
ASSETS_MIN_HEIGHT = _s(300)
ASSETS_CONTENT_HEIGHT = _s(214)

# 抽卡结果**只写卡名**（不放品质标签和"新卡/重复"），一行矮一些；随卡片宽度自适应字号。
LIST_ROW_HEIGHT = _s(56)
LIST_ROW_GAP = _s(10)
# 抽卡结果排两列，两列之间的间距
LIST_COLUMN_GAP = _s(14)
# 超过这么多张就不再一行行排了，多发几张就折成"还有 N 张"。
LIST_ROW_LIMIT = 8
# 抽卡卡底部的收尾话（卡片会被拉高，底下空着不好看）
DRAWS_CLOSING = "明天还有 5 次，记得来。"

BACKGROUND_TOP = (247, 243, 248)
BACKGROUND_BOTTOM = (238, 238, 246)
PANEL_FILL = (255, 255, 255)
PANEL_EDGE = (229, 224, 234)
# 卡片 / 圆角条这些"界面块"的**不透明度**：1 = 完全盖住底下那层背景，
# 越往下调底下的背景（模糊照片 / 淡紫渐变）透出来的越多，卡片像一层磨砂玻璃。
# 想整张图再透一点/再实一点，只改这一个数就行（0.7 已经挺透了，别低于 0.6，
# 再低正文跟背景的对比度就不够了）。
PANEL_ALPHA = 0.65
# 背景照片上压的那层白纱：1 = 全白（等于没有照片），越小照片的颜色越足。
BACKGROUND_WASH = 0.10
TEXT_MAIN = (52, 44, 60)
TEXT_SUB = (140, 132, 150)
TEXT_FAINT = (176, 168, 186)
ACCENT = (211, 68, 122)
ACCENT_SOFT = (253, 236, 244)
DIVIDER = (240, 235, 243)
# 老婆图"完整缩进画框"之后，缩不到的地方铺这个色（跟卡片底一个色系，像照片留白）。
WIFE_IMAGE_BACKDROP = (247, 244, 249)

# 抽卡结果的样子：**浅底圆角条**（不上色），里面是卡名 + 品质徽章 + 「新卡 / 重复→银币」。
# 品质颜色只用在那个小徽章上（用户给的样例就是这样）：稀有绿、史诗紫、神话橙、传奇玫红。
NEUTRAL_ROW_FILL = (250, 247, 251)
NEUTRAL_ROW_EDGE = (240, 234, 242)
# 品质 → (徽章上的字, 徽章底色)
RARITY_BADGE: dict[str, tuple[str, tuple[int, int, int]]] = {
    "rare": ("稀有", (106, 140, 194)),
    "epic": ("史诗", (150, 100, 214)),
    "myth": ("神话", (233, 146, 47)),
    "legend": ("传奇", (214, 62, 120)),
    "origin": ("始源", (198, 74, 42)),
}
RARITY_BADGE_FALLBACK = ("卡牌", (150, 142, 158))

# 字体：Windows 自带的中文字体。找不到就往下退，最后退回 Pillow 的位图字体
# （那样中文会是方块，但至少不会因为缺字体把整个签到搞崩）。
_FONT_CANDIDATES = (
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\Deng.ttf",
)
_FONT_BOLD_CANDIDATES = (
    r"C:\Windows\Fonts\msyhbd.ttc",
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
)
_font_cache: dict[tuple[bool, int], ImageFont.ImageFont] = {}


def _first_existing(candidates: tuple[str, ...]) -> str | None:
    for path in candidates:
        if Path(path).is_file():
            return path
    return None


def _default_font(size: int) -> ImageFont.ImageFont:
    """最后一道兜底：Pillow 自带的位图字体（中文会是方块，但不会抛异常）。"""
    try:
        return ImageFont.load_default(size)
    except TypeError:  # 老 Pillow 的 load_default 不收 size
        return ImageFont.load_default()


def _font(size: int, *, bold: bool = False) -> ImageFont.ImageFont:
    """取一个字号的字体，带缓存（同一个尺寸反复 load 很浪费）。

    字号统一过一遍 ``SCALE``：版式放大时文字跟着放大，比例才不会走样。
    """
    size = max(1, _s(size))
    key = (bold, size)
    cached = _font_cache.get(key)
    if cached is not None:
        return cached
    path = _first_existing(_FONT_BOLD_CANDIDATES if bold else _FONT_CANDIDATES)
    try:
        font: ImageFont.ImageFont = (
            ImageFont.truetype(path, size) if path else _default_font(size)
        )
    except OSError as error:  # 字体文件坏了/读不动，退回位图字体
        logger.warning(f"[签到图] 字体 {path} 加载失败，改用默认字体：{error}")
        font = _default_font(size)
    _font_cache[key] = font
    return font


def _text_width(draw: ImageDraw.ImageDraw, text: str, font) -> int:
    return int(draw.textlength(text, font=font))


def _ellipsize(draw: ImageDraw.ImageDraw, text: str, font, limit: int) -> str:
    """把过长的卡名截成 ``前面…``，免得压到右边的标签上。"""
    if _text_width(draw, text, font) <= limit:
        return text
    trimmed = text
    while trimmed and _text_width(draw, trimmed + "…", font) > limit:
        trimmed = trimmed[:-1]
    return (trimmed + "…") if trimmed else "…"


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, limit: int) -> list[str]:
    """按像素宽度折行：中文没有空格，只能逐字量。"""
    lines: list[str] = []
    current = ""
    for character in text:
        if character == "\n":
            lines.append(current)
            current = ""
            continue
        if _text_width(draw, current + character, font) > limit and current:
            lines.append(current)
            current = character
        else:
            current += character
    lines.append(current)
    return lines


# ------------------------------------------------------------------ 基础绘制
def _linear_gradient(size: tuple[int, int], top, bottom) -> Image.Image:
    """竖直线性渐变。逐行画 1500 条线就够了，不用 numpy。"""
    width, height = size
    strip = Image.new("RGB", (1, height))
    pixels = strip.load()
    for y in range(height):
        ratio = y / max(height - 1, 1)
        pixels[0, y] = tuple(
            int(top[index] + (bottom[index] - top[index]) * ratio) for index in range(3)
        )
    return strip.resize((width, height))


def _rounded_mask(size: tuple[int, int], radius: int) -> Image.Image:
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, size[0] - 1, size[1] - 1), radius=max(radius, 0), fill=255
    )
    return mask


def _paint_panel(
    canvas: Image.Image,
    box: tuple[int, int, int, int],
    fill: tuple[int, int, int],
    radius: int,
    alpha: float | None = None,
) -> None:
    """在 ``box`` 处按圆角铺一层**半透明**色块（卡片、圆角条都走这里）。

    ``alpha`` 不给就用全局的 ``PANEL_ALPHA``（这里**运行时**才读，
    改了常量立刻生效，不需要重启）。

    ``alpha=1`` 就是原来的不透明卡片；小于 1 时底下的背景会透出来。
    Pillow 的 ``ImageDraw`` 在 RGB 图上直接吃掉 RGBA 的 ``fill``（不会混合），
    所以只能自己混：把这块底下的像素取出来跟纯色按 ``alpha`` 混好，
    再用圆角遮罩贴回去 —— 圆角外面一点都不动。
    """
    left, top, right, bottom = (int(value) for value in box)
    width, height = right - left, bottom - top
    if width <= 0 or height <= 0:
        return
    if alpha is None:
        alpha = PANEL_ALPHA
    if alpha >= 1.0:
        layer = Image.new("RGB", (width, height), fill)
    else:
        base = canvas.crop((left, top, right, bottom))
        layer = Image.blend(base, Image.new("RGB", (width, height), fill), alpha)
    canvas.paste(layer, (left, top), _rounded_mask((width, height), radius))


def _background_canvas(width: int, height: int) -> Image.Image:
    """签到图/库存图共用的底：淡紫渐变，够朴素、不抢前景。"""
    return _linear_gradient((width, height), BACKGROUND_TOP, BACKGROUND_BOTTOM)


def _background_source(wife_path: Path | None) -> Image.Image | None:
    """背景底图：拿今日老婆那张图放大模糊、再压一层白纱。

    取不到图就返回 ``None``，调用方退回纯渐变背景。这张图**只读**，不碰随机池。
    """
    if wife_path is None:
        return None
    try:
        with Image.open(wife_path) as opened:
            photo = ImageOps.exif_transpose(opened).convert("RGB")
    except (OSError, ValueError) as error:
        logger.warning(f"[签到图] 背景图读取失败 {wife_path}：{error}")
        return None
    # 放大到至少盖住画布，模糊之后边缘才不会露白。
    photo = ImageOps.fit(photo, (IMAGE_WIDTH, IMAGE_WIDTH * 2),
                         method=Image.Resampling.LANCZOS)
    photo = photo.filter(ImageFilter.GaussianBlur(38))
    wash = Image.new("RGB", photo.size, (255, 255, 255))
    # 白纱压得越狠背景越淡；卡片半透明（PANEL_ALPHA）时能透出来的也就越少 ——
    # 这两个数是一对：想让卡片更"玻璃"，光调卡片没用，背景也得留住一点颜色。
    return Image.blend(photo, wash, BACKGROUND_WASH)


def _image_ratio(path: Path | None) -> float | None:
    """老婆图的**宽高比**（宽 ÷ 高）；没图 / 读不出来返回 ``None``。

    画框的形状就按这个数来定（见 ``_wife_image_box``）。只读个尺寸，不动图本身。
    """
    if path is None:
        return None
    try:
        with Image.open(path) as opened:
            width, height = opened.size
    except (OSError, ValueError):
        return None
    if width <= 0 or height <= 0:
        return None
    return width / height


def _wife_image_box(
    width: int,
    *,
    ratio: float | None = None,
    missing: bool = False,
    max_height: int = WIFE_IMAGE_MAX_HEIGHT,
) -> tuple[int, int]:
    """老婆图画框的尺寸：**形状跟着图片自己的宽高比走**，图正好撑满、不留白边。

    ``ratio`` 是图片的宽 ÷ 高（见 ``_image_ratio``）；``width`` 是卡片的内宽。
    先按"宽度撑满"算高度，太高就压到 ``max_height`` 并**同比例收窄宽度**（画框变窄，
    画的时候在卡片里居中摆）；太矮就抬到 ``WIFE_IMAGE_MIN_HEIGHT``。
    于是宽图画框是扁的、竖图画框是高的 —— 不裁图，也不会缩在中间留一大圈底色。
    没图 / 读不出比例时退回 4:5 这种常见的竖图比例，观感跟老版差不多。
    """
    if missing:
        return (width, _s(300))
    if ratio is None or ratio <= 0:
        ratio = 0.8
    box_width = width
    box_height = int(round(box_width / ratio))
    if box_height > max_height:
        box_height = max_height
        box_width = int(round(box_height * ratio))
    if box_height < WIFE_IMAGE_MIN_HEIGHT:
        box_height = WIFE_IMAGE_MIN_HEIGHT
        box_width = int(round(box_height * ratio))
    # 特别瘦长的图（比如 1080×2560）按高度上限一压就剩一条细线 ——
    # 给宽度留个下限，宁可画框再高一点，也别让老婆缩成一根棍。
    floor_width = int(width * WIFE_IMAGE_MIN_WIDTH_RATIO)
    if box_width < floor_width:
        box_width = min(floor_width, width)
        box_height = int(round(box_width / ratio))
    return (box_width, box_height)


def _load_picture(
    path: Path | None, box: tuple[int, int], *, crop: bool = True
) -> Image.Image | None:
    """把图读出来并按 ``box`` 缩放；读不动就返回 ``None``。

    ``crop=True``：居中裁切成 ``box`` 的精确尺寸（背景底图用这套，铺满不留边）；
    ``crop=False``：整张图**完整**缩进 ``box``（不裁），多出来的地方由调用方铺底色 ——
    老婆图和运势图走这条，图再长也不会被切掉一截。

    这里用 ``ImageOps.contain`` 而不是 ``Image.thumbnail``：后者在"图比 box 还小"时
    会**直接原样返回**（它只往下缩、不往上放），结果图画框给得再大也白给。
    GIF 取第一帧（Pillow 的 ``paste`` 不支持动图），带 EXIF 旋转的先摆正。
    """
    if path is None:
        return None
    try:
        with Image.open(path) as opened:
            frame = ImageOps.exif_transpose(opened).convert("RGB")
            if crop:
                return ImageOps.fit(frame, box, method=Image.Resampling.LANCZOS)
            return ImageOps.contain(frame, box, method=Image.Resampling.LANCZOS)
    except (OSError, ValueError) as error:
        logger.warning(f"[签到图] 图片读取失败 {path}：{error}")
        return None


def _card(
    canvas: Image.Image,
    box: tuple[int, int, int, int],
    *,
    fill=PANEL_FILL,
    outline=PANEL_EDGE,
    radius: int = 18,
    alpha: float | None = None,
) -> None:
    """圆角卡片：``fill`` 也画进圆角遮罩里，卡片角上不会露出背景色。

    ``alpha`` 是卡片底的不透明度（见 ``PANEL_ALPHA``）：小于 1 时底下那层
    模糊照片/渐变会透出来，卡片变"磨砂玻璃"；**描边仍是实色**，块与块的界限清楚。
    """
    _paint_panel(canvas, box, fill, _s(radius), alpha)
    width = box[2] - box[0]
    height = box[3] - box[1]
    ImageDraw.Draw(canvas).rounded_rectangle(
        (box[0], box[1], box[2] - 1, box[3] - 1), radius=_s(radius),
        outline=outline, width=2,
    )


def _card_header(
    draw: ImageDraw.ImageDraw,
    left: int,
    top: int,
    right: int,
    title: str,
    *,
    note: str = "",
    color=TEXT_MAIN,
) -> int:
    """小卡片的标题栏：左标题、右小字、下面一条分隔线。返回内容区的起始 y。"""
    title_font = _font(30, bold=True)
    draw.text((left + PAD, top + _s(20)), title, font=title_font, fill=color)
    if note:
        draw.text((right - PAD, top + _s(30)), note, font=_font(22), fill=TEXT_FAINT, anchor="ra")
    line_y = top + CARD_HEADER_HEIGHT - 18
    draw.line((left + PAD, line_y, right - PAD, line_y), fill=DIVIDER, width=2)
    return top + CARD_HEADER_HEIGHT


# ------------------------------------------------------------------ 各块内容
def _draw_header(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    *,
    username: str,
    user_id: int,
    today: datetime.date,
    first_check_in: bool,
) -> None:
    """左卡顶部的用户信息：圆头像 + 名字 + 今天的签到情况。"""
    left, top, right = box[0], box[1], box[2]
    size = 96
    avatar_left = left + PAD
    avatar_top = top + (HEADER_HEIGHT - size) // 2
    draw.ellipse(
        (avatar_left, avatar_top, avatar_left + size, avatar_top + size),
        fill=ACCENT_SOFT, outline=(246, 216, 230), width=2,
    )
    initial = (username.strip() or "杂")[0]
    draw.text(
        (avatar_left + size / 2, avatar_top + size / 2 + 2), initial,
        font=_font(44, bold=True), fill=ACCENT, anchor="mm",
    )

    # 群名片可能很长：先给右边那句状态、以及右上角的角标留出位置，剩下的才给名字。
    text_left = avatar_left + size + 22
    status = "签到成功" if first_check_in else "今天已经签过啦"
    status_font = _font(24)
    corner_x = right - PAD - _text_width(draw, "qqchatbot", _font(22))
    name_limit = max(
        corner_x - 20 - _text_width(draw, status, status_font) - 16 - text_left, 120
    )
    name_font = _font(36, bold=True)
    name = _ellipsize(draw, username, name_font, name_limit)
    draw.text((text_left, top + _s(26)), name, font=name_font, fill=TEXT_MAIN)
    draw.text(
        (text_left + _text_width(draw, name, name_font) + _s(16), top + _s(38)), status,
        font=status_font, fill=ACCENT if first_check_in else TEXT_SUB,
    )
    draw.text(
        (text_left, top + _s(80)),
        f"{user_id} · {today.strftime('%Y-%m-%d')}",
        font=_font(22), fill=TEXT_SUB,
    )
    draw.text(
        (right - PAD, top + _s(32)), "qqchatbot", font=_font(22), fill=TEXT_FAINT, anchor="ra"
    )
    draw.text(
        (right - PAD, top + _s(72)), "每日签到卡", font=_font(22), fill=TEXT_FAINT, anchor="ra"
    )


def _draw_wife_card(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    *,
    username: str,
    wife_path: Path | None,
    wife_name: str | None,
    name_height: int,
    image_box: tuple[int, int],
) -> None:
    """左卡：**只有今日老婆的图**（名字有才画，说明可关）。

    这里**没有**小卡片的标题栏 —— "今日的老婆 / 随机池里挑的"那两行去掉了，
    图直接从卡片顶上开始摆，省下来的高度全给图。
    """
    left, top, right, bottom = box
    _card(canvas, box)
    draw = ImageDraw.Draw(canvas)
    # 画框由调用方按**图片自己的宽高比**算好（见 _wife_image_box）：宽图画框是扁的、
    # 竖图画框是高的。图**完整**缩进画框（不裁切），比例对得上所以基本没有留白；
    # 画框比卡片内宽窄时（竖图被高度上限压住）就在卡片里**居中**摆。
    picture = _load_picture(wife_path, image_box, crop=False)
    # 画框比卡片内宽窄时（竖图被高度上限压住）就在卡片里**居中**摆。
    panel_left = left + PAD + (right - left - PAD * 2 - image_box[0]) // 2
    # 画框比卡片矮时（宽图就是这样）整块内容**垂直居中**：上下各留一点，
    # 比"图顶在上边、底下空一大片"好看。
    content_height = image_box[1] + _s(18) + name_height + (
        WIFE_NOTE_LINE * WIFE_NOTE_LINES if WIFE_NOTE else 0
    )
    panel_top = top + PAD + max((bottom - top - PAD * 2 - content_height) // 2, 0)
    if picture is not None:
        panel = Image.new("RGB", image_box, WIFE_IMAGE_BACKDROP)
        panel.paste(
            picture,
            ((image_box[0] - picture.width) // 2, (image_box[1] - picture.height) // 2),
        )
        panel = panel.convert("RGBA")
        panel.putalpha(_rounded_mask(image_box, _s(14)))
        canvas.paste(panel, (panel_left, panel_top), panel)
    else:
        draw.rounded_rectangle(
            (panel_left, panel_top, panel_left + image_box[0], panel_top + image_box[1]),
            radius=_s(14), fill=(246, 242, 248),
        )
        draw.text(
            (panel_left + image_box[0] / 2, panel_top + image_box[1] / 2),
            "老婆文件夹里还没有图片",
            font=_font(26), fill=TEXT_SUB, anchor="mm",
        )

    text_top = panel_top + image_box[1] + _s(18)
    # 老婆**没有名字就什么都不画**（不留一行"无名老婆"）。
    if wife_name:
        name_font = _font(38, bold=True)
        draw.text(
            (left + PAD, text_top),
            _ellipsize(draw, f"「{wife_name}」", name_font, right - left - PAD * 2),
            font=name_font, fill=TEXT_MAIN,
        )
    text_top += name_height
    # 这句说明写短一点，正好一行；不要它就把 WIFE_NOTE 置成 False。
    note = f"这是 {username} 今天的份，收好。"
    note_font = _font(24)
    lines = _wrap(draw, note, note_font, right - left - PAD * 2)[:WIFE_NOTE_LINES]
    for index, line in enumerate(lines):
        draw.text(
            (left + PAD, text_top + index * WIFE_NOTE_LINE), line,
            font=note_font, fill=TEXT_SUB,
        )


def _draw_hint_card(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    *,
    text: str,
) -> None:
    """右栏那张独立的提示卡（跟抽卡结果、银币、今日运势并列）。

    ``draw`` 只是为了跟别的 ``_draw_*_card`` 签名一致，这里自己重画一个。
    """
    del draw
    left, top, right, bottom = box
    _card(canvas, box, fill=(255, 249, 252), outline=(250, 222, 235))
    painter = ImageDraw.Draw(canvas)
    inner_width = right - left - PAD * 2
    font = _font(26, bold=True)
    if _text_width(painter, text, font) > inner_width:
        font = _font(22, bold=True)
    painter.text(
        (left + (right - left) / 2, (top + bottom) / 2), text,
        font=font, fill=ACCENT, anchor="mm",
    )


def _draw_list_metrics(row_width: int) -> tuple[int, int]:
    """抽卡列表的行高和卡名字号 —— **跟着一列的宽度走**。

    布局和绘制都调它，免得两边各算一套：之前就是布局按矮行算高度、绘制按宽栏算出行高，
    结果列表画到卡片外面去了。
    """
    row_height = max(_s(84), min(_s(108), int(row_width * 0.36)))
    size = max(_s(22), min(_s(26), int(row_width * 0.085)))
    return row_height, size


def _draw_draws_card(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    *,
    drawn: list[dict],
    drawn_count: int,
) -> None:
    """右栏上卡：今天自动抽了几次、抽到了什么（每张牌一行：卡名 + 品质徽章 + 新卡/重复）。"""
    left, top, right, bottom = box
    _card(canvas, box)
    draw = ImageDraw.Draw(canvas)
    note = f"共 {drawn_count} 次" if drawn_count else "今天没次数了"
    content_top = _card_header(draw, left, top, right, "自动抽卡结果", note=note)
    row_width = right - left - PAD * 2
    if not drawn:
        # 今天一次都没抽（次数已经用完）：提示摆在卡片中间。
        draw.text(
            (left + (right - left) / 2, (content_top + bottom) / 2),
            "今天的机会已经用完了，\n明天记得攒够次数再来哦。",
            font=_font(26), fill=TEXT_SUB, anchor="mm", align="center", spacing=12,
        )
        return

    shown = drawn[:LIST_ROW_LIMIT]
    # **两列**排（照用户给的样例）：一列太窄、卡名和"新卡"会挤在一起。
    columns = 2 if len(shown) > 1 else 1
    column_width = (row_width - LIST_COLUMN_GAP) // columns
    # 行高跟着列宽走，布局那边也是用同一套算法算卡片高度的。
    row_height, name_size = _draw_list_metrics(column_width)
    name_font = _font(name_size, bold=True)
    for index, item in enumerate(shown):
        _draw_draw_row(
            canvas, draw, item,
            (
                left + PAD + (index % columns) * (column_width + LIST_COLUMN_GAP),
                content_top + (index // columns) * (row_height + LIST_ROW_GAP),
            ),
            column_width, row_height, name_font,
        )
    rows_used = (len(shown) + columns - 1) // columns
    list_bottom = content_top + rows_used * (row_height + LIST_ROW_GAP)
    if len(drawn) > len(shown):
        list_bottom += 4
        draw.text(
            (left + PAD, list_bottom),
            f"……还有 {len(drawn) - len(shown)} 张，不念了",
            font=_font(22), fill=TEXT_SUB,
        )
        list_bottom += 30
    # 只抽了几张时，下面那两行小字本来会贴着最后一条彩色卡片 —— 卡片高度已经算进它们，
    # 这里再兜一手。
    list_bottom = max(list_bottom, bottom - _s(150))
    # 卡片会被拉到跟左栏一样高，中间空着不好看：补一行小计 + 一句收尾。
    summary = (
        f"新卡 {sum(1 for item in drawn if item.get('is_new'))} 张 · "
        f"重复折成银币 {sum(1 for item in drawn if not item.get('is_new'))} 张"
    )
    summary_font = _font(24)
    if list_bottom + 2 * 40 <= bottom - 30:
        draw.text(
            (left + PAD, list_bottom + 16), summary,
            font=summary_font, fill=TEXT_SUB,
        )
        if _text_width(draw, DRAWS_CLOSING, summary_font) <= row_width:
            draw.text(
                (left + PAD, list_bottom + 56), DRAWS_CLOSING,
                font=summary_font, fill=TEXT_FAINT,
            )
    elif _text_width(draw, DRAWS_CLOSING, summary_font) <= row_width:
        draw.text(
            (left + (right - left) / 2, bottom - 44), DRAWS_CLOSING,
            font=summary_font, fill=TEXT_FAINT, anchor="ms",
        )


def _draw_draw_row(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    item: dict,
    origin: tuple[int, int],
    width: int,
    height: int,
    name_font,
) -> None:
    """一条抽卡结果（照用户给的样例）：浅底圆角条，左边卡名、左下品质徽章、右下新卡/重复。

    底色不上色，颜色只用在品质徽章上（见 ``RARITY_BADGE``）；圆角条本身跟卡片一样
    是半透明的（``PANEL_ALPHA``），描边和品质徽章保持实色。
    """
    x, y = origin
    _paint_panel(
        canvas, (x, y, x + width, y + height),
        NEUTRAL_ROW_FILL, min(_s(14), height // 4),
    )
    draw.rounded_rectangle(
        (x, y, x + width, y + height), radius=min(_s(14), height // 4),
        outline=NEUTRAL_ROW_EDGE, width=2,
    )
    name = _ellipsize(draw, str(item.get("name", "")), name_font, width - PAD * 2)
    draw.text((x + PAD, y + _s(16)), name, font=name_font, fill=TEXT_MAIN)

    label, color = RARITY_BADGE.get(
        str(item.get("rarity", "")), RARITY_BADGE_FALLBACK
    )
    tag_font = _font(22, bold=True)
    tag_height = _s(38)
    tag_width = _text_width(draw, label, tag_font) + _s(30)
    tag_top = y + height - tag_height - _s(12)
    draw.rounded_rectangle(
        (x + PAD, tag_top, x + PAD + tag_width, tag_top + tag_height),
        radius=tag_height // 2, fill=color,
    )
    draw.text(
        (x + PAD + tag_width / 2, tag_top + tag_height / 2 + _s(1)), label,
        font=tag_font, fill=(255, 255, 255), anchor="mm",
    )
    draw.text(
        (x + width - PAD, tag_top + tag_height / 2),
        "新卡" if item.get("is_new") else "重复→银币",
        font=_font(22), fill=ACCENT if item.get("is_new") else TEXT_SUB, anchor="rm",
    )


def _draw_assets_card(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    *,
    shard_gain: int,
    shard_total: int,
    first_check_in: bool,
) -> int:
    """中栏下卡：银币。这是唯一会跨天累积的资产，数字给到最大。"""
    left, top, right, bottom = box
    _card(canvas, box, fill=(255, 251, 253), outline=(250, 224, 236))
    draw = ImageDraw.Draw(canvas)
    content_top = _card_header(
        draw, left, top, right, "银币",
        note="重复卡自动折算" if first_check_in else "今天已经领过了",
        color=ACCENT,
    )
    number_text = f"{shard_total:,}"
    number_font = _font(58, bold=True)
    draw.text(
        (left + PAD, content_top + _s(4)), number_text,
        font=number_font, fill=ACCENT,
    )
    # 先量出数字占多宽，"本次 +N" 跟在它右边；数字特别长就换到下一行去。
    number_width = _text_width(draw, number_text, number_font)
    gain = f"本次 +{shard_gain}" if shard_gain else "本次不再发放"
    gain_font = _font(26)
    gain_x = left + PAD + number_width + 16
    # 数字特别长时"本次 +N"挤不到右边，就换到数字下面一行；说明文字再往下让一档。
    if gain_x + _text_width(draw, gain, gain_font) <= right - PAD:
        draw.text(
            (gain_x, content_top + _s(60)), gain,
            font=gain_font, fill=ACCENT if shard_gain else TEXT_SUB, anchor="ls",
        )
        detail_top = content_top + _s(122)
    else:
        draw.text(
            (left + PAD, content_top + _s(92)), gain,
            font=gain_font, fill=ACCENT if shard_gain else TEXT_SUB,
        )
        detail_top = content_top + _s(150)
    # 这两句写得短，是因为这一栏比原来窄（三栏之后右栏只剩 300 出头）：
    # 宁可分成两行，也不要折出孤零零的第三个字。
    detail = (
        "今日首次签到，银币已到账。" if first_check_in
        else "今天已经签过啦。"
    )
    detail_font = _font(24)
    inner_width = right - left - PAD * 2
    # 要几行就画几行（最多三行）：卡片高度是拉到整栏的，宁可多一行也不要把字裁掉。
    lines = _wrap(
        draw, detail + "攒够 500 就能「开箱」。", detail_font, inner_width
    )[:3]
    line_bottom = detail_top
    for index, line in enumerate(lines):
        draw.text(
            (left + PAD, detail_top + index * 34), line,
            font=detail_font, fill=TEXT_SUB,
        )
        line_bottom = detail_top + (index + 1) * 34
    # 这里**不画**"某某的资产"那种签名：卡片高度是按比例分的、说明又要几行就几行，
    # 签名怎么摆都可能跟说明撞上。名字在卡片左上角那块已经有了。
    return line_bottom


def _draw_luck_card(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    *,
    luck_name: str,
    luck_path: Path,
) -> None:
    """运势卡：**左边一整栏放图**，右边一栏从上到下是等级名、配文、宜、忌。

    左右结构是为了让竖着的运势图能占满卡片高度（图大了不少），文字全挤在右侧那一栏里。
    """
    left, top, right, bottom = box
    _card(canvas, box)
    draw = ImageDraw.Draw(canvas)
    content_top = _card_header(
        draw, left, top, right, "今日运势", note=luck_name, color=ACCENT
    )
    inner_bottom = bottom - PAD
    # 右边文字栏固定宽度（够放"抽卡、开箱、表白"这种一句），剩下全是图的。
    side_width = _s(330)
    image_width = max(right - left - PAD * 3 - side_width, _s(200))
    image_height = max(inner_bottom - content_top, _s(200))
    # 图在画框里等比缩到最大（竖图按高度撑满，横图按宽度）。
    picture = _load_picture(luck_path, (image_width, image_height), crop=False)
    if picture is None:
        draw.rounded_rectangle(
            (left + PAD, content_top, left + PAD + image_width, inner_bottom),
            radius=_s(14), fill=(246, 242, 248),
        )
    else:
        canvas.paste(
            picture,
            (
                left + PAD + (image_width - picture.width) // 2,
                content_top + (image_height - picture.height) // 2,
            ),
            _rounded_mask(picture.size, _s(14)),
        )

    # ---- 右边那一栏：等级名 → 配文 → 宜 / 忌
    side_left = right - PAD - side_width
    name_font = _font(40, bold=True)
    draw.text(
        (side_left, content_top),
        _ellipsize(draw, luck_name, name_font, side_width),
        font=name_font, fill=ACCENT,
    )
    flavor_font = _font(22)
    flavor_lines = _wrap(
        draw, luck_flavor(luck_name), flavor_font, side_width
    )[:2]
    for index, line in enumerate(flavor_lines):
        draw.text(
            (side_left, content_top + _s(56) + index * _s(30)), line,
            font=flavor_font, fill=TEXT_SUB,
        )
    # 宜 / 忌 贴卡片底边往上摆：每条一个标签 + 一句话，写不下就省略号。
    advice_top = inner_bottom - _s(168)
    draw.line(
        (side_left, advice_top - _s(18), right - PAD, advice_top - _s(18)),
        fill=DIVIDER, width=2,
    )
    good, bad = luck_advice(luck_name)
    for index, (label, text, color) in enumerate(
        (("宜", good, (86, 152, 110)), ("忌", bad, (196, 92, 92)))
    ):
        row_top = advice_top + index * _s(64)
        badge = _s(42)
        draw.rounded_rectangle(
            (side_left, row_top, side_left + badge, row_top + badge),
            radius=_s(10), fill=color,
        )
        draw.text(
            (side_left + badge / 2, row_top + badge / 2 + _s(1)), label,
            font=_font(24, bold=True), fill=(255, 255, 255), anchor="mm",
        )
        draw.text(
            (side_left + badge + _s(14), row_top + badge / 2),
            _ellipsize(draw, text, flavor_font, side_width - badge - _s(14)),
            font=flavor_font, fill=(96, 90, 106), anchor="lm",
        )


def _wife_pool_size() -> int:
    """老婆池里有多少张图；取不到就返回 0（只影响一个装饰性的数字）。"""
    try:
        from . import wife

        return len(wife.wife_paths())
    except Exception:  # noqa: BLE001 - 纯装饰信息，出错不值得影响签到
        return 0


def _output_path(user_id: int) -> Path:
    CHECKIN_CARD_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    return CHECKIN_CARD_DIR / f"checkin_{user_id}_{stamp}.jpg"


# 签到图是发完就没用的中间产物：留一段时间便于排查，之后由下一次渲染顺手清掉。
CHECKIN_CARD_KEEP_SECONDS = 3600


def _cleanup_old_files() -> None:
    deadline = time.time() - CHECKIN_CARD_KEEP_SECONDS
    try:
        for path in CHECKIN_CARD_DIR.glob("checkin_*"):
            try:
                if path.stat().st_mtime < deadline:
                    path.unlink(missing_ok=True)
            except OSError:
                continue
    except OSError as error:
        logger.warning(f"[签到图] 清理旧图失败：{error}")


# ------------------------------------------------------------------ 渲染入口
def render_check_in_card(
    *,
    username: str,
    user_id: int | str,
    wife_path: Path | None,
    wife_name: str | None,
    drawn: list[dict],
    drawn_count: int,
    shard_gain: int,
    shard_total: int,
    first_check_in: bool,
    luck_name: str | None = None,
    luck_path: Path | None = None,
    today: datetime.date | None = None,
) -> Path | None:
    """渲染签到图，返回图片路径；渲染不出来时抛异常（调用方退回文案）。

    参数：
        wife_path       今日老婆的图片路径（没有就画一块占位）；同时被拿去当背景底图
        wife_name       老婆的名字；没有名字时**不画名字那一行**（说明直接顶上去）
        drawn           本次自动抽卡的结果，每项 ``{"name":…, "rarity":…, "is_new":…}``
        drawn_count     实际抽了几次
        shard_gain      本次签到实增的银币
        shard_total     签到后的银币总数
        first_check_in  今天是不是第一次签到
        luck_name       今日运势的等级名（如「大吉」）；和 ``luck_path`` 一起给才画运势栏
        luck_path       今日运势的图片路径
    """
    today = today or datetime.date.today()
    username = username.strip() or "群友"
    user_id = str(user_id)   # 官方版是 openid，不是数字 QQ 号

    left_width = LEFT_COLUMN_WIDTH
    right_width = RIGHT_COLUMN_WIDTH
    show_luck = bool(luck_name and luck_path)

    # ---- 右栏三张卡：抽卡结果（上）+ 银币（中）+ 今日运势（下）
    shown = drawn[:LIST_ROW_LIMIT]
    overflow = len(drawn) > len(shown)
    # 两列排：行高跟绘制那边用同一个算法（见 _draw_list_metrics），否则卡片会比列表矮。
    list_columns = 2 if len(shown) > 1 else 1
    column_width = ((right_width - PAD * 2) - LIST_COLUMN_GAP) // list_columns
    row_height, _ = _draw_list_metrics(column_width)
    list_rows = (len(shown) + list_columns - 1) // list_columns if shown else 0
    draws_height = CARD_HEADER_HEIGHT + max(
        list_rows * (row_height + LIST_ROW_GAP), row_height
    )
    # 列表下面还有"小计 + 收尾"两行，卡片必须留出它们的位置
    draws_height += _s(180)
    # 空列表时那一块提示也要占点地方，别缩成一条
    if not shown:
        draws_height = CARD_HEADER_HEIGHT + 4 * (LIST_ROW_HEIGHT + LIST_ROW_GAP)
    draws_height += (FOOTER_HEIGHT if overflow else 0) + PAD
    assets_height = max(ASSETS_MIN_HEIGHT, CARD_HEADER_HEIGHT + ASSETS_CONTENT_HEIGHT)
    # 抽卡卡最多长到"比实际行数多留一行"（再加小计/收尾两行的位置）：再高只是空白，
    # 多出来的空间留给运势卡。
    draws_cap = CARD_HEADER_HEIGHT + PAD + (list_rows + 1) * (
        row_height + LIST_ROW_GAP
    ) + _s(140)
    draws_height = min(draws_height, draws_cap)
    luck_height = (
        CARD_HEADER_HEIGHT + LUCK_IMAGE_MIN_HEIGHT
        + LUCK_CARD_TEXT_HEIGHT + LUCK_ADVICE_HEIGHT + PAD
    )
    # 提示卡（"输入功能列表…"）：右栏单独一张，高度按文字来
    show_hint = bool(WIFE_HINT)
    hint_height = _s(120) if show_hint else 0

    # 右栏：抽卡结果 + 银币 + 今日运势（提示卡在**左栏**老婆图下面）
    right_min = (
        draws_height + GAP + assets_height
        + (GAP + luck_height if show_luck else 0)
    )
    # 左栏的高度由老婆图的画框决定，而画框**跟着图片的宽高比走**（见 _wife_image_box）：
    # 宽图画框就是扁的、竖图画框就是高的。这里**没有**小卡片的标题栏（"今日的老婆"
    # 那两行已去掉），图直接顶到卡片上边，所以只算 内边距 + 图 + 名字 + 说明。
    # 画框的高度上限直接拿"右栏那一摞有多高"来定：右栏本来就比左栏高，让老婆图
    # 长到刚好填满，整张图就不会在左栏底下剩一条空白。
    # **老婆文件夹是空的时候**画框缩成一小块：那时卡片里本来就没东西可看，
    # 撑到整栏高只会把名字和说明挤出卡片底边。
    wife_name_height = WIFE_NAME_HEIGHT if wife_name else 0
    wife_note_height = WIFE_NOTE_LINE * WIFE_NOTE_LINES if WIFE_NOTE else 0
    wife_inner_width = left_width - PAD * 2
    wife_fixed_height = (
        PAD * 2 + _s(18) + wife_name_height + wife_note_height
    )
    wife_budget = right_min - (
        HEADER_HEIGHT + GAP
        + (GAP + hint_height if show_hint else 0)
        + wife_fixed_height
    )
    wife_image_box = _wife_image_box(
        wife_inner_width,
        ratio=_image_ratio(wife_path),
        missing=wife_path is None,
        max_height=min(
            WIFE_IMAGE_MAX_HEIGHT, max(wife_budget, WIFE_IMAGE_MIN_HEIGHT)
        ),
    )
    # 没名字时那一行整段不占位，左卡跟着矮一截（多出来的空间由右栏的卡片吃掉）。
    wife_height = wife_fixed_height + wife_image_box[1]
    # 左栏：用户信息条（固定高）+ 老婆卡 + （提示卡）+ 卡间距
    left_min = (
        HEADER_HEIGHT + GAP + wife_height
        + (GAP + hint_height if show_hint else 0)
    )
    # 整张图的高度取两栏里更高的那一栏
    left_height = max(left_min, right_min)

    # ---- 垂直方向：右栏几张卡按各自内容的高度**按比例**分掉多出来的空间，
    # 列表短的时候不至于把抽卡卡撑成一大片空白，运势卡也不会被挤瘦。
    # 注意右边的和总高度都要**用分配之后的高度重算** —— 运势卡长高了，画布也得跟着长，
    # 不然卡片底部（宜/忌 那两行）会被画到画布外面去。
    surplus = left_height - right_min
    if surplus > 0:
        # 抽卡列表最多长到"比实际行数多留一行"（再加小计/收尾两行的位置），再高就只是空白；
        # 多出来的全给运势卡（竖图越大越好看）。
        draws_cap = CARD_HEADER_HEIGHT + PAD + (
            (list_rows + 1) * (row_height + LIST_ROW_GAP)
        ) + _s(140)
        if show_luck:
            extra = min(surplus, max(0, draws_cap - draws_height))
            draws_height += extra
            surplus -= extra
        if surplus > 0:
            weights = [assets_height] + (
                [luck_height] if show_luck else []
            )
            total_weight = sum(weights)
            assets_height += int(surplus * assets_height / total_weight)
            if show_luck:
                luck_height += surplus - int(surplus * assets_height / total_weight)
        right_total = draws_height + assets_height + (
            luck_height if show_luck else 0
        ) + (1 + int(show_luck)) * GAP
    else:
        right_total = right_min
    left_height = max(left_min, right_total)
    total_height = MARGIN * 2 + left_height + FOOTER_HEIGHT
    # 左栏的纵向骨架：用户信息条在最上、提示卡贴底边，老婆卡吃掉中间那段
    left_top = MARGIN
    header_box = (
        MARGIN, left_top, MARGIN + left_width, left_top + HEADER_HEIGHT,
    )
    body_top = header_box[3] + GAP
    hint_box = None
    wife_box = (MARGIN, body_top, MARGIN + left_width, MARGIN + left_height)
    if show_hint:
        hint_box = (
            MARGIN, MARGIN + left_height - hint_height,
            MARGIN + left_width, MARGIN + left_height,
        )
        wife_box = (MARGIN, body_top, MARGIN + left_width, hint_box[1] - GAP)

    # ---- 背景：模糊照片 + 半透明白纱，抄 example 那张图的做法
    background = _background_source(wife_path)
    if background is None:
        canvas = _linear_gradient(
            (IMAGE_WIDTH, total_height), BACKGROUND_TOP, BACKGROUND_BOTTOM
        )
    else:
        background = ImageOps.fit(background, (IMAGE_WIDTH, total_height),
                                  method=Image.Resampling.LANCZOS)
        canvas = background

    right_left = MARGIN + left_width + GAP
    draws_box = (right_left, MARGIN, right_left + right_width, MARGIN + draws_height)
    assets_box = (
        right_left, draws_box[3] + GAP,
        right_left + right_width, draws_box[3] + GAP + assets_height,
    )
    # 今日运势垫底（它吃掉剩下的全部高度）
    luck_top = assets_box[3] + GAP
    luck_box = (right_left, luck_top, right_left + right_width, MARGIN + left_height)

    # 左卡：用户信息条（一张独立的卡）+ 老婆卡 +（提示卡）
    _card(canvas, header_box)
    draw = ImageDraw.Draw(canvas)
    _draw_header(
        canvas, draw, header_box, username=username, user_id=user_id,
        today=today, first_check_in=first_check_in,
    )
    # 老婆卡：只有老婆的图和名字（没有小标题那一行）
    _draw_wife_card(
        canvas, draw, wife_box,
        username=username, wife_path=wife_path, wife_name=wife_name,
        name_height=wife_name_height, image_box=wife_image_box,
    )
    _draw_draws_card(canvas, draw, draws_box, drawn=drawn, drawn_count=drawn_count)
    _draw_assets_card(
        canvas, draw, assets_box, shard_gain=shard_gain,
        shard_total=shard_total, first_check_in=first_check_in,
    )
    if hint_box is not None:
        _draw_hint_card(
            canvas, draw, hint_box, text=WIFE_HINT.format(command="功能列表")
        )
    if show_luck:
        _draw_luck_card(
            canvas, draw, luck_box, luck_name=str(luck_name), luck_path=luck_path
        )

    # 左下角一个小角标，纯装饰（放在卡片外面的留白里，不跟正文抢地方）
    draw.text(
        (MARGIN, MARGIN + left_height + 8),
        f"老婆池 {_wife_pool_size()} 张 · qqchatbot",
        font=_font(20), fill=TEXT_FAINT, anchor="la",
    )

    path = _output_path(user_id)
    # 存 JPEG 不存 PNG：这张图里有照片，PNG 要 590 KB 而 JPEG q88 只要 175 KB，
    # 画质上肉眼看不出差别，群里发图快得多。
    canvas.save(path, format="JPEG", quality=88, optimize=True)
    logger.info(f"[签到图] 已渲染：{path}（{canvas.width}×{canvas.height}）")
    _cleanup_old_files()
    return path


# ------------------------------------------------------------------ 库存图
# 每张小卡五列；名字太长就缩字号，缩到下限再省略号。
INVENTORY_COLUMNS = 5
INVENTORY_TILE_HEIGHT = _s(88)
INVENTORY_TILE_GAP = _s(12)
INVENTORY_TILE_FONT = [24, 22, 20, 18]  # 依次试着用，第一个放得下就用它
INVENTORY_HEADER_HEIGHT = _s(132)       # 顶部那张"谁 + 有多少张卡"的卡
INVENTORY_SHARDS_HEIGHT = _s(132)       # 底部那张"银币"的卡
INVENTORY_CLOSING = "想看缺哪张就去翻卡池吧。"


def _draw_inventory_tile(
    canvas: Image.Image,
    box: tuple[int, int, int, int],
    *,
    name: str,
    label: str,
    color: tuple[int, int, int],
) -> None:
    """一张卡：浅底圆角小卡，上面一行卡名、下面一个品质徽章（窄底 + 同色字，看得清）。"""
    left, top, right, bottom = box
    _card(canvas, box, radius=_s(12))
    draw = ImageDraw.Draw(canvas)
    inner = _s(20)
    width = right - left - inner * 2
    for size in INVENTORY_TILE_FONT:
        name_font = _font(size, bold=True)
        if _text_width(draw, name, name_font) <= width:
            break
    name = _ellipsize(draw, name, name_font, width)
    draw.text(
        (left + inner, top + _s(16)), name, font=name_font, fill=TEXT_MAIN,
    )
    badge_font = _font(18, bold=True)
    badge_width = _text_width(draw, label, badge_font) + _s(20)
    badge_height = _s(28)
    badge_left = left + inner
    badge_top = bottom - _s(14) - badge_height
    # 徽章用"同色的淡底 + 同色字"：五列之后格子窄，纯色块压白字会显得又重又挤
    draw.rounded_rectangle(
        (badge_left, badge_top, badge_left + badge_width, badge_top + badge_height),
        radius=badge_height // 2, fill=tuple(min(255, c + 150) for c in color),
    )
    draw.text(
        (badge_left + badge_width / 2, badge_top + badge_height / 2 + _s(1)), label,
        font=badge_font, fill=color, anchor="mm",
    )


def render_inventory_card(
    *,
    username: str,
    user_id: int | str,
    groups: list[tuple[str, str, tuple[int, int, int], list[str]]],
    shards: int,
    total_cards: int,
    show_all: bool,
    today: datetime.date | None = None,
) -> Path | None:
    """把「查看库存 / 查看全部库存」渲染成一张图（跟签到图一个路子）。

    参数：
        groups      ``[(分组的标题, 徽章上的字, 徽章颜色, [卡名, …]), …]``（空的组不传）
        shards      银币总数
        total_cards 手里一共有多少张卡
        show_all    True = 「查看全部库存」（列出稀有/史诗），False = 精选视图
    """
    today = today or datetime.date.today()
    username = username.strip() or "群友"
    user_id = str(user_id)   # 官方版是 openid，不是数字 QQ 号

    columns = INVENTORY_COLUMNS
    content_width = IMAGE_WIDTH - MARGIN * 2
    tile_width = (content_width - INVENTORY_TILE_GAP * (columns - 1)) // columns
    total_tiles = sum(len(names) for _, _, _, names in groups)
    total_rows = sum(
        (len(names) + columns - 1) // columns for _, _, _, names in groups
    )
    group_headers = _s(52) * len(groups)
    grid_height = (
        total_rows * (INVENTORY_TILE_HEIGHT + INVENTORY_TILE_GAP)
        + group_headers + _s(30) * max(len(groups) - 1, 0)
    )
    height = (
        MARGIN * 2 + INVENTORY_HEADER_HEIGHT + _s(24) + grid_height
        + _s(24) + INVENTORY_SHARDS_HEIGHT + FOOTER_HEIGHT
    )

    canvas = _background_canvas(IMAGE_WIDTH, height)
    draw = ImageDraw.Draw(canvas)

    # ---- 顶部：谁 + 有多少张卡
    header_box = (MARGIN, MARGIN, IMAGE_WIDTH - MARGIN, MARGIN + INVENTORY_HEADER_HEIGHT)
    _card(canvas, header_box)
    draw = ImageDraw.Draw(canvas)
    left, top, right = header_box[0], header_box[1], header_box[2]
    size = _s(96)
    avatar_top = top + (INVENTORY_HEADER_HEIGHT - size) // 2
    draw.ellipse(
        (left + PAD, avatar_top, left + PAD + size, avatar_top + size),
        fill=ACCENT_SOFT, outline=(246, 216, 230), width=2,
    )
    draw.text(
        (left + PAD + size / 2, avatar_top + size / 2 + _s(2)),
        (username or "杂")[0], font=_font(44, bold=True), fill=ACCENT, anchor="mm",
    )
    text_left = left + PAD + size + _s(22)
    title = "全部库存" if show_all else "查看库存"
    draw.text((text_left, top + _s(26)), title, font=_font(34, bold=True), fill=TEXT_MAIN)
    draw.text(
        (text_left, top + _s(84)),
        f"{username} · {user_id} · {today.strftime('%Y-%m-%d')}",
        font=_font(22), fill=TEXT_SUB,
    )
    count_text = f"{total_cards} 张卡"
    count_font = _font(26, bold=True)
    draw.text(
        (right - PAD, top + INVENTORY_HEADER_HEIGHT / 2), count_text,
        font=count_font, fill=ACCENT, anchor="rm",
    )

    # ---- 中间：按档位分组的卡片网格
    y = MARGIN + INVENTORY_HEADER_HEIGHT + _s(24)
    grid_top = y
    if not groups:
        empty_box = (
            MARGIN, grid_top, IMAGE_WIDTH - MARGIN, grid_top + _s(200),
        )
        _card(canvas, empty_box)
        draw = ImageDraw.Draw(canvas)
        draw.text(
            (IMAGE_WIDTH / 2, (empty_box[1] + empty_box[3]) / 2),
            "嗯……空的？先去抽几张卡再来吧。",
            font=_font(26), fill=TEXT_SUB, anchor="mm",
        )
        y = empty_box[3]
    for title, label, color, names in groups:
        draw.text(
            (MARGIN + _s(6), y + _s(26)), f"{title}（{len(names)}）",
            font=_font(24, bold=True), fill=color, anchor="lm",
        )
        y += _s(52)
        for index, name in enumerate(names):
            row, column = divmod(index, columns)
            tile_left = MARGIN + column * (tile_width + INVENTORY_TILE_GAP)
            tile_top = y + row * (INVENTORY_TILE_HEIGHT + INVENTORY_TILE_GAP)
            _draw_inventory_tile(
                canvas,
                (tile_left, tile_top, tile_left + tile_width,
                 tile_top + INVENTORY_TILE_HEIGHT),
                name=name, label=label, color=color,
            )
        y += (len(names) + columns - 1) // columns * (
            INVENTORY_TILE_HEIGHT + INVENTORY_TILE_GAP
        ) + _s(30)

    # ---- 底部：银币
    shards_top = height - MARGIN - FOOTER_HEIGHT - INVENTORY_SHARDS_HEIGHT
    shards_box = (MARGIN, shards_top, IMAGE_WIDTH - MARGIN, shards_top + INVENTORY_SHARDS_HEIGHT)
    _card(canvas, shards_box, fill=(255, 251, 253), outline=(250, 224, 236))
    draw = ImageDraw.Draw(canvas)
    draw.text(
        (MARGIN + PAD, shards_top + _s(24)), "银币",
        font=_font(26, bold=True), fill=ACCENT,
    )
    shard_font = _font(56, bold=True)
    draw.text(
        (MARGIN + PAD, shards_top + _s(66)), f"{shards:,}",
        font=shard_font, fill=ACCENT,
    )
    draw.text(
        (IMAGE_WIDTH - MARGIN - PAD, shards_top + INVENTORY_SHARDS_HEIGHT / 2),
        INVENTORY_CLOSING, font=_font(24), fill=TEXT_SUB, anchor="rm",
    )

    # 左下角小角标（跟签到图同一个位置）
    draw.text(
        (MARGIN, height - MARGIN + _s(8)),
        f"共 {total_tiles} 张 · qqchatbot",
        font=_font(20), fill=TEXT_FAINT, anchor="la",
    )

    path = _output_path(user_id)
    canvas.save(path, format="JPEG", quality=88, optimize=True)
    logger.info(f"[库存图] 已渲染：{path}（{canvas.width}×{canvas.height}）")
    _cleanup_old_files()
    return path


# ------------------------------------------------------------------ 锻造排行榜
# 固定十行：榜上不足十条时，空位也画出来（「虚位以待」），这样"前十"是一眼能数清的。
# 新锻造系统要一行塞七列（名次 / 总价值 / 锻造人 / 时间 / 刀型 / 图案 / 分数），
# 比签到图那套宽，所以这张图单独用更宽的画布。
FORGE_RANK_IMAGE_WIDTH = 2400
FORGE_RANK_HEADER_HEIGHT = _s(190)      # 顶部标题卡
FORGE_RANK_COLUMN_LABEL_HEIGHT = _s(48)  # 列表上方那行列名
FORGE_RANK_ROW_HEIGHT = _s(104)         # 每一行（一条记录）的高度
FORGE_RANK_ROW_GAP = _s(12)             # 行与行之间的缝
# 七列**等宽**铺满整行（内容区宽度 ÷ 7，每列左边对齐自己那一格的起点）。
# 之前是按内容挤着放的，长数字和名字会挤成一坨，所以改成均分。
FORGE_RANK_COLUMNS = 7
FORGE_RANK_COLUMN_GAP = _s(12)          # 每列内部留白：文字不能顶到下一列
# 前三名的颜色：金 / 银 / 铜；其余名次用中性灰紫。
FORGE_RANK_COLORS = {
    1: (198, 132, 42),
    2: (126, 136, 154),
    3: (172, 108, 66),
}
FORGE_RANK_EMPTY = "虚位以待"


def _tint(color: tuple[int, int, int], ratio: float) -> tuple[int, int, int]:
    """把颜色往白色里调：``ratio=0`` 是原色，``1`` 是纯白（画徽章淡底用）。"""
    ratio = min(max(ratio, 0.0), 1.0)
    return tuple(int(channel + (255 - channel) * ratio) for channel in color)


def render_forge_rank_card(
    *,
    records: list[dict],
    user_id: int | str,
    now: datetime.datetime | None = None,
) -> Path:
    """把「锻造排行榜」渲染成一张图：标题 + 固定十行记录。

    参数：
        records  已按总价值从高到低排好的记录，每项
                 ``{"value": 整数, "name": 锻造人, "time": "YYYY-MM-DD HH:MM",
                 "knife": 刀型, "pattern": 图案模板, "score": 测试分数}``
                 （旧系统的记录只有 ``sword``，没有刀型/图案/分数时就画 —）；
                 列从左到右是 名次 / 总价值 / 锻造人 / 锻造时间 / 刀型 / 图案 / 分数，
                 不足十条时后面补空行（不补的话"一共十行"就不成立）
        user_id  发命令的人（只用来给输出文件命名）
        now      只给左下角那句渲染时间用；测试可以钉死

    渲染不出来时抛异常（调用方退回文字版，排行榜本身不能因此看不到）。
    """
    now = now or datetime.datetime.now()
    records = list(records or [])[:FORGE_RANK_TOP_N]
    left = MARGIN
    right = FORGE_RANK_IMAGE_WIDTH - MARGIN
    # 七列等宽：内容区（左右各让出一层内边距）平均切成 7 格，文字都从自己那格
    # 的左边起排 —— 列与列之间是等距的，不会再挤成一块。
    content_left = left + PAD
    content_right = right - PAD
    column_width = (content_right - content_left) / FORGE_RANK_COLUMNS
    column_x = [content_left + index * column_width
                for index in range(FORGE_RANK_COLUMNS)]
    text_limit = column_width - FORGE_RANK_COLUMN_GAP

    header_box = (
        left, MARGIN, right, MARGIN + FORGE_RANK_HEADER_HEIGHT,
    )
    label_top = header_box[3] + _s(18)
    rows_top = label_top + FORGE_RANK_COLUMN_LABEL_HEIGHT
    rows_height = (
        FORGE_RANK_TOP_N * FORGE_RANK_ROW_HEIGHT
        + (FORGE_RANK_TOP_N - 1) * FORGE_RANK_ROW_GAP
    )
    height = (
        MARGIN * 2 + FORGE_RANK_HEADER_HEIGHT + _s(18)
        + FORGE_RANK_COLUMN_LABEL_HEIGHT + rows_height + FOOTER_HEIGHT
    )

    canvas = _background_canvas(FORGE_RANK_IMAGE_WIDTH, height)
    draw = ImageDraw.Draw(canvas)

    # ---- 顶部标题卡
    _card(canvas, header_box)
    draw = ImageDraw.Draw(canvas)
    draw.text(
        (left + PAD, MARGIN + _s(30)), "锻造排行榜",
        font=_font(56, bold=True), fill=TEXT_MAIN,
    )
    subtitle = (
        "还没有人收工，砸完一局来占个位置吧。"
        if not records
        else "锻造总价值最高的十次历史记录 · 时间精确到分"
    )
    draw.text(
        (left + PAD, MARGIN + _s(116)), subtitle,
        font=_font(26), fill=TEXT_SUB,
    )
    draw.text(
        (right - PAD, MARGIN + _s(48)), "TOP 10",
        font=_font(54, bold=True), fill=ACCENT, anchor="ra",
    )
    draw.text(
        (right - PAD, MARGIN + _s(126)), "只保留总价值最高的十次",
        font=_font(22), fill=TEXT_FAINT, anchor="ra",
    )

    # ---- 列名（名次 / 总价值 / 锻造人 / 锻造时间 / 刀型 / 图案 / 分数）
    label_font = _font(22, bold=True)
    label_y = label_top + FORGE_RANK_COLUMN_LABEL_HEIGHT / 2
    labels = ("名次", "总价值", "锻造人", "锻造时间", "刀型", "图案", "分数")
    for x, label in zip(column_x, labels):
        draw.text((x, label_y), label, font=label_font,
                  fill=TEXT_FAINT, anchor="lm")

    badge_width = _s(104)
    badge_height = _s(52)
    for index in range(FORGE_RANK_TOP_N):
        rank = index + 1
        top = rows_top + index * (FORGE_RANK_ROW_HEIGHT + FORGE_RANK_ROW_GAP)
        box = (left, top, right, top + FORGE_RANK_ROW_HEIGHT)
        # 隔行换一个极淡的底色，十行才不会糊成一片。
        _card(
            canvas, box, radius=14,
            fill=PANEL_FILL if index % 2 == 0 else (252, 249, 253),
        )
        draw = ImageDraw.Draw(canvas)
        middle = top + FORGE_RANK_ROW_HEIGHT / 2
        record = records[index] if index < len(records) else None
        color = (
            FORGE_RANK_COLORS.get(rank, TEXT_MAIN)
            if record is not None
            else TEXT_FAINT
        )
        # 行首的名次徽章：1st / 2nd / …（空位也照样有，十行的骨架不会缺一条）
        badge_top = top + (FORGE_RANK_ROW_HEIGHT - badge_height) / 2
        draw.rounded_rectangle(
            (left + PAD, badge_top, left + PAD + badge_width, badge_top + badge_height),
            radius=badge_height // 2,
            fill=_tint(color, 0.84 if record is not None else 0.92),
        )
        draw.text(
            (left + PAD + badge_width / 2, badge_top + badge_height / 2 + _s(1)),
            rank_ordinal(rank), font=_font(28, bold=True),
            fill=color, anchor="mm",
        )
        if record is None:
            # 空位：每一列都画一个 —，只有「锻造人」那列写「虚位以待」
            draw.text((column_x[1], middle), "—", font=_font(36, bold=True),
                      fill=TEXT_FAINT, anchor="lm")
            draw.text((column_x[2], middle), FORGE_RANK_EMPTY, font=_font(28),
                      fill=TEXT_FAINT, anchor="lm")
            for column in (3, 4, 5, 6):
                draw.text((column_x[column], middle), "—", font=_font(24),
                          fill=TEXT_FAINT, anchor="lm")
            continue

        # 总价值：数字长了就缩字号，绝不截断（截断就把金额看错了）。
        value_text = f"{int(record.get('value') or 0):,}"
        value_font = _font(40, bold=True)
        for size in (40, 36, 32, 28):
            value_font = _font(size, bold=True)
            if _text_width(draw, value_text, value_font) <= text_limit:
                break
        draw.text(
            (column_x[1], middle), value_text, font=value_font,
            fill=ACCENT if rank <= 3 else TEXT_MAIN, anchor="lm",
        )

        # 锻造人：一格之内放不下就用省略号，不会压到时间那一列。
        name_text = _ellipsize(
            draw, str(record.get("name") or "无名氏"), _font(30), text_limit
        )
        draw.text(
            (column_x[2], middle), name_text, font=_font(30),
            fill=TEXT_MAIN, anchor="lm",
        )

        # 锻造时间：长度固定（YYYY-MM-DD HH:MM），不截断。
        draw.text(
            (column_x[3], middle), str(record.get("time") or "—"),
            font=_font(22), fill=TEXT_SUB, anchor="lm",
        )

        # 刀型：廓尔喀刀 / 折叠刀 / 刺刀 / 蝴蝶刀 / 爪子刀 / M9刺刀。
        # 旧系统的记录没有刀型，退回它存下来的剑名（石剑 / 铁剑…）。
        knife_text = str(record.get("knife") or record.get("sword") or "").strip() or "—"
        knife_text = _ellipsize(draw, knife_text, _font(24), text_limit)
        draw.text(
            (column_x[4], middle), knife_text, font=_font(24),
            fill=TEXT_SUB, anchor="lm",
        )

        # 图案模板：狩猎网格 … 红宝石。
        pattern_text = str(record.get("pattern") or "").strip() or "—"
        pattern_text = _ellipsize(draw, pattern_text, _font(24), text_limit)
        draw.text(
            (column_x[5], middle), pattern_text, font=_font(24),
            fill=TEXT_SUB, anchor="lm",
        )

        # 测试分数：满分 300。
        score = record.get("score")
        score_text = f"{int(score)} 分" if score is not None else "—"
        draw.text(
            (column_x[6], middle), score_text, font=_font(24, bold=True),
            fill=TEXT_MAIN, anchor="lm",
        )

    # 左下角小角标（跟签到图/库存图同一个位置）
    draw.text(
        (MARGIN, height - MARGIN + _s(8)),
        f"共 {len(records)} 条记录 · {now.strftime('%Y-%m-%d %H:%M')} · qqchatbot",
        font=_font(20), fill=TEXT_FAINT, anchor="la",
    )

    path = _output_path(user_id)
    canvas.save(path, format="JPEG", quality=88, optimize=True)
    logger.info(f"[锻造排行榜] 已渲染：{path}（{canvas.width}×{canvas.height}）")
    _cleanup_old_files()
    return path
