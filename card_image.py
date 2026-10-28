"""把「查看库存」画成一张图（Pillow）。

从原插件 `checkin_card.render_inventory_card` 的版式里搬了骨架：淡紫渐变底、
白色圆角卡、顶部头像 + 标题、按档位分组的网格、底部奶龙碎片。做了两处简化：

* 尺寸写死一套，不再做 2100px + SCALE 的等比放大（群里看 1600px 已经够清楚）；
* 不再画背景照片，只用渐变 —— 库存是查资料，不需要氛围图。

**Pillow 是可选依赖**：这个模块只在真的渲染时才被导入，没装 Pillow 时
`official_bot` 会退回纯文字版库存（见 `Handler._handle_cards`）。
"""
from __future__ import annotations

import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

WIDTH = 1600
MARGIN = 48
PAD = 28
HEADER_H = 170
GROUP_H = 64
TILE_H = 92
GAP = 16
COLUMNS = 4
SHARDS_H = 130
FOOTER_H = 56
MAX_KEEP = 20

BG_TOP = (247, 243, 248)
BG_BOTTOM = (238, 238, 246)
PANEL = (255, 255, 255)
PANEL_EDGE = (229, 224, 234)
TILE_FILL = (250, 247, 251)
TILE_EDGE = (240, 234, 242)
TEXT_MAIN = (52, 44, 60)
TEXT_SUB = (140, 132, 150)
TEXT_FAINT = (176, 168, 186)
ACCENT = (211, 68, 122)
ACCENT_SOFT = (253, 236, 244)

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
_font_cache: dict[tuple[bool, int], ImageFont.FreeTypeFont] = {}


def _font(size: int, *, bold: bool = False) -> ImageFont.ImageFont:
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
    except TypeError:  # 老 Pillow 的 load_default 不收 size
        fallback = ImageFont.load_default()
    _font_cache[key] = fallback
    return fallback


def _gradient(size: tuple[int, int]) -> Image.Image:
    width, height = size
    strip = Image.new("RGB", (1, height))
    pixels = strip.load()
    for y in range(height):
        ratio = y / max(height - 1, 1)
        pixels[0, y] = tuple(
            int(BG_TOP[index] + (BG_BOTTOM[index] - BG_TOP[index]) * ratio)
            for index in range(3)
        )
    return strip.resize((width, height))


def _panel(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int],
           *, fill=PANEL, edge=PANEL_EDGE, radius: int = 22) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=edge, width=2)


def _ellipsize(draw: ImageDraw.ImageDraw, text: str, font, limit: int) -> str:
    """太长就中间截断加省略号，宁可少几个字也不溢出格子。"""
    if draw.textlength(text, font=font) <= limit:
        return text
    trimmed = text
    while trimmed and draw.textlength(trimmed + "…", font=font) > limit:
        trimmed = trimmed[:-1]
    return (trimmed + "…") if trimmed else "…"


def _cleanup(directory: Path) -> None:
    try:
        files = sorted(directory.glob("inv_*.jpg"), key=lambda p: p.stat().st_mtime)
    except OSError:
        return
    for stale in files[:-MAX_KEEP]:
        try:
            stale.unlink()
        except OSError:
            pass


def render_inventory_card(
    *,
    groups: list[tuple[str, tuple[int, int, int], list[str]]],
    shards: int,
    total_cards: int,
    username: str,
    show_all: bool,
    out_dir: Path,
    today: datetime.date | None = None,
) -> Path | None:
    """画一张库存图，返回文件路径；画不出来返回 ``None``（调用方退回文字）。"""
    if not groups:
        return None
    today = today or datetime.date.today()
    name = (username or "群友").strip()

    rows_per_group = [
        max(1, (len(names) + COLUMNS - 1) // COLUMNS) for _, _, names in groups
    ]
    grid_height = sum(
        GROUP_H + rows * (TILE_H + GAP) + 12
        for rows in rows_per_group
    )
    height = (
        MARGIN * 2 + HEADER_H + 24 + grid_height + 24 + SHARDS_H + FOOTER_H
    )
    canvas = _gradient((WIDTH, height))
    draw = ImageDraw.Draw(canvas)

    # ---- 顶部：头像 + 标题 + 张数
    header = (MARGIN, MARGIN, WIDTH - MARGIN, MARGIN + HEADER_H)
    _panel(draw, header)
    avatar = 96
    avatar_top = MARGIN + (HEADER_H - avatar) // 2
    draw.ellipse(
        (MARGIN + PAD, avatar_top, MARGIN + PAD + avatar, avatar_top + avatar),
        fill=ACCENT_SOFT, outline=(246, 216, 230), width=2,
    )
    draw.text(
        (MARGIN + PAD + avatar / 2, avatar_top + avatar / 2),
        name[0], font=_font(44, bold=True), fill=ACCENT, anchor="mm",
    )
    text_left = MARGIN + PAD + avatar + 24
    draw.text(
        (text_left, MARGIN + 30),
        "全部库存" if show_all else "查看库存",
        font=_font(36, bold=True), fill=TEXT_MAIN,
    )
    draw.text(
        (text_left, MARGIN + 92),
        f"{name} · {today.strftime('%Y-%m-%d')}",
        font=_font(24), fill=TEXT_SUB,
    )
    draw.text(
        (WIDTH - MARGIN - PAD, MARGIN + HEADER_H / 2),
        f"{total_cards:,} 张卡",
        font=_font(28, bold=True), fill=ACCENT, anchor="rm",
    )

    # ---- 中间：按档位分组的格子
    content_width = WIDTH - MARGIN * 2
    tile_width = (content_width - GAP * (COLUMNS - 1)) // COLUMNS
    y = MARGIN + HEADER_H + 24
    for index, (label, color, names) in enumerate(groups):
        draw.rounded_rectangle(
            (MARGIN, y + 18, MARGIN + 10, y + 42), radius=5, fill=color,
        )
        draw.text(
            (MARGIN + 22, y + 10), label,
            font=_font(30, bold=True), fill=TEXT_MAIN,
        )
        draw.text(
            (WIDTH - MARGIN, y + 20), f"{len(names)} 种",
            font=_font(22), fill=TEXT_FAINT, anchor="ra",
        )
        y += GROUP_H
        name_font = _font(26)
        for position, card_name in enumerate(names):
            column = position % COLUMNS
            row = position // COLUMNS
            left = MARGIN + column * (tile_width + GAP)
            top = y + row * (TILE_H + GAP)
            _panel(draw, (left, top, left + tile_width, top + TILE_H),
                   fill=TILE_FILL, edge=TILE_EDGE, radius=14)
            draw.rounded_rectangle(
                (left + 12, top + TILE_H / 2 - 10, left + 18, top + TILE_H / 2 + 10),
                radius=3, fill=color,
            )
            draw.text(
                (left + 34, top + TILE_H / 2),
                _ellipsize(draw, card_name, name_font, tile_width - 52),
                font=name_font, fill=TEXT_MAIN, anchor="lm",
            )
        y += rows_per_group[index] * (TILE_H + GAP) + 12

    # ---- 底部：奶龙碎片
    shards_box = (MARGIN, height - MARGIN - FOOTER_H - SHARDS_H,
                  WIDTH - MARGIN, height - MARGIN - FOOTER_H)
    _panel(draw, shards_box)
    draw.text(
        (MARGIN + PAD + 6, shards_box[1] + 34), "奶龙碎片",
        font=_font(26), fill=TEXT_SUB,
    )
    draw.text(
        (MARGIN + PAD + 6, shards_box[1] + 70), f"*{shards:,}",
        font=_font(48, bold=True), fill=ACCENT,
    )
    draw.text(
        (WIDTH - MARGIN - PAD, shards_box[1] + SHARDS_H / 2),
        "重复卡会折成碎片，攒够 500 就能开箱。",
        font=_font(22), fill=TEXT_FAINT, anchor="rm",
    )

    # ---- 页脚
    draw.text(
        (WIDTH / 2, height - MARGIN - FOOTER_H / 2),
        "想看缺哪张就去翻卡池吧。",
        font=_font(20), fill=TEXT_FAINT, anchor="mm",
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"inv_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}_{total_cards}.jpg"
    try:
        canvas.convert("RGB").save(target, "JPEG", quality=92)
    except OSError:
        return None
    _cleanup(out_dir)
    return target


# --------------------------------------------------------------------------
# 签到图
# --------------------------------------------------------------------------


def _fit_picture(path, box_size, backdrop=TILE_FILL):
    """把图片完整缩进框里（不裁切），空出来的地方铺底色。"""
    width, height = box_size
    canvas = Image.new("RGB", (width, height), backdrop)
    try:
        with Image.open(path) as opened:
            image = opened.convert("RGB")
            image = ImageOps.contain(image, (width, height), Image.LANCZOS)
    except (OSError, ValueError):
        return canvas
    canvas.paste(image, ((width - image.width) // 2, (height - image.height) // 2))
    return canvas


def render_checkin_card(
    *,
    username: str,
    drawn: list[str],
    shard_gain: int,
    shard_total: int,
    first_check_in: bool,
    luck_name: str | None,
    luck_path=None,
    luck_flavor: str,
    luck_advice: tuple[str, str],
    wife_path,
    wife_name: str | None,
    out_dir,
    today=None,
):
    """画签到图：左边今日老婆，右边抽卡结果 + 奶龙碎片 + 今日运势。"""
    today = today or datetime.date.today()
    name = (username or "群友").strip()
    drawn = drawn or []

    left_width = 700
    right_width = WIDTH - MARGIN * 2 - GAP - left_width
    # 画框高度跟着图片比例走：横图别再塞进竖框，否则上下两大片空白
    frame_width = left_width - PAD * 2
    frame_height = 700
    if wife_path is not None:
        try:
            with Image.open(str(wife_path)) as opened:
                image_w, image_h = opened.size
            if image_w > 0:
                frame_height = max(320, min(700, round(frame_width * image_h / image_w)))
        except OSError:
            pass
    wife_box = (frame_width, frame_height)
    drawn_columns = 3
    drawn_tile_h = 64
    drawn_rows = max(1, (len(drawn) + drawn_columns - 1) // drawn_columns)
    drawn_h = 96 + drawn_rows * (drawn_tile_h + 12) + 16
    shards_h = 150
    luck_h = (668 if luck_path is not None else 210) if luck_name else 0
    right_h = drawn_h + GAP + shards_h + (GAP + luck_h if luck_h else 0)
    left_h = 96 + wife_box[1] + 60
    body_h = max(left_h, right_h)
    height = MARGIN * 2 + HEADER_H + 24 + body_h + FOOTER_H
    canvas = _gradient((WIDTH, height))
    draw = ImageDraw.Draw(canvas)

    # 顶部：头像 + 标题 + 日期
    header = (MARGIN, MARGIN, WIDTH - MARGIN, MARGIN + HEADER_H)
    _panel(draw, header)
    avatar = 96
    avatar_top = MARGIN + (HEADER_H - avatar) // 2
    draw.ellipse(
        (MARGIN + PAD, avatar_top, MARGIN + PAD + avatar, avatar_top + avatar),
        fill=ACCENT_SOFT, outline=(246, 216, 230), width=2,
    )
    draw.text(
        (MARGIN + PAD + avatar / 2, avatar_top + avatar / 2),
        name[0], font=_font(44, bold=True), fill=ACCENT, anchor="mm",
    )
    draw.text(
        (MARGIN + PAD + avatar + 24, MARGIN + 30), "签到成功",
        font=_font(36, bold=True), fill=TEXT_MAIN,
    )
    draw.text(
        (MARGIN + PAD + avatar + 24, MARGIN + 92),
        f"{name} · {today.strftime('%Y-%m-%d')}",
        font=_font(24), fill=TEXT_SUB,
    )
    draw.text(
        (WIDTH - MARGIN - PAD, MARGIN + HEADER_H / 2),
        "奶龙碎片 +" + ("%d（首次）" % shard_gain if first_check_in else "0"),
        font=_font(26, bold=True), fill=ACCENT, anchor="rm",
    )

    top = MARGIN + HEADER_H + 24
    left_box = (MARGIN, top, MARGIN + left_width, top + body_h)
    _panel(draw, left_box)
    draw.text((MARGIN + PAD, top + 26), "今日老婆", font=_font(28, bold=True), fill=TEXT_MAIN)
    if wife_name:
        draw.text(
            (MARGIN + left_width - PAD, top + 34), wife_name,
            font=_font(22), fill=TEXT_FAINT, anchor="ra",
        )
    picture = (
        _fit_picture(wife_path, wife_box) if wife_path is not None
        else Image.new("RGB", wife_box, TILE_FILL)
    )
    picture_y = top + 76
    canvas.paste(picture, (MARGIN + PAD, picture_y))
    if wife_path is None:
        draw.text(
            (MARGIN + left_width / 2, top + 76 + wife_box[1] / 2), "老婆文件夹里还没有图片",
            font=_font(24), fill=TEXT_FAINT, anchor="mm",
        )
    draw.text(
        (MARGIN + PAD, picture_y + wife_box[1] + 14),
        "早上好，今天也要加油哦。" if wife_path is not None else "放几张图进去就有了。",
        font=_font(22), fill=TEXT_FAINT,
    )

    right_left = MARGIN + left_width + GAP
    right_box = (right_left, top, WIDTH - MARGIN, top + drawn_h)
    _panel(draw, right_box)
    draw.text(
        (right_left + PAD, top + 24), "今日抽卡", font=_font(28, bold=True), fill=TEXT_MAIN,
    )
    draw.text(
        (WIDTH - MARGIN - PAD, top + 32), f"{len(drawn)} 张",
        font=_font(22), fill=TEXT_FAINT, anchor="ra",
    )
    if drawn:
        tile_gap = 12
        tile_width = (right_width - PAD * 2 - tile_gap * (drawn_columns - 1)) // drawn_columns
        for index, card_name in enumerate(drawn):
            column = index % drawn_columns
            row = index // drawn_columns
            left = right_left + PAD + column * (tile_width + tile_gap)
            tile_top = top + 92 + row * (drawn_tile_h + tile_gap)
            draw.rounded_rectangle(
                (left, tile_top, left + tile_width, tile_top + drawn_tile_h),
                radius=12, fill=TILE_FILL, outline=TILE_EDGE, width=2,
            )
            draw.text(
                (left + tile_width / 2, tile_top + drawn_tile_h / 2),
                _ellipsize(draw, card_name, _font(24), tile_width - 24),
                font=_font(24), fill=TEXT_MAIN, anchor="mm",
            )
    else:
        draw.text(
            (right_left + PAD + 6, top + 96),
            "今天已经抽完了，明天再来。", font=_font(26), fill=TEXT_SUB,
        )

    shards_top = top + drawn_h + GAP
    shards_box = (right_left, shards_top, WIDTH - MARGIN, shards_top + shards_h)
    _panel(draw, shards_box)
    draw.text(
        (right_left + PAD, shards_top + 26), "奶龙碎片",
        font=_font(24), fill=TEXT_SUB,
    )
    draw.text(
        (right_left + PAD, shards_top + 66), "*%d" % shard_total,
        font=_font(48, bold=True), fill=ACCENT,
    )
    draw.text(
        (WIDTH - MARGIN - PAD, shards_top + shards_h / 2),
        "今日 +%d" % shard_gain if first_check_in else "今天已经领过了",
        font=_font(22), fill=TEXT_FAINT, anchor="rm",
    )

    if luck_name:
        luck_top = shards_top + shards_h + GAP
        luck_box = (right_left, luck_top, WIDTH - MARGIN, luck_top + luck_h)
        _panel(draw, luck_box)
        draw.text(
            (right_left + PAD, luck_top + 24), "今日运势",
            font=_font(24), fill=TEXT_SUB,
        )
        center_x = right_left + right_width / 2
        text_left = right_left + PAD
        if luck_path is not None:
            image_box = (420, 420)
            luck_image = _fit_picture(luck_path, image_box, backdrop=PANEL)
            canvas.paste(
                luck_image,
                (int(center_x - image_box[0] / 2), luck_top + 58),
            )
            text_top = luck_top + 58 + image_box[1] + 16
        else:
            text_top = luck_top + 62
        draw.text(
            (center_x, text_top), luck_name,
            font=_font(40, bold=True), fill=ACCENT, anchor="ma",
        )
        draw.text(
            (center_x, text_top + 56),
            _ellipsize(draw, luck_flavor, _font(24), right_width - PAD * 2),
            font=_font(24), fill=TEXT_MAIN, anchor="ma",
        )
        if luck_advice:
            draw.text(
                (center_x, text_top + 98),
                "宜 " + luck_advice[0] + "    忌 " + luck_advice[1],
                font=_font(22), fill=TEXT_SUB, anchor="ma",
            )

    draw.text(
        (WIDTH / 2, height - MARGIN - FOOTER_H / 2),
        "签到会把今天剩下的抽卡次数一次用完。",
        font=_font(20), fill=TEXT_FAINT, anchor="mm",
    )

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / (
        "checkin_%s_%d.jpg"
        % (datetime.datetime.now().strftime("%Y%m%d_%H%M%S"), shard_total)
    )
    try:
        canvas.convert("RGB").save(str(target), "JPEG", quality=92)
    except OSError:
        return None
    _cleanup(out_dir)
    return target
