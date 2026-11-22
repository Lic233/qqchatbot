"""宠物状态图（横向宽版）：左边整张场景图，右边一块信息面板。

要点是**不裁图**：场景图按原比例完整放进左边，右边单独开一栏放数值，
而不是像竖版那样把图放大到铺满再裁掉两边。

只画静态图，不做交互。返回图片路径；Pillow 没装或素材缺了就返回 None，
调用方退回纯文字面板（跟签到图一个套路）。
"""
from __future__ import annotations

from .base import *  # noqa: F401,F403

try:
    from PIL import Image, ImageDraw, ImageFilter, ImageFont
except ImportError:  # 没装 Pillow 就只能发文字
    Image = None  # type: ignore[assignment]

FONT_REGULAR = (
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/simhei.ttf",
    "C:/Windows/Fonts/Deng.ttf",
)
FONT_BOLD = (
    "C:/Windows/Fonts/msyhbd.ttc",
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/simhei.ttf",
)

CARD_SIZE = (1960, 900)
ART_BOX = (40, 40, 1350, 860)         # 场景图能占的最大区域（会等比缩放居中）
PANEL_BOX = (1395, 40, 1920, 860)     # 右侧信息面板
TEXT = (43, 43, 51)
SUBTLE = (124, 124, 136)
WHITE = (255, 255, 255)
MOOD_COLOR = (232, 106, 138)
STAMINA_COLOR = (79, 163, 217)
EXP_COLOR = (139, 111, 196)
AFFECTION_COLOR = (233, 146, 47)
COIN_COLOR = (201, 162, 39)
TRACK = (231, 231, 238)
PANEL_FILL = (253, 252, 250, 244)

_font_cache: dict[tuple[bool, int], "ImageFont.FreeTypeFont"] = {}


def _font(size: int, *, bold: bool = False):
    key = (bold, size)
    cached = _font_cache.get(key)
    if cached is not None:
        return cached
    for candidate in FONT_BOLD if bold else FONT_REGULAR:
        if not Path(candidate).is_file():
            continue
        try:
            font = ImageFont.truetype(candidate, size)
        except OSError:
            continue
        _font_cache[key] = font
        return font
    try:
        fallback = ImageFont.load_default(size)
    except TypeError:
        fallback = ImageFont.load_default()
    _font_cache[key] = fallback
    return fallback


def _cover(image: "Image.Image", size: tuple[int, int]) -> "Image.Image":
    """等比放大后居中裁切，用来铺满背景。"""
    target_w, target_h = size
    ratio = max(target_w / image.width, target_h / image.height)
    resized = image.resize(
        (max(1, int(image.width * ratio)), max(1, int(image.height * ratio))),
        Image.LANCZOS,
    )
    left = (resized.width - target_w) // 2
    top = (resized.height - target_h) // 2
    return resized.crop((left, top, left + target_w, top + target_h))


def _contain(image: "Image.Image", size: tuple[int, int]) -> "Image.Image":
    """等比缩放塞进框里，整张都留着（不裁）。"""
    target_w, target_h = size
    ratio = min(target_w / image.width, target_h / image.height)
    return image.resize(
        (max(1, int(image.width * ratio)), max(1, int(image.height * ratio))),
        Image.LANCZOS,
    )


def _bar(draw, box: tuple[int, int, int, int], ratio: float, color) -> None:
    left, top, right, bottom = box
    radius = (bottom - top) // 2
    draw.rounded_rectangle(box, radius=radius, fill=TRACK)
    width = int((right - left) * max(0.0, min(1.0, ratio)))
    if width >= 4:
        draw.rounded_rectangle((left, top, left + max(width, radius * 2), bottom),
                               radius=radius, fill=color)


def _wrap(draw, text: str, font, width: int) -> list[str]:
    """按像素宽度断行（中文逐字断，够用了）。"""
    lines: list[str] = []
    line = ""
    for char in text:
        if char == "\n":
            lines.append(line)
            line = ""
            continue
        probe = line + char
        if draw.textlength(probe, font=font) > width and line:
            lines.append(line)
            line = char
        else:
            line = probe
    if line:
        lines.append(line)
    return lines


def render_pet_card(
    *,
    name: str,
    level: int,
    exp: int,
    exp_need: int,
    mood: int,
    stamina: int,
    coins: int,
    status: str,
    chatter: str,
    background: Path | None,
    out_dir: Path,
    mood_max: int = 100,
    stamina_max: int = 100,
    affection: int = 100,
    affection_max: int = 100,
    max_level: int = 30,
    owner: str = "",
) -> Path | None:
    """画一张横向宠物状态图，返回路径；画不出来返回 None。"""
    if Image is None:
        return None
    if background is None or not Path(background).is_file():
        return None
    try:
        with Image.open(background) as raw:
            art = raw.convert("RGB")
    except (OSError, ValueError) as error:
        log(f"[宠物] 读背景图失败：{error!r}")
        return None

    width, height = CARD_SIZE
    # 背景：同一张图放大裁切 + 模糊压暗，给左边那张原图做个衬底
    canvas = _cover(art, CARD_SIZE).filter(ImageFilter.GaussianBlur(26))
    canvas = Image.blend(canvas, Image.new("RGB", CARD_SIZE, (18, 20, 30)), 0.55)

    # 左边：整张场景图（等比缩放，不裁），圆角 + 细边
    box_w = ART_BOX[2] - ART_BOX[0]
    box_h = ART_BOX[3] - ART_BOX[1]
    shown = _contain(art, (box_w, box_h))
    art_layer = Image.new("RGBA", CARD_SIZE, (0, 0, 0, 0))
    left = ART_BOX[0] + (box_w - shown.width) // 2
    top = ART_BOX[1] + (box_h - shown.height) // 2
    mask = Image.new("L", shown.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, shown.width, shown.height),
                                           radius=28, fill=255)
    art_layer.paste(shown, (left, top), mask)
    canvas = canvas.convert("RGBA")
    canvas.alpha_composite(art_layer)

    draw = ImageDraw.Draw(canvas, "RGBA")
    draw.rounded_rectangle((left, top, left + shown.width, top + shown.height),
                           radius=28, outline=(255, 255, 255, 60), width=2)

    # 右边：信息面板
    draw.rounded_rectangle(PANEL_BOX, radius=32, fill=PANEL_FILL)
    inner_left = PANEL_BOX[0] + 42
    inner_right = PANEL_BOX[2] - 42
    inner_width = inner_right - inner_left
    panel_height = PANEL_BOX[3] - PANEL_BOX[1]

    # 先算行数和总高，再整体垂直居中——面板比内容高，不能一律顶头写，
    # 不然底下空一大截很难看。
    status_lines = _wrap(draw, status, _font(27, bold=True), inner_width)
    # 那句话后面跟着引号，按内宽排版常把「」单独挤到下一行：宁可让最后一行
    # 稍微溢出一点（面板左右还有 42px 内边距），也别让一个引号占一整行。
    chat_lines = _wrap(draw, f"「{chatter}」", _font(27), inner_width)
    if len(chat_lines) > 1 and len(chat_lines[-1].strip()) <= 1:
        tail = chat_lines.pop()
        chat_lines[-1] += tail
    owner_line = f"主人 · {owner}" if owner else ""
    content_height = ((40 if owner_line else 0) + 74 + 58
                      + 4 * (34 + 16 + 36) + 76 + 30
                      + 38 * len(status_lines) + 16 + 38 * len(chat_lines))
    cursor = PANEL_BOX[1] + max(46, (panel_height - content_height) // 2)

    # 主人的名字：宠物名字上面一行小字，别抢主标题的视觉重量
    if owner_line:
        draw.text((inner_left, cursor), owner_line, font=_font(24), fill=SUBTLE)
        cursor += 40

    draw.text((inner_left, cursor), name, font=_font(52, bold=True), fill=TEXT)
    cursor += 74

    if level >= max_level:
        draw.text((inner_left, cursor), f"Lv.{level}", font=_font(34, bold=True),
                  fill=EXP_COLOR)
        draw.text((inner_left + 130, cursor + 6), "已满级", font=_font(26),
                  fill=SUBTLE)
    else:
        draw.text((inner_left, cursor), f"Lv.{level}", font=_font(34, bold=True),
                  fill=EXP_COLOR)
        draw.text((inner_left + 120, cursor + 6), f"经验 {exp}/{exp_need}",
                  font=_font(26), fill=SUBTLE)
    cursor += 58

    for label, value, total, color in (
        ("心情", mood, max(1, mood_max), MOOD_COLOR),
        ("体力", stamina, max(1, stamina_max), STAMINA_COLOR),
        ("好感", affection, max(1, affection_max), AFFECTION_COLOR),
        ("经验", exp, max(1, exp_need), EXP_COLOR),
    ):
        draw.text((inner_left, cursor), label, font=_font(28), fill=SUBTLE)
        value_text = f"{value}/{total}"
        draw.text((inner_right - draw.textlength(value_text, font=_font(28, bold=True)),
                   cursor), value_text, font=_font(28, bold=True), fill=TEXT)
        cursor += 34
        _bar(draw, (inner_left, cursor, inner_right, cursor + 16), value / total, color)
        cursor += 36

    draw.text((inner_left, cursor), "银币", font=_font(28), fill=SUBTLE)
    draw.text((inner_left + 78, cursor - 10), f"{coins}", font=_font(46, bold=True),
              fill=COIN_COLOR)
    cursor += 76

    draw.line((inner_left, cursor, inner_right, cursor), fill=(224, 224, 232), width=2)
    cursor += 30

    for line in status_lines:
        draw.text((inner_left, cursor), line, font=_font(27, bold=True), fill=TEXT)
        cursor += 38
    cursor += 16

    for line in chat_lines:
        draw.text((inner_left, cursor), line, font=_font(27), fill=(88, 88, 100))
        cursor += 38

    draw.text((inner_left, PANEL_BOX[3] - 44), "输入「宠物面板」随时回来看看",
              font=_font(21), fill=(176, 176, 188))

    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"pet_{int(time.time() * 1000)}.jpg"
    canvas.convert("RGB").save(path, "JPEG", quality=90)
    return path
