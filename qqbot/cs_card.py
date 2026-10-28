"""把 CS2 赛事 / 赛果画成图（Pillow）。

版式照抄 NapCat 版 cs2radar 的三张 HTML 卡片（`matches.html` / `events.html` /
`match_results.html`）：深色底、圆角卡、顶部细色条、日期 / 赛事标签、队徽、
比分块、状态胶囊。官方版没有 htmlrender，这里用 Pillow 按同样的尺寸和配色重画。

三张图：
    render_matches_card(matches, out_dir)  赛程预告（按日期+赛事分组）
    render_events_card(events, out_dir)    S/A 级赛事列表
    render_results_card(matches, out_dir)  赛果（按日期+赛事分组，标胜负）

**Pillow 是可选依赖**：handler 里 import 失败就退回文字版（见 `_handle_cs`）。
"""
from __future__ import annotations

import datetime
import functools
import io
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from .base import fetch_bytes, log


# --------------------------------------------------------------------------
# 版式常量（1x；实际按 SCALE 放大后再缩回去，文字更清楚）
# --------------------------------------------------------------------------

WIDTH = 800
SCALE = 2
BODY_PAD = 20
PANEL_PAD = 30
RADIUS = 16
ROW_RADIUS = 12
ROW_H = 78
ROW_GAP = 12
EVENT_H = 86
HEADER_H = 92
GROUP_HEAD_H = 44
GROUP_GAP = 22
FOOTER_H = 58
TAG_H = 26

BG = (11, 14, 20)              # #0b0e14
PANEL = (20, 25, 33)           # #141921
TEXT_MAIN = (225, 225, 225)
TEXT_DIM = (138, 143, 152)
ACCENT = (247, 181, 0)         # 赛程 / 赛事
ACCENT_RESULT = (139, 92, 246)  # 赛果
ONGOING = (95, 252, 123)
UPCOMING = (50, 165, 253)
ENDED = (150, 150, 150)
WIN = (95, 252, 123)
LOSS = (255, 77, 77)
LOSER_NAME = (122, 127, 136)

ROW_FILL = (25, 30, 38)
ROW_EDGE = (27, 32, 40)
PANEL_EDGE = (27, 32, 40)
MAX_KEEP = 24


# --------------------------------------------------------------------------
# 小工具
# --------------------------------------------------------------------------


def _s(value: float) -> int:
    return int(round(value * SCALE))


def _blend(fg: tuple[int, int, int], bg: tuple[int, int, int],
           alpha: float) -> tuple[int, int, int]:
    return tuple(int(bg[i] + (fg[i] - bg[i]) * alpha) for i in range(3))


FONT_FILES = {
    "regular": (
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/simhei.ttf",
        "C:/Windows/Fonts/Deng.ttf",
    ),
    "bold": (
        "C:/Windows/Fonts/msyhbd.ttc",
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/simhei.ttf",
    ),
    "mono": (
        "C:/Windows/Fonts/consolab.ttf",
        "C:/Windows/Fonts/courbd.ttf",
    ),
    "emoji": ("C:/Windows/Fonts/seguiemj.ttf",),
}
_font_cache: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}
# Pillow 的字体对象不是线程安全的；两个群同时查赛事时串行画，别图快。
_render_lock = threading.Lock()


def _locked(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        with _render_lock:
            return func(*args, **kwargs)
    return wrapper


def _font(size: int, *, bold: bool = False, mono: bool = False,
          emoji: bool = False) -> ImageFont.FreeTypeFont:
    kind = "emoji" if emoji else ("mono" if mono else ("bold" if bold else "regular"))
    key = (kind, size)
    cached = _font_cache.get(key)
    if cached is not None:
        return cached
    for candidate in FONT_FILES[kind]:
        if not Path(candidate).is_file():
            continue
        try:
            font = ImageFont.truetype(candidate, _s(size))
        except OSError:
            continue
        _font_cache[key] = font
        return font
    fallback = ImageFont.load_default()
    _font_cache[key] = fallback
    return fallback


def _ellipsize(draw: ImageDraw.ImageDraw, text: str, font, limit: int) -> str:
    if limit <= 0 or draw.textlength(text, font=font) <= limit:
        return text
    trimmed = text
    while trimmed and draw.textlength(trimmed + "…", font=font) > limit:
        trimmed = trimmed[:-1]
    return (trimmed + "…") if trimmed else "…"


def _text(draw: ImageDraw.ImageDraw, x: float, baseline: float, text: str,
          font, fill, anchor: str = "ls") -> None:
    draw.text((_s(x), _s(baseline)), text, font=font, fill=fill, anchor=anchor)


def _emoji_text(draw: ImageDraw.ImageDraw, x: float, baseline: float,
                emoji: str, text: str, font, fill,
                emoji_size: int | None = None, gap: float = 7) -> float:
    """先画 emoji（彩色字体），再画文字；返回文字结束的 x（1x 坐标）。"""
    if emoji:
        efont = _font(emoji_size or 26, emoji=True)
        try:
            draw.text((_s(x), _s(baseline)), emoji, font=efont,
                      anchor="ls", embedded_color=True)
            x += efont.getlength(emoji) / SCALE + gap
        except Exception:  # noqa: BLE001 - 彩色 emoji 画不出来不影响正文
            x += gap
    draw.text((_s(x), _s(baseline)), text, font=font, fill=fill, anchor="ls")
    return x + font.getlength(text) / SCALE


def _status_style(status: str) -> tuple[str, tuple[int, int, int]]:
    if status == "live":
        return "进行中", ONGOING
    if status == "finished":
        return "已结束", ENDED
    return "未开始", UPCOMING


def _status_pill(draw: ImageDraw.ImageDraw, right: float, top: float,
                 status: str, font) -> None:
    label, color = _status_style(status)
    width = font.getlength(label) / SCALE + 20
    height = 22
    left = right - width
    draw.rounded_rectangle(
        (_s(left), _s(top), _s(right), _s(top + height)),
        radius=_s(6), fill=_blend(color, ROW_FILL, 0.15),
        outline=_blend(color, ROW_FILL, 0.2), width=_s(1),
    )
    draw.text(
        (_s((left + right) / 2), _s(top + height / 2 + 1)), label,
        font=font, fill=color, anchor="mm",
    )


def _tag(draw: ImageDraw.ImageDraw, x: float, y: float, text: str, font,
         color: tuple[int, int, int], max_width: int,
         bg_alpha: float = 0.1, edge_alpha: float = 0.15) -> float:
    """画一个圆角标签，返回它右边缘的 x（1x 坐标）。"""
    text = _ellipsize(draw, text, font, max_width - _s(20))
    width = textwidth(draw, text, font) + 20
    draw.rounded_rectangle(
        (_s(x), _s(y), _s(x + width), _s(y + TAG_H)),
        radius=_s(6), fill=_blend(color, PANEL, bg_alpha),
        outline=_blend(color, PANEL, edge_alpha), width=_s(1),
    )
    draw.text((_s(x + width / 2), _s(y + TAG_H / 2 + 1)), text,
              font=font, fill=color, anchor="mm")
    return x + width


def textwidth(draw: ImageDraw.ImageDraw, text: str, font) -> float:
    return draw.textlength(text, font=font) / SCALE


def _gradient_bar(panel: Image.Image, color: tuple[int, int, int]) -> None:
    """容器顶部那条从主色渐变到透明的细线（靠圆角遮罩裁掉两端）。"""
    width, height = panel.size
    bar_h = max(1, _s(4))
    bar = Image.new("RGB", (width, bar_h))
    pixels = bar.load()
    fade = max(width * 0.45, 1)
    for x in range(width):
        ratio = max(0.0, 1.0 - x / fade)
        color_now = tuple(int(PANEL[i] + (color[i] - PANEL[i]) * ratio) for i in range(3))
        for y in range(bar_h):
            pixels[x, y] = color_now
    mask = Image.new("L", (width, bar_h), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (-_s(RADIUS), 0, width + _s(RADIUS), bar_h + _s(RADIUS) * 2),
        radius=_s(RADIUS), fill=255,
    )
    panel.paste(bar, (0, 0), mask)


def _panel(height: int, color: tuple[int, int, int]) -> Image.Image:
    panel = Image.new("RGBA", (_s(WIDTH - BODY_PAD * 2), _s(height)), (0, 0, 0, 0))
    draw = ImageDraw.Draw(panel)
    draw.rounded_rectangle(
        (0, 0, panel.width - 1, panel.height - 1),
        radius=_s(RADIUS), fill=PANEL, outline=PANEL_EDGE, width=_s(1),
    )
    _gradient_bar(panel, color)
    return panel


def _finish(panel: Image.Image, height: int, out_dir: Path, kind: str) -> Path:
    """套圆角遮罩 → 贴到深色画布 → 缩回 800 宽 → 存图。"""
    mask = Image.new("L", panel.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, panel.width - 1, panel.height - 1), radius=_s(RADIUS), fill=255,
    )
    panel.putalpha(Image.composite(panel.getchannel("A"), Image.new("L", panel.size, 0), mask))
    canvas = Image.new("RGB", (_s(WIDTH), _s(height)), BG)
    canvas.paste(panel, (_s(BODY_PAD), _s(BODY_PAD)), panel)
    final = canvas.resize((WIDTH, int(canvas.height / SCALE)), Image.LANCZOS)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    path = out_dir / f"cs_{kind}_{stamp}.png"
    final.save(path, format="PNG", optimize=True)
    _cleanup(out_dir)
    log(f"[CS图] 已渲染：{path}（{final.width}×{final.height}）")
    return path


def _cleanup(directory: Path) -> None:
    try:
        files = sorted(directory.glob("cs_*.png"), key=lambda p: p.stat().st_mtime)
    except OSError:
        return
    for stale in files[:-MAX_KEEP]:
        try:
            stale.unlink()
        except OSError:
            pass


# --------------------------------------------------------------------------
# 队徽
# --------------------------------------------------------------------------

_LOGO_CACHE: dict[str, Image.Image | None] = {}


def _fetch_logo(url: str) -> Image.Image | None:
    if not url:
        return None
    if url in _LOGO_CACHE:
        return _LOGO_CACHE[url]
    image = None
    try:
        data = fetch_bytes(url, timeout=6)
        image = Image.open(io.BytesIO(data)).convert("RGBA")
        image.thumbnail((_s(36), _s(36)), Image.LANCZOS)
    except Exception as error:  # noqa: BLE001 - 队徽拉不到就画首字母
        log(f"[CS图] 队徽下载失败：{error!r}")
        image = None
    if len(_LOGO_CACHE) > 400:
        _LOGO_CACHE.clear()
    _LOGO_CACHE[url] = image
    return image


def _prefetch(urls: list[str]) -> None:
    unique = [url for url in dict.fromkeys(urls) if url and url not in _LOGO_CACHE]
    if not unique:
        return
    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(_fetch_logo, unique))
    except Exception as error:  # noqa: BLE001 - 预取失败就逐个用兜底
        log(f"[CS图] 队徽预取失败：{error!r}")


def _place_logo(panel: Image.Image, draw: ImageDraw.ImageDraw, x: float, y: float,
                url: str, team: str, *, dim: bool = False) -> None:
    size = 36
    box = (_s(x), _s(y), _s(x + size), _s(y + size))
    image = _fetch_logo(url) if url else None
    if image is None:
        draw.rounded_rectangle(
            box, radius=_s(8), fill=(34, 39, 47), outline=(44, 50, 60), width=_s(1),
        )
        initial = (team or "?")[:1]
        draw.text(
            (_s(x + size / 2), _s(y + size / 2 + 1)), initial,
            font=_font(16, bold=True), fill=TEXT_DIM, anchor="mm",
        )
        return
    if dim:
        image = ImageOps.grayscale(image).convert("RGBA")
        alpha = image.getchannel("A").point(lambda value: int(value * 0.45))
        image.putalpha(alpha)
    left = _s(x) + (_s(size) - image.width) // 2
    top = _s(y) + (_s(size) - image.height) // 2
    panel.alpha_composite(image, (left, top))


# --------------------------------------------------------------------------
# 分组
# --------------------------------------------------------------------------


def _match_rows(matches, limit: int = 12) -> list:
    """赛程图的行：进行中优先，其余按日期/赛事/时间排，TBD 占位不画。"""
    live = sorted((m for m in matches if m.status == "live"), key=lambda m: m.start)
    upcoming = [
        m for m in matches
        if m.status == "upcoming" and not (m.team1 == "TBD" and m.team2 == "TBD")
    ]
    upcoming.sort(key=lambda m: (m.start.strftime("%m-%d"), m.tournament, m.start))
    rows = live[:5] + upcoming
    return rows[:limit]


def _result_rows(matches, limit: int = 12) -> list:
    finished = [m for m in matches if m.status == "finished"]
    finished.sort(key=lambda m: (m.start.strftime("%m-%d"), m.tournament, m.start),
                  reverse=True)
    return finished[:limit]


def _groups(rows) -> list[tuple[tuple[str, str], list]]:
    groups: list[tuple[tuple[str, str], list]] = []
    for match in rows:
        key = (match.start.strftime("%m-%d"), match.tournament or "未知赛事")
        if groups and groups[-1][0] == key:
            groups[-1][1].append(match)
        else:
            groups.append((key, [match]))
    return groups


def _winner_side(match) -> int:
    try:
        left, right = int(match.score1), int(match.score2)
    except (TypeError, ValueError):
        return 0
    if left > right:
        return 1
    if right > left:
        return 2
    return 0


# --------------------------------------------------------------------------
# 赛程 / 赛事 / 赛果
# --------------------------------------------------------------------------


def _draw_header(draw: ImageDraw.ImageDraw, width: int, emoji: str, title: str,
                 source: str, *, title_size: int = 28) -> None:
    _emoji_text(draw, PANEL_PAD, PANEL_PAD + 30, emoji, title,
                _font(title_size, bold=True), TEXT_MAIN, emoji_size=title_size - 2)
    draw.text(
        (_s(width - PANEL_PAD), _s(PANEL_PAD + 30)), source,
        font=_font(14), fill=TEXT_DIM, anchor="rs",
    )
    y = PANEL_PAD + 58
    draw.line(
        (_s(PANEL_PAD), _s(y), _s(width - PANEL_PAD), _s(y)),
        fill=PANEL_EDGE, width=_s(1),
    )


def _draw_group_title(draw: ImageDraw.ImageDraw, y: float, date: str,
                      tournament: str, color: tuple[int, int, int]) -> None:
    x = PANEL_PAD
    f_tag = _font(13, bold=True)
    right = _tag(draw, x, y, date, f_tag, color, 140)
    _tag(draw, right + 10, y, tournament, _font(13, bold=True), TEXT_MAIN, 500,
         bg_alpha=0.05, edge_alpha=0.05)


def _draw_match_row(panel: Image.Image, draw: ImageDraw.ImageDraw, y: float,
                    match) -> None:
    x0, x1 = PANEL_PAD, WIDTH - BODY_PAD * 2 - PANEL_PAD
    draw.rounded_rectangle(
        (_s(x0), _s(y), _s(x1), _s(y + ROW_H)),
        radius=_s(ROW_RADIUS), fill=ROW_FILL, outline=ROW_EDGE, width=_s(1),
    )
    mid = y + ROW_H / 2

    # 时间 / 赛制
    _text(draw, x0 + 64, y + 34, match.start.strftime("%H:%M"),
          _font(20, mono=True, bold=True), TEXT_MAIN, anchor="ms")
    _text(draw, x0 + 64, y + 54, match.best_of or "BO3",
          _font(11, bold=True), TEXT_DIM, anchor="ms")
    draw.line(
        (_s(x0 + 134), _s(y + 16), _s(x0 + 134), _s(y + ROW_H - 16)),
        fill=ROW_EDGE, width=_s(1),
    )

    # 比分块（未开始显示 --:--，和 NapCat 版一致）
    upcoming = match.status == "upcoming"
    score_text = "--:--" if upcoming else f"{match.score1}:{match.score2}"
    score_color = TEXT_DIM if upcoming else ACCENT
    teams_left, teams_right = x0 + 154, x1 - 120
    score_w, score_h = 90, 40
    score_left = teams_left + (teams_right - teams_left - score_w) / 2
    score_top = mid - score_h / 2
    draw.rounded_rectangle(
        (_s(score_left), _s(score_top), _s(score_left + score_w), _s(score_top + score_h)),
        radius=_s(10), fill=(10, 13, 18), outline=(38, 44, 54), width=_s(1),
    )
    _text(draw, score_left + score_w / 2, mid + 7, score_text,
          _font(20, mono=True, bold=True), score_color, anchor="ms")

    # 左队：名字右对齐 + 队徽贴比分
    logo_size = 36
    left_logo_x = score_left - 14 - logo_size
    right_logo_x = score_left + score_w + 14
    _place_logo(panel, draw, left_logo_x, mid - logo_size / 2, match.logo1, match.team1)
    _place_logo(panel, draw, right_logo_x, mid - logo_size / 2, match.logo2, match.team2)
    name_limit = _s(100)
    f_team = _font(15, bold=True)
    left_name = _ellipsize(draw, match.team1, f_team, name_limit)
    right_name = _ellipsize(draw, match.team2, f_team, name_limit)
    _text(draw, left_logo_x - 12, mid + 5, left_name, f_team, TEXT_MAIN, anchor="rs")
    _text(draw, right_logo_x + logo_size + 12, mid + 5, right_name, f_team,
          TEXT_MAIN, anchor="ls")

    # 状态 + 赛事名（右侧）
    status_right = x1 - 20
    _status_pill(draw, status_right, y + 15, match.status, _font(11, bold=True))
    tournament = _ellipsize(draw, match.tournament, _font(11), _s(100))
    _text(draw, status_right, y + 54, tournament, _font(11), TEXT_DIM, anchor="rs")


def _draw_result_row(panel: Image.Image, draw: ImageDraw.ImageDraw, y: float,
                     match) -> None:
    x0, x1 = PANEL_PAD, WIDTH - BODY_PAD * 2 - PANEL_PAD
    draw.rounded_rectangle(
        (_s(x0), _s(y), _s(x1), _s(y + ROW_H)),
        radius=_s(ROW_RADIUS), fill=ROW_FILL, outline=ROW_EDGE, width=_s(1),
    )
    mid = y + ROW_H / 2
    winner = _winner_side(match)

    _text(draw, x0 + 64, y + 34, match.start.strftime("%H:%M"),
          _font(20, mono=True, bold=True), TEXT_MAIN, anchor="ms")
    _text(draw, x0 + 64, y + 54, match.best_of or "BO3",
          _font(11, bold=True), TEXT_DIM, anchor="ms")
    draw.line(
        (_s(x0 + 134), _s(y + 16), _s(x0 + 134), _s(y + ROW_H - 16)),
        fill=ROW_EDGE, width=_s(1),
    )

    box_left = x1 - 140
    teams_left, teams_right = x0 + 154, box_left
    score_w, score_h = 90, 40
    score_left = teams_left + (teams_right - teams_left - score_w) / 2
    score_top = mid - score_h / 2
    draw.rounded_rectangle(
        (_s(score_left), _s(score_top), _s(score_left + score_w), _s(score_top + score_h)),
        radius=_s(10), fill=(10, 13, 18), outline=(38, 44, 54), width=_s(1),
    )
    left_score_color = WIN if winner == 1 else (LOSS if winner == 2 else TEXT_MAIN)
    right_score_color = WIN if winner == 2 else (LOSS if winner == 1 else TEXT_MAIN)
    _text(draw, score_left + score_w / 2 - 5, mid + 7, match.score1,
          _font(20, mono=True, bold=True), left_score_color, anchor="rs")
    _text(draw, score_left + score_w / 2, mid + 7, ":",
          _font(16, mono=True, bold=True), TEXT_DIM, anchor="ms")
    _text(draw, score_left + score_w / 2 + 5, mid + 7, match.score2,
          _font(20, mono=True, bold=True), right_score_color, anchor="ls")

    logo_size = 36
    left_logo_x = score_left - 14 - logo_size
    right_logo_x = score_left + score_w + 14
    _place_logo(panel, draw, left_logo_x, mid - logo_size / 2, match.logo1,
                match.team1, dim=winner == 2)
    _place_logo(panel, draw, right_logo_x, mid - logo_size / 2, match.logo2,
                match.team2, dim=winner == 1)
    name_limit = _s(94)
    f_team = _font(15, bold=True)
    left_name = _ellipsize(draw, match.team1, f_team, name_limit)
    right_name = _ellipsize(draw, match.team2, f_team, name_limit)
    left_color = TEXT_MAIN if winner != 2 else LOSER_NAME
    right_color = TEXT_MAIN if winner != 1 else LOSER_NAME
    _text(draw, left_logo_x - 12, mid + 5, left_name, f_team, left_color, anchor="rs")
    _text(draw, right_logo_x + logo_size + 12, mid + 5, right_name, f_team,
          right_color, anchor="ls")

    # 胜方
    draw.line(
        (_s(box_left), _s(y + 16), _s(box_left), _s(y + ROW_H - 16)),
        fill=ROW_EDGE, width=_s(1),
    )
    _text(draw, x1 - 20, y + 30, "胜方", _font(11), TEXT_DIM, anchor="rs")
    winner_name = match.team1 if winner == 1 else (match.team2 if winner == 2 else "平局")
    winner_color = WIN if winner else ENDED
    winner_name = _ellipsize(draw, winner_name, _font(14, bold=True), _s(110))
    _text(draw, x1 - 20, y + 53, winner_name, _font(14, bold=True),
          winner_color, anchor="rs")


def _draw_footer(draw: ImageDraw.ImageDraw, width: int, y: float,
                 now: datetime.datetime) -> None:
    draw.line(
        (_s(PANEL_PAD), _s(y), _s(width - PANEL_PAD), _s(y)),
        fill=PANEL_EDGE, width=_s(1),
    )
    draw.text(
        (_s(width / 2), _s(y + 20)), f"Generated by qqchatbot • {now:%Y-%m-%d %H:%M}",
        font=_font(11), fill=TEXT_DIM, anchor="ms",
    )


def _matches_height(groups) -> int:
    inner = HEADER_H + GROUP_GAP
    for _, rows in groups:
        inner += GROUP_HEAD_H + len(rows) * ROW_H + (len(rows) - 1) * ROW_GAP + GROUP_GAP
    inner += FOOTER_H
    return inner + PANEL_PAD * 2


def _events_height(count: int) -> int:
    inner = HEADER_H + GROUP_GAP + count * EVENT_H + (count - 1) * ROW_GAP + FOOTER_H
    return inner + PANEL_PAD * 2


@_locked
def render_matches_card(matches, out_dir: Path,
                        now: datetime.datetime | None = None) -> Path | None:
    rows = _match_rows(matches)
    if not rows:
        return None
    now = now or datetime.datetime.now()
    groups = _groups(rows)
    height = _matches_height(groups)
    panel = _panel(height, ACCENT)
    draw = ImageDraw.Draw(panel)
    width = panel.width / SCALE
    _draw_header(draw, width, "📅", "CS2 职业赛程预告", "数据源: 5EPlay")

    _prefetch([url for match in rows for url in (match.logo1, match.logo2)])
    y = HEADER_H + GROUP_GAP
    for (date, tournament), group_rows in groups:
        _draw_group_title(draw, y, date, tournament, ACCENT)
        y += GROUP_HEAD_H
        for index, match in enumerate(group_rows):
            _draw_match_row(panel, draw, y, match)
            y += ROW_H
            if index != len(group_rows) - 1:
                y += ROW_GAP
        y += GROUP_GAP
    _draw_footer(draw, width, height - PANEL_PAD - FOOTER_H + 18, now)
    return _finish(panel, height, out_dir, "matches")


@_locked
def render_results_card(matches, out_dir: Path,
                        now: datetime.datetime | None = None) -> Path | None:
    rows = _result_rows(matches)
    if not rows:
        return None
    now = now or datetime.datetime.now()
    groups = _groups(rows)
    height = _matches_height(groups)
    panel = _panel(height, ACCENT_RESULT)
    draw = ImageDraw.Draw(panel)
    width = panel.width / SCALE
    _draw_header(draw, width, "🏁", "CS2 赛果速览", "数据源: 5EPlay")

    _prefetch([url for match in rows for url in (match.logo1, match.logo2)])
    y = HEADER_H + GROUP_GAP
    for (date, tournament), group_rows in groups:
        _draw_group_title(draw, y, date, tournament, ACCENT_RESULT)
        y += GROUP_HEAD_H
        for index, match in enumerate(group_rows):
            _draw_result_row(panel, draw, y, match)
            y += ROW_H
            if index != len(group_rows) - 1:
                y += ROW_GAP
        y += GROUP_GAP
    _draw_footer(draw, width, height - PANEL_PAD - FOOTER_H + 18, now)
    return _finish(panel, height, out_dir, "results")


@_locked
def render_events_card(events, out_dir: Path,
                       now: datetime.datetime | None = None) -> Path | None:
    rows = list(events)[:6]
    if not rows:
        return None
    now = now or datetime.datetime.now()
    height = _events_height(len(rows))
    panel = _panel(height, ACCENT)
    draw = ImageDraw.Draw(panel)
    width = panel.width / SCALE
    _draw_header(draw, width, "🏆", "Major & Professional Events",
                 "POWERED BY 5EPLAY ARENA", title_size=26)

    y = HEADER_H + GROUP_GAP
    for event in rows:
        x0 = PANEL_PAD
        draw.rounded_rectangle(
            (_s(x0), _s(y), _s(width - PANEL_PAD), _s(y + EVENT_H)),
            radius=_s(ROW_RADIUS), fill=ROW_FILL, outline=ROW_EDGE, width=_s(1),
        )
        is_s = event.grade == "S级"
        tier_color = (255, 77, 77) if is_s else ACCENT
        tier_letter = "S" if is_s else "A"
        draw.rounded_rectangle(
            (_s(x0 + 24), _s(y + 18), _s(x0 + 74), _s(y + 68)),
            radius=_s(10), fill=_blend(tier_color, ROW_FILL, 0.15),
            outline=_blend(tier_color, ROW_FILL, 0.3), width=_s(1),
        )
        draw.text(
            (_s(x0 + 49), _s(y + 43)), tier_letter,
            font=_font(22, bold=True), fill=tier_color, anchor="mm",
        )
        title = _ellipsize(draw, event.name, _font(18, bold=True), _s(430))
        _text(draw, x0 + 94, y + 36, title, _font(18, bold=True), TEXT_MAIN)
        when = event.start_date
        if event.end_date and event.end_date != event.start_date:
            when = f"{event.start_date}~{event.end_date}"
        f_meta = _font(13)
        meta_x = _emoji_text(draw, x0 + 94, y + 62, "📅",
                             _ellipsize(draw, when or "TBD", f_meta, _s(100)),
                             f_meta, TEXT_DIM, emoji_size=13)
        meta_x = _emoji_text(draw, meta_x + 16, y + 62, "📍",
                             _ellipsize(draw, event.city or "Online", f_meta, _s(170)),
                             f_meta, TEXT_DIM, emoji_size=13)
        if event.prize:
            _emoji_text(draw, meta_x + 16, y + 62, "💰",
                        _ellipsize(draw, event.prize, f_meta, _s(140)),
                        f_meta, TEXT_DIM, emoji_size=13)

        status_right = width - PANEL_PAD - 24
        _status_right_pill(draw, status_right, y + (EVENT_H - 22) / 2, event.status,
                           _font(11, bold=True))
        y += EVENT_H + ROW_GAP
    _draw_footer(draw, width, height - PANEL_PAD - FOOTER_H + 18, now)
    return _finish(panel, height, out_dir, "events")


def _status_right_pill(draw: ImageDraw.ImageDraw, right: float, top: float,
                       status: str, font) -> None:
    """赛事卡的状态胶囊（文案用「进行中 / 即将开始 / 已结束」）。"""
    label = {"live": "进行中", "upcoming": "即将开始"}.get(status, "已结束")
    color = {"live": ONGOING, "upcoming": UPCOMING}.get(status, ENDED)
    width = font.getlength(label) / SCALE + 28
    left = right - width
    draw.rounded_rectangle(
        (_s(left), _s(top), _s(right), _s(top + 22)),
        radius=_s(11), fill=_blend(color, ROW_FILL, 0.1),
        outline=_blend(color, ROW_FILL, 0.2), width=_s(1),
    )
    draw.text((_s((left + right) / 2), _s(top + 12)), label,
              font=font, fill=color, anchor="mm")
